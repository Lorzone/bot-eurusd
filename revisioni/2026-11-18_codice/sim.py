import numpy as np, pandas as pd, pickle
D,P=pickle.load(open("/home/claude/ri2/days.pkl","rb"))
COST=1.4
SPLIT=pd.Timestamp("2024-01-01")
def trade(d, side, stop, entry=None, tp=None, be=None, trail=None, tex=None, partial=None, start_i=0):
    p=P[d]; risk=abs((entry if entry is not None else p["o"][start_i])-stop)
    e=entry if entry is not None else p["o"][start_i]
    if risk<=0: return None
    st=stop; best=e; tgt=None if tp is None else e+side*tp*risk
    part=None if partial is None else e+side*partial*risk; part_done=False; realized=0.0
    n=len(p["o"])
    for i in range(start_i,n):
        if tex is not None and p["lm"][i]>=tex: 
            px=p["o"][i]; break
        hi,lo=p["h"][i],p["l"][i]
        if (side==1 and lo<=st) or (side==-1 and hi>=st):
            px=st if i==start_i else (min(p["o"][i],st) if side==1 else max(p["o"][i],st)); break
        if part is not None and not part_done and ((side==1 and hi>=part) or (side==-1 and lo<=part)):
            part_done=True; realized=0.5*partial
        if tgt is not None and ((side==1 and hi>=tgt) or (side==-1 and lo<=tgt)):
            px=tgt; break
        best=max(best,hi) if side==1 else min(best,lo)
        mfe=side*(best-e)/risk
        if be is not None and mfe>=be: st=max(st,e) if side==1 else min(st,e)
        if trail is not None and mfe>=trail[0]:
            ns=best-side*trail[1]*risk
            st=max(st,ns) if side==1 else min(st,ns)
    else:
        px=p["c"][n-1]
    R=side*(px-e)/risk
    if part_done: R=realized+0.5*R
    return R-COST/risk
def base_signals(th=0.1):
    s=D[(D.atr.notna())&(D.mv.abs()>=th*D.atr)].copy()
    s["side"]=np.sign(s.mv).astype(int)
    s["stop"]=np.where(s.side==1,s.fh_lo,s.fh_hi)
    s=s[(s.side*(s.entry-s.stop))>0]
    return s
def run(sig, **kw):
    R=[trade(d,int(r.side),r.stop,**kw) for d,r in sig.iterrows()]
    out=sig.assign(R=R).dropna(subset=["R"]); return out
def summ(t,lab=""):
    a=t[t.index<SPLIT].R; b=t[t.index>=SPLIT].R
    yrs=t.groupby(t.index.year).R.mean()
    return dict(label=lab,n=len(t),tw=round(len(t)/((t.index.max()-t.index.min()).days/7),2),
                R_sel=round(a.mean(),3),R_ver=round(b.mean(),3),pf_ver=round(b[b>0].sum()/-b[b<0].sum(),2),
                anni_pos=int((yrs>0).sum()),anni=len(yrs),worst=round(yrs.min(),3))
