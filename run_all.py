"""
run_all.py — run every forecast model in the repo, then build an interactive HTML report comparing them.

This script is for COMPARING models. (The final election-day forecast/report will be a separate script.)

What it does
------------
1. Finds every model: any folder under Models/ that contains a `model.json` file (see README, "Adding a model").
2. Runs each model's notebook, then its testing notebook(s), headless, one after another. Notebooks are updated
   IN PLACE (exactly as if you had opened them and clicked Run All). If one model fails, the others still run.
3. Makes every model use the same date and simulation count: today's system date and 10,000 simulations.
   This is done through two environment variables (FORECAST_AS_OF, FORECAST_N_SIMS) that each notebook reads;
   when you run a notebook yourself they aren't set, so the notebook's own CONFIG is used.
4. Reads each model's standard output (Output/standard/summary.json, races.csv, seats.csv).
5. Writes an interactive HTML comparison:
      Comparisons/latest.html                    <- always the newest report
      Comparisons/runs/<YYYY-MM-DD_HHMM>/        <- archive: report.html + the data behind it
      Comparisons/history.csv                    <- one row per model per run (feeds the "history" chart)

Usage (from the repo root, with the same Python your Jupyter uses)
-----
    python run_all.py                       # run everything, build the report
    python run_all.py --only dadbod_swing   # run just some models (ids from model.json), report on all
    python run_all.py --report-only         # don't run anything; rebuild the report from existing outputs
    python run_all.py --as-of 2026-10-20    # backtest every model as of a date (default: today)

When models are added, renamed or removed: give the new model folder a model.json and the standard-export
cell (README, "Adding a model"). run_all.py itself does not need editing.
"""
import argparse
import datetime as dt
import html
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parent
MODELS_DIR = REPO / "Models"
OUT_DIR = REPO / "Comparisons"
DEFAULT_N_SIMS = 10_000
CELL_TIMEOUT = 1800 # seconds any single notebook cell may take

# ---------------------------------------------------------------------------------------------------
# Setup
# ---------------------------------------------------------------------------------------------------
PACKAGES = {"nbformat": "nbformat", "nbclient": "nbclient", "ipykernel": "ipykernel", "pandas": "pandas",
            "numpy": "numpy", "plotly": "plotly"} # import name -> pip name


def ensure_packages():
    """Install anything run_all.py needs that's missing (into the Python running this script)."""
    missing = []
    for mod, pip_name in PACKAGES.items():
        try:
            __import__(mod)
        except ImportError:
            missing.append(pip_name)
    if missing:
        print(f"Installing missing packages: {', '.join(missing)}")
        subprocess.check_call([sys.executable, "-m", "pip", "install", "--quiet", *missing])


def discover_models():
    """Every enabled model.json under Models/, sorted by its 'order'. Also lists notebooks no model.json mentions."""
    models, registered = [], set()
    for mj in sorted(MODELS_DIR.rglob("model.json")):
        if ".ipynb_checkpoints" in mj.parts:
            continue
        d = json.loads(mj.read_text(encoding="utf-8"))
        d["folder"] = mj.parent
        for key in ("id", "name", "notebook"):
            if key not in d:
                raise ValueError(f"{mj} is missing '{key}'")
        for nb in [d["notebook"], *d.get("testing_notebooks", [])]:
            registered.add((mj.parent / nb).resolve())
            if not (mj.parent / nb).exists():
                raise FileNotFoundError(f"{mj} lists {nb}, which doesn't exist in {mj.parent}")
        if d.get("enabled", True):
            models.append(d)
    ids = [m["id"] for m in models]
    dupes = {i for i in ids if ids.count(i) > 1}
    if dupes:
        raise ValueError(f"duplicate model ids in model.json files: {dupes}")
    unregistered = [p for p in MODELS_DIR.rglob("*.ipynb")
                    if ".ipynb_checkpoints" not in p.parts and p.resolve() not in registered]
    return sorted(models, key=lambda d: (d.get("order", 999), d["name"])), unregistered


# ---------------------------------------------------------------------------------------------------
# Running notebooks
# ---------------------------------------------------------------------------------------------------
def run_notebook(path):
    """Execute a notebook in its own folder and save it in place. Returns {ok, seconds, error}."""
    import nbformat
    from nbclient import NotebookClient
    from nbclient.exceptions import CellExecutionError
    if sys.platform == "win32": # Jupyter kernels on Windows need the selector event loop
        import asyncio
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    nb = nbformat.read(path, as_version=4)
    client = NotebookClient(nb, timeout=CELL_TIMEOUT, kernel_name="python3", resources={"metadata": {"path": str(path.parent)}})
    t0, err = time.time(), None
    try:
        client.execute()
    except CellExecutionError as e:
        err = f"{getattr(e, 'ename', 'Error')}: {getattr(e, 'evalue', str(e))}"[:500]
    except Exception as e: # kernel died, timeout, ...
        err = f"{type(e).__name__}: {e}"[:500]
    finally:
        nbformat.write(nb, path) # notebooks are updated in place (outputs kept even if a cell failed)
    return {"ok": err is None, "seconds": round(time.time() - t0, 1), "error": err}


def run_models(models, as_of, n_sims):
    os.environ["FORECAST_AS_OF"] = as_of
    os.environ["FORECAST_N_SIMS"] = str(n_sims)
    status = {}
    for m in models:
        print(f"\n=== {m['name']} ===")
        res = run_notebook(m["folder"] / m["notebook"])
        print(f"  model notebook: {'OK' if res['ok'] else 'FAILED - ' + res['error']} ({res['seconds']}s)")
        tests = []
        for tnb in m.get("testing_notebooks", []):
            tr = run_notebook(m["folder"] / tnb)
            tests.append({"notebook": tnb, **tr})
            print(f"  {tnb}: {'OK' if tr['ok'] else 'FAILED - ' + tr['error']} ({tr['seconds']}s)")
        status[m["id"]] = {"model": res, "testing": tests}
    return status


# ---------------------------------------------------------------------------------------------------
# Reading the standard outputs
# ---------------------------------------------------------------------------------------------------
def load_results(models, run_start, status):
    import pandas as pd
    out = []
    for m in models:
        std = m["folder"] / m.get("standard_output", "Output/standard")
        r = {"meta": m, "summary": None, "races": None, "seats": None, "checks": None,
             "status": status.get(m["id"]), "fresh": False}
        if (std / "summary.json").exists():
            r["summary"] = json.loads((std / "summary.json").read_text(encoding="utf-8"))
            r["races"] = pd.read_csv(std / "races.csv") if (std / "races.csv").exists() else None
            r["seats"] = pd.read_csv(std / "seats.csv") if (std / "seats.csv").exists() else None
            written = dt.datetime.fromtimestamp((std / "summary.json").stat().st_mtime)
            r["fresh"] = written >= run_start
        chk = m.get("testing_checks")
        if chk and (m["folder"] / chk).exists():
            c = pd.read_csv(m["folder"] / chk)
            r["checks"] = c["status"].value_counts().to_dict()
        out.append(r)
    return out


# ---------------------------------------------------------------------------------------------------
# The HTML report
# ---------------------------------------------------------------------------------------------------
# One base colour per model family; later variants of the same family get lighter shades + dashed lines.
PALETTE = {"Model 1": "#6B6B6B", "Ozempic": "#D9641E", "DadBod": "#1A6FB0"}
EXTRA = ["#2CA02C", "#9467BD", "#8C564B", "#E377C2", "#17BECF", "#BCBD22"]


def lighten(hex_color, amount):
    h = hex_color.lstrip("#")
    rgb = [int(h[i:i + 2], 16) for i in (0, 2, 4)]
    return "#" + "".join(f"{int(c + (255 - c) * amount):02X}" for c in rgb)


def assign_styles(results):
    """{model name: (colour, dash)}: family colour, variants within a family get lighter + dashed."""
    styles, seen, extra = {}, {}, 0
    for r in results:
        fam = r["meta"].get("family") or r["meta"]["name"]
        if fam not in PALETTE:
            PALETTE[fam] = EXTRA[extra % len(EXTRA)]
            extra += 1
        k = seen.get(fam, 0)
        seen[fam] = k + 1
        styles[r["meta"]["name"]] = (lighten(PALETTE[fam], 0.25 * min(k, 2) + (0.2 if k else 0)), ["solid", "dash", "dot"][min(k, 2)])
    return styles


def esc(x):
    return html.escape("" if x is None else str(x))


def fmt_pct(x):
    return "—" if x is None or x != x else f"{100 * x:.1f}%"


def table(headers, rows, cls="sortable"):
    """rows: list of lists of (display, sort_value, style)."""
    th = "".join(f"<th>{esc(h)}</th>" for h in headers)
    trs = []
    for row in rows:
        tds = "".join(f'<td data-sort="{esc(sv)}" style="{st}">{d}</td>' for d, sv, st in row)
        trs.append(f"<tr>{tds}</tr>")
    return f'<table class="{cls}"><thead><tr>{th}</tr></thead><tbody>{"".join(trs)}</tbody></table>'


def prob_style(p):
    """Background colour for a probability: red (R favoured) -> white -> blue (D favoured)."""
    if p is None or p != p:
        return ""
    if p >= 0.5:
        a = (p - 0.5) * 2
        return f"background-color: rgba(26,111,176,{0.75 * a:.2f}); color: {'#fff' if a > 0.6 else '#111'}"
    a = (0.5 - p) * 2
    return f"background-color: rgba(200,49,43,{0.75 * a:.2f}); color: {'#fff' if a > 0.6 else '#111'}"


def build_report(results, run_info, history):
    import numpy as np
    import pandas as pd
    import plotly.graph_objects as go
    from plotly.offline import get_plotlyjs

    ok = [r for r in results if r["summary"] is not None]
    names = [r["meta"]["name"] for r in ok]
    styles = assign_styles(ok)
    colors = {n: c for n, (c, _) in styles.items()}
    dashes = {n: d for n, (_, d) in styles.items()}
    figs = []

    def add(fig, title, note=""):
        fig.update_layout(template="plotly_white", margin=dict(l=60, r=30, t=50, b=50), title=dict(text=title, x=0),
                          font=dict(family="Inter, Segoe UI, Helvetica, Arial, sans-serif", size=13))
        figs.append((fig.to_html(full_html=False, include_plotlyjs=False, config={"displaylogo": False}), note))
        return len(figs) - 1

    # Kalshi reference (from whichever model recorded it)
    k_ctrl = next((r["summary"].get("kalshi_p_control") for r in ok if r["summary"].get("kalshi_p_control") is not None), None)
    k_seats = next((r["summary"].get("kalshi_expected_seats") for r in ok if r["summary"].get("kalshi_expected_seats") is not None), None)
    k_races = None
    for r in ok:
        if r["races"] is not None and r["races"]["kalshi_p"].notna().any():
            k_races = r["races"].set_index("state")["kalshi_p"]
            break

    # ---- 1. headline bar ----
    fig = go.Figure()
    p51 = [r["summary"]["p_d_51"] for r in ok]
    fig.add_bar(x=names, y=[100 * p for p in p51], marker_color=[colors[n] for n in names],
                marker_pattern_shape=["" if dashes[n] == "solid" else "/" for n in names],
                text=[f"{100 * p:.1f}%" for p in p51], textposition="outside",
                hovertemplate="%{x}<br>P(D ≥ 51) = %{y:.1f}%<extra></extra>")
    if k_ctrl is not None:
        fig.add_hline(y=100 * k_ctrl, line_dash="dash", line_color="#444",
                      annotation_text=f"Kalshi {100 * k_ctrl:.1f}%", annotation_position="top left")
    fig.add_hline(y=50, line_color="#bbb", line_width=1)
    fig.update_yaxes(title="P(Democrats ≥ 51 seats), %", range=[0, 100])
    i_head = add(fig, "Chance Democrats control the Senate (51+ seats)")

    # ---- 2. seat distributions ----
    fig = go.Figure()
    for r in ok:
        s = r["seats"]
        if s is None:
            continue
        n = r["meta"]["name"]
        fig.add_scatter(x=s["dem_seats"], y=100 * s["share"], mode="lines+markers", name=n,
                        line=dict(color=colors[n], width=2.5, dash=dashes[n]),
                        hovertemplate=f"{n}<br>%{{x}} D seats: %{{y:.1f}}%<extra></extra>")
    fig.add_vline(x=50.5, line_color="#444", line_width=1, annotation_text="51 = control", annotation_position="top right")
    fig.update_xaxes(title="Democratic seats (incl. caucusing independents)", dtick=1)
    fig.update_yaxes(title="Share of simulations, %")
    i_seats = add(fig, "Seat distributions")

    # ---- race matrix ----
    P = pd.DataFrame({r["meta"]["name"]: r["races"].set_index("state")["p_dem"] for r in ok if r["races"] is not None})
    M = pd.DataFrame({r["meta"]["name"]: r["races"].set_index("state")["margin"] for r in ok if r["races"] is not None})
    if k_races is not None:
        P["Kalshi"] = k_races
    model_cols = [c for c in P.columns if c != "Kalshi"]
    order = P[model_cols].mean(axis=1).sort_values(ascending=False).index
    P, M = P.loc[order], M.reindex(order)

    # ---- 3. heatmap of P(D win) ----
    fig = go.Figure(go.Heatmap(z=100 * P.values, x=list(P.columns), y=list(P.index), zmin=0, zmax=100,
                               colorscale=[[0, "#C8312B"], [0.5, "#F7F7F7"], [1, "#1A6FB0"]],
                               text=[[f"{100 * v:.0f}" if v == v else "" for v in row] for row in P.values],
                               texttemplate="%{text}", colorbar=dict(title="P(D) %"),
                               hovertemplate="%{y} — %{x}<br>P(Dem/Ind win) = %{z:.0f}%<extra></extra>"))
    fig.update_layout(height=max(500, 24 * len(P) + 120))
    fig.update_yaxes(autorange="reversed")
    i_heat = add(fig, "P(Democrat or independent wins), by race and model")

    # ---- 4. disagreement ----
    spread = (P[model_cols].max(axis=1) - P[model_cols].min(axis=1)).sort_values(ascending=False)
    top = spread[spread > 0.05].head(12).index.tolist() or spread.head(8).index.tolist()
    fig = go.Figure()
    for n in model_cols:
        fig.add_scatter(x=100 * P.loc[top, n], y=top, mode="markers", name=n,
                        marker=dict(size=12, color=colors.get(n, "#999"), symbol="circle" if dashes.get(n) == "solid" else "diamond",
                                    line=dict(width=1, color="#333")),
                        hovertemplate=f"{n}<br>%{{y}}: %{{x:.0f}}%<extra></extra>")
    if "Kalshi" in P:
        fig.add_scatter(x=100 * P.loc[top, "Kalshi"], y=top, mode="markers", name="Kalshi",
                        marker=dict(size=12, symbol="x", color="#222"), hovertemplate="Kalshi<br>%{y}: %{x:.0f}%<extra></extra>")
    fig.add_vline(x=50, line_color="#bbb")
    fig.update_xaxes(title="P(Dem/Ind win), %", range=[-2, 102])
    fig.update_yaxes(autorange="reversed")
    fig.update_layout(height=max(400, 40 * len(top) + 120))
    i_dis = add(fig, "Races where the models disagree most")

    # ---- 5. difference from the model average ----
    avg = P[model_cols].mean(axis=1)
    D = P[model_cols].sub(avg, axis=0)
    fig = go.Figure(go.Heatmap(z=100 * D.values, x=model_cols, y=list(D.index), zmid=0,
                               colorscale=[[0, "#C8312B"], [0.5, "#F7F7F7"], [1, "#1A6FB0"]],
                               text=[[f"{100 * v:+.0f}" if v == v else "" for v in row] for row in D.values], texttemplate="%{text}",
                               colorbar=dict(title="pts vs avg"),
                               hovertemplate="%{y} — %{x}<br>%{z:+.0f} pts vs the model average<extra></extra>"))
    fig.update_layout(height=max(500, 24 * len(D) + 120))
    fig.update_yaxes(autorange="reversed")
    i_diff = add(fig, "Each model vs the average of all models (P(D win), points)")
    seat_gap = D.sum(axis=0) # expected-seat difference vs the average

    # ---- 6. margins in competitive races ----
    comp = [s for s in order if (P.loc[s, model_cols].between(0.1, 0.9).any()) or
            ("Kalshi" in P and 0.1 <= (P.loc[s, "Kalshi"] if P.loc[s, "Kalshi"] == P.loc[s, "Kalshi"] else 0) <= 0.9)]
    fig = go.Figure()
    for n in M.columns:
        fig.add_scatter(x=M.loc[comp, n], y=comp, mode="markers", name=n,
                        marker=dict(size=11, color=colors.get(n, "#999"), symbol="circle" if dashes.get(n) == "solid" else "diamond",
                                    line=dict(width=1, color="#333")),
                        hovertemplate=f"{n}<br>%{{y}}: %{{x:+.1f}} pts<extra></extra>")
    fig.add_vline(x=0, line_color="#444", line_width=1)
    fig.update_xaxes(title="Projected margin, D − R (points)")
    fig.update_yaxes(autorange="reversed")
    fig.update_layout(height=max(400, 32 * len(comp) + 120))
    i_marg = add(fig, "Projected margins in competitive races")

    # ---- 7. history ----
    i_hist = None
    if history is not None and len(history):
        h = history[history["status"] == "OK"].copy()
        h["run_at"] = pd.to_datetime(h["run_at"])
        fig = go.Figure()
        for i, (n, g) in enumerate(h.groupby("model", sort=False)):
            g = g.sort_values("run_at")
            fig.add_scatter(x=g["run_at"], y=100 * g["p_d_51"], mode="lines+markers", name=n,
                            line=dict(color=colors.get(n, EXTRA[i % len(EXTRA)]), dash=dashes.get(n, "solid")),
                            hovertemplate=f"{n}<br>%{{x|%b %d %H:%M}}: %{{y:.1f}}%<extra></extra>")
        if "kalshi_p_control" in h:
            k = h.dropna(subset=["kalshi_p_control"]).groupby("run_id").first().sort_values("run_at")
            if len(k):
                fig.add_scatter(x=k["run_at"], y=100 * k["kalshi_p_control"], mode="lines+markers", name="Kalshi",
                                line=dict(color="#222", dash="dash"))
        fig.update_yaxes(title="P(D ≥ 51), %", range=[0, 100])
        if h["run_at"].nunique() == 1: # a single run: give the time axis some room
            t = h["run_at"].iloc[0]
            fig.update_xaxes(range=[t - pd.Timedelta(days=1), t + pd.Timedelta(days=1)])
        i_hist = add(fig, "History: every run_all.py run")

    # ---- tables ----
    status_rows = []
    for r in results:
        m, st, s = r["meta"], r["status"], r["summary"]
        if st is None:
            mstat, secs, err = ("not run (report only)" if run_info["report_only"] else "skipped (--only)"), "", ""
        else:
            mstat = "OK" if st["model"]["ok"] else "FAILED"
            secs = st["model"]["seconds"] + sum(t["seconds"] for t in st["testing"])
            err = st["model"]["error"] or "; ".join(f"{t['notebook']}: {t['error']}" for t in st["testing"] if t["error"])
        tests = ("—" if not m.get("testing_notebooks") else
                 ("OK" if st and all(t["ok"] for t in st["testing"]) else ("FAILED" if st else "not run")))
        chk = r["checks"] or {}
        chk_txt = " / ".join(f"{chk.get(k, 0)} {k}" for k in ("PASS", "WARN", "FAIL")) if chk else "—"
        src = (s or {}).get("sources") or {}
        cached = [k for k, v in src.items() if isinstance(v, str) and v.startswith("cache")]
        src_txt = ("all live" if src and not cached and any(v == "live" for v in src.values())
                   else (f"{len(cached)} of {len(src)} from saved copy" if cached else "—"))
        fresh = "" if r["fresh"] else (f" (results from {s['run_at']})" if s else " (no results)")
        sty = "color:#2E7D32;font-weight:600" if mstat == "OK" else ("color:#C62828;font-weight:600" if mstat == "FAILED" else "")
        status_rows.append([(esc(m["name"]), m["name"], ""), (esc(mstat) + esc(fresh), mstat, sty), (esc(secs), secs, ""),
                            (esc(tests), tests, ""), (esc(chk_txt), chk.get("FAIL", 0), ""), (esc(src_txt), src_txt, ""),
                            (esc(err), err, "color:#C62828")])

    head_rows = []
    for r in ok:
        s, n = r["summary"], r["meta"]["name"]
        head_rows.append([(f'<span class="dot" style="background:{colors[n]}"></span>{esc(n)}', n, ""),
                          (fmt_pct(s["p_d_51"]), s["p_d_51"], prob_style(s["p_d_51"])),
                          (f"{s['exp_d_seats']:.1f}", s["exp_d_seats"], ""), (f"{s.get('median_d_seats', float('nan')):.0f}", s.get("median_d_seats"), ""),
                          (f"{s.get('p10', float('nan')):.0f}–{s.get('p90', float('nan')):.0f}", s.get("p10"), ""),
                          (f"{seat_gap.get(n, float('nan')):+.2f}", seat_gap.get(n), ""),
                          (esc(s.get("as_of")), s.get("as_of"), ""), (f"{int(s.get('n_sims', 0)):,}", s.get("n_sims"), ""),
                          (esc(s.get("run_at")), s.get("run_at"), "")])
    if k_ctrl is not None:
        head_rows.append([("<i>Kalshi (reference)</i>", "zzz", ""), (fmt_pct(k_ctrl), k_ctrl, prob_style(k_ctrl)),
                          (f"{k_seats:.1f}" if k_seats is not None else "—", k_seats, ""), ("—", "", ""), ("—", "", ""),
                          ("—", "", ""), ("", "", ""), ("", "", ""), ("", "", "")])

    race_rows = []
    for st in P.index:
        row = [(esc(st), st, "")]
        for c in P.columns:
            v = P.loc[st, c]
            row.append((fmt_pct(v) if v == v else "—", v if v == v else -1, prob_style(v)))
        row.append((f"{100 * spread.get(st, 0):.0f}", spread.get(st, 0), ""))
        race_rows.append(row)

    keys = []
    for r in ok:
        for k in (r["summary"].get("key_settings") or {}):
            if k not in keys:
                keys.append(k)
    set_rows = [[(f"<b>{esc(k)}</b>", k, "")] + [(esc((r["summary"].get("key_settings") or {}).get(k, "—")), "", "") for r in ok] for k in keys]

    reg_rows = [[(esc(r["meta"]["name"]), r["meta"]["name"], ""), (f"<code>{esc(r['meta']['id'])}</code>", r["meta"]["id"], ""),
                 (f"<code>{esc(Path(r['meta']['folder']).relative_to(REPO).as_posix())}/{esc(r['meta']['notebook'])}</code>", "", ""),
                 (esc(", ".join(r["meta"].get("testing_notebooks", [])) or "—"), "", ""), (esc(r["meta"].get("description", "")), "", "")]
                for r in results]

    # ---- assemble ----
    def fig_block(i):
        if i is None:
            return ""
        return f'<div class="fig">{figs[i][0]}</div>'

    warn = ""
    if run_info["unregistered"]:
        warn = ('<div class="warn"><b>Notebooks not registered in any model.json</b> (not run, not compared): '
                + ", ".join(f"<code>{esc(p)}</code>" for p in run_info["unregistered"]) + "</div>")
    failed = [r["meta"]["name"] for r in results if r["status"] and not r["status"]["model"]["ok"]]
    if failed:
        warn += f'<div class="warn bad"><b>Failed this run:</b> {esc(", ".join(failed))}. Their rows show their last successful results (if any).</div>'

    title = "Senate Forecast — Model Comparison"
    css = """
    :root{--bg:#fff;--fg:#1d1d1f;--muted:#666;--line:#e3e3e3;--card:#fafafa}
    body{margin:0;background:var(--bg);color:var(--fg);font:15px/1.5 Inter,'Segoe UI',Helvetica,Arial,sans-serif}
    main{max-width:1180px;margin:0 auto;padding:24px 16px 64px}
    h1{font-size:26px;margin:0 0 4px} h2{font-size:20px;margin:40px 0 8px;border-bottom:1px solid var(--line);padding-bottom:6px}
    .sub{color:var(--muted);margin:0 0 16px} p.note{color:var(--muted);margin:4px 0 12px}
    nav a{margin-right:14px;color:#1A6FB0;text-decoration:none;font-size:14px}
    table{border-collapse:collapse;width:100%;font-size:13.5px;margin:8px 0}
    th,td{border-bottom:1px solid var(--line);padding:6px 8px;text-align:left;vertical-align:top}
    th{background:var(--card);cursor:pointer;position:sticky;top:0;white-space:nowrap} th:hover{background:#eef3f8}
    td{white-space:nowrap} td:last-child{white-space:normal}
    .wrap td{white-space:normal}
    .scroll{overflow-x:auto} .fig{margin:8px 0 4px}
    .dot{display:inline-block;width:10px;height:10px;border-radius:50%;margin-right:6px}
    .warn{background:#FFF8E1;border:1px solid #F2D27A;padding:10px 12px;border-radius:6px;margin:10px 0}
    .warn.bad{background:#FDECEA;border-color:#F0B4AE}
    code{background:#f2f2f2;padding:1px 4px;border-radius:3px;font-size:12.5px}
    .kpis{display:flex;gap:12px;flex-wrap:wrap;margin:10px 0}
    .kpi{flex:1 1 200px;background:var(--card);border:1px solid var(--line);border-radius:8px;padding:10px 14px}
    .kpi b{font-size:22px;display:block}
    """
    js = """
    document.querySelectorAll('table.sortable').forEach(t=>{
      t.querySelectorAll('th').forEach((th,i)=>{let asc=false;th.addEventListener('click',()=>{
        const rows=[...t.tBodies[0].rows];asc=!asc;
        rows.sort((a,b)=>{const x=a.cells[i].dataset.sort,y=b.cells[i].dataset.sort;
          const nx=parseFloat(x),ny=parseFloat(y);
          const c=(!isNaN(nx)&&!isNaN(ny))?nx-ny:String(x).localeCompare(String(y));return asc?c:-c});
        rows.forEach(r=>t.tBodies[0].appendChild(r));});});});
    """
    best = max(ok, key=lambda r: r["summary"]["p_d_51"]) if ok else None
    worst = min(ok, key=lambda r: r["summary"]["p_d_51"]) if ok else None
    kpis = ""
    if ok:
        kpis = (f'<div class="kpis"><div class="kpi">Models compared<b>{len(ok)}</b></div>'
                f'<div class="kpi">P(D ≥ 51) range<b>{fmt_pct(worst["summary"]["p_d_51"])} – {fmt_pct(best["summary"]["p_d_51"])}</b></div>'
                f'<div class="kpi">Average of models<b>{fmt_pct(float(np.mean(p51)))}</b></div>'
                f'<div class="kpi">Kalshi<b>{fmt_pct(k_ctrl)}</b></div></div>')
    body = f"""
<main>
<h1>{title}</h1>
<p class="sub">Run {esc(run_info['run_at'])} · data as of {esc(run_info['as_of'])} · {run_info['n_sims']:,} simulations per model ·
generated by <code>run_all.py</code>. Comparison only — not the final forecast. Click any table header to sort; hover charts for details.</p>
<nav><a href="#status">Run status</a><a href="#headline">Headline</a><a href="#seats">Seats</a><a href="#races">Races</a>
<a href="#disagree">Disagreements</a><a href="#margins">Margins</a><a href="#settings">Settings</a><a href="#history">History</a><a href="#models">Models</a></nav>
{warn}
{kpis}
<h2 id="status">Run status</h2>
<p class="note">Each model notebook and its testing notebook(s) were run in place. "saved copy used" means a data source couldn't be reached and the model fell back to its last saved download. Testing checks are from each model's Model Testing notebook.</p>
<div class="scroll">{table(["Model", "Status", "Seconds", "Testing notebook", "Checks", "Data sources", "Error"], status_rows)}</div>

<h2 id="headline">Headline numbers</h2>
<p class="note"><b>P(D ≥ 51)</b>: share of simulated elections where Democrats (incl. caucusing independents) hold 51+ seats. <b>Mean seats</b>: predicted Democratic seats. <b>vs avg</b>: expected seats above/below the average of all models (sum over races of the model's P(win) minus the average P(win)).</p>
{fig_block(i_head)}
<div class="scroll">{table(["Model", "P(D ≥ 51)", "Mean D seats", "Median", "80% range", "Seats vs avg", "As of", "Simulations", "Run at"], head_rows)}</div>

<h2 id="seats">Seat distributions</h2>
<p class="note">How often each seat total comes up. The vertical line is the 51-seat control threshold. Wider curves = more uncertainty.</p>
{fig_block(i_seats)}

<h2 id="races">Race by race</h2>
<p class="note">P(Democrat or independent wins) in every race, by model, with Kalshi for reference. Sorted from most to least Democratic (average of models). <b>Spread</b> = largest minus smallest model, in points.</p>
{fig_block(i_heat)}
<div class="scroll">{table(["State", *P.columns, "Spread (pts)"], race_rows)}</div>

<h2 id="disagree">Where the models disagree</h2>
<p class="note">The races with the largest spread between models, and how far each model sits from the average of all models. Races where one model is far from the others usually trace back to a single setting (fundamentals type, poll reliability, Kalshi weight); see each model's README.</p>
{fig_block(i_dis)}
{fig_block(i_diff)}

<h2 id="margins">Projected margins</h2>
<p class="note">Each model's projected margin (Democrat minus Republican, points) in races any model or Kalshi rates between 10% and 90%.</p>
{fig_block(i_marg)}

<h2 id="settings">Key settings, side by side</h2>
<p class="note">Reported by each model's standard export (<code>key_settings</code> in <code>Output/standard/summary.json</code>).</p>
<div class="scroll wrap">{table(["Setting", *names], set_rows, cls="")}</div>

<h2 id="history">History</h2>
<p class="note">P(D ≥ 51) from every <code>run_all.py</code> run (<code>Comparisons/history.csv</code>).</p>
{fig_block(i_hist) if i_hist is not None else '<p class="note">History starts with this run.</p>'}

<h2 id="models">Registered models</h2>
<p class="note">Every folder under <code>Models/</code> with a <code>model.json</code>. To add a model, see "Adding a model" in the repo README; <code>run_all.py</code> needs no changes.</p>
<div class="scroll wrap">{table(["Model", "id", "Notebook", "Testing", "Description"], reg_rows)}</div>
</main>"""
    return (f'<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">'
            f"<title>Model Comparison</title><style>{css}</style><script>{get_plotlyjs()}</script></head>"
            f"<body>{body}<script>{js}</script></body></html>")


# ---------------------------------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------------------------------
def main():
    ap = argparse.ArgumentParser(description="Run every registered model and build an interactive comparison report.")
    ap.add_argument("--only", help="comma-separated model ids to run (others are still included in the report)")
    ap.add_argument("--report-only", action="store_true", help="don't run notebooks; rebuild the report from existing outputs")
    ap.add_argument("--as-of", default=dt.date.today().isoformat(), help="date every model uses (default: today)")
    ap.add_argument("--n-sims", type=int, default=DEFAULT_N_SIMS, help="simulations per model (default 10,000)")
    args = ap.parse_args()

    ensure_packages()
    import pandas as pd

    models, unregistered = discover_models()
    print(f"Found {len(models)} models: {', '.join(m['id'] for m in models)}")
    for p in unregistered:
        print(f"  WARNING: {p.relative_to(REPO)} is not listed in any model.json (won't be run or compared)")

    run_start = dt.datetime.now()
    run_id = run_start.strftime("%Y-%m-%d_%H%M")
    status = {}
    if not args.report_only:
        to_run = models
        if args.only:
            wanted = {s.strip() for s in args.only.split(",")}
            unknown = wanted - {m["id"] for m in models}
            if unknown:
                sys.exit(f"Unknown model id(s): {unknown}. Known: {[m['id'] for m in models]}")
            to_run = [m for m in models if m["id"] in wanted]
        status = run_models(to_run, args.as_of, args.n_sims)

    results = load_results(models, run_start, status)

    # ---- history + archive ----
    OUT_DIR.mkdir(exist_ok=True)
    hist_path = OUT_DIR / "history.csv"
    rows = []
    for r in results:
        if r["summary"] is None or (not args.report_only and not r["fresh"]):
            continue
        s = r["summary"]
        rows.append({"run_id": run_id, "run_at": run_start.strftime("%Y-%m-%d %H:%M"), "as_of": s.get("as_of"),
                     "model_id": r["meta"]["id"], "model": r["meta"]["name"], "p_d_51": s["p_d_51"], "exp_d_seats": s["exp_d_seats"],
                     "p10": s.get("p10"), "p90": s.get("p90"), "n_sims": s.get("n_sims"), "kalshi_p_control": s.get("kalshi_p_control"),
                     "status": "OK"})
    history = pd.read_csv(hist_path) if hist_path.exists() else pd.DataFrame()
    if rows and not args.report_only: # report-only runs don't add history rows
        history = pd.concat([history, pd.DataFrame(rows)], ignore_index=True)
        history.to_csv(hist_path, index=False)

    run_info = {"run_at": run_start.strftime("%Y-%m-%d %H:%M"), "as_of": args.as_of, "n_sims": args.n_sims,
                "report_only": args.report_only, "unregistered": [p.relative_to(REPO).as_posix() for p in unregistered]}
    report = build_report(results, run_info, history if len(history) else None)

    arch = OUT_DIR / "runs" / run_id
    arch.mkdir(parents=True, exist_ok=True)
    (arch / "report.html").write_text(report, encoding="utf-8")
    (OUT_DIR / "latest.html").write_text(report, encoding="utf-8")
    for r in results: # archive the data behind the report
        std = r["meta"]["folder"] / r["meta"].get("standard_output", "Output/standard")
        if std.exists():
            shutil.copytree(std, arch / "standard" / r["meta"]["id"], dirs_exist_ok=True)
    json.dump({"run_info": run_info, "status": status,
               "models": [{"id": r["meta"]["id"], "name": r["meta"]["name"], "fresh": r["fresh"]} for r in results]},
              open(arch / "run_status.json", "w"), indent=2, default=str)

    n_ok = sum(1 for s in status.values() if s["model"]["ok"])
    print(f"\n{'Report rebuilt' if args.report_only else f'{n_ok}/{len(status)} models ran OK'}.")
    print(f"Report: {OUT_DIR / 'latest.html'}\nArchive: {arch}")
    if any(not s["model"]["ok"] for s in status.values()):
        sys.exit(1)


if __name__ == "__main__":
    main()
