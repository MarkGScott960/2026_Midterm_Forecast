# Rylyn's Model (Event Edition)

Rylyn's Senate forecast (`ElectionGroupModelThing` repo, `senate_event_model.py`), ported into this project's model format so `run_all.py` can run and compare it.

**The port is faithful.** Every model function in `rylyn_model.ipynb` is copied word for word from Rylyn's script: the notebook is generated from the script's source, function by function. Every setting keeps Rylyn's value, and the model reads Rylyn's own data files. `Model Testing.ipynb` re-runs Rylyn's published case (Oct 15, 40,000 simulations, seed 2026) and gets **66.6%**, exactly what Rylyn's README reports.

| File / folder | What it is |
|---|---|
| `rylyn_model.ipynb` | The model, in steps, with Rylyn's explanations. Run the install cell once, then *Run All* |
| `Model Testing.ipynb` | Data checks, sanity checks, Rylyn's correlation check, the 66.6% reproduction, Rylyn's low/high sensitivity sweep, random seeds |
| `model.json` | Registers the model with `run_all.py` (id `rylyn`) |
| `data/` | Rylyn's data folder, unchanged: the professor's Oct 15 `Midterm_Polls.xlsx` (one row fixed; see `data/README.md`), `National_Polls.xlsx`, `leans_and_regions.csv`, `Events.xlsx`, `RV_LV_pairs.xlsx`, and the professor's original files |
| `docs/` | Rylyn's guides: *How the Senate Forecast Works* and *Variables and Choices* (Markdown + PDF) |
| `notes/` | The professor's notes and Rylyn's Oct 15 data check |
| `rv_lv_shift.py` | Rylyn's helper that estimates `RV_MARGIN_SHIFT` and `RV_WEIGHT` from paired RV/LV surveys (`python rv_lv_shift.py`) |
| `source_repo/` | Rylyn's original script, README and requirements, plus the original notebooks zipped (`original_notebooks.zip`, zipped so `run_all.py` doesn't flag them as unregistered models). For reference only; nothing runs them |
| `Output/` | Results (created on the first run). `Output/standard/` is read by `run_all.py`; `Output/testing/` holds Model Testing's results |

## What the model does (Rylyn's design)

Starter-notebook backbone plus an **events layer**:

1. **Polls**: weighted by recency (half-life 14 days), sample size, RV vs LV, partisan sponsor, generic ballot, full field, pollster rank, accuracy, flooding and survey versions. Partisan polls move 3 points against the sponsor; RV polls move +1.0 toward D.
2. **National environment**: 0.35 × −(net presidential approval), from the approval spreadsheet.
3. **Prior**: 2 × partisan lean + environment (incumbency off by default), SD 7. Combined with the polls by precision; drift for the days left.
4. **Opinion events** (`Events.xlsx`, Opinion sheet): each event's prior effect is checked against same-pollster before/after pairs, then added only where the polls haven't seen it yet. Each event's uncertainty adds correlated simulation error.
5. **Access events** (Access sheet): changes in who gets a counted ballot, applied to the simulated Election Day margin. Rows marked active are in the forecast; the others are scenarios.
6. **Simulations**: factor-built correlated errors (national, region, lean similarity), multivariate t (df 8), 40,000 runs.
7. **Extras**: battleground table with each race's chance of being the deciding seat, event decomposition, access scenarios, stress test, and a House map module (toy data).

Every setting is explained in `docs/variables_and_choices.md`.

## What the port changed (plumbing only)

| Change | Why |
|---|---|
| Script → notebook steps, with Rylyn's explanations from `senate_midterm_model_EVENTS.ipynb` | Same layout as the other models |
| `report()` split into one cell per section (same code) | Readable results |
| `SETTINGS["AS_OF_DATE"]` added (= the script's `--today`), plus the *Shared settings from run_all.py* cell | `run_all.py` gives every model the same date and 10,000 simulations |
| Paths: `data/` and `Output/` in this folder | Works from the repo |
| Install cell; standard export to `Output/standard/` | Required by `run_all.py` |
| Correlation check and `--sweep` moved to `Model Testing.ipynb` | Same split as the other models |
| Not ported: `--set` (edit SETTINGS instead) and `matplotlib.use("Agg")` (charts display in the notebook) | Notebook, not a command line |

For the standard export, each race's margin is the mean simulated Election Day margin (Rylyn's "Projected margin", including event draws). `p_dem` is the correlated-simulation win probability, and P(D ≥ 51) uses `D_SEATS_FOR_CONTROL` = 51.

## Running it

- **On its own:** open `rylyn_model.ipynb`, run the install cell, then *Run All* (a few seconds at 40,000 simulations). Then run `Model Testing.ipynb` (about 1.5 minutes; the sweep re-runs the model 57 times).
- **With the other models:** `python run_all.py` picks it up through `model.json`. `python run_all.py --only rylyn` runs just this one; the report still shows every model.
- **Rylyn's published numbers:** set `SETTINGS["AS_OF_DATE"] = "2026-10-15"` (40,000 simulations) → 66.6%, median 52 seats.

## Things to know when comparing it with the other models

1. **Its data stops on Oct 15.** It reads the professor's Oct 15 spreadsheets, which nothing updates. On later dates the polls are simply older. With a 14-day half-life, every poll is down-weighted by about the same factor, so the average barely changes, but no new polls come in. To update it, replace `data/Midterm_Polls.xlsx` and `data/National_Polls.xlsx` with newer files in the same columns (Rylyn's README).
2. **No as-of filter.** The script doesn't drop polls dated after the forecast date, because it was always run on the release date. A backtest earlier than Oct 15 would still see later polls. Model Testing flags this.
3. **Two open data flags from Rylyn's check** are still in the files: New Mexico SurveyUSA Oct 5 (54 + 47 > 100) and a duplicated AlphaROC approval poll. Model Testing lists both.
4. **Different choices from the group model (Model 1)**, from Rylyn's own guide: no undecided allocation, no generic-ballot blend, incumbency off, half-life 14 (not 21), prior SD 7 (not 7.5), RV shift +1.0 (not −0.5), Osborn caucus probability 0.7 (not 0.8), t df 8 (not 5), national correlation 0.40 (not 0.45). If the forecasts disagree, compare these first.
5. **No Kalshi.** The model doesn't use prediction markets; Kalshi appears only in `run_all.py`'s report as a reference.
6. **Ratings** use Rylyn's cut-offs (Toss-up < 60%, Lean < 70%, Likely < 85%, else Safe). The other models use 60/75/95.
