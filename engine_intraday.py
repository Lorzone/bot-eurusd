"""Bot intraday (aperti e chiusi nello stesso giorno), separati dai bot swing di engine.py.

Strategia "continuazione della prima ora" (fhc): sugli indici USA, alla fine della prima ora di
borsa (09:30-10:30 New York) se il movimento della prima ora è almeno th x ATR giornaliero
(media 14 giorni del range della sessione regolare), si entra a mercato nella stessa direzione
all'apertura della candela delle 10:30; stop all'altro estremo della prima ora; nessun target;
uscita forzata alla chiusura della candela delle 15:50 (15:55 New York). Max 1 trade al giorno.

Il bot è DETERMINISTICO: a ogni giro ricalcola i trade dalle candele a 5 minuti già chiuse e li
confronta con quelli già registrati. Se un giro salta, il giro dopo ricostruisce esattamente
gli stessi ingressi, stop e uscite: il risultato paper è identico al backtest.
"""
import numpy as np
import pandas as pd

START = 100_000.0
DD_HALVE = 0.04

INTRA_BOTS = {
    "E": dict(desc="Nasdaq 100: continuazione prima ora (intraday)", risk=0.0075,
              slots=[dict(sym="NAS100", yahoo="^NDX", tz="America/New_York", open="09:30", minutes=60,
                          th=0.1, exit="15:55", cost=1.2, slip=0.1)]),
}


def _hm(s):
    h, m = s.split(":")
    return int(h) * 60 + int(m)


def fhc_trades(df, slot, now=None):
    """df: candele 5m (indice UTC = apertura candela, colonne open/high/low/close).
    Ritorna lista di trade (dict). status = 'chiuso' o 'aperto' (uscita non ancora avvenuta)."""
    tz = slot["tz"]
    o0, mins = _hm(slot["open"]), slot["minutes"]
    ex = _hm(slot["exit"])
    loc = df.index.tz_convert(tz)
    lmin = loc.hour * 60 + loc.minute
    day = loc.normalize()
    o, h, l, c = (df[k].to_numpy(float) for k in ("open", "high", "low", "close"))
    days = pd.unique(day)
    # range della sessione regolare per l'ATR (09:30-16:00)
    rng = []
    groups = {}
    for d in days:
        ix = np.flatnonzero(day == d)
        groups[d] = ix
        rix = ix[(lmin[ix] >= o0) & (lmin[ix] < _hm("16:00"))]
        rng.append(h[rix].max() - l[rix].min() if len(rix) > 12 else np.nan)
    rng = pd.Series(rng, index=days)
    atr = rng.dropna().rolling(14).mean().reindex(rng.index).ffill().shift(1)  # solo giorni precedenti
    now = now or pd.Timestamp.now(tz="UTC")
    out = []
    for d in days:
        a = atr.get(d, np.nan)
        if not np.isfinite(a):
            continue
        ix = groups[d]
        fh = ix[(lmin[ix] >= o0) & (lmin[ix] < o0 + mins)]
        if len(fh) < 0.8 * mins / 5:
            continue
        mv = c[fh[-1]] - o[fh[0]]
        if abs(mv) < slot["th"] * a:
            continue
        side = int(np.sign(mv))
        nxt = ix[(lmin[ix] >= o0 + mins) & (lmin[ix] < o0 + mins + 5)]
        if not len(nxt):
            continue
        ie = nxt[0]
        fill = o[ie]
        stop = l[fh].min() if side == 1 else h[fh].max()
        risk = abs(fill - stop)
        if side * (fill - stop) <= 0:
            continue
        body = ix[(ix >= ie) & (lmin[ix] < ex)]
        px, why, ix_exit = None, None, None
        for i in body:
            if (side == 1 and l[i] <= stop) or (side == -1 and h[i] >= stop):
                px = stop if i == ie else (min(o[i], stop) if side == 1 else max(o[i], stop))
                why, ix_exit = "STOP", i
                break
        session_end = (pd.Timestamp(d).tz_localize(None).tz_localize(tz) + pd.Timedelta(minutes=ex)).tz_convert("UTC")
        if px is None:
            # uscita alla chiusura dell'ultima candela prima delle 15:55; nei giorni a orario ridotto
            # (vigilie) la borsa chiude prima: basta che ci siano dati successivi alla fine della sessione
            ended = now >= session_end and (df.index[-1] >= session_end or
                                            df.index[body[-1]] + pd.Timedelta(minutes=5) >= session_end)
            if len(body) and ended:
                px, why, ix_exit = c[body[-1]], "FINE GIORNATA", body[-1]
        tr = dict(day=str(pd.Timestamp(d).date()), sym=slot["sym"], side=side, entry_time=str(df.index[ie]),
                  entry=float(fill), stop=float(stop), risk_pts=float(risk))
        if px is None:
            tr.update(status="aperto", last=float(c[body[-1]]) if len(body) else float(fill))
        else:
            slip = slot["slip"] * 2
            R = (side * (px - fill) - slot["cost"] - slip) / risk
            tr.update(status="chiuso", exit=float(px), exit_time=str(df.index[ix_exit] + pd.Timedelta(minutes=5)),
                      why=why, R=float(R))
        out.append(tr)
    return out


def new_state():
    return dict(balance=START, peak=START, positions={}, done_days=[], day=None, day_start=START,
                challenge="in corso", challenge_end=None, errors=[], skipped=[], last_bar={})


class IntradayBot:
    def __init__(self, name, state, notify=lambda m: None, on_close=lambda row: None):
        self.name, self.cfg, self.s = name, INTRA_BOTS[name], state
        self.notify, self.on_close = notify, on_close

    def risk_pct(self):
        return self.cfg["risk"] * (0.5 if self.s["balance"] < self.s["peak"] * (1 - DD_HALVE) else 1)

    def process(self, data, now=None):
        """data: {sym: df 5m}. Registra ingressi e uscite nuovi, in ordine di tempo."""
        s = self.s
        evs = []
        for slot in self.cfg["slots"]:
            for tr in fhc_trades(data[slot["sym"]], slot, now):
                key = f"{slot['sym']}:{tr['day']}"
                if key in s["done_days"]:
                    continue
                if pd.Timestamp(tr["entry_time"]) < pd.Timestamp(s.get("started", "2000-01-01T00:00:00+00:00")):
                    continue  # niente trade precedenti all'avvio del bot
                evs.append((key, slot, tr))
        evs.sort(key=lambda e: e[2]["entry_time"])
        for key, slot, tr in evs:
            pos = s["positions"].get(key)
            lbl = f"{'LONG' if tr['side'] == 1 else 'SHORT'} {slot['sym']}"
            if pos is None:
                risk_usd = s["balance"] * self.risk_pct()
                pos = dict(sym=slot["sym"], side=tr["side"], entry=tr["entry"], entry_time=tr["entry_time"],
                           stop=tr["stop"], tp=None, sl_dist=tr["risk_pts"], risk_usd=risk_usd, day=tr["day"])
                s["positions"][key] = pos
                et = pd.Timestamp(tr["entry_time"]).tz_convert("Europe/Rome")
                self.notify(f"🟢 [{self.name}] {lbl} a {tr['entry']:.1f} (ore {et:%H:%M}) · stop {tr['stop']:.1f} "
                            f"({tr['risk_pts']:.0f} punti) · rischio {risk_usd:.0f}$ · chiusura entro le 15:55 New York")
            if tr["status"] == "chiuso":
                pnl = pos["risk_usd"] * tr["R"]
                s["balance"] += pnl
                s["peak"] = max(s["peak"], s["balance"])
                row = dict(bot=self.name, slot=f"fhc:{slot['sym']}", entry_time=tr["entry_time"], exit_time=tr["exit_time"],
                           side="LONG" if tr["side"] == 1 else "SHORT", entry=round(tr["entry"], 2), exit=round(tr["exit"], 2),
                           sl_pips=round(tr["risk_pts"], 1), R=round(tr["R"], 3), pnl=round(pnl, 2),
                           balance=round(s["balance"], 2), why=tr["why"])
                self.on_close(row)
                del s["positions"][key]
                s["done_days"] = (s["done_days"] + [key])[-400:]
                self.notify(f"{'📈' if pnl > 0 else '📉'} [{self.name}] {lbl} chiuso ({tr['why']}) a {tr['exit']:.1f} → "
                            f"{tr['R']:+.2f}R, {pnl:+.0f}$ · saldo {s['balance']:.0f}$")
                self.check_challenge(tr["exit_time"])
            else:
                pos["last"] = tr.get("last")
        return s

    def equity(self):
        eq = self.s["balance"]
        for p in self.s["positions"].values():
            if p.get("last") is not None:
                eq += p["risk_usd"] * p["side"] * (p["last"] - p["entry"]) / p["sl_dist"]
        return eq

    def check_challenge(self, when):
        s = self.s
        if s["challenge"] != "in corso":
            return
        if s["balance"] >= START * 1.10:
            s["challenge"], s["challenge_end"] = "PASSATA", str(when)
            self.notify(f"🏆 [{self.name}] +10% raggiunto: fase 1 simulata PASSATA")
        elif s["balance"] <= START * 0.90:
            s["challenge"], s["challenge_end"] = "BOCCIATA", str(when)
            self.notify(f"❌ [{self.name}] limite FTMO superato: challenge simulata BOCCIATA")


def get_candles_5m(slot):
    import yfinance as yf
    d = None
    for _ in range(3):
        d = yf.download(slot["yahoo"], period="60d", interval="5m", progress=False)
        if d is not None and len(d):
            break
    d.columns = [x[0].lower() if isinstance(x, tuple) else x.lower() for x in d.columns]
    d = d[["open", "high", "low", "close"]].dropna()
    d.index = pd.to_datetime(d.index, utc=True)
    now = pd.Timestamp.now(tz="UTC")
    d = d[d.index + pd.Timedelta(minutes=5) <= now]  # solo candele chiuse
    if len(d) < 500:
        raise RuntimeError(f"dati {slot['yahoo']} insufficienti ({len(d)} candele 5m)")
    return d
