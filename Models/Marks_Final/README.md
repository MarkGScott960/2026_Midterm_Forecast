# Marks_Final — final-model candidate

**Pray_For_The_Floor, calibrated on past Senate races, with the structural problems from the Oct 29 model review fixed.**

| File | What it is |
|---|---|
| `marks_final.ipynb` | The model. Run the install cell once, then *Run All* |
| `Model Testing.ipynb` | Pray's checks, sweep, toggles, seeds and weekly backtests, plus Marks checks (calibration, candidate history, Kalshi request failures, RV pairs, seat tails) and **E4b: what each change did** |
| `candidate_history.csv` | Each competitive-race nominee's last top-of-ticket statewide result, with a source link per row |
| `calibration.json` | Written by `Final Model/calibration.ipynb`; read automatically (`USE_CALIBRATION`) |
| `model.json` | Registers the model with `run_all.py` (id `marks_final`, order 60) |
| `Data_Cache/`, `Output/` | As in Pray |

## Forecast, Oct 29 (run_all.py, 14:00, live data)
| | P(D ≥ 51) | D seats (mean, 80% range) | seat SD |
|---|---|---|---|
| **Marks_Final** (Oct 29 evening: in-cycle house effects, 7-day half-life; 16:49 data) | **75.8%** | **52.2** (49–55) | 2.6 |
| Marks_Final, 5-day half-life, scorecard leans only (15:50) | 76.2% | 52.2 (49–55) | 2.6 |
| Marks_Final, first calibration (run_all 14:00) | 73.8% | 52.0 (49–55) | 2.5 |
| Marks_Final fed Kalshi's race prices instead of its own estimates | 73.2% | 52.1 | 2.75 |
| Pray_For_The_Floor | 61.2% | 51.4 (48–55) | 3.1 |
| Kalshi | 67.5% (control market) | 52.2 (sum of race odds) | — |

Marks_Final's seat forecast is slightly *below* the sum of Kalshi's race prices; its higher P(51+) comes from a narrower seat distribution (calibrated national error) and from Kalshi's control market being lower than its own race markets imply. A uniform polling miss toward Republicans is the main risk: 1 pt toward R → ~62%, 2 pts → ~47%.

## What changed from Pray_For_The_Floor, and why

| # | Change | Setting(s) | Why |
|---|---|---|---|
| 1 | **Candidate effects in the prior** | `CANDIDATE_EFFECTS`, `CANDIDATE_EFFECT_WEIGHT` (0.30, calibrated), `candidate_history.csv` | The lean-based prior treated every nominee as generic. Maine's prior was D+13.5 against Collins (who won by 8.6 when Biden carried Maine by 9); Peltola and Osborn ran 12–15 pts ahead of their party in 2024. Over-performance = their margin − (state pres − national pres + national House margin that year). Down-ballot races (AG, LG) aren't used |
| 2 | **Calibration** on 1998–2022 Senate races | `PRIOR_SD` 7.5→9.31, `SYSTEMATIC_POLL_ERROR_SD` 4.5→3.75, `DAILY_DRIFT_SD` 0.25→0.89, `INCUMBENCY_ADVANTAGE` 2→3.74, `RECENCY_HALF_LIFE_DAYS` 21→7, `NATIONAL_ERROR_SD` 2.52 (around zero), error pieces; historical averages corrected for in-cycle pollster leans | These were the settings that moved P(51+) most, and they were guesses. Calibrated values beat the old ones on a historical replay (Brier 0.102 vs 0.108; ranges the right width) |
| 3 | **Simulation errors as pieces, in points** | `ERROR_MODEL = "components"`, `NATIONAL_ERROR_SD` 2.43, `REGIONAL_ERROR_SD` 1.60, `LEAN_FACTOR_ERROR_SD` 1.0, `NATIONAL_T_DF` 8, `STATE_T_DF` ~10 | Pray's shared fat-tail draw gave 35- and 69-seat outcomes, and a national miss was bigger in unpolled safe states. `"legacy"` restores Pray |
| 4 | **Kalshi as a real input** | `KALSHI_SD` 17→8, `KALSHI_CONVERT_SD` (floor 4.69), `KALSHI_LONGSHOT_SLOPE` 1.15, `KALSHI_USE_RANGE` 6–94% | At 5–7% weight Kalshi changed nothing. The conversion was circular, and 1–5¢ prices dragged safe races toward the middle. Now ~13–22% of a polled race and up to ~60% of an unpolled one |
| 5 | **National mood** | `GENERIC_BALLOT_BLEND` 0.5→0.75, `NAT_FRESH_HALF_LIFE_DAYS` 14 | VoteHub's national polls are 3–4 weeks old but still counted like fresh polls against Kalshi's live averages. The generic ballot is already a margin; approval needs an uncalibrated slope |
| 6 | **RV shift measured** + LV version preferred | `RV_MARGIN_SHIFT = "estimate"` (+0.9 from 32 pairs today), `PREFER_LV_VERSION` | Pray assumed RV polls lean D by 0.5; this year's paired LV/RV releases say likely voters are about 0.9 pts *more* Democratic |
| 7 | **Kalshi requests retried, paged and logged** | `HTTP_TRIES`, `KALSHI_THROTTLE_S` | Pray's search swallowed rate-limit errors, so a different set of races fell back to the hand table on each run |
| 8 | **Deciding-seat table** (from Rylyn) | — | Share of simulations each race delivers seat 51 |
| 9 | **In-cycle house effects** | `HOUSE_EFFECT_MODE = "in_cycle"`, `HOUSE_EFFECT_K` 5, `HOUSE_EFFECT_WINDOW_DAYS` 60 | Each pollster's lean this year (its last-60-day polls vs other pollsters' polls of the same states), shrunk toward its scorecard lean; replaces the scorecard subtraction. On 179 competitive Senate races 1998–2022 it cut polling-average error 4.72 → 4.43 pts, better Brier in 10 of 15 cycles. Today: Quantus −4.5, InsiderAdvantage −1.5, Marist +1.6, CNN +1.2; P(51+) +0.5 pt vs scorecard only |
| 10 | **7-day half-life** (team choice) | `HALF_LIFE_DAYS = 7` in the calibration notebook | 5 days was most accurate historically, 7 nearly as good and steadier in thinly polled races. A national trend adjustment was tested and **not** added: it didn't reliably help and made things slightly worse once house effects were in |

Kept from Pray unchanged: VoteHub data, scorecard grades and house effects, random grades for ungraded pollsters redrawn every simulation, flooding penalty, survey versions, half-life recency, correlated source errors, standard export. Not used: Rylyn's events layer (her own check: 67.0% with and without).

**Effect of undoing each change on its own** (Model Testing E4b, 2,000-simulation check): none moves P(51+) more than about 2 points. Together they move it 13 points, because many small shifts all point toward Democrats in the races near the 51st seat (Ohio, Texas, Alaska, Kansas). Undoing the calibration or the candidate effects moves Maine the most (74% → 80–82%), and also Kansas.

## Tables checked (Oct 29)
Incumbent status re-verified: OK and LA are **open** (Oklahoma's appointed senator isn't running; Cassidy lost his primary); SC has an **appointed** incumbent running; FL and OH are appointed; AL, IA, IL, KY, MI, MN, MT, NC, NH, TX and WY are open. Holdovers 34 D / 31 R; Osborn caucus probability 0.8 (Adler); Fetterman defection 0.

## Known weaknesses
1. **Polling bias isn't corrected, on purpose.** 2014–2022 Senate polls overstated Democrats by about 2.7 pts on average, but a cycle's miss can't be predicted from earlier cycles (correlation +0.14). Predicting "no miss" beat the long-run average, the last-3-cycles average and the last cycle on 1998–2022 (calibration Step 3). So the margin isn't shifted; the national error is measured around zero (2.55) so the spread covers a miss either way. Sensitivity if the team wants it anyway: 1 pt toward R ≈ −12 pts on P(51+), 2 pts ≈ −26.
2. **Candidate effects use one past race per nominee** at weight 0.3. Nominees with no statewide history (Talarico, Jackson, Hinson…) get none.
3. **Not calibrated:** `ENV_SLOPE`, Kalshi's weight and longshot slope, and the national tail (`NATIONAL_T_DF`).
4. **The national mood still rests on thin VoteHub data** plus Kalshi's averages.
5. Everything in Pray's README §9 that isn't fixed above still applies (static scorecard, surname matching, hand-maintained incumbent table).
