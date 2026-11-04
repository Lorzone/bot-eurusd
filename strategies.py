"""Strategie swing EUR/USD su 1h/4h.

Ogni strategia riceve un DataFrame 1h (open/high/low/close, indice UTC)
e restituisce lo stesso DataFrame con le colonne:
  signal : +1 long, -1 short, 0 niente (valutato a chiusura candela)
  sl_dist: distanza dello stop in prezzo
  tp_dist: distanza del take profit in prezzo (NaN = nessun TP, solo trailing)
L'ingresso avviene all'apertura della candela successiva.
"""
import numpy as np
import pandas as pd


# ---------- indicatori ----------
def ema(s, n):
    return s.ewm(span=n, adjust=False).mean()


def rsi(s, n=14):
    d = s.diff()
    up = d.clip(lower=0).ewm(alpha=1 / n, adjust=False).mean()
    dn = (-d.clip(upper=0)).ewm(alpha=1 / n, adjust=False).mean()
    return 100 - 100 / (1 + up / dn.replace(0, np.nan))


def atr(df, n=14):
    pc = df["close"].shift()
    tr = pd.concat([df["high"] - df["low"], (df["high"] - pc).abs(), (df["low"] - pc).abs()], axis=1).max(axis=1)
    return tr.ewm(alpha=1 / n, adjust=False).mean()


def to_4h(df):
    """Ricampiona a 4h e riporta sull'1h SOLO le candele 4h già chiuse (niente look-ahead)."""
    h4 = df.resample("4h", label="right", closed="left").agg(
        {"open": "first", "high": "max", "low": "min", "close": "last"}).dropna()
    return h4


def align_4h(series_4h, idx_1h):
    # una candela 4h etichettata alle 08:00 (right label) è chiusa alle 08:00:
    # è disponibile per la candela 1h che CHIUDE alle 08:00, cioè quella che apre alle 07:00.
    s = series_4h.copy()
    s.index = s.index - pd.Timedelta(hours=1)
    return s.reindex(idx_1h, method="ffill")


# ---------- strategia A: trend 4h + pullback 1h ----------
def trend_pullback(df, ema_fast=50, ema_slow=200, rsi_n=14, rsi_lo=40, rsi_hi=60,
                   sl_atr=1.5, tp_r=2.0, **_):
    df = df.copy()
    h4 = to_4h(df)
    up = align_4h((ema(h4["close"], ema_fast) > ema(h4["close"], ema_slow)).astype(float), df.index)
    dn = align_4h((ema(h4["close"], ema_fast) < ema(h4["close"], ema_slow)).astype(float), df.index)
    r = rsi(df["close"], rsi_n)
    a = atr(df)
    long_ = (up == 1) & (r.shift() < rsi_lo) & (r >= rsi_lo)
    short = (dn == 1) & (r.shift() > rsi_hi) & (r <= rsi_hi)
    df["signal"] = np.where(long_, 1, np.where(short, -1, 0))
    df["sl_dist"] = sl_atr * a
    df["tp_dist"] = tp_r * sl_atr * a
    return df


# ---------- strategia B: breakout Donchian su 4h ----------
def donchian_breakout(df, n=20, sl_atr=2.0, tp_r=np.nan, **_):
    df = df.copy()
    h4 = to_4h(df)
    hi = h4["high"].rolling(n).max().shift()
    lo = h4["low"].rolling(n).min().shift()
    a4 = atr(h4)
    sig4 = np.where(h4["close"] > hi, 1, np.where(h4["close"] < lo, -1, 0))
    sig4 = pd.Series(sig4, index=h4.index)
    # segnale solo sul primo breakout (evita ingressi ripetuti)
    sig4 = sig4.where(sig4 != sig4.shift(), 0)
    df["signal"] = align_4h(sig4, df.index).fillna(0)
    # il segnale deve valere una sola candela 1h: quella in cui la 4h si chiude
    closes = align_4h(pd.Series(h4.index, index=h4.index), df.index)
    df["signal"] = df["signal"].where(closes != closes.shift(), 0)
    df["sl_dist"] = sl_atr * align_4h(a4, df.index)
    df["tp_dist"] = tp_r * df["sl_dist"]
    return df


# ---------- strategia C: breakout del range asiatico (sessione di Londra) ----------
def london_breakout(df, asia_start=0, asia_end=7, entry_until=11, buffer_atr=0.1,
                    tp_r=1.5, min_range_atr=0.5, max_range_atr=3.0, ema_filter=200, **_):
    """Range 00-07 UTC; se una candela 1h tra 07 e 11 chiude fuori dal range -> ingresso.
    Stop all'altro estremo del range, TP = tp_r * rischio. Max 1 trade al giorno."""
    df = df.copy()
    a = atr(df, 24)
    h = df.index.hour
    day = df.index.normalize()
    in_asia = (h >= asia_start) & (h < asia_end)
    rng_hi = df["high"].where(in_asia).groupby(day).transform("max")
    rng_lo = df["low"].where(in_asia).groupby(day).transform("min")
    width = rng_hi - rng_lo
    ok = (width > min_range_atr * a) & (width < max_range_atr * a) & (h >= asia_end) & (h < entry_until)
    buf = buffer_atr * a
    trend = ema(df["close"], ema_filter) if ema_filter else None
    long_ = ok & (df["close"] > rng_hi + buf)
    short = ok & (df["close"] < rng_lo - buf)
    if trend is not None:
        long_ &= df["close"] > trend
        short &= df["close"] < trend
    sig = pd.Series(np.where(long_, 1, np.where(short, -1, 0)), index=df.index)
    # solo il primo segnale della giornata
    first = sig.ne(0).groupby(day).cumsum()
    sig = sig.where((first == 1) & sig.ne(0), 0)
    df["signal"] = sig
    df["sl_dist"] = np.where(sig > 0, df["close"] - rng_lo, rng_hi - df["close"])
    df["tp_dist"] = tp_r * df["sl_dist"]
    return df


STRATEGIES = {
    "trend_pullback": trend_pullback,
    "donchian_breakout": donchian_breakout,
    "london_breakout": london_breakout,
}
