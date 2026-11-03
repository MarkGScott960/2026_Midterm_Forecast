# 2026 U.S. Senate Forecast: Event Edition

version of the group model for the election poll prediction workshop. It starts from the professor's starter notebook (polls, partisan lean, presidential approval, correlated simulations) and adds a layer for major events: news shocks, changes to voting access, and redrawn maps. It also includes a sensitivity sweep that shows which of our choices actually move the forecast.

**On the October 15 data, Democrats control the Senate in 66.6% of 40,000 simulated elections** (median 52 Democratic seats, 80% range 48 to 55).

## Quick start

```bash
pip install -r requirements.txt

python senate_event_model.py --today 2026-10-15           # the forecast in the guides
python senate_event_model.py --today 2026-10-15 --sweep   # test every setting, low vs. high (about 70 seconds)
python senate_event_model.py --set ENV_SLOPE=0.5 --set PRIOR_SD=5   # try values without editing the file
```

Leave out `--today` to forecast as of today. Results, tables and charts go to `outputs/`.

## Read these first

| Guide | For | What it covers |
| --- | --- | --- |
| [How the Senate Forecast Works](docs/how_the_forecast_works.md) | Policy students who don't code, and coding students who don't study policy | The model as a flow, one race (Iowa) traced through every step, the political science behind each step, a shared vocabulary, and who decides what |
| [Variables and Choices](docs/variables_and_choices.md) | Anyone changing a setting | Every setting, which party raising it helps, the range we tested, and the group's decisions ranked by impact |

PDF versions of both are in `docs/`.

## What's in here

```
senate_event_model.py        the model: settings at the top, one command runs everything
rv_lv_shift.py               estimates the registered-voter vs. likely-voter shift from paired surveys
requirements.txt
data/
  Midterm_Polls.xlsx         state Senate polls (professor's Oct 15 file, one row relabeled; see data/README.md)
  National_Polls.xlsx        presidential approval polls
  leans_and_regions.csv      partisan lean and Census region by state
  Events.xlsx                our event register: opinion events, access changes, map scenarios
  RV_LV_pairs.xlsx           paired RV/LV survey results used by rv_lv_shift.py
  original/                  the professor's files exactly as released (Oct 9 and Oct 15)
  README.md                  data dictionary and change log
notes/
  Important_Considerations.docx, Major_events.docx   the professor's notes (Oct 15)
  Data_check_2026-10-15.xlsx                          our check of the Oct 15 data: 36 flags, 1 fixed, 2 high flags still open
notebooks/
  senate_midterm_model_EVENTS.ipynb    the model as a step-by-step notebook, with explanations
  senate_midterm_model_SAMPLE.ipynb    the professor's starter notebook, unchanged
docs/
  how_the_forecast_works.md, variables_and_choices.md   the two guides (plus PDF versions)
  images/                    the flow diagram and sensitivity chart used in the guides
outputs/
  results from the script on Oct 15 (race probabilities, battlegrounds, scenarios, sensitivity.csv, charts)
  run_log_2026-10-15.txt     the full printed output of that run
  notebook/                  results from the notebook
```

## Changing the model

- **Settings** live in the `SETTINGS` block at the top of `senate_event_model.py`. Each line has a comment that says what it does. The low and high values the sweep tests are in `SWEEP`, right below it.
- **Events** live in `data/Events.xlsx`, so you can add a news event or a voting-access change without touching code. The `Readme` sheet defines every column.
- **New polls:** replace `data/Midterm_Polls.xlsx` and `data/National_Polls.xlsx` with newer files that keep the same columns, then rerun. Run the data check again before trusting the result.
- **RV/LV shift:** add paired results to `data/RV_LV_pairs.xlsx` and run `python rv_lv_shift.py`.

## Reproducing the numbers

- The script gives 66.6% with `--today 2026-10-15` and the default `SEED` of 2026. Every number in the guides comes from that run.
- The notebook gives 66.9%. It is the same model, but it draws its random numbers in a different order. A 0.3-point gap is ordinary simulation noise at 40,000 runs. The script draws each piece of randomness from its own stream, so the sweep compares settings on identical draws.

## Not included

- **The Silver Bulletin generic ballot file.** It is a paid subscriber download, so it isn't in the repo. The +1.87 RV/LV estimate in the guides came from it. `.gitignore` blocks it so it doesn't get committed by accident.
- **PDFs of the papers we cite.** The full references are at the end of each guide.

## Before making this repo public

The poll files, the notes and the starter notebook come from the course professor. Keep the repo private unless the professor says it can be public.
