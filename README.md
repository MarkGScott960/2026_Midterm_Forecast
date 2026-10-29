# 2026 Midterm Forecast — Team 5

Forecasting the 2026 U.S. Senate: **the chance Democrats hold at least 51 seats** and **how many seats they're likely to win**. The repo holds several competing models, a script that runs and compares them all (`run_all.py`), and, later, a separate script for the final election-day forecast.

## Repo layout

```
2026_Midterm_Forecast/
├── README.md                     <- this file
├── run_all.py                    <- runs every model + builds the interactive comparison report
├── Comparisons/                  <- created by run_all.py
│   ├── latest.html                   newest comparison report (open in any browser)
│   ├── history.csv                   one row per model per run
│   └── runs/<YYYY-MM-DD_HHMM>/       archive of every run: report.html, run_status.json, each model's standard output
├── Data/                         <- shared inputs
│   ├── pres_2024_results.csv         2024 presidential result by state (certified)
│   ├── votehub_pollster_scorecards.csv  VoteHub pollster grades, error, house effect (+ name aliases)
│   ├── leans_and_regions.csv         partisan lean + Census region per state
│   └── Midterm_Polls.xlsx, National_Polls.xlsx, *.docx   original course materials (Model 1 only; no longer updated)
├── Models/
│   ├── Model_Full_Configs/           Model 1  (model.json, notebook, README, Output/)
│   ├── Model_Ozempic/                Model 2  (Ozempic_Swing/, Ozempic_Literal/, README, Data_Cache/)
│   └── DadBod_Model/                 Model 3  (DadBod_Swing/, DadBod_Literal/, README, Data_Cache/)
└── Sample Code/                  <- the course's sample notebook
```

## The models

| Model | Folder | In one line | README |
|---|---|---|---|
| **Model 1 — Full Configs** | `Models/Model_Full_Configs` | Bayesian model on the course spreadsheet polls; ~90 settings | `Models/Model_Full_Configs/README.md` |
| **Ozempic — Swing / Literal** | `Models/Model_Ozempic/` | Slim: VoteHub polls (last 28 days), fixed polls : fundamentals : Kalshi = 10 : 5 : 1 | `Models/Model_Ozempic/README.md` |
| **DadBod — Swing / Literal** | `Models/DadBod_Model/` | Ozempic + poll reliability, flooding penalty, house effects, correlated errors, Kalshi national averages, automatic Kalshi search, separate Model Testing notebook | `Models/DadBod_Model/README.md` |
| **Pray_For_The_Floor** | `Models/Pray_For_The_Floor` | Model 1's Bayesian model on VoteHub polls + Kalshi as a third Bayesian input, random grades for ungraded pollsters every simulation, DadBod's controls | `Models/Pray_For_The_Floor/README.md` |
| **Rylyn (Event Edition)** | `Models/Rylyn_Model` | Rylyn's starter-notebook model on the Oct 15 spreadsheet polls, plus opinion events, voting-access changes and a House map module | `Models/Rylyn_Model/README.md` |



*Swing* and *Literal* differ only in the "fundamentals" (the no-polls expectation for each race); each model's README explains the difference. Every model notebook starts with an **install** cell. Run it once per computer.

---

## `run_all.py` — run and compare every model

**What it does**
1. **Finds every model:** any folder under `Models/` with a `model.json` file.
2. **Runs each model notebook, then its testing notebook(s),** headless, one after another. Notebooks are **updated in place**, exactly as if you'd opened them and clicked *Run All*, so you can open any of them afterwards to see the results. If one model fails, the rest still run, and the failure is shown in the report.
3. **Makes every model use the same settings for a fair comparison:** **today's system date** and **10,000 simulations**. It does this through two environment variables (`FORECAST_AS_OF`, `FORECAST_N_SIMS`) that each notebook reads in its "Shared settings from run_all.py" cell. When you run a notebook yourself these aren't set, so the notebook's own CONFIG is used. Each model downloads its own data, a few minutes apart.
4. **Reads each model's standard output** (`Output/standard/`, see below) and builds an **interactive HTML report**. Hover over charts for details and click table headers to sort. The report contains:
   - run status: OK/FAILED, runtime, testing results (PASS/WARN/FAIL), and whether each model's data was live or a saved copy
   - headline numbers vs Kalshi
   - overlaid seat distributions
   - a race-by-race heatmap and table
   - where the models disagree, and how far each model sits from the average of all models
   - projected margins in competitive races
   - key settings side by side
   - history across runs
   - the registered models
5. **Archives everything:** `Comparisons/latest.html` is always the newest report. Each run is also saved to `Comparisons/runs/<date_time>/` with the report, the run status and a copy of every model's standard output, and appended to `Comparisons/history.csv`.

**Usage** (from the repo root, with the **same Python your Jupyter uses**):
```bash
python run_all.py                        # run every model + testing notebook, build the report (~1-2 min)
python run_all.py --only dadbod_swing    # run only some models (ids from model.json); the report still shows all
python run_all.py --report-only          # rebuild the report from existing outputs without running anything
python run_all.py --as-of 2026-10-20     # backtest every model as of an earlier date
python run_all.py --n-sims 20000         # change the shared number of simulations
```
It installs anything it needs that's missing (`nbformat`, `nbclient`, `ipykernel`, `pandas`, `numpy`, `plotly`). The report embeds its charting library, so it opens offline and can be emailed as a single file (about 5 MB).

`run_all.py` is for **comparing models** only. The final election-day forecast and report will be a separate script, which can reuse the same standard outputs.

> ### ⚠️ Keep this up to date as models change
> `run_all.py` finds models automatically from their `model.json` files, so **you don't edit `run_all.py` when models are added**. But every time a model is **added, renamed, moved or retired**, update:
> 1. that model's **`model.json`**: notebook name, testing notebooks, order; set `"enabled": false` to retire a model without deleting it
> 2. the model's **standard-export cell**, if its outputs change (see below)
> 3. the **"The models" table** in this README
>
> `run_all.py` prints a warning, and the report shows a box, for any notebook under `Models/` that no `model.json` mentions, so nothing is silently left out.

---

## Adding a model

A new model needs three things. Copying them from a DadBod variant is the quickest way.

### 1. A `model.json` in the model's folder
```json
{
  "id": "newmodel_swing",
  "name": "New Model (Swing)",
  "family": "New Model",
  "variant": "Swing",
  "order": 40,
  "notebook": "newmodel_swing.ipynb",
  "testing_notebooks": ["Model Testing.ipynb"],
  "description": "One line on what makes this model different.",
  "standard_output": "Output/standard",
  "testing_checks": "Output/testing/checks.csv",
  "enabled": true
}
```

| Field | Meaning |
|---|---|
| `id` | Short unique name, used with `run_all.py --only` |
| `name` | Name shown in the report |
| `family` | Models in the same family share a colour; variants get lighter shades and dashed lines |
| `order` | Position in the report (Model 1 = 10, Ozempic = 20s, DadBod = 30s) |
| `notebook` | The model notebook, relative to this folder |
| `testing_notebooks` | Notebooks run after the model (e.g. Model Testing); `[]` if none |
| `standard_output` | Where the standard files are written (keep `Output/standard`) |
| `testing_checks` | Optional CSV with a `status` column (PASS/WARN/FAIL) to summarise in the report; `null` if none |
| `enabled` | `false` = skip this model without deleting it |

### 2. The shared-settings cell, right after CONFIG
```python
import os
if os.environ.get("FORECAST_AS_OF"):          # set only by run_all.py
    CONFIG["AS_OF_DATE"] = os.environ["FORECAST_AS_OF"]
if os.environ.get("FORECAST_N_SIMS"):
    CONFIG["N_SIMS"] = int(os.environ["FORECAST_N_SIMS"])
```

### 3. The standard-export cell, at the end of the model notebook
It writes three files to `Output/standard/`. `run_all.py` reads only these:

| File | Contents |
|---|---|
| `summary.json` | `model`, `variant`, `run_at`, `as_of`, `p_d_51`, `exp_d_seats`, `median_d_seats`, `p10`, `p90`, `n_sims`, `kalshi_p_control` (or null), `kalshi_expected_seats` (or null), `sources` (`{name: "live" or "cache (...)"}`), `key_settings` (`{label: short text}`, shown side by side in the report; reuse the existing labels where they apply) |
| `races.csv` | one row per race: `state`, `p_dem` (P Democrat/independent wins), `margin` (D − R, points), `sd`, `kalshi_p` (or blank), `n_polls` |
| `seats.csv` | `dem_seats`, `share` (share of simulations with that many Democratic seats) |

That's all. The next `python run_all.py` picks the model up automatically.

---

## Running the final forecast on election day (9 AM, Nov 3)

The final forecast script is still to be built. When we schedule it, it will need:
1. The script itself, which executes the chosen model(s) the same way `run_all.py` does.
2. A **Windows Task Scheduler** task running it with the same Python Jupyter uses (e.g. `C:\...\python.exe final_forecast.py`), with the repo folder as the "Start in" directory.
3. The computer **awake and online at 9 AM** ("Wake the computer to run this task").
4. A timestamped archive of the output, so the published 9 AM numbers are preserved exactly.
