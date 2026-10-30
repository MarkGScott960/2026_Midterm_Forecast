"""
final_forecast.py - scheduled Most_Magnificent_Model forecasts + dashboard (Team 5, 2026 Senate)

    python final_forecast.py            start (or resume) the schedule: a run now, then every 6 hours, then one final
                                        run at 9:00 AM on Nov 3, then stop for good
    python final_forecast.py --test     one quick run (1,000 simulations) -> Forecasts/test_<datetime>.html, to tune the
                                        dashboard's look. Doesn't touch the schedule, the history or Most_Magnificent_Model/Output
    python final_forecast.py --status   show the schedule and what has run, then exit
    python final_forecast.py --report   rebuild every saved run's dashboard + figures and latest.html with the current code
                                        (no model run; use after editing the dashboard code, with the schedule stopped)
    python final_forecast.py --reset    DELETE the schedule + history + run folders (tests kept) and start fresh; stop the
                                        running script first (Ctrl+C)

Every scheduled run executes Model Testing.ipynb and then Most_Magnificent_Model.ipynb (both at N_SIMS), saves everything in
Forecasts/<YYYY-MM-DD_HHMM>/ (dashboard.html, figures/*.html + *.png, data), appends to Forecasts/history.csv and
race_history.csv, and copies the dashboard to Forecasts/latest.html.

Schedule rules
- Run times are fixed when the schedule starts (start, +6 h, +12 h, ...), up to the last one at least
  FINAL_BUFFER_HOURS before the final run, plus FINAL_RUN (9:00 AM Nov 3). A long run never shifts later run times.
- Runs never overlap. If a run is still going when the next one is due, that run finishes and saves; the next starts
  right after. Several missed run times (e.g. the script was closed) are made up with ONE run, immediately.
- The schedule and history live in Forecasts/schedule.json and history.csv, so restarting the script resumes it.
- After the final run the schedule is marked finished; restarting the script only prints that.
"""
import argparse
import datetime as dt
import json
import os
import shutil
import subprocess
import sys
import threading
import time
import warnings
from pathlib import Path

# ============================== SETTINGS ==============================
N_SIMS = 100_000              # simulations per scheduled run (forecast AND Model Testing)
TEST_N_SIMS = 1_000           # simulations for --test
INTERVAL_HOURS = 3            # time between scheduled runs
FINAL_RUN = dt.datetime(2026, 11, 3, 9, 0)   # last run, local time; nothing runs after it
FINAL_BUFFER_HOURS = 1        # no regular run starts in the 1 h before FINAL_RUN, so the final run isn't delayed by one
PLANNED_MINUTES = (120, 240)  # expected length of one full run, shown until a real run has been timed
SEAT_INTERVALS = (80, 95)     # seat ranges shown on the dashboard (%)
P_INTERVAL = 95               # simulation-precision interval on P(D >= 51) (%)
CONTROL_SEATS = 51            # Democrats need 51 (Republican VP)
CELL_TIMEOUT = 4 * 3600       # max seconds for one notebook cell
STATUS_EVERY_S = 60           # how often the console status line updates
# =======================================================================

HERE = Path(__file__).resolve().parent
REPO = HERE.parent
TEAM = ["Elizabeth Miller", "Mark Scott", "Ethan Verrone", "Boaz Alkalay", "Leo Westebbe"]  # shown on every dashboard
MODEL_NAME = "Most_Magnificent_Model"   # Team 5's final model (folder, notebook and display name)
MODEL_DIR = REPO / "Models" / MODEL_NAME
MODEL_NB = MODEL_DIR / f"{MODEL_NAME}.ipynb"
TEST_NB = MODEL_DIR / "Model Testing.ipynb"
OUT = HERE / "Forecasts"
STATE = OUT / "schedule.json"
HISTORY = OUT / "history.csv"
RACE_HISTORY = OUT / "race_history.csv"
WARNINGS_XLSX = OUT / "model_warnings.xlsx"  # every WARN / FAIL from Model Testing, one row per check per run (appended)

D_BLUE, R_RED, K_GRAY, INK, GRID = "#1A6FB0", "#C8312B", "#7A7A7A", "#2B2B2B", "#E6E6E6"
TOSS_PURPLE, NONE_GRAY = "#8E6BBF", "#E9E9E9"
CALLS = {"Democrat / Independent": D_BLUE, "Republican": R_RED, "Too close to call": TOSS_PURPLE, "No election": NONE_GRAY}
ABBR = {"Alabama": "AL", "Alaska": "AK", "Arizona": "AZ", "Arkansas": "AR", "California": "CA", "Colorado": "CO", "Connecticut": "CT",
        "Delaware": "DE", "Florida": "FL", "Georgia": "GA", "Hawaii": "HI", "Idaho": "ID", "Illinois": "IL", "Indiana": "IN", "Iowa": "IA",
        "Kansas": "KS", "Kentucky": "KY", "Louisiana": "LA", "Maine": "ME", "Maryland": "MD", "Massachusetts": "MA", "Michigan": "MI",
        "Minnesota": "MN", "Mississippi": "MS", "Missouri": "MO", "Montana": "MT", "Nebraska": "NE", "Nevada": "NV", "New Hampshire": "NH",
        "New Jersey": "NJ", "New Mexico": "NM", "New York": "NY", "North Carolina": "NC", "North Dakota": "ND", "Ohio": "OH",
        "Oklahoma": "OK", "Oregon": "OR", "Pennsylvania": "PA", "Rhode Island": "RI", "South Carolina": "SC", "South Dakota": "SD",
        "Tennessee": "TN", "Texas": "TX", "Utah": "UT", "Vermont": "VT", "Virginia": "VA", "Washington": "WA", "West Virginia": "WV",
        "Wisconsin": "WI", "Wyoming": "WY"}
TILES = {"AK": (0, 0), "ME": (11, 0), "VT": (10, 1), "NH": (11, 1), "WA": (1, 2), "ID": (2, 2), "MT": (3, 2), "ND": (4, 2), "MN": (5, 2),
         "IL": (6, 2), "WI": (7, 2), "MI": (8, 2), "NY": (9, 2), "RI": (10, 2), "MA": (11, 2), "OR": (1, 3), "NV": (2, 3), "WY": (3, 3),
         "SD": (4, 3), "IA": (5, 3), "IN": (6, 3), "OH": (7, 3), "PA": (8, 3), "NJ": (9, 3), "CT": (10, 3), "CA": (1, 4), "UT": (2, 4),
         "CO": (3, 4), "NE": (4, 4), "MO": (5, 4), "KY": (6, 4), "WV": (7, 4), "VA": (8, 4), "MD": (9, 4), "DE": (10, 4), "AZ": (2, 5),
         "NM": (3, 5), "KS": (4, 5), "AR": (5, 5), "TN": (6, 5), "NC": (7, 5), "SC": (8, 5), "OK": (4, 6), "LA": (5, 6), "MS": (6, 6),
         "AL": (7, 6), "GA": (8, 6), "HI": (0, 7), "TX": (4, 7), "FL": (9, 7)}
PACKAGES = {"nbformat": "nbformat", "nbclient": "nbclient", "ipykernel": "ipykernel", "pandas": "pandas",
            "numpy": "numpy", "plotly": "plotly", "matplotlib": "matplotlib", "openpyxl": "openpyxl"}


def ensure_packages():
    import importlib.util
    missing = [pip for mod, pip in PACKAGES.items() if importlib.util.find_spec(mod) is None]
    if missing:
        print(f"Installing {', '.join(missing)} ...", flush=True)
        subprocess.check_call([sys.executable, "-m", "pip", "install", "--quiet", *missing])


ensure_packages()
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

# ------------------------------------------------------------------ console helpers
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


# ------------------------------------------------------------------ schedule
def load_state():
    return json.loads(STATE.read_text()) if STATE.exists() else None


def save_state(st):
    OUT.mkdir(parents=True, exist_ok=True)
    STATE.write_text(json.dumps(st, indent=2))


def slot_times(anchor):
    """Every scheduled run time: anchor + k x INTERVAL before FINAL_RUN, then FINAL_RUN."""
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
    print(f"\nSchedule (started {fmt_t(dt.datetime.fromisoformat(st['anchor']))}; every {INTERVAL_HOURS} h; final run "
          f"{fmt_t(FINAL_RUN)}):")
    for i, t in enumerate(slots, 1):
        tag = "FINAL" if t == FINAL_RUN else f"#{i}"
        print(f"  {tag:>5}  {fmt_t(t):<24} {'done' if t.isoformat() in done else ('due' if t <= now() else '')}")
    print(flush=True)


# ------------------------------------------------------------------ running notebooks
class Progress:
    """Background status line while a notebook runs: elapsed, cell, expected time left (from the last run)."""

    def __init__(self, label, expected_s, n_cells, run_t0=None, plan_s=None):
        self.label, self.expected, self.n = label, expected_s, n_cells
        self.run_t0, self.plan_s = run_t0, plan_s  # whole-run start and remaining plan for the whole run (first run)
        self.cell, self.t0, self._stop = 0, time.time(), threading.Event()
        self.th = threading.Thread(target=self._loop, daemon=True)

    def _line(self):
        el = time.time() - self.t0
        if self.expected:
            left = (f"~{fmt_td(self.expected - el)} left in this step (last run: {fmt_td(self.expected)})" if el < self.expected
                    else f"past last run's {fmt_td(self.expected)}; still working")
        elif self.plan_s:
            run_el = time.time() - (self.run_t0 or self.t0)
            lo, hi = self.plan_s
            left = (f"whole run planned {fmt_td(lo)}-{fmt_td(hi)}: ~{fmt_td(max(lo - run_el, 0))}-{fmt_td(max(hi - run_el, 0))} left"
                    if run_el < hi else "longer than planned; still working (results will be saved)")
        else:
            left = "no estimate yet"
        return f"RUNNING {self.label}: cell {self.cell}/{self.n} | elapsed {fmt_td(el)} | {left}"

    def _loop(self):
        while not self._stop.wait(STATUS_EVERY_S):
            say(self._line())

    def start(self):
        say(self._line())
        self.th.start()

    def stop(self):
        self._stop.set()


def run_notebook(path, env, label, expected_s, save=True, run_t0=None, plan_s=None):
    """Execute a notebook in its own folder (like run_all.py). Returns {ok, seconds, error}."""
    import nbformat
    from nbclient import NotebookClient
    from nbclient.exceptions import CellExecutionError
    if sys.platform == "win32":  # Jupyter kernels on Windows need the selector event loop
        import asyncio
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", DeprecationWarning)
            asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    old = {k: os.environ.get(k) for k in env}
    os.environ.update({k: str(v) for k, v in env.items()})
    nb = nbformat.read(path, as_version=4)
    prog = Progress(label, expected_s, sum(c.cell_type == "code" for c in nb.cells), run_t0, plan_s)
    counter = {"i": 0}

    def on_done(cell=None, cell_index=None, **_):
        if cell is not None and cell.cell_type == "code":
            counter["i"] += 1
            prog.cell = counter["i"]

    client = NotebookClient(nb, timeout=CELL_TIMEOUT, kernel_name="python3",
                            resources={"metadata": {"path": str(path.parent)}}, on_cell_complete=on_done)
    t0, err = time.time(), None
    prog.start()
    try:
        client.execute()
    except CellExecutionError as e:
        err = f"{getattr(e, 'ename', 'Error')}: {getattr(e, 'evalue', str(e))}"[:500]
    except Exception as e:  # kernel died, timeout, ...
        err = f"{type(e).__name__}: {e}"[:500]
    finally:
        prog.stop()
        for k, v in old.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        if save:
            nbformat.write(nb, path)
    secs = round(time.time() - t0, 1)
    say(f"{'DONE' if err is None else 'FAILED'} {label} in {fmt_td(secs)}" + (f": {err}" if err else ""))
    return {"ok": err is None, "seconds": secs, "error": err}


# ------------------------------------------------------------------ results
def seat_stats(seats):
    s = seats.sort_values("dem_seats")
    x, w = s["dem_seats"].to_numpy(float), s["share"].to_numpy(float)
    w = w / w.sum()
    cdf = np.cumsum(w)
    q = lambda p: float(x[np.searchsorted(cdf, p)])
    out = {"mean": float((x * w).sum()), "median": q(0.5)}
    for lvl in SEAT_INTERVALS:
        a = (1 - lvl / 100) / 2
        out[f"s{lvl}"] = (q(a), q(1 - a))
    return out


def collect(model_out, testing_out, n_sims, kind, slot, runtime_s, statuses):
    std = model_out / "standard"
    summ = json.loads((std / "summary.json").read_text())
    races = pd.read_csv(std / "races.csv")
    seats = pd.read_csv(std / "seats.csv")
    p = float(summ["p_d_51"])
    z = {90: 1.645, 95: 1.96, 99: 2.576}[P_INTERVAL]
    half = z * np.sqrt(p * (1 - p) / n_sims)
    st = seat_stats(seats)
    checks = None
    cf = testing_out / "checks.csv"
    if cf.exists() and statuses.get("testing", {}).get("ok"):
        checks = pd.read_csv(cf)
    for k in ("kalshi_p_control", "kalshi_expected_seats"):
        if summ.get(k) is not None and pd.isna(summ[k]):
            summ[k] = None
    row = {"run_at": now().strftime("%Y-%m-%d %H:%M"), "kind": kind, "slot": slot, "as_of": summ.get("as_of"),
           "p_d_51": p, "p_lo": max(p - half, 0), "p_hi": min(p + half, 1), "mean_seats": st["mean"], "median_seats": st["median"],
           **{f"s{l}_lo": st[f"s{l}"][0] for l in SEAT_INTERVALS}, **{f"s{l}_hi": st[f"s{l}"][1] for l in SEAT_INTERVALS},
           "kalshi_p_control": summ.get("kalshi_p_control"), "kalshi_seats": summ.get("kalshi_expected_seats"),
           "n_sims": n_sims, "runtime_min": round(runtime_s / 60, 1),
           "testing_pass": int((checks["status"] == "PASS").sum()) if checks is not None else None,
           "testing_warn": int((checks["status"] == "WARN").sum()) if checks is not None else None,
           "testing_fail": int((checks["status"] == "FAIL").sum()) if checks is not None else None,
           "sources_live": sum(v == "live" for v in summ.get("sources", {}).values()), "sources_total": len(summ.get("sources", {}))}
    tossup = 0.60
    cfg_snap = model_out / "config_snapshot.json"
    if cfg_snap.exists():
        try:
            tossup = float(json.loads(cfg_snap.read_text()).get("RATING_TOSSUP", tossup))
        except Exception:
            pass
    races["call"] = [race_call(p, tossup) for p in races["p_dem"]]
    load = lambda p: json.loads(p.read_text()) if p.exists() else {}
    return {"summary": summ, "races": races, "seats": seats, "row": row, "checks": checks, "statuses": statuses, "tossup": tossup,
            "cfg": load(cfg_snap), "headline": load(model_out / "headline.json")}


def race_call(p, tossup):
    """Model's own rating rule: the favourite needs at least RATING_TOSSUP (60%) or the race is too close to call."""
    if max(p, 1 - p) < tossup:
        return "Too close to call"
    return "Democrat / Independent" if p >= 0.5 else "Republican"


def map_frame(res):
    r = res["races"].set_index("state")
    rows = []
    for st, ab in ABBR.items():
        if st in r.index:
            x = r.loc[st]
            rows.append({"state": st, "abbr": ab, "call": x["call"], "p_dem": x["p_dem"], "kalshi_p": x["kalshi_p"], "margin": x["margin"]})
        else:
            rows.append({"state": st, "abbr": ab, "call": "No election", "p_dem": np.nan, "kalshi_p": np.nan, "margin": np.nan})
    return pd.DataFrame(rows)


# ------------------------------------------------------------------ figures
ASCII_MAP = {"\u00d7": "x", "\u00b7": "|", "\u2014": "-", "\u2013": "-", "\u2212": "-", "\u2265": ">=", "\u2264": "<=", "\u00b1": "+/-",
             "\u00b2": "^2", "\u221a": "sqrt", "\u2192": "->", "\u2018": "'", "\u2019": "'", "\u201c": '"', "\u201d": '"', "\u2026": "...",
             "\u00a0": " ", "\u2248": "~", "\u2032": "'"}
MATHJAX_URL = "https://cdn.jsdelivr.net/npm/mathjax@3.2.2/es5/tex-svg.js"


def ascii_text(s):
    """Only characters on a standard keyboard: known symbols spelled out, accents dropped, anything else removed."""
    import unicodedata
    s = "".join(ASCII_MAP.get(ch, ch) for ch in str(s))
    return unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode("ascii")


def mathjax_script():
    """MathJax (renders the LaTeX equations). Downloaded once and embedded, so the dashboard works offline; if the download
    fails, the page loads it from the web instead."""
    cfg = "<script>window.MathJax={tex:{inlineMath:[['\\\\(','\\\\)']]},svg:{fontCache:'global'}};</script>"
    cache = OUT / ".cache" / "mathjax-tex-svg-3.2.2.js"
    try:
        if not cache.exists():
            import urllib.request
            cache.parent.mkdir(parents=True, exist_ok=True)
            with urllib.request.urlopen(MATHJAX_URL, timeout=30) as r:
                cache.write_bytes(r.read())
        js = cache.read_text(encoding="utf-8").replace("</script", "<\\/script")
        return cfg + f"<script>{js}</script>"
    except Exception as e:
        say(f"MathJax couldn't be embedded ({type(e).__name__}); the equations will load it from the web when the page opens")
        return cfg + f"<script src='{MATHJAX_URL}'></script>"


def pct_label(p):
    """Rounded probability that never claims certainty: <1% / >99%."""
    if p is None or pd.isna(p):
        return "-"
    return "<1%" if p < 0.01 else (">99%" if p > 0.99 else f"{p:.0%}")


def margin_label(m):
    return "-" if pd.isna(m) else (f"D+{m:.1f}" if m >= 0 else f"R+{-m:.1f}")


def plotly_figs(res, hist):
    import plotly.graph_objects as go
    row, races, seats = res["row"], res["races"].copy(), res["seats"]
    base = dict(template="simple_white", font=dict(family="Inter, Segoe UI, Arial", size=13, color=INK),
                margin=dict(l=60, r=30, t=50, b=50), hoverlabel=dict(bgcolor="white"))
    figs = {}

    # 1. seat distribution
    s = seats.sort_values("dem_seats")
    f = go.Figure(go.Bar(x=s["dem_seats"], y=100 * s["share"], marker_color=np.where(s["dem_seats"] >= CONTROL_SEATS, D_BLUE, R_RED),
                         hovertemplate="%{x} D seats: %{y:.2f}% of simulations<extra></extra>", name="Most_Magnificent_Model"))
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
    f.update_layout(**base, title=f"Democratic seats in {row['n_sims']:,} simulations - P(D >= {CONTROL_SEATS}): Model "
                    f"{row['p_d_51']:.1%}" + (f" | Kalshi {kc:.1%}" if kc is not None else ""),
                    xaxis_title="Democratic seats (incl. caucusing independents)", yaxis_title="% of simulations",
                    showlegend=False, bargap=0.1, height=450)
    f.update_layout(margin=dict(l=60, r=30, t=80, b=50))
    f.update_xaxes(range=[s.loc[s["share"].cumsum() > 0.001, "dem_seats"].min() - 1.5,
                          s.loc[s["share"].cumsum() < 0.999, "dem_seats"].max() + 1.5])
    figs["seat_distribution"] = f

    # 2. races: Model vs Kalshi
    r = races.sort_values("p_dem")
    f = go.Figure()
    for _, x in r.iterrows():
        if pd.notna(x["kalshi_p"]):
            f.add_shape(type="line", x0=x["kalshi_p"], x1=x["p_dem"], y0=x["state"], y1=x["state"], line=dict(color=GRID, width=3))
    f.add_trace(go.Scatter(x=r["kalshi_p"], y=r["state"], mode="markers", name="Kalshi",
                           marker=dict(symbol="diamond", size=10, color=K_GRAY),
                           hovertemplate="%{y}: Kalshi %{x:.1%}<extra></extra>"))
    f.add_trace(go.Scatter(x=r["p_dem"], y=r["state"], mode="markers", name="Most_Magnificent_Model", marker=dict(size=11, color=D_BLUE),
                           customdata=np.column_stack([r["margin"].map(margin_label), r["sd"].round(1)]),
                           hovertemplate="%{y}: Model %{x:.1%}<br>projected %{customdata[0]} +/- %{customdata[1]}<extra></extra>"))
    f.add_vline(x=0.5, line=dict(color=INK, width=1, dash="dot"))
    f.update_layout(**base, title="P(Democrat or independent wins), by race", height=max(500, 24 * len(r) + 120),
                    xaxis=dict(title="probability", tickformat=".0%", range=[-0.02, 1.02]),
                    legend=dict(orientation="h", y=1.02, x=1, xanchor="right", yanchor="bottom"))
    figs["races_vs_kalshi"] = f

    # 3. map: tile map (one square per state), drawn with shapes so it works offline and matches the PNG
    m = map_frame(res)
    m["cx"], m["cy"] = m["abbr"].map(lambda a: TILES[a][0]), m["abbr"].map(lambda a: -TILES[a][1])
    f = go.Figure()
    for _, x in m.iterrows():
        f.add_shape(type="rect", x0=x["cx"] + 0.05, x1=x["cx"] + 0.95, y0=x["cy"] + 0.05, y1=x["cy"] + 0.95,
                    fillcolor=CALLS[x["call"]], opacity=1, line=dict(color="white", width=1.5), layer="above")
        txt = "#8A8A8A" if x["call"] == "No election" else "white"
        f.add_annotation(x=x["cx"] + 0.5, y=x["cy"] + 0.5, text=f"<b>{x['abbr']}</b>" + ("" if x["call"] == "No election" else
                         f"<br><span style='font-size:10px'>{pct_label(x['p_dem'])}</span>"), showarrow=False, font=dict(color=txt, size=12))
    for call, col in CALLS.items():
        g = m[m["call"] == call]
        hov = g["state"] + "<br>" + ("No Senate race in 2026" if call == "No election" else
              call + "<br>Model " + g["p_dem"].map(pct_label) + " | Kalshi " + g["kalshi_p"].map(pct_label)
              + "<br>projected " + g["margin"].map(margin_label))
        f.add_trace(go.Scatter(x=g["cx"] + 0.5, y=g["cy"] + 0.5, mode="markers", name=f"{call} ({len(g)})", text=hov,
                               hovertemplate="%{text}<extra></extra>",
                               marker=dict(symbol="square", size=34, color=col, opacity=0)))
        f.add_trace(go.Scatter(x=[None], y=[None], mode="markers", name=f"{call} ({len(g)})", hoverinfo="skip",
                               marker=dict(symbol="square", size=12, color=col), showlegend=True))
    for i, t in enumerate(f.data):  # legend shows only the visible swatches
        t.showlegend = i % 2 == 1
    f.update_layout(**{k: v for k, v in base.items() if k != "margin"}, margin=dict(l=10, r=10, t=50, b=10), height=520,
                    title=f"Projected winner by state (number = Model P(D/Ind wins); too close to call = favourite under {res['tossup']:.0%})",
                    xaxis=dict(visible=False, range=[-0.2, 12.2]), yaxis=dict(visible=False, range=[-7.3, 1.2], scaleanchor="x"),
                    plot_bgcolor="rgba(0,0,0,0)", legend=dict(orientation="h", y=-0.02, x=0.5, xanchor="center", yanchor="top"))
    figs["race_map"] = f

    # 4/5. history
    h = hist.copy()
    h["t"] = pd.to_datetime(h["run_at"])
    lbl = np.where(h["kind"] == "final", "FINAL", np.where(h["kind"] == "test", "test", ""))
    f = go.Figure()
    f.add_trace(go.Scatter(x=list(h["t"]) + list(h["t"][::-1]), y=list(h["p_hi"]) + list(h["p_lo"][::-1]), fill="toself",
                           fillcolor="rgba(26,111,176,0.15)", mode="lines", line=dict(width=0), hoverinfo="skip", name=f"{P_INTERVAL}% simulation interval"))
    f.add_trace(go.Scatter(x=h["t"], y=h["p_d_51"], mode="lines+markers+text", name="Most_Magnificent_Model", text=lbl, textposition="top center",
                           line=dict(color=D_BLUE, width=3), hovertemplate="%{x|%b %d %I:%M %p}: %{y:.1%}<extra>Model</extra>"))
    f.add_trace(go.Scatter(x=h["t"], y=h["kalshi_p_control"], mode="lines+markers", name="Kalshi control market",
                           line=dict(color=K_GRAY, width=2, dash="dash"), hovertemplate="%{x|%b %d %I:%M %p}: %{y:.1%}<extra>Kalshi</extra>"))
    f.update_layout(**base, title=f"P(D >= {CONTROL_SEATS}) over time", height=380, yaxis=dict(tickformat=".0%", range=[0, 1]),
                    legend=dict(orientation="h", y=1.02, x=1, xanchor="right", yanchor="bottom"))
    pad = dt.timedelta(hours=8)
    xr = [h["t"].min() - pad, h["t"].max() + pad]
    f.update_xaxes(range=xr, tickformat="%b %d<br>%I %p")
    figs["history_control"] = f
    lo, hi = f"s{SEAT_INTERVALS[0]}_lo", f"s{SEAT_INTERVALS[0]}_hi"
    f = go.Figure()
    f.add_trace(go.Scatter(x=list(h["t"]) + list(h["t"][::-1]), y=list(h[hi]) + list(h[lo][::-1]), fill="toself",
                           fillcolor="rgba(26,111,176,0.12)", mode="lines", line=dict(width=0), hoverinfo="skip", name=f"{SEAT_INTERVALS[0]}% seat range"))
    f.add_trace(go.Scatter(x=h["t"], y=h["mean_seats"], mode="lines+markers+text", name="Most_Magnificent_Model mean", text=lbl, textposition="top center",
                           line=dict(color=D_BLUE, width=3), hovertemplate="%{x|%b %d %I:%M %p}: %{y:.2f}<extra>Model</extra>"))
    f.add_trace(go.Scatter(x=h["t"], y=h["kalshi_seats"], mode="lines+markers", name="Kalshi (sum of race prices)",
                           line=dict(color=K_GRAY, width=2, dash="dash"), hovertemplate="%{x|%b %d %I:%M %p}: %{y:.2f}<extra>Kalshi</extra>"))
    f.add_hline(y=CONTROL_SEATS - 0.5, line=dict(color=INK, width=1, dash="dot"))
    f.update_layout(**base, title="Expected Democratic seats over time", height=380, yaxis_title="D seats",
                    legend=dict(orientation="h", y=1.02, x=1, xanchor="right", yanchor="bottom"))
    f.update_xaxes(range=xr, tickformat="%b %d<br>%I %p")
    figs["history_seats"] = f
    return figs


def png_figs(res, hist, folder):
    """Static PNG versions (matplotlib) of the same four charts."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import matplotlib.dates  # noqa: F401  (date axis labels)
    import matplotlib.patches  # noqa: F401  (map tiles)
    import matplotlib.ticker  # noqa: F401
    plt.rcParams.update({"font.size": 10, "axes.spines.top": False, "axes.spines.right": False})
    row, races, seats = res["row"], res["races"], res["seats"].sort_values("dem_seats")
    paths = {}
    fig, ax = plt.subplots(figsize=(10, 4.6))
    ax.bar(seats["dem_seats"], 100 * seats["share"], color=np.where(seats["dem_seats"] >= CONTROL_SEATS, D_BLUE, R_RED), width=0.85)
    ax.axvline(CONTROL_SEATS - 0.5, color=INK, lw=1.5)
    ax.axvline(row["mean_seats"], color=D_BLUE, ls=":", lw=2, label=f"Model mean {row['mean_seats']:.1f}")
    if row["kalshi_seats"] is not None:
        ax.axvline(row["kalshi_seats"], color=K_GRAY, ls="--", lw=2, label=f"Kalshi {row['kalshi_seats']:.1f}")
    keep = seats[(seats["share"].cumsum() > 0.001) & (seats["share"].cumsum() < 0.999)]["dem_seats"]
    ax.set_xlim(keep.min() - 1.5, keep.max() + 1.5)
    ax.set_xlabel("Democratic seats (incl. caucusing independents)"); ax.set_ylabel("% of simulations")
    kc = row["kalshi_p_control"]
    ax.set_title(f"P(D >= {CONTROL_SEATS}): Model {row['p_d_51']:.1%}" + (f" | Kalshi {kc:.1%}" if kc is not None else ""), loc="left", fontweight="bold")
    ax.legend(frameon=False)
    fig.tight_layout(); paths["seat_distribution"] = folder / "seat_distribution.png"; fig.savefig(paths["seat_distribution"], dpi=200); plt.close(fig)

    r = races.sort_values("p_dem")
    fig, ax = plt.subplots(figsize=(8, 0.28 * len(r) + 1.2))
    y = np.arange(len(r))
    ax.hlines(y, r["kalshi_p"], r["p_dem"], color=GRID, lw=3)
    ax.scatter(r["kalshi_p"], y, marker="D", color=K_GRAY, s=28, label="Kalshi", zorder=3)
    ax.scatter(r["p_dem"], y, color=D_BLUE, s=34, label="Most_Magnificent_Model", zorder=4)
    ax.axvline(0.5, color=INK, lw=0.8, ls=":")
    ax.set_yticks(y, r["state"]); ax.set_xlim(-0.02, 1.02)
    ax.xaxis.set_major_formatter(matplotlib.ticker.PercentFormatter(1.0))
    ax.set_title("P(Democrat or independent wins), by race", loc="left", fontweight="bold")
    ax.legend(frameon=False, loc="lower right")
    fig.tight_layout(); paths["races_vs_kalshi"] = folder / "races_vs_kalshi.png"; fig.savefig(paths["races_vs_kalshi"], dpi=200); plt.close(fig)

    m = map_frame(res).set_index("abbr")
    fig, ax = plt.subplots(figsize=(10, 6.2))
    for ab, (cx, cy) in TILES.items():
        call = m.loc[ab, "call"]
        ax.add_patch(matplotlib.patches.FancyBboxPatch((cx + 0.05, -cy + 0.05), 0.9, 0.9, boxstyle="round,pad=0,rounding_size=0.08",
                                                       facecolor=CALLS[call], edgecolor="white", lw=1.5))
        txt = "white" if call != "No election" else "#8A8A8A"
        ax.text(cx + 0.5, -cy + 0.62, ab, ha="center", va="center", fontsize=10, fontweight="bold", color=txt)
        if call != "No election":
            ax.text(cx + 0.5, -cy + 0.3, pct_label(m.loc[ab, "p_dem"]), ha="center", va="center", fontsize=8, color=txt)
    ax.set_xlim(-0.2, 12.2); ax.set_ylim(-7.4, 1.3); ax.set_aspect("equal"); ax.axis("off")
    handles = [matplotlib.patches.Patch(color=c, label=f"{k} ({int((m['call'] == k).sum())})") for k, c in CALLS.items()]
    ax.legend(handles=handles, loc="lower center", ncol=4, frameon=False, bbox_to_anchor=(0.5, -0.06))
    ax.set_title(f"Projected winner by state (number = Model P(D/Ind wins); too close to call = favourite under {res['tossup']:.0%})",
                 loc="left", fontweight="bold", fontsize=10)
    fig.tight_layout(); paths["race_map"] = folder / "race_map.png"; fig.savefig(paths["race_map"], dpi=200); plt.close(fig)

    h = hist.copy(); h["t"] = pd.to_datetime(h["run_at"])
    for key, col, kcol, band, title, pct in [
            ("history_control", "p_d_51", "kalshi_p_control", ("p_lo", "p_hi"), f"P(D >= {CONTROL_SEATS}) over time", True),
            ("history_seats", "mean_seats", "kalshi_seats", (f"s{SEAT_INTERVALS[0]}_lo", f"s{SEAT_INTERVALS[0]}_hi"), "Expected Democratic seats over time", False)]:
        fig, ax = plt.subplots(figsize=(10, 3.8))
        ax.fill_between(h["t"], h[band[0]], h[band[1]], color=D_BLUE, alpha=0.13, lw=0)
        ax.plot(h["t"], h[col], marker="o", color=D_BLUE, lw=2.5, label="Most_Magnificent_Model")
        ax.plot(h["t"], h[kcol], marker="o", color=K_GRAY, lw=1.8, ls="--", label="Kalshi")
        ax.set_xlim(h["t"].min() - pd.Timedelta(hours=8), h["t"].max() + pd.Timedelta(hours=8))
        ax.xaxis.set_major_formatter(matplotlib.dates.DateFormatter("%b %d\n%I %p"))
        if pct:
            ax.set_ylim(0, 1); ax.yaxis.set_major_formatter(matplotlib.ticker.PercentFormatter(1.0))
        else:
            ax.axhline(CONTROL_SEATS - 0.5, color=INK, lw=0.8, ls=":")
        ax.set_title(title, loc="left", fontweight="bold"); ax.legend(frameon=False); ax.grid(axis="y", color=GRID)
        fig.tight_layout()
        paths[key] = folder / f"{key}.png"; fig.savefig(paths[key], dpi=200); plt.close(fig)
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
th{cursor:pointer;background:var(--card);position:sticky;top:0} th:first-child,td:first-child{text-align:left} .wrap{overflow-x:auto}
.eq{border-bottom:1px solid var(--line);padding:10px 0} .eqn{font-size:12px;color:var(--muted);text-transform:uppercase;letter-spacing:.04em}
.eqf{font-family:'Cambria Math',Cambria,Georgia,serif;font-size:16px;margin:4px 0;overflow-x:auto} .eqw{font-size:13px;color:var(--muted)}
.kv td{text-align:left;white-space:normal} .kv td:first-child{width:32%;color:var(--muted)} .notes li{margin:3px 0;font-size:13px}
@media (prefers-color-scheme: dark){:root{--ink:#E8E8E8;--muted:#A0A0A0;--line:#333;--bg:#141414;--card:#1D1F22}}
"""
SORT_JS = """
document.querySelectorAll('table.sortable').forEach(t=>{t.querySelectorAll('th').forEach((th,i)=>{th.addEventListener('click',()=>{
const b=t.tBodies[0],rows=[...b.rows],asc=th.dataset.asc!=='1';th.dataset.asc=asc?'1':'0';
rows.sort((x,y)=>{const a=x.cells[i].dataset.v??x.cells[i].innerText,c=y.cells[i].dataset.v??y.cells[i].innerText;
const na=parseFloat(a),nc=parseFloat(c);return (isNaN(na)||isNaN(nc)?a.localeCompare(c):na-nc)*(asc?1:-1)});rows.forEach(r=>b.appendChild(r))})})});
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
    """The model's equations (LaTeX, rendered by MathJax) with the values this run used (config_snapshot / headline)."""
    c, hd = res.get("cfg", {}), res.get("headline", {})
    if not c:
        return "<p class='sub'>Settings snapshot not found for this run.</p>"
    g = lambda k, d=None: c.get(k, d)

    def n(v, f="g"):
        return "?" if v is None else format(float(v), f)

    pw, pa = g("POPULATION_WEIGHTS", {}), g("PARTISAN_WEIGHTS", {})
    clip, kr = g("ACCURACY_WEIGHT_CLIP", [0.5, 2.0]), g("KALSHI_USE_RANGE", [0.06, 0.94])
    k_he, ksd, rv = n(g("HOUSE_EFFECT_K")), g("KALSHI_SD"), hd.get("rv_shift")
    gb = float(g("GENERIC_BALLOT_BLEND", 0.75))
    caucus = ", ".join(f"{s} {p:g}" for s, p in g("INDEPENDENT_CAUCUS_PROB_D", {}).items())
    blocks = [
        ("1. Weight of each poll",
         r"w = 0.5^{{\text{{age}}/{hl}}} \times \left(\frac{{\min(n,\,{cap})}}{{{ref}}}\right)^{{{ex}}} \times w_{{\text{{pop}}}} \times w_{{\text{{partisan}}}} "
         r"\times w_{{\text{{generic}}}} \times w_{{\text{{field}}}} \times w_{{\text{{quality}}}} \times w_{{\text{{accuracy}}}} \times \frac{{1}}{{k^{{{fl}}}}} \times \frac{{1}}{{\text{{versions}}}}",
         dict(hl=n(g("RECENCY_HALF_LIFE_DAYS")), cap=n(g("SAMPLE_SIZE_CAP")), ref=n(g("REFERENCE_SAMPLE")), ex=n(g("SAMPLE_SIZE_EXPONENT")), fl=n(g("FLOOD_EXPONENT"))),
         f"Population: LV {n(pw.get('LV'))}, RV {n(pw.get('RV'))}, adults {n(pw.get('A'))}. Partisan sponsor {n(pa.get('Republican'))}. "
         f"Generic-party question {n(g('GENERIC_WEIGHT'))}. Full field {n(g('BIGGER_FIELD_WEIGHT'))}. Quality {n(g('MIN_QUALITY_WEIGHT'))} to 1 by VoteHub grade "
         f"(ungraded firms get a random graded firm's grade in each simulation). Accuracy = ({n(g('MAE_TO_SD'))} x {n(g('DEFAULT_TYPICAL_ERROR'))} / poll SD)^2, "
         f"kept between {n(clip[0])} and {n(clip[1])}. k = the pollster's polls of that race."),
        ("2. Each poll's margin",
         r"m = (D - R)\,\frac{{D + R + U}}{{D + R}} + s_{{RV}} \pm s_{{\text{{partisan}}}} - h, \qquad h = \frac{{\sum \text{{residuals}} + {k} \, h_{{\text{{scorecard}}}}}}{{n_{{\text{{polls}}}} + {k}}}",
         dict(k=k_he),
         f"U = undecided. RV shift s_RV = {'?' if rv is None else f'{rv:+.2f}'} pts (registered-voter polls only; measured from LV/RV pairs). "
         f"Partisan shift = {n(g('PARTISAN_HOUSE_EFFECTS', {}).get('Republican'))} pts against the sponsor. Residual = poll minus the same state's average "
         f"of other pollsters, from the last {n(g('HOUSE_EFFECT_WINDOW_DAYS'))} days."),
        ("3. Polling average",
         r"\bar{{m}} = \frac{{\sum w\,m}}{{\sum w}}, \qquad SD_{{\text{{polls}}}} = \sqrt{{\frac{{SD_{{\text{{poll}}}}^2}}{{n_{{\text{{eff}}}}}} + {fl}^2 + SD_U^2}}, \qquad n_{{\text{{eff}}}} = \frac{{(\sum w)^2}}{{\sum w^2}}",
         dict(fl=n(g("SYSTEMATIC_POLL_ERROR_SD"), ".2f")),
         "The middle term is the error all polls of a state share, so more polls can't remove it."),
        ("4. National environment",
         r"\text{{env}} = {gb} \times \text{{GB}} + {ap} \times {sl} \times (-\text{{net approval}}), \qquad \text{{signal}} = \frac{{n_{{\text{{fresh}}}} \cdot \text{{VoteHub}} + {kk} \cdot \text{{Kalshi}}}}{{n_{{\text{{fresh}}}} + {kk}}}",
         dict(gb=n(gb), ap=n(1 - gb), sl=n(g("ENV_SLOPE")), kk=n(g("NAT_KALSHI_POLL_EQUIV"))),
         f"GB = generic ballot. Each VoteHub poll counts 0.5^(age / {n(g('NAT_FRESH_HALF_LIFE_DAYS'))}) toward n_fresh."
         + ("" if hd.get("env") is None else f" This run: env = D{float(hd['env']):+.1f}.")),
        ("5. Prior (fundamentals)",
         r"\text{{prior}} = {pvi} \times \text{{PVI}} + \text{{env}} \pm {inc} \,[\text{{incumbent}}] + {cw} \times c, \qquad SD_{{\text{{prior}}}} = {psd}",
         dict(pvi=n(g("PVI_TO_MARGIN")), inc=n(g("INCUMBENCY_ADVANTAGE"), ".2f"), cw=n(g("CANDIDATE_EFFECT_WEIGHT"), ".2f"), psd=n(g("PRIOR_SD"), ".2f")),
         f"Appointed incumbents get {n(g('APPOINTED_INCUMBENT_ADVANTAGE'))} pt. c = candidate effect: the nominees' past margin minus a generic candidate's "
         f"(capped at +/- {n(g('CANDIDATE_EFFECT_CLIP'))}). Independent-led races: SD x {n(g('INDEPENDENT_PRIOR_SD_MULT'))}."),
        ("6. Kalshi",
         r"P' = \text{{logistic}}\left({ls} \cdot \text{{logit}}\,P\right), \qquad \text{{margin}}_K = \Phi^{{-1}}(P') \cdot \max\left({cs},\ SD_{{F+P}}\right), \qquad SD_K = {ksd}",
         dict(ls=n(g("KALSHI_LONGSHOT_SLOPE")), cs=n(g("KALSHI_CONVERT_SD"), ".2f"), ksd=n(ksd) if ksd else r"\infty"),
         f"Used only when {float(kr[0]):.0%} <= P <= {float(kr[1]):.0%}."),
        ("7. Each race",
         r"\text{{margin}} = \frac{{\pi_F \cdot \text{{prior}} + \pi_P \cdot \bar{{m}} + \pi_K \cdot \text{{margin}}_K}}{{\pi_F + \pi_P + \pi_K}}, \quad \pi = \frac{{1}}{{SD^2}}, \quad "
         r"SD^2 = \frac{{1}}{{\Pi}} + \frac{{2({rho})}}{{\Pi^2}}\left(\sqrt{{\pi_F \pi_P}} + \sqrt{{\pi_F \pi_K}} + \sqrt{{\pi_P \pi_K}}\right) + {dr}^2 \cdot \text{{days left}}",
         dict(rho=n(g("SOURCE_ERROR_CORR")), dr=n(g("DAILY_DRIFT_SD"), ".2f")),
         "Pi = the sum of the three precisions. The second term widens the range because the three sources tend to miss together."),
        ("8. Simulations",
         r"\tilde{{m}}_i = \text{{margin}}_i + N + R_{{g(i)}} + L\,f_i + e_i, \qquad \text{{D seats}} = {hold} + \sum_i \mathbf{{1}}[\tilde{{m}}_i > 0], \qquad P(D \geq {ctl}) = \text{{share of simulations}}",
         dict(hold=n(g("HOLDOVER_D")), ctl=CONTROL_SEATS),
         f"N = national miss (SD {n(g('NATIONAL_ERROR_SD'), '.2f')}, t with df {n(g('NATIONAL_T_DF'))}). R = regional miss (SD {n(g('REGIONAL_ERROR_SD'), '.2f')}). "
         f"L = lean factor (SD {n(g('LEAN_FACTOR_ERROR_SD'))}), f_i = PVI / {n(g('LEAN_FACTOR_SCALE'))}. e = the rest of the race's SD (t with df {n(g('STATE_T_DF'), '.1f')}). "
         f"An independent's win counts for Democrats with probability: {caucus}."),
    ]
    out = []
    for title, tex, vals, where in blocks:
        latex = tex.format(**vals)  # {{ }} in the templates are literal LaTeX braces
        out.append(f"<div class='eq'><div class='eqn'>{title}</div><div class='eqf'>\\[{latex}\\]</div><div class='eqw'>{ascii_text(where)}</div></div>")
    return "".join(out)


def build_dashboard(res, hist, figs, title_tag, path):
    import plotly
    row, summ, races = res["row"], res["summary"], res["races"].copy()
    kind = row["kind"]
    badge = {"final": "<span class='badge final'>FINAL</span>", "test": "<span class='badge test'>TEST</span>"}.get(kind, "<span class='badge'>scheduled</span>")
    kc, ks = row["kalshi_p_control"], row["kalshi_seats"]
    s_iv = " | ".join(f"{l}%: {row[f's{l}_lo']:.0f}-{row[f's{l}_hi']:.0f}" for l in SEAT_INTERVALS)
    tiles = f"""
<div class='tiles'>
 <div class='tile'><div class='k'>P(Democrats >= {CONTROL_SEATS} seats)</div><div class='v blue'>{row['p_d_51']:.1%}</div>
  <div class='s'>{P_INTERVAL}% simulation interval {row['p_lo']:.1%}-{row['p_hi']:.1%}</div></div>
 <div class='tile'><div class='k'>Expected Democratic seats</div><div class='v'>{row['mean_seats']:.1f}</div>
  <div class='s'>median {row['median_seats']:.0f} | {s_iv}</div></div>
 <div class='tile'><div class='k'>Kalshi control market</div><div class='v' style='color:#7A7A7A'>{'-' if kc is None else f'{kc:.1%}'}</div>
  <div class='s'>sum of race prices: {'-' if ks is None else f'{ks:.1f} seats'}</div></div>
 <div class='tile'><div class='k'>Run</div><div class='v' style='font-size:20px'>{row['run_at']}</div>
  <div class='s'>{row['n_sims']:,} simulations | data as of {row['as_of']} | {row['runtime_min']:.0f} min</div></div>
</div>"""
    # race table
    first = hist[hist["kind"] != "test"].head(1)
    base_races = None
    if len(first):
        rh = pd.read_csv(RACE_HISTORY) if RACE_HISTORY.exists() else None
        if rh is not None:
            base_races = rh[rh["run_at"] == first["run_at"].iloc[0]].set_index("state")
    rows_html = []
    for _, x in races.sort_values("p_dem", ascending=False).iterrows():
        d = x["p_dem"] - x["kalshi_p"] if pd.notna(x["kalshi_p"]) else np.nan
        chg_m = chg_k = np.nan
        if base_races is not None and x["state"] in base_races.index:
            chg_m = x["p_dem"] - base_races.loc[x["state"], "p_dem"]
            chg_k = x["kalshi_p"] - base_races.loc[x["state"], "kalshi_p"]
        f = lambda v: "<td data-v='0'>-</td>" if pd.isna(v) else f"<td data-v='{v:.4f}'>{v * 100:+.0f}</td>"
        rows_html.append(f"<tr><td>{x['state']}</td><td style='text-align:left'>{x['call']}</td>{pct_cell(x['p_dem'])}{pct_cell(x['kalshi_p'])}{f(d)}"
                         f"<td data-v='{x['margin']:.2f}'>{margin_label(x['margin'])}</td><td data-v='{x['sd']:.2f}'>+/-{x['sd']:.1f}</td>"
                         f"<td data-v='{x['n_polls']}'>{int(x['n_polls'])}</td>{f(chg_m)}{f(chg_k)}</tr>")
    race_table = ("<div class='wrap'><table class='sortable'><thead><tr><th>Race</th><th>Call</th><th>Model P(D/Ind)</th><th>Kalshi P(D/Ind)</th>"
                  "<th>Model - Kalshi (pts)</th><th>Projected margin</th><th>+/- (1 SD)</th><th>Polls</th>"
                  "<th>Model change since first run (pts)</th><th>Kalshi change since first run (pts)</th></tr></thead><tbody>"
                  + "".join(rows_html) + "</tbody></table></div>")
    # key settings
    ks_rows = "".join(f"<tr><td>{k}</td><td>{v}</td></tr>" for k, v in summ.get("key_settings", {}).items())
    ks_rows += f"<tr><td>Simulations</td><td>{row['n_sims']:,}</td></tr>"
    # notes
    notes = []
    stt = res["statuses"]
    t = stt.get("testing")
    if t is None:
        notes.append("Model Testing: not run (test mode).")
    elif not t["ok"]:
        notes.append(f"Model Testing: FAILED ({t['error']}).")
    elif res["checks"] is not None:
        c = res["checks"]
        notes.append(f"Model Testing: {row['testing_pass']} PASS | {row['testing_warn']} WARN | {row['testing_fail']} FAIL"
                     + (f" (details in {WARNINGS_XLSX.name})." if row["testing_warn"] or row["testing_fail"] else "."))
        for _, x in c[c["status"] == "FAIL"].iterrows():
            notes.append(f"FAIL - {x['check']}: {x['detail']}")
    src = summ.get("sources", {})
    notes.append("Data: " + ", ".join(f"{k.replace('_cache.csv', '')} {v}" for k, v in src.items()) + ".")
    if not stt["model"]["ok"]:
        notes.append(f"Model run FAILED: {stt['model']['error']}")
    notes_html = "<ul class='notes'>" + "".join(f"<li>{n}</li>" for n in notes) + "</ul>"
    fig_html = {k: f.to_html(full_html=False, include_plotlyjs=False, config={"displaylogo": False, "responsive": True}) for k, f in figs.items()}
    body = f"""<h1>2026 Senate forecast - Most_Magnificent_Model {badge}</h1><div class='sub'>Team 5: {', '.join(TEAM)}</div><div class='sub'>{title_tag}</div>
{tiles}
<h2>Seat distribution</h2>{fig_html['seat_distribution']}
<h2>Map</h2>{fig_html['race_map']}
<h2>Race by race</h2>{fig_html['races_vs_kalshi']}{race_table}
<h2>History</h2>{fig_html['history_control']}{fig_html['history_seats']}
<h2>Notes</h2>{notes_html}
<h2>Key settings</h2><table class='kv'><tbody>{ks_rows}</tbody></table>
<h2>Equations and weights</h2>{equations_html(res)}"""
    html = (f"<!doctype html><html lang='en'><head><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'>"
            f"<title>Most_Magnificent_Model Forecast</title><style>{CSS}</style><script>{plotly.offline.get_plotlyjs()}</script>"
            f"{mathjax_script()}</head><body><main>\n{ascii_text(body)}\n</main><script>{SORT_JS}</script></body></html>")
    path.write_text(html, encoding="utf-8")


def log_warnings(checks, run_at, kind):
    """Append this run's WARN / FAIL checks to Forecasts/model_warnings.xlsx (one row per check per run)."""
    new = checks[checks["status"] != "PASS"].assign(run_at=run_at, kind=kind)[["run_at", "kind", "status", "section", "check", "detail"]]
    if new.empty:
        new = pd.DataFrame([{"run_at": run_at, "kind": kind, "status": "PASS", "section": "", "check": "all checks passed", "detail": ""}])
    try:
        old = pd.read_excel(WARNINGS_XLSX) if WARNINGS_XLSX.exists() else pd.DataFrame()
        allw = pd.concat([old, new], ignore_index=True)
        with pd.ExcelWriter(WARNINGS_XLSX, engine="openpyxl") as xw:
            allw.to_excel(xw, sheet_name="warnings", index=False)
            ws = xw.sheets["warnings"]
            for col, width in zip("ABCDEF", (17, 10, 8, 8, 42, 90)):
                ws.column_dimensions[col].width = width
            ws.freeze_panes = "A2"
            ws.auto_filter.ref = ws.dimensions
        say(f"Logged {len(new)} warning row(s) to {WARNINGS_XLSX.name}")
    except PermissionError:  # the workbook is open in Excel
        alt = OUT / f"model_warnings_{run_at.replace(':', '').replace(' ', '_')}.xlsx"
        new.to_excel(alt, index=False)
        say(f"{WARNINGS_XLSX.name} is open in Excel, so this run's warnings went to {alt.name}; close Excel and they'll append next run")
    except Exception as e:
        say(f"Couldn't update {WARNINGS_XLSX.name} ({type(e).__name__}: {e}); the run's checks are still in its data/checks.csv")


def save_figures(figs, res, hist, folder):
    folder.mkdir(parents=True, exist_ok=True)
    for k, f in figs.items():
        f.write_html(folder / f"{k}.html", include_plotlyjs="cdn", full_html=True)  # small files; Plotly loads from the web
    try:
        png_figs(res, hist, folder)
    except Exception as e:
        say(f"PNG export failed ({type(e).__name__}: {e}); HTML figures were saved")


# ------------------------------------------------------------------ one run
def do_run(kind, slot, n_sims, test=False):
    stamp = now().strftime("%Y-%m-%d_%H%M")
    folder = OUT / (f"test_{stamp}" if test else stamp)
    folder.mkdir(parents=True, exist_ok=True)
    st = load_state() or {}
    durations = st.get("durations", {})
    env = {"FORECAST_N_SIMS": n_sims}
    model_out = MODEL_DIR / "Output"
    if test:  # keep Most_Magnificent_Model/Output untouched
        model_out = folder / "model_output"
        env["FORECAST_OUT_DIR"] = model_out
    statuses, t0 = {}, time.time()
    say(f"=== {'TEST RUN' if test else ('FINAL RUN' if kind == 'final' else 'SCHEDULED RUN')} started "
        f"({n_sims:,} simulations) -> {folder.relative_to(REPO)}")
    plan = None if test else tuple(60 * m for m in PLANNED_MINUTES)
    if not test:
        statuses["testing"] = run_notebook(TEST_NB, env, "step 1/2 Model Testing", durations.get("testing"), save=True,
                                           run_t0=t0, plan_s=plan)
        durations["testing"] = statuses["testing"]["seconds"]
    statuses["model"] = run_notebook(MODEL_NB, env, "step 2/2 forecast" if not test else "test forecast",
                                     None if test else durations.get("model"), save=not test, run_t0=t0, plan_s=plan)
    if not test:
        durations["model"] = statuses["model"]["seconds"]
        st["durations"] = durations
        save_state(st)
    if not (model_out / "standard" / "summary.json").exists():
        say("No forecast output was produced; nothing to report for this run.")
        return None
    runtime = time.time() - t0
    res = collect(model_out, model_out / "testing", n_sims, kind, slot, runtime, statuses)
    res["row"]["folder"] = folder.name
    # data for this run
    data = folder / "data"; data.mkdir(exist_ok=True)
    for f in (model_out / "standard").glob("*"):
        shutil.copy2(f, data / f.name)
    for name in ("checks.csv",):
        if (model_out / "testing" / name).exists():
            shutil.copy2(model_out / "testing" / name, data / name)
    for name in ("headline.json", "config_snapshot.json", "race_probabilities.csv"):
        if (model_out / name).exists():
            shutil.copy2(model_out / name, data / name)
    # history (tests are shown on their own dashboard but never written to the history files)
    hist = pd.read_csv(HISTORY) if HISTORY.exists() else pd.DataFrame()
    races = res["races"].assign(run_at=res["row"]["run_at"], kind=kind)[["run_at", "kind", "state", "call", "p_dem", "kalshi_p", "margin", "sd", "n_polls"]]
    if test:
        hist_show = pd.concat([hist, pd.DataFrame([res["row"]])], ignore_index=True)
    else:
        hist_show = pd.concat([hist, pd.DataFrame([res["row"]])], ignore_index=True)
        hist_show.to_csv(HISTORY, index=False)
        rh = pd.read_csv(RACE_HISTORY) if RACE_HISTORY.exists() else pd.DataFrame()
        pd.concat([rh, races], ignore_index=True).to_csv(RACE_HISTORY, index=False)
    races.to_csv(data / "races_this_run.csv", index=False)
    if not test and res["checks"] is not None:
        log_warnings(res["checks"], res["row"]["run_at"], kind)
    figs = plotly_figs(res, hist_show)
    save_figures(figs, res, hist_show, folder / "figures")
    tag = (f"test run {res['row']['run_at']} ({n_sims:,} simulations; not saved to history)" if test else
           ("final forecast, " if kind == "final" else "scheduled run, ") + f"{res['row']['run_at']}")
    if test:
        dash = OUT / f"test_{stamp}.html"
        build_dashboard(res, hist_show, figs, tag, dash)
    else:
        dash = folder / "dashboard.html"
        build_dashboard(res, hist_show, figs, tag, dash)
        shutil.copy2(dash, OUT / "latest.html")
    say(f"=== Run finished in {fmt_td(runtime)}: P(D >= {CONTROL_SEATS}) {res['row']['p_d_51']:.1%} "
        f"({P_INTERVAL}%: {res['row']['p_lo']:.1%}-{res['row']['p_hi']:.1%}), mean seats {res['row']['mean_seats']:.2f} "
        f"| dashboard: {dash.relative_to(REPO)}")
    return res


# ------------------------------------------------------------------ rebuild dashboards from saved runs (no model run)
def load_saved_run(folder, row):
    d = folder / "data"
    load = lambda p: json.loads(p.read_text()) if p.exists() else {}
    cfg, headline = load(d / "config_snapshot.json"), load(d / "headline.json")
    races, seats = pd.read_csv(d / "races.csv"), pd.read_csv(d / "seats.csv")
    checks = pd.read_csv(d / "checks.csv") if (d / "checks.csv").exists() else None
    tossup = float(cfg.get("RATING_TOSSUP", 0.60))
    races["call"] = [race_call(p, tossup) for p in races["p_dem"]]
    row = {k: (None if isinstance(v, float) and np.isnan(v) else v) for k, v in row.items()}
    for k in ("testing_pass", "testing_warn", "testing_fail", "n_sims", "sources_live", "sources_total"):
        if row.get(k) is not None:
            row[k] = int(row[k])
    statuses = {"model": {"ok": True, "error": None},
                "testing": {"ok": True, "error": None} if checks is not None else {"ok": False, "error": "no checks saved"}}
    return {"summary": load(d / "summary.json"), "races": races, "seats": seats, "row": row, "checks": checks,
            "statuses": statuses, "tossup": tossup, "cfg": cfg, "headline": headline}


def rebuild_reports():
    """Rebuild every scheduled run's dashboard + figures (and latest.html) from its saved data, with the current code."""
    import re
    if not HISTORY.exists():
        say("No history yet; nothing to rebuild.")
        return
    hist = pd.read_csv(HISTORY)
    folders = sorted(p for p in OUT.iterdir() if p.is_dir() and re.fullmatch(r"\d{4}-\d{2}-\d{2}_\d{4}", p.name) and (p / "data" / "summary.json").exists())
    if "folder" not in hist.columns or hist["folder"].isna().any():
        if len(folders) != len(hist):
            say(f"Can't match {len(hist)} history rows to {len(folders)} run folders; rebuild skipped.")
            return
        hist["folder"] = [p.name for p in folders]  # runs before this version: matched in order
        hist.to_csv(HISTORY, index=False)
    last = None
    for i, r in hist.reset_index(drop=True).iterrows():
        folder = OUT / r["folder"]
        if not (folder / "data" / "summary.json").exists():
            continue
        hist_upto = hist.iloc[: i + 1].drop(columns="folder")
        res = load_saved_run(folder, r.drop(labels="folder").to_dict())
        figs = plotly_figs(res, hist_upto)
        save_figures(figs, res, hist_upto, folder / "figures")
        tag = ("final forecast, " if r["kind"] == "final" else "scheduled run, ") + str(r["run_at"])
        build_dashboard(res, hist_upto, figs, tag, folder / "dashboard.html")
        last = folder / "dashboard.html"
        say(f"Rebuilt {folder.name}")
    if last is not None:
        shutil.copy2(last, OUT / "latest.html")
        say(f"latest.html = {last.parent.name}")


# ------------------------------------------------------------------ main loop
def main():
    ap = argparse.ArgumentParser(description="Scheduled Most_Magnificent_Model forecasts + dashboard.")
    ap.add_argument("--test", action="store_true", help=f"one quick run ({TEST_N_SIMS:,} simulations) -> Forecasts/test_<datetime>.html")
    ap.add_argument("--status", action="store_true", help="show the schedule and exit")
    ap.add_argument("--report", action="store_true", help="rebuild every saved run's dashboard and latest.html with the current code")
    ap.add_argument("--reset", action="store_true", help="DELETE the schedule, history, warnings workbook, latest.html and every scheduled-run folder "
                    "(test files are kept), then start a fresh schedule. Stop any running copy of this script first")
    a = ap.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)

    if a.test:
        do_run("test", None, TEST_N_SIMS, test=True)
        return

    if a.reset:
        import re
        gone = [p for p in OUT.iterdir() if re.fullmatch(r"\d{4}-\d{2}-\d{2}_\d{4}", p.name) and p.is_dir()]
        for p in gone:
            shutil.rmtree(p)
        for p in (STATE, HISTORY, RACE_HISTORY, WARNINGS_XLSX, OUT / "latest.html"):
            p.unlink(missing_ok=True)
        say(f"RESET: deleted the schedule, history, warnings workbook, latest.html and {len(gone)} run folder(s). Starting a fresh schedule.")

    st = load_state()
    if a.status:
        if st is None:
            print("No schedule yet: run `python final_forecast.py` to start it.")
        else:
            print_schedule(st)
            print("FINISHED." if st.get("finished") else f"Next run: {fmt_t(pending(st)[0])}" if pending(st) else "")
        return
    if a.report:
        rebuild_reports()
        return

    if st and st.get("finished"):
        say(f"The schedule finished with the final run ({fmt_t(FINAL_RUN)}). Nothing more to do.")
        return
    if st is None:
        if now() > FINAL_RUN + dt.timedelta(hours=1):
            say("It's past the final run time; nothing to schedule.")
            return
        st = {"anchor": now().isoformat(), "done_slots": [], "durations": {}, "created": now().isoformat()}
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
            say(f"FINISHED: the final run ({fmt_t(FINAL_RUN)}) is done. The schedule is complete; the script will not run again.")
            return
        due = [t for t in todo if t <= now()]
        if due:
            is_final = FINAL_RUN in due
            if len(due) > 1:
                say(f"{len(due)} run times are due ({', '.join(fmt_t(t) for t in due)}); doing ONE run for them.")
            kind = "final" if is_final else "scheduled"
            slot = due[-1].isoformat()
            try:
                do_run(kind, slot, N_SIMS)
            except Exception as e:  # never let one bad run kill the schedule
                say(f"RUN ERROR ({type(e).__name__}: {e}); the schedule continues.")
            st = load_state()
            st["done_slots"] = sorted(set(st["done_slots"]) | {t.isoformat() for t in due})
            st.setdefault("runs", []).append({"slot": slot, "finished": now().isoformat(), "kind": kind})
            save_state(st)
            continue
        nxt = todo[0]
        label = "FINAL run" if nxt == FINAL_RUN else "next run"
        left_runs = len(todo)
        say(f"RESTING. {label.capitalize()} at {fmt_t(nxt)} (in {fmt_td((nxt - now()).total_seconds())}); "
            f"{left_runs} run{'s' if left_runs != 1 else ''} left including the final one. Leave this window open.")
        while now() < nxt:
            time.sleep(min(STATUS_EVERY_S * 5, max((nxt - now()).total_seconds(), 1)))
            if now() < nxt:
                say(f"RESTING. {label.capitalize()} in {fmt_td((nxt - now()).total_seconds())} (at {fmt_t(nxt)}).")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        say("Stopped by you (Ctrl+C). Run `python final_forecast.py` again to resume the schedule; history is kept.")
