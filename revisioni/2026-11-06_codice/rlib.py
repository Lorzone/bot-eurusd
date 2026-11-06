"""Strumenti comuni della ricerca intraday del 6 novembre 2026.

Dati: dati/<SIMBOLO>_5m.csv.gz (Dukascopy BID, UTC, 's' = apertura candela).
Esecuzione su candele a 5 minuti con ordini calcolati in anticipo:
  - ordine stop (breakout) o a mercato all'apertura di una candela, valido in una finestra
  - stop e target fissi, uscita forzata alla chiusura di una candela prestabilita
  - stessa candela con stop e target -> stop; gap oltre il livello -> eseguito all'apertura
Costi (in prezzo): spread+commissione sempre, slittamento su ingresso a mercato/stop e
su uscita a stop o forzata (il target è un ordine limite, senza slittamento).
"""
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
SPLIT = pd.Timestamp("2024-01-01", tz="UTC")

SYM = {  # file, costo fisso, slittamento, unità
    "EURUSD": dict(file="EURUSD", cost=1.4e-4, slip=0.2e-4),
    "GBPUSD": dict(file="GBPUSD", cost=1.8e-4, slip=0.2e-4),
    "XAUUSD": dict(file="XAUUSD", cost=0.40, slip=0.10),
    "NAS100": dict(file="USATECHIDXUSD", cost=1.5, slip=0.1),
    "US30": dict(file="USA30IDXUSD", cost=3.0, slip=0.1),
}


class Data:
    """Candele di un simbolo raggruppate per giorno locale (tz)."""

    def __init__(self, sym, tz):
        self.sym, self.tz = sym, tz
        df = pd.read_csv(ROOT / "dati" / f"{SYM[sym]['file']}_5m.csv.gz")
        t = pd.to_datetime(df["s"], utc=True)
        df = df.drop(columns="s")
        df.index = t
        df = df[~df.index.duplicated()].sort_index()
        self.df = df
        self.o, self.h, self.l, self.c = (df[k].to_numpy(float) for k in ("open", "high", "low", "close"))
        self.t = df.index
        loc = df.index.tz_convert(tz)
        self.lmin = (loc.hour * 60 + loc.minute).to_numpy()
        self.umin = (df.index.hour * 60 + df.index.minute).to_numpy()
        ld = loc.normalize().tz_localize(None)
        codes, uniq = pd.factorize(ld)
        self.days = pd.DatetimeIndex(uniq)
        starts = np.r_[0, np.flatnonzero(np.diff(codes)) + 1]
        ends = np.r_[starts[1:], len(codes)]
        self.slices = list(zip(starts, ends))
        self.cost, self.slip = SYM[sym]["cost"], SYM[sym]["slip"]

    def win(self, k, m0, m1, utc=False):
        """Indici (assoluti) delle candele del giorno k con minuto locale (o UTC) in [m0, m1)."""
        a, b = self.slices[k]
        mm = (self.umin if utc else self.lmin)[a:b]
        return a + np.flatnonzero((mm >= m0) & (mm < m1))

    def daily_close(self, m_close):
        """Chiusura giornaliera = close dell'ultima candela prima del minuto locale m_close."""
        out = np.full(len(self.slices), np.nan)
        for k in range(len(self.slices)):
            ix = self.win(k, 0, m_close)
            if len(ix):
                out[k] = self.c[ix[-1]]
        return out


def hm(s):
    h, m = s.split(":")
    return int(h) * 60 + int(m)


def execute(D, orders, i_exit):
    """orders: lista di (side, kind, level, i_from, i_to, stop, tp) in OCO; il primo eseguito vince.
    i_exit: indice dell'ultima candela, uscita forzata alla sua chiusura.
    Ritorna dict del trade o None."""
    o, h, l, c = D.o, D.h, D.l, D.c
    best = None
    for od in orders:
        side, kind, level, i0, i1, stop, tp = od
        if i1 < i0:
            continue
        if kind == "market":
            ie, fill = i0, o[i0]
        else:
            seg = h[i0:i1 + 1] >= level if side == 1 else l[i0:i1 + 1] <= level
            if not seg.any():
                continue
            ie = i0 + int(np.argmax(seg))
            fill = max(o[ie], level) if side == 1 else min(o[ie], level)
        if best is None or ie < best[0]:
            best = (ie, fill, od)
    if best is None:
        return None
    ie, fill, (side, kind, level, i0, i1, stop, tp) = best
    risk = abs((level if kind != "market" else fill) - stop)
    if risk <= 0:
        return None
    worst, why, px, ix = fill, "FINE", None, None
    for i in range(ie, i_exit + 1):
        if side == 1:
            worst = min(worst, l[i])
            if l[i] <= stop:
                px, why = (stop if i == ie else min(o[i], stop)), "STOP"
            elif tp is not None and h[i] >= tp:
                px, why = tp, "TARGET"
        else:
            worst = max(worst, h[i])
            if h[i] >= stop:
                px, why = (stop if i == ie else max(o[i], stop)), "STOP"
            elif tp is not None and l[i] <= tp:
                px, why = tp, "TARGET"
        if px is not None:
            ix = i
            break
    if px is None:
        ix, px = i_exit, c[i_exit]
    slip = D.slip * (1 + (why != "TARGET"))
    R = (side * (px - fill) - D.cost - slip) / risk
    mae = min(0.0, side * (worst - fill)) / risk - (D.cost + slip) / risk
    return dict(sym=D.sym, side=side, entry_time=D.t[ie], exit_time=D.t[ix] + pd.Timedelta(minutes=5),
                entry=fill, exit=px, stop=stop, tp=tp, risk=risk, R=R, mae=min(mae, R), why=why)


# ---------------- statistiche ----------------
def pf(r):
    g, p = r[r > 0].sum(), -r[r < 0].sum()
    return g / p if p > 0 else np.inf


def summary(tr, label=""):
    if tr is None or len(tr) == 0:
        return dict(label=label, n=0)
    tr = tr.sort_values("entry_time")
    sel, ver = tr[tr.entry_time < SPLIT], tr[tr.entry_time >= SPLIT]
    weeks_sel = (SPLIT - pd.Timestamp("2020-01-01", tz="UTC")).days / 7
    weeks_ver = (pd.Timestamp("2026-11-06", tz="UTC") - SPLIT).days / 7
    yrs = {y: round(g.R.mean(), 3) for y, g in ver.groupby(ver.entry_time.dt.year)}
    return dict(label=label, n_sel=len(sel), tw_sel=round(len(sel) / weeks_sel, 2), R_sel=round(sel.R.mean(), 3),
                pf_sel=round(pf(sel.R), 2), n_ver=len(ver), tw_ver=round(len(ver) / weeks_ver, 2),
                R_ver=round(ver.R.mean(), 3) if len(ver) else np.nan, pf_ver=round(pf(ver.R), 2) if len(ver) else np.nan,
                yrs_pos=sum(v > 0 for v in yrs.values()), **{f"R{y}": v for y, v in yrs.items()})


# ---------------- conto e challenge ----------------
def account(tr, risk, start_bal=10_000, dd_halve=0.04):
    """Applica il rischio % ai trade in ordine di uscita (rischio = % del saldo all'ingresso).
    Ritorna serie del saldo e DD massimo (sul saldo, più il peggior flottante del giorno)."""
    tr = tr.sort_values("entry_time").reset_index(drop=True)
    events = []
    for i, r in tr.iterrows():
        events.append((r.entry_time, 0, i))
        events.append((r.exit_time, 1, i))
    events.sort()
    bal, peak, risk_usd = start_bal, start_bal, {}
    pnl = np.zeros(len(tr))
    maxdd = 0.0
    for t, typ, i in events:
        if typ == 0:
            rr = risk * (0.5 if bal < peak * (1 - dd_halve) else 1)
            risk_usd[i] = bal * rr
            # flottante peggiore possibile del trade appena aperto
            maxdd = min(maxdd, (bal + risk_usd[i] * tr.mae[i]) / peak - 1)
        else:
            pnl[i] = risk_usd[i] * tr.R[i]
            bal += pnl[i]
            peak = max(peak, bal)
            maxdd = min(maxdd, bal / peak - 1)
    tr = tr.assign(pnl=pnl)
    return tr, bal, maxdd


def challenges(tr, risk, t0="2020-01-01", t1="2026-11-06", target1=0.10, target2=0.05):
    """Una challenge FTMO 2-Step che parte il primo di ogni mese (10.000 $).
    Fase 1 +10%, poi fase 2 +5% (riparte da 10.000). Bocciata a -10% statico o -5% in un giorno
    (giorno da mezzanotte di Praga; peggior caso: ogni trade del giorno al suo minimo flottante)."""
    tr = tr.sort_values("entry_time").reset_index(drop=True)
    tr["pday"] = tr.entry_time.dt.tz_convert("Europe/Prague").dt.date
    res = []
    for m in pd.date_range(t0, t1, freq="MS", tz="UTC"):
        sub = tr[tr.entry_time >= m]
        state, phase, bal, peak, t_end = "aperta", 1, 10_000.0, 10_000.0, None
        for day, g in sub.groupby("pday", sort=True):
            day_start = bal
            worst = 0.0
            for _, r in g.iterrows():
                ru = bal * risk * (0.5 if bal < peak * 0.96 else 1)
                worst += ru * min(r.mae, r.R)
                bal += ru * r.R
                peak = max(peak, bal)
            if bal <= 9_000 or day_start + worst <= day_start - 500 or day_start + worst <= 9_000:
                state = "bocciata"
                t_end = day
                break
            if bal >= 10_000 * (1 + (target1 if phase == 1 else target2)):
                if phase == 1:
                    phase, bal, peak = 2, 10_000.0, 10_000.0
                    p1 = day
                else:
                    state, t_end = "passata", day
                    break
        res.append(dict(start=m.date(), state=state, phase=phase, end=t_end))
    r = pd.DataFrame(res)
    return r


def report(tr, risk, label=""):
    s = summary(tr, label)
    if not s.get("n_sel") and not s.get("n_ver"):
        return s
    _, bal, dd = account(tr[tr.entry_time >= SPLIT], risk)
    _, bal_all, dd_all = account(tr, risk)
    ch = challenges(tr, risk)
    s.update(dd_ver=round(dd * 100, 1), dd_all=round(dd_all * 100, 1), rend_ver=round((bal / 10_000 - 1) * 100, 1),
             ch_pass=int((ch.state == "passata").sum()), ch_fail=int((ch.state == "bocciata").sum()),
             ch_open=int((ch.state == "aperta").sum()))
    return s
