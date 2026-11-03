"""
house_model.py - Team 5's 2026 House forecast model (the House version of Most_Magnificent_Model).

    python house_model.py              one run with CONFIG as written (10,000 simulations) -> Output/
    (house_forecasts.py imports this file, runs it on a schedule and builds the dashboard)

Same assumptions and data sources as Most_Magnificent_Model (Senate), applied to all 435 districts:
  - polls: VoteHub (poll_type us-representative), weighted and adjusted exactly like the Senate polls (recency half-life,
    sample size, LV/RV/A, partisan sponsors, generic question, full field, VoteHub grade + past accuracy, flooding,
    in-cycle house effects, measured RV shift, ungraded pollsters redrawn every simulation)
  - fundamentals: PVI_TO_MARGIN x partisan lean (2024 presidential result on the 2026 lines, The Downballot) + national
    environment (generic ballot 75% + Trump approval 25%, VoteHub + Kalshi averages) +/- incumbency
  - Kalshi: each district's market (found automatically by title) as a third input, longshot-corrected, only for prices in
    6-94%; the House-control market for comparison
  - combined by precision (1 / SD^2), then 100,000 simulated elections with national + regional + state + lean + district
    errors. Democrats need 218 seats.
What is different from the Senate model, and why, is listed in README.md. Every assumption lives in CONFIG below.
All margins are Democrat minus Republican (or minus the non-Democrat finalist), in percentage points.
"""
import copy
import datetime as dt
import json
import os
import re
import time
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.stats import norm

HERE = Path(__file__).resolve().parent
REPO = HERE.parent
SENATE = REPO / "Senate Forecast" if (REPO / "Senate Forecast").is_dir() else REPO  # Senate model, Data/, Final Model/

# =====================================================================================================================
# CONFIG - every assumption lives here (values marked [cal] are replaced by house_calibration.json when USE_CALIBRATION)
# =====================================================================================================================
CONFIG = {
    # ---------------- Files & run settings ----------------
    "DATA_DIR": SENATE / "Data",                         # shared repo data (pollster scorecards, regions)
    "DISTRICT_FILE": HERE / "Data" / "house_districts_2026.csv",  # one row per district (built by Data/build_house_districts.py)
    "SCORECARD_FILE": "votehub_pollster_scorecards.csv",
    "OUT_DIR": HERE / "Output",
    "CACHE_DIR": HERE / "Data_Cache",                  # last good download of every source, used if a website is down
    "USE_CALIBRATION": True,                           # True = house_calibration.json replaces the [cal] values below
    "CALIBRATION_FILE": HERE / "house_calibration.json",
    "ELECTION_DAY": "2026-11-03",
    "AS_OF_DATE": None,                                # None = today
    "N_SIMS": 10_000,
    "SIM_CHUNK": 5_000,                                # simulations processed at a time (memory: 435 districts x chunk)
    "SEED": 2026,

    # ---------------- House rules ----------------
    "TOTAL_SEATS": 435,
    "D_SEATS_FOR_CONTROL": 218,                        # a majority of 435
    # Races without a D-vs-R contest (race_type in the district file): "D_only" and "DD" = certain D seat, "RR" = certain
    # R seat. "IND" = a race whose main challenger is an independent, listed here:
    #   side "D": the independent takes the Democrat's place against the Republican (like Osborn in the Senate model).
    #     Polls and Kalshi are read for the independent (Kalshi: 1 - the Republican's price), and if he wins the seat counts
    #     for Democrats with probability caucus_prob_d, drawn in every simulation.
    #   side "R": the independent is the non-Democratic finalist; a win by him is not a Democratic seat.
    "INDEPENDENTS": {
        "AK-AL": {"name": "Bill Hill", "side": "D", "caucus_prob_d": 0.8},   # Hill (I) vs Begich (R); the Democrat (Hafner,
                                                                           #   3.8% in the primary) is still on the ballot.
                                                                           #   0.8 = the Senate model's figure for Osborn;
                                                                           #   Hill hasn't said whom he'd caucus with
        "CA-06": {"name": "Kevin Kiley", "side": "R", "caucus_prob_d": 0.0},  # Pan (D) vs Kiley (I, ex-Republican)
    },
    "INDEPENDENT_PRIOR_SD_MULT": 1.3,                  # lean says less about a race with an independent (Senate value)
    # Louisiana: Nov 3 is an all-party primary (runoff Dec 12). Modelled as D vs R by the district's lean, like every seat.

    # ---------------- Data cleaning (Senate values) ----------------
    "POLLSTER_NAME_FIXES": {},
    "MIN_SAMPLE_SIZE": 0,
    "MISSING_SAMPLE_SIZE": 600,
    "MAX_POLL_AGE_DAYS": None,
    "DROP_EXACT_DUPLICATES": True,
    "NAT_ZERO_SAMPLE_IMPUTE": 1000,
    "POLL_VERSION_MODE": "split",
    "PREFER_LV_VERSION": True,
    "DROP_GENERIC_IF_CANDIDATE_VERSION": True,

    # ---------------- Undecided / other voters (Senate values) ----------------
    "OTHER_TO_UNDECIDED_H2H": 1.0,
    "OTHER_TO_UNDECIDED_FULL_FIELD": 0.5,
    "UNDECIDED_MODE": "proportional",
    "UNDECIDED_SPLIT_SD": 0.15,

    # ---------------- Poll weights (Senate values) ----------------
    "RECENCY_HALF_LIFE_DAYS": 7,                       # [cal] Senate calibration (no House-specific test)
    "REFERENCE_SAMPLE": 800,
    "SAMPLE_SIZE_EXPONENT": 0.5,
    "SAMPLE_SIZE_CAP": 2500,
    "POPULATION_WEIGHTS": {"LV": 1.0, "RV": 0.85, "A": 0.7},
    "RV_MARGIN_SHIFT": "estimate",                     # measured from 2026 LV/RV pairs (House district + generic ballot)
    "RV_SHIFT_PRIOR_PAIRS": 5,
    "RV_SHIFT_CLIP": (-3.0, 3.0),
    "PARTISAN_WEIGHTS": {"Republican": 0.6, "Democrat": 0.6},
    "PARTISAN_HOUSE_EFFECTS": {"Republican": 3.0, "Democrat": 3.0},
    "GENERIC_WEIGHT": 0.5,
    "BIGGER_FIELD_WEIGHT": 0.9,
    "GRADE_TO_RANK": {"A+": 10, "A": 9, "B": 8, "C": 7, "D": 6, "F": 5},
    "QUALITY_SCORE_MIN": 5,
    "QUALITY_SCORE_MAX": 10,
    "MIN_QUALITY_WEIGHT": 0.5,
    "UNRATED_POLLSTERS": "random",                     # ungraded firms get a random graded firm's grade, error and lean in every simulation
    "UNRANKED_SCORE": 5,
    "DEFAULT_TYPICAL_ERROR": 4.0,
    "MAE_TO_SD": 1.25,
    "ACCURACY_WEIGHT_CLIP": (0.5, 2.0),
    "FLOOD_EXPONENT": 0.5,
    "SYSTEMATIC_POLL_ERROR_SD": 5.6,                   # [cal] House polls miss more than Senate polls (Senate: 3.87)

    # ---------------- House effects (Senate values) ----------------
    "SCORECARD_HOUSE_EFFECTS": True,
    "HOUSE_EFFECT_K": 5,                               # [cal] Senate calibration
    "HOUSE_EFFECT_ITERS": 3,
    "HOUSE_EFFECT_WINDOW_DAYS": 60,

    # ---------------- National environment (Senate values) ----------------
    "PRESIDENT_PARTY": "R",
    "NAT_HALF_LIFE_DAYS": 30,
    "NAT_REFERENCE_SAMPLE": 1000,
    "NAT_POPULATION_WEIGHTS": {"LV": 1.0, "RV": 1.0, "Adults": 0.8},
    "NAT_PARTISAN_WEIGHT": 0.6,
    "NAT_USE_QUALITY": True,
    "ENV_SLOPE": 0.35,                                 # pts of margin per pt of net approval (judgment call, as in the Senate)
    "APPROVAL_NEUTRAL_NET": 0.0,
    "MIDTERM_PENALTY": 0.0,
    "GENERIC_BALLOT_BLEND": 0.75,
    "GB_LOOKBACK_DAYS": 90,
    "GB_MIN_POLLS": 10,
    "GB_POPULATION_PREFERENCE": ["LV", "RV", "A"],
    "GB_MARGIN_BASIS": "two_party",
    "GB_APPLY_RV_SHIFT": True,
    "GB_HALF_LIFE_DAYS": 21,
    "GB_SHIFT": 0.0,
    "NAT_KALSHI_POLL_EQUIV": 5,
    "NAT_FRESH_HALF_LIFE_DAYS": 14,
    "NAT_MIX_LOOKBACK_DAYS": 90,
    "ENV_OVERRIDE": None,

    # ---------------- Fundamentals prior ----------------
    "PVI_TO_MARGIN": 1.78,                             # [cal] House: 2 x 0.89. A district's House margin moves 0.89 pt per pt
                                                       #   of presidential margin (2018/2022); Senate uses the full 2.0
    "ENV_ELASTICITY_DEFAULT": 1.0,
    "INCUMBENCY_ADVANTAGE": 4.5,                       # [cal] pts for an incumbent running in the district (2018/2022)
    "DISTRICT_PRIOR_ADJUSTMENTS": {},                  # manual pts added to a district's prior, e.g. {"NE-02": +2}
    "PRIOR_SD": 6.6,                                   # [cal] district miss incl. the national-environment miss

    # ---------------- Bayesian update (Senate values) ----------------
    "POLL_PRECISION_MULT": 1.0,
    "KALSHI_SD": 8.0,
    "KALSHI_CONVERT_SD": 7.3,                          # [cal] historical RMSE of a final House polling average
    "KALSHI_LONGSHOT_SLOPE": 1.15,
    "KALSHI_USE_RANGE": (0.06, 0.94),
    "CORRELATED_ERRORS": True,
    "SOURCE_ERROR_CORR": 0.3,
    "DAILY_DRIFT_SD": 0.762,                           # [cal] Senate calibration

    # ---------------- Simulation errors (in points) ----------------
    "NATIONAL_ERROR_SD": 3.35,                         # [cal] generic-ballot miss, 1998-2022
    "NATIONAL_T_DF": 8,
    "REGIONAL_ERROR_SD": 2.7,                          # [cal] shared within a Census region (2018/2022 House misses)
    "STATE_ERROR_SD": 2.4,                             # [cal] NEW for the House: shared by districts of one state
    "LEAN_FACTOR_ERROR_SD": 1.0,
    "LEAN_FACTOR_SCALE": 10,
    "STATE_T_DF": 10.9,                                # [cal] tails of the district-only miss
    "MIN_DISTRICT_ERROR_SD": 1.0,

    # ---------------- Race ratings ----------------
    "RATING_TOSSUP": 0.60, "RATING_LEAN": 0.75, "RATING_LIKELY": 0.95,
}

SOURCES = {
    "VOTEHUB_URL": "https://api.votehub.com/polls",
    "KALSHI_URL": "https://api.elections.kalshi.com/trade-api/v2",
    "USER_AGENT": "DACSS-Team5-forecast",
    # district series look like HOUSEME2, KXHOUSENY21, HOUSEPARTY-MI07, HOUSENJ09 (specials end in S and are skipped)
    "KALSHI_HOUSE_SERIES_PATTERN": r"(KX)?HOUSE(PARTY-)?([A-Z]{2})(\d{1,2}|AL)",
    "KALSHI_CONTROL_SERIES": "CONTROLH",
    "KALSHI_CONTROL_FALLBACK": "CONTROLH-2026-D",
    "KALSHI_NATIONAL_SERIES": [("approval", "RCP", "KXTRUMPAPPROVE"), ("approval", "VoteHub", "KXTRUMPVH"),
                               ("generic_ballot", "VoteHub", "KXGENERICBALLOTVOTEHUB")],
    "KALSHI_UPDOWN_SD": 0.5,
    "KALSHI_PROB_CLIP": (0.01, 0.99),
    "HTTP_TRIES": 4,
    "KALSHI_THROTTLE_S": 0.15,
}
AT_LARGE = {"AK", "DE", "ND", "SD", "VT", "WY"}
CALIBRATION = None


def apply_overrides(cfg):
    """Environment overrides set by house_forecasts.py, then house_calibration.json."""
    global CALIBRATION
    cfg = dict(cfg)
    if os.environ.get("FORECAST_N_SIMS"):
        cfg["N_SIMS"] = int(os.environ["FORECAST_N_SIMS"])
    if os.environ.get("FORECAST_OUT_DIR"):
        cfg["OUT_DIR"] = Path(os.environ["FORECAST_OUT_DIR"])
    if os.environ.get("FORECAST_AS_OF"):
        cfg["AS_OF_DATE"] = os.environ["FORECAST_AS_OF"]
    CALIBRATION = None
    if cfg["USE_CALIBRATION"] and Path(cfg["CALIBRATION_FILE"]).exists():
        CALIBRATION = json.loads(Path(cfg["CALIBRATION_FILE"]).read_text())
        for k, v in CALIBRATION.get("overrides", {}).items():
            if k in cfg:
                cfg[k] = tuple(v) if isinstance(cfg[k], tuple) and isinstance(v, list) else v
    return cfg


def validate_config(cfg):
    assert 0 <= cfg["GENERIC_BALLOT_BLEND"] <= 1
    assert cfg["UNDECIDED_MODE"] in {"ignore", "proportional"}
    assert cfg["UNRATED_POLLSTERS"] in {"random", "fixed"}
    assert cfg["KALSHI_SD"] in (None, 0) or cfg["KALSHI_SD"] > 0
    assert cfg["KALSHI_LONGSHOT_SLOPE"] > 0 and 0 <= cfg["SOURCE_ERROR_CORR"] < 1
    assert cfg["RATING_TOSSUP"] <= cfg["RATING_LEAN"] <= cfg["RATING_LIKELY"] <= 1
    for k in ("NATIONAL_T_DF", "STATE_T_DF"):
        assert cfg[k] is None or cfg[k] > 2, f"{k} must be > 2 or None"
    assert min(cfg["NATIONAL_ERROR_SD"], cfg["REGIONAL_ERROR_SD"], cfg["STATE_ERROR_SD"], cfg["LEAN_FACTOR_ERROR_SD"]) >= 0
    assert cfg["PRIOR_SD"] > 0 and cfg["SYSTEMATIC_POLL_ERROR_SD"] > 0


def kalshi_on(cfg):
    return bool(cfg["KALSHI_SD"])


# =====================================================================================================================
# Step 1: data
# =====================================================================================================================
SOURCE_STATUS, KALSHI_LOG = {}, []


def http_json(url, timeout=20):
    is_kalshi = "kalshi" in url
    for attempt in range(SOURCES["HTTP_TRIES"]):
        if is_kalshi:
            time.sleep(SOURCES["KALSHI_THROTTLE_S"])
        try:
            req = urllib.request.Request(url, headers={"User-Agent": SOURCES["USER_AGENT"], "Accept": "application/json"})
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return json.load(r)
        except urllib.error.HTTPError as e:
            if e.code not in (429, 500, 502, 503, 504) or attempt == SOURCES["HTTP_TRIES"] - 1:
                raise
        except (urllib.error.URLError, TimeoutError, ConnectionError):
            if attempt == SOURCES["HTTP_TRIES"] - 1:
                raise
        time.sleep(0.5 * 2 ** attempt)


def kalshi_paged(path, key, params):
    out, cursor = [], None
    for _ in range(50):
        j = http_json(f"{SOURCES['KALSHI_URL']}{path}?{params}" + (f"&cursor={cursor}" if cursor else ""))
        out += j.get(key) or []
        cursor = j.get("cursor")
        if not cursor:
            break
    return out


def with_cache(cfg, name, fetch, parse_dates):
    path = Path(cfg["CACHE_DIR"]) / name
    try:
        df = fetch()
        if df is None or df.empty:
            raise ValueError("empty result")
        df.to_csv(path, index=False)
        SOURCE_STATUS[name] = "live"
        print(f"{name}: fetched {len(df)} rows live")
    except Exception as e:
        if not path.exists():
            raise RuntimeError(f"{name}: download failed ({type(e).__name__}: {e}) and there is no saved copy") from e
        df = pd.read_csv(path)
        SOURCE_STATUS[name] = f"cache ({type(e).__name__})"
        print(f"{name}: download failed ({type(e).__name__}); using the saved copy ({len(df)} rows)")
    for c in parse_dates:
        if c in df.columns:
            df[c] = pd.to_datetime(df[c], utc=True, errors="coerce").dt.tz_localize(None).dt.normalize()
    return df


def norm_district(code):
    """'AK-01' / 'ak-1' / 'NY-4' -> 'AK-AL' / 'NY-04'."""
    m = re.fullmatch(r"\s*([A-Za-z]{2})\s*-?\s*(\d{1,2}|AL|al)\s*", str(code))
    if not m:
        return None
    st, n = m.group(1).upper(), m.group(2).upper()
    if st in AT_LARGE or n in ("AL", "0", "00"):
        return f"{st}-AL"
    return f"{st}-{int(n):02d}"


def fetch_house_polls(districts):
    rows = []
    for p in http_json(f"{SOURCES['VOTEHUB_URL']}?poll_type=us-representative"):
        subj = str(p.get("subject") or "")
        if not subj.startswith("2026 ") or subj.endswith((" Democratic", " Republican")):
            continue
        d = norm_district(p.get("seat_name") or subj[5:])
        if d not in districts:
            continue
        rows.append({"id": p.get("id"), "end_date": p.get("end_date"), "created_at": p.get("created_at"), "district": d,
                     "pollster": p.get("pollster"), "sample_size": p.get("sample_size"),
                     "population": (p.get("population") or "").lower(), "partisan": p.get("partisan") or "",
                     "internal": bool(p.get("internal")),
                     "answers": "|".join(f"{a['choice']}={a['pct']}" for a in p.get("answers", []) if a.get("pct") is not None)})
    return pd.DataFrame(rows)


NAT_COLS = {"generic-ballot": ["Dem", "Rep"], "approval": ["Approve", "Disapprove"]}


def fetch_national(poll_type, keys, extra=""):
    rows = []
    for p in http_json(f"{SOURCES['VOTEHUB_URL']}?poll_type={poll_type}{extra}"):
        ans = {a["choice"].strip().lower(): a["pct"] for a in p.get("answers", [])}
        vals = [next((v for k, v in ans.items() if k.startswith(key)), None) for key in keys]
        if None in vals:
            continue
        rows.append({"Date": p.get("end_date"), "Released": p.get("created_at"), "Pollster": p.get("pollster"),
                     **dict(zip(NAT_COLS[poll_type], vals)), "SampleSize": p.get("sample_size"),
                     "Population": (p.get("population") or "").upper(),
                     "Partisan": bool(p.get("partisan") or p.get("internal"))})
    return pd.DataFrame(rows)


def kalshi_mid(m):
    def f(k):
        v = m.get(k + "_dollars")
        if v not in (None, ""):
            return float(v)
        v = m.get(k)
        return None if v in (None, "") else float(v) / 100
    bid, ask, last = f("yes_bid"), f("yes_ask"), f("last_price")
    if bid and ask and ask >= bid:
        return (bid + ask) / 2
    return last


def is_live_market(m):
    return str(m.get("status", "active")).lower() in ("active", "open", "initialized", "unopened")


def market_side(x):
    """'D' / 'R' / None for one Kalshi market (ticker suffix first, then its titles)."""
    t = str(x.get("ticker", ""))
    if t.endswith("-D"):
        return "D"
    if t.endswith("-R"):
        return "R"
    txt = " ".join(str(x.get(k) or "") for k in ("subtitle", "title", "yes_sub_title")).lower()
    if "democrat" in txt and "republican" not in txt:
        return "D"
    if "republican" in txt and "democrat" not in txt:
        return "R"
    return None


def fetch_kalshi_house(districts):
    """Every 2026 district market, found by its series ticker / event title; plus the House-control market."""
    today = pd.Timestamp.today().strftime("%Y-%m-%d")
    K = SOURCES["KALSHI_URL"]
    series = []
    for s in kalshi_paged("/series", "series", "category=Elections&tags=House"):
        m = re.fullmatch(SOURCES["KALSHI_HOUSE_SERIES_PATTERN"], str(s.get("ticker", "")))
        if m:
            series.append((s["ticker"], norm_district(f"{m.group(3)}-{m.group(4)}")))
    found = {}
    for ser, d_ser in series:
        try:
            events = kalshi_paged("/events", "events", f"series_ticker={ser}&status=open&with_nested_markets=true")
        except Exception as e:
            KALSHI_LOG.append({"request": f"events {ser}", "error": f"{type(e).__name__}: {e}"})
            continue
        for ev in events:
            title = str(ev.get("title") or "")
            is_2026 = "2026" in str(ev.get("sub_title") or "") or "-26" in str(ev.get("event_ticker", ""))
            if not is_2026 or "special" in title.lower() or "primary" in title.lower():
                continue
            mt = re.search(r"\b([A-Z]{2})[- ]?(\d{1,2}|AL)\b", title)
            d = norm_district(f"{mt.group(1)}-{mt.group(2)}") if mt else d_ser
            if d not in districts:
                continue
            mk = [x for x in ev.get("markets", []) if is_live_market(x) and market_side(x)]
            sides = {market_side(x) for x in mk}
            if not {"D", "R"} & sides:
                continue
            vol = sum(float(x.get("volume_fp") or x.get("volume") or 0) for x in mk)
            if d not in found or vol > found[d][0]:
                found[d] = (vol, ev, mk)
    rows = []
    for d, (_, ev, mk) in found.items():
        for x in mk:
            rows.append({"district": d, "event_ticker": ev.get("event_ticker"), "event_title": ev.get("title"),
                         "market_ticker": x["ticker"], "side": market_side(x), "name": x.get("yes_sub_title"),
                         "p_mid": kalshi_mid(x), "fetched": today})
    ctrl = None
    try:
        for ev in http_json(f"{K}/events?series_ticker={SOURCES['KALSHI_CONTROL_SERIES']}&status=open&with_nested_markets=true").get("events", []):
            if "2026" in ev.get("event_ticker", "") or "2026" in str(ev.get("sub_title") or ""):
                ctrl = next((x for x in ev.get("markets", []) if "democ" in str(x.get("yes_sub_title", "")).lower()), ctrl)
    except Exception as e:
        KALSHI_LOG.append({"request": "control market search", "error": f"{type(e).__name__}: {e}"})
    if ctrl is None:
        ctrl = http_json(f"{K}/markets/{SOURCES['KALSHI_CONTROL_FALLBACK']}")["market"]
    rows.append({"district": "CONTROL", "event_ticker": ctrl.get("event_ticker"), "event_title": ctrl.get("title"),
                 "market_ticker": ctrl["ticker"], "side": "D", "name": ctrl.get("yes_sub_title"), "p_mid": kalshi_mid(ctrl),
                 "fetched": today})
    return pd.DataFrame(rows)


def fetch_kalshi_national():
    today = pd.Timestamp.today().strftime("%Y-%m-%d")
    rows = []
    for signal, source, ser in SOURCES["KALSHI_NATIONAL_SERIES"]:
        try:
            events = kalshi_paged("/events", "events", f"series_ticker={ser}&status=open&with_nested_markets=true")
        except Exception as e:
            KALSHI_LOG.append({"request": f"national {ser}", "error": f"{type(e).__name__}: {e}"})
            continue
        events = [e for e in events if e.get("markets")]
        if not events:
            continue
        ev = min(events, key=lambda e: min(str(m.get("close_time") or "9") for m in e["markets"]))
        for m in ev["markets"]:
            rows.append({"signal": signal, "source": source, "series_ticker": ser, "event_ticker": ev.get("event_ticker"),
                         "market_ticker": m["ticker"], "strike_type": m.get("strike_type"), "floor_strike": m.get("floor_strike"),
                         "cap_strike": m.get("cap_strike"), "p_mid": kalshi_mid(m), "fetched": today})
    return pd.DataFrame(rows)


def load_districts(cfg):
    d = pd.read_csv(cfg["DISTRICT_FILE"], keep_default_na=False, na_values=[""])
    for c in ("incumbent", "incumbent_party", "dem_candidate", "rep_candidate", "other_candidate", "notes"):
        d[c] = d[c].fillna("").astype(str)
    return d.set_index("district")


def load_data(cfg):
    SOURCE_STATUS.clear()
    KALSHI_LOG.clear()
    Path(cfg["CACHE_DIR"]).mkdir(parents=True, exist_ok=True)
    districts = load_districts(cfg)
    cards = pd.read_csv(Path(cfg["DATA_DIR"]) / cfg["SCORECARD_FILE"])
    he = cards["House_Effect"].astype(str).str.strip()
    cards["house_effect_d"] = he.str[2:].astype(float) * np.where(he.str.startswith("D"), 1.0, -1.0)
    names = set(districts.index)
    data = {
        "districts": districts, "scorecards": cards,
        "house": with_cache(cfg, "votehub_house_cache.csv", lambda: fetch_house_polls(names), ["end_date", "created_at"]),
        "generic": with_cache(cfg, "votehub_generic_ballot_cache.csv", lambda: fetch_national("generic-ballot", ["dem", "rep"]),
                              ["Date", "Released"]),
        "approval": with_cache(cfg, "votehub_approval_cache.csv",
                               lambda: fetch_national("approval", ["approve", "disapprove"], "&subject=Donald%20Trump"),
                               ["Date", "Released"]),
        "kalshi_races": with_cache(cfg, "kalshi_house_races_cache.csv", lambda: fetch_kalshi_house(names), []),
        "kalshi_national": with_cache(cfg, "kalshi_national_cache.csv", fetch_kalshi_national, []),
    }
    data["nominees"], data["nominee_check"] = build_nominees(data)
    data["polls"], data["n_unmatched"], data["unmatched"] = build_poll_table(data)
    return data


# =====================================================================================================================
# Nominees and the poll table
# =====================================================================================================================
def surname(name):
    s = unicodedata.normalize("NFKD", str(name)).encode("ascii", "ignore").decode().lower()
    s = re.sub(r"\b(jr|sr|ii|iii|iv)\b\.?", "", s)
    s = re.sub(r"[^a-z\- ]", "", s).strip()
    return s.split()[-1] if s else ""


def build_nominees(data):
    """{district: (D name, R-side name)} from Kalshi's market names, else the district file."""
    k, dist = data["kalshi_races"], data["districts"]
    generic = lambda n: (not isinstance(n, str)) or "party" in n.lower() or n.strip().lower() in ("democratic", "republican", "")
    out, rows = {}, []
    for d, r in dist.iterrows():
        g = k[k["district"] == d]
        dk = [n for n in g.loc[g["side"] == "D", "name"] if not generic(n)]
        rk = [n for n in g.loc[g["side"] == "R", "name"] if not generic(n)]
        dem = dk[0] if dk else r["dem_candidate"]
        rep = rk[0] if rk else r["rep_candidate"]
        ind = CONFIG["INDEPENDENTS"].get(d)
        if ind:  # the independent replaces that side's party nominee (Kalshi lists the party's own candidate)
            dem, rep = (ind["name"], rep) if ind["side"] == "D" else (dem, ind["name"])
        out[d] = (dem, rep)
        if len(g) and not ind:
            rows.append({"district": d, "dem": dem, "rep": rep, "source": "Kalshi" if dk and rk else "Kalshi + district file",
                         "matches_file": (not r["dem_candidate"] or surname(dem) == surname(r["dem_candidate"]))
                         and (not r["rep_candidate"] or surname(rep) == surname(r["rep_candidate"]))})
    return out, pd.DataFrame(rows)


def parse_answers(s):
    out = []
    for part in str(s).split("|"):
        if "=" in part:
            name, pct = part.rsplit("=", 1)
            try:
                out.append((name.strip(), float(pct)))
            except ValueError:
                pass
    return out


def party_answer(name):
    n = name.strip().lower()
    if n in ("dem", "dem.", "d", "democrats") or (re.search(r"\bdemocrat", n) and not re.search(r"\brepublican", n)):
        return "D"
    if n in ("rep", "rep.", "r", "gop", "republicans") or (re.search(r"\brepublican", n) and not re.search(r"\bdemocrat", n)):
        return "R"
    return None


def match_poll(row, nominees):
    """(dem_pct, rep_pct, n_candidates, generic, how) or None."""
    ans = parse_answers(row["answers"])
    if len(ans) < 2:
        return None
    parties = {party_answer(n): p for n, p in ans if party_answer(n)}
    if "D" in parties and "R" in parties and len(parties) == len(ans):
        return parties["D"], parties["R"], len(ans), True, "generic"
    dem_name, rep_name = nominees.get(row["district"], ("", ""))
    dem = next((p for n, p in ans if dem_name and surname(n) == surname(dem_name)), None)
    rep = next((p for n, p in ans if rep_name and surname(n) == surname(rep_name)), None)
    if dem is not None and rep is not None:
        return dem, rep, len(ans), False, "both nominees"
    # One nominee's name is unknown (no Kalshi market, not in the district file): when the KNOWN nominee is in the poll,
    # the other side is the top remaining answer (the Senate model's rule for an unnamed opposition nominee)
    others = lambda name: [p for n, p in ans if surname(n) != surname(name) and not party_answer(n)]
    if rep is not None and not dem_name and others(rep_name):
        return max(others(rep_name)), rep, len(ans), False, "R nominee + top other"
    if dem is not None and not rep_name and others(dem_name):
        return dem, max(others(dem_name)), len(ans), False, "D nominee + top other"
    return None  # a nominee is missing: old hypothetical / primary match-up


def scorecard_lookup(cards):
    key = lambda s: re.sub(r"[^a-z0-9]", "", str(s).lower())
    lut = {}
    for _, r in cards.iterrows():
        names = [r["Scorecard_Name"]] + (str(r["Aliases"]).split("|") if pd.notna(r["Aliases"]) else [])
        for n in names:
            lut[key(n)] = (r["Grade"], float(r["Percent_Error"]), float(r["house_effect_d"]))
    return lambda p: lut.get(key(p), (None, np.nan, np.nan))


def build_poll_table(data):
    raw = data["house"]
    dist = data["districts"]
    if raw.empty:
        return pd.DataFrame(), 0, pd.DataFrame()
    raw = raw[raw["district"].map(dist["race_type"]).isin(["DR", "IND"])]  # no polls needed where the result is fixed
    m = raw.apply(lambda r: match_poll(r, data["nominees"]), axis=1)
    keep = m.notna().to_numpy(dtype=bool)
    p, m = raw[keep].copy(), m[keep]
    party = p["partisan"].fillna("").astype(str).str.upper()
    look = p["pollster"].map(scorecard_lookup(data["scorecards"]))
    out = pd.DataFrame({
        "Date": p["end_date"], "Released": p["created_at"], "District": p["district"], "Pollster": p["pollster"].astype(str),
        "Dem%": [x[0] for x in m], "Rep%": [x[1] for x in m], "n_cands": [x[2] for x in m], "Generic": [x[3] for x in m],
        "SampleSize": pd.to_numeric(p["sample_size"], errors="coerce"),
        "LVorRV": p["population"].fillna("").astype(str).str.upper().replace({"ADULTS": "A", "V": "RV"}),
        "Partisan": np.where(party.str.startswith("REP"), "Republican", np.where(party.str.startswith("DEM"), "Democrat", None)),
        "Grade": [x[0] for x in look], "Scorecard Error": [x[1] for x in look], "Scorecard Lean": [x[2] for x in look],
    })
    out["Partisan"] = out["Partisan"].astype("string")
    out["Bigger_Field"] = out["n_cands"] > 2
    out["Unrated"] = out["Grade"].isna()
    return out.reset_index(drop=True), int((~keep).sum()), raw[~keep]


# =====================================================================================================================
# Steps 2-4: clean, margins, weights, averages (the Senate model's code, by district)
# =====================================================================================================================
def normalize_pollsters(names, fixes):
    s = names.astype(str).str.strip().replace(fixes)
    key = s.str.lower().str.replace(r"[^a-z0-9]", "", regex=True)
    canonical = s.groupby(key).agg(lambda x: x.value_counts().index[0])
    return key.map(canonical)


def resolve_today(cfg):
    return pd.Timestamp(cfg["AS_OF_DATE"]) if cfg["AS_OF_DATE"] else pd.Timestamp.today().normalize()


def is_backtest(today):
    return today < pd.Timestamp.today().normalize()


def clean_polls(raw, cfg, today):
    p = raw.copy()
    if p.empty:
        return p
    p["Pollster"] = normalize_pollsters(p["Pollster"], cfg["POLLSTER_NAME_FIXES"])
    p["SampleSize"] = p["SampleSize"].fillna(cfg["MISSING_SAMPLE_SIZE"]).replace(0, cfg["MISSING_SAMPLE_SIZE"])
    if cfg["DROP_EXACT_DUPLICATES"]:
        p = p.drop_duplicates(subset=["Date", "District", "Pollster", "Dem%", "Rep%", "SampleSize", "LVorRV", "Bigger_Field", "Generic"])
    p = p[p["Date"].notna() & (p["Date"] <= today)]
    p = p[p["Released"].isna() | (p["Released"] <= today)]
    p = p[p["SampleSize"] >= cfg["MIN_SAMPLE_SIZE"]]
    if cfg["MAX_POLL_AGE_DAYS"] is not None:
        p = p[(today - p["Date"]).dt.days <= cfg["MAX_POLL_AGE_DAYS"]]
    return p.reset_index(drop=True)


def apply_version_mode(p, cfg):
    p = p.copy()
    if p.empty:
        return p
    p["family"] = p["Date"].dt.strftime("%Y-%m-%d") + " | " + p["District"] + " | " + p["Pollster"]
    if cfg["DROP_GENERIC_IF_CANDIDATE_VERSION"]:
        has_named = p.groupby("family")["Generic"].transform(lambda g: (~g).any())
        p = p[~(p["Generic"] & has_named)]
    if cfg["PREFER_LV_VERSION"]:
        has_lv = p.groupby("family")["LVorRV"].transform(lambda g: (g == "LV").any())
        p = p[(p["LVorRV"] == "LV") | ~has_lv]
    p["n_versions"] = p.groupby("family")["family"].transform("size")
    p["w_version"] = 1.0 if cfg["POLL_VERSION_MODE"] == "keep_all" else 1.0 / p["n_versions"]
    return p.reset_index(drop=True)


def compute_margins(p, cfg):
    p = p.copy()
    if p.empty:
        return p
    d, r = p["Dem%"].astype(float), p["Rep%"].astype(float)
    other = (100 - d - r).clip(lower=0)
    u = other * np.where(p["Bigger_Field"], cfg["OTHER_TO_UNDECIDED_FULL_FIELD"], cfg["OTHER_TO_UNDECIDED_H2H"])
    p["margin"] = (d - r) * (d + r + u) / (d + r) if cfg["UNDECIDED_MODE"] == "proportional" else d - r
    p["undecided"] = u
    p["undecided_sd"] = 2 * u * cfg["UNDECIDED_SPLIT_SD"]
    return p


def grade_pool(data, cfg):
    c = data["scorecards"]
    rank = c["Grade"].map(cfg["GRADE_TO_RANK"]).fillna(cfg["UNRANKED_SCORE"]).to_numpy(dtype=float)
    lo, hi = cfg["QUALITY_SCORE_MIN"], cfg["QUALITY_SCORE_MAX"]
    q = cfg["MIN_QUALITY_WEIGHT"] + (1 - cfg["MIN_QUALITY_WEIGHT"]) * (np.clip(rank, lo, hi) - lo) / (hi - lo)
    return {"quality": q, "mae": c["Percent_Error"].to_numpy(dtype=float), "lean": c["house_effect_d"].to_numpy(dtype=float)}


def accuracy_parts(samp_sd, mae, cfg):
    pes = np.maximum(samp_sd, cfg["MAE_TO_SD"] * mae)
    w = np.clip((cfg["MAE_TO_SD"] * cfg["DEFAULT_TYPICAL_ERROR"] / pes) ** 2, *cfg["ACCURACY_WEIGHT_CLIP"])
    return pes, w


def weight_polls(p, cfg, today, data):
    p = p.copy()
    if p.empty:
        return p
    age = (today - p["Date"]).dt.days.clip(lower=0)
    p["age"] = age
    p["w_recency"] = 0.5 ** (age / cfg["RECENCY_HALF_LIFE_DAYS"])
    n = p["SampleSize"].clip(upper=cfg["SAMPLE_SIZE_CAP"])
    p["w_size"] = (n / cfg["REFERENCE_SAMPLE"]) ** cfg["SAMPLE_SIZE_EXPONENT"]
    p["w_type"] = p["LVorRV"].map(cfg["POPULATION_WEIGHTS"]).fillna(1.0)
    p["w_partisan"] = p["Partisan"].map(cfg["PARTISAN_WEIGHTS"]).astype(float).fillna(1.0)
    p["w_generic"] = np.where(p["Generic"], cfg["GENERIC_WEIGHT"], 1.0)
    p["w_field"] = np.where(p["Bigger_Field"], cfg["BIGGER_FIELD_WEIGHT"], 1.0)
    k = p.groupby(["District", "Pollster"])["family"].transform("nunique")
    p["w_flood"] = 1 / k ** cfg["FLOOD_EXPONENT"]
    lo, hi = cfg["QUALITY_SCORE_MIN"], cfg["QUALITY_SCORE_MAX"]
    unr = p["Unrated"].to_numpy(dtype=bool)
    rank = p["Grade"].map(cfg["GRADE_TO_RANK"]).fillna(cfg["UNRANKED_SCORE"]).clip(lo, hi)
    p["w_quality"] = cfg["MIN_QUALITY_WEIGHT"] + (1 - cfg["MIN_QUALITY_WEIGHT"]) * (rank - lo) / (hi - lo)
    pd_, pr_ = p["Dem%"] / 100, p["Rep%"] / 100
    p["samp_sd"] = 100 * np.sqrt((pd_ + pr_ - (pd_ - pr_) ** 2) / p["SampleSize"])
    mae = p["Scorecard Error"].fillna(cfg["DEFAULT_TYPICAL_ERROR"])
    p["poll_error_sd"], p["w_accuracy"] = accuracy_parts(p["samp_sd"], mae, cfg)
    if cfg["UNRATED_POLLSTERS"] == "random" and unr.any():
        pool = grade_pool(data, cfg)
        pes, wa = accuracy_parts(p.loc[unr, "samp_sd"].to_numpy()[:, None], pool["mae"][None, :], cfg)
        p.loc[unr, "w_quality"] = pool["quality"].mean()
        p.loc[unr, "w_accuracy"] = wa.mean(axis=1)
        p.loc[unr, "poll_error_sd"] = np.sqrt((pes ** 2).mean(axis=1))
    wcols = [c for c in p.columns if c.startswith("w_")]
    p["weight"] = p[wcols].prod(axis=1)
    p["w_base"] = p["weight"] / (p["w_quality"] * p["w_accuracy"])
    return p


def national_poll_frame(df, today):
    g = df[df["Date"] <= today].copy()
    if "Released" in g.columns:
        g = g[g["Released"].isna() | (g["Released"] <= today)]
    g["Population"] = g["Population"].fillna("").astype(str).str.upper().replace({"ADULTS": "A", "V": "RV"})
    return g


def estimate_rv_shift(data, cfg, today):
    gaps = []
    sp = data["polls"]
    if len(sp):
        sp = sp[(sp["Date"] <= today) & ~sp["Generic"]]
        for _, g in sp.groupby(["District", "Pollster", "Date", "Bigger_Field"]):
            lv, rv = g[g["LVorRV"] == "LV"], g[g["LVorRV"] == "RV"]
            if len(lv) and len(rv):
                gaps.append(float((lv["Dem%"] - lv["Rep%"]).mean() - (rv["Dem%"] - rv["Rep%"]).mean()))
    gb = national_poll_frame(data["generic"], today)
    for _, g in gb.groupby(["Pollster", "Date"]):
        lv, rv = g[g["Population"] == "LV"], g[g["Population"] == "RV"]
        if len(lv) and len(rv):
            gaps.append(float((lv["Dem"] - lv["Rep"]).mean() - (rv["Dem"] - rv["Rep"]).mean()))
    n = len(gaps)
    return (float(np.clip(sum(gaps) / (n + cfg["RV_SHIFT_PRIOR_PAIRS"]), *cfg["RV_SHIFT_CLIP"])) if n else 0.0), n


def rv_shift(cfg):
    return cfg["_rv_shift"] if cfg["RV_MARGIN_SHIFT"] == "estimate" else float(cfg["RV_MARGIN_SHIFT"])


def in_cycle_house_effects(p, cfg, prior):
    recent = (p["age"] <= cfg["HOUSE_EFFECT_WINDOW_DAYS"]).to_numpy()
    x, w = p["adj_margin_raw"].astype(float), p["weight"].astype(float).where(recent, 0.0)
    use = ~p["partisan_poll"] & recent
    k = cfg["HOUSE_EFFECT_K"]
    lean = prior.copy()
    n_i = sum_i = pd.Series(0.0, index=p.index)
    for _ in range(cfg["HOUSE_EFFECT_ITERS"]):
        xc = x - lean
        tot = (w * xc).groupby(p["District"]).transform("sum"); tw = w.groupby(p["District"]).transform("sum")
        own = (w * xc).groupby([p["District"], p["Pollster"]]).transform("sum")
        ow = w.groupby([p["District"], p["Pollster"]]).transform("sum")
        others = tw - ow
        res = (x - (tot - own) / others.where(others > 0)).where(use)
        s = res.groupby(p["Pollster"]).agg(["sum", "count"])
        n_i, sum_i = p["Pollster"].map(s["count"]).fillna(0.0), p["Pollster"].map(s["sum"]).fillna(0.0)
        lean = pd.Series(np.where(~p["partisan_poll"], (sum_i + k * prior) / (n_i + k), 0.0), index=p.index)
    return n_i, sum_i, lean


def adjust_margins(p, cfg, data):
    p = p.copy()
    if p.empty:
        return p
    adj = p["margin"].astype(float).copy()
    adj += np.where(p["LVorRV"] == "RV", rv_shift(cfg), 0.0)
    effect = p["Partisan"].map(cfg["PARTISAN_HOUSE_EFFECTS"]).astype(float).fillna(0.0)
    toward_d = p["Partisan"].fillna("").str.startswith("Republican")
    adj += np.where(toward_d, effect, -effect)
    p["partisan_poll"] = p["Partisan"].notna().to_numpy(dtype=bool)
    p["adj_margin_raw"] = adj.copy()
    lean = p["Scorecard Lean"].astype(float).copy()
    if cfg["UNRATED_POLLSTERS"] == "random":
        lean[p["Unrated"]] = grade_pool(data, cfg)["lean"].mean()
    p["scorecard_lean"] = np.where(cfg["SCORECARD_HOUSE_EFFECTS"] & ~p["partisan_poll"], lean.fillna(0.0), 0.0)
    p["he_n"], p["he_sum"], p["house_lean"] = in_cycle_house_effects(p, cfg, pd.Series(p["scorecard_lean"], index=p.index))
    p["adj_margin"] = adj - p["house_lean"]
    return p


POLL_AVG_COLS = ["poll_mean", "poll_sd", "n_polls", "n_surveys", "n_eff", "undecided", "last_poll_age"]


def polling_averages(p, cfg):
    rows = {}
    for d, g in p.groupby("District"):
        w = g["weight"].to_numpy()
        n_eff = w.sum() ** 2 / (w ** 2).sum()
        poll_sd = np.sqrt(np.average(g["poll_error_sd"] ** 2, weights=w))
        und_sd = np.average(g["undecided_sd"], weights=w)
        rows[d] = {"poll_mean": np.average(g["adj_margin"], weights=w),
                   "poll_sd": np.sqrt(poll_sd ** 2 / n_eff + cfg["SYSTEMATIC_POLL_ERROR_SD"] ** 2 + und_sd ** 2),
                   "n_polls": len(g), "n_surveys": g["family"].nunique(), "n_eff": n_eff,
                   "undecided": np.average(g["undecided"], weights=w), "last_poll_age": g["age"].min()}
    return pd.DataFrame.from_dict(rows, orient="index", columns=POLL_AVG_COLS).astype(float)


# =====================================================================================================================
# Step 5: national environment (the Senate model's code)
# =====================================================================================================================
def _quality(n, data, cfg):
    lo, hi = cfg["QUALITY_SCORE_MIN"], cfg["QUALITY_SCORE_MAX"]
    look = n["Pollster"].map(scorecard_lookup(data["scorecards"]))
    s = pd.Series([cfg["GRADE_TO_RANK"].get(x[0], cfg["UNRANKED_SCORE"]) for x in look], index=n.index).clip(lo, hi)
    return cfg["MIN_QUALITY_WEIGHT"] + (1 - cfg["MIN_QUALITY_WEIGHT"]) * (s - lo) / (hi - lo)


def approval_environment(data, cfg, today):
    n = national_poll_frame(data["approval"], today)
    if n.empty:
        return np.nan, 0, 0.0
    n["Pollster"] = normalize_pollsters(n["Pollster"], cfg["POLLSTER_NAME_FIXES"])
    if cfg["DROP_EXACT_DUPLICATES"]:
        n = n.drop_duplicates(subset=["Date", "Pollster", "Approve", "Disapprove", "SampleSize", "Population"])
    ss = pd.to_numeric(n["SampleSize"], errors="coerce").fillna(cfg["NAT_ZERO_SAMPLE_IMPUTE"]).replace(0, cfg["NAT_ZERO_SAMPLE_IMPUTE"])
    pop = n["Population"].replace({"A": "Adults"})
    net = n["Approve"] - n["Disapprove"]
    age = (today - n["Date"]).dt.days.clip(lower=0)
    w = 0.5 ** (age / cfg["NAT_HALF_LIFE_DAYS"]) * np.sqrt(ss / cfg["NAT_REFERENCE_SAMPLE"])
    w *= pop.map(cfg["NAT_POPULATION_WEIGHTS"]).fillna(1.0)
    w *= np.where(n["Partisan"].astype(str).str.lower().isin(["true", "1"]), cfg["NAT_PARTISAN_WEIGHT"], 1.0)
    if cfg["NAT_USE_QUALITY"]:
        w *= _quality(n, data, cfg)
    w = w.to_numpy(dtype=float)
    n_fresh = float((0.5 ** (age / cfg["NAT_FRESH_HALF_LIFE_DAYS"])).sum())
    return float(np.average(net, weights=w)), len(n), min(float(w.sum() ** 2 / (w ** 2).sum()), n_fresh)


def generic_ballot_poll_average(data, cfg, today):
    g = national_poll_frame(data["generic"], today)
    if g.empty:
        return np.nan, 0, 0.0
    g["Pollster"] = normalize_pollsters(g["Pollster"], cfg["POLLSTER_NAME_FIXES"])
    rank = {pop: i for i, pop in enumerate(cfg["GB_POPULATION_PREFERENCE"])}
    g["pop_rank"] = g["Population"].map(rank).fillna(len(rank))
    g = g.sort_values("pop_rank").drop_duplicates(["Date", "Pollster"], keep="first")
    recent = g[g["Date"] >= today - pd.Timedelta(days=cfg["GB_LOOKBACK_DAYS"])]
    if len(recent) < cfg["GB_MIN_POLLS"]:
        recent = g.nlargest(cfg["GB_MIN_POLLS"], "Date")
    if recent.empty:
        return np.nan, 0, 0.0
    d, r = recent["Dem"].astype(float), recent["Rep"].astype(float)
    margin = 100 * (d - r) / (d + r) if cfg["GB_MARGIN_BASIS"] == "two_party" else d - r
    if cfg["GB_APPLY_RV_SHIFT"]:
        margin = margin + np.where(recent["Population"] == "RV", rv_shift(cfg), 0.0)
    age = (today - recent["Date"]).dt.days.clip(lower=0)
    n = pd.to_numeric(recent["SampleSize"], errors="coerce").fillna(cfg["NAT_REFERENCE_SAMPLE"]).replace(0, cfg["NAT_REFERENCE_SAMPLE"])
    pop = recent["Population"].replace({"A": "Adults"})
    w = 0.5 ** (age / cfg["GB_HALF_LIFE_DAYS"]) * np.sqrt(n / cfg["NAT_REFERENCE_SAMPLE"])
    w *= pop.map(cfg["NAT_POPULATION_WEIGHTS"]).fillna(1.0)
    w *= np.where(recent["Partisan"].astype(str).str.lower().isin(["true", "1"]), cfg["NAT_PARTISAN_WEIGHT"], 1.0)
    w = w.to_numpy(dtype=float)
    n_fresh = float((0.5 ** (age / cfg["NAT_FRESH_HALF_LIFE_DAYS"])).sum())
    return float(np.average(margin, weights=w)), len(recent), min(float(w.sum() ** 2 / (w ** 2).sum()), n_fresh)


def kalshi_implied_value(g):
    g = g.dropna(subset=["p_mid"])
    if g.empty:
        return np.nan
    fl = pd.to_numeric(g["floor_strike"], errors="coerce")
    cp = pd.to_numeric(g["cap_strike"], errors="coerce")
    if (g["strike_type"] == "greater").all():
        if len(g) == 1:
            p = float(np.clip(g["p_mid"].iloc[0], 0.02, 0.98))
            return float(fl.iloc[0] + norm.ppf(p) * SOURCES["KALSHI_UPDOWN_SD"])
        lad = pd.DataFrame({"x": fl, "p": g["p_mid"].astype(float)}).sort_values("x")
        return float(np.interp(0.5, lad["p"].to_numpy()[::-1], lad["x"].to_numpy()[::-1]))
    strikes = np.sort(pd.concat([fl, cp]).dropna().unique())
    step = float(np.min(np.diff(strikes))) if len(strikes) > 1 else 0.1
    val = np.where(g["strike_type"] == "less", cp - step, np.where(g["strike_type"] == "greater", fl + step, (fl + cp) / 2))
    p = g["p_mid"].astype(float).to_numpy()
    return float(np.sum(p * val) / p.sum())


def national_environment(data, cfg, today):
    backtest = is_backtest(today)
    look = cfg["NAT_MIX_LOOKBACK_DAYS"]

    def recent(df):
        d = national_poll_frame(df, today)
        r = d[d["Date"] >= today - pd.Timedelta(days=look)]
        return r if len(r) >= 10 else d.nlargest(10, "Date")
    ap_mix, gb_mix = recent(data["approval"]), recent(data["generic"])
    U = float((100 - ap_mix["Approve"] - ap_mix["Disapprove"]).clip(lower=0).mean()) if len(ap_mix) else 4.0
    DR = float((gb_mix["Dem"] + gb_mix["Rep"]).mean()) if len(gb_mix) else 90.0
    net_poll, n_ap, ne_ap = approval_environment(data, cfg, today)
    gb_poll, n_gb, ne_gb = generic_ballot_poll_average(data, cfg, today)
    kn = data["kalshi_national"]
    parts = {} if backtest or kn is None or kn.empty else {
        (sig, src): kalshi_implied_value(g) for (sig, src), g in kn.groupby(["signal", "source"])}
    ap_k = [v for (sig, _), v in parts.items() if sig == "approval" and not np.isnan(v)]
    gb_k = [v for (sig, _), v in parts.items() if sig == "generic_ballot" and not np.isnan(v)]
    approve_k = float(np.mean(ap_k)) if ap_k else np.nan
    net_k = 2 * approve_k - 100 + U if ap_k else np.nan
    gb_k_val = float(np.mean(gb_k)) * (100 / DR if cfg["GB_MARGIN_BASIS"] == "two_party" else 1.0) if gb_k else np.nan
    K = cfg["NAT_KALSHI_POLL_EQUIV"]

    def blend(poll, n_eff, kal):
        pts = [(w, v) for w, v in [(n_eff, poll), (K, kal)] if w > 0 and not np.isnan(v)]
        return sum(w * v for w, v in pts) / sum(w for w, _ in pts) if pts else np.nan
    net = blend(net_poll, ne_ap, net_k)
    gb = blend(gb_poll, ne_gb, gb_k_val)
    sign = 1 if cfg["PRESIDENT_PARTY"] == "R" else -1
    env_appr = sign * (cfg["ENV_SLOPE"] * -(net - cfg["APPROVAL_NEUTRAL_NET"]) + cfg["MIDTERM_PENALTY"]) if not np.isnan(net) else np.nan
    env_gb = gb + cfg["GB_SHIFT"] if not np.isnan(gb) else np.nan
    if cfg["ENV_OVERRIDE"] is not None:
        env = cfg["ENV_OVERRIDE"]
    elif np.isnan(env_appr) and np.isnan(env_gb):
        env = 0.0
    elif np.isnan(env_gb):
        env = env_appr
    elif np.isnan(env_appr):
        env = env_gb
    else:
        b = cfg["GENERIC_BALLOT_BLEND"]
        env = b * env_gb + (1 - b) * env_appr
    table = pd.DataFrame([
        {"signal": "generic ballot (D-R)", "VoteHub polls": gb_poll, "n polls": n_gb, "effective n (fresh)": ne_gb,
         "Kalshi average": gb_k_val, "combined": gb},
        {"signal": "net approval", "VoteHub polls": net_poll, "n polls": n_ap, "effective n (fresh)": ne_ap,
         "Kalshi average": net_k, "combined": net}]).set_index("signal")
    return {"net_approval": net, "env_approval": env_appr, "env_generic": env_gb, "env": float(env), "table": table,
            "U": U, "DR": DR, "backtest": backtest}


# =====================================================================================================================
# Step 6: prior + Bayesian update with Kalshi
# =====================================================================================================================
def posterior(prior_mean, prior_sd, poll_mean, poll_sd, n_eff, k_margin, cfg, drift):
    prior_mean, prior_sd, poll_mean, poll_sd, k_margin = (np.asarray(x, dtype=float) for x in
                                                          (prior_mean, prior_sd, poll_mean, poll_sd, k_margin))
    has_p, has_k = ~np.isnan(poll_mean), ~np.isnan(k_margin) & kalshi_on(cfg)
    pi_f = 1.0 / prior_sd ** 2 * np.ones_like(poll_mean)
    with np.errstate(divide="ignore", invalid="ignore"):
        pi_p = np.where(has_p, cfg["POLL_PRECISION_MULT"] / poll_sd ** 2, 0.0)
    pi_k = np.where(has_k, 1.0 / (cfg["KALSHI_SD"] or 1.0) ** 2, 0.0)
    P = pi_f + pi_p + pi_k
    wf, wp, wk = pi_f / P, pi_p / P, pi_k / P
    mean = wf * prior_mean + wp * np.nan_to_num(poll_mean) + wk * np.nan_to_num(k_margin)
    var = 1.0 / P
    if cfg["CORRELATED_ERRORS"]:
        var = var + 2 * cfg["SOURCE_ERROR_CORR"] / P ** 2 * (np.sqrt(pi_f * pi_p) + np.sqrt(pi_f * pi_k) + np.sqrt(pi_p * pi_k))
    return mean, np.sqrt(var + drift ** 2), wf, wp, wk


def drift_sd(cfg, today):
    days_left = max((pd.Timestamp(cfg["ELECTION_DAY"]) - today).days, 0)
    return cfg["DAILY_DRIFT_SD"] * np.sqrt(days_left)


def kalshi_to_margin(p_dem, sd_model, cfg):
    p = pd.Series(p_dem, dtype=float)
    lo, hi = cfg["KALSHI_USE_RANGE"]
    pc = p.clip(*SOURCES["KALSHI_PROB_CLIP"])
    p_adj = 1 / (1 + np.exp(-cfg["KALSHI_LONGSHOT_SLOPE"] * np.log(pc / (1 - pc))))
    sd = np.maximum(float(cfg["KALSHI_CONVERT_SD"]), sd_model)
    return pd.Series(norm.ppf(p_adj) * sd, index=p.index).where(p.between(lo, hi)), p_adj


def kalshi_prices(data, cfg):
    """P(Democrat - or the independent on the D side - wins) per district from Kalshi, and P(D control)."""
    k = data["kalshi_races"]
    out = {}
    for d, g in k[k["district"] != "CONTROL"].groupby("district"):
        dm, rm = g[g["side"] == "D"]["p_mid"].dropna(), g[g["side"] == "R"]["p_mid"].dropna()
        ind = cfg["INDEPENDENTS"].get(d)
        if ind and ind["side"] == "D":  # the D market is the Democrat, not the independent: use 1 - P(Republican)
            if len(rm):
                out[d] = 1 - float(rm.iloc[0])
            continue
        if ind and ind["side"] == "R":  # the R market (if any) isn't the independent: use P(Democrat)
            if len(dm):
                out[d] = float(dm.iloc[0])
            continue
        if len(dm) and len(rm):
            pd_, pr_ = float(dm.iloc[0]), float(rm.iloc[0])
            out[d] = pd_ / (pd_ + pr_) if pd_ + pr_ > 0 else np.nan  # removes the two markets' overround
        elif len(dm):
            out[d] = float(dm.iloc[0])
        elif len(rm):
            out[d] = 1 - float(rm.iloc[0])
    ctrl = k.loc[k["district"] == "CONTROL", "p_mid"]
    return pd.Series(out, dtype=float), (float(ctrl.iloc[0]) if len(ctrl) and pd.notna(ctrl.iloc[0]) else np.nan)


def build_race_table(data, poll_avg, env, cfg, today):
    r = data["districts"].copy()
    r["fixed"] = r["race_type"].map({"D_only": 1.0, "DD": 1.0, "RR": 0.0})  # certain result (1 = D seat), NaN = modelled
    inc = r["incumbent_party"].map({"D": 1.0, "R": -1.0, "I": -1.0}).fillna(0.0)
    r["incumbency_pts"] = np.where(r["status"] == "running", inc * cfg["INCUMBENCY_ADVANTAGE"], 0.0)
    r["manual_adj"] = pd.Series(cfg["DISTRICT_PRIOR_ADJUSTMENTS"], dtype=float).reindex(r.index).fillna(0.0)
    r["prior_mean"] = (cfg["PVI_TO_MARGIN"] * r["partisan_lean"] + cfg["ENV_ELASTICITY_DEFAULT"] * env
                       + r["incumbency_pts"] + r["manual_adj"])
    r["prior_sd"] = cfg["PRIOR_SD"] * np.where(r["race_type"] == "IND", cfg["INDEPENDENT_PRIOR_SD_MULT"], 1.0)
    r = r.join(poll_avg)
    for c in ("n_polls", "n_surveys"):
        r[c] = r[c].fillna(0).astype(int)
    r["n_eff"] = r["n_eff"].fillna(0.0)
    drift = drift_sd(cfg, today)
    nok = np.full(len(r), np.nan)
    pf = posterior(r["prior_mean"], r["prior_sd"], r["poll_mean"], r["poll_sd"], r["n_eff"], nok, cfg, drift)
    r["pf_mean"], r["pf_sd"] = pf[0], pf[1]
    kp, kctrl = kalshi_prices(data, cfg)
    r["kalshi_p"] = kp.reindex(r.index)
    r["kalshi_margin"], r["kalshi_p_adj"] = kalshi_to_margin(r["kalshi_p"], r["pf_sd"], cfg)
    m, s, wf, wp, wk = posterior(r["prior_mean"], r["prior_sd"], r["poll_mean"], r["poll_sd"], r["n_eff"],
                                 r["kalshi_margin"], cfg, drift)
    r["post_mean"], r["post_sd"], r["share_prior"], r["share_polls"], r["share_kalshi"] = m, s, wf, wp, wk
    fx = r["fixed"].notna()
    r.loc[fx, ["post_mean", "post_sd", "share_prior", "share_polls", "share_kalshi"]] = np.nan
    r.loc[fx, "post_mean"] = np.where(r.loc[fx, "fixed"] == 1, 100.0, -100.0)  # shown as "uncontested"
    return r, kctrl


# =====================================================================================================================
# Step 7: simulations (chunked; nothing of size n_sims x 435 is kept)
# =====================================================================================================================
def t_unit(rng, df, shape):
    z = rng.standard_normal(shape)
    if df is None:
        return z
    return z / np.sqrt(rng.chisquare(df, size=shape) / df) * np.sqrt((df - 2) / df)


class UnratedDraws:
    """Per simulation, ungraded pollsters get a random graded pollster's grade, error and lean; the polled districts'
    averages and posteriors are recomputed (the Senate model's unrated_draws, chunked)."""

    def __init__(self, polls, races, cfg, data, today):
        self.on = cfg["UNRATED_POLLSTERS"] == "random" and len(polls) and polls["Unrated"].any()
        if not self.on:
            return
        self.cfg, self.pool = cfg, grade_pool(data, cfg)
        self.cols = [races.index.get_loc(d) for d in sorted(polls["District"].unique())]
        idx = races.index[self.cols]
        self.unr = polls["Unrated"].to_numpy(dtype=bool)
        self.codes, uniq = pd.factorize(polls.loc[self.unr, "Pollster"])
        self.n_unr = len(uniq)
        self.nonpart = ~polls["partisan_poll"].to_numpy(dtype=bool)[self.unr]
        self.ind = (polls["District"].to_numpy()[:, None] == idx.to_numpy()[None, :]).astype(float)
        self.base_w, self.base_a, self.base_e = (polls[c].to_numpy(dtype=float) for c in ("weight", "adj_margin", "poll_error_sd"))
        self.und = polls["undecided_sd"].to_numpy(dtype=float)
        self.a_raw_u = polls["adj_margin_raw"].to_numpy(dtype=float)[self.unr]
        self.he_n_u, self.he_sum_u = (polls[c].to_numpy(dtype=float)[self.unr] for c in ("he_n", "he_sum"))
        self.w_base_u = polls.loc[self.unr, "w_base"].to_numpy(dtype=float)
        self.samp_u = polls.loc[self.unr, "samp_sd"].to_numpy(dtype=float)
        sub = races.iloc[self.cols]
        self.prior_m, self.prior_s = sub["prior_mean"].to_numpy(), sub["prior_sd"].to_numpy()
        self.k_m = sub["kalshi_margin"].to_numpy()
        self.drift = drift_sd(cfg, today)

    def draw(self, rng, n):
        cfg, pool = self.cfg, self.pool
        draw = rng.integers(0, len(pool["quality"]), size=(n, self.n_unr))[:, self.codes]
        pes_u, wa_u = accuracy_parts(self.samp_u[None, :], pool["mae"][draw], cfg)
        W, A, E = np.tile(self.base_w, (n, 1)), np.tile(self.base_a, (n, 1)), np.tile(self.base_e, (n, 1))
        W[:, self.unr] = self.w_base_u * pool["quality"][draw] * wa_u
        E[:, self.unr] = pes_u
        if cfg["SCORECARD_HOUSE_EFFECTS"]:
            k_ = cfg["HOUSE_EFFECT_K"]
            lean = (self.he_sum_u[None, :] + k_ * pool["lean"][draw]) / (self.he_n_u[None, :] + k_)
            A[:, self.unr] = np.where(self.nonpart, self.a_raw_u - lean, A[:, self.unr])
        sw = W @ self.ind
        with np.errstate(invalid="ignore", divide="ignore"):
            pm = ((W * A) @ self.ind) / sw
            n_eff = sw ** 2 / ((W ** 2) @ self.ind)
            single = ((W * E ** 2) @ self.ind) / sw
            und_sd = ((W * self.und) @ self.ind) / sw
            psd = np.sqrt(single / n_eff + cfg["SYSTEMATIC_POLL_ERROR_SD"] ** 2 + und_sd ** 2)
        m, s, *_ = posterior(self.prior_m, self.prior_s, pm, psd, n_eff, np.broadcast_to(self.k_m, pm.shape), cfg, self.drift)
        return m, s


def error_pieces(races, cfg):
    """Codes and loadings for the shared errors. A district whose own SD is smaller than the shared pieces gets them
    scaled down (loading < 1) so its total uncertainty is kept."""
    f = np.clip(races["partisan_lean"].to_numpy(dtype=float) / cfg["LEAN_FACTOR_SCALE"], -2, 2)
    reg_codes, regs = pd.factorize(races["region"])
    st_codes, sts = pd.factorize(races["state_abbr"])
    return f, reg_codes, len(regs), st_codes, len(sts)


def simulate_chunk(mu, sd, pieces, cfg, rng, n, independent=False):
    f, reg_codes, n_reg, st_codes, n_st = pieces
    k = mu.shape[-1]
    sN, sR, sS, sL = cfg["NATIONAL_ERROR_SD"], cfg["REGIONAL_ERROR_SD"], cfg["STATE_ERROR_SD"], cfg["LEAN_FACTOR_ERROR_SD"]
    shared_var = sN ** 2 + sR ** 2 + sS ** 2 + (sL * f) ** 2
    sd = np.broadcast_to(sd, (n, k))
    room = np.maximum(sd ** 2 - cfg["MIN_DISTRICT_ERROR_SD"] ** 2, 0.0)
    load = np.sqrt(np.minimum(1.0, room / shared_var))
    if independent:
        nat = sN * t_unit(rng, cfg["NATIONAL_T_DF"], (n, k))
        reg = sR * rng.standard_normal((n, k))
        st = sS * rng.standard_normal((n, k))
        lean = sL * rng.standard_normal((n, k)) * f
    else:
        nat = sN * t_unit(rng, cfg["NATIONAL_T_DF"], (n, 1))
        reg = (sR * rng.standard_normal((n, n_reg)))[:, reg_codes]
        st = (sS * rng.standard_normal((n, n_st)))[:, st_codes]
        lean = sL * rng.standard_normal((n, 1)) * f[None, :]
    shared = load * (nat + reg + st + lean)
    s_own = np.sqrt(np.maximum(sd ** 2 - load ** 2 * shared_var, cfg["MIN_DISTRICT_ERROR_SD"] ** 2))
    return mu + shared + s_own * t_unit(rng, cfg["STATE_T_DF"], (n, k))


def run_simulations(races, polls, cfg, data, today, n_sims, rng):
    need = cfg["D_SEATS_FOR_CONTROL"]
    fixed = races["fixed"]
    model_idx = np.where(fixed.isna())[0]
    fixed_d = int((fixed == 1).sum())
    mr = races.iloc[model_idx]
    mu0, sd0 = mr["post_mean"].to_numpy(), mr["post_sd"].to_numpy()
    caucus = np.array([cfg["INDEPENDENTS"].get(d, {}).get("caucus_prob_d", 1.0)
                       if cfg["INDEPENDENTS"].get(d, {}).get("side") == "D" else 1.0 for d in mr.index])
    pieces = error_pieces(mr, cfg)
    ud = UnratedDraws(polls, mr, cfg, data, today)
    wins = np.zeros(len(mr)); wins_ind = np.zeros(len(mr)); pivot = np.zeros(len(mr))
    seats = np.empty(n_sims, dtype=np.int32)
    tip_margin = []
    need_model = need - fixed_d
    for s0 in range(0, n_sims, cfg["SIM_CHUNK"]):
        n = min(cfg["SIM_CHUNK"], n_sims - s0)
        mu, sd = np.tile(mu0, (n, 1)), np.tile(sd0, (n, 1))
        if ud.on:
            m_, s_ = ud.draw(rng, n)
            mu[:, ud.cols], sd[:, ud.cols] = m_, s_
        m = simulate_chunk(mu, sd, pieces, cfg, rng, n)
        dwin = m > 0  # the Democrat (or the D-side independent) wins
        wins += dwin.sum(axis=0)
        dseat = dwin & (rng.random((n, len(caucus))) < caucus[None, :])  # an independent's seat counts with caucus_prob_d
        seats[s0:s0 + n] = fixed_d + dseat.sum(axis=1)
        wins_ind += (simulate_chunk(mu, sd, pieces, cfg, rng, n, independent=True) > 0).sum(axis=0)
        if 0 < need_model <= m.shape[1]:
            order = np.argpartition(-m, need_model - 1, axis=1)[:, need_model - 1]  # the district that gives seat 218
            pivot += np.bincount(order, minlength=m.shape[1])
            tip_margin.append(m[np.arange(n), order])
    p = pd.Series(np.nan, index=races.index)
    p.iloc[model_idx] = wins / n_sims
    p[fixed == 1], p[fixed == 0] = 1.0, 0.0
    p_ind = p.copy()
    p_ind.iloc[model_idx] = wins_ind / n_sims
    deciding = pd.Series(pivot / n_sims, index=mr.index).sort_values(ascending=False)
    tip = np.concatenate(tip_margin) if tip_margin else np.array([np.nan])
    return p, p_ind, seats, deciding, tip


# =====================================================================================================================
# Step 8: run everything
# =====================================================================================================================
def race_call(p, cfg):
    fav = max(p, 1 - p)
    if fav < cfg["RATING_TOSSUP"]:
        return "Toss-up"
    return ("Lean " if fav < cfg["RATING_LEAN"] else "Likely " if fav < cfg["RATING_LIKELY"] else "Safe ") + ("D" if p >= 0.5 else "R")


def run_model(data, cfg, n_sims=None, verbose=True):
    validate_config(cfg)
    n_sims = int(n_sims or cfg["N_SIMS"])
    rng = np.random.default_rng(cfg["SEED"])
    today = resolve_today(cfg)
    cfg = dict(cfg)
    if cfg["RV_MARGIN_SHIFT"] == "estimate":
        cfg["_rv_shift"], n_pairs = estimate_rv_shift(data, cfg, today)
    else:
        cfg["_rv_shift"], n_pairs = float(cfg["RV_MARGIN_SHIFT"]), 0
    polls = clean_polls(data["polls"], cfg, today)
    polls = apply_version_mode(polls, cfg)
    polls = compute_margins(polls, cfg)
    polls = weight_polls(polls, cfg, today, data)
    polls = adjust_margins(polls, cfg, data)
    poll_avg = polling_averages(polls, cfg) if len(polls) else pd.DataFrame(columns=POLL_AVG_COLS, dtype=float)
    env = national_environment(data, cfg, today)
    races, k_ctrl = build_race_table(data, poll_avg, env["env"], cfg, today)
    p, p_ind, seats, deciding, tip = run_simulations(races, polls, cfg, data, today, n_sims, rng)
    races["p_dem"], races["p_dem_independent"] = p, p_ind
    races["call"] = [race_call(x, cfg) for x in races["p_dem"]]
    need = cfg["D_SEATS_FOR_CONTROL"]
    # Kalshi "expected seats": Kalshi's price where a district is listed, the model's probability elsewhere
    kp = races["kalshi_p"]
    cp = pd.Series({d: v.get("caucus_prob_d", 1.0) for d, v in cfg["INDEPENDENTS"].items() if v.get("side") == "D"}).reindex(races.index).fillna(1.0)
    k_seats = float((np.where(kp.notna(), kp, races["p_dem"]) * cp).sum())
    summary = {"p_d_218": float((seats >= need).mean()), "exp_d_seats": float(seats.mean()),
               "median_d_seats": float(np.median(seats)), "p10": float(np.percentile(seats, 10)),
               "p90": float(np.percentile(seats, 90)), "env": float(env["env"]), "rv_shift": float(cfg["_rv_shift"]),
               "rv_pairs": int(n_pairs), "kalshi_p_control": k_ctrl, "kalshi_expected_seats": k_seats,
               "kalshi_districts": int(kp.notna().sum()), "tipping_point_margin": float(np.nanmedian(tip))}
    summary["p_d_control"] = summary["p_d_218"]
    if verbose:
        print(f"As of {today:%Y-%m-%d}: environment D{env['env']:+.1f} (generic ballot D{env['env_generic']:+.1f}, "
              f"net approval {env['net_approval']:+.1f}); RV shift {cfg['_rv_shift']:+.2f} ({n_pairs} pairs)")
        print(f"{len(polls)} polls in {races['n_polls'].gt(0).sum()} districts; Kalshi prices for {kp.notna().sum()} districts")
        print(f"D seats: mean {summary['exp_d_seats']:.1f}, 80% {summary['p10']:.0f}-{summary['p90']:.0f} | "
              f"P(D >= {need}) = {summary['p_d_218']:.1%} | Kalshi control {k_ctrl:.1%}")
    return {"polls": polls, "poll_avg": poll_avg, "env": env, "races": races, "seats": seats, "summary": summary,
            "today": today, "deciding": deciding, "cfg": cfg, "n_sims": n_sims}


# =====================================================================================================================
# Checks (the House version of Model Testing): PASS / WARN / FAIL rows
# =====================================================================================================================
def model_checks(data, res, cfg):
    out = []

    def add(section, check, ok, detail, warn_only=True):
        out.append({"section": section, "check": check, "status": "PASS" if ok else ("WARN" if warn_only else "FAIL"),
                    "detail": detail})
    d, r, s = data["districts"], res["races"], res["summary"]
    add("data", "435 districts, each with a partisan lean and region",
        len(d) == 435 and d["partisan_lean"].notna().all() and d["region"].notna().all(),
        f"{len(d)} rows; missing lean {int(d['partisan_lean'].isna().sum())}; missing region {int(d['region'].isna().sum())}", False)
    add("data", "every source downloaded live this run", all(v == "live" for v in SOURCE_STATUS.values()),
        ", ".join(f"{k}: {v}" for k, v in SOURCE_STATUS.items()))
    nk = int(r["kalshi_p"].notna().sum())
    add("Kalshi", "district markets found (expect 40+)", nk >= 40, f"{nk} districts with a price"
        + (f"; {len(KALSHI_LOG)} Kalshi requests failed" if KALSHI_LOG else ""))
    add("Kalshi", "House-control market found", pd.notna(s["kalshi_p_control"]), f"P(D control) = {s['kalshi_p_control']}")
    nc = data["nominee_check"]
    if len(nc):
        bad = nc[~nc["matches_file"]]
        add("Kalshi", "Kalshi nominee names agree with the district file", bad.empty,
            "all agree" if bad.empty else "differ: " + "; ".join(f"{x.district} Kalshi {x.dem} / {x.rep}" for x in bad.head(8).itertuples()))
    raw_n = len(data["house"])
    add("polls", "VoteHub district polls matched to both nominees (expect most)",
        raw_n == 0 or len(data["polls"]) >= 0.5 * raw_n,
        f"{len(data['polls'])} of {raw_n} general-election rows matched; {data['n_unmatched']} dropped (a nominee missing)")
    polled = r[r["n_polls"] > 0]
    add("polls", "polled districts", len(polled) > 0, f"{len(polled)} districts with polls, {int(r['n_polls'].sum())} polls used")
    env = res["env"]["env"]
    add("national", "environment within D-10 to R-10", -10 <= env <= 10, f"D{env:+.1f}")
    for dd, v in cfg["INDEPENDENTS"].items():
        if dd in r.index:
            add("data", f"{dd}: independent {v['name']} modelled on the {v['side']} side", r.loc[dd, "race_type"] == "IND",
                f"P(D-side candidate wins) {r.loc[dd, 'p_dem']:.0%}, counts for D with probability {v['caucus_prob_d']:g}; race_type {r.loc[dd, 'race_type']}")
    gap = (r["p_dem"] - r["p_dem_independent"]).abs()
    tol = max(0.03, 4 * 0.5 / np.sqrt(res["n_sims"]))  # 3 pts, or simulation noise in small test runs
    add("simulation", f"correlated vs independent race probabilities agree (< {tol:.0%})", gap.max() < tol,
        f"largest gap {gap.max():.3f} ({gap.idxmax()})")
    fixed = r["fixed"].notna()
    add("simulation", "fixed seats (single-party races)", True,
        f"{int((r['fixed'] == 1).sum())} certain D, {int((r['fixed'] == 0).sum())} certain R")
    mk = r[r["kalshi_p"].notna()]
    big = mk[(mk["p_dem"] - mk["kalshi_p"]).abs() > 0.25]
    add("Kalshi", "no district differs from Kalshi by more than 25 pts", big.empty,
        "none" if big.empty else "; ".join(f"{i} model {x.p_dem:.0%} vs Kalshi {x.kalshi_p:.0%}" for i, x in big.head(8).iterrows()))
    if pd.notna(s["kalshi_p_control"]):
        g = s["p_d_218"] - s["kalshi_p_control"]
        add("Kalshi", "P(D control) within 15 pts of Kalshi's control market", abs(g) <= 0.15,
            f"model {s['p_d_218']:.1%} vs Kalshi {s['kalshi_p_control']:.1%}")
    add("simulation", "seat total possible", 0 <= s["exp_d_seats"] <= 435, f"mean {s['exp_d_seats']:.1f}", False)
    return pd.DataFrame(out)


# =====================================================================================================================
# Outputs
# =====================================================================================================================
def key_settings(cfg, res):
    c = cfg
    return {
        "Poll source": "VoteHub API (us-representative + generic ballot + approval)",
        "Poll age": f"all polls, half-life {c['RECENCY_HALF_LIFE_DAYS']} days",
        "Polls : fundamentals : Kalshi": (f"Bayesian precision (poll floor {c['SYSTEMATIC_POLL_ERROR_SD']:.1f}, prior SD {c['PRIOR_SD']:.1f}); "
                                          f"Kalshi precision 1/{c['KALSHI_SD']:g}^2, longshot-corrected, conversion SD >= {c['KALSHI_CONVERT_SD']}"),
        "Fundamentals": (f"{c['PVI_TO_MARGIN']:.2f} x partisan lean (2024 pres., 2026 lines) + national environment "
                         f"(generic-ballot blend {c['GENERIC_BALLOT_BLEND']:g})"),
        "Incumbency": f"{c['INCUMBENCY_ADVANTAGE']:.1f} pts for an incumbent running in the district",
        "LV : RV : A": " : ".join(f"{v:g}" for v in c["POPULATION_WEIGHTS"].values()) + f"; RV shift {res['summary']['rv_shift']:+.1f} (measured)",
        "Flooding penalty": f"1/k^{c['FLOOD_EXPONENT']}",
        "House effects": f"in-cycle, shrunk to scorecard (k {c['HOUSE_EFFECT_K']:g})",
        "Ungraded pollsters": c["UNRATED_POLLSTERS"],
        "National signals": f"VoteHub polls + Kalshi averages (= {c['NAT_KALSHI_POLL_EQUIV']} polls)",
        "Kalshi races": "Bayesian input + comparison (found automatically)" if kalshi_on(c) else "comparison only",
        "Source errors": (f"correlated (rho {c['SOURCE_ERROR_CORR']}); sims: national {c['NATIONAL_ERROR_SD']:.1f} + region "
                          f"{c['REGIONAL_ERROR_SD']:.1f} + state {c['STATE_ERROR_SD']:.1f} + district, in pts"),
        "Single-party races": "uncontested / same-party top-two seats counted as certain",
        "Calibration": f"house_calibration.json ({CALIBRATION.get('created', '?')})" if CALIBRATION else "none (CONFIG as written)",
    }


def save_outputs(data, res, cfg, checks):
    out = Path(cfg["OUT_DIR"]); std = out / "standard"
    std.mkdir(parents=True, exist_ok=True)
    r = res["races"]
    _json = lambda x: x.item() if hasattr(x, "item") else str(x)
    cols = ["state", "region", "race_type", "incumbent", "incumbent_party", "status", "dem_candidate", "rep_candidate",
            "partisan_lean", "pres24_margin", "incumbency_pts", "prior_mean", "prior_sd", "n_polls", "n_eff", "poll_mean",
            "poll_sd", "kalshi_p", "kalshi_p_adj", "kalshi_margin", "share_prior", "share_polls", "share_kalshi",
            "post_mean", "post_sd", "p_dem", "p_dem_independent", "call"]
    r[cols].to_csv(out / "race_probabilities.csv", index_label="district")
    res["polls"].to_csv(out / "polls_used.csv", index=False)
    res["env"]["table"].to_csv(out / "national_signals.csv")
    checks.to_csv(out / "checks.csv", index=False)
    res["deciding"].rename("deciding_share").to_csv(out / "deciding_seats.csv", index_label="district")
    pd.DataFrame({"district": r.index, "state": r["state"].values, "p_dem": r["p_dem"].values,
                  "margin": r["post_mean"].values, "sd": r["post_sd"].values, "kalshi_p": r["kalshi_p"].values,
                  "n_polls": r["n_polls"].values, "race_type": r["race_type"].values, "incumbent": r["incumbent"].values,
                  "status": r["status"].values,
                  "dem_candidate": [data["nominees"].get(d, ("", ""))[0] for d in r.index],  # names used (Kalshi where listed)
                  "rep_candidate": [data["nominees"].get(d, ("", ""))[1] for d in r.index],
                  "ind_side": [cfg["INDEPENDENTS"].get(d, {}).get("side", "") for d in r.index],
                  "partisan_lean": r["partisan_lean"].values, "pres24_margin": r["pres24_margin"].values,
                  "prior_mean": r["prior_mean"].values, "poll_mean": r["poll_mean"].values, "kalshi_margin": r["kalshi_margin"].values,
                  "share_prior": r["share_prior"].values, "share_polls": r["share_polls"].values, "share_kalshi": r["share_kalshi"].values,
                  "deciding_share": res["deciding"].reindex(r.index).fillna(0.0).values}).to_csv(std / "races.csv", index=False)
    sh = pd.Series(res["seats"]).value_counts(normalize=True).sort_index()
    pd.DataFrame({"dem_seats": sh.index, "share": sh.values}).to_csv(std / "seats.csv", index=False)
    snap = {k: v for k, v in cfg.items() if not k.startswith("_")}
    (out / "config_snapshot.json").write_text(json.dumps(snap, indent=2, default=_json))
    headline = {"as_of": f"{res['today']:%Y-%m-%d}", "run_at": pd.Timestamp.now().strftime("%Y-%m-%d %H:%M"), **res["summary"],
                "national": {"generic_ballot": res["env"]["env_generic"], "net_approval": res["env"]["net_approval"],
                             "env": res["env"]["env"]}, "sources": dict(SOURCE_STATUS), "kalshi_failures": len(KALSHI_LOG)}
    (out / "headline.json").write_text(json.dumps(headline, indent=2, default=_json))
    s = res["summary"]
    std_summary = {"model": "House_Model", "run_at": headline["run_at"], "as_of": headline["as_of"],
                   **{k: s[k] for k in ("p_d_218", "exp_d_seats", "median_d_seats", "p10", "p90", "kalshi_p_control",
                                        "kalshi_expected_seats", "kalshi_districts", "env", "rv_shift", "tipping_point_margin")},
                   "n_sims": res["n_sims"], "sources": dict(SOURCE_STATUS), "key_settings": key_settings(cfg, res)}
    (std / "summary.json").write_text(json.dumps(std_summary, indent=2, default=_json))
    return out


def run(n_sims=None, verbose=True):
    """Load data, run the model and the checks, save everything. Returns (res, checks, out_dir)."""
    cfg = apply_overrides(CONFIG)
    for k in ("OUT_DIR", "CACHE_DIR"):
        Path(cfg[k]).mkdir(parents=True, exist_ok=True)
    data = load_data(cfg)
    res = run_model(data, cfg, n_sims=n_sims, verbose=verbose)
    checks = model_checks(data, res, res["cfg"])
    out = save_outputs(data, res, res["cfg"], checks)
    if verbose:
        print(f"Checks: {(checks['status'] == 'PASS').sum()} PASS, {(checks['status'] == 'WARN').sum()} WARN, "
              f"{(checks['status'] == 'FAIL').sum()} FAIL | outputs in {out}")
    return res, checks, out


if __name__ == "__main__":
    run()
