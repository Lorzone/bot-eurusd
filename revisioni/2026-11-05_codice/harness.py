import sys, warnings, itertools, numpy as np, pandas as pd
warnings.filterwarnings("ignore")
from pathlib import Path
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(Path(__file__).parent))
import engine
from engine import backtest, START
from strategie_ricerca import session_orb, index_swing_4h

# strumenti e strategie di ricerca registrati solo qui (engine.py resta com'è)
engine.STRATS.update(orb=session_orb, swing4h=index_swing_4h)
engine.INSTR["NAS100"] = dict(yahoo="^NDX", pip=1.0, cost=2.0, news=("USD",))
engine.INSTR["US30"] = dict(yahoo="^DJI", pip=1.0, cost=3.0, news=("USD",))
_manage = engine.Bot.manage
def _manage_fe(self, sid, t, bar):
    """come engine.Bot.manage + chiusura forzata a fine sessione (colonna force_exit: 1 = alla chiusura, 2 = all'apertura)"""
    p = self.s["positions"].get(sid); fe = bar.get("force_exit", 0)
    if p and fe == 2:
        p["bars"] += 1
        return self.close(sid, bar["open"], t, "FINE SESSIONE")
    _manage(self, sid, t, bar)
    if fe == 1 and sid in self.s["positions"]:
        self.close(sid, bar["close"], t + pd.Timedelta(hours=1), "FINE SESSIONE")
engine.Bot.manage = _manage_fe

def load(f):
    d = pd.read_csv(ROOT / "data" / f"{f}.csv", index_col=0); d.index = pd.to_datetime(d.index, utc=True)
    return d[["open", "high", "low", "close"]]

def run(name, slots, data, risk, t0, split, challenges=True, max_open=None, months=None):
    engine.BOTS[name] = dict(desc=name, risk=risk, slots=slots, **({"max_open": max_open} if max_open else {}))
    tr, st = backtest(name, data)
    if len(tr) == 0:
        return dict(n=0)
    tr["entry_time"] = pd.to_datetime(tr.entry_time, utc=True); tr = tr[tr.entry_time >= t0]
    end = max(d.index[-1] for d in data.values())
    weeks = (end - t0).days / 7
    eq = np.concatenate([[START], START + tr.pnl.cumsum().values]); dd = (eq / np.maximum.accumulate(eq) - 1).min()
    ins, oos = tr[tr.entry_time < split], tr[tr.entry_time >= split]
    out = dict(n=len(tr), tps=round(len(tr) / weeks, 2), R=round(tr.R.mean(), 3), R_is=round(ins.R.mean(), 3),
               R_oos=round(oos.R.mean(), 3), n_oos=len(oos), win=round((tr.R > 0).mean() * 100, 1),
               ret=round(tr.pnl.sum() / START * 100, 1), dd=round(dd * 100, 1))
    if challenges:
        res = []
        for m in (months if months is not None else pd.date_range(t0.normalize() + pd.offsets.MonthBegin(0), end - pd.Timedelta(days=20), freq="MS")):
            _, s = backtest(name, data, start=m)
            dd_ = (pd.Timestamp(s["challenge_end"]) - m).days if s["challenge_end"] else None
            res.append((s["challenge"], dd_))
        r = pd.DataFrame(res, columns=["esito", "giorni"])
        out.update(pass_=int((r.esito == "PASSATA").sum()), fail=int((r.esito == "BOCCIATA").sum()),
                   open_=int((r.esito == "in corso").sum()), gg_pass=r[r.esito == "PASSATA"].giorni.median())
    return out, tr
