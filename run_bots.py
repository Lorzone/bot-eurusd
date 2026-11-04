"""Esegue ogni ora i bot paper A-D (vedi engine.BOTS) e aggiorna DASHBOARD.md.

Per ogni bot: bots/<nome>/state.json (saldo, posizioni), bots/<nome>/trades.csv (storico).
Errori: registrati in state.json e mostrati nella dashboard; un errore su un bot non ferma gli altri.
Telegram: TELEGRAM_TOKEN (+ TELEGRAM_CHAT_ID opzionale). Dati: OANDA se OANDA_TOKEN, altrimenti Yahoo.
"""
import json
import os
import traceback
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd
import requests

import engine
from engine import BOTS, INSTR, Bot, new_state, signals, slot_id, START

ROOT = Path(__file__).parent
BOTDIR = ROOT / "bots"
NEWS_CACHE = ROOT / "news_cache.json"
CHAT_FILE = ROOT / "telegram_chat.txt"
EXPECTED = json.loads((ROOT / "expected.json").read_text()) if (ROOT / "expected.json").exists() else {}
RUN_LOG = []


# ---------------- telegram ----------------
def telegram_chat(tok):
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
                return str(cid)
    except Exception:
        pass
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


# ---------------- dati ----------------
def get_candles(sym):
    now = pd.Timestamp.now(tz="UTC")
    tok = os.getenv("OANDA_TOKEN")
    if tok:
        r = requests.get(f"https://api-fxpractice.oanda.com/v3/instruments/{INSTR[sym]['oanda']}/candles",
                         headers={"Authorization": f"Bearer {tok}"},
                         params={"granularity": "H1", "count": 2500, "price": "M"}, timeout=30)
        r.raise_for_status()
        rows = [dict(time=c["time"], open=float(c["mid"]["o"]), high=float(c["mid"]["h"]),
                     low=float(c["mid"]["l"]), close=float(c["mid"]["c"]))
                for c in r.json()["candles"] if c["complete"]]
        df = pd.DataFrame(rows)
        df.index = pd.to_datetime(df.pop("time"), utc=True)
    else:
        import yfinance as yf
        d = None
        for _ in range(3):
            d = yf.download(INSTR[sym]["yahoo"], period="180d", interval="1h", progress=False)
            if d is not None and len(d):
                break
        d.columns = [c[0].lower() if isinstance(c, tuple) else c.lower() for c in d.columns]
        df = d[["open", "high", "low", "close"]].dropna()
        df.index = pd.to_datetime(df.index, utc=True)
    df = df[df.index + pd.Timedelta(hours=1) <= now]  # solo candele chiuse
    if len(df) < 1000:
        raise RuntimeError(f"dati {sym} insufficienti ({len(df)} candele)")
    if now - df.index[-1] > pd.Timedelta(hours=6) and now.weekday() < 5 and not (now.weekday() == 4 and now.hour >= 21):
        RUN_LOG.append(f"⚠️ dati {sym} vecchi: ultima candela {df.index[-1]}")
    return df


def get_news():
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
        if pd.Timestamp(cache["fetched"]).isocalendar()[:2] == now.isocalendar()[:2]:
            raw, err = cache["events"], None
    if raw is None:
        return None, err or "nessun dato"
    ev = [e for e in raw if e.get("impact") == "High"]
    for e in ev:
        e["dt"] = pd.Timestamp(e["date"]).tz_convert("UTC")
    return ev, None


def news_block(sym, events, now, window=60):
    if events is None:
        return "calendario notizie non disponibile"
    w = pd.Timedelta(minutes=window)
    for e in events:
        if e["country"] in INSTR[sym]["news"] and e["dt"] - w <= now <= e["dt"] + w:
            return f"{e['country']} {e['title']} alle {e['dt']:%H:%M} UTC"
    return None


# ---------------- esecuzione di un bot ----------------
def run_bot(name, data, sigcache, events):
    d = BOTDIR / name
    d.mkdir(parents=True, exist_ok=True)
    st_path, tr_path = d / "state.json", d / "trades.csv"
    state = json.loads(st_path.read_text()) if st_path.exists() else new_state()

    def on_close(row):
        pd.DataFrame([row]).to_csv(tr_path, mode="a", header=not tr_path.exists(), index=False)

    bot = Bot(name, state, notify=notify, on_close=on_close)
    now = pd.Timestamp.now(tz="UTC")
    slots = []
    for strat, sym, params in BOTS[name]["slots"]:
        sid = slot_id(strat, sym)
        key = (strat, sym, json.dumps(params, default=str))
        if key not in sigcache:
            sigcache[key] = signals(strat, data[sym], params)
        sig = sigcache[key]
        last = state["last_bar"].get(sid)
        new = sig.iloc[-1:] if last is None else sig[sig.index > pd.Timestamp(last)]
        slots.append((sid, sym, sig, new))
    times = sorted(set().union(*[set(n.index) for _, _, _, n in slots]))
    for t in times:
        bot.roll_day(t)
        for sid, sym, sig, new in slots:
            if t in new.index:
                bar = new.loc[t]
                bot.last_px[sym] = bar["close"]
                bot.manage(sid, t, bar)
        for sid, sym, sig, new in slots:
            if t in new.index:
                bar = new.loc[t]
                if t == sig.index[-1]:  # si entra solo sull'ultima candela chiusa (non nei recuperi)
                    bot.try_enter(sid, sym, t, bar, float(bar["close"]), news_block(sym, events, now))
                state["last_bar"][sid] = str(t)
        bot.check_challenge(t)
    for sid, sym, sig, _ in slots:
        bot.last_px[sym] = float(sig["close"].iloc[-1])
    state["equity"] = round(bot.equity(), 2)
    state["updated"] = str(now)
    st_path.write_text(json.dumps(state, indent=1, default=str))
    return state


# ---------------- dashboard ----------------
def dashboard(states, events, news_err, data_err):
    now = datetime.now(timezone.utc)
    started = min((st.get("started", "") for st in states.values() if st.get("started")), default="")
    L = [f"# Bot paper — confronto", f"_Aggiornato {now:%Y-%m-%d %H:%M} UTC · in gara dal {started[:10]}_", ""]
    L += ["| Bot | Strategia | Saldo | Equity | Challenge | Trade | Trade/sett (atteso) | R medio (atteso) | Aperte |",
          "|---|---|---|---|---|---|---|---|---|"]
    for name, st in states.items():
        exp = EXPECTED.get(name, {})
        trp = BOTDIR / name / "trades.csv"
        t = pd.read_csv(trp) if trp.exists() else pd.DataFrame(columns=["R", "exit_time"])
        start = pd.Timestamp(st.get("started", now.isoformat()))
        weeks = max((pd.Timestamp(now) - start).days / 7, 1 / 7)
        if isinstance(st, dict) and "balance" in st:
            L.append(f"| **{name}** | {BOTS[name]['desc']} | {st['balance']:,.0f}$ ({(st['balance'] / START - 1) * 100:+.2f}%) | "
                     f"{st.get('equity', st['balance']):,.0f}$ | {st['challenge']} | {len(t)} | "
                     f"{len(t) / weeks:.1f} ({exp.get('trade_sett', '–')}) | "
                     f"{(t.R.mean() if len(t) else 0):+.2f} ({exp.get('R_medio', '–')}) | {len(st['positions'])} |")
        else:
            L.append(f"| **{name}** | {BOTS[name]['desc']} | ERRORE | | | | | | |")
    L += ["", "_Atteso = backtest 2024-2026 con lo stesso motore. Con pochi trade la differenza è normale: "
          "conta dopo almeno 20-30 trade._", ""]
    pos = [(n, sid, p) for n, st in states.items() if "positions" in st for sid, p in st["positions"].items()]
    if pos:
        L += ["## Posizioni aperte", "| Bot | Slot | Lato | Ingresso | Stop | Target | Da |", "|---|---|---|---|---|---|---|"]
        for n, sid, p in pos:
            L.append(f"| {n} | {sid} | {'LONG' if p['side'] == 1 else 'SHORT'} | {p['entry']:.5g} | {p['stop']:.5g} | "
                     f"{p['tp']:.5g} | {p['entry_time'][:16]} |" if p["tp"] else
                     f"| {n} | {sid} | {'LONG' if p['side'] == 1 else 'SHORT'} | {p['entry']:.5g} | {p['stop']:.5g} | trailing | {p['entry_time'][:16]} |")
        L.append("")
    probs = list(RUN_LOG) + ([f"⚠️ calendario notizie non disponibile: {news_err}"] if news_err else []) + data_err
    for n, st in states.items():
        probs += [f"[{n}] {e}" for e in st.get("errors", [])[-3:]]
    L += ["## Errori e avvisi"] + ([f"- {p}" for p in probs] if probs else ["- nessuno ✅"]) + [""]
    skipped = [(n, x) for n, st in states.items() for x in st.get("skipped", [])[-5:]]
    if skipped:
        L += ["## Segnali saltati (ultimi)"] + [f"- [{n}] {x}" for n, x in skipped] + [""]
    if events:
        cur = {c for i in INSTR.values() for c in i["news"]}
        nxt = [e for e in events if e["dt"] > pd.Timestamp.now(tz="UTC") and e["country"] in cur][:6]
        if nxt:
            L += ["## Prossime notizie ad alto impatto (UTC)"] + [f"- {e['dt']:%a %d %H:%M} · {e['country']} · {e['title']}" for e in nxt]
    (ROOT / "DASHBOARD.md").write_text("\n".join(L) + "\n")


def main():
    needed = sorted({sym for b in BOTS.values() for _, sym, _ in b["slots"]})
    data, data_err = {}, []
    for sym in needed:
        try:
            data[sym] = get_candles(sym)
        except Exception as ex:
            data_err.append(f"⚠️ dati {sym}: {ex}")
    events, news_err = get_news()
    states, sigcache = {}, {}
    for name in BOTS:
        st_path = BOTDIR / name / "state.json"
        try:
            missing = [s for _, s, _ in BOTS[name]["slots"] if s not in data]
            if missing:
                raise RuntimeError(f"mancano i dati di {', '.join(missing)}")
            if not st_path.exists():
                (BOTDIR / name).mkdir(parents=True, exist_ok=True)
                st = new_state()
                st["started"] = str(pd.Timestamp.now(tz="UTC"))
                st_path.write_text(json.dumps(st, indent=1))
            states[name] = run_bot(name, data, sigcache, events)
        except Exception as ex:
            msg = f"{datetime.now(timezone.utc):%m-%d %H:%M} {type(ex).__name__}: {ex}"
            print(f"[{name}] ERRORE", traceback.format_exc())
            st = json.loads(st_path.read_text()) if st_path.exists() else new_state()
            st.setdefault("errors", []).append(msg)
            st["errors"] = st["errors"][-20:]
            st_path.parent.mkdir(parents=True, exist_ok=True)
            st_path.write_text(json.dumps(st, indent=1, default=str))
            states[name] = st
    dashboard(states, events, news_err, data_err)
    if os.getenv("TELEGRAM_TOKEN", "").strip():
        telegram_chat(os.getenv("TELEGRAM_TOKEN").strip())
    print("OK", {n: (round(s.get("balance", 0)), len(s.get("positions", {}))) for n, s in states.items()},
          "errori dati:", data_err, "notizie:", news_err or len(events or []))


if __name__ == "__main__":
    main()
