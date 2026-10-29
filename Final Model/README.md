# Final Model — calibration

`calibration.ipynb` fine-tunes **any** model in `Models/` on past Senate elections.

1. Open `calibration.ipynb` and set `MODEL_FOLDER` in the first code cell (default `Models/Marks_Final`).
2. *Run All* (about a minute, plus one model run).
3. It writes **`calibration.json` into that model's folder** and, if `RUN_MODEL = True`, re-runs the model and shows the forecast before and after.

## What it measures
From FiveThirtyEight's public `raw_polls.csv` (polls from the final ~2 months of every Senate, governor, presidential and generic-ballot race since 1998, with certified results; cached in `Data_Cache/`):

| Quantity | How | Becomes | Oct 29 value |
|---|---|---|---|
| National polling miss | SD of each year's average Senate polling error (competitive races), minus averaging noise | `NATIONAL_ERROR_SD` (legacy: `CORR_NATIONAL`) | 2.43 pts (90%: 1.5–2.9) |
| Regional miss | same within year × Census region | `REGIONAL_ERROR_SD` (legacy: `CORR_REGION`) | 1.60 |
| State miss, tails | the rest; kurtosis -> t df | `STATE_T_DF` (legacy: `T_DF`) | 3.42 pts, df ≈ 10 |
| Drift | extra error 3–8 weeks out, after allowing for fewer polls | `DAILY_DRIFT_SD` | 0.84 pts/√day |
| Prior spread | result − (lean + generic-ballot polls), after incumbency and candidate effects, 2014–2022 | `PRIOR_SD` | 9.35 |
| Incumbency | regression | `INCUMBENCY_ADVANTAGE` / `INCUMBENCY_PTS` | 3.84 pts |
| Candidate effects | regression on each nominee's past over-performance | `CANDIDATE_EFFECT_WEIGHT` | 0.30 |
| Poll-error floor | solved so the model's ranges are the right width on 2014–2022 competitive races | `SYSTEMATIC_POLL_ERROR_SD` | 3.69 |

A model only gets the settings it actually has (matched by name). `Marks_Final` reads `calibration.json` itself (`USE_CALIBRATION` in its CONFIG). Any other model is run from a **copy** in `calibration_runs/<model id>/` with the values injected after its CONFIG, so its own notebook and `Output/` never change.

## Not calibrated (no history in the file)
`ENV_SLOPE` (approval → margin), Kalshi's weight and longshot correction (no market history), `NATIONAL_T_DF` (15 elections can't pin down the tails of the national miss).

## Caveats
- Polls in this file are the final ~60 days only, and lopsided races are excluded (third-party-heavy blowouts produce meaningless "errors").
- Incumbents and candidate histories are found by matching surnames to earlier races in the same state; appointed incumbents and candidates whose earlier races weren't polled are missed.
- 2014–2022 Senate polls overstated Democrats by about 2.7 pts on average (2014, 2016, 2020), while 2018 and 2022 were close or the other way. The calibration widens the ranges for this but does **not** shift any margin; that's a judgment call for the team.
