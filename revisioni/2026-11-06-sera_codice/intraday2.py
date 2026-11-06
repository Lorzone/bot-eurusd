"""Nuove tipologie intraday (6 novembre 2026, sera). Tutti i trade aperti e chiusi in giornata.

1) pdhl  : breakout del massimo/minimo di ieri (ordini stop), stop in ATR giornaliero, uscita a fine sessione
2) fhc   : continuazione della prima ora sugli indici (ingresso a mercato a fine prima ora)
3) pull30: pullback intraday su candele 30 minuti a favore del trend giornaliero, uscita a fine sessione

Uso: COSTI=ftmo python3 intraday2.py pdhl|fhc|pull30
Selezione 2020-2023, verifica 2024-oggi (rlib.SPLIT). Rischio 0,5% per le challenge.
"""
import itertools
import sys

import numpy as np
import pandas as pd

from rlib import Data, execute, hm, report

SESS = {  # tz, inizio ordini, fine ordini, uscita forzata (minuti locali), fine "giorno" per massimi/minimi
    "EURUSD": ("Europe/London", hm("07:00"), hm("16:00"), hm("20:00")),
    "GBPUSD": ("Europe/London", hm("07:00"), hm("16:00"), hm("20:00")),
    "XAUUSD": ("Europe/London", hm("07:00"), hm("16:00"), hm("20:00")),
    "NAS100": ("America/New_York", hm("09:35"), hm("15:00"), hm("15:55")),
    "US30": ("America/New_York", hm("09:35"), hm("15:00"), hm("15:55")),
    "SPX500": ("America/New_York", hm("09:35"), hm("15:00"), hm("15:55")),
    "GER40": ("Europe/Berlin", hm("09:05"), hm("16:00"), hm("17:25")),
}
RTH = {"NAS100": (hm("09:30"), hm("16:00")), "US30": (hm("09:30"), hm("16:00")), "SPX500": (hm("09:30"), hm("16:00")),
       "GER40": (hm("09:00"), hm("17:30"))}


def daily_hl(D, sym):
    """Massimo, minimo, chiusura di ogni giorno (sessione regolare per gli indici, giorno intero per FX/oro)."""
    m0, m1 = RTH.get(sym, (0, 24 * 60))
    n = len(D.slices)
    H, L, C = np.full(n, np.nan), np.full(n, np.nan), np.full(n, np.nan)
    for k in range(n):
        ix = D.win(k, m0, m1)
        if len(ix) > 12:
            H[k], L[k], C[k] = D.h[ix].max(), D.l[ix].min(), D.c[ix[-1]]
    return H, L, C


def prev_valid(arr):
    """Per ogni giorno k: valore dell'ultimo giorno precedente con dati (niente look-ahead)."""
    s = pd.Series(arr)
    return s.ffill().shift(1).to_numpy()


def daily_feats(D, sym):
    H, L, C = daily_hl(D, sym)
    rng = pd.Series(H - L)
    atr = rng.dropna().rolling(14).mean().reindex(rng.index).ffill().shift(1).to_numpy()  # ATR fino a ieri
    c = pd.Series(C)
    sma = c.dropna().rolling(20).mean().reindex(c.index).ffill()
    trend = np.sign(c.ffill() - sma).shift(1).to_numpy()  # chiusura di ieri vs media 20 di ieri
    return prev_valid(H), prev_valid(L), atr, trend


# ---------- 1) breakout massimo/minimo di ieri ----------
def pdhl(D, sym, k_atr, tp_r, use_trend):
    tz, e0, e1, ex = SESS[sym]
    PH, PL, ATR, TR = daily_feats(D, sym)
    out = []
    for k in range(len(D.slices)):
        if not np.isfinite(PH[k]) or not np.isfinite(ATR[k]):
            continue
        ent, exi = D.win(k, e0, e1), D.win(k, 0, ex)
        if not len(ent) or not len(exi):
            continue
        i_exit = exi[-1]
        i0, i1 = ent[0], min(ent[-1], i_exit - 1)
        # se all'apertura della finestra il prezzo è già oltre il livello, quel lato non vale
        p0 = D.o[i0]
        orders = []
        for side in (1, -1):
            if use_trend and TR[k] != side:
                continue
            lvl = PH[k] if side == 1 else PL[k]
            if (side == 1 and p0 >= lvl) or (side == -1 and p0 <= lvl):
                continue
            stop = lvl - side * k_atr * ATR[k]
            tp = lvl + side * tp_r * k_atr * ATR[k] if tp_r else None
            orders.append((side, "stop", lvl, i0, i1, stop, tp))
        t = execute(D, orders, i_exit) if orders else None
        if t:
            out.append(t)
    return pd.DataFrame(out)


# ---------- 2) continuazione della prima ora ----------
def fhc(D, sym, th, tp_r, use_trend, minutes=60):
    o0 = RTH[sym][0]
    _, _, ex = SESS[sym][1:]
    _, _, ATR, TR = daily_feats(D, sym)
    out = []
    for k in range(len(D.slices)):
        if not np.isfinite(ATR[k]):
            continue
        fh = D.win(k, o0, o0 + minutes)
        if len(fh) < 0.8 * minutes / 5:
            continue
        mv = D.c[fh[-1]] - D.o[fh[0]]
        if abs(mv) < th * ATR[k]:
            continue
        side = int(np.sign(mv))
        if use_trend and TR[k] != side:
            continue
        nxt = D.win(k, o0 + minutes, o0 + minutes + 5)
        exi = D.win(k, 0, ex)
        if not len(nxt) or not len(exi):
            continue
        stop = D.l[fh].min() if side == 1 else D.h[fh].max()
        fill = D.o[nxt[0]]
        if side * (fill - stop) <= 0:
            continue
        tp = fill + side * tp_r * abs(fill - stop) if tp_r else None
        t = execute(D, [(side, "market", fill, nxt[0], nxt[0], stop, tp)], exi[-1])
        if t:
            out.append(t)
    return pd.DataFrame(out)


# ---------- 3) pullback su 30 minuti ----------
def rsi(x, n=14):
    d = np.diff(x, prepend=x[0])
    up = pd.Series(np.clip(d, 0, None)).ewm(alpha=1 / n, adjust=False).mean()
    dn = pd.Series(np.clip(-d, 0, None)).ewm(alpha=1 / n, adjust=False).mean()
    return (100 - 100 / (1 + up / dn.replace(0, np.nan))).to_numpy()


def pull30(D, sym, lo, sl_atr, tp_r):
    """Candele 30m costruite dalle 5m. Trend = chiusura di ieri vs media 20 giorni E prezzo sopra/sotto
    l'apertura di oggi. Segnale alla chiusura della 30m: RSI14(30m) rientra sopra lo (long) / sotto 100-lo.
    Ingresso a mercato all'apertura della 5m successiva, stop sl_atr x ATR14(30m), uscita a fine sessione.
    Max 1 trade al giorno."""
    tz, e0, e1, ex = SESS[sym]
    _, _, _, TR = daily_feats(D, sym)
    df = D.df.copy()
    df["i"] = np.arange(len(df))
    b = df.resample("30min", label="left", closed="left").agg(
        {"open": "first", "high": "max", "low": "min", "close": "last", "i": "last"}).dropna()
    r = rsi(b.close.to_numpy())
    pc = b.close.shift().to_numpy()
    tr = np.maximum(b.high - b.low, np.maximum(abs(b.high - pc), abs(b.low - pc)))
    atr = pd.Series(tr).ewm(alpha=1 / 14, adjust=False).mean().to_numpy()
    last_i = b.i.to_numpy().astype(int)
    # giorno locale di ogni 5m
    day_of = np.empty(len(df), dtype=int)
    for k, (a, z) in enumerate(D.slices):
        day_of[a:z] = k
    out, used = [], set()
    for j in range(15, len(b)):
        i_close = last_i[j]
        if i_close + 1 >= len(df):
            break
        k = day_of[i_close]
        if k in used or not np.isfinite(TR[k]):
            continue
        lm = D.lmin[i_close] + 5  # minuto locale di chiusura della 30m
        if lm < e0 or lm > e1:
            continue
        side = 0
        if r[j - 1] < lo <= r[j]:
            side = 1
        elif r[j - 1] > 100 - lo >= r[j]:
            side = -1
        if side == 0 or TR[k] != side:
            continue
        a, z = D.slices[k]
        day_open = D.o[a + np.flatnonzero(D.lmin[a:z] >= e0)[0]] if (D.lmin[a:z] >= e0).any() else np.nan
        if not np.isfinite(day_open) or side * (b.close.iloc[j] - day_open) < 0:
            continue
        exi = D.win(k, 0, ex)
        if not len(exi) or exi[-1] <= i_close + 1:
            continue
        ie = i_close + 1
        fill = D.o[ie]
        stop = fill - side * sl_atr * atr[j]
        tp = fill + side * tp_r * sl_atr * atr[j] if tp_r else None
        t = execute(D, [(side, "market", fill, ie, ie, stop, tp)], exi[-1])
        if t:
            out.append(t)
            used.add(k)
    return pd.DataFrame(out)


def run(idea, syms):
    rows, trades = [], {}
    for sym in syms:
        D = Data(sym, SESS[sym][0])
        if idea == "pdhl":
            grid = itertools.product((0.5, 1.0), (1.0, 2.0, None), (False, True))
            for k_atr, tp, tf in grid:
                t = pdhl(D, sym, k_atr, tp, tf)
                lab = f"pdhl {sym} k{k_atr} tp{tp} trend{int(tf)}"
                rows.append(report(t, 0.005, lab)); trades[lab] = t
        elif idea == "fhc":
            for th, tp, tf in itertools.product((0.1, 0.2, 0.3), (2.0, None), (False, True)):
                t = fhc(D, sym, th, tp, tf)
                lab = f"fhc {sym} th{th} tp{tp} trend{int(tf)}"
                rows.append(report(t, 0.005, lab)); trades[lab] = t
        elif idea == "pull30":
            for lo, sl, tp in itertools.product((30, 40), (1.0, 2.0), (1.5, None)):
                t = pull30(D, sym, lo, sl, tp)
                lab = f"pull30 {sym} rsi{lo} sl{sl} tp{tp}"
                rows.append(report(t, 0.005, lab)); trades[lab] = t
        print(sym, "fatto", flush=True)
    return pd.DataFrame(rows), trades


if __name__ == "__main__":
    import os, pickle
    idea = sys.argv[1]
    syms = sys.argv[2].split(",")
    df, trades = run(idea, syms)
    sc = os.getenv("COSTI", "ftmo")
    pd.set_option("display.width", 260, "display.max_columns", 40, "display.max_rows", 300)
    cols = [c for c in ("label", "tw_ver", "R_sel", "pf_sel", "R_ver", "pf_ver", "yrs_pos", "R2024", "R2025", "R2026",
                        "dd_ver", "ch_pass", "ch_fail", "ch_open") if c in df]
    print(df[cols].to_string())
    df.to_csv(f"g2_{sc}_{idea}_{'-'.join(syms)}.csv", index=False)
    pickle.dump(trades, open(f"t2_{sc}_{idea}_{'-'.join(syms)}.pkl", "wb"))
