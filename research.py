import itertools, pandas as pd, numpy as np, warnings
warnings.filterwarnings("ignore")
from strategies import STRATEGIES
from backtest import run
df = pd.read_csv("data/eurusd_1h.csv", index_col=0); df.index = pd.to_datetime(df.index, utc=True)
split = df.index[int(len(df)*0.6)]
print("in-sample fino a", split)
grids = {
 "trend_pullback": dict(rsi_lo=[30,40], rsi_hi=[60,70], sl_atr=[1.5,2.5], tp_r=[1.5,2.5,np.nan], ema_fast=[20,50]),
 "donchian_breakout": dict(n=[10,20,40], sl_atr=[1.5,2.5,3.5], tp_r=[2.0,3.0,np.nan]),
 "london_breakout": dict(tp_r=[1.0,1.5,2.0], buffer_atr=[0,0.15], ema_filter=[0,200], entry_until=[10,13]),
}
rows=[]
for name, g in grids.items():
    keys=list(g)
    for vals in itertools.product(*g.values()):
        p=dict(zip(keys,vals))
        if name=="trend_pullback" and p["rsi_lo"]+p["rsi_hi"]!=100: continue
        sig=STRATEGIES[name](df, **p)
        for part,sub in (("IS",sig[sig.index<split]),("OOS",sig[sig.index>=split])):
            t,s=run(sub)
            if s: rows.append(dict(strategy=name, part=part, **{k:v for k,v in p.items()}, **s))
r=pd.DataFrame(rows)
r.to_csv("grid_results.csv",index=False)
pcols=["strategy"]+sorted({k for g in grids.values() for k in g})
w=r.pivot_table(index=pcols,columns="part",values=["avg_R","trades_week","profit_factor","max_dd_pct","return_pct"],dropna=False).dropna(how="all")
w.columns=[f"{a}_{b}" for a,b in w.columns]
w=w.reset_index()
for name in grids:
    x=w[w.strategy==name].sort_values("avg_R_IS",ascending=False).head(6)
    print("\n==",name); print(x[[c for c in x.columns if c!='strategy' and not x[c].isna().all()]].to_string(index=False))
