"""Motore comune: stessa logica per il paper trading live e per il backtest.

Un "bot" = un conto paper con il suo saldo e più "slot" (strategia x strumento).
Ogni slot può avere al massimo una posizione aperta.
Regole di rischio (pensate per FTMO 2-Step Swing):
  - rischio fisso % per trade, dimezzato se il conto è sotto il picco di oltre DD_HALVE
  - rischio aperto totale massimo MAX_OPEN_RISK (le posizioni con stop già in pari non contano)
  - stop giornaliero interno: niente nuovi trade se l'equity del giorno scende di DAILY_STOP
    (il giorno parte a mezzanotte di Praga, come FTMO)
  - niente nuovi trade da venerdì 19:00 UTC alla riapertura (regola FTMO sul gap del weekend)
  - filtro notizie: niente nuovi trade ±60 min da notizie ad alto impatto (gestito dal chiamante)
"""
import numpy as np
import pandas as pd

from strategies import trend_pullback, donchian_breakout

STRATS = {"pullback": trend_pullback, "breakout": donchian_breakout}

INSTR = {
    # yahoo, pip, costo in pip (spread+commissione), valute delle notizie che contano
    "EURUSD": dict(yahoo="EURUSD=X", oanda="EUR_USD", pip=0.0001, cost=1.3, news=("USD", "EUR")),
    "GBPUSD": dict(yahoo="GBPUSD=X", oanda="GBP_USD", pip=0.0001, cost=1.6, news=("USD", "GBP")),
    "AUDUSD": dict(yahoo="AUDUSD=X", oanda="AUD_USD", pip=0.0001, cost=1.5, news=("USD", "AUD")),
    "XAUUSD": dict(yahoo="GC=F", oanda="XAU_USD", pip=0.01, cost=40, news=("USD",)),
}

P_PULL = dict(ema_fast=20, ema_slow=200, rsi_lo=30, rsi_hi=70, sl_atr=2.5, tp_r=np.nan)
P_BRK = dict(n=10, sl_atr=2.5, tp_r=3.0)

BOTS = {
    "A": dict(desc="Pullback EURUSD (riferimento)", risk=0.01,
              slots=[("pullback", "EURUSD", P_PULL)]),
    "B": dict(desc="Pullback + breakout EURUSD", risk=0.0075,
              slots=[("pullback", "EURUSD", P_PULL), ("breakout", "EURUSD", P_BRK)]),
    "C": dict(desc="Pullback EURUSD + GBPUSD + AUDUSD", risk=0.007,
              slots=[("pullback", s, P_PULL) for s in ("EURUSD", "GBPUSD", "AUDUSD")]),
    "D": dict(desc="Pullback + breakout EURUSD + breakout oro", risk=0.0075, max_open=0.0225,
              slots=[("pullback", "EURUSD", P_PULL), ("breakout", "EURUSD", P_BRK),
                     ("breakout", "XAUUSD", P_BRK)]),
}

START = 100_000.0
MAX_OPEN_RISK = 0.015
DAILY_STOP = 0.03
DD_HALVE = 0.04
MAX_BARS = 120
TARGET, MAX_LOSS, FTMO_DAILY = 0.10, 0.10, 0.05


def slot_id(strat, sym):
    return f"{strat}:{sym}"


def signals(strat, df, params):
    return STRATS[strat](df, **params)


def prague_day(t):
    return pd.Timestamp(t).tz_convert("Europe/Prague").date().isoformat()


def new_state():
    return dict(balance=START, peak=START, positions={}, last_bar={}, day=None,
                day_start=START, challenge="in corso", challenge_end=None, errors=[], skipped=[])


class Bot:
    def __init__(self, name, state, notify=lambda m: None, on_close=lambda row: None):
        self.name, self.cfg, self.s = name, BOTS[name], state
        self.notify, self.on_close = notify, on_close
        self.last_px = {}

    # ---------- utilità ----------
    def open_risk(self, sym=None):
        r = 0.0
        for p in self.s["positions"].values():
            if sym and p["sym"] != sym:
                continue
            r += max(0.0, p["side"] * (p["entry"] - p["stop"])) / p["sl_dist"] * p["risk_usd"]
        return r

    def floating(self):
        f = 0.0
        for sid, p in self.s["positions"].items():
            px = self.last_px.get(p["sym"], p["entry"])
            f += p["side"] * (px - p["entry"]) / p["sl_dist"] * p["risk_usd"]
        return f

    def equity(self):
        return self.s["balance"] + self.floating()

    def roll_day(self, t):
        d = prague_day(t)
        if self.s["day"] != d:
            self.s["day"], self.s["day_start"] = d, self.s["balance"] + self.floating()

    # ---------- gestione posizioni ----------
    def close(self, sid, price, when, why):
        p = self.s["positions"].pop(sid)
        pip, cost = INSTR[p["sym"]]["pip"], INSTR[p["sym"]]["cost"]
        R = (p["side"] * (price - p["entry"]) - cost * pip) / p["sl_dist"]
        pnl = p["risk_usd"] * R
        self.s["balance"] += pnl
        self.s["peak"] = max(self.s["peak"], self.s["balance"])
        row = dict(bot=self.name, slot=sid, entry_time=p["entry_time"], exit_time=str(when),
                   side="LONG" if p["side"] == 1 else "SHORT", entry=round(p["entry"], 5),
                   exit=round(price, 5), sl_pips=round(p["sl_dist"] / pip, 1), R=round(R, 3),
                   pnl=round(pnl, 2), balance=round(self.s["balance"], 2), why=why)
        self.on_close(row)
        self.notify(f"{'📈' if pnl > 0 else '📉'} [{self.name}] {p['sym']} {row['side']} chiuso ({why}) "
                    f"a {row['exit']} → {R:+.2f}R, {pnl:+.0f}$ · saldo {self.s['balance']:.0f}$")
        self.check_challenge(when)

    def check_challenge(self, when):
        s = self.s
        if s["challenge"] != "in corso":
            return
        eq = self.equity()
        if eq >= START * (1 + TARGET):  # su FTMO a quel punto si chiude tutto e la fase è passata
            s["challenge"], s["challenge_end"] = "PASSATA", str(when)
            self.notify(f"🏆 [{self.name}] +10% raggiunto: fase 1 simulata PASSATA")
        elif eq <= START * (1 - MAX_LOSS) or eq <= s["day_start"] - START * FTMO_DAILY:
            s["challenge"], s["challenge_end"] = "BOCCIATA", str(when)
            self.notify(f"❌ [{self.name}] limite FTMO superato: challenge simulata BOCCIATA")

    def manage(self, sid, t, bar):
        """Aggiorna la posizione aperta di uno slot con una candela chiusa (t = apertura candela)."""
        p = self.s["positions"].get(sid)
        if not p:
            return
        side = p["side"]
        p["bars"] += 1
        end = t + pd.Timedelta(hours=1)
        if (side == 1 and bar["low"] <= p["stop"]) or (side == -1 and bar["high"] >= p["stop"]):
            px = min(bar["open"], p["stop"]) if side == 1 else max(bar["open"], p["stop"])
            return self.close(sid, px, end, "STOP")
        if p["tp"] is not None and ((side == 1 and bar["high"] >= p["tp"]) or (side == -1 and bar["low"] <= p["tp"])):
            return self.close(sid, p["tp"], end, "TARGET")
        if p["bars"] >= MAX_BARS:
            return self.close(sid, bar["close"], end, "TEMPO")
        if p["tp"] is None:  # trailing
            if side == 1:
                p["best"] = max(p["best"], bar["high"])
                p["stop"] = max(p["stop"], p["best"] - p["sl_dist"])
            else:
                p["best"] = min(p["best"], bar["low"])
                p["stop"] = min(p["stop"], p["best"] + p["sl_dist"])

    def try_enter(self, sid, sym, t, bar, entry_px, news_block=None):
        """Valuta il segnale della candela chiusa t. entry_px = prezzo d'ingresso (apertura candela dopo)."""
        sig = int(bar["signal"])
        if sig == 0 or sid in self.s["positions"] or not np.isfinite(bar["sl_dist"]) or bar["sl_dist"] <= 0:
            return
        when = t + pd.Timedelta(hours=1)
        lbl = f"{'LONG' if sig == 1 else 'SHORT'} {sym} ({sid.split(':')[0]})"
        reason = None
        wd, hr = when.weekday(), when.hour
        if (wd == 4 and hr >= 19) or wd == 5 or (wd == 6 and hr < 22):
            reason = "venerdì sera / weekend"
        elif self.equity() <= self.s["day_start"] * (1 - DAILY_STOP):
            reason = "stop giornaliero -3% raggiunto"
        elif news_block:
            reason = f"notizia: {news_block}"
        risk_pct = self.cfg["risk"] * (0.5 if self.s["balance"] < self.s["peak"] * (1 - DD_HALVE) else 1)
        risk_usd = self.s["balance"] * risk_pct
        max_open = self.cfg.get("max_open", MAX_OPEN_RISK)
        if not reason and self.open_risk() + risk_usd > self.s["balance"] * max_open + 1e-6:
            reason = f"rischio aperto totale al massimo ({max_open * 100:.2f}%)"
        elif not reason and self.open_risk(sym) + risk_usd > self.s["balance"] * MAX_OPEN_RISK + 1e-6:
            reason = f"rischio aperto su {sym} al massimo (1,5%)"
        if reason:
            self.s["skipped"].append(f"{when:%Y-%m-%d %H:%M} {lbl} saltato: {reason}")
            self.s["skipped"] = self.s["skipped"][-30:]
            if news_block:
                self.notify(f"⏸️ [{self.name}] {lbl} saltato per {reason}")
            return
        d = float(bar["sl_dist"])
        tp = entry_px + sig * float(bar["tp_dist"]) if np.isfinite(bar["tp_dist"]) else None
        pip = INSTR[sym]["pip"]
        lots = risk_usd / (d / pip * (10 if sym != "XAUUSD" else 1))  # $10/pip forex, $1 per 0.01 su 100oz
        self.s["positions"][sid] = dict(sym=sym, side=sig, entry=float(entry_px), entry_time=str(when),
                                        sl_dist=d, stop=float(entry_px) - sig * d, tp=tp, best=float(entry_px),
                                        bars=0, risk_usd=risk_usd, lots=round(lots, 2))
        self.notify(f"🟢 [{self.name}] {lbl} a {entry_px:.5g} · stop {entry_px - sig * d:.5g}"
                    f"{f' · target {tp:.5g}' if tp else ' · trailing'} · rischio {risk_usd:.0f}$ ({risk_pct * 100:.2f}%)"
                    f" · {lots:.2f} lotti")


# ---------- backtest con lo stesso motore ----------
def backtest(name, data, start=None):
    """data: {sym: DataFrame 1h}. Ritorna (trades DataFrame, state)."""
    cfg = BOTS[name]
    trades = []
    bot = Bot(name, new_state(), on_close=trades.append)
    sigs = {}
    for strat, sym, params in cfg["slots"]:
        df = signals(strat, data[sym], params)
        if start is not None:
            df = df[df.index >= start]
        sigs[slot_id(strat, sym)] = (sym, df)
    # timeline comune
    times = sorted(set().union(*[set(df.index) for _, df in sigs.values()]))
    nxt_open = {sid: df["open"].shift(-1) for sid, (sym, df) in sigs.items()}
    for t in times:
        bot.roll_day(t)
        for sid, (sym, df) in sigs.items():
            if t not in df.index:
                continue
            bar = df.loc[t]
            bot.last_px[sym] = bar["close"]
            bot.manage(sid, t, bar)
        for sid, (sym, df) in sigs.items():
            if t not in df.index:
                continue
            bar = df.loc[t]
            o = nxt_open[sid].get(t, np.nan)
            if np.isfinite(o):
                bot.try_enter(sid, sym, t, bar, o)
        bot.check_challenge(t)
    return pd.DataFrame(trades), bot.s
