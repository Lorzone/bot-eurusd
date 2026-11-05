from harness import *
for sym,f,cost in (("NAS100","nqf_1h",2.0),("US30","ymf_1h",3.0)):
    data={sym:load(f)}; idx=data[sym].index; t0=idx[0]+pd.Timedelta(days=60); split=t0+(idx[-1]-t0)*0.6
    rows=[]
    for setup,sl,tp in itertools.product(["bounce","flag"],[1.5,2.5],[1.0,2.0,np.nan]):
        P=dict(setup=setup,sl_atr=sl,tp_r=tp)
        o,_=run("X",[("swing4h",sym,P)],data,0.005,t0,split,challenges=False)
        rows.append(dict(sym=sym,**P,**o))
    print(pd.DataFrame(rows).to_string(index=False))
