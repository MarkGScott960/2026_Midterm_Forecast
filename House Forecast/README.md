# House Forecast: `House_Model` + `house_forecasts.py`

The House version of Most_Magnificent_Model. It borrows the Senate model's data sources and assumptions, stretches them across all 435 districts, and runs on the same schedule with the same kind of dashboard. Same recipe, much bigger batch.

```
python house_forecasts.py # start (or resume) the schedule: a run now, every 3 h, final run 9:00 AM Tue Nov 3
python house_forecasts.py --once  # one full run now (100,000 simulations), saved to the history
python house_forecasts.py --test  # quick 1,000-simulation run -> Forecasts/test_<datetime>.html (history untouched)
python house_forecasts.py --status  # show the schedule
python house_forecasts.py --report  # rebuild every saved dashboard with the current code (no model run)
python house_forecasts.py --reset # delete the schedule, history and run folders (tests kept)
python house_model.py # the model alone, CONFIG as written (10,000 simulations) -> Output/
python house_calibration.py # re-measure the uncertainty settings -> house_calibration.json
```

A 100,000-simulation run takes about 1-3 minutes, plus downloads. The model is a plain `.py` file, not a notebook, so the scheduler calls it directly; this is why it runs so much faster than the Senate's notebooks. Every assumption is in the `CONFIG` block at the top of `house_model.py`.

## Files

| File | What it is |
|---|---|
| `house_model.py` | The model. CONFIG at the top; `run()` downloads the data, runs the model and the checks, and writes `Output/` |
| `house_forecasts.py` | The scheduler and dashboard (the House version of `Senate Forecast/Final Model/final_forecast.py`) |
| `house_calibration.py` / `.json` | Measures the uncertainty settings from past House elections (see below) |
| `Data/house_districts_2026.csv` | One row per district: 2024 presidential result on the 2026 lines, partisan lean, region, incumbent running or open, nominees, race type |
| `Data/build_house_districts.py` | Builds that file and lists every source. Edit its tables and re-run it to change a district |
| `Data/calibration/` | Historical inputs for the calibration (saved, so it runs offline) |
| `Forecasts/` | Created on the first run: `latest.html` / `latest.pdf`, one folder per run (dashboard, `figures/*.html` + `.png` for Quarto, `data/`, `inputs/`), `history.csv`, `race_history.csv`, `model_warnings.xlsx` |

## Same as the Senate model

- **Polls:** VoteHub (`poll_type=us-representative`), matched to each district's two nominees by surname. Weights and adjustments use the Senate code unchanged: 7-day recency half-life, $\sqrt{n/800}$ capped at 2,500, LV 1.0 / RV 0.85 / A 0.7, partisan sponsors (weight 0.6, 3 pts against the sponsor), generic-question 0.5, full field 0.9, VoteHub grade and past accuracy, flooding $1/\sqrt{k}$, in-cycle house effects (k = 5), RV shift measured from 2026 LV/RV pairs, and each ungraded pollster redrawn in every simulation.
- **National environment:** 75% generic ballot + 25% Trump approval (0.35 pts per point of net approval), VoteHub polls blended with Kalshi's polling-average markets counted as 5 polls. The cache files are the Senate's, so both models see the same numbers.
- **Kalshi:** each district's market, found automatically by series ticker and event title (`ME-02 House winner?`). Longshot-corrected (slope 1.15) and used only for prices between 6% and 94%, with SD 8 pts. P(D) = D price / (D price + R price). The House-control market (`CONTROLH`) is shown for comparison only.
- **Combination:** precision-weighted average of the prior, the polls and Kalshi, with correlated source errors (rho 0.3) and drift.
- **Simulations:** errors in points: national (Student-t), Census region, lean factor and district.
- **Checks:** PASS / WARN / FAIL rows (the House version of Model Testing), logged to `model_warnings.xlsx`.

## What is different, and why

| Change | Why |
|---|---|
| **Fundamentals = 1.78 x lean** (Senate: 2.0) | On the 2018 and 2022 midterms, a district's House margin moved 0.89 pt for every point of presidential margin. House candidates run a little closer to the middle than the top of the ticket. |
| **Lean from 2024 only**, 2026 district lines (The Downballot) | 2020 results don't exist for the redrawn lines in TX, CA, FL, NC, OH, UT, TN, AL and LA |
| **Incumbency 4.5 pts**, applied only to an incumbent running *in that district* | Measured on 2018/2022. Incumbents who moved districts (e.g. Wasserman Schultz to FL-20, Casar to TX-37) count as incumbents where they now run |
| **No candidate effects** | `candidate_history.csv` covers statewide races only. Nothing equivalent exists for 870 House nominees |
| **New state-level error** (2.4 pts) | Districts in one state share candidates at the top of the ticket, turnout and redistricting quirks. Measured as the state-year part of the 2018/2022 misses |
| **Single-party races are certain** | 8 California D-vs-D races and 8 Democrats with no Republican opponent are certain D seats; CA-40 (Kim vs Calvert) is a certain R seat |
| **Independents** (`INDEPENDENTS` in CONFIG) | **AK-AL:** Bill Hill (independent, backed by national Democratic groups) vs Nick Begich (R). The Democrat, Eric Hafner, took 3.8% in the primary but is still on the ballot. Hill takes the Democratic side: polls are read for him and Kalshi as 1 - Begich's price (Kalshi's "Democratic" market is Hafner at about 1 cent). A Hill win counts for Democrats in 80% of simulations, the Senate model's figure for Osborn; Hill hasn't said whom he'd caucus with. **CA-06:** Richard Pan (D) vs Kevin Kiley (independent, no Republican on the ballot); a Kiley win does **not** count for Democrats. Both use prior SD x 1.3, as the Senate model does for independents |
| **Louisiana** | Nov 3 is an all-party primary, with a runoff on Dec 12. The six seats are forecast by party and lean, as if decided now (none is competitive) |
| **Missouri** | Uses its 2022 map: the new map can't be used in November (Missouri Supreme Court; it goes to Proposition A) |
| **Kalshi's expected seats** | Kalshi lists only some districts. The dashboard's "Kalshi (race prices)" total uses Kalshi where a district is listed and the model's probability everywhere else, and says how many districts Kalshi listed |
| **Simulation chunks** | 100,000 x 435 margins don't fit in memory at once, so the model processes 5,000 at a time and keeps only seat counts and win totals |

## Calibration (`house_calibration.json`, written Nov 2)

| Setting | Value | Measured from | Senate value |
|---|---|---|---|
| `PVI_TO_MARGIN` | 1.78 | 2018 + 2022 House results vs 2016/2020 presidential results in the same districts (510 contested races) | 2.0 |
| `INCUMBENCY_ADVANTAGE` | 4.51 pts | same regression | 3.78 |
| `PRIOR_SD` | 6.56 | district miss 5.65 (222 competitive districts) combined with the national miss | 9.32 |
| `NATIONAL_ERROR_SD` | 3.35 | final 3-week generic-ballot average vs national House vote, 1998-2022 (13 cycles) | 2.52 |
| `REGIONAL_ERROR_SD` / `STATE_ERROR_SD` | 2.68 / 2.42 | shared parts of the 2018/2022 district misses | 1.51 / none |
| `SYSTEMATIC_POLL_ERROR_SD` | 5.62 | 703 polled House races 1998-2022 (final average RMSE 7.26) | 3.87 |
| `KALSHI_CONVERT_SD` | 7.26 | same | 4.42 |
| drift, half-life, house-effect k, t tails | Senate values | no House-specific history in the files | |

Two judgment calls:

- **2014 is measured but not used.** Its 2012 presidential baseline comes before the 2016 realignment, so its misses (10 pts) and incumbency estimate (11 pts) are far from 2018 and 2022 (5.7-5.8 and 4.4-4.7). Change `PRIOR_CYCLES` to include it.
- **No bias correction**, as in the Senate model. Generic-ballot polls overstated Democrats by 2.3 pts on average in 1998-2022. The miss counts toward the 3.35-pt national error but does not shift the forecast.

## Before relying on it

- **Live data checked Nov 2 (4:05 PM test):** 191 VoteHub House polls (170 matched to both nominees), Kalshi prices for 76 districts plus the control market; model 95% vs Kalshi 94% for control, and 0.96 correlation with Kalshi across the 76 districts.
- **District file:** incumbents, open seats and nominees come from Wikipedia, Ballotpedia and 270toWin as of Nov 2, so spot-check the races you care about. Kalshi's candidate names replace the file's wherever a market exists, and the check "Kalshi nominee names agree with the district file" lists any disagreement.
- **NC-11:** Chuck Edwards withdrew in August. The file has no name for the replacement Republican, so polls there match only if Kalshi lists the nominee.

## Dashboard sections

Headline tiles; seat distribution; all 435 seats from safest D to safest R (seat 218 outlined); state tile map of expected D seats; competitive districts (model vs Kalshi dot chart, sortable table, plus a filterable table of all 435); **model vs Kalshi scatter** (every Kalshi-listed district, 10+ point gaps labelled); **swing from 2024** (projected margin against the 2024 presidential margin); **tipping-point districts** (bar chart + table); **what each forecast rests on** (fundamentals / polls / Kalshi share for the 40 closest districts); **run history** (a table, one row per run: the time-series line charts were dropped because a handful of points over 18 hours doesn't make a useful chart); notes, key settings and equations. Every chart is also saved to `figures/` as `.html` and `.png`.
