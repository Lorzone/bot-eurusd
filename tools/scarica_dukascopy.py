"""Scarica le candele a 1 minuto di Dukascopy (BID) e le salva a 5 minuti.

Uso: python3 tools/scarica_dukascopy.py SIMBOLO DATA_INIZIO [DATA_FINE]
  es. python3 tools/scarica_dukascopy.py EURUSD 2019-01-01
Output: dati/<SIMBOLO>_5m.csv.gz (UTC, open/high/low/close/volume)

Formato Dukascopy: un file lzma al giorno, record da 24 byte big-endian:
secondi dalla mezzanotte, open, close, low, high (interi) e volume (float).
"""
import io
import lzma
import struct
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pandas as pd
import requests

SCALE = {"EURUSD": 1e5, "GBPUSD": 1e5, "AUDUSD": 1e5, "XAUUSD": 1e3,
         "USATECHIDXUSD": 1e3, "USA30IDXUSD": 1e3, "USA500IDXUSD": 1e3, "DEUIDXEUR": 1e3}
URL = "https://datafeed.dukascopy.com/datafeed/{s}/{y}/{m:02d}/{d:02d}/BID_candles_min_1.bi5"
FAILED = []
S = requests.Session()
S.headers["User-Agent"] = "Mozilla/5.0"


def day(sym, dt):
    url = URL.format(s=sym, y=dt.year, m=dt.month - 1, d=dt.day)  # mese 0-based
    for k in range(10):
        try:
            r = S.get(url, timeout=30)
        except requests.RequestException:
            time.sleep(2 + 2 * k)
            continue
        if r.status_code == 404 or (r.status_code == 200 and not r.content):
            return None
        if r.status_code == 200:
            try:
                b = lzma.decompress(r.content)
            except lzma.LZMAError:
                time.sleep(2 + 2 * k)
                continue
            n = len(b) // 24
            rows = [struct.unpack(">5if", b[i * 24:(i + 1) * 24]) for i in range(n)]
            df = pd.DataFrame(rows, columns=["s", "open", "close", "low", "high", "volume"])
            df = df[df.volume > 0]  # minuti senza scambi (mercato chiuso)
            if df.empty:
                return None
            sc = SCALE[sym]
            for c in ("open", "close", "low", "high"):
                df[c] = df[c] / sc
            df.index = pd.Timestamp(dt, tz="UTC") + pd.to_timedelta(df.pop("s"), unit="s")
            return df
        time.sleep(2 + 2 * k)  # 503 / 429: riprova più piano
    FAILED.append(dt.strftime("%Y-%m-%d"))
    return None


def main():
    sym, start = sys.argv[1], sys.argv[2]
    end = sys.argv[3] if len(sys.argv) > 3 else pd.Timestamp.now(tz="UTC").strftime("%Y-%m-%d")
    days = [d for d in pd.date_range(start, end, freq="D") if d.weekday() != 5]  # sabato sempre chiuso
    t0 = time.time()
    with ThreadPoolExecutor(8) as ex:
        parts = list(ex.map(lambda d: day(sym, d), days))
    # secondo giro, lento, sui giorni falliti
    retry = list(FAILED)
    FAILED.clear()
    for ds in retry:
        time.sleep(3)
        parts.append(day(sym, pd.Timestamp(ds)))
    m1 = pd.concat([p for p in parts if p is not None]).sort_index()
    m1 = m1[~m1.index.duplicated()]
    m5 = m1.resample("5min", label="left", closed="left").agg(
        {"open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"}).dropna()
    out = Path("dati")
    out.mkdir(exist_ok=True)
    m5.to_csv(out / f"{sym}_5m.csv.gz", float_format="%.6g", compression="gzip")
    print(f"{sym}: {len(days)} giorni, {len(m1)} minuti -> {len(m5)} candele 5m "
          f"da {m5.index[0]} a {m5.index[-1]} in {time.time() - t0:.0f}s · giorni falliti: {len(FAILED)} {FAILED[:20]}")
    if len(FAILED) > max(3, 0.02 * len(days)):
        sys.exit(f"troppi giorni falliti ({len(FAILED)})")


if __name__ == "__main__":
    main()
