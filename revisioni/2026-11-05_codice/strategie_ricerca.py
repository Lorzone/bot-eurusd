"""Strategie provate nella revisione del 2026-11-05 (NON in gara). Vedi revisioni/2026-11-05.md."""
import numpy as np
import pandas as pd
from strategies import ema, rsi, atr, to_4h, align_4h


# ---------- strategia D: opening-range breakout sull'indice USA (sessione di New York) ----------
def session_orb(df, side="both", stop="mid", tp_r=2.0, last_entry="12:30", exit_bar="14:30",
                tz="America/New_York", **_):
    """Candele 1h del CFD/indice cash (09:30, 10:30, ... ora di New York).
    Range = prima candela (09:30-10:30). Segnale = prima candela successiva che CHIUDE oltre il range
    (entro la candela delle `last_entry`), max 1 trade al giorno. Stop al centro ("mid") o all'estremo
    opposto ("opp") del range, target tp_r x rischio (NaN = nessun target).
    force_exit: 1 = chiudi alla chiusura della candela delle `exit_bar` (15:30 NY, prima delle 15:55);
                2 = chiudi all'apertura (prima candela di una nuova sessione: rete di sicurezza per i giorni corti)."""
    df = df.copy()
    loc = df.index.tz_convert(tz)
    hm = loc.strftime("%H:%M")
    day = pd.Series(loc.date, index=df.index)
    first = hm == "09:30"
    rng_hi = df["high"].where(first).groupby(day).transform("max")
    rng_lo = df["low"].where(first).groupby(day).transform("min")
    win = (hm > "09:30") & (hm <= last_entry)
    long_ = win & (df["close"] > rng_hi)
    short = win & (df["close"] < rng_lo)
    if side == "long":
        short &= False
    sig = pd.Series(np.where(long_, 1, np.where(short, -1, 0)), index=df.index)
    n = sig.ne(0).groupby(day).cumsum()
    sig = sig.where((n == 1) & sig.ne(0), 0)
    lvl = (rng_hi + rng_lo) / 2 if stop == "mid" else pd.Series(np.where(sig > 0, rng_lo, rng_hi), index=df.index)
    df["signal"] = sig
    df["sl_dist"] = np.where(sig > 0, df["close"] - lvl, np.where(sig < 0, lvl - df["close"], np.nan))
    df["tp_dist"] = tp_r * df["sl_dist"]
    fe = pd.Series(0, index=df.index)
    fe[hm >= exit_bar] = 1
    fe[day.ne(day.shift()).values & (np.arange(len(df)) > 0)] = 2
    df["force_exit"] = fe
    return df




# ---------- strategia E (ricerca): oversold bounce / bull flag su 4h, solo long sopra la SMA200 ----------
def index_swing_4h(df, setup="bounce", sl_atr=2.5, tp_r=2.0, rsi_lo=30, pole=0.03, flag=0.015, **_):
    """Adattamento a 4h delle regole del trader-scanner: 'bounce' = RSI14 4h sotto rsi_lo alla candela prima
    e chiusura in rialzo; 'flag' = +pole nelle 10 candele 4h prima delle ultime 5, ultime 5 chiusure in un
    range < flag. Sempre sopra la SMA200 4h. Ingresso alla chiusura della 4h; stop sl_atr x ATR 4h."""
    df = df.copy()
    h4 = to_4h(df)
    c = h4["close"]
    above = c > c.rolling(200).mean()
    if setup == "bounce":
        r = rsi(c, 14)
        s4 = (r.shift() < rsi_lo) & (c > c.shift()) & above
    else:
        p = c.shift(5) / c.shift(15) - 1
        w = c.rolling(5).max() / c.rolling(5).min() - 1
        s4 = (p > pole) & (w < flag) & above
        s4 = s4 & ~s4.shift(fill_value=False)
    sig4 = pd.Series(np.where(s4, 1, 0), index=h4.index)
    df["signal"] = align_4h(sig4, df.index).fillna(0)
    closes = align_4h(pd.Series(h4.index, index=h4.index), df.index)
    df["signal"] = df["signal"].where(closes != closes.shift(), 0)
    df["sl_dist"] = sl_atr * align_4h(atr(h4), df.index)
    df["tp_dist"] = tp_r * df["sl_dist"]
    return df
