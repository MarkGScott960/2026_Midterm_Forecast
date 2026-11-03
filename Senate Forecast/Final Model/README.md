# Final Model - calibration

`calibration.ipynb` fine-tunes **any** model in `Models/` on past Senate elections.

1. Open `calibration.ipynb` and set `MODEL_FOLDER` in the first code cell (default `Models/Marks_Final`).
2. *Run All* (about a minute, plus one model run).
3. It writes **`calibration.json` into that model's folder** and, if `RUN_MODEL = True`, re-runs the model and shows the forecast before and after.

## What it measures
From FiveThirtyEight's public `raw_polls.csv` (polls from the final ~2 months of every Senate, governor, presidential and generic-ballot race since 1998, with certified results; cached in `Data_Cache/`):

| Quantity | How | Becomes | Oct 29 value |
|---|---|---|---|
| National polling miss | SD of each year's average Senate polling error (competitive races), minus averaging noise | `NATIONAL_ERROR_SD` (legacy: `CORR_NATIONAL`) | 2.52 pts (90%: 1.7-2.9) |
| Regional miss | same within year x Census region | `REGIONAL_ERROR_SD` (legacy: `CORR_REGION`) | 1.51 |
| State miss, tails | the rest; kurtosis -> t df | `STATE_T_DF` (legacy: `T_DF`) | df ~ 11 |
| Drift | extra error 3-8 weeks out, after allowing for fewer polls | `DAILY_DRIFT_SD` | 0.76 pts per $\sqrt{\text{day}}$ |
| Prior spread | result - (lean + generic-ballot polls), after incumbency and candidate effects, 2014-2022 | `PRIOR_SD` | 9.32 |
| Incumbency | regression | `INCUMBENCY_ADVANTAGE` / `INCUMBENCY_PTS` | 3.78 pts |
| Candidate effects | regression on each nominee's past over-performance | `CANDIDATE_EFFECT_WEIGHT` | 0.30 |
| Recency half-life | error of past polling averages for half-lives of 3-30 days (best: 5); team chose 7 for steadier thin races | `RECENCY_HALF_LIFE_DAYS` | 7 days |
| Pollster leans | in-cycle house effects (each pollster vs other pollsters in the same race), shrunk by k; cut averaging error 4.72 -> 4.43 pts | `HOUSE_EFFECT_K` | 5 |
| Poll-error floor | solved so the model's ranges are the right width on 2014-2022 competitive races | `SYSTEMATIC_POLL_ERROR_SD` | 3.87 |

A model only gets the settings it actually has (matched by name). `Marks_Final` reads `calibration.json` itself (`USE_CALIBRATION` in its CONFIG). Any other model is run from a **copy** in `calibration_runs/<model id>/` with the values injected after its CONFIG, so its own notebook and `Output/` never change.

## Not calibrated (no history in the file)
`ENV_SLOPE` (approval -> margin), Kalshi's weight and longshot correction (no market history), `NATIONAL_T_DF` (15 elections can't pin down the tails of the national miss).

## Caveats
- Polls in this file are the final ~60 days only, and lopsided races are excluded (third-party-heavy blowouts produce meaningless "errors").
- Incumbents and candidate histories are found by matching surnames to earlier races in the same state; appointed incumbents and candidates whose earlier races weren't polled are missed.
- 2014-2022 Senate polls overstated Democrats by about 2.7 pts on average (2014, 2016, 2020), while 2018 and 2022 were close or the other way. The calibration widens the ranges for this but does **not** shift any margin; that's a judgment call for the team.

# Final forecast: `final_forecast.py`

Runs Most_Magnificent_Model (Team 5's final model) on a schedule and builds a dashboard after every run.

```
python final_forecast.py            # start (or resume) the schedule; leave the window open
python final_forecast.py --test     # one quick 1,000-simulation run -> Forecasts/test_<datetime>.html (to tune the look)
python final_forecast.py --status   # show the schedule and what has run
```

- **Schedule:** a run when you start it, then every 3 hours on fixed clock times, then a final run at **9:00 AM Tue Nov 3**, then it stops for good. No regular run starts in the hour before the final one, so the final run starts on time. A long run never shifts later run times; runs never overlap (an overrunning run finishes and saves, and the next starts right after); missed runs are made up with one run.
- **Each run** (100,000 simulations, planned 2-4 h): Model Testing, then the forecast. The console shows which step is running, elapsed time and time left (planned 120-240 min until a run has been timed); between runs it shows RESTING and the time until the next run.
- **Restarting** resumes the same schedule and keeps the history (`Forecasts/schedule.json`, `history.csv`, `race_history.csv`).
- **Outputs:** `Forecasts/latest.html` (newest dashboard) and `Forecasts/<YYYY-MM-DD_HHMM>/`: `dashboard.html`, `figures/` (each chart as interactive `.html` and static `.png`, for Quarto) and `data/`.
- **Dashboard:** P(D >= 51) with a 95% simulation interval, mean seats with 80% and 95% ranges, Kalshi's control market and race-price total, seat distribution, state tile map (too close to call = favourite under 60%, the model's `RATING_TOSSUP`), race-by-race model vs Kalshi with projected margins, history charts vs Kalshi, notes (Model Testing results, data sources), key settings, and the equations with the weights each run used.
- **Warnings:** the dashboard's notes show only the PASS / WARN / FAIL counts (and any FAIL). Every WARN and FAIL is appended, one row per check per run, to `Forecasts/model_warnings.xlsx` (filterable). If the workbook is open in Excel during a run, that run's rows go to a separate dated file instead.
- **Editing the dashboard mid-schedule:** wait for RESTING, press Ctrl+C, edit, run `python final_forecast.py --report` (rebuilds every saved run's dashboard, figures and `latest.html` from saved data; no model run), then `python final_forecast.py` to resume. No runs are lost.
- The dashboard uses only standard keyboard characters; the equations are LaTeX, rendered by MathJax (downloaded once into `Forecasts/.cache` and embedded, so pages work offline).
- `--reset` deletes the schedule, history, warnings workbook, `latest.html` and run folders (tests kept); stop the running script first.
- Test runs write to their own folder and never touch the schedule, the history or `Models/Most_Magnificent_Model/Output`.
