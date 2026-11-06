"""Idee a), b), d): breakout di sessione con ordini stop calcolati in anticipo.

Uso: python3 breakouts.py [a|b|d]   -> stampa la griglia e salva grid_<idea>.csv
"""
import itertools
import sys

import numpy as np
import pandas as pd

from rlib import Data, execute, hm, report


def breakout(D, rng, entry_end, exit_m, exit_utc, stop_mode, tp_r, sides=None):
    """rng = (m0, m1) minuti locali del range; ordini stop validi da m1 a entry_end (locali);
    uscita forzata alla chiusura dell'ultima candela prima di exit_m (UTC se exit_utc).
    stop_mode: 'opp' = altro estremo del range, 'mid' = metà del range.
    sides: array per giorno (+1 solo long, -1 solo short, 0 entrambi, nan = niente)."""
    m0, m1 = rng
    exp_bars = (m1 - m0) // 5
    out = []
    for k in range(len(D.slices)):
        side_ok = 0 if sides is None else sides[k]
        if side_ok != side_ok:  # nan
            continue
        r = D.win(k, m0, m1)
        if len(r) < 0.8 * exp_bars:
            continue
        hi, lo = D.h[r].max(), D.l[r].min()
        ent = D.win(k, m1, entry_end)
        ex = D.win(k, 0, exit_m, utc=exit_utc)
        if not len(ent) or not len(ex):
            continue
        i_exit = ex[-1]
        i0, i1 = ent[0], min(ent[-1], i_exit - 1)
        if i1 < i0:
            continue
        orders = []
        for side in (1, -1):
            if side_ok and side != side_ok:
                continue
            lvl = hi if side == 1 else lo
            stop = (lo if side == 1 else hi) if stop_mode == "opp" else (hi + lo) / 2
            risk = abs(lvl - stop)
            tp = lvl + side * tp_r * risk if tp_r else None
            orders.append((side, "stop", lvl, i0, i1, stop, tp))
        tr = execute(D, orders, i_exit)
        if tr:
            out.append(tr)
    return pd.DataFrame(out)


def trend_sides(D, close_m, n=20):
    """+1 se la chiusura di ieri è sopra la media di n chiusure, -1 se sotto (solo dati passati)."""
    dc = pd.Series(D.daily_close(close_m))
    v = dc.dropna()
    s = np.sign(v - v.rolling(n).mean()).shift(1)  # decisione con i dati fino al giorno di borsa prima
    s = s.reindex(dc.index)  # i giorni senza chiusura (domeniche) non fanno trade
    return s.replace(0, np.nan).to_numpy()


def idea_a():
    rows = []
    data = {s: Data(s, "Europe/London") for s in ("EURUSD", "GBPUSD")}
    ranges = {"asia": (hm("00:00"), hm("07:00")), "L30": (hm("08:00"), hm("08:30")), "L60": (hm("08:00"), hm("09:00"))}
    for (rn, rg), stop, tp, ex in itertools.product(ranges.items(), ("opp", "mid"), (1.5, None), (16, 20)):
        trs = []
        for s, D in data.items():
            t = breakout(D, rg, hm("12:00"), ex * 60, True, stop, tp)
            trs.append(t)
            rows.append(report(t, 0.005, f"a {s} {rn} {stop} tp{tp} ex{ex}"))
        rows.append(report(pd.concat(trs), 0.005, f"a EUR+GBP {rn} {stop} tp{tp} ex{ex}"))
    return rows


def idea_b():
    rows = []
    for s in ("NAS100", "US30"):
        D = Data(s, "America/New_York")
        ts = trend_sides(D, hm("16:00"))
        for rmin, stop, tp, filt in itertools.product((5, 15, 30), ("opp", "mid"), (2.0, None), (False, True)):
            t = breakout(D, (hm("09:30"), hm("09:30") + rmin), hm("12:00"), hm("15:55"), False, stop, tp,
                         ts if filt else None)
            rows.append(report(t, 0.005, f"b {s} OR{rmin} {stop} tp{tp} trend{int(filt)}"))
    return rows


def idea_d():
    rows = []
    DL = Data("XAUUSD", "Europe/London")
    DN = Data("XAUUSD", "America/New_York")
    for rn, stop, tp, late in itertools.product(("asia", "L60", "NY30"), ("opp", "mid"), (2.0, None), (False, True)):
        if rn == "NY30":
            t = breakout(DN, (hm("09:30"), hm("10:00")), hm("12:00"), hm("15:55") if late else hm("13:00"), False, stop, tp)
        else:
            rg = (hm("00:00"), hm("07:00")) if rn == "asia" else (hm("08:00"), hm("09:00"))
            t = breakout(DL, rg, hm("12:00"), (20 if late else 16) * 60, True, stop, tp)
        rows.append(report(t, 0.005, f"d XAU {rn} {stop} tp{tp} late{int(late)}"))
    return rows


if __name__ == "__main__":
    idea = sys.argv[1]
    rows = {"a": idea_a, "b": idea_b, "d": idea_d}[idea]()
    df = pd.DataFrame(rows)
    pd.set_option("display.width", 250, "display.max_columns", 40, "display.max_rows", 200)
    print(df.drop(columns=[c for c in ("dd_all",) if c in df]).to_string())
    df.to_csv(f"grid_{idea}.csv", index=False)
