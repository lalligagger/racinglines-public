import sys, numpy as np, pandas as pd
from racinglines.models import cycling as C
S = sys.argv[1]
b = C.model_block("itt"); s0 = dict(b["defaults"])
res = C.load_results("itt", f"{S}/data"); raw = C.to_raw(res, "itt", b["rules"])
dist = res.groupby("race")["distance_km"].first()
sets = [{**s0, "noise_scale": x, "climb_scale": 0.0} for x in [1.15, 1.5, 2.0, 2.5, 3.0]] + [dict(s0)]
bt = C.backtest(raw, "itt", sets, "2023-01-01", "flat", n_sims=3000)
bt["distance_km"] = bt["race"].map(dist)
bt.to_csv(f"{S}/report/prologue_noise.csv", index=False)
sh = bt[bt["distance_km"] <= 15]
print(sh.groupby(["noise_scale","climb_scale"]).agg(races=("race","size"), win_ll=("win_ll","mean"), pair_ll=("pair_ll","mean"),
      fav_p=("fav_p","mean"), fav_won=("fav_won","mean")).to_string())
lg = bt[bt["distance_km"] > 15]
print(lg.groupby(["noise_scale","climb_scale"]).agg(races=("race","size"), win_ll=("win_ll","mean"), pair_ll=("pair_ll","mean")).to_string())
