"""
house_forecasts.py - scheduled House_Model forecasts + dashboard (Team 5, 2026 House). The House twin of
Final Model/final_forecast.py.

    python house_forecasts.py            start (or resume) the schedule: a run now, then every 3 hours, then one final
                                         run at 9:00 AM on Nov 3, then stop for good
    python house_forecasts.py --once     one full run now (100,000 simulations), saved to the history like a scheduled run
    python house_forecasts.py --test     one quick run (1,000 simulations) -> Forecasts/test_<datetime>.html; doesn't touch
                                         the schedule, the history or Output/
    python house_forecasts.py --status   show the schedule and what has run, then exit
    python house_forecasts.py --report   rebuild every saved run's dashboard + figures and latest.html with the current code
    python house_forecasts.py --reset    DELETE the schedule + history + run folders (tests kept) and start fresh

Each run executes house_model.run() (model + checks), saves everything in Forecasts/<YYYY-MM-DD_HHMM>/ (dashboard.html +
dashboard.pdf, figures/*.html + *.png, data/, inputs/), appends to Forecasts/history.csv and race_history.csv, logs every
WARN / FAIL check to Forecasts/model_warnings.xlsx, and copies the dashboard to Forecasts/latest.html and latest.pdf.
Schedule rules are the Senate script's: fixed clock times, runs never overlap, missed runs are made up with one run.
"""
import argparse
import datetime as dt
import json
import os
import re
import shutil
import subprocess
import sys
import time
import traceback
from pathlib import Path

# ============================== SETTINGS ==============================
N_SIMS = 100_000
TEST_N_SIMS = 1_000
INTERVAL_HOURS = 3
FINAL_RUN = dt.datetime(2026, 11, 3, 9, 0)
FINAL_BUFFER_HOURS = 1
SEAT_INTERVALS = (80, 95)
P_INTERVAL = 95
CONTROL_SEATS = 218
TOTAL_SEATS = 435
STATUS_EVERY_S = 60
# =======================================================================

HERE = Path(__file__).resolve().parent
REPO = HERE.parent
SENATE = REPO / "Senate Forecast" if (REPO / "Senate Forecast").is_dir() else REPO  # Senate model, Data/, Final Model/
TEAM = ["Elizabeth Miller", "Mark Scott", "Ethan Verrone", "Boaz Alkalay", "Leo Westebbe"]
MODEL_NAME = "House_Model"
MODEL_OUT = HERE / "Output"
OUT = HERE / "Forecasts"
STATE = OUT / "schedule.json"
HISTORY = OUT / "history.csv"
RACE_HISTORY = OUT / "race_history.csv"
WARNINGS_XLSX = OUT / "model_warnings.xlsx"

D_BLUE, R_RED, K_GRAY, INK, GRID = "#1A6FB0", "#C8312B", "#7A7A7A", "#2B2B2B", "#E6E6E6"
TOSS_PURPLE = "#8E6BBF"
CALLS = {"Safe D": "#08306B", "Likely D": D_BLUE, "Lean D": "#8DB8E2", "Toss-up": TOSS_PURPLE,
         "Lean R": "#EFA39D", "Likely R": R_RED, "Safe R": "#8A1D18"}
CALL_ORDER = list(CALLS)
TILES = {"AK": (0, 0), "ME": (11, 0), "VT": (10, 1), "NH": (11, 1), "WA": (1, 2), "ID": (2, 2), "MT": (3, 2), "ND": (4, 2), "MN": (5, 2),
         "IL": (6, 2), "WI": (7, 2), "MI": (8, 2), "NY": (9, 2), "RI": (10, 2), "MA": (11, 2), "OR": (1, 3), "NV": (2, 3), "WY": (3, 3),
         "SD": (4, 3), "IA": (5, 3), "IN": (6, 3), "OH": (7, 3), "PA": (8, 3), "NJ": (9, 3), "CT": (10, 3), "CA": (1, 4), "UT": (2, 4),
         "CO": (3, 4), "NE": (4, 4), "MO": (5, 4), "KY": (6, 4), "WV": (7, 4), "VA": (8, 4), "MD": (9, 4), "DE": (10, 4), "AZ": (2, 5),
         "NM": (3, 5), "KS": (4, 5), "AR": (5, 5), "TN": (6, 5), "NC": (7, 5), "SC": (8, 5), "OK": (4, 6), "LA": (5, 6), "MS": (6, 6),
         "AL": (7, 6), "GA": (8, 6), "HI": (0, 7), "TX": (4, 7), "FL": (9, 7)}
PACKAGES = {"pandas": "pandas", "numpy": "numpy", "scipy": "scipy", "plotly": "plotly", "matplotlib": "matplotlib",
            "openpyxl": "openpyxl"}


def ensure_packages():
    import importlib.util
    missing = [pip for mod, pip in PACKAGES.items() if importlib.util.find_spec(mod) is None]
    if missing:
        print(f"Installing {', '.join(missing)} ...", flush=True)
        subprocess.check_call([sys.executable, "-m", "pip", "install", "--quiet", *missing])


ensure_packages()
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

sys.path.insert(0, str(HERE))
import house_model  # noqa: E402


# ------------------------------------------------------------------ console + schedule (as in final_forecast.py)
def now():
    return dt.datetime.now().replace(microsecond=0)


def fmt_td(seconds):
    seconds = max(int(seconds), 0)
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    return f"{h}h {m:02d}m" if h else f"{m}m {s:02d}s"


def fmt_t(t):
    return t.strftime("%a %b %d, %I:%M %p").replace(" 0", " ")


def say(msg):
    print(f"[{now():%H:%M:%S}] {msg}", flush=True)


def load_state():
    return json.loads(STATE.read_text()) if STATE.exists() else None


def save_state(st):
    OUT.mkdir(parents=True, exist_ok=True)
    STATE.write_text(json.dumps(st, indent=2))


def slot_times(anchor):
    slots, t = [], anchor
    while t <= FINAL_RUN - dt.timedelta(hours=FINAL_BUFFER_HOURS):
        slots.append(t)
        t += dt.timedelta(hours=INTERVAL_HOURS)
    return slots + [FINAL_RUN]


def pending(st):
    done = set(st["done_slots"])
    return [t for t in slot_times(dt.datetime.fromisoformat(st["anchor"])) if t.isoformat() not in done]


def print_schedule(st):
    slots = slot_times(dt.datetime.fromisoformat(st["anchor"]))
    done = set(st["done_slots"])
    print(f"\nSchedule (started {fmt_t(dt.datetime.fromisoformat(st['anchor']))}; every {INTERVAL_HOURS} h; final run {fmt_t(FINAL_RUN)}):")
    for i, t in enumerate(slots, 1):
        tag = "FINAL" if t == FINAL_RUN else f"#{i}"
        print(f"  {tag:>5}  {fmt_t(t):<24} {'done' if t.isoformat() in done else ('due' if t <= now() else '')}")
    print(flush=True)


# ------------------------------------------------------------------ results
def seat_stats(seats):
    s = seats.sort_values("dem_seats")
    x, w = s["dem_seats"].to_numpy(float), s["share"].to_numpy(float)
    w = w / w.sum()
    cdf = np.cumsum(w)
    q = lambda p: float(x[min(np.searchsorted(cdf, p), len(x) - 1)])
    out = {"mean": float((x * w).sum()), "median": q(0.5)}
    for lvl in SEAT_INTERVALS:
        a = (1 - lvl / 100) / 2
        out[f"s{lvl}"] = (q(a), q(1 - a))
    return out


def rating_cuts(cfg):
    cfg = cfg or {}
    return tuple(float(cfg.get(k, d)) for k, d in (("RATING_TOSSUP", 0.60), ("RATING_LEAN", 0.75), ("RATING_LIKELY", 0.95)))


def race_call(p, cuts):
    toss, lean, likely = cuts
    fav = max(p, 1 - p)
    if fav < toss:
        return "Toss-up"
    return ("Lean " if fav < lean else "Likely " if fav < likely else "Safe ") + ("D" if p >= 0.5 else "R")


def cuts_label(cuts):
    toss, lean, likely = cuts
    return f"Toss-up under {toss:.0%}, Lean {toss:.0%}-{lean:.0%}, Likely {lean:.0%}-{likely:.0%}, Safe {likely:.0%}+"


def collect(model_out, n_sims, kind, slot, runtime_s, status):
    std = model_out / "standard"
    summ = json.loads((std / "summary.json").read_text())
    races = pd.read_csv(std / "races.csv", keep_default_na=False, na_values=[""])
    seats = pd.read_csv(std / "seats.csv")
    checks = pd.read_csv(model_out / "checks.csv") if (model_out / "checks.csv").exists() else None
    p = float(summ["p_d_218"])
    z = {90: 1.645, 95: 1.96, 99: 2.576}[P_INTERVAL]
    half = z * np.sqrt(p * (1 - p) / n_sims)
    st = seat_stats(seats)
    for k in ("kalshi_p_control", "kalshi_expected_seats"):
        if summ.get(k) is not None and pd.isna(summ[k]):
            summ[k] = None
    row = {"run_at": now().strftime("%Y-%m-%d %H:%M"), "kind": kind, "slot": slot, "as_of": summ.get("as_of"),
           "p_d_218": p, "p_lo": max(p - half, 0), "p_hi": min(p + half, 1), "mean_seats": st["mean"], "median_seats": st["median"],
           **{f"s{l}_lo": st[f"s{l}"][0] for l in SEAT_INTERVALS}, **{f"s{l}_hi": st[f"s{l}"][1] for l in SEAT_INTERVALS},
           "kalshi_p_control": summ.get("kalshi_p_control"), "kalshi_seats": summ.get("kalshi_expected_seats"),
           "kalshi_districts": summ.get("kalshi_districts"), "env": summ.get("env"),
           "n_sims": n_sims, "runtime_min": round(runtime_s / 60, 1),
           "testing_pass": int((checks["status"] == "PASS").sum()) if checks is not None else None,
           "testing_warn": int((checks["status"] == "WARN").sum()) if checks is not None else None,
           "testing_fail": int((checks["status"] == "FAIL").sum()) if checks is not None else None,
           "sources_live": sum(v == "live" for v in summ.get("sources", {}).values()), "sources_total": len(summ.get("sources", {}))}
    load = lambda f: json.loads(f.read_text()) if f.exists() else {}
    cfg = load(model_out / "config_snapshot.json")
    cuts = rating_cuts(cfg)
    races["call"] = [race_call(x, cuts) for x in races["p_dem"]]
    return {"summary": summ, "races": races, "seats": seats, "row": row, "checks": checks, "status": status, "cuts": cuts,
            "cfg": cfg, "headline": load(model_out / "headline.json")}


def competitive(races):
    """Districts worth showing one by one: not Safe, or listed on Kalshi (single-party races excluded)."""
    r = races[races["race_type"].isin(["DR", "IND"])]
    return r[(r["call"] != "Safe D") & (r["call"] != "Safe R") | r["kalshi_p"].notna()]


# ------------------------------------------------------------------ figures
ASCII_MAP = {"\u00d7": "x", "\u00b7": "|", "\u2014": "-", "\u2013": "-", "\u2212": "-", "\u2265": ">=", "\u2264": "<=", "\u00b1": "+/-",
             "\u00b2": "^2", "\u221a": "sqrt", "\u2192": "->", "\u2018": "'", "\u2019": "'", "\u201c": '"', "\u201d": '"', "\u2026": "...",
             "\u00a0": " ", "\u2248": "~", "\u2032": "'"}
MATHJAX_URL = "https://cdn.jsdelivr.net/npm/mathjax@3.2.2/es5/tex-svg.js"


def ascii_text(s):
    import unicodedata
    s = "".join(ASCII_MAP.get(ch, ch) for ch in str(s))
    return unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode("ascii")


def mathjax_script():
    cfg = "<script>window.MathJax={tex:{inlineMath:[['\\\\(','\\\\)']]},svg:{fontCache:'global'}};</script>"
    cache = OUT / ".cache" / "mathjax-tex-svg-3.2.2.js"
    senate_cache = SENATE / "Final Model" / "Forecasts" / ".cache" / "mathjax-tex-svg-3.2.2.js"
    try:
        if not cache.exists():
            cache.parent.mkdir(parents=True, exist_ok=True)
            if senate_cache.exists():
                shutil.copy2(senate_cache, cache)
            else:
                import urllib.request
                with urllib.request.urlopen(MATHJAX_URL, timeout=30) as r:
                    cache.write_bytes(r.read())
        js = cache.read_text(encoding="utf-8").replace("</script", "<\\/script")
        return cfg + f"<script>{js}</script>"
    except Exception as e:
        say(f"MathJax couldn't be embedded ({type(e).__name__}); the equations will load it from the web")
        return cfg + f"<script src='{MATHJAX_URL}'></script>"


def pct_label(p):
    if p is None or pd.isna(p):
        return "-"
    return "<1%" if p < 0.01 else (">99%" if p > 0.99 else f"{p:.0%}")


def margin_label(m, race_type="DR"):
    if race_type in ("D_only", "DD"):
        return "D (no R)"
    if race_type == "RR":
        return "R (no D)"
    return "-" if pd.isna(m) else (f"D+{m:.1f}" if m >= 0 else f"R+{-m:.1f}")


def matchup(x):
    clean = lambda v: "" if v is None or (isinstance(v, float) and np.isnan(v)) else str(v)
    d, r = clean(x.get("dem_candidate")), clean(x.get("rep_candidate"))
    side = clean(x.get("ind_side"))
    if x.get("race_type") == "IND" and side == "D":
        return f"{d} (I) vs {r} (R)"
    if x.get("race_type") == "IND":
        return f"{d} (D) vs {r} (I)"
    return (f"{d} (D)" if d else "D") + " vs " + (f"{r} (R)" if r else "R")


def state_frame(res):
    r = res["races"].copy()
    r["st"] = r["district"].str[:2]
    g = r.groupby("st").agg(seats=("district", "size"), exp_d=("p_dem", "sum"),
                             close=("call", lambda c: int(c.isin(["Toss-up", "Lean D", "Lean R"]).sum())))
    g["share_d"] = g["exp_d"] / g["seats"]
    return g


def share_color(share, mpl=False):
    """Blue above 50% D seats, red below, stronger the further from 50%; dark text on pale tiles."""
    a = min(abs(float(share) - 0.5) * 2, 1) * 0.85 + 0.15
    rgb = (26, 111, 176) if share >= 0.5 else (200, 49, 43)
    mix = tuple(int(255 + (c - 255) * a) for c in rgb)
    txt = "white" if a > 0.55 else INK
    return (tuple(c / 255 for c in mix), txt) if mpl else (f"rgb{mix}", txt)


def waffle_frame(res, cols=29):
    r = res["races"].sort_values("p_dem", ascending=False).reset_index(drop=True)
    r["col"], r["row"] = r.index // 15, r.index % 15
    return r


def plotly_figs(res, hist):
    import plotly.graph_objects as go
    row, races, seats = res["row"], res["races"].copy(), res["seats"]
    base = dict(template="simple_white", font=dict(family="Inter, Segoe UI, Arial", size=13, color=INK),
                margin=dict(l=60, r=30, t=50, b=50), hoverlabel=dict(bgcolor="white"))
    figs = {}
    # 1. seat distribution
    s = seats.sort_values("dem_seats")
    f = go.Figure(go.Bar(x=s["dem_seats"], y=100 * s["share"], marker_color=np.where(s["dem_seats"] >= CONTROL_SEATS, D_BLUE, R_RED),
                         hovertemplate="%{x} D seats: %{y:.2f}% of simulations<extra></extra>"))
    f.add_vline(x=CONTROL_SEATS - 0.5, line=dict(color=INK, width=1.5))
    left_first = row["kalshi_seats"] is None or row["mean_seats"] <= row["kalshi_seats"]
    f.add_vline(x=row["mean_seats"], line=dict(color=D_BLUE, width=2, dash="dot"),
                annotation=dict(text=f"Model mean {row['mean_seats']:.1f}", font=dict(color=D_BLUE), xanchor="right" if left_first else "left",
                                yanchor="bottom", y=1.0, yref="paper"), annotation_position="top left" if left_first else "top right")
    if row["kalshi_seats"] is not None:
        f.add_vline(x=row["kalshi_seats"], line=dict(color=K_GRAY, width=2, dash="dash"),
                    annotation=dict(text=f"Kalshi (race prices) {row['kalshi_seats']:.1f}", font=dict(color=K_GRAY),
                                    xanchor="left" if left_first else "right", yanchor="bottom", y=1.0, yref="paper"),
                    annotation_position="top right" if left_first else "top left")
    kc = row["kalshi_p_control"]
    f.update_layout(**base, title=f"Democratic House seats in {row['n_sims']:,} simulations - P(D >= {CONTROL_SEATS}): Model "
                    f"{row['p_d_218']:.1%}" + (f" | Kalshi {kc:.1%}" if kc is not None else ""),
                    xaxis_title="Democratic seats", yaxis_title="% of simulations", showlegend=False, bargap=0.1, height=450)
    f.update_layout(margin=dict(l=60, r=30, t=80, b=50))
    f.update_xaxes(range=[s.loc[s["share"].cumsum() > 0.001, "dem_seats"].min() - 1.5,
                          s.loc[s["share"].cumsum() < 0.999, "dem_seats"].max() + 1.5])
    figs["seat_distribution"] = f

    # 2. all 435 seats, safest D to safest R (one square per district)
    w = waffle_frame(res)
    f = go.Figure()
    for call in CALL_ORDER:
        g = w[w["call"] == call]
        hov = (g["district"] + " - " + call + "<br>" + g.apply(matchup, axis=1) + "<br>Model " + g["p_dem"].map(pct_label)
               + " | Kalshi " + g["kalshi_p"].map(pct_label) + "<br>projected "
               + [margin_label(m, t) for m, t in zip(g["margin"], g["race_type"])])
        f.add_trace(go.Scatter(x=g["col"], y=-g["row"], mode="markers", name=f"{call} ({len(g)})", text=hov,
                               hovertemplate="%{text}<extra></extra>", marker=dict(symbol="square", size=13, color=CALLS[call],
                                                                                      line=dict(color="white", width=1))))
    t = w.iloc[CONTROL_SEATS - 1]  # the 218th-best seat for Democrats
    f.add_trace(go.Scatter(x=[t["col"]], y=[-t["row"]], mode="markers", showlegend=False, hoverinfo="skip",
                           marker=dict(symbol="square-open", size=21, color=INK, line=dict(width=2.5))))
    f.add_annotation(x=t["col"], y=-t["row"], text=f"seat {CONTROL_SEATS}: {t['district']}", showarrow=True, ay=-70, ax=0,
                     font=dict(size=11, color=INK), bgcolor="white", yanchor="bottom")
    f.update_layout(**{k: v for k, v in base.items() if k != "margin"}, margin=dict(l=10, r=10, t=70, b=10), height=400,
                    title=f"All 435 seats, from safest Democratic to safest Republican<br><sup>{cuts_label(res['cuts'])}</sup>",
                    xaxis=dict(visible=False), yaxis=dict(visible=False, scaleanchor="x"), plot_bgcolor="rgba(0,0,0,0)",
                    legend=dict(orientation="h", y=-0.02, x=0.5, xanchor="center", yanchor="top"))
    figs["seat_chart"] = f

    # 3. state tile map: expected D seats / seats
    m = state_frame(res)
    f = go.Figure()
    for ab, (cx, cy) in TILES.items():
        if ab not in m.index:
            continue
        x = m.loc[ab]
        col, txt = share_color(x["share_d"])
        f.add_shape(type="rect", x0=cx + 0.05, x1=cx + 0.95, y0=-cy + 0.05, y1=-cy + 0.95, fillcolor=col, opacity=1, layer="above",
                    line=dict(color="white", width=1.5))
        f.add_annotation(x=cx + 0.5, y=-cy + 0.5, text=f"<b>{ab}</b><br><span style='font-size:10px'>{x['exp_d']:.1f}/{int(x['seats'])}</span>",
                         showarrow=False, font=dict(color=txt, size=12))
    r = res["races"]
    hov = []
    for ab in m.index:
        close = r[(r["district"].str[:2] == ab) & r["call"].isin(["Toss-up", "Lean D", "Lean R", "Likely D", "Likely R"])]
        lst = "<br>".join(f"{d}: {c} ({pct_label(p)})" for d, c, p in zip(close["district"], close["call"], close["p_dem"])) or "no competitive districts"
        hov.append(f"{ab}: {m.loc[ab, 'exp_d']:.1f} of {int(m.loc[ab, 'seats'])} seats expected D<br>{lst}")
    f.add_trace(go.Scatter(x=[TILES[a][0] + 0.5 for a in m.index], y=[-TILES[a][1] + 0.5 for a in m.index], mode="markers",
                           text=hov, hovertemplate="%{text}<extra></extra>", marker=dict(symbol="square", size=34, opacity=0), showlegend=False))
    f.update_layout(**{k: v for k, v in base.items() if k != "margin"}, margin=dict(l=10, r=10, t=70, b=10), height=520,
                    title="Expected Democratic seats by state (number = expected D seats / seats; colour = D share)",
                    xaxis=dict(visible=False, range=[-0.2, 12.2]), yaxis=dict(visible=False, range=[-7.3, 1.2], scaleanchor="x"),
                    plot_bgcolor="rgba(0,0,0,0)")
    figs["state_map"] = f

    # 4. competitive districts: model vs Kalshi
    c = competitive(races).sort_values("p_dem")
    f = go.Figure()
    for _, x in c.iterrows():
        if pd.notna(x["kalshi_p"]):
            f.add_shape(type="line", x0=x["kalshi_p"], x1=x["p_dem"], y0=x["district"], y1=x["district"], line=dict(color=GRID, width=3))
    f.add_trace(go.Scatter(x=c["kalshi_p"], y=c["district"], mode="markers", name="Kalshi",
                           marker=dict(symbol="diamond", size=9, color=K_GRAY), hovertemplate="%{y}: Kalshi %{x:.1%}<extra></extra>"))
    f.add_trace(go.Scatter(x=c["p_dem"], y=c["district"], mode="markers", name=MODEL_NAME, marker=dict(size=10, color=D_BLUE),
                           customdata=np.column_stack([[margin_label(m) for m in c["margin"]], c["sd"].round(1), c.apply(matchup, axis=1)]),
                           hovertemplate="%{y}: Model %{x:.1%}<br>%{customdata[2]}<br>projected %{customdata[0]} +/- %{customdata[1]}<extra></extra>"))
    f.add_vline(x=0.5, line=dict(color=INK, width=1, dash="dot"))
    f.update_layout(**base, title=f"P(Democrat wins): the {len(c)} competitive or Kalshi-listed districts", height=max(500, 18 * len(c) + 120),
                    xaxis=dict(title="probability", tickformat=".0%", range=[-0.02, 1.02]), yaxis=dict(tickfont=dict(size=10)),
                    legend=dict(orientation="h", y=1.02, x=1, xanchor="right", yanchor="bottom"))
    figs["races_vs_kalshi"] = f

    # 5. model vs Kalshi, every district Kalshi lists
    k = races[races["kalshi_p"].notna() & races["race_type"].isin(["DR", "IND"])].copy()
    k["gap"] = k["p_dem"] - k["kalshi_p"]
    f = go.Figure()
    f.add_shape(type="line", x0=0, y0=0, x1=1, y1=1, line=dict(color=GRID, width=2))
    f.add_shape(type="rect", x0=0, y0=0, x1=1, y1=1, line=dict(width=0), fillcolor="rgba(0,0,0,0)")
    lab = k["gap"].abs() >= 0.10
    f.add_trace(go.Scatter(x=k["kalshi_p"], y=k["p_dem"], mode="markers+text", text=np.where(lab, k["district"], ""),
                           textposition="top center", textfont=dict(size=10),
                           marker=dict(size=10, color=[CALLS[c] for c in k["call"]], line=dict(color="white", width=1)),
                           customdata=np.column_stack([k["district"], k.apply(matchup, axis=1), k["gap"] * 100]),
                           hovertemplate="%{customdata[0]}: %{customdata[1]}<br>Model %{y:.0%} | Kalshi %{x:.0%} "
                                         "(%{customdata[2]:+.0f} pts)<extra></extra>", showlegend=False))
    f.update_layout(**base, height=560, title=f"Model vs Kalshi in the {len(k)} districts Kalshi lists "
                    f"(above the line = model more Democratic; labelled if 10+ pts apart)",
                    xaxis=dict(title="Kalshi P(D)", tickformat=".0%", range=[-0.03, 1.03]),
                    yaxis=dict(title="Model P(D)", tickformat=".0%", range=[-0.03, 1.03]), width=None)
    figs["model_vs_kalshi"] = f

    if not {"pres24_margin", "share_prior"} <= set(races.columns):  # runs saved before these columns existed
        return figs
    # 6. swing: projected margin against the 2024 presidential margin, contested districts
    c2 = races[races["race_type"].isin(["DR", "IND"]) & races["pres24_margin"].between(-40, 40)].copy()
    env = float(res["summary"].get("env") or 0)
    f = go.Figure()
    f.add_shape(type="line", x0=-40, y0=-40, x1=40, y1=40, line=dict(color=GRID, width=2))
    f.add_hline(y=0, line=dict(color=INK, width=1, dash="dot"))
    for call in CALL_ORDER:
        g = c2[c2["call"] == call]
        if g.empty:
            continue
        f.add_trace(go.Scatter(x=g["pres24_margin"], y=g["margin"], mode="markers", name=call,
                               marker=dict(size=8, color=CALLS[call], line=dict(color="white", width=0.5)),
                               customdata=np.column_stack([g["district"], g.apply(matchup, axis=1)]),
                               hovertemplate="%{customdata[0]}: %{customdata[1]}<br>2024 pres. %{x:+.1f} -> projected %{y:+.1f}<extra></extra>"))
    f.update_layout(**base, height=520, title=f"Projected 2026 margin vs 2024 presidential margin (grey line = no change; "
                    f"national environment D{env:+.1f})",
                    xaxis=dict(title="2024 presidential margin (D - R, pts)", range=[-41, 41], zeroline=False),
                    yaxis=dict(title="projected 2026 House margin (pts)", range=[-45, 55], zeroline=False),
                    legend=dict(orientation="h", y=-0.15, x=0.5, xanchor="center", yanchor="top"))
    f.update_layout(margin=dict(l=60, r=30, t=60, b=110))
    figs["swing"] = f

    # 7. tipping-point districts
    tp = races[races["deciding_share"] > 0].sort_values("deciding_share").tail(15)
    f = go.Figure(go.Bar(x=100 * tp["deciding_share"], y=tp["district"], orientation="h",
                         marker_color=[CALLS[c] for c in tp["call"]],
                         customdata=np.column_stack([tp.apply(matchup, axis=1), tp["p_dem"]]),
                         hovertemplate="%{y}: %{customdata[0]}<br>tipping point in %{x:.1f}% of simulations; "
                                       "P(D) %{customdata[1]:.0%}<extra></extra>"))
    f.update_layout(**base, height=480, title=f"Tipping-point districts: the district that delivers seat {CONTROL_SEATS} "
                    "(share of simulations)", xaxis_title="% of simulations", showlegend=False)
    figs["tipping_point"] = f

    # 8. what each forecast rests on: share of prior / polls / Kalshi in the closest districts
    sm = competitive(races).dropna(subset=["share_prior"]).copy()
    sm = sm.reindex((sm["p_dem"] - 0.5).abs().sort_values().index).head(40).iloc[::-1]
    f = go.Figure()
    for col, name, colr in (("share_prior", "Fundamentals", "#B9B9B9"), ("share_polls", "Polls", D_BLUE), ("share_kalshi", "Kalshi", "#E8A33D")):
        f.add_trace(go.Bar(x=100 * sm[col], y=sm["district"], orientation="h", name=name, marker_color=colr,
                           hovertemplate="%{y}: " + name + " %{x:.0f}%<extra></extra>"))
    f.update_layout(**base, barmode="stack", height=max(420, 17 * len(sm) + 140),
                    title=f"What each forecast rests on: the {len(sm)} closest districts", xaxis=dict(title="% of the projected margin", range=[0, 100]),
                    yaxis=dict(tickfont=dict(size=10)),
                    legend=dict(orientation="h", y=1.02, x=1, xanchor="right", yanchor="bottom", traceorder="normal"))
    figs["source_mix"] = f
    return figs


def png_figs(res, hist, folder):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import matplotlib.dates  # noqa: F401
    import matplotlib.patches  # noqa: F401
    import matplotlib.ticker  # noqa: F401
    plt.rcParams.update({"font.size": 10, "axes.spines.top": False, "axes.spines.right": False})
    row, races, seats = res["row"], res["races"], res["seats"].sort_values("dem_seats")
    paths = {}

    def save(fig, key):
        fig.tight_layout(); paths[key] = folder / f"{key}.png"; fig.savefig(paths[key], dpi=200); plt.close(fig)
    fig, ax = plt.subplots(figsize=(10, 4.6))
    ax.bar(seats["dem_seats"], 100 * seats["share"], color=np.where(seats["dem_seats"] >= CONTROL_SEATS, D_BLUE, R_RED), width=0.85)
    ax.axvline(CONTROL_SEATS - 0.5, color=INK, lw=1.5)
    ax.axvline(row["mean_seats"], color=D_BLUE, ls=":", lw=2, label=f"Model mean {row['mean_seats']:.1f}")
    if row["kalshi_seats"] is not None:
        ax.axvline(row["kalshi_seats"], color=K_GRAY, ls="--", lw=2, label=f"Kalshi {row['kalshi_seats']:.1f}")
    keep = seats[(seats["share"].cumsum() > 0.001) & (seats["share"].cumsum() < 0.999)]["dem_seats"]
    ax.set_xlim(keep.min() - 1.5, keep.max() + 1.5)
    ax.set_xlabel("Democratic seats"); ax.set_ylabel("% of simulations")
    kc = row["kalshi_p_control"]
    ax.set_title(f"P(D >= {CONTROL_SEATS}): Model {row['p_d_218']:.1%}" + (f" | Kalshi {kc:.1%}" if kc is not None else ""), loc="left", fontweight="bold")
    ax.legend(frameon=False); save(fig, "seat_distribution")

    w = waffle_frame(res)
    fig, ax = plt.subplots(figsize=(11, 4.2))
    for call in CALL_ORDER:
        g = w[w["call"] == call]
        ax.scatter(g["col"], -g["row"], marker="s", s=48, color=CALLS[call], label=f"{call} ({len(g)})")
    t = w.iloc[CONTROL_SEATS - 1]
    ax.scatter([t["col"]], [-t["row"]], marker="s", s=150, facecolors="none", edgecolors=INK, linewidths=2)
    ax.set_aspect("equal"); ax.axis("off")
    ax.legend(loc="lower center", ncol=7, frameon=False, bbox_to_anchor=(0.5, -0.18), fontsize=8)
    ax.set_title(f"All 435 seats, safest D to safest R (outlined = seat {CONTROL_SEATS}: {t['district']})", loc="left", fontweight="bold")
    save(fig, "seat_chart")

    m = state_frame(res)
    fig, ax = plt.subplots(figsize=(10, 6.2))
    for ab, (cx, cy) in TILES.items():
        if ab not in m.index:
            continue
        col, txt = share_color(m.loc[ab, "share_d"], mpl=True)
        ax.add_patch(matplotlib.patches.FancyBboxPatch((cx + 0.05, -cy + 0.05), 0.9, 0.9, boxstyle="round,pad=0,rounding_size=0.08",
                                                       facecolor=col, edgecolor="white", lw=1.5))
        ax.text(cx + 0.5, -cy + 0.62, ab, ha="center", va="center", fontsize=10, fontweight="bold", color=txt)
        ax.text(cx + 0.5, -cy + 0.3, f"{m.loc[ab, 'exp_d']:.1f}/{int(m.loc[ab, 'seats'])}", ha="center", va="center", fontsize=7.5, color=txt)
    ax.set_xlim(-0.2, 12.2); ax.set_ylim(-7.4, 1.3); ax.set_aspect("equal"); ax.axis("off")
    ax.set_title("Expected Democratic seats by state (expected D seats / seats; colour = D share)", loc="left", fontweight="bold", fontsize=10)
    save(fig, "state_map")

    c = competitive(races).sort_values("p_dem")
    fig, ax = plt.subplots(figsize=(8, 0.2 * len(c) + 1.2))
    y = np.arange(len(c))
    ax.hlines(y, c["kalshi_p"], c["p_dem"], color=GRID, lw=3)
    ax.scatter(c["kalshi_p"], y, marker="D", color=K_GRAY, s=20, label="Kalshi", zorder=3)
    ax.scatter(c["p_dem"], y, color=D_BLUE, s=24, label=MODEL_NAME, zorder=4)
    ax.axvline(0.5, color=INK, lw=0.8, ls=":")
    ax.set_yticks(y, c["district"], fontsize=7); ax.set_xlim(-0.02, 1.02)
    ax.xaxis.set_major_formatter(matplotlib.ticker.PercentFormatter(1.0))
    ax.set_title("P(Democrat wins): competitive or Kalshi-listed districts", loc="left", fontweight="bold")
    ax.legend(frameon=False, loc="lower right"); save(fig, "races_vs_kalshi")

    k = races[races["kalshi_p"].notna() & races["race_type"].isin(["DR", "IND"])]
    fig, ax = plt.subplots(figsize=(6.5, 6.5))
    ax.plot([0, 1], [0, 1], color=GRID, lw=2)
    ax.scatter(k["kalshi_p"], k["p_dem"], c=[CALLS[c] for c in k["call"]], s=36, edgecolors="white", zorder=3)
    for _, x in k[(k["p_dem"] - k["kalshi_p"]).abs() >= 0.10].iterrows():
        ax.annotate(x["district"], (x["kalshi_p"], x["p_dem"]), xytext=(4, 3), textcoords="offset points", fontsize=7)
    ax.set_xlim(-0.03, 1.03); ax.set_ylim(-0.03, 1.03)
    ax.xaxis.set_major_formatter(matplotlib.ticker.PercentFormatter(1.0)); ax.yaxis.set_major_formatter(matplotlib.ticker.PercentFormatter(1.0))
    ax.set_xlabel("Kalshi P(D)"); ax.set_ylabel("Model P(D)")
    ax.set_title(f"Model vs Kalshi ({len(k)} districts)", loc="left", fontweight="bold"); save(fig, "model_vs_kalshi")

    if not {"pres24_margin", "share_prior"} <= set(races.columns):
        return paths
    c2 = races[races["race_type"].isin(["DR", "IND"]) & races["pres24_margin"].between(-40, 40)]
    fig, ax = plt.subplots(figsize=(8, 6))
    ax.plot([-40, 40], [-40, 40], color=GRID, lw=2); ax.axhline(0, color=INK, lw=0.8, ls=":")
    for call in CALL_ORDER:
        g = c2[c2["call"] == call]
        ax.scatter(g["pres24_margin"], g["margin"], s=16, color=CALLS[call], label=call)
    ax.set_xlabel("2024 presidential margin (D - R)"); ax.set_ylabel("projected 2026 House margin")
    ax.legend(frameon=False, fontsize=8, ncol=4)
    ax.set_title("Projected margin vs 2024 presidential margin (grey = no change)", loc="left", fontweight="bold"); save(fig, "swing")

    tp = races[races["deciding_share"] > 0].sort_values("deciding_share").tail(15)
    fig, ax = plt.subplots(figsize=(8, 5))
    ax.barh(tp["district"], 100 * tp["deciding_share"], color=[CALLS[c] for c in tp["call"]])
    ax.set_xlabel("% of simulations")
    ax.set_title(f"Tipping-point districts (deliver seat {CONTROL_SEATS})", loc="left", fontweight="bold"); save(fig, "tipping_point")

    sm = competitive(races).dropna(subset=["share_prior"]).copy()
    sm = sm.reindex((sm["p_dem"] - 0.5).abs().sort_values().index).head(40).iloc[::-1]
    fig, ax = plt.subplots(figsize=(8, 0.2 * len(sm) + 1.4))
    left = np.zeros(len(sm))
    for col, name, colr in (("share_prior", "Fundamentals", "#B9B9B9"), ("share_polls", "Polls", D_BLUE), ("share_kalshi", "Kalshi", "#E8A33D")):
        v = 100 * sm[col].to_numpy(float)
        ax.barh(sm["district"], v, left=left, color=colr, label=name); left += v
    ax.set_xlim(0, 100); ax.tick_params(axis="y", labelsize=7); ax.set_xlabel("% of the projected margin")
    ax.legend(frameon=False, ncol=3, loc="lower right", fontsize=8)
    ax.set_title("What each forecast rests on (closest districts)", loc="left", fontweight="bold"); save(fig, "source_mix")
    return paths


# ------------------------------------------------------------------ dashboard
CSS = """
:root{--ink:#2B2B2B;--muted:#6B6B6B;--line:#E6E6E6;--blue:#1A6FB0;--red:#C8312B;--bg:#FFFFFF;--card:#F7F8FA}
*{box-sizing:border-box} body{margin:0;background:var(--bg);color:var(--ink);font-family:Inter,'Segoe UI',Arial,sans-serif}
main{max-width:1150px;margin:0 auto;padding:24px 16px 60px} h1{font-size:22px;margin:0 0 4px} h2{font-size:16px;margin:34px 0 10px}
.sub{color:var(--muted);font-size:13px} .tiles{display:grid;grid-template-columns:repeat(auto-fit,minmax(200px,1fr));gap:12px;margin-top:18px}
.tile{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:14px 16px} .tile .k{font-size:12px;color:var(--muted);text-transform:uppercase;letter-spacing:.04em}
.tile .v{font-size:30px;font-weight:700;margin:4px 0} .tile .s{font-size:13px;color:var(--muted)} .blue{color:var(--blue)} .red{color:var(--red)}
.badge{display:inline-block;padding:2px 8px;border-radius:999px;font-size:12px;font-weight:600;background:#EAF2FA;color:var(--blue);margin-left:6px}
.badge.final{background:var(--ink);color:#fff} .badge.test{background:#FFF4D6;color:#8A6100}
table{border-collapse:collapse;width:100%;font-size:13px} th,td{padding:6px 8px;border-bottom:1px solid var(--line);text-align:right;white-space:nowrap}
th{cursor:pointer;background:var(--card);position:sticky;top:0} th:first-child,td:first-child{text-align:left} td.l{text-align:left} .wrap{overflow-x:auto}
.eq{border-bottom:1px solid var(--line);padding:10px 0} .eqn{font-size:12px;color:var(--muted);text-transform:uppercase;letter-spacing:.04em}
.eqf{font-family:'Cambria Math',Cambria,Georgia,serif;font-size:16px;margin:4px 0;overflow-x:auto} .eqw{font-size:13px;color:var(--muted)}
.kv td{text-align:left;white-space:normal} .kv td:first-child{width:32%;color:var(--muted)} .notes li{margin:3px 0;font-size:13px}
details summary{cursor:pointer;color:var(--blue);font-size:14px;margin:12px 0}
input.filter{padding:6px 10px;border:1px solid var(--line);border-radius:6px;margin:6px 0;width:260px;background:var(--bg);color:var(--ink)}
@media (prefers-color-scheme: dark){:root{--ink:#E8E8E8;--muted:#A0A0A0;--line:#333;--bg:#141414;--card:#1D1F22}}
@page{size:letter landscape;margin:0.4in}
@media print{
 :root{--ink:#2B2B2B;--muted:#6B6B6B;--line:#E6E6E6;--bg:#FFFFFF;--card:#F7F8FA}
 *{-webkit-print-color-adjust:exact;print-color-adjust:exact}
 main{max-width:none;padding:0} h2{break-before:page;margin-top:0} h2.keep{break-before:auto;margin-top:24px}
 .tile,.eq,tr,.js-plotly-plot,.kv{break-inside:avoid} th{position:static} .wrap,.eqf{overflow:visible}
 .modebar-container{display:none!important} details.all, input.filter{display:none}
}
"""
SORT_JS = """
document.querySelectorAll('table.sortable').forEach(t=>{t.querySelectorAll('th').forEach((th,i)=>{th.addEventListener('click',()=>{
const b=t.tBodies[0],rows=[...b.rows],asc=th.dataset.asc!=='1';th.dataset.asc=asc?'1':'0';
rows.sort((x,y)=>{const a=x.cells[i].dataset.v??x.cells[i].innerText,c=y.cells[i].dataset.v??y.cells[i].innerText;
const na=parseFloat(a),nc=parseFloat(c);return (isNaN(na)||isNaN(nc)?a.localeCompare(c):na-nc)*(asc?1:-1)});rows.forEach(r=>b.appendChild(r))})})});
document.querySelectorAll('input.filter').forEach(inp=>{inp.addEventListener('input',()=>{const q=inp.value.toLowerCase();
document.querySelectorAll(inp.dataset.target+' tbody tr').forEach(r=>{r.style.display=r.innerText.toLowerCase().includes(q)?'':'none'})})});
"""


def pct_cell(p, color=True):
    if p is None or pd.isna(p):
        return "<td data-v='-1'>-</td>"
    style = ""
    if color:
        a = abs(p - 0.5) * 1.6
        rgb = "26,111,176" if p >= 0.5 else "200,49,43"
        style = f" style='background:rgba({rgb},{a:.2f})'"
    return f"<td data-v='{p:.4f}'{style}>{pct_label(p)}</td>"


def equations_html(res):
    c, hd = res.get("cfg", {}), res.get("headline", {})
    if not c:
        return "<p class='sub'>Settings snapshot not found for this run.</p>"
    g = lambda k, d=None: c.get(k, d)

    def n(v, f="g"):
        return "?" if v is None else format(float(v), f)
    pw, pa = g("POPULATION_WEIGHTS", {}), g("PARTISAN_WEIGHTS", {})
    clip, kr = g("ACCURACY_WEIGHT_CLIP", [0.5, 2.0]), g("KALSHI_USE_RANGE", [0.06, 0.94])
    ksd, rv = g("KALSHI_SD"), hd.get("rv_shift")
    gb = float(g("GENERIC_BALLOT_BLEND", 0.75))
    blocks = [
        ("1. Weight of each poll",
         r"w = 0.5^{{\text{{age}}/{hl}}} \times \left(\frac{{\min(n,\,{cap})}}{{{ref}}}\right)^{{{ex}}} \times w_{{\text{{pop}}}} \times w_{{\text{{partisan}}}} "
         r"\times w_{{\text{{generic}}}} \times w_{{\text{{field}}}} \times w_{{\text{{quality}}}} \times w_{{\text{{accuracy}}}} \times \frac{{1}}{{k^{{{fl}}}}} \times \frac{{1}}{{\text{{versions}}}}",
         dict(hl=n(g("RECENCY_HALF_LIFE_DAYS")), cap=n(g("SAMPLE_SIZE_CAP")), ref=n(g("REFERENCE_SAMPLE")), ex=n(g("SAMPLE_SIZE_EXPONENT")), fl=n(g("FLOOD_EXPONENT"))),
         f"Population: LV {n(pw.get('LV'))}, RV {n(pw.get('RV'))}, adults {n(pw.get('A'))}. Partisan sponsor {n(pa.get('Republican'))}. "
         f"Generic-party question {n(g('GENERIC_WEIGHT'))}. Full field {n(g('BIGGER_FIELD_WEIGHT'))}. Quality {n(g('MIN_QUALITY_WEIGHT'))} to 1 by VoteHub grade "
         f"(ungraded firms get a random graded firm's grade in each simulation). Accuracy kept between {n(clip[0])} and {n(clip[1])}. k = the pollster's polls of that district."),
        ("2. Each poll's margin",
         r"m = (D - R)\,\frac{{D + R + U}}{{D + R}} + s_{{RV}} \pm s_{{\text{{partisan}}}} - h, \qquad h = \frac{{\sum \text{{residuals}} + {k} \, h_{{\text{{scorecard}}}}}}{{n_{{\text{{polls}}}} + {k}}}",
         dict(k=n(g("HOUSE_EFFECT_K"))),
         f"U = undecided. RV shift s_RV = {'?' if rv is None else f'{rv:+.2f}'} pts (measured from LV/RV pairs). Partisan shift = "
         f"{n(g('PARTISAN_HOUSE_EFFECTS', {}).get('Republican'))} pts against the sponsor. Residual = poll minus the same district's average of other pollsters."),
        ("3. Polling average",
         r"\bar{{m}} = \frac{{\sum w\,m}}{{\sum w}}, \qquad SD_{{\text{{polls}}}} = \sqrt{{\frac{{SD_{{\text{{poll}}}}^2}}{{n_{{\text{{eff}}}}}} + {fl}^2 + SD_U^2}}",
         dict(fl=n(g("SYSTEMATIC_POLL_ERROR_SD"), ".2f")), "The middle term is the error all polls of a district share (calibrated on House polls 1998-2022)."),
        ("4. National environment",
         r"\text{{env}} = {gb} \times \text{{GB}} + {ap} \times {sl} \times (-\text{{net approval}})",
         dict(gb=n(gb), ap=n(1 - gb), sl=n(g("ENV_SLOPE"))),
         "GB = generic ballot (VoteHub polls blended with Kalshi's average)." + ("" if hd.get("national", {}).get("env") is None
                                                                                   else f" This run: env = D{float(hd['national']['env']):+.1f}.")),
        ("5. Prior (fundamentals)",
         r"\text{{prior}} = {pvi} \times \text{{lean}} + \text{{env}} \pm {inc}\,[\text{{incumbent running}}], \qquad SD_{{\text{{prior}}}} = {psd}",
         dict(pvi=n(g("PVI_TO_MARGIN"), ".2f"), inc=n(g("INCUMBENCY_ADVANTAGE"), ".2f"), psd=n(g("PRIOR_SD"), ".2f")),
         "lean = (district 2024 presidential margin - national margin) / 2, on the 2026 lines. Slope, incumbency and SD measured on the 2018 and 2022 House midterms."),
        ("6. Kalshi",
         r"P' = \text{{logistic}}\left({ls} \cdot \text{{logit}}\,P\right), \qquad \text{{margin}}_K = \Phi^{{-1}}(P') \cdot \max\left({cs},\ SD_{{F+P}}\right), \qquad SD_K = {ksd}",
         dict(ls=n(g("KALSHI_LONGSHOT_SLOPE")), cs=n(g("KALSHI_CONVERT_SD"), ".2f"), ksd=n(ksd) if ksd else r"\infty"),
         f"Used only when {float(kr[0]):.0%} <= P <= {float(kr[1]):.0%}. P = D price / (D price + R price)."),
        ("7. Each district",
         r"\text{{margin}} = \frac{{\pi_F \cdot \text{{prior}} + \pi_P \cdot \bar{{m}} + \pi_K \cdot \text{{margin}}_K}}{{\pi_F + \pi_P + \pi_K}}, \quad \pi = \frac{{1}}{{SD^2}}, \quad "
         r"SD^2 = \frac{{1}}{{\Pi}} + \frac{{2({rho})}}{{\Pi^2}}\left(\sqrt{{\pi_F \pi_P}} + \sqrt{{\pi_F \pi_K}} + \sqrt{{\pi_P \pi_K}}\right) + {dr}^2 \cdot \text{{days left}}",
         dict(rho=n(g("SOURCE_ERROR_CORR")), dr=n(g("DAILY_DRIFT_SD"), ".2f")), "Pi = the sum of the three precisions."),
        ("8. Simulations",
         r"\tilde{{m}}_i = \text{{margin}}_i + N + R_{{g(i)}} + S_{{s(i)}} + L\,f_i + e_i, \qquad \text{{D seats}} = \text{{certain D seats}} + \sum_i \mathbf{{1}}[\tilde{{m}}_i > 0], \qquad P(D \geq {ctl})",
         dict(ctl=CONTROL_SEATS),
         f"N = national miss (SD {n(g('NATIONAL_ERROR_SD'), '.2f')}, t df {n(g('NATIONAL_T_DF'))}). R = Census-region miss (SD {n(g('REGIONAL_ERROR_SD'), '.2f')}). "
         f"S = state miss (SD {n(g('STATE_ERROR_SD'), '.2f')}). L = lean factor (SD {n(g('LEAN_FACTOR_ERROR_SD'))}). e = the rest of the district's SD (t df {n(g('STATE_T_DF'), '.1f')}). "
         "Uncontested and same-party races are certain seats."),
    ]
    out = []
    for title, tex, vals, where in blocks:
        out.append(f"<div class='eq'><div class='eqn'>{title}</div><div class='eqf'>\\[{tex.format(**vals)}\\]</div><div class='eqw'>{ascii_text(where)}</div></div>")
    return "".join(out)


def race_rows(races, base_races):
    rows = []
    for _, x in races.iterrows():
        d = x["p_dem"] - x["kalshi_p"] if pd.notna(x["kalshi_p"]) else np.nan
        chg = x["p_dem"] - base_races.loc[x["district"], "p_dem"] if base_races is not None and x["district"] in base_races.index else np.nan
        f = lambda v: "<td data-v='0'>-</td>" if pd.isna(v) else f"<td data-v='{v:.4f}'>{v * 100:+.0f}</td>"
        inc = x["incumbent"] if isinstance(x["incumbent"], str) and x["incumbent"] else "open"
        sd = "-" if pd.isna(x["sd"]) else f"+/-{x['sd']:.1f}"
        mv = 0 if pd.isna(x["margin"]) else x["margin"]
        rows.append(f"<tr><td>{x['district']}</td><td class='l'>{matchup(x)}</td><td class='l'>{inc}</td><td class='l'>{x['call']}</td>"
                    f"{pct_cell(x['p_dem'])}{pct_cell(x['kalshi_p'])}{f(d)}<td data-v='{mv:.2f}'>{margin_label(x['margin'], x['race_type'])}</td>"
                    f"<td>{sd}</td><td data-v='{x['partisan_lean']:.2f}'>{'D' if x['partisan_lean'] >= 0 else 'R'}+{abs(x['partisan_lean']):.1f}</td>"
                    f"<td data-v='{x['n_polls']}'>{int(x['n_polls'])}</td>{f(chg)}</tr>")
    head = ("<thead><tr><th>District</th><th>Match-up</th><th>Incumbent</th><th>Call</th><th>Model P(D)</th><th>Kalshi P(D)</th>"
            "<th>Model - Kalshi (pts)</th><th>Projected margin</th><th>+/- (1 SD)</th><th>Lean</th><th>Polls</th>"
            "<th>Model change since first run (pts)</th></tr></thead>")
    return head, "".join(rows)


def runs_table(hist):
    """Every run so far, newest first (replaces the line charts: a few points over 18 hours read better as a table)."""
    h = hist.iloc[::-1]
    rows = "".join(
        f"<tr><td>{x['run_at']}</td><td class='l'>{x['kind']}</td><td>{x['p_d_218']:.1%}</td><td>{x['mean_seats']:.1f}</td>"
        f"<td>{x[f's{SEAT_INTERVALS[0]}_lo']:.0f}-{x[f's{SEAT_INTERVALS[0]}_hi']:.0f}</td>"
        f"<td>{'-' if pd.isna(x['kalshi_p_control']) else format(float(x['kalshi_p_control']), '.1%')}</td>"
        f"<td>{'-' if pd.isna(x['kalshi_seats']) else format(float(x['kalshi_seats']), '.1f')}</td></tr>" for _, x in h.iterrows())
    return ("<div class='wrap'><table><thead><tr><th>Run</th><th>Kind</th><th>P(D >= 218)</th><th>Mean D seats</th>"
            f"<th>{SEAT_INTERVALS[0]}% range</th><th>Kalshi control</th><th>Kalshi seats</th></tr></thead><tbody>{rows}</tbody></table></div>")


def build_dashboard(res, hist, figs, title_tag, path):
    import plotly
    row, summ, races = res["row"], res["summary"], res["races"].copy()
    badge = {"final": "<span class='badge final'>FINAL</span>", "test": "<span class='badge test'>TEST</span>"}.get(row["kind"], "<span class='badge'>scheduled</span>")
    kc, ks = row["kalshi_p_control"], row["kalshi_seats"]
    s_iv = " | ".join(f"{l}%: {row[f's{l}_lo']:.0f}-{row[f's{l}_hi']:.0f}" for l in SEAT_INTERVALS)
    calls = races["call"].value_counts()
    tiles = f"""
<div class='tiles'>
 <div class='tile'><div class='k'>P(Democrats >= {CONTROL_SEATS} seats)</div><div class='v blue'>{row['p_d_218']:.1%}</div>
  <div class='s'>simulation precision \\(\\pm{(row['p_hi'] - row['p_lo']) / 2 * 100:.1f}\\) pts</div></div>
 <div class='tile'><div class='k'>Expected Democratic seats</div><div class='v'>{row['mean_seats']:.1f}</div>
  <div class='s'>median {row['median_seats']:.0f} | {s_iv}</div></div>
 <div class='tile'><div class='k'>Kalshi control market</div><div class='v' style='color:#7A7A7A'>{'-' if kc is None else f'{kc:.1%}'}</div>
  <div class='s'>race prices: {'-' if ks is None else f'{ks:.1f} seats'} ({summ.get('kalshi_districts', '?')} districts listed; model elsewhere)</div></div>
 <div class='tile'><div class='k'>Run</div><div class='v' style='font-size:20px'>{row['run_at']}</div>
  <div class='s'>{row['n_sims']:,} simulations | data as of {row['as_of']} | {row['runtime_min']:.0f} min</div></div>
</div>
<div class='sub' style='margin-top:12px'>Ratings: {' | '.join(f"{c} {int(calls.get(c, 0))}" for c in CALL_ORDER)}.
 National environment D{float(summ.get('env', 0)):+.1f}. Median tipping-point margin {float(summ.get('tipping_point_margin', float('nan'))):+.1f}.</div>"""
    first = hist[hist["kind"] != "test"].head(1)
    base_races = None
    if len(first) and RACE_HISTORY.exists():
        rh = pd.read_csv(RACE_HISTORY)
        base_races = rh[rh["run_at"] == first["run_at"].iloc[0]].set_index("district")
    comp = competitive(races).sort_values("p_dem", ascending=False)
    head, body = race_rows(comp, base_races)
    comp_table = f"<div class='wrap'><table class='sortable' id='comp'>{head}<tbody>{body}</tbody></table></div>"
    head, body = race_rows(races.sort_values("district"), base_races)
    all_table = (f"<details class='all'><summary>All 435 districts</summary><input class='filter' data-target='#all' placeholder='Filter (e.g. TX, Safe R, open)'>"
                 f"<div class='wrap'><table class='sortable' id='all'>{head}<tbody>{body}</tbody></table></div></details>")
    dec = races[races["deciding_share"] > 0].sort_values("deciding_share", ascending=False).head(15)
    dec_rows = "".join(f"<tr><td>{x['district']}</td><td class='l'>{matchup(x)}</td><td>{x['deciding_share']:.1%}</td>{pct_cell(x['p_dem'])}"
                       f"<td>{margin_label(x['margin'])}</td></tr>" for _, x in dec.iterrows())
    dec_table = ("<p class='sub'>In each simulation the districts are ranked from best to worst for Democrats; the one that delivers seat 218 "
                 "is that simulation's tipping point.</p><div class='wrap'><table><thead><tr><th>District</th><th>Match-up</th>"
                 f"<th>Share of simulations</th><th>Model P(D)</th><th>Projected margin</th></tr></thead><tbody>{dec_rows}</tbody></table></div>")
    ks_rows = "".join(f"<tr><td>{k}</td><td>{v}</td></tr>" for k, v in summ.get("key_settings", {}).items())
    ks_rows += f"<tr><td>Simulations</td><td>{row['n_sims']:,}</td></tr>"
    notes = []
    stt = res["status"]
    if not stt["ok"]:
        notes.append(f"Model run FAILED: {stt['error']}")
    if res["checks"] is not None:
        c = res["checks"]
        notes.append(f"Checks: {row['testing_pass']} PASS | {row['testing_warn']} WARN | {row['testing_fail']} FAIL"
                     + (f" (details in {WARNINGS_XLSX.name})." if row["testing_warn"] or row["testing_fail"] else "."))
        for _, x in c[c["status"] == "FAIL"].iterrows():
            notes.append(f"FAIL - {x['check']}: {x['detail']}")
    src = summ.get("sources", {})
    notes.append("Data: " + ", ".join(f"{k.replace('_cache.csv', '')} {v}" for k, v in src.items()) + ".")
    notes.append("Districts: 2024 presidential results on the 2026 lines (The Downballot); incumbents, open seats and nominees as of Nov 2, "
                 "2026 (Wikipedia, Ballotpedia, 270toWin); see House Forecast/Data/build_house_districts.py.")
    notes.append("Louisiana holds an all-party primary on Nov 3 (runoff Dec 12); its seats are forecast by party. AK-AL is Bill Hill "
                 "(independent) vs Nick Begich (R): Hill is read from the polls and from 1 - Kalshi's Begich price, and a Hill win counts "
                 "for Democrats in 80% of simulations. CA-06 is Richard Pan (D) vs Kevin Kiley (independent); a Kiley win is not a "
                 "Democratic seat. Missouri uses its 2022 map.")
    notes_html = "<ul class='notes'>" + "".join(f"<li>{n}</li>" for n in notes) + "</ul>"
    fig_html = {k: f.to_html(full_html=False, include_plotlyjs=False, config={"displaylogo": False, "responsive": True}) for k, f in figs.items()}
    body = f"""<h1>2026 House forecast - {MODEL_NAME} {badge}</h1><div class='sub'>Team 5: {', '.join(TEAM)}</div><div class='sub'>{title_tag}</div>
{tiles}
<h2 class='keep'>Seat distribution</h2>{fig_html['seat_distribution']}
<h2>All 435 seats</h2>{fig_html['seat_chart']}
<h2>Map</h2>{fig_html['state_map']}
<h2>Competitive districts</h2>{fig_html['races_vs_kalshi']}{comp_table}{all_table}
<h2>Model vs Kalshi</h2>{fig_html.get('model_vs_kalshi', '')}
<h2>Swing from 2024</h2>{fig_html.get('swing', '')}
<h2>Tipping-point districts</h2>{fig_html['tipping_point']}{dec_table}
<h2>What each forecast rests on</h2>{fig_html.get('source_mix', '')}
<h2>Run history</h2>{runs_table(hist)}
<h2>Notes</h2>{notes_html}
<h2 class='keep'>Key settings</h2><table class='kv'><tbody>{ks_rows}</tbody></table>
<h2>Equations and weights</h2>{equations_html(res)}"""
    html = (f"<!doctype html><html lang='en'><head><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'>"
            f"<title>House Forecast</title><style>{CSS}</style><script>{plotly.offline.get_plotlyjs()}</script>"
            f"{mathjax_script()}</head><body><main>\n{ascii_text(body)}\n</main><script>{SORT_JS}</script></body></html>")
    path.write_text(html, encoding="utf-8")


def log_warnings(checks, run_at, kind):
    new = checks[checks["status"] != "PASS"].assign(run_at=run_at, kind=kind)[["run_at", "kind", "status", "section", "check", "detail"]]
    if new.empty:
        new = pd.DataFrame([{"run_at": run_at, "kind": kind, "status": "PASS", "section": "", "check": "all checks passed", "detail": ""}])
    try:
        old = pd.read_excel(WARNINGS_XLSX) if WARNINGS_XLSX.exists() else pd.DataFrame()
        allw = pd.concat([old, new], ignore_index=True)
        with pd.ExcelWriter(WARNINGS_XLSX, engine="openpyxl") as xw:
            allw.to_excel(xw, sheet_name="warnings", index=False)
            ws = xw.sheets["warnings"]
            for col, width in zip("ABCDEF", (17, 10, 8, 10, 50, 90)):
                ws.column_dimensions[col].width = width
            ws.freeze_panes = "A2"
            ws.auto_filter.ref = ws.dimensions
        say(f"Logged {len(new)} warning row(s) to {WARNINGS_XLSX.name}")
    except PermissionError:
        alt = OUT / f"model_warnings_{run_at.replace(':', '').replace(' ', '_')}.xlsx"
        new.to_excel(alt, index=False)
        say(f"{WARNINGS_XLSX.name} is open in Excel, so this run's warnings went to {alt.name}")
    except Exception as e:
        say(f"Couldn't update {WARNINGS_XLSX.name} ({type(e).__name__}: {e}); the checks are still in the run's data/checks.csv")


def save_figures(figs, res, hist, folder):
    folder.mkdir(parents=True, exist_ok=True)
    for k, f in figs.items():
        f.write_html(folder / f"{k}.html", include_plotlyjs="cdn", full_html=True)
    try:
        png_figs(res, hist, folder)
    except Exception as e:
        say(f"PNG export failed ({type(e).__name__}: {e}); HTML figures were saved")


# ------------------------------------------------------------------ PDF (same approach as final_forecast.py)
PDF_BROWSERS = [r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe", r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
                r"C:\Program Files\Google\Chrome\Application\chrome.exe", r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
                "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge", "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"]
PDF_WIDTH_PX, PDF_MAX_CHART_PX = 980, 640


def find_pdf_browser():
    cands = [os.environ.get("FORECAST_PDF_BROWSER")] + PDF_BROWSERS
    cands += [shutil.which(n) for n in ("msedge", "microsoft-edge", "google-chrome", "chrome", "chromium", "chromium-browser")]
    return next((c for c in cands if c and Path(c).exists()), None)


def _pdf_playwright(html_path, out):
    from playwright.sync_api import sync_playwright
    with sync_playwright() as pw:
        browser, err = None, None
        for opts in ({"channel": "msedge"}, {"channel": "chrome"}, {}):
            try:
                browser = pw.chromium.launch(**opts)
                break
            except Exception as e:
                err = e
        if browser is None:
            raise err
        try:
            page = browser.new_page(viewport={"width": PDF_WIDTH_PX, "height": 1400})
            page.goto(Path(html_path).resolve().as_uri(), wait_until="load", timeout=120_000)
            page.evaluate("() => (window.MathJax && MathJax.startup && MathJax.startup.promise) ? MathJax.startup.promise.then(() => true) : true")
            page.wait_for_function("() => [...document.querySelectorAll('.js-plotly-plot')].every(d => d.querySelector('.main-svg'))", timeout=60_000)
            page.evaluate(f"() => document.querySelectorAll('.js-plotly-plot').forEach(d => {{"
                          f" if (d.offsetHeight > {PDF_MAX_CHART_PX}) d.parentElement.style.zoom = {PDF_MAX_CHART_PX} / d.offsetHeight; }})")
            page.wait_for_timeout(500)
            page.pdf(path=str(out), prefer_css_page_size=True, print_background=True)
        finally:
            browser.close()


def _pdf_cli(html_path, out):
    import tempfile
    browser = find_pdf_browser()
    if browser is None:
        raise RuntimeError("no Edge/Chrome found (set FORECAST_PDF_BROWSER to the browser's .exe)")
    with tempfile.TemporaryDirectory() as profile:
        cmd = [browser, "--headless=new", "--disable-gpu", "--no-first-run", "--no-default-browser-check", f"--user-data-dir={profile}",
               f"--window-size={PDF_WIDTH_PX},1400", "--hide-scrollbars", "--run-all-compositor-stages-before-draw",
               "--virtual-time-budget=30000", "--no-pdf-header-footer", "--print-to-pdf-no-header", f"--print-to-pdf={out}",
               Path(html_path).resolve().as_uri()]
        subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=180)


def write_pdf(html_path, pdf_path):
    pdf_path = Path(pdf_path)
    tmp = pdf_path.with_name(pdf_path.stem + ".tmp.pdf")
    errors = []
    for name, fn in (("playwright", _pdf_playwright), ("browser command line", _pdf_cli)):
        tmp.unlink(missing_ok=True)
        try:
            fn(html_path, tmp)
        except Exception as e:
            errors.append(f"{name}: {type(e).__name__}: {str(e).splitlines()[0][:150] if str(e) else ''}")
            continue
        if tmp.exists() and tmp.stat().st_size > 10_000:
            break
        errors.append(f"{name}: no PDF produced")
    else:
        tmp.unlink(missing_ok=True)
        say(f"PDF skipped for {Path(html_path).name} ({'; '.join(errors)})")
        return False
    try:
        os.replace(tmp, pdf_path)
    except PermissionError:
        alt = pdf_path.with_name(pdf_path.stem + f"_{now().strftime('%H%M%S')}.pdf")
        os.replace(tmp, alt)
        return alt
    return pdf_path


def copy_latest(src, name):
    try:
        shutil.copy2(src, OUT / name)
    except PermissionError:
        say(f"{name} is open in another program and wasn't updated")


INPUT_FILES = [
    *[(f, f"Data_Cache/{f.name}") for f in sorted((HERE / "Data_Cache").glob("*.csv"))],
    (HERE / "house_calibration.json", "house_calibration.json"),
    (HERE / "house_model.py", "house_model.py"),
    (HERE / "Data" / "house_districts_2026.csv", "Data/house_districts_2026.csv"),
    (SENATE / "Data" / "votehub_pollster_scorecards.csv", "Data/votehub_pollster_scorecards.csv"),
    (SENATE / "Data" / "leans_and_regions.csv", "Data/leans_and_regions.csv"),
]


def save_inputs(dest):
    try:
        files = [(Path(src), name) for src, name in INPUT_FILES if Path(src).exists()]
        files += [(f, f"Data_Cache/{f.name}") for f in sorted((HERE / "Data_Cache").glob("*.csv")) if (f, f"Data_Cache/{f.name}") not in files]
        for src, name in files:
            (dest / name).parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dest / name)
        (dest / "manifest.json").write_text(json.dumps({"saved_at": now().isoformat(timespec="seconds"),
                                                        "files": sorted({name for _, name in files})}, indent=2))
    except Exception as e:
        say(f"Input snapshot failed ({type(e).__name__}: {e}); the run itself is fine")


# ------------------------------------------------------------------ one run
def do_run(kind, slot, n_sims, test=False):
    stamp = now().strftime("%Y-%m-%d_%H%M")
    folder = OUT / (f"test_{stamp}" if test else stamp)
    folder.mkdir(parents=True, exist_ok=True)
    model_out = folder / "model_output" if test else MODEL_OUT
    os.environ["FORECAST_N_SIMS"] = str(n_sims)
    os.environ["FORECAST_OUT_DIR"] = str(model_out)
    say(f"=== {'TEST RUN' if test else ('FINAL RUN' if kind == 'final' else 'RUN')} started ({n_sims:,} simulations) -> {folder.relative_to(HERE)}")
    t0 = time.time()
    status = {"ok": True, "error": None}
    try:
        house_model.run(n_sims=n_sims)
    except Exception as e:
        status = {"ok": False, "error": f"{type(e).__name__}: {e}"[:500]}
        say(f"MODEL FAILED: {status['error']}")
        traceback.print_exc()
    finally:
        os.environ.pop("FORECAST_OUT_DIR", None)
        os.environ.pop("FORECAST_N_SIMS", None)
    if not (model_out / "standard" / "summary.json").exists() or not status["ok"]:
        say("No forecast output was produced; nothing to report for this run.")
        return None
    runtime = time.time() - t0
    res = collect(model_out, n_sims, kind, slot, runtime, status)
    res["row"]["folder"] = folder.name
    data = folder / "data"; data.mkdir(exist_ok=True)
    for f in (model_out / "standard").glob("*"):
        shutil.copy2(f, data / f.name)
    for name in ("checks.csv", "headline.json", "config_snapshot.json", "race_probabilities.csv", "polls_used.csv", "national_signals.csv"):
        if (model_out / name).exists():
            shutil.copy2(model_out / name, data / name)
    if not test:
        save_inputs(folder / "inputs")
    hist = pd.read_csv(HISTORY) if HISTORY.exists() else pd.DataFrame()
    races = res["races"].assign(run_at=res["row"]["run_at"], kind=kind)[["run_at", "kind", "district", "call", "p_dem", "kalshi_p", "margin", "sd", "n_polls"]]
    hist_show = pd.concat([hist, pd.DataFrame([res["row"]])], ignore_index=True)
    if not test:
        hist_show.to_csv(HISTORY, index=False)
        rh = pd.read_csv(RACE_HISTORY) if RACE_HISTORY.exists() else pd.DataFrame()
        pd.concat([rh, races], ignore_index=True).to_csv(RACE_HISTORY, index=False)
        if res["checks"] is not None:
            log_warnings(res["checks"], res["row"]["run_at"], kind)
    races.to_csv(data / "races_this_run.csv", index=False)
    figs = plotly_figs(res, hist_show)
    save_figures(figs, res, hist_show, folder / "figures")
    tag = (f"test run {res['row']['run_at']} ({n_sims:,} simulations; not saved to history)" if test else
           ("final forecast, " if kind == "final" else "scheduled run, " if kind == "scheduled" else "one-off run, ") + res["row"]["run_at"])
    if test:
        dash = OUT / f"test_{stamp}.html"
        build_dashboard(res, hist_show, figs, tag, dash)
        write_pdf(dash, dash.with_suffix(".pdf"))
    else:
        dash = folder / "dashboard.html"
        build_dashboard(res, hist_show, figs, tag, dash)
        copy_latest(dash, "latest.html")
        pdf = write_pdf(dash, folder / "dashboard.pdf")
        if pdf:
            copy_latest(pdf, "latest.pdf")
    say(f"=== Run finished in {fmt_td(runtime)}: P(D >= {CONTROL_SEATS}) {res['row']['p_d_218']:.1%}, mean seats "
        f"{res['row']['mean_seats']:.1f} | dashboard: {dash.relative_to(HERE)}")
    return res


# ------------------------------------------------------------------ rebuild dashboards from saved runs
def load_saved_run(folder, row):
    d = folder / "data"
    load = lambda p: json.loads(p.read_text()) if p.exists() else {}
    cfg = load(d / "config_snapshot.json")
    races = pd.read_csv(d / "races.csv", keep_default_na=False, na_values=[""])
    cuts = rating_cuts(cfg)
    races["call"] = [race_call(p, cuts) for p in races["p_dem"]]
    row = {k: (None if isinstance(v, float) and np.isnan(v) else v) for k, v in row.items()}
    for k in ("testing_pass", "testing_warn", "testing_fail", "n_sims", "sources_live", "sources_total"):
        if row.get(k) is not None:
            row[k] = int(row[k])
    checks = pd.read_csv(d / "checks.csv") if (d / "checks.csv").exists() else None
    return {"summary": load(d / "summary.json"), "races": races, "seats": pd.read_csv(d / "seats.csv"), "row": row, "checks": checks,
            "status": {"ok": True, "error": None}, "cuts": cuts, "cfg": cfg, "headline": load(d / "headline.json")}


def rebuild_reports():
    if not HISTORY.exists():
        say("No history yet; nothing to rebuild.")
        return
    hist = pd.read_csv(HISTORY)
    last = None
    for i, r in hist.reset_index(drop=True).iterrows():
        folder = OUT / str(r["folder"])
        if not (folder / "data" / "summary.json").exists():
            continue
        hist_upto = hist.iloc[: i + 1].drop(columns="folder")
        res = load_saved_run(folder, r.drop(labels="folder").to_dict())
        figs = plotly_figs(res, hist_upto)
        save_figures(figs, res, hist_upto, folder / "figures")
        tag = ("final forecast, " if r["kind"] == "final" else "scheduled run, ") + str(r["run_at"])
        build_dashboard(res, hist_upto, figs, tag, folder / "dashboard.html")
        last = folder / "dashboard.html"
        pdf = write_pdf(last, folder / "dashboard.pdf")
        say(f"Rebuilt {folder.name}" + (" (HTML + PDF)" if pdf else " (HTML only)"))
    if last is not None:
        copy_latest(last, "latest.html")
        if (last.parent / "dashboard.pdf").exists():
            copy_latest(last.parent / "dashboard.pdf", "latest.pdf")


# ------------------------------------------------------------------ main loop
def main():
    ap = argparse.ArgumentParser(description="Scheduled House_Model forecasts + dashboard.")
    ap.add_argument("--once", action="store_true", help=f"one full run now ({N_SIMS:,} simulations), saved to the history")
    ap.add_argument("--test", action="store_true", help=f"one quick run ({TEST_N_SIMS:,} simulations) -> Forecasts/test_<datetime>.html")
    ap.add_argument("--status", action="store_true", help="show the schedule and exit")
    ap.add_argument("--report", action="store_true", help="rebuild every saved run's dashboard and latest.html with the current code")
    ap.add_argument("--reset", action="store_true", help="DELETE the schedule, history, warnings workbook, latest.* and run folders, then start fresh")
    a = ap.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    if a.test:
        do_run("test", None, TEST_N_SIMS, test=True)
        return
    if a.once:
        do_run("final" if now() >= FINAL_RUN else "once", None, N_SIMS)
        return
    if a.reset:
        gone = [p for p in OUT.iterdir() if re.fullmatch(r"\d{4}-\d{2}-\d{2}_\d{4}", p.name) and p.is_dir()]
        for p in gone:
            shutil.rmtree(p)
        for p in (STATE, HISTORY, RACE_HISTORY, WARNINGS_XLSX, OUT / "latest.html", OUT / "latest.pdf"):
            p.unlink(missing_ok=True)
        say(f"RESET: deleted the schedule, history and {len(gone)} run folder(s).")
    st = load_state()
    if a.status:
        if st is None:
            print("No schedule yet: run `python house_forecasts.py` to start it.")
        else:
            print_schedule(st)
            print("FINISHED." if st.get("finished") else (f"Next run: {fmt_t(pending(st)[0])}" if pending(st) else ""))
        return
    if a.report:
        rebuild_reports()
        return
    if st and st.get("finished"):
        say(f"The schedule finished with the final run ({fmt_t(FINAL_RUN)}). Use --once for another run.")
        return
    if st is None:
        if now() > FINAL_RUN + dt.timedelta(hours=1):
            say("It's past the final run time; nothing to schedule. Use --once for a single run.")
            return
        st = {"anchor": now().isoformat(), "done_slots": [], "created": now().isoformat()}
        save_state(st)
        say(f"New schedule: a run now, then every {INTERVAL_HOURS} hours, then a final run at {fmt_t(FINAL_RUN)}.")
    else:
        say("Resuming the existing schedule (history kept).")
    print_schedule(st)
    while True:
        st = load_state()
        todo = pending(st)
        if not todo:
            st["finished"] = True
            save_state(st)
            say(f"FINISHED: the final run ({fmt_t(FINAL_RUN)}) is done.")
            return
        due = [t for t in todo if t <= now()]
        if due:
            kind = "final" if FINAL_RUN in due else "scheduled"
            slot = due[-1].isoformat()
            try:
                do_run(kind, slot, N_SIMS)
            except Exception as e:
                say(f"RUN ERROR ({type(e).__name__}: {e}); the schedule continues.")
                traceback.print_exc()
            st = load_state()
            st["done_slots"] = sorted(set(st["done_slots"]) | {t.isoformat() for t in due})
            st.setdefault("runs", []).append({"slot": slot, "finished": now().isoformat(), "kind": kind})
            save_state(st)
            continue
        nxt = todo[0]
        label = "FINAL run" if nxt == FINAL_RUN else "next run"
        say(f"RESTING. {label.capitalize()} at {fmt_t(nxt)} (in {fmt_td((nxt - now()).total_seconds())}). Leave this window open.")
        while now() < nxt:
            time.sleep(min(STATUS_EVERY_S * 5, max((nxt - now()).total_seconds(), 1)))
            if now() < nxt:
                say(f"RESTING. {label.capitalize()} in {fmt_td((nxt - now()).total_seconds())} (at {fmt_t(nxt)}).")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        say("Stopped by you (Ctrl+C). Run `python house_forecasts.py` again to resume the schedule; history is kept.")
