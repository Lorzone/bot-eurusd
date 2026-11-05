import sys; sys.path.insert(0, sys.path[0])
from harness import *
sym, f, cost = sys.argv[1], sys.argv[2], float(sys.argv[3])
engine.INSTR[sym]["cost"] = cost
data = {sym: load(f)}
idx = data[sym].index
t0 = idx[0]; split = idx[int(len(idx) * 0.6)]
print(sym, "dati", idx[0].date(), "->", idx[-1].date(), "split", split.date(), "costo", cost)
rows = []
for side, stop, tp in itertools.product(["both", "long"], ["mid", "opp"], [1.0, 1.5, 2.0, np.nan]):
    P = dict(side=side, stop=stop, tp_r=tp)
    o, _ = run("X", [("orb", sym, P)], data, 0.005, t0, split, challenges=False)
    rows.append(dict(**P, **o))
r = pd.DataFrame(rows)
print(r.to_string(index=False))
