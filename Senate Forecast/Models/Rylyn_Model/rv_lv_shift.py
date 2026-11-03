"""Estimate RV_MARGIN_SHIFT and RV_WEIGHT from paired registered-voter / likely-voter results.

Usage:
    python rv_lv_shift.py                          # uses data/RV_LV_pairs.xlsx (Pairs sheet, rows with use = Yes)
    python rv_lv_shift.py --polls polls.csv        # also pulls pairs out of a poll database CSV

A pair is one survey reported two ways: among registered voters and among likely voters.
Margins are Democrat (or credible independent) minus Republican, in points.

RV_MARGIN_SHIFT = average (LV margin - RV margin), pulled toward 0 when pairs are few.
RV_WEIGHT       = POLL_ERROR_VAR / (POLL_ERROR_VAR + variance of the gaps): an RV poll adjusted
                  by the average shift is still off by however much its own gap differs from average.
State shifts    = each state's average gap, pulled toward the pooled shift (most states have 1-2 pairs).
"""
import argparse
import sys

import numpy as np
import pandas as pd

PRIOR_PAIRS = 5        # judgment call: your prior of "no shift" counts as this many pairs
STATE_PRIOR_PAIRS = 3  # judgment call: the pooled shift counts as this many pairs for each state
POLL_ERROR_SD = 5.0    # typical single-poll error on the margin (points); matches DEFAULT_TYPICAL_ERROR


def find_col(df, *candidates, required=True):
    cols = {c.lower().strip(): c for c in df.columns}
    for cand in candidates:
        if cand in cols:                      # exact match first
            return cols[cand]
    for cand in candidates:
        for low, orig in cols.items():
            if cand in low:
                return orig
    if required:
        sys.exit(f"Could not find a column like {candidates} in: {list(df.columns)}")
    return None


def long_to_wide(df):
    # Long format (one row per candidate, e.g., FiftyPlusOne / old 538 files) -> one row per question
    qid = find_col(df, "question_id")
    party = find_col(df, "party", "candidate_party")
    pct = find_col(df, "pct")
    keep = [c for c in [find_col(df, "poll_id", required=False), find_col(df, "pollster"),
                        find_col(df, "state", required=False), find_col(df, "start_date", required=False),
                        find_col(df, "end_date"), find_col(df, "population")] if c]
    rows = []
    for q, g in df.groupby(qid):
        pr = g[party].astype(str).str.upper()
        rep = g.loc[pr.str.startswith("REP"), pct].max()
        dem_rows = g.loc[pr.str.startswith("DEM"), pct]
        dem = dem_rows.max() if len(dem_rows) else g.loc[~pr.str.startswith("REP"), pct].max()  # independent stand-in
        rows.append({**g.iloc[0][keep].to_dict(), "dem": dem, "rep": rep})
    return pd.DataFrame(rows)


def pairs_from_poll_csv(path):
    df = pd.read_csv(path)
    if find_col(df, "pct", required=False) and find_col(df, "question_id", required=False):
        df = long_to_wide(df)
    pollster = find_col(df, "pollster")
    state = find_col(df, "state", required=False)
    start = find_col(df, "start_date", "start", required=False)
    end = find_col(df, "end_date", "end", "date")
    pop = find_col(df, "population", "pop", "lv/rv", "voter_type")
    dem = find_col(df, "dem")
    rep = find_col(df, "rep")
    df["_pop"] = df[pop].astype(str).str.lower().str.strip()
    df["_margin"] = pd.to_numeric(df[dem], errors="coerce") - pd.to_numeric(df[rep], errors="coerce")
    df["_state"] = df[state].fillna("National").replace("", "National") if state else "National"
    keys = ["_state", pollster] + ([start] if start else []) + [end]
    rows = []
    for key, g in df[df["_pop"].isin(["lv", "rv"])].groupby(keys):
        if {"lv", "rv"} <= set(g["_pop"]):
            lv = g.loc[g["_pop"] == "lv", "_margin"].mean()
            rv = g.loc[g["_pop"] == "rv", "_margin"].mean()
            rows.append({"use": "Yes", "state": key[0], "pollster": key[1], "field_dates": " to ".join(map(str, key[2:])),
                         "race": "from poll CSV", "rv_margin": rv, "lv_margin": lv, "same_survey": "Yes", "source": path})
    print(f"Found {len(rows)} LV/RV pairs in {path}")
    return pd.DataFrame(rows)


def main():
    from pathlib import Path
    here = Path(__file__).resolve().parent
    default_pairs = next((p for p in (here / "data" / "RV_LV_pairs.xlsx", here / "RV_LV_pairs.xlsx") if p.exists()),
                         Path("RV_LV_pairs.xlsx"))
    ap = argparse.ArgumentParser()
    ap.add_argument("--pairs", default=str(default_pairs))
    ap.add_argument("--polls", help="optional poll database CSV (wide: pollster/dates/population/dem/rep, or long: question_id/party/pct)")
    args = ap.parse_args()

    pairs = pd.read_excel(args.pairs, sheet_name="Pairs")
    if "state" not in pairs:
        pairs["state"] = "National"
    pairs = pairs[pairs["use"].astype(str).str.strip().str.lower() == "yes"]
    if args.polls:
        pairs = pd.concat([pairs, pairs_from_poll_csv(args.polls)], ignore_index=True)
    pairs["rv_margin"] = pd.to_numeric(pairs["rv_margin"], errors="coerce")
    pairs["lv_margin"] = pd.to_numeric(pairs["lv_margin"], errors="coerce")
    pairs = pairs.dropna(subset=["rv_margin", "lv_margin"])
    pairs["gap"] = pairs["lv_margin"] - pairs["rv_margin"]
    n = len(pairs)
    if n == 0:
        sys.exit("No complete pairs with use = Yes.")

    gap = pairs["gap"]
    raw = gap.mean()
    se = gap.std(ddof=1) / np.sqrt(n) if n > 1 else float("nan")
    pooled = raw * n / (n + PRIOR_PAIRS)
    gap_var = gap.var(ddof=1) if n > 1 else 0.0
    rv_weight = POLL_ERROR_SD ** 2 / (POLL_ERROR_SD ** 2 + gap_var)

    print(pairs[["state", "pollster", "field_dates", "rv_margin", "lv_margin", "gap"]].to_string(index=False))
    print(f"\n{n} pairs. Average LV - RV gap: {raw:+.2f} points (SE {se:.2f})")
    print(f"RV_MARGIN_SHIFT = {pooled:+.2f}   (pulled toward 0; prior worth {PRIOR_PAIRS} pairs)")
    print(f"RV_WEIGHT       = {rv_weight:.2f}   (gap SD {np.sqrt(gap_var):.2f} vs poll error SD {POLL_ERROR_SD})")

    by_state = pairs.groupby("state")["gap"].agg(["count", "mean"])
    by_state["state_shift"] = (by_state["count"] * by_state["mean"] + STATE_PRIOR_PAIRS * pooled) / (by_state["count"] + STATE_PRIOR_PAIRS)
    print("\nBy state (each pulled toward the pooled shift):")
    print(by_state.rename(columns={"count": "pairs", "mean": "raw_gap"}).round(2).to_string())
    print("\nPositive shift = likely voters more Democratic than registered voters.")


if __name__ == "__main__":
    main()
