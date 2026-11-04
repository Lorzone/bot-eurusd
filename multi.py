import pandas as pd, numpy as np, warnings; warnings.filterwarnings("ignore")
from strategies import trend_pullback
from backtest import run, stats, ftmo_sim
COST={"eurusd":1.3,"gbpusd":1.6,"usdjpy":1.5,"audusd":1.5,"usdcad":1.9,"eurjpy":2.0,"gbpjpy":2.8}
def load(f):
    d=pd.read_csv(f"data/{f}_1h.csv",index_col=0); d.index=pd.to_datetime(d.index,utc=True); return d
P=dict(ema_fast=20, ema_slow=200, rsi_lo=30, rsi_hi=70, sl_atr=2.5, tp_r=np.nan)
allt=[]
for f,c in COST.items():
    d=load(f); pip=0.01 if "jpy" in f else 0.0001
    t,s=run(trend_pullback(d,**P),cost_pips=c,pip=pip)
    print(f, s); t["pair"]=f; allt.append(t)
T=pd.concat(allt)
import sys
for risk in (0.005,0.0075,0.01):
    # portafoglio: trade ordinati per uscita, rischio fisso per trade (le sovrapposizioni sono ammesse, max un trade per coppia)
    P_=T.sort_values("exit_time").reset_index(drop=True)
    P_["equity"]=100000*np.cumprod(1+risk*P_["R"].values)
    idx=load("eurusd").index
    s=stats(P_,100000,risk,idx)
    f,_=ftmo_sim(P_,risk)
    # max posizioni aperte insieme
    ev=pd.concat([pd.Series(1,index=T.entry_time),pd.Series(-1,index=T.exit_time)]).sort_index().cumsum().max()
    print(f"\nPORTAFOGLIO rischio {risk*100}%:",s,"\n FTMO:",f,"max posizioni aperte:",ev)
T.to_csv("portfolio_trades.csv",index=False)
