"""Backtest dei bot A-D con il motore live + challenge simulate (una che parte ogni mese)."""
import time, json, warnings, numpy as np, pandas as pd
warnings.filterwarnings("ignore")
from engine import BOTS, backtest, START
def load(f):
    d=pd.read_csv(f"data/{f.lower()}_1h.csv",index_col=0); d.index=pd.to_datetime(d.index,utc=True); return d
data={s:load(s) for s in ("EURUSD","GBPUSD","AUDUSD","XAUUSD")}
t0=pd.Timestamp("2024-07-01",tz="UTC")   # inizio comune (dati oro da giugno 2024 + 200 candele 4h di riscaldamento)
split=pd.Timestamp("2025-09-19",tz="UTC")
out={}
import sys
names=sys.argv[1:] or list(BOTS)
for name in names:
    tic=time.time()
    tr,st=backtest(name,data,start=None)
    tr["entry_time"]=pd.to_datetime(tr.entry_time,utc=True); tr=tr[tr.entry_time>=t0]
    weeks=(data["EURUSD"].index[-1]-t0).days/7
    eq=np.concatenate([[START],START+tr.pnl.cumsum().values]); dd=(eq/np.maximum.accumulate(eq)-1).min()
    oos=tr[tr.entry_time>=split]
    # challenge: una ogni mese, motore completo
    res=[]
    for m in pd.date_range("2024-07-01","2026-10-01",freq="MS",tz="UTC"):
        _,s=backtest(name,data,start=m)
        d=(pd.Timestamp(s["challenge_end"])-m).days if s["challenge_end"] else None
        res.append((s["challenge"],d))
    r=pd.DataFrame(res,columns=["esito","giorni"])
    out[name]=dict(desc=BOTS[name]["desc"],trade_sett=round(len(tr)/weeks,2),R_medio=round(tr.R.mean(),3),
                   R_oos=round(oos.R.mean(),3),winrate=round((tr.R>0).mean()*100,1),
                   rend_pct=round(tr.pnl.sum()/START*100,1),max_dd=round(dd*100,1),
                   pass_=int((r.esito=="PASSATA").sum()),fail=int((r.esito=="BOCCIATA").sum()),
                   aperte=int((r.esito=="in corso").sum()),giorni_pass=r[r.esito=="PASSATA"].giorni.median(),
                   r_medio_per_trade_atteso=round(tr.R.mean(),3))
    tr.to_csv(f"backtest_{name}.csv",index=False)
    print(name,out[name],f"{time.time()-tic:.0f}s",flush=True)
json.dump(out,open(f"expected_{''.join(names)}.json","w"),indent=1,default=float)
