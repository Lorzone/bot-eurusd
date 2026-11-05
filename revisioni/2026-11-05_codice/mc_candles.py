"""Time Machine adattata: storie sintetiche di candele 1h costruite pescando a caso blocchi di 4 settimane reali
(le stesse settimane per tutti gli strumenti, così resta la correlazione), poi il motore vero (engine.backtest)
gioca la challenge fase 1 (+10% / -10% / -5% giornaliero). 60 settimane: 8 di riscaldamento + 52 di challenge."""
import sys, json, numpy as np, pandas as pd, warnings, time
warnings.filterwarnings("ignore"); sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parents[2]))
from engine import backtest, BOTS
def load(f):
    d = pd.read_csv(f"{__import__('pathlib').Path(__file__).resolve().parents[2]}/data/{f.lower()}_1h.csv", index_col=0); d.index = pd.to_datetime(d.index, utc=True); return d[["open","high","low","close"]]
syms = ("EURUSD","GBPUSD","AUDUSD","XAUUSD")
data = {s: load(s) for s in syms}
wk = {s: ((d.index + pd.Timedelta(hours=2)).tz_localize(None).to_period("W-SUN")) for s, d in data.items()}
common = sorted(set.intersection(*[set(w.unique()) for w in wk.values()]))[1:-1]  # settimane complete comuni
groups = {s: {p: g for p, g in data[s].groupby(wk[s])} for s in syms}
prev_close = {s: {} for s in syms}
for s in syms:
    keys = sorted(groups[s]); 
    for a, b in zip(keys[:-1], keys[1:]): prev_close[s][b] = groups[s][a]["close"].iloc[-1]
common = [p for p in common if all(p in prev_close[s] for s in syms)]
NB, BLK, WARM = 15, 4, 8   # 15 blocchi da 4 settimane = 60 settimane
base_week = common[0]
def path(rng):
    starts = rng.integers(0, len(common) - BLK, NB)
    seq = [common[i + j] for i in starts for j in range(BLK)]
    out = {}
    for s in syms:
        px = data[s]["close"].iloc[0]; parts = []
        for k, p in enumerate(seq):
            g = groups[s][p]; f = px / prev_close[s][p]
            g = g * f
            g.index = g.index + pd.Timedelta(weeks=(k - (p - base_week).n))
            parts.append(g); px = g["close"].iloc[-1]
        out[s] = pd.concat(parts)
    return out
N = int(sys.argv[1]) if len(sys.argv) > 1 else 100
rng = np.random.default_rng(19)
res = {b: [] for b in BOTS}
tic = time.time()
for i in range(N):
    d = path(rng)
    start = d["EURUSD"].index[0] + pd.Timedelta(weeks=WARM)
    for b in BOTS:
        _, st = backtest(b, d, start=start)
        days = (pd.Timestamp(st["challenge_end"]) - start).days if st["challenge_end"] else None
        res[b].append((st["challenge"], days, (st["balance"] / 100000 - 1) * 100))
    if i % 10 == 9: print(i + 1, f"{time.time()-tic:.0f}s", flush=True)
summ = {}
for b, r in res.items():
    r = pd.DataFrame(r, columns=["esito", "giorni", "rend"])
    summ[b] = dict(paths=len(r), passata=round((r.esito == "PASSATA").mean() * 100, 1),
                   bocciata=round((r.esito == "BOCCIATA").mean() * 100, 1), in_corso_dopo_1_anno=round((r.esito == "in corso").mean() * 100, 1),
                   giorni_mediani_pass=r[r.esito == "PASSATA"].giorni.median(), rend_mediano_pct=round(r.rend.median(), 1))
print(json.dumps(summ, indent=1, default=float)); json.dump(summ, open("mc_candles.json", "w"), indent=1, default=float)
