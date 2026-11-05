"""Bootstrap dei trade dei backtest A-D (blocchi di 5 trade consecutivi): fase 1 (+10%) e fase 2 (+5%), stop a -10%.
Rischio come nel bot, dimezzato sotto -4% dal picco. Il limite giornaliero non è simulato (trade sequenziali)."""
import json, numpy as np, pandas as pd, sys
sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parents[2])); from engine import BOTS
exp = json.load(open(str(__import__("pathlib").Path(__file__).resolve().parents[2])+"/expected.json"))
rng = np.random.default_rng(19); N = 20000; BLK = 5
def phase(R, risk, target, rng, maxn=2000):
    bal, peak, n = 1.0, 1.0, 0
    while n < maxn:
        i = rng.integers(0, len(R) - BLK)
        for r in R[i:i + BLK]:
            rk = risk * (0.5 if bal < peak * 0.96 else 1)
            bal += rk * r; peak = max(peak, bal); n += 1   # rischio sul saldo iniziale (~ motore: % del saldo)
            if bal >= 1 + target: return True, n
            if bal <= 0.90: return False, n
    return None, n
out = {}
for b in BOTS:
    R = pd.read_csv(f"{__import__('pathlib').Path(__file__).resolve().parents[2]}/backtest_{b}.csv").R.values; risk = BOTS[b]["risk"]; tps = exp[b]["trade_sett"]
    p1 = [phase(R, risk, 0.10, rng) for _ in range(N)]
    ok1 = [n for ok, n in p1 if ok]
    p2 = [phase(R, risk, 0.05, rng) for _ in range(N)]
    ok2 = [n for ok, n in p2 if ok]
    P1, P2 = len(ok1) / N, len(ok2) / N
    out[b] = dict(fase1=round(P1 * 100, 1), fase2=round(P2 * 100, 1), entrambe=round(P1 * P2 * 100, 1),
                  settimane_mediane_fase1=round(np.median(ok1) / tps, 0), settimane_mediane_fase2=round(np.median(ok2) / tps, 0))
print(json.dumps(out, indent=1)); json.dump(out, open("mc_trades.json", "w"), indent=1)
