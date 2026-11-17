"""Costruisce, per ogni giorno 2020-2026, i dati della prima ora e il percorso 5m dalle 10:30 alle 15:55 NY (Dukascopy)."""
import pandas as pd, numpy as np, pickle
df=pd.read_csv("/home/claude/bot-eurusd/dati/USATECHIDXUSD_5m.csv.gz"); df.index=pd.to_datetime(df.pop("s"),utc=True)
loc=df.index.tz_convert("America/New_York"); lm=(loc.hour*60+loc.minute).to_numpy(); day=loc.normalize()
o,h,l,c=(df[k].to_numpy(float) for k in ("open","high","low","close"))
rows=[]; paths={}
days=pd.unique(day); groups={}
for d in days: groups[d]=np.flatnonzero(day==d)
rng={}
for d in days:
    ix=groups[d]; r=ix[(lm[ix]>=570)&(lm[ix]<960)]
    rng[d]=(h[r].max()-l[r].min()) if len(r)>12 else np.nan
rng=pd.Series(rng); atr=rng.dropna().rolling(14).mean().reindex(rng.index).ffill().shift(1)
prevclose=None
for d in days:
    ix=groups[d]; r=ix[(lm[ix]>=570)&(lm[ix]<960)]
    if len(r)<=12: continue
    fh=ix[(lm[ix]>=570)&(lm[ix]<630)]; body=ix[(lm[ix]>=630)&(lm[ix]<955)]
    pre=ix[(lm[ix]<570)]
    if len(fh)<10 or len(body)<5: prevclose=c[r[-1]]; continue
    f30=ix[(lm[ix]>=570)&(lm[ix]<600)]
    rows.append(dict(day=pd.Timestamp(d).tz_localize(None), atr=atr.get(d,np.nan), o930=o[fh[0]], c1030=c[fh[-1]],
        fh_hi=h[fh].max(), fh_lo=l[fh].min(), m30=c[f30[-1]]-o[fh[0]] if len(f30) else np.nan,
        gap=(o[fh[0]]-prevclose) if prevclose is not None else np.nan, entry=o[body[0]],
        close1555=c[body[-1]], close1600=c[r[-1]], dayrange=rng[d], wd=pd.Timestamp(d).weekday()))
    paths[pd.Timestamp(d).tz_localize(None)]=dict(lm=lm[body],o=o[body],h=h[body],l=l[body],c=c[body])
    prevclose=c[r[-1]]
D=pd.DataFrame(rows).set_index("day"); D["mv"]=D.c1030-D.o930
pickle.dump((D,paths),open("/home/claude/ri2/days.pkl","wb")); print(len(D), D.index.min(), D.index.max())
