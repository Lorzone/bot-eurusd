"""Bot swing EUR/USD — paper trading live, gira ogni ora (GitHub Actions o PC).

Strategia: trend 4h (EMA20 > EMA200) + pullback 1h (RSI14 che rientra sopra 30 / sotto 70),
stop = 2.5 x ATR(14) 1h, poi trailing stop alla stessa distanza. Rischio 1% per trade.
Filtro notizie: nessun nuovo ingresso da 60 min prima a 60 min dopo una notizia
ad alto impatto USD/EUR (calendario ForexFactory).

Stato in state.json, storico in trades.csv, riepilogo leggibile in STATUS.md.
Telegram opzionale: variabili d'ambiente TELEGRAM_TOKEN e TELEGRAM_CHAT_ID.
Dati: OANDA practice se ci sono OANDA_TOKEN (+ OANDA_ENV=practice), altrimenti Yahoo Finance.
"""
import json
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import pandas as pd
import requests

from strategies import trend_pullback

ROOT = Path(__file__).parent
STATE = ROOT / "state.json"
TRADES = ROOT / "trades.csv"
STATUS = ROOT / "STATUS.md"

CFG = dict(
    symbol="EURUSD",
    params=dict(ema_fast=20, ema_slow=200, rsi_lo=30, rsi_hi=70, sl_atr=2.5, tp_r=np.nan),
    risk=float(os.getenv("RISK", "0.01")),
    start_balance=100_000.0,
    cost_pips=1.3,
    max_bars=120,
    news_window_min=60,
    news_currencies=("USD", "EUR"),
    ftmo_target=0.10, ftmo_max_loss=0.10, ftmo_daily_loss=0.05,
)
PIP = 0.0001


# ---------------- dati ----------------
def get_candles():
    tok = os.getenv("OANDA_TOKEN")
    if tok:
        host = "api-fxpractice.oanda.com" if os.getenv("OANDA_ENV", "practice") == "practice" else "api-fxtrade.oanda.com"
        r = requests.get(f"https://{host}/v3/instruments/EUR_USD/candles",
                         headers={"Authorization": f"Bearer {tok}"},
                         params={"granularity": "H1", "count": 1500, "price": "M"}, timeout=30)
        r.raise_for_status()
        rows = [dict(time=c["time"], open=float(c["mid"]["o"]), high=float(c["mid"]["h"]),
                     low=float(c["mid"]["l"]), close=float(c["mid"]["c"]))
                for c in r.json()["candles"] if c["complete"]]
        df = pd.DataFrame(rows)
        df.index = pd.to_datetime(df.pop("time"), utc=True)
        return df
    import yfinance as yf
    d = yf.download("EURUSD=X", period="180d", interval="1h", progress=False)
    d.columns = [c[0].lower() if isinstance(c, tuple) else c.lower() for c in d.columns]
    d = d[["open", "high", "low", "close"]].dropna()
    d.index = pd.to_datetime(d.index, utc=True)
    # togli la candela in corso (non ancora chiusa)
    now = pd.Timestamp.now(tz="UTC")
    return d[d.index + pd.Timedelta(hours=1) <= now]


NEWS_CACHE = ROOT / "news_cache.json"


def get_news():
    """Calendario della settimana. Scaricato al massimo ogni 6 ore (il feed limita le richieste);
    se il download fallisce si usa la copia salvata, purché sia di questa settimana."""
    raw, err = None, None
    cache = json.loads(NEWS_CACHE.read_text()) if NEWS_CACHE.exists() else None
    now = pd.Timestamp.now(tz="UTC")
    fresh = cache and now - pd.Timestamp(cache["fetched"]) < pd.Timedelta(hours=6)
    if not fresh:
        try:
            r = requests.get("https://nfs.faireconomy.media/ff_calendar_thisweek.json", timeout=20,
                             headers={"User-Agent": "Mozilla/5.0"})
            r.raise_for_status()
            raw = r.json()
            NEWS_CACHE.write_text(json.dumps(dict(fetched=str(now), events=raw)))
        except Exception as ex:
            err = str(ex)
    if raw is None and cache:
        same_week = pd.Timestamp(cache["fetched"]).isocalendar()[:2] == now.isocalendar()[:2]
        if same_week:
            raw, err = cache["events"], None
    if raw is None:  # niente calendario affidabile: per prudenza non si entra
        return None, err or "nessun dato"
    ev = [e for e in raw if e.get("impact") == "High" and e.get("country") in CFG["news_currencies"]]
    for e in ev:
        e["dt"] = pd.Timestamp(e["date"]).tz_convert("UTC")
    return ev, None


def news_block(now, events):
    if events is None:
        return "calendario notizie non disponibile"
    w = pd.Timedelta(minutes=CFG["news_window_min"])
    for e in events:
        if e["dt"] - w <= now <= e["dt"] + w:
            return f"{e['country']} {e['title']} alle {e['dt'].strftime('%H:%M')} UTC"
    return None


# ---------------- stato ----------------
def load_state():
    if STATE.exists():
        return json.loads(STATE.read_text())
    return dict(balance=CFG["start_balance"], position=None, last_bar=None,
                day=None, day_start_balance=CFG["start_balance"], challenge="in corso", log=[])


def save_state(s):
    s["log"] = s["log"][-50:]
    STATE.write_text(json.dumps(s, indent=2, default=str))


CHAT_FILE = ROOT / "telegram_chat.txt"


def telegram_chat(tok):
    """Chat ID: dal secret, altrimenti dal file salvato, altrimenti lo ricava dall'ultimo
    messaggio che hai scritto al bot (basta premere Avvia sul bot)."""
    chat = os.getenv("TELEGRAM_CHAT_ID", "").strip()
    if chat:
        return chat
    if CHAT_FILE.exists():
        return CHAT_FILE.read_text().strip()
    try:
        upd = requests.get(f"https://api.telegram.org/bot{tok}/getUpdates", timeout=15).json()
        for u in reversed(upd.get("result", [])):
            m = u.get("message") or u.get("my_chat_member") or {}
            cid = (m.get("chat") or {}).get("id")
            if cid:
                CHAT_FILE.write_text(str(cid))
                requests.post(f"https://api.telegram.org/bot{tok}/sendMessage", timeout=15,
                              data={"chat_id": cid, "text": "✅ Bot EURUSD collegato: da ora ti scrivo qui quando apro o chiudo un trade."})
                return str(cid)
    except Exception:
        pass
    print("Telegram: token presente ma nessun messaggio ricevuto, premi Avvia sul tuo bot")
    return None


def notify(msg):
    print(msg)
    tok = os.getenv("TELEGRAM_TOKEN", "").strip()
    chat = telegram_chat(tok) if tok else None
    if tok and chat:
        try:
            requests.post(f"https://api.telegram.org/bot{tok}/sendMessage",
                          data={"chat_id": chat, "text": msg}, timeout=15)
        except Exception:
            pass


def close_position(s, price, when, why):
    p = s["position"]
    side, entry, d = p["side"], p["entry"], p["sl_dist"]
    R = (side * (price - entry) - CFG["cost_pips"] * PIP) / d
    pnl = p["risk_eur"] * R
    s["balance"] += pnl
    row = dict(entry_time=p["entry_time"], exit_time=str(when), side="LONG" if side == 1 else "SHORT",
               entry=round(entry, 5), exit=round(price, 5), sl_pips=round(d / PIP, 1),
               R=round(R, 2), pnl=round(pnl, 2), balance=round(s["balance"], 2), why=why)
    pd.DataFrame([row]).to_csv(TRADES, mode="a", header=not TRADES.exists(), index=False)
    s["position"] = None
    notify(f"🔔 EURUSD chiuso {row['side']} ({why}) a {row['exit']} → {row['R']:+.2f}R, "
           f"{row['pnl']:+.0f}$ · saldo {row['balance']:.0f}$")


# ---------------- ciclo principale ----------------
def step():
    s = load_state()
    df = get_candles()
    if len(df) < 1000:
        print("dati insufficienti:", len(df))
        return
    sig = trend_pullback(df, **CFG["params"])
    last = s["last_bar"]
    new = sig if last is None else sig[sig.index > pd.Timestamp(last)]
    if last is None:
        new = sig.iloc[-1:]  # primo avvio: si valuta solo l'ultima candela chiusa
    events, news_err = get_news()

    for t, bar in new.iterrows():
        # nuovo giorno -> aggiorna base per la perdita giornaliera (regola FTMO)
        day = t.date().isoformat()
        if s["day"] != day:
            s["day"], s["day_start_balance"] = day, s["balance"]

        p = s["position"]
        if p:
            side = p["side"]
            p["bars"] += 1
            hit = (side == 1 and bar["low"] <= p["stop"]) or (side == -1 and bar["high"] >= p["stop"])
            if hit:
                px = min(bar["open"], p["stop"]) if side == 1 else max(bar["open"], p["stop"])
                close_position(s, px, t + pd.Timedelta(hours=1), "STOP")
            elif p["bars"] >= CFG["max_bars"]:
                close_position(s, bar["close"], t + pd.Timedelta(hours=1), "TEMPO")
            else:
                if side == 1:
                    p["best"] = max(p["best"], bar["high"])
                    p["stop"] = max(p["stop"], p["best"] - p["sl_dist"])
                else:
                    p["best"] = min(p["best"], bar["low"])
                    p["stop"] = min(p["stop"], p["best"] + p["sl_dist"])

        if s["position"] is None and bar["signal"] != 0:  # continua anche dopo pass/fail per raccogliere dati
            when = t + pd.Timedelta(hours=1)
            # se la candela non è l'ultima, siamo in recupero di run persi: si entra solo sull'ultima
            if t != sig.index[-1]:
                continue
            blk = news_block(pd.Timestamp.now(tz="UTC"), events)
            if blk:
                s["log"].append(f"{when}: segnale {'LONG' if bar['signal'] > 0 else 'SHORT'} saltato per notizia: {blk}")
                notify(f"⏸️ Segnale EURUSD saltato per notizia: {blk}")
                continue
            side = int(bar["signal"])
            entry = float(bar["close"])  # ≈ apertura della candela successiva
            d = float(bar["sl_dist"])
            risk_eur = s["balance"] * CFG["risk"]
            s["position"] = dict(side=side, entry=entry, entry_time=str(when), sl_dist=d,
                                 stop=entry - side * d, best=entry, bars=0, risk_eur=risk_eur,
                                 lots=round(risk_eur / (d / PIP * 10), 2))
            notify(f"🟢 EURUSD {'LONG' if side == 1 else 'SHORT'} a {entry:.5f} · stop {entry - side * d:.5f} "
                   f"({d / PIP:.0f} pips) · rischio {risk_eur:.0f}$ · {s['position']['lots']} lotti")

        # regole della challenge
        b0 = CFG["start_balance"]
        if s["balance"] >= b0 * (1 + CFG["ftmo_target"]) and s["challenge"] == "in corso":
            s["challenge"] = "PASSATA"
            notify("🏆 Obiettivo +10% raggiunto: challenge simulata PASSATA")
        if s["balance"] <= b0 * (1 - CFG["ftmo_max_loss"]) or \
                s["balance"] <= s["day_start_balance"] - b0 * CFG["ftmo_daily_loss"]:
            if s["challenge"] == "in corso":
                s["challenge"] = "BOCCIATA"
                notify("❌ Limite di perdita superato: challenge simulata BOCCIATA")

        s["last_bar"] = str(t)

    write_status(s, sig, events, news_err)
    save_state(s)
    if os.getenv("TELEGRAM_TOKEN", "").strip():
        telegram_chat(os.getenv("TELEGRAM_TOKEN").strip())
    p = s["position"]
    print(f"OK {s['last_bar']} · saldo {s['balance']:.0f} · "
          f"{'posizione ' + ('LONG' if p['side'] == 1 else 'SHORT') if p else 'nessuna posizione'} · "
          f"notizie: {'errore ' + news_err if news_err else len(events or []) }")


def write_status(s, sig, events, news_err):
    b0 = CFG["start_balance"]
    last = sig.iloc[-1]
    p = s["position"]
    lines = [f"# Bot EURUSD swing — stato",
             f"_Aggiornato: {datetime.now(timezone.utc):%Y-%m-%d %H:%M} UTC · ultima candela: {s['last_bar']}_", "",
             f"**Saldo:** {s['balance']:,.0f} $ ({(s['balance'] / b0 - 1) * 100:+.2f}%) · "
             f"**Challenge:** {s['challenge']} (obiettivo +10%, max -10%, max -5% al giorno)", "",
             f"**Prezzo:** {last['close']:.5f}", ""]
    if p:
        fl = p["side"] * (last["close"] - p["entry"]) / p["sl_dist"]
        lines += [f"**Posizione aperta:** {'LONG' if p['side'] == 1 else 'SHORT'} da {p['entry']:.5f} "
                  f"({p['entry_time']}) · stop attuale {p['stop']:.5f} · in corso {fl:+.2f}R", ""]
    else:
        lines += ["**Nessuna posizione aperta.**", ""]
    if news_err:
        lines.append(f"⚠️ Calendario notizie non raggiungibile: nuovi ingressi sospesi.")
    elif events:
        nxt = [e for e in events if e["dt"] > pd.Timestamp.now(tz="UTC")][:5]
        if nxt:
            lines += ["**Prossime notizie ad alto impatto (UTC):**"] + \
                     [f"- {e['dt']:%a %d %H:%M} · {e['country']} · {e['title']}" for e in nxt] + [""]
    if TRADES.exists():
        t = pd.read_csv(TRADES)
        lines += [f"**Trade chiusi:** {len(t)} · vinti {(t.R > 0).mean() * 100:.0f}% · media {t.R.mean():+.2f}R", "",
                  t.tail(10).to_markdown(index=False)]
    if s["log"]:
        lines += ["", "**Note:**"] + [f"- {x}" for x in s["log"][-5:]]
    STATUS.write_text("\n".join(lines) + "\n")


if __name__ == "__main__":
    step()
