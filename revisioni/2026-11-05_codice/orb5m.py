import pandas as pd, numpy as np, sys
def load(f):
    d=pd.read_csv(f"{__import__('pathlib').Path(__file__).resolve().parents[2]}/data/{f}.csv",index_col=0); d.index=pd.to_datetime(d.index,utc=True).tz_convert("America/New_York"); return d
for f,cost in (("ndx_5m",2.0),("dji_5m",3.0)):
  d=load(f)
  for orm in (30,60):
   for stop in ("mid","opp"):
    for tp in (1.0,2.0):
     for side in ("both","long"):
      Rs=[]
      for day,g in d.groupby(d.index.date):
        hm=g.index.strftime("%H:%M")
        if len(g)<70: continue
        endr=(pd.Timestamp("09:30")+pd.Timedelta(minutes=orm)).strftime("%H:%M")
        r=g[hm<endr]; hi,lo=r.high.max(),r.low.min()
        rest=g[(hm>=endr)&(hm<"15:55")]
        ent=None
        for i,(t,b) in enumerate(rest.iterrows()):
            if t.strftime("%H:%M")>"13:30": break
            s=1 if b.close>hi else (-1 if b.close<lo and side=="both" else 0)
            if s: ent=(i,s,b.close); break
        if not ent: continue
        i,s,e=ent; lvl=(hi+lo)/2 if stop=="mid" else (lo if s==1 else hi)
        sd=abs(e-lvl); tgt=e+s*tp*sd; stp=e-s*sd; R=None
        for t,b in rest.iloc[i+1:].iterrows():
            if (s==1 and b.low<=stp) or (s==-1 and b.high>=stp): R=-1;break
            if (s==1 and b.high>=tgt) or (s==-1 and b.low<=tgt): R=tp;break
            last=b.close
        if R is None: R=s*(last-e)/sd
        Rs.append(R-cost/sd)
      Rs=np.array(Rs); print(f,orm,stop,tp,side,"n",len(Rs),"R medio %.3f"%Rs.mean())
