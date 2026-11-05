# da eseguire dalla cartella principale del repo: python3 revisioni/2026-11-05_codice/scarica_dati.py
import yfinance as yf, pandas as pd
def save(t,name,period,interval):
    d=yf.download(t,period=period,interval=interval,progress=False,auto_adjust=False)
    d.columns=[c[0].lower() if isinstance(c,tuple) else c.lower() for c in d.columns]
    d=d[["open","high","low","close"]+(["volume"] if "volume" in d else [])].dropna(subset=["close"])
    d.index=pd.to_datetime(d.index,utc=True)
    d.to_csv(f"data/{name}.csv"); print(name,len(d),d.index[0],d.index[-1])
for t,n in [("EURUSD=X","eurusd"),("GBPUSD=X","gbpusd"),("AUDUSD=X","audusd"),("GC=F","xauusd"),("^NDX","ndx"),("^DJI","dji"),("NQ=F","nqf"),("YM=F","ymf"),("^GDAXI","dax")]:
    save(t,n+"_1h","730d","1h")
for t,n in [("^NDX","ndx"),("^DJI","dji"),("^GSPC","spx"),("^GDAXI","dax")]:
    save(t,n+"_1d","max","1d")
for t,n in [("^NDX","ndx"),("^DJI","dji"),("NQ=F","nqf")]:
    save(t,n+"_5m","60d","5m")
