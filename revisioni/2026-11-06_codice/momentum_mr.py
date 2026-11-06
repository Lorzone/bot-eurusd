"""Idea c) intraday momentum sugli indici (Gao, Han, Li, Zhou 2018) e
idea e) mean reversion intraday su EURUSD nelle ore di range (ordini limite).

Uso: python3 momentum_mr.py [c|e]
"""
import itertools
import sys

import numpy as np
import pandas as pd

from rlib import Data, execute, hm, report


def daily_atr(D, m0, m1, n=14):
    """Media del range (max-min) della sessione locale [m0, m1) dei giorni PRECEDENTI."""
    rg = np.full(len(D.slices), np.nan)
    for k in range(len(D.slices)):
        ix = D.win(k, m0, m1)
        if len(ix) > 0.8 * (m1 - m0) / 5:
            rg[k] = D.h[ix].max() - D.l[ix].min()
    s = pd.Series(rg)
    v = s.dropna()
    return v.rolling(n).mean().shift(1).reindex(s.index).to_numpy()


def momentum(D, sig_mode, entry_m, stop_f, thr_f, atr):
    """sig_mode 'on' = da chiusura di ieri (16:00) alle 10:00; 'first' = 09:30 -> 10:00.
    Ingresso a mercato all'apertura della candela entry_m (ordine deciso alle 10:00), uscita 15:55,
    stop = stop_f x range medio giornaliero. Si entra solo se |rendimento| > thr_f x range medio."""
    out, prev_close = [], np.nan
    for k in range(len(D.slices)):
        a = atr[k]
        sess = D.win(k, hm("09:30"), hm("16:00"))
        pc = prev_close
        if len(sess) > 60:
            prev_close = D.c[sess[-1]]
        if not np.isfinite(a) or len(sess) < 70:
            continue
        f30 = D.win(k, hm("09:30"), hm("10:00"))
        if len(f30) < 5:
            continue
        base = pc if sig_mode == "on" else D.o[f30[0]]
        if not np.isfinite(base):
            continue
        r1 = D.c[f30[-1]] - base
        if abs(r1) <= thr_f * a or r1 == 0:
            continue
        side = 1 if r1 > 0 else -1
        e = D.win(k, entry_m, entry_m + 5)
        ex = D.win(k, 0, hm("15:55"))
        if not len(e):
            continue
        i0 = e[0]
        stop = D.o[i0] - side * stop_f * a
        tr = execute(D, [(side, "market", np.nan, i0, i0, stop, None)], ex[-1])
        if tr:
            out.append(tr)
    return pd.DataFrame(out)


def idea_c():
    rows = []
    for s in ("NAS100", "US30"):
        D = Data(s, "America/New_York")
        atr = daily_atr(D, hm("09:30"), hm("16:00"))
        for sig, em, sf, th in itertools.product(("on", "first"), (hm("15:00"), hm("15:30")), (0.2, 0.4), (0, 0.25)):
            t = momentum(D, sig, em, sf, th, atr)
            rows.append(report(t, 0.005, f"c {s} {sig} in{em // 60}:{em % 60:02d} stop{sf} thr{th}"))
    return rows


def meanrev(D, n, k_sd, s_sd, w0, w1):
    """Ore [w0, w1) UTC. A ogni candela: limite buy a media - k*sd e sell a media + k*sd
    (media/sd delle ultime n chiusure, note prima della candela); target = media, stop = s*sd oltre
    il livello d'ingresso; una posizione per volta; uscita forzata alla chiusura dell'ultima candela."""
    c = pd.Series(D.c)
    m = c.rolling(n).mean().shift(1).to_numpy()
    sd = c.rolling(n).std().shift(1).to_numpy()
    out = []
    o, h, l = D.o, D.h, D.l
    for k in range(len(D.slices)):
        ix = D.win(k, w0, w1, utc=True)
        if len(ix) < 0.8 * (w1 - w0) / 5:
            continue
        i_exit = ix[-1]
        i = ix[0]
        while i < i_exit:
            if not np.isfinite(sd[i]) or sd[i] <= 0:
                i += 1
                continue
            bl, sl = m[i] - k_sd * sd[i], m[i] + k_sd * sd[i]
            orders = [(1, "limit", bl, i, i, bl - s_sd * sd[i], m[i]),
                      (-1, "limit", sl, i, i, sl + s_sd * sd[i], m[i])]
            tr = execute_limit(D, orders, i_exit)
            if tr:
                out.append(tr)
                i = tr.pop("_ix") + 1
            else:
                i += 1
    return pd.DataFrame(out)


def execute_limit(D, orders, i_exit):
    """Ordini limite validi una sola candela. Nella candela d'ingresso conta solo lo stop."""
    o, h, l, c = D.o, D.h, D.l, D.c
    for side, _, lvl, i, _, stop, tp in orders:
        hit = l[i] <= lvl if side == 1 else h[i] >= lvl
        if not hit:
            continue
        fill = min(o[i], lvl) if side == 1 else max(o[i], lvl)
        risk = abs(lvl - stop)
        worst, px, why, ix = fill, None, "FINE", None
        for j in range(i, i_exit + 1):
            if side == 1:
                worst = min(worst, l[j])
                if l[j] <= stop:
                    px, why = (stop if j == i else min(o[j], stop)), "STOP"
                elif j > i and h[j] >= tp:
                    px, why = tp, "TARGET"
            else:
                worst = max(worst, h[j])
                if h[j] >= stop:
                    px, why = (stop if j == i else max(o[j], stop)), "STOP"
                elif j > i and l[j] <= tp:
                    px, why = tp, "TARGET"
            if px is not None:
                ix = j
                break
        if px is None:
            ix, px = i_exit, c[i_exit]
        slip = D.slip * (why != "TARGET")  # ingresso limite: niente slittamento
        R = (side * (px - fill) - D.cost - slip) / risk
        mae = min(0.0, side * (worst - fill)) / risk - (D.cost + slip) / risk
        return dict(sym=D.sym, side=side, entry_time=D.t[i], exit_time=D.t[ix] + pd.Timedelta(minutes=5),
                    entry=fill, exit=px, stop=stop, tp=tp, risk=risk, R=R, mae=min(mae, R), why=why, _ix=ix)
    return None


def idea_e():
    rows = []
    D = Data("EURUSD", "UTC")
    for n, k, s, (w0, w1) in itertools.product((24, 48), (2.0, 2.5, 3.0), (1.0, 2.0),
                                                ((hm("00:00"), hm("06:00")), (hm("19:00"), hm("21:00")))):
        t = meanrev(D, n, k, s, w0, w1)
        rows.append(report(t, 0.005, f"e EURUSD n{n} k{k} s{s} {w0 // 60:02d}-{w1 // 60:02d}"))
    return rows


if __name__ == "__main__":
    idea = sys.argv[1]
    rows = {"c": idea_c, "e": idea_e}[idea]()
    df = pd.DataFrame(rows)
    pd.set_option("display.width", 250, "display.max_columns", 40, "display.max_rows", 200)
    print(df.to_string())
    df.to_csv(f"grid_{idea}.csv", index=False)
