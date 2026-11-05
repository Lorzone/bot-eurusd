import pandas as pd, numpy as np, sys
sys.path.insert(0,str(__import__("pathlib").Path(__file__).resolve().parents[2]))
from strategies import rsi, atr
def load(f):
    d=pd.read_csv(f"{__import__('pathlib').Path(__file__).resolve().parents[2]}/data/{f}.csv",index_col=0); d.index=pd.to_datetime(d.index,utc=True); return d[["open","high","low","close"]].dropna()
def setups(d):
    c=d.close; r=rsi(c,14); sma=c.rolling(200).mean()
    ob=(r.shift()<30)&(c>c.shift())&(c>sma)
    pole=c.shift(5)/c.shift(15)-1; w5=c.rolling(5).max()/c.rolling(5).min()-1
    bf=(pole>0.10)&(w5<0.05)&(c>sma)
    bf=bf&~bf.shift().fillna(False)
    return {"oversold_bounce":ob,"bull_flag":bf}
def sim(d,sig,k,tp,hold=10,cost=0.0):
    a=atr(d).values;o,h,l,c=d.open.values,d.high.values,d.low.values,d.close.values;s=sig.values;R=[];T=[];i=0
    while i<len(d)-1:
        if not s[i] or not np.isfinite(a[i]): i+=1;continue
        e=o[i+1];sd=k*a[i];st=e-sd;tg=e+tp*sd if tp else np.inf;res=None
        for j in range(i+1,min(i+1+hold,len(d))):
            if l[j]<=st: res=(min(o[j],st)-e)/sd;break
            if h[j]>=tg: res=tp;break
        else: res=(c[j]-e)/sd
        R.append(res-cost/sd);T.append(d.index[i]);i=j+1
    return pd.Series(R,index=T)
for f,cost,start in (("ndx_1d",2,"1990"),("spx_1d",0.5,"1990"),("dji_1d",3,"1993"),("dax_1d",2,"1990")):
    d=load(f); d=d[d.index>=start]; yrs=(d.index[-1]-d.index[0]).days/365.25
    for name,sig in setups(d).items():
        for k in (1.5,2.5):
            for tp in (1.0,2.0,None):
                R=sim(d,sig,k,tp,cost=cost); rec=R[R.index>="2016"]
                print(f"{f:7}{name:16} k{k} tp{tp}  n={len(R):4} tr/sett={len(R)/yrs/52:.2f}  R={R.mean():+.3f}  R(2016+)={rec.mean():+.3f} n2016={len(rec)}")
