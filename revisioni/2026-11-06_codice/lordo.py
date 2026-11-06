"""Controllo: stesse regole senza costi (quanto vantaggio c'è prima di spread/commissioni)."""
import pandas as pd
from rlib import Data, hm, summary
from breakouts import breakout, trend_sides
from momentum_mr import meanrev, momentum, daily_atr

rows = []
for s in ("EURUSD", "GBPUSD"):
    D = Data(s, "Europe/London"); D.cost = D.slip = 0
    rows.append(summary(breakout(D, (hm("08:00"), hm("08:30")), hm("12:00"), 16 * 60, True, "opp", None), f"a {s} L30 opp tpNone ex16 LORDO"))
    rows.append(summary(breakout(D, (hm("00:00"), hm("07:00")), hm("12:00"), 20 * 60, True, "opp", None), f"a {s} asia opp tpNone ex20 LORDO"))
D = Data("EURUSD", "UTC"); D.cost = D.slip = 0
rows.append(summary(meanrev(D, 48, 2.0, 2.0, 0, 360), "e EURUSD n48 k2 s2 00-06 LORDO"))
rows.append(summary(meanrev(D, 48, 3.0, 2.0, 19 * 60, 21 * 60), "e EURUSD n48 k3 s2 19-21 LORDO"))
D = Data("NAS100", "America/New_York"); a = daily_atr(D, hm("09:30"), hm("16:00"))
D.cost = D.slip = 0
rows.append(summary(momentum(D, "on", hm("15:30"), 0.2, 0, a), "c NAS100 on in15:30 stop0.2 thr0 LORDO"))
rows.append(summary(breakout(D, (hm("09:30"), hm("10:00")), hm("12:00"), hm("15:55"), False, "opp", 2.0, trend_sides(D, hm("16:00"))), "b NAS100 OR30 opp tp2 trend1 LORDO"))
D = Data("XAUUSD", "Europe/London"); D.cost = D.slip = 0
rows.append(summary(breakout(D, (0, 420), hm("12:00"), 20 * 60, True, "opp", 2.0), "d XAU asia opp tp2 late1 LORDO"))
pd.set_option("display.width", 250, "display.max_columns", 40)
df = pd.DataFrame(rows); print(df.to_string()); df.to_csv("lordo.csv", index=False)
