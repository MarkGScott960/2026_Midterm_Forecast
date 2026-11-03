"""
house_calibration.py - measures the House model's uncertainty settings from past House elections and writes
house_calibration.json (read by house_model.py when USE_CALIBRATION = True).

    python house_calibration.py

What it measures (every number is printed and saved with the data it came from):
  A. Fundamentals ("prior"), from the midterms 2018 and 2022 (2014 is measured and reported, but not used; see PRIOR_CYCLES): each contested D-vs-R district's House margin against
         national House margin + b x (district pres. margin - national pres. margin) + incumbency
     -> PVI_TO_MARGIN (= 2b), INCUMBENCY_ADVANTAGE, the district miss (LOCAL_PRIOR_SD) and how much of it is shared
        within a state / Census region in a year (STATE_ERROR_SD / REGIONAL_ERROR_SD).
  B. National environment, from FiveThirtyEight's generic-ballot polls 1998-2022 (House-G-US) against the actual national
     House vote: the final 3 weeks' average miss -> NATIONAL_ERROR_SD. PRIOR_SD = sqrt(local miss^2 + national miss^2),
     the same total the Senate model's prior SD measured.
  C. District polls, from FiveThirtyEight's House-G polls 1998-2022: final 3-week averages (7-day half-life, partisan
     polls shifted 3 pts against the sponsor) against results -> SYSTEMATIC_POLL_ERROR_SD (the floor that makes the
     model's poll ranges the right width) and KALSHI_CONVERT_SD (the RMSE of a final polling average).
Not re-measured (taken from the Senate calibration; no House-specific history in the files): DAILY_DRIFT_SD,
RECENCY_HALF_LIFE_DAYS, HOUSE_EFFECT_K, CANDIDATE effects (none for the House).

Inputs (all saved in this folder, so it runs offline):
  ../Final Model/Data_Cache/raw_polls.csv                (FiveThirtyEight, cached by the Senate calibration)
  Data/calibration/house_results_midterms_538.csv        (FiveThirtyEight election-results repo, House 2014/18/22)
  Data/calibration/pres_by_district_midterm_maps.csv     (Daily Kos Elections / The Downballot district pres. results)
  ../Data/leans_and_regions.csv                          (Census region per state)
"""
import json
import re
import datetime as dt
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
REPO = HERE.parent
SENATE = REPO / "Senate Forecast" if (REPO / "Senate Forecast").is_dir() else REPO  # Senate model, Data/, Final Model/
RAW_POLLS = SENATE / "Final Model" / "Data_Cache" / "raw_polls.csv"
RAW_POLLS_URL = "https://raw.githubusercontent.com/fivethirtyeight/data/master/pollster-ratings/raw_polls.csv"
RESULTS = HERE / "Data" / "calibration" / "house_results_midterms_538.csv"
PRES = HERE / "Data" / "calibration" / "pres_by_district_midterm_maps.csv"
REGIONS = SENATE / "Data" / "leans_and_regions.csv"
OUT = HERE / "house_calibration.json"
SENATE_CAL = SENATE / "Models" / "Most_Magnificent_Model" / "calibration.json"

# ---------------- settings ----------------
NATIONAL_PRES = {2012: 51.06 - 47.20, 2016: 48.18 - 46.09, 2020: 51.31 - 46.85}  # D - R national popular vote (pts)
PRIOR_CYCLES = [2018, 2022]  # midterms used for the fundamentals fit. 2014 is measured and reported but left out: its
                             #   2012 presidential baseline predates the 2016 realignment, so its misses (10 pts) and
                             #   incumbency estimate (11 pts) are far from 2018/2022's (5.7-5.8 and 4.4-4.7)
COMPETITIVE_LIMIT = 15      # prior misses measured on districts whose expected margin is within +/- this (pts)
FIT_LIMIT = 30              # slope/incumbency fitted on districts within +/- this
MAX_THIRD_PARTY = 15        # skip races where non-D/R candidates took more than this share (pts)
FINAL_WINDOW_DAYS = 21      # polls in the final 3 weeks
HALF_LIFE_DAYS = 7          # same recency as the Senate model
PARTISAN_SHIFT = 3.0        # pts against the sponsor (Senate model)
SINGLE_POLL_FLOOR = 1.25 * 4.0  # model: a poll's SD is at least MAE_TO_SD x DEFAULT_TYPICAL_ERROR
POLL_START_CYCLE = 1998


def surname(n):
    n = str(n)
    if "," in n:  # "Young, Don"
        n = n.split(",")[0]
    s = re.sub(r"[^a-z\- ]", "", n.lower().replace("jr.", "").replace(" iii", "").replace(" ii", "")).strip()
    return s.split()[-1] if s else ""


def district_code(st, seat):
    m = re.search(r"(\d+)", str(seat))
    return f"{st}-AL" if m is None else f"{st}-{int(m.group(1)):02d}"


def load_raw_polls():
    if RAW_POLLS.exists():
        return pd.read_csv(RAW_POLLS, low_memory=False), str(RAW_POLLS.relative_to(REPO))
    d = pd.read_csv(RAW_POLLS_URL, low_memory=False)
    return d, "live (GitHub)"


def var_components(df, value, groups):
    """Method-of-moments variance of group means: Var(mean_g) - E[within var / n_g], floored at 0."""
    g = df.groupby(groups)[value]
    stats = g.agg(["mean", "var", "count"]).dropna()
    stats = stats[stats["count"] >= 2]
    between = stats["mean"].var()
    noise = (stats["var"] / stats["count"]).mean()
    return float(max(between - noise, 0.0)), int(len(stats))


# ---------------- A. fundamentals ----------------
def house_margins():
    r = pd.read_csv(RESULTS)
    r["district"] = [district_code(s, x) for s, x in zip(r["state_abbrev"], r["office_seat_name"])]
    r = r[r["state_abbrev"] != "LA"]  # Louisiana's all-party format
    # one row per candidate (fusion tickets list a candidate on several lines)
    cand = (r.groupby(["cycle", "district", "candidate_id"])
             .agg(name=("candidate_name", "first"), pct=("percent", "sum"),
                  parties=("ballot_party", lambda x: set(x.dropna()))).reset_index())
    cand["party"] = np.where(cand["parties"].map(lambda p: "DEM" in p), "D",
                             np.where(cand["parties"].map(lambda p: "REP" in p), "R", "O"))
    rows = []
    for (cy, d), g in cand.groupby(["cycle", "district"]):
        dm, rp = g[g["party"] == "D"], g[g["party"] == "R"]
        if dm.empty or rp.empty:
            continue
        dtop, rtop = dm.nlargest(1, "pct").iloc[0], rp.nlargest(1, "pct").iloc[0]
        third = 100 - dtop["pct"] - rtop["pct"]
        rows.append({"cycle": cy, "district": d, "house_margin": dtop["pct"] - rtop["pct"], "third": third,
                     "cand_surnames": {surname(n) for n in g["name"]}, "d_name": dtop["name"], "r_name": rtop["name"]})
    return pd.DataFrame(rows)


def fundamentals(nat_house):
    pres = pd.read_csv(PRES)
    hm = house_margins()
    df = hm.merge(pres, on=["cycle", "district"], how="inner")
    df = df[df["third"] <= MAX_THIRD_PARTY].copy()
    all_cycles = df.copy()
    df = df[df["cycle"].isin(PRIOR_CYCLES)].copy()
    df["state"] = df["district"].str[:2]
    df["pres_rel"] = df["pres_margin"] - df["pres_year"].map(NATIONAL_PRES)  # = 2 x partisan lean
    df["nat_house"] = df["cycle"].map(nat_house)
    df["y"] = df["house_margin"] - df["nat_house"]
    running = [surname(h) in s for h, s in zip(df["incumbent"], df["cand_surnames"])]
    df["inc"] = np.where(running, np.where(df["party"] == "D", 1.0, np.where(df["party"] == "R", -1.0, 0.0)), 0.0)
    fit = df[(df["pres_rel"] + df["nat_house"]).abs() <= FIT_LIMIT]
    X = np.column_stack([fit["pres_rel"], fit["inc"]])
    coef, *_ = np.linalg.lstsq(X, fit["y"].to_numpy(), rcond=None)
    b, inc = float(coef[0]), float(coef[1])
    df["expected"] = df["nat_house"] + b * df["pres_rel"] + inc * df["inc"]
    df["resid"] = df["house_margin"] - df["expected"]
    comp = df[df["expected"].abs() <= COMPETITIVE_LIMIT].copy()
    local_sd = float(np.sqrt(np.mean(comp["resid"] ** 2)))
    regions = pd.read_csv(REGIONS, encoding="utf-8-sig")
    st_abbr = {"Alabama": "AL", "Alaska": "AK", "Arizona": "AZ", "Arkansas": "AR", "California": "CA", "Colorado": "CO",
               "Connecticut": "CT", "Delaware": "DE", "Florida": "FL", "Georgia": "GA", "Hawaii": "HI", "Idaho": "ID",
               "Illinois": "IL", "Indiana": "IN", "Iowa": "IA", "Kansas": "KS", "Kentucky": "KY", "Louisiana": "LA",
               "Maine": "ME", "Maryland": "MD", "Massachusetts": "MA", "Michigan": "MI", "Minnesota": "MN",
               "Mississippi": "MS", "Missouri": "MO", "Montana": "MT", "Nebraska": "NE", "Nevada": "NV",
               "New Hampshire": "NH", "New Jersey": "NJ", "New Mexico": "NM", "New York": "NY", "North Carolina": "NC",
               "North Dakota": "ND", "Ohio": "OH", "Oklahoma": "OK", "Oregon": "OR", "Pennsylvania": "PA",
               "Rhode Island": "RI", "South Carolina": "SC", "South Dakota": "SD", "Tennessee": "TN", "Texas": "TX",
               "Utah": "UT", "Vermont": "VT", "Virginia": "VA", "Washington": "WA", "West Virginia": "WV",
               "Wisconsin": "WI", "Wyoming": "WY"}
    reg = {st_abbr[s]: r for s, r in zip(regions["State"].str.strip(), regions["Region"]) if s in st_abbr}
    df["region"] = df["state"].map(reg)
    # shared pieces of the miss, measured on every contested district (more groups -> steadier), in pts^2
    v_region, n_rg = var_components(df[df["expected"].abs() <= FIT_LIMIT], "resid", ["cycle", "region"])
    df["resid_ex_region"] = df["resid"] - df.groupby(["cycle", "region"])["resid"].transform("mean")
    v_state, n_st = var_components(df[df["expected"].abs() <= FIT_LIMIT], "resid_ex_region", ["cycle", "state"])
    # how often the expected winner lost (sanity)
    wrong = float(((comp["expected"] > 0) != (comp["house_margin"] > 0)).mean())
    by_cycle = {}
    all_cycles["pres_rel"] = all_cycles["pres_margin"] - all_cycles["pres_year"].map(NATIONAL_PRES)
    all_cycles["y"] = all_cycles["house_margin"] - all_cycles["cycle"].map(nat_house)
    all_cycles["inc"] = [((1.0 if p == "D" else -1.0) if surname(h) in s else 0.0)
                         for h, s, p in zip(all_cycles["incumbent"], all_cycles["cand_surnames"], all_cycles["party"])]
    for cy, g in all_cycles.groupby("cycle"):
        g = g[(g["pres_rel"] + g["cycle"].map(nat_house)).abs() <= FIT_LIMIT]
        c, *_ = np.linalg.lstsq(np.column_stack([g["pres_rel"], g["inc"]]), g["y"].to_numpy(), rcond=None)
        by_cycle[int(cy)] = {"slope_b": round(float(c[0]), 3), "incumbency": round(float(c[1]), 2), "n": int(len(g))}
    return {"prior_cycles": PRIOR_CYCLES, "fit_by_cycle_all": by_cycle, "b": b, "PVI_TO_MARGIN": 2 * b, "INCUMBENCY_ADVANTAGE": inc, "local_sd": local_sd,
            "regional_sd": float(np.sqrt(v_region)), "state_sd": float(np.sqrt(v_state)),
            "n_fit": int(len(fit)), "n_competitive": int(len(comp)), "n_region_groups": n_rg, "n_state_groups": n_st,
            "wrong_winner_share_competitive": wrong,
            "local_sd_by_cycle": comp.groupby("cycle")["resid"].apply(lambda x: float(np.sqrt(np.mean(x ** 2)))).to_dict(),
            "mean_resid_by_cycle": df.groupby("cycle")["resid"].mean().round(2).to_dict()}


# ---------------- B / C. polls ----------------
def final_average(g, margin_col="margin_poll"):
    t = (g["time_to_election"]).astype(float)
    g = g[t <= FINAL_WINDOW_DAYS]
    if g.empty:
        return None
    n = pd.to_numeric(g["samplesize"], errors="coerce").fillna(600).clip(upper=2500)
    w = 0.5 ** (g["time_to_election"].astype(float) / HALF_LIFE_DAYS) * np.sqrt(n / 800)
    m = g[margin_col].astype(float)
    part = g["partisan"].fillna("").astype(str)
    m = m + np.where(part == "REP", PARTISAN_SHIFT, np.where(part == "DEM", -PARTISAN_SHIFT, 0.0))
    samp = 100 * np.sqrt(np.clip(1 - (m / 100) ** 2, 0.5, 1) / n)  # SD of D - R from sampling (approx.)
    single = np.maximum(samp, SINGLE_POLL_FLOOR)
    n_eff = float(w.sum() ** 2 / (w ** 2).sum())
    return {"avg": float(np.average(m, weights=w)), "n_eff": n_eff,
            "single_sd": float(np.sqrt(np.average(single ** 2, weights=w))), "n_polls": int(len(g))}


def generic_ballot(raw):
    g = raw[(raw["type_simple"] == "House-G-US") & (raw["cycle"] >= POLL_START_CYCLE) & (raw["cycle"] % 2 == 0)]
    rows = []
    for cy, x in g.groupby("cycle"):
        a = final_average(x)
        if a:
            rows.append({"cycle": cy, "avg": a["avg"], "actual": float(x["margin_actual"].iloc[0]), "n_polls": a["n_polls"]})
    t = pd.DataFrame(rows)
    t["error"] = t["avg"] - t["actual"]
    return t


def district_polls(raw):
    h = raw[(raw["type_simple"] == "House-G") & (raw["cycle"] >= POLL_START_CYCLE) & (raw["cycle"] % 2 == 0)]
    h = h[(h["cand1_party"] == "DEM") & (h["cand2_party"] == "REP")]
    h = h[(100 - h["cand1_actual"] - h["cand2_actual"]) <= MAX_THIRD_PARTY]
    rows = []
    for (cy, race), x in h.groupby(["cycle", "race"]):
        a = final_average(x)
        if a:
            rows.append({"cycle": cy, "race": race, "location": x["location"].iloc[0], **a,
                         "actual": float(x["margin_actual"].iloc[0])})
    t = pd.DataFrame(rows)
    t["error"] = t["avg"] - t["actual"]
    t = t[t["actual"].abs() <= 40]  # lopsided results produce meaningless "errors"
    return t


def solve_floor(t):
    """Floor F so that error / sqrt(single^2 / n_eff + F^2) has SD 1 (bisection)."""
    lo, hi = 0.0, 15.0
    for _ in range(60):
        mid = (lo + hi) / 2
        z = t["error"] / np.sqrt(t["single_sd"] ** 2 / t["n_eff"] + mid ** 2)
        lo, hi = (mid, hi) if np.sqrt(np.mean(z ** 2)) > 1 else (lo, mid)
    return (lo + hi) / 2


def main():
    raw, raw_src = load_raw_polls()
    nat_house = raw[raw["type_simple"] == "House-G-US"].groupby("cycle")["margin_actual"].first().to_dict()
    F = fundamentals(nat_house)
    gb = generic_ballot(raw)
    nat_sd = float(np.sqrt(np.mean(gb["error"] ** 2)))  # RMS, i.e. about 0 (no bias correction, as in the Senate model)
    polls = district_polls(raw)
    floor = solve_floor(polls)
    rmse = float(np.sqrt(np.mean(polls["error"] ** 2)))
    v_nat_polls, _ = var_components(polls, "error", ["cycle"])
    senate = json.loads(SENATE_CAL.read_text())["overrides"] if SENATE_CAL.exists() else {}
    prior_sd = float(np.sqrt(F["local_sd"] ** 2 + nat_sd ** 2))
    overrides = {
        "PVI_TO_MARGIN": round(F["PVI_TO_MARGIN"], 3),
        "INCUMBENCY_ADVANTAGE": round(F["INCUMBENCY_ADVANTAGE"], 2),
        "PRIOR_SD": round(prior_sd, 2),
        "NATIONAL_ERROR_SD": round(nat_sd, 2),
        "REGIONAL_ERROR_SD": round(F["regional_sd"], 2),
        "STATE_ERROR_SD": round(F["state_sd"], 2),
        "SYSTEMATIC_POLL_ERROR_SD": round(floor, 2),
        "KALSHI_CONVERT_SD": round(rmse, 2),
        # not measurable from House files: the Senate calibration's values
        **{k: senate[k] for k in ("DAILY_DRIFT_SD", "RECENCY_HALF_LIFE_DAYS", "HOUSE_EFFECT_K", "STATE_T_DF") if k in senate},
    }
    out = {
        "created": dt.datetime.now().strftime("%Y-%m-%d %H:%M"),
        "model": "house_model",
        "source": f"FiveThirtyEight raw_polls.csv ({raw_src}) + election-results (House 2014/2018/2022) + Daily Kos/Downballot "
                  "district presidential results; House Forecast/house_calibration.py",
        "settings": {"COMPETITIVE_LIMIT": COMPETITIVE_LIMIT, "FIT_LIMIT": FIT_LIMIT, "MAX_THIRD_PARTY": MAX_THIRD_PARTY,
                     "PRIOR_CYCLES": PRIOR_CYCLES, "FINAL_WINDOW_DAYS": FINAL_WINDOW_DAYS, "HALF_LIFE_DAYS": HALF_LIFE_DAYS,
                     "PARTISAN_SHIFT": PARTISAN_SHIFT, "POLL_START_CYCLE": POLL_START_CYCLE, "NATIONAL_PRES": NATIONAL_PRES},
        "overrides": overrides,
        "from_senate_calibration": [k for k in ("DAILY_DRIFT_SD", "RECENCY_HALF_LIFE_DAYS", "HOUSE_EFFECT_K", "STATE_T_DF") if k in senate],
        "estimates": {
            "fundamentals": F,
            "generic_ballot_errors": gb.round(2).to_dict(orient="records"),
            "generic_ballot_mean_error": round(float(gb["error"].mean()), 2),
            "district_polls": {"races": int(len(polls)), "rmse": rmse, "mean_error": float(polls["error"].mean()),
                               "national_sd_from_district_polls": float(np.sqrt(v_nat_polls)),
                               "median_n_eff": float(polls["n_eff"].median()),
                               "rmse_by_cycle": polls.groupby("cycle")["error"].apply(lambda x: float(np.sqrt(np.mean(x ** 2)))).round(2).to_dict()},
        },
    }
    OUT.write_text(json.dumps(out, indent=2, default=lambda x: x.item() if hasattr(x, "item") else str(x)))
    print(f"House calibration written to {OUT.name}")
    for k, v in overrides.items():
        print(f"  {k:28s} {v}")
    print(f"  fundamentals: slope b = {F['b']:.3f} (PVI_TO_MARGIN {2 * F['b']:.2f}), incumbency {F['INCUMBENCY_ADVANTAGE']:.2f} pts, "
          f"local miss {F['local_sd']:.2f} pts on {F['n_competitive']} competitive districts; "
          f"expected winner lost {F['wrong_winner_share_competitive']:.0%}")
    print(f"  generic ballot: final-average miss RMS {nat_sd:.2f} pts over {len(gb)} cycles (mean {gb['error'].mean():+.2f})")
    print(f"  district polls: {len(polls)} races, RMSE {rmse:.2f}, floor {floor:.2f}")


if __name__ == "__main__":
    main()
