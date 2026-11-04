"""Motore di backtest semplice e prudente.
- una posizione alla volta, ingresso all'apertura della candela dopo il segnale
- se nella stessa candela vengono toccati sia SL che TP, si assume SL (caso peggiore)
- costi: spread + commissione in pips, tolti da ogni trade
- rischio fisso % del capitale per trade
- trailing stop opzionale (se tp_dist è NaN) + uscita a tempo
"""
import numpy as np
import pandas as pd

PIP = 0.0001


def run(df, risk=0.01, cost_pips=1.3, max_bars=120, start_balance=100_000, trail=True, pip=PIP):
    o, h, l, c = (df[k].values for k in ("open", "high", "low", "close"))
    sig, sld, tpd = df["signal"].values, df["sl_dist"].values, df["tp_dist"].values
    idx = df.index
    trades = []
    i, n = 0, len(df)
    while i < n - 1:
        s = sig[i]
        if s == 0 or not np.isfinite(sld[i]) or sld[i] <= 0:
            i += 1
            continue
        e_i = i + 1
        entry = o[e_i]
        d = sld[i]
        stop = entry - s * d
        tp = entry + s * tpd[i] if np.isfinite(tpd[i]) else np.nan
        best = entry
        exit_p, exit_i, why = None, None, None
        for j in range(e_i, min(n, e_i + max_bars)):
            # stop
            if (s == 1 and l[j] <= stop) or (s == -1 and h[j] >= stop):
                # gap oltre lo stop: esci all'apertura
                exit_p = min(o[j], stop) if s == 1 else max(o[j], stop)
                exit_i, why = j, "SL"
                break
            if np.isfinite(tp) and ((s == 1 and h[j] >= tp) or (s == -1 and l[j] <= tp)):
                exit_p, exit_i, why = tp, j, "TP"
                break
            if trail and not np.isfinite(tp):
                best = max(best, h[j]) if s == 1 else min(best, l[j])
                stop = max(stop, best - d) if s == 1 else min(stop, best + d)
        if exit_p is None:
            exit_i = min(n - 1, e_i + max_bars - 1)
            exit_p, why = c[exit_i], "TIME"
        r = (s * (exit_p - entry) - cost_pips * pip) / d
        trades.append(dict(entry_time=idx[e_i], exit_time=idx[exit_i], side=s, entry=entry,
                           exit=exit_p, sl_pips=d / pip, R=r, why=why))
        i = exit_i + 1
    t = pd.DataFrame(trades)
    if t.empty:
        return t, {}
    eq = start_balance * np.cumprod(1 + risk * t["R"].values)
    t["equity"] = eq
    return t, stats(t, start_balance, risk, idx)


def stats(t, start, risk, idx):
    eq = np.concatenate([[start], t["equity"].values])
    peak = np.maximum.accumulate(eq)
    dd = (eq / peak - 1).min()
    weeks = (idx[-1] - idx[0]).days / 7
    # perdita giornaliera peggiore (sulle chiusure)
    t2 = t.copy()
    t2["day"] = pd.to_datetime(t2["exit_time"]).dt.date
    daily = t2.groupby("day")["R"].sum() * risk
    wins = t["R"] > 0
    gp, gl = t.loc[wins, "R"].sum(), -t.loc[~wins, "R"].sum()
    return dict(
        trades=len(t), trades_week=round(len(t) / weeks, 2),
        winrate=round(wins.mean() * 100, 1), avg_R=round(t["R"].mean(), 3),
        profit_factor=round(gp / gl, 2) if gl > 0 else np.inf,
        return_pct=round((eq[-1] / start - 1) * 100, 1),
        max_dd_pct=round(dd * 100, 1),
        worst_day_pct=round(daily.min() * 100, 2),
    )


def ftmo_sim(t, risk, start=100_000, target=0.10, max_loss=0.10, daily=0.05, days=None):
    """Simula challenge consecutive: dall'inizio di ogni mese parte una challenge.
    Passata = +10% prima di toccare -10% totale o -5% in un giorno. Nessun limite di tempo (come FTMO oggi)."""
    if t.empty:
        return {}
    t = t.copy()
    t["exit_time"] = pd.to_datetime(t["exit_time"])
    starts = pd.date_range(t["entry_time"].min().normalize(), t["entry_time"].max(), freq="MS", tz="UTC")
    res = []
    for st in starts:
        sub = t[t["entry_time"] >= st]
        bal, outcome, dur = start, "aperta", None
        day_start, cur_day = start, None
        for _, row in sub.iterrows():
            dday = row["exit_time"].date()
            if dday != cur_day:
                cur_day, day_start = dday, bal
            bal *= 1 + risk * row["R"]
            if bal <= start * (1 - max_loss) or bal <= day_start - start * daily:
                outcome = "bocciata"
            elif bal >= start * (1 + target):
                outcome = "passata"
            if outcome != "aperta":
                dur = (row["exit_time"] - st).days
                break
        res.append((st.date(), outcome, dur))
    r = pd.DataFrame(res, columns=["start", "esito", "giorni"])
    closed = r[r.esito != "aperta"]
    return dict(challenge=len(r), passate=int((r.esito == "passata").sum()),
                bocciate=int((r.esito == "bocciata").sum()), aperte=int((r.esito == "aperta").sum()),
                giorni_medi_pass=round(closed[closed.esito == "passata"]["giorni"].mean(), 0) if len(closed) else None), r
