#!/usr/bin/env python3
"""2026 U.S. Senate forecast with major events: opinion shocks, voting-access changes and redrawn maps.

Built from the professor's starter notebook (senate_midterm_model_SAMPLE.ipynb). Same steps:
polls -> weighted polling average per state -> fundamentals prior (partisan lean + national
environment) -> combine -> correlated simulations -> seats and control. On top of that it adds
an events layer read from Events.xlsx.

The data files are read from data/ next to this script (or from the script's own folder).
    python senate_event_model.py                       full forecast; tables and charts go to outputs/
    python senate_event_model.py --sweep               test each setting at a low and a high value
    python senate_event_model.py --set ENV_SLOPE=0.5 --set PRIOR_SD=5
    python senate_event_model.py --today 2026-10-15 --sims 40000

Margins are Democrat (or credible independent) minus Republican, in points. Positive = Democratic lead.
Needs: numpy, pandas, scipy, matplotlib, openpyxl.
"""
import argparse
import ast
import sys
import time
from pathlib import Path
from types import SimpleNamespace

import matplotlib
matplotlib.use("Agg")                     # save charts to files, no pop-up windows
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from scipy.stats import beta, chi2, norm

# =====================================================================================
# SETTINGS: the choices the group makes. Change them here, or for one run with
#   --set NAME=VALUE. "Raising it" notes say which way the forecast moves on the
#   October 15 data (run --sweep to recheck after the data changes).
# =====================================================================================
SETTINGS = {
    # ---- Simulation -------------------------------------------------------------------
    "ELECTION_DAY": "2026-11-03",
    "N_SIMS": 40_000,              # simulated elections; 40,000 keeps simulation noise near +/-0.25 pts
    "SEED": 2026,                  # fixed so reruns match and setting changes are compared fairly

    # ---- Who controls the chamber -----------------------------------------------------
    "D_SEATS_FOR_CONTROL": 51,     # 50-50 goes to R (VP tiebreak). 52 = "a Democrat switches" view
    "NEBRASKA_CAUCUS_PROB_D": 0.7, # chance independent Osborn caucuses with Democrats if he wins

    # ---- Poll weights (each poll's weight is the product of these) -------------------
    "RECENCY_HALF_LIFE_DAYS": 14,  # a poll this many days old counts half; also used for approval polls
    "REFERENCE_SAMPLE": 800,       # scaling constant for the sample-size weight; changes nothing
    "RV_WEIGHT": 0.85,             # registered-voter polls count this much of a likely-voter poll
    "RV_MARGIN_SHIFT": 1.0,        # points added to RV margins (2026 LV results run more Democratic)
    "PARTISAN_WEIGHT": 0.5,        # party-sponsored polls count this much
    "PARTISAN_HOUSE_EFFECT": 3.0,  # points moved against the sponsor's party
    "GENERIC_WEIGHT": 0.3,         # "generic Democrat vs Republican" questions count this much
    "BIGGER_FIELD_WEIGHT": 1.0,    # full-field ballots (third parties named) count this much
    "COLLAPSE_POLL_VERSIONS": True,# one survey released several ways counts once
    "MIN_QUALITY_WEIGHT": 0.4,     # weight of the lowest-rated pollster (rank 5); rank 10 gets 1.0
    "UNRANKED_SCORE": 6.5,         # rank given to pollsters with no rating (scale 5-10)
    "DEFAULT_TYPICAL_ERROR": 5.0,  # a pollster's average miss on the margin when unknown (all are blank)
    "MAE_TO_SD": 1.25,             # converts average miss to SD; a math constant, leave it
    "SYSTEMATIC_POLL_ERROR_SD": 4.5,  # miss shared by every poll in a state; caps how sure polls can be

    # ---- National environment and prior ------------------------------------------------
    "ENV_SLOPE": 0.35,             # Senate margin points per point of presidential net disapproval
    "NAT_ADULTS_WEIGHT": 0.8,      # approval polls of all adults count this much (RV/LV = 1)
    "PRIOR_SD": 7.0,               # how far a race may stray from lean + environment before polls
    "INCUMBENCY_ADVANTAGE": 0.0,   # points for an elected incumbent running (half if appointed); 0 = off
    "DAILY_DRIFT_SD": 0.28,        # opinion movement per day left; total = this x sqrt(days left)

    # ---- Error shape and how states move together --------------------------------------
    "T_DF": 8,                     # tail weight; lower = more upsets (must be > 2)
    "CORR_NATIONAL": 0.40,         # error every state shares (a national polling miss)
    "CORR_REGION": 0.15,           # extra shared error within a Census region
    "CORR_LEAN": 0.15,             # extra shared error for states with similar partisan lean
    "LEAN_SCALE": 8.0,             # lean gap (points) at which that similarity falls to 37%

    # ---- Events (details live in Events.xlsx) ------------------------------------------
    "USE_OPINION_EVENTS": True,    # news shocks on the Opinion sheet
    "USE_ACCESS_EVENTS": True,     # voting-access changes marked active on the Access sheet
    "NONSAMPLING_SD": 2.0,         # extra poll-to-poll noise when estimating an event from polls

    # ---- House module only (never touches the Senate) ----------------------------------
    "HOUSE_DISTRICT_SD": 5.0,      # district noise for the redrawn-map comparison
}

# Values the sweep tries: (low, high). Every other setting stays as above.
SWEEP = {
    "ENV_SLOPE": (0.20, 0.50),
    "PRIOR_SD": (5.0, 10.0),
    "SYSTEMATIC_POLL_ERROR_SD": (3.0, 6.0),
    "RV_MARGIN_SHIFT": (-1.0, 2.0),
    "INCUMBENCY_ADVANTAGE": (0.0, 2.0),
    "CORR_NATIONAL": (0.25, 0.55),
    "T_DF": (4, 30),
    "D_SEATS_FOR_CONTROL": (51, 52),
    "NEBRASKA_CAUCUS_PROB_D": (0.5, 0.9),
    "RECENCY_HALF_LIFE_DAYS": (7, 30),
    "DAILY_DRIFT_SD": (0.15, 0.40),
    "PARTISAN_HOUSE_EFFECT": (0.0, 5.0),
    "PARTISAN_WEIGHT": (0.25, 1.0),
    "RV_WEIGHT": (0.6, 1.0),
    "GENERIC_WEIGHT": (0.1, 0.6),
    "BIGGER_FIELD_WEIGHT": (0.7, 1.0),
    "COLLAPSE_POLL_VERSIONS": (False, True),
    "MIN_QUALITY_WEIGHT": (0.2, 0.8),
    "UNRANKED_SCORE": (5.0, 8.0),
    "DEFAULT_TYPICAL_ERROR": (4.0, 6.0),
    "NAT_ADULTS_WEIGHT": (0.5, 1.0),
    "CORR_REGION": (0.05, 0.25),
    "CORR_LEAN": (0.05, 0.25),
    "LEAN_SCALE": (4.0, 15.0),
    "NONSAMPLING_SD": (1.0, 3.0),
    "USE_OPINION_EVENTS": (False, True),
    "USE_ACCESS_EVENTS": (False, True),
    "REFERENCE_SAMPLE": (400, 1600),
}

# =====================================================================================
# FACTS (not choices): seats, files, name fixes
# =====================================================================================
POLLS_FILE = "Midterm_Polls.xlsx"
NATIONAL_FILE = "National_Polls.xlsx"
LEANS_FILE = "leans_and_regions.csv"
EVENTS_FILE = "Events.xlsx"

SEATS_UP = {
    # Republican-held
    "Alabama": "R", "Alaska": "R", "Arkansas": "R", "Florida": "R", "Idaho": "R",
    "Iowa": "R", "Kansas": "R", "Kentucky": "R", "Louisiana": "R", "Maine": "R",
    "Mississippi": "R", "Montana": "R", "Nebraska": "R", "North Carolina": "R",
    "Ohio": "R", "Oklahoma": "R", "South Carolina": "R", "South Dakota": "R",
    "Tennessee": "R", "Texas": "R", "West Virginia": "R", "Wyoming": "R",
    # Democratic-held
    "Colorado": "D", "Delaware": "D", "Georgia": "D", "Illinois": "D",
    "Massachusetts": "D", "Michigan": "D", "Minnesota": "D", "New Hampshire": "D",
    "New Jersey": "D", "New Mexico": "D", "Oregon": "D", "Rhode Island": "D",
    "Virginia": "D",
}
HOLDOVER_D = 34   # seats not up in 2026 (Democrats + the two independents who caucus with them)
HOLDOVER_R = 31
RACES = sorted(SEATS_UP)
BATTLEGROUNDS = ["Alaska", "Georgia", "Iowa", "Kansas", "Maine", "Michigan", "Minnesota", "Nebraska",
                 "New Hampshire", "North Carolina", "Ohio", "South Carolina", "Texas"]
INDEPENDENT_RACES = ["Nebraska"]   # the "Dem%" column holds an independent

# Used only when INCUMBENCY_ADVANTAGE > 0. Copied from the group model's INCUMBENT_STATUS
# (hand-maintained there, "verified against news reports on 2026-10-15"); re-check before the final run.
# Any race not listed has an elected incumbent running.
INCUMBENT_STATUS = {
    "Illinois": "open", "Michigan": "open", "Minnesota": "open", "New Hampshire": "open",
    "Alabama": "open", "Iowa": "open", "Kentucky": "open", "Montana": "open",
    "North Carolina": "open", "Wyoming": "open", "Oklahoma": "open", "Texas": "open", "Louisiana": "open",
    "Florida": "appointed", "Ohio": "appointed", "South Carolina": "appointed",
}

POLLSTER_FIXES = {
    "St.Pete Polls": "St. Pete Polls",
    "St. Pete Pols": "St. Pete Polls",
    "HarrixX/Harris Poll": "HarrisX/Harris Poll",
    "Cygnal Politial": "Cygnal Political",
    "Fabrizio, Lee, & Asspcoates": "Fabrizio, Lee & Associates",
}
QUALITY_SCORE_MIN, QUALITY_SCORE_MAX = 5, 10

DEM_BLUE, REP_RED = "#1A6FB0", "#D7301F"


# =====================================================================================
# Settings handling
# =====================================================================================
def make_context(settings, today, verbose=True):
    c = SimpleNamespace(**settings)
    c.TODAY = pd.Timestamp(today).normalize()
    c.ELECTION_DAY = pd.Timestamp(c.ELECTION_DAY)
    c.INDEPENDENT_CAUCUS_PROB_D = {"Nebraska": float(c.NEBRASKA_CAUCUS_PROB_D)}
    c.verbose = verbose
    assert c.T_DF > 2, "T_DF must be greater than 2"
    assert c.CORR_NATIONAL + c.CORR_REGION + c.CORR_LEAN < 1, "correlations must leave room for state noise"
    assert HOLDOVER_D + HOLDOVER_R + len(SEATS_UP) == 100, "seat counts must total 100"
    assert c.TODAY <= c.ELECTION_DAY, "the forecast date is after the election"
    return c


def log(c, *args):
    if c.verbose:
        print(*args)


def parse_set(pairs):
    out = {}
    for item in pairs or []:
        if "=" not in item:
            sys.exit(f"--set needs NAME=VALUE, got '{item}'")
        name, raw = item.split("=", 1)
        name = name.strip().upper()
        if name not in SETTINGS:
            sys.exit(f"Unknown setting '{name}'. Settings: {', '.join(SETTINGS)}")
        try:
            out[name] = ast.literal_eval(raw.strip())
        except (ValueError, SyntaxError):
            out[name] = raw.strip()
    return out


# =====================================================================================
# Step 1. Load and clean the data
# =====================================================================================
def clean_pollster_names(names, verbose=False):
    raw = names.astype(str)
    s = raw.str.strip().str.replace(r"\s+", " ", regex=True).replace(POLLSTER_FIXES)
    key = s.str.lower()
    canon = {k: max(g.unique(), key=lambda v: (sum(ch.isupper() for ch in v), (g == v).sum()))
             for k, g in s.groupby(key)}
    out = key.map(canon)
    if verbose:
        for a, b in sorted({(a, b) for a, b in zip(raw, out) if a != b}):
            print(f"  pollster name: '{a}' -> '{b}'")
    return out


def load_leans(path):
    leans = pd.read_csv(path)
    leans = leans[leans["State"] != "Source"].copy()          # drop the citation row
    leans["State"] = leans["State"].str.strip()
    leans["PartisanLean"] = pd.to_numeric(leans["PartisanLean"])
    return leans.set_index("State")


def load_polls(path, verbose=False):
    p = pd.read_excel(path, sheet_name="Sheet1")
    p["State"] = p["State"].str.strip()
    p["Pollster"] = clean_pollster_names(p["Pollster"], verbose)
    p["Date"] = pd.to_datetime(p["Date"])
    p["LVorRV"] = p["LVorRV"].str.upper().str.strip()
    p["Generic"] = p["Generic"].eq("Yes")
    p["Bigger_Field"] = p["Bigger_Field"].eq("Yes")
    p["Partisan"] = p["Partisan (Pollster or Sponsor)"]
    p["margin"] = p["Dem%"] - p["Rep%"]
    unknown = set(p["State"]) - set(SEATS_UP)
    if unknown:
        print(f"WARNING: polls for states without a race: {unknown}")
    return p


def load_national(path, verbose=False):
    n = pd.read_excel(path, sheet_name="Sheet1")
    n["Pollster"] = clean_pollster_names(n["Pollster"], verbose)
    n["Date"] = pd.to_datetime(n["Date"])
    n["net"] = n["Approval"] - n["Disapproval"]
    bad = n["SampleSize"].fillna(0) <= 0
    if bad.any() and verbose:
        print(f"WARNING: {bad.sum()} national poll(s) with no sample size get zero weight: "
              f"{list(n.loc[bad, 'Pollster'])}")
    return n


def yes(col):
    return col.astype(str).str.strip().str.lower().eq("yes")


def load_events(path):
    op = pd.read_excel(path, sheet_name="Opinion")
    op = op[yes(op["active"])].copy()
    op["date"] = pd.to_datetime(op["date"])
    op["half_life_days"] = pd.to_numeric(op["half_life_days"], errors="coerce")   # blank = permanent
    op["estimate_from_polls"] = yes(op["estimate_from_polls"])
    op["national"] = op["scope"].astype(str).str.strip().str.lower().eq("national")
    ac = pd.read_excel(path, sheet_name="Access")
    ac["active"] = yes(ac["active"])
    if "p_in_effect" not in ac:
        ac["p_in_effect"] = 1.0
    ac["p_in_effect"] = pd.to_numeric(ac["p_in_effect"], errors="coerce").fillna(1.0)
    mp = pd.read_excel(path, sheet_name="Maps")
    mp = mp[yes(mp["active"])].copy()
    md = pd.read_excel(path, sheet_name="Map_Districts")
    return op.set_index("event_id"), ac, mp, md


def load_data(data_dir, verbose=True):
    data_dir = Path(data_dir)
    if verbose:
        print("State polls:")
    polls_raw = load_polls(data_dir / POLLS_FILE, verbose)
    if verbose:
        print("National polls:")
    nat = load_national(data_dir / NATIONAL_FILE, verbose)
    leans = load_leans(data_dir / LEANS_FILE)
    opinion, access, maps, map_districts = load_events(data_dir / EVENTS_FILE)
    d = SimpleNamespace(polls_raw=polls_raw, nat=nat, leans=leans, opinion=opinion,
                        access=access, maps=maps, map_districts=map_districts)
    missing = set(SEATS_UP) - set(leans.index)
    if missing:
        print(f"WARNING: races with no partisan lean: {missing}")
    for label, table in [("Opinion", opinion.reset_index()), ("Access", access)]:
        for _, ev in table.iterrows():
            if not parse_scope(ev["scope"], RACES, leans):
                print(f"WARNING: {label} event {ev['event_id']} scope '{ev['scope']}' matches no race")
    if verbose:
        print(f"{len(leans)} states with leans, {len(polls_raw)} state polls, {len(nat)} national polls")
        print(f"{len(opinion)} active opinion events, {len(access)} access scenarios "
              f"({access['active'].sum()} active), {len(maps)} map events")
    return d


def parse_scope(scope, race_list, leans):
    # Races an event touches: 'national', 'State;State', or 'region:<Region>'
    race_list = list(race_list)
    scope = str(scope).strip()
    if scope.lower() == "national":
        return race_list
    if scope.lower().startswith("region:"):
        region = scope.split(":", 1)[1].strip()
        return [s for s in race_list if s in leans.index and leans.loc[s, "Region"] == region]
    named = [s.strip() for s in scope.split(";") if s.strip()]
    return [s for s in named if s in race_list]


# =====================================================================================
# Step 2. Weight the polls and average them by state
# =====================================================================================
def weight_polls(p, c):
    p = p.copy()
    age = (c.TODAY - p["Date"]).dt.days.clip(lower=0)
    p["w_recency"] = 0.5 ** (age / c.RECENCY_HALF_LIFE_DAYS)
    p["w_size"] = np.sqrt(p["SampleSize"] / c.REFERENCE_SAMPLE)
    p["w_type"] = np.where(p["LVorRV"] == "RV", c.RV_WEIGHT, 1.0)
    p["w_partisan"] = np.where(p["Partisan"].notna(), c.PARTISAN_WEIGHT, 1.0)
    p["w_generic"] = np.where(p["Generic"], c.GENERIC_WEIGHT, 1.0)
    p["w_field"] = np.where(p["Bigger_Field"], c.BIGGER_FIELD_WEIGHT, 1.0)
    score = p["Pollster Rank"].fillna(c.UNRANKED_SCORE).clip(QUALITY_SCORE_MIN, QUALITY_SCORE_MAX)
    frac = (score - QUALITY_SCORE_MIN) / (QUALITY_SCORE_MAX - QUALITY_SCORE_MIN)
    p["w_quality"] = c.MIN_QUALITY_WEIGHT + (1 - c.MIN_QUALITY_WEIGHT) * frac
    pd_, pr_ = p["Dem%"] / 100, p["Rep%"] / 100
    samp_sd = 100 * np.sqrt((pd_ + pr_ - (pd_ - pr_) ** 2) / p["SampleSize"])
    hist_sd = c.MAE_TO_SD * p["Typical Error"].fillna(c.DEFAULT_TYPICAL_ERROR)
    p["poll_error_sd"] = np.maximum(samp_sd, hist_sd)
    p["w_accuracy"] = (c.MAE_TO_SD * c.DEFAULT_TYPICAL_ERROR / p["poll_error_sd"]) ** 2

    # One survey (same state, pollster, date, sample size) released several ways is one sample
    p["survey_id"] = p["Date"].astype(str) + "|" + p["SampleSize"].astype(str)
    if c.COLLAPSE_POLL_VERSIONS:
        p["w_version"] = 1 / p.groupby(["State", "Pollster", "survey_id"])["Pollster"].transform("count")
        n_by_pollster = p.groupby(["State", "Pollster"])["survey_id"].transform("nunique")
    else:
        p["w_version"] = 1.0
        n_by_pollster = p.groupby(["State", "Pollster"])["Pollster"].transform("count")
    p["w_flood"] = 1 / np.sqrt(n_by_pollster)
    p["weight"] = p[[col for col in p.columns if col.startswith("w_")]].prod(axis=1)

    # House-effect shifts to the margin
    adj = p["margin"].astype(float).copy()
    adj += np.where(p["LVorRV"] == "RV", c.RV_MARGIN_SHIFT, 0)
    adj += np.where(p["Partisan"] == "Republican", c.PARTISAN_HOUSE_EFFECT, 0)                    # R poll -> toward D
    adj -= np.where(p["Partisan"].isin(["Democrat", "Independent/Dem"]), c.PARTISAN_HOUSE_EFFECT, 0)  # D poll -> toward R
    p["house_adj_margin"] = adj
    p["event_adj"] = 0.0
    p["adj_margin"] = adj
    return p


def polling_averages(p, c):
    def summarize(g):
        w = g["weight"]
        mean = np.average(g["adj_margin"], weights=w)
        n_eff = w.sum() ** 2 / (w ** 2).sum()                 # Kish effective number of polls
        poll_sd = np.sqrt(np.average(g["poll_error_sd"] ** 2, weights=w))
        sd = np.sqrt(poll_sd ** 2 / n_eff + c.SYSTEMATIC_POLL_ERROR_SD ** 2)
        return pd.Series({"poll_mean": mean, "poll_sd": sd, "n_polls": len(g), "n_eff": n_eff})
    return p.groupby("State")[["weight", "adj_margin", "poll_error_sd"]].apply(summarize)


# =====================================================================================
# Step 3. National environment from presidential approval
# =====================================================================================
def national_poll_weights(nat, c):
    age = (c.TODAY - nat["Date"]).dt.days.clip(lower=0)
    w = 0.5 ** (age / c.RECENCY_HALF_LIFE_DAYS) * np.sqrt(nat["SampleSize"].clip(lower=0) / 1000)
    w = w * np.where(nat["Type"] == "Adults", c.NAT_ADULTS_WEIGHT, 1.0)
    return w.to_numpy()


def national_environment(nat, c):
    net = np.average(nat["net"], weights=national_poll_weights(nat, c))
    env = c.ENV_SLOPE * -net
    log(c, f"Weighted presidential net approval: {net:+.1f}  ->  national environment D{env:+.1f}")
    return env, net


# =====================================================================================
# Step 3b. Opinion events: estimate each effect from same-pollster before/after pairs
# =====================================================================================
def presence(dates, ev):
    # Share of an event's effect present on each date: 0 until the event, then 1 or decaying by half-life
    dts = pd.DatetimeIndex(np.atleast_1d(pd.to_datetime(dates)))
    days = np.asarray((dts - ev["date"]).days, dtype=float)
    hl = ev["half_life_days"]
    decay = np.ones_like(days) if pd.isna(hl) else 0.5 ** (np.clip(days, 0, None) / hl)
    return np.where(days > 0, decay, 0.0)


def diff_sampling_var(a, b, n):
    pa, pb = a / 100, b / 100
    return 1e4 * (pa + pb - (pa - pb) ** 2) / n


def same_pollster_pairs(df, value, var, ev, match_cols, c):
    win = pd.Timedelta(days=int(ev["window_days"]))
    sub = df[(df["Date"] > ev["date"] - win) & (df["Date"] <= ev["date"] + win) & (df["SampleSize"] > 0)].copy()
    sub["post"] = sub["Date"] > ev["date"]
    sub["presence"] = presence(sub["Date"], ev)
    rows = []
    for key, g in sub.groupby(match_cols):
        pre, post = g[~g["post"]], g[g["post"]]
        if len(pre) and len(post):
            noise = c.NONSAMPLING_SD ** 2
            rows.append({
                "comparison": " / ".join(map(str, key if isinstance(key, tuple) else (key,))),
                "n_before": len(pre), "n_after": len(post),
                "before": pre[value].mean(), "after": post[value].mean(),
                "shift": post[value].mean() - pre[value].mean(),
                "var": (pre[var].mean() + noise) / len(pre) + (post[var].mean() + noise) / len(post),
                "presence": post["presence"].mean(),
            })
    return pd.DataFrame(rows)


def estimate_opinion_effects(d, c):
    rows, pairs_by_event = [], {}
    for eid, ev in d.opinion.iterrows():
        est, se, n_pairs = np.nan, np.nan, 0
        if ev["estimate_from_polls"]:
            if ev["national"]:
                df = d.nat.assign(var=diff_sampling_var(d.nat["Approval"], d.nat["Disapproval"],
                                                        d.nat["SampleSize"].clip(lower=1)))
                pairs = same_pollster_pairs(df, "net", "var", ev, ["Pollster", "Type"], c)
                to_margin = -c.ENV_SLOPE        # Republican president: approval up -> D margin down
            else:
                df = d.polls_raw[d.polls_raw["State"].isin(parse_scope(ev["scope"], RACES, d.leans))]
                df = df.assign(var=diff_sampling_var(df["Dem%"], df["Rep%"], df["SampleSize"]))
                pairs = same_pollster_pairs(df, "margin", "var", ev,
                                            ["State", "Pollster", "LVorRV", "Generic", "Bigger_Field"], c)
                to_margin = 1.0
            n_pairs = len(pairs)
            if n_pairs:
                w = 1 / pairs["var"]
                shift = np.average(pairs["shift"], weights=w)
                strength = np.average(pairs["presence"], weights=w)
                est = to_margin * shift / strength
                se = abs(to_margin) * np.sqrt(1 / w.sum()) / strength
                pairs_by_event[eid] = pairs
        if ev["prior_sd"] <= 0:
            post_mean, post_sd, data_share = ev["prior_mean"], 0.0, 0.0
        else:
            prec_prior = 1 / ev["prior_sd"] ** 2
            prec_data = 0.0 if np.isnan(est) else 1 / se ** 2
            post_mean = (prec_prior * ev["prior_mean"] + prec_data * np.nan_to_num(est)) / (prec_prior + prec_data)
            post_sd = np.sqrt(1 / (prec_prior + prec_data))
            data_share = prec_data / (prec_prior + prec_data)
        rows.append({"event_id": eid, "prior_mean": ev["prior_mean"], "prior_sd": ev["prior_sd"],
                     "pairs": n_pairs, "poll_estimate": est, "poll_se": se,
                     "post_mean": post_mean, "post_sd": post_sd, "weight_on_polls": data_share})
    cols = ["prior_mean", "prior_sd", "pairs", "poll_estimate", "poll_se", "post_mean", "post_sd", "weight_on_polls"]
    table = pd.DataFrame(rows).set_index("event_id") if rows else pd.DataFrame(columns=cols)
    return table, pairs_by_event


# =====================================================================================
# Step 4. Prior + polls -> each race's expected margin and uncertainty
# =====================================================================================
def build_race_table(d, c, poll_avg, env, prior_event_adj=None):
    days_left = (c.ELECTION_DAY - c.TODAY).days
    drift_sd = c.DAILY_DRIFT_SD * np.sqrt(days_left)

    races = pd.DataFrame(index=RACES)
    races["incumbent_party"] = pd.Series(SEATS_UP)
    races = races.join(d.leans[["PartisanLean", "Region"]]).join(poll_avg)
    status = pd.Series(INCUMBENT_STATUS).reindex(races.index).fillna("running")
    adv = status.map({"running": c.INCUMBENCY_ADVANTAGE, "appointed": c.INCUMBENCY_ADVANTAGE / 2, "open": 0.0})
    races["incumbency_pts"] = np.where(races["incumbent_party"] == "D", adv, -adv)
    adj = 0.0 if prior_event_adj is None else prior_event_adj.reindex(races.index).fillna(0)
    races["prior_mean"] = 2 * races["PartisanLean"] + env + races["incumbency_pts"] + adj  # lean is in share; x2 = margin
    races["prior_sd"] = c.PRIOR_SD

    has_polls = races["poll_mean"].notna()
    prec_prior = 1 / races["prior_sd"] ** 2
    prec_poll = np.where(has_polls, 1 / races["poll_sd"] ** 2, 0.0)
    races["post_mean"] = (prec_prior * races["prior_mean"]
                          + prec_poll * races["poll_mean"].fillna(0)) / (prec_prior + prec_poll)
    races["post_sd"] = np.sqrt(1 / (prec_prior + prec_poll) + drift_sd ** 2)
    races["poll_share_of_estimate"] = prec_poll / (prec_prior + prec_poll)
    races["n_polls"] = races["n_polls"].fillna(0).astype(int)
    return races


def opinion_poll_adjustment(p, effects, d, c):
    adj = np.zeros(len(p))
    for eid, ev in d.opinion.iterrows():
        in_scope = p["State"].isin(parse_scope(ev["scope"], RACES, d.leans)).to_numpy()
        still_to_come = presence(c.ELECTION_DAY, ev)[0] - presence(p["Date"], ev)
        adj += np.where(in_scope, effects[eid] * still_to_come, 0.0)
    return adj


def env_exposure(ev, d, c):
    # Part of a national event's effect the approval polls haven't seen but Election Day will
    seen = np.average(presence(d.nat["Date"], ev), weights=national_poll_weights(d.nat, c))
    return presence(c.ELECTION_DAY, ev)[0] - seen


def env_event_adjustment(effects, d, c):
    return sum(effects[eid] * env_exposure(ev, d, c) for eid, ev in d.opinion[d.opinion["national"]].iterrows())


def state_prior_adjustment(effects, d, c):
    adj = pd.Series(0.0, index=RACES)
    for eid, ev in d.opinion[~d.opinion["national"]].iterrows():
        adj.loc[parse_scope(ev["scope"], RACES, d.leans)] += effects[eid] * presence(c.ELECTION_DAY, ev)[0]
    return adj


def run_pipeline(d, c, polls, env, effects):
    p = polls.copy()
    p["event_adj"] = opinion_poll_adjustment(p, effects, d, c)
    p["adj_margin"] = p["house_adj_margin"] + p["event_adj"]
    env_total = env + env_event_adjustment(effects, d, c)
    races = build_race_table(d, c, polling_averages(p, c), env_total, state_prior_adjustment(effects, d, c))
    return races, p, env_total


# =====================================================================================
# Steps 5-6. Simulations: correlated, fat-tailed errors plus event uncertainty
# =====================================================================================
def scaled_t(gen, size, df):
    return gen.standard_t(df, size=size) * np.sqrt((df - 2) / df)


def draw_base(races, d, c, n):
    # Every random number the simulations use, drawn once. Each piece has its own random stream,
    # so changing one setting reuses the same draws everywhere else (a fair before/after comparison).
    gens = [np.random.default_rng(s) for s in np.random.SeedSequence(c.SEED).spawn(9)]
    k = len(races)
    lean = races["PartisanLean"].to_numpy(float)
    regions, region_idx = np.unique(races["Region"].to_numpy(dtype=str), return_inverse=True)
    K = np.exp(-np.abs(lean[:, None] - lean[None, :]) / c.LEAN_SCALE)
    vals, vecs = np.linalg.eigh(K)                    # eigh, not Cholesky: equal leans make K singular
    K_half = vecs * np.sqrt(np.clip(vals, 0, None))
    c_state = 1 - c.CORR_NATIONAL - c.CORR_REGION - c.CORR_LEAN

    eta = gens[0].standard_normal(n)                  # the national draw
    z = (np.sqrt(c.CORR_NATIONAL) * eta[:, None]
         + np.sqrt(c.CORR_REGION) * gens[1].standard_normal((n, len(regions)))[:, region_idx]
         + np.sqrt(c.CORR_LEAN) * gens[2].standard_normal((n, k)) @ K_half.T
         + np.sqrt(c_state) * gens[3].standard_normal((n, k)))
    # Shared chi-square scale -> multivariate t: a "bad polling year" hits every state at once
    u = np.clip(gens[4].random(n), 1e-12, 1 - 1e-12)
    t_scale = np.sqrt((c.T_DF - 2) / c.T_DF) / np.sqrt(chi2.ppf(u, c.T_DF) / c.T_DF)
    access_ids = list(d.access["event_id"].unique()) + ["STRESS"]
    return {
        "z": z * t_scale[:, None],
        "eta": eta * t_scale,
        "caucus_u": gens[5].random((n, k)),
        "opinion": {eid: gens[6].standard_normal(n) for eid in d.opinion.index},
        "access": {eid: {"u_det": gens[7].random(n), "u_cm": gens[7].random(n),
                         "z_gap": gens[7].standard_normal(n), "u_effect": gens[7].random(n)}
                   for eid in access_ids},
        "indep": gens[8],
    }


def correlation_matrix(races, c):
    # The starter's formula, used to check the simulated correlations
    lean = races["PartisanLean"].to_numpy(dtype=float)
    region = races["Region"].to_numpy(dtype=object)
    same_region = (region[:, None] == region[None, :]).astype(float)
    lean_sim = np.exp(-np.abs(lean[:, None] - lean[None, :]) / c.LEAN_SCALE)
    R = c.CORR_NATIONAL + c.CORR_REGION * same_region + c.CORR_LEAN * lean_sim
    np.fill_diagonal(R, 1.0)
    return R


def unit_beta(u, mean, sd):
    # Beta draws with a given mean and SD via the inverse CDF, so scenarios reuse the same uniforms
    mean = float(np.clip(mean, 0, 0.999))
    if mean <= 0:
        return np.zeros_like(u)
    if sd <= 0:
        return np.full_like(u, mean)
    var = min(sd ** 2, 0.95 * mean * (1 - mean))
    k = mean * (1 - mean) / var - 1
    return beta.ppf(u, mean * k, (1 - mean) * k)


def access_shift(race_index, rows, draws, leans):
    race_index = pd.Index(race_index)
    out = np.zeros((len(draws["eta"]), len(race_index)))
    if rows is None:
        return out
    for _, r in rows.iterrows():
        dr = draws["access"][r["event_id"]]
        deter = unit_beta(dr["u_det"], r["deterrence_mean"], r["deterrence_sd"])
        backlash = unit_beta(dr["u_cm"], r["countermobilization_mean"], r["countermobilization_sd"])
        lost = r["affected_share"] * deter * (1 - backlash)        # share of the electorate whose ballots are lost
        gap = r["lean_gap"] + r["lean_gap_sd"] * dr["z_gap"]
        shift = -(1 - r["in_polls_share"]) * lost * gap / (1 - lost)
        shift = shift * (dr["u_effect"] < r.get("p_in_effect", 1.0))   # in force in this simulation?
        cols = race_index.get_indexer(parse_scope(r["scope"], race_index, leans))
        out[:, cols] += shift[:, None]
    return out


def simulate(races, draws, c, leans, exposure=None, opinion_sd=None, access_rows=None):
    base = races["post_mean"].to_numpy()[None, :] + races["post_sd"].to_numpy()[None, :] * draws["z"]
    op = np.zeros_like(base)
    if exposure is not None:
        for eid in exposure.columns:
            deviation = opinion_sd[eid] * draws["opinion"][eid]     # true effect minus the mean used
            op += deviation[:, None] * exposure[eid].reindex(races.index).to_numpy()[None, :]
    acc = access_shift(races.index, access_rows, draws, leans)
    margins = base + op + acc
    opp_wins = margins > 0                                          # D or credible independent wins
    caucus_d = np.ones_like(opp_wins)
    for st, prob in c.INDEPENDENT_CAUCUS_PROB_D.items():
        if st in races.index:
            j = races.index.get_loc(st)
            caucus_d[:, j] = draws["caucus_u"][:, j] < prob
    return {
        "margins": pd.DataFrame(margins, columns=races.index),
        "d_seats": HOLDOVER_D + (opp_wins & caucus_d).sum(axis=1),
        "p_dem": pd.Series(opp_wins.mean(axis=0), index=races.index),
        "opinion_shift": pd.DataFrame(op, columns=races.index),
        "access_shift": pd.DataFrame(acc, columns=races.index),
    }


# =====================================================================================
# The whole forecast in one call
# =====================================================================================
def forecast(d, c, n_sims, with_base=True):
    polls = weight_polls(d.polls_raw, c)
    env, net = national_environment(d.nat, c)
    opinion_post, event_pairs = estimate_opinion_effects(d, c)
    no_effects = pd.Series(0.0, index=d.opinion.index)
    use_op = c.USE_OPINION_EVENTS and len(d.opinion) > 0
    effects = opinion_post["post_mean"] if use_op else no_effects

    races_base, _, env_base = run_pipeline(d, c, polls, env, no_effects)    # starter model, no events
    races, polls_adj, env_events = run_pipeline(d, c, polls, env, effects)  # with opinion events

    # Exposure: forecast margin points per point of event effect (the model is linear, so +1 is exact)
    exposure = pd.DataFrame(index=races.index)
    if use_op:
        for eid in d.opinion.index:
            bumped = effects.copy()
            bumped[eid] += 1.0
            exposure[eid] = run_pipeline(d, c, polls, env, bumped)[0]["post_mean"] - races["post_mean"]

    draws = draw_base(races, d, c, n_sims)
    indep = races["post_mean"].values + races["post_sd"].values * scaled_t(draws["indep"], (n_sims, len(races)), c.T_DF)
    races["p_dem_state_sim"] = (indep > 0).mean(axis=0)

    active_access = d.access[d.access["active"]] if c.USE_ACCESS_EVENTS else None
    sim = simulate(races, draws, c, d.leans,
                   exposure if use_op else None, opinion_post["post_sd"] if use_op else None, active_access)
    races["p_dem_national_sim"] = sim["p_dem"]
    sim_base = simulate(races_base, draws, c, d.leans) if with_base else None
    return SimpleNamespace(polls=polls, polls_adj=polls_adj, env=env, net=net, env_base=env_base,
                           env_events=env_events, opinion_post=opinion_post, event_pairs=event_pairs,
                           effects=effects, exposure=exposure, use_op=use_op, races=races,
                           races_base=races_base, draws=draws, sim=sim, sim_base=sim_base,
                           active_access=active_access)


def control_summary(s, c):
    seats = s["d_seats"]
    return pd.Series({
        "P(D control)": (seats >= c.D_SEATS_FOR_CONTROL).mean(),
        "Mean D seats": seats.mean(),
        "D seats, 10th pct": np.percentile(seats, 10),
        "D seats, 90th pct": np.percentile(seats, 90),
    })


# =====================================================================================
# Step 7-10. Tables, charts, scenarios, House maps (full run only)
# =====================================================================================
def margin_label(m):
    return f"D+{m:.1f}" if m >= 0 else f"R+{-m:.1f}"


def race_rating(p_dem, state):
    opp = "Ind" if state in INDEPENDENT_RACES else "D"
    fav, top = (opp, p_dem) if p_dem >= 0.5 else ("R", 1 - p_dem)
    if top < 0.60:
        return "Toss-up"
    level = "Lean" if top < 0.70 else "Likely" if top < 0.85 else "Safe"
    return f"{level} {fav}"


def show(title, df):
    print(f"\n{title}\n" + "-" * len(title))
    print(df.to_string())


def plot_seat_distribution(d_seats, c, path):
    seats, counts = np.unique(d_seats, return_counts=True)
    pct = 100 * counts / len(d_seats)
    p_dem = (d_seats >= c.D_SEATS_FOR_CONTROL).mean()
    mu, sd = d_seats.mean(), d_seats.std()
    with plt.style.context("fivethirtyeight"):
        fig, ax = plt.subplots(figsize=(12, 6.5))
        colors = np.where(seats >= c.D_SEATS_FOR_CONTROL, DEM_BLUE, REP_RED)
        ax.bar(seats, pct, width=0.85, color=colors, zorder=3)
        x = np.linspace(seats.min() - 2, seats.max() + 2, 400)
        ax.plot(x, 100 * norm.pdf(x, mu, sd), color="#3C3C3C", lw=2, ls="--", zorder=4,
                label=f"Normal fit (mean {mu:.1f}, SD {sd:.1f})")
        ax.axvline(c.D_SEATS_FOR_CONTROL - 0.5, color="#3C3C3C", lw=1.5, zorder=2)
        top = pct.max() * 1.15
        ax.text(c.D_SEATS_FOR_CONTROL - 0.8, top, f"Republican control\n{1 - p_dem:.0%}",
                ha="right", va="top", color=REP_RED, fontsize=15, fontweight="bold")
        ax.text(c.D_SEATS_FOR_CONTROL - 0.2, top, f"Democratic control\n{p_dem:.0%}",
                ha="left", va="top", color=DEM_BLUE, fontsize=15, fontweight="bold")
        ax.set_ylim(0, top * 1.05)
        ax.set_xlabel("Democratic seats (incl. caucusing independents)")
        ax.set_ylabel("Share of simulations (%)")
        sec = ax.secondary_xaxis("top", functions=(lambda v: 100 - v, lambda v: 100 - v))
        sec.set_xlabel("Republican seats")
        ax.legend(loc="upper right", frameon=False, fontsize=11)
        fig.suptitle(f"Senate control: {len(d_seats):,} simulated elections",
                     x=0.02, ha="left", fontsize=20, fontweight="bold")
        fig.text(0.02, 0.01, f"Model run {c.TODAY:%b %d, %Y}. Ties below {c.D_SEATS_FOR_CONTROL} seats go to "
                 "Republicans. Includes opinion events and active access events.", fontsize=10, color="#555555")
        fig.tight_layout(rect=(0, 0.03, 1, 1))
        fig.savefig(path, dpi=200, bbox_inches="tight")
        plt.close(fig)


def stress_rows(lost, gap, affected_share):
    return pd.DataFrame([dict(event_id="STRESS", scope="national", affected_share=affected_share,
                              lean_gap=gap, lean_gap_sd=0, deterrence_mean=lost / affected_share,
                              deterrence_sd=0, countermobilization_mean=0, countermobilization_sd=0,
                              in_polls_share=0, p_in_effect=1.0)])


def house_module(d, c, r, out_dir):
    print("\nMap events change Senate margins by 0.0 points in every race (statewide races don't use district lines).")
    if d.maps.empty:
        return
    house_national_sd = np.sqrt(c.CORR_NATIONAL) * r.races["post_sd"].median()
    e = r.env_events + house_national_sd * r.draws["eta"]
    if r.use_op:
        for eid, ev in d.opinion[d.opinion["national"]].iterrows():
            e = e + r.opinion_post.loc[eid, "post_sd"] * r.draws["opinion"][eid] * env_exposure(ev, d, c)
    e = e + access_shift(["__district__"], r.active_access, r.draws, d.leans)[:, 0]

    def house_seats(pvi):
        noise = np.random.default_rng(c.SEED + 1).standard_normal((len(e), len(pvi)))
        return ((2 * pvi[None, :] + e[:, None] + c.HOUSE_DISTRICT_SD * noise) > 0).sum(axis=1)

    def expected_seats(pvi, grid):
        return norm.cdf((2 * pvi[None, :] + grid[:, None]) / c.HOUSE_DISTRICT_SD).sum(axis=1)

    env_grid = np.linspace(-10, 30, 161)
    for _, mev in d.maps.iterrows():
        dist = d.map_districts[d.map_districts["map_event"] == mev["event_id"]]
        pvi_old = dist.loc[dist["plan"] == mev["plan_old"], "pvi"].to_numpy(float)
        pvi_new = dist.loc[dist["plan"] == mev["plan_new"], "pvi"].to_numpy(float)
        n_seats = len(pvi_old)
        s_old, s_new = house_seats(pvi_old), house_seats(pvi_new)
        print(f"\n{mev['name']} ({mev['state']}, {n_seats} districts); statewide lean old {pvi_old.mean():+.1f}, "
              f"new {pvi_new.mean():+.1f}")
        summary = pd.DataFrame({
            "old plan": [s_old.mean(), np.percentile(s_old, 10), np.percentile(s_old, 90)],
            "new plan": [s_new.mean(), np.percentile(s_new, 10), np.percentile(s_new, 90)],
        }, index=["mean D seats", "10th pct", "90th pct"])
        summary["new - old"] = summary["new plan"] - summary["old plan"]
        print(summary.round(2).to_string())
        print(f"  P(new plan gives D fewer seats than old plan) = {(s_new < s_old).mean():.0%}")

        curve_old, curve_new = expected_seats(pvi_old, env_grid), expected_seats(pvi_new, env_grid)
        diff = curve_new - curve_old
        cross = env_grid[np.where(np.diff(np.sign(diff)) != 0)[0]]
        lo, hi = np.percentile(e, [10, 90])
        fig, ax = plt.subplots(figsize=(10, 5.5))
        ax.axvspan(lo, hi, color="#e8e6df", lw=0)
        ax.text((lo + hi) / 2, n_seats * 0.97, "80% range of this\nyear's simulated environment",
                ha="center", va="top", fontsize=9, color="#52514e")
        ax.plot(env_grid, curve_old, color="#4a3aa7", lw=2, label="Old plan")
        ax.plot(env_grid, curve_new, color="#eb6834", lw=2, label="New plan")
        for x in cross[cross > 0]:
            ax.axvline(x, color="#52514e", lw=1, ls=":")
            ax.text(x + 0.4, 1.0, f"crossover at D+{x:.0f}:\nbeyond it the new plan\nhelps Democrats",
                    fontsize=9, color="#52514e")
        ax.set_xlabel("National environment (Democratic margin, points)")
        ax.set_ylabel(f"Expected Democratic seats (of {n_seats})")
        ax.set_ylim(0, n_seats)
        ax.grid(axis="y", color="#e8e6df", lw=0.8)
        ax.spines[["top", "right"]].set_visible(False)
        ax.legend(frameon=False, loc="lower right")
        ax.set_title(f"Seats-votes curves, {mev['state']}", loc="left", fontsize=14, fontweight="bold")
        fig.tight_layout()
        fig.savefig(out_dir / f"house_map_{mev['event_id']}.png", dpi=200, bbox_inches="tight")
        plt.close(fig)


def report(d, c, r, out_dir):
    races, sim, sim_base = r.races, r.sim, r.sim_base
    sims, d_seats = sim["margins"], sim["d_seats"]
    days_left = (c.ELECTION_DAY - c.TODAY).days

    # Headline
    print("\n" + "=" * 72)
    for label, s in [("No events (starter model)", sim_base), ("Main forecast (with events)", sim)]:
        cs = control_summary(s, c)
        print(f"{label:30s} D seats median {np.median(s['d_seats']):.0f}, 80% interval "
              f"{cs['D seats, 10th pct']:.0f}-{cs['D seats, 90th pct']:.0f}, P(D control) {cs['P(D control)']:.1%}")
    print("=" * 72)
    print(f"Model date {c.TODAY:%Y-%m-%d}, {days_left} days to the election, {len(d_seats):,} simulations. "
          f"National environment D{r.env_events:+.1f}.")

    # Check the correlation structure
    R_target = correlation_matrix(races, c)
    R_draws = np.corrcoef(r.draws["z"], rowvar=False)
    gaps = np.abs(R_target - R_draws)[np.triu_indices(len(races), 1)]
    print(f"Correlation check: target vs simulated, mean gap {gaps.mean():.3f}, largest {gaps.max():.3f}")

    if r.use_op:
        show("Opinion events (prior combined with same-pollster estimates)", r.opinion_post.round(2))

    cols = ["incumbent_party", "PartisanLean", "Region", "n_polls", "poll_mean", "prior_mean",
            "poll_share_of_estimate", "post_mean", "post_sd", "p_dem_state_sim", "p_dem_national_sim"]
    out = races[cols].sort_values("post_mean")
    show("Every race (margin = D minus R)", out.round(2))

    # Battlegrounds and the deciding seat
    need = c.D_SEATS_FOR_CONTROL - HOLDOVER_D
    order = np.argsort(-sims.to_numpy(), axis=1)
    deciding = pd.Series(sims.columns[order[:, need - 1]]).value_counts(normalize=True)
    bg = pd.DataFrame({
        "Incumbent party": races["incumbent_party"],
        "Projected margin": sims.median().apply(margin_label),
        "P(Dem win)": races["p_dem_national_sim"],
        "Access shift (pts)": sim["access_shift"].mean(),
        "Deciding seat share": deciding.reindex(races.index).fillna(0),
    }).loc[BATTLEGROUNDS].sort_values("P(Dem win)", ascending=False)
    bg.to_csv(out_dir / "battlegrounds.csv")
    shown = bg.copy()
    for col in ["P(Dem win)", "Deciding seat share"]:
        shown[col] = shown[col].map("{:.0%}".format)
    shown["Access shift (pts)"] = shown["Access shift (pts)"].map("{:+.3f}".format)
    show(f"The 13 battlegrounds (deciding seat is one of them in "
         f"{deciding.reindex(BATTLEGROUNDS).fillna(0).sum():.0%} of simulations)", shown)

    # What the events did
    event_total = sim["opinion_shift"] + sim["access_shift"]
    decomp = pd.DataFrame({
        "margin_no_events": r.races_base["post_mean"],
        "opinion_shift": races["post_mean"] - r.races_base["post_mean"],
        "access_shift": sim["access_shift"].mean(),
        "final_margin": sims.mean(),
        "event_sd": event_total.std(),
        "P(D) no events": sim_base["p_dem"],
        "P(D) with events": sim["p_dem"],
    })
    decomp["P(D) change"] = decomp["P(D) with events"] - decomp["P(D) no events"]
    show("What the events changed, by race", decomp.sort_values("final_margin").round(2))

    print("\nHow races move together:")
    for a, b in [("Iowa", "Kansas"), ("Maine", "New Hampshire"), ("Texas", "Alaska")]:
        pa, pb = (sims[a] > 0), (sims[b] > 0)
        print(f"  P(D wins {b}) = {pb.mean():.2f};  if D wins {a}: {pb[pa].mean():.2f};  "
              f"if D loses {a}: {pb[~pa].mean():.2f}")

    plot_seat_distribution(d_seats, c, out_dir / "seat_distribution.png")

    win_table = pd.DataFrame({
        "Incumbent party": races["incumbent_party"],
        "Projected margin": sims.mean().apply(margin_label),
        "P(Dem win)": races["p_dem_national_sim"],
        "P(Rep win)": 1 - races["p_dem_national_sim"],
    })
    win_table["Rating"] = [race_rating(p, st) for st, p in win_table["P(Dem win)"].items()]
    win_table.index = [f"{st} (Ind)" if st in INDEPENDENT_RACES else st for st in win_table.index]
    win_table.index.name = "State"
    win_table = win_table.sort_values("P(Dem win)", ascending=False)
    win_table.to_csv(out_dir / "state_win_probabilities.csv")

    # Scenarios: each access row on its own, and all of them
    runs = {"No events (starter model)": sim_base}
    op_args = (r.exposure, r.opinion_post["post_sd"]) if r.use_op else (None, None)
    runs["Opinion events only"] = simulate(races, r.draws, c, d.leans, *op_args)
    runs["Main forecast"] = sim
    for eid, rows in d.access.groupby("event_id", sort=False):
        runs[f"Opinion + {eid}"] = simulate(races, r.draws, c, d.leans, *op_args, rows)
    runs["Opinion + every access scenario"] = simulate(races, r.draws, c, d.leans, *op_args, d.access)
    scen = pd.DataFrame({k: control_summary(v, c) for k, v in runs.items()}).T
    base_p = scen.loc["Opinion events only", "P(D control)"]
    scen["Change vs opinion only (pts)"] = 100 * (scen["P(D control)"] - base_p)
    scen.to_csv(out_dir / "scenario_comparison.csv")
    shown = scen.copy()
    shown["P(D control)"] = shown["P(D control)"].map("{:.1%}".format)
    show("Scenarios (access rows marked active are in the main forecast)", shown.round(2))

    # Stress test: how big a nationwide access shock has to be to matter
    affected, gap = 0.10, 20
    lost_grid = np.linspace(0, 0.04, 17)
    stress = pd.DataFrame({
        g: [(simulate(races, r.draws, c, d.leans, *op_args, stress_rows(L, g, affected))["d_seats"]
             >= c.D_SEATS_FOR_CONTROL).mean() for L in lost_grid]
        for g in (gap, -gap)}, index=lost_grid)
    stress.to_csv(out_dir / "access_stress_test.csv", index_label="share_of_electorate_lost")
    fig, ax = plt.subplots(figsize=(10, 5.5))
    ax.plot(100 * lost_grid, 100 * stress[gap], color=DEM_BLUE, lw=2, label=f"Lost voters lean D by {gap}")
    ax.plot(100 * lost_grid, 100 * stress[-gap], color=REP_RED, lw=2, label=f"Lost voters lean R by {gap}")
    ax.axhline(100 * base_p, color="#8a8985", lw=1, ls=":")
    ax.text(100 * lost_grid[-1], 100 * base_p + 1.2, "no access shock", ha="right", color="#52514e", fontsize=10)
    ax.set_xlabel("Share of the electorate whose ballots are lost, nationwide (%)")
    ax.set_ylabel("P(Democratic Senate control), %")
    ax.set_ylim(0, 100)
    ax.grid(axis="y", color="#e8e6df", lw=0.8)
    ax.spines[["top", "right"]].set_visible(False)
    ax.legend(frameon=False, loc="upper left")
    ax.set_title("Senate control vs. size of a nationwide access shock", loc="left", fontsize=14, fontweight="bold")
    fig.tight_layout()
    fig.savefig(out_dir / "access_stress_test.png", dpi=200, bbox_inches="tight")
    plt.close(fig)

    robust = pd.DataFrame({"median margin": sims.median(), "P(D)": races["p_dem_national_sim"]})
    robust = robust[robust["P(D)"].between(0.10, 0.90)].copy()
    robust["share of electorate lost to erase margin"] = robust["median margin"].abs() / (gap + robust["median margin"].abs())
    shown = robust.sort_values("share of electorate lost to erase margin").copy()
    shown["share of electorate lost to erase margin"] = shown["share of electorate lost to erase margin"].map("{:.1%}".format)
    show(f"Competitive races: ballots that would have to be lost (lost voters favor the leader by {gap})",
         shown.round(2))

    house_module(d, c, r, out_dir)

    show("Win probabilities and ratings", win_table.assign(
        **{"P(Dem win)": win_table["P(Dem win)"].map("{:.0%}".format),
           "P(Rep win)": win_table["P(Rep win)"].map("{:.0%}".format)}))

    out.to_csv(out_dir / "race_probabilities.csv")
    decomp.to_csv(out_dir / "event_decomposition.csv")
    r.opinion_post.to_csv(out_dir / "opinion_event_estimates.csv")
    pd.Series(d_seats).value_counts().sort_index().rename("n_sims") \
        .to_csv(out_dir / "seat_distribution.csv", index_label="dem_seats")
    print(f"\nSaved tables and charts to {out_dir.resolve()}")


# =====================================================================================
# Sensitivity sweep: each setting at a low and a high value, everything else fixed
# =====================================================================================
def run_sweep(d, settings, today, n_sims, out_dir):
    def one(s):
        c = make_context(s, today, verbose=False)
        res = forecast(d, c, n_sims, with_base=False)
        seats = res.sim["d_seats"]
        row = {"P(D control)": (seats >= c.D_SEATS_FOR_CONTROL).mean(), "Mean D seats": seats.mean()}
        row.update({f"P(D) {st}": res.sim["p_dem"][st] for st in BATTLEGROUNDS})
        return row

    t0 = time.time()
    base = one(settings)
    print(f"Baseline: P(D control) {base['P(D control)']:.1%}, mean D seats {base['Mean D seats']:.2f}")
    rows = []
    for name, (lo, hi) in SWEEP.items():
        r_lo = one({**settings, name: lo})
        r_hi = one({**settings, name: hi})
        change = 100 * (r_hi["P(D control)"] - r_lo["P(D control)"])
        moves = {st: 100 * (r_hi[f"P(D) {st}"] - r_lo[f"P(D) {st}"]) for st in BATTLEGROUNDS}
        top_state = max(moves, key=lambda k: abs(moves[k]))
        row = {"setting": name, "current": settings[name], "low": lo, "high": hi,
               "P(D control) at low": r_lo["P(D control)"], "P(D control) at high": r_hi["P(D control)"],
               "change low->high (pts)": change,
               "raising it helps": "D" if change >= 0.5 else "R" if change <= -0.5 else "neither",   # under half a point = neither
               "mean D seats at low": r_lo["Mean D seats"], "mean D seats at high": r_hi["Mean D seats"],
               "battleground that moves most": top_state, "its change (pts)": moves[top_state]}
        for st in BATTLEGROUNDS:
            row[f"{st} low"] = r_lo[f"P(D) {st}"]
            row[f"{st} high"] = r_hi[f"P(D) {st}"]
        rows.append(row)
        print(f"  {name:26s} {str(lo):>6} -> {str(hi):<6}  P(D control) {r_lo['P(D control)']:.1%} -> "
              f"{r_hi['P(D control)']:.1%}  ({change:+.1f} pts)   most-moved race: {top_state} {moves[top_state]:+.0f}")
    table = pd.DataFrame(rows)
    table = table.reindex(table["change low->high (pts)"].abs().sort_values(ascending=False).index)
    table.insert(1, "baseline P(D control)", base["P(D control)"])
    table.to_csv(out_dir / "sensitivity.csv", index=False)
    print(f"\nSaved {out_dir / 'sensitivity.csv'} ({time.time() - t0:.0f} s)")
    return table


# =====================================================================================
def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--sweep", action="store_true", help="test each setting at a low and a high value")
    ap.add_argument("--set", action="append", metavar="NAME=VALUE", help="change a setting for this run")
    ap.add_argument("--today", default=None, help="forecast date, YYYY-MM-DD (default: today)")
    ap.add_argument("--sims", type=int, default=None, help="number of simulated elections")
    here = Path(__file__).resolve().parent
    default_data = here / "data" if (here / "data" / POLLS_FILE).exists() else here
    ap.add_argument("--data-dir", default=str(default_data),
                    help="folder with the data files (default: data/ next to this script, else this script's folder)")
    ap.add_argument("--out", default=None, help="output folder (default: outputs/ next to this script)")
    args = ap.parse_args()

    settings = {**SETTINGS, **parse_set(args.set)}
    if args.sims:
        settings["N_SIMS"] = args.sims
    today = args.today or pd.Timestamp.today().normalize()
    out_dir = Path(args.out) if args.out else here / "outputs"
    out_dir.mkdir(parents=True, exist_ok=True)
    changed = {k: v for k, v in settings.items() if SETTINGS.get(k) != v}
    if changed:
        print("Settings changed for this run:", changed)

    d = load_data(args.data_dir, verbose=not args.sweep)
    if args.sweep:
        run_sweep(d, settings, today, settings["N_SIMS"], out_dir)
        return
    c = make_context(settings, today)
    r = forecast(d, c, c.N_SIMS)
    report(d, c, r, out_dir)


if __name__ == "__main__":
    main()
