# Data

Margins everywhere are the Democrat (or credible independent) minus the Republican, in percentage points.

## Files the model reads

| File | Rows | What it is | Source |
| --- | --- | --- | --- |
| `Midterm_Polls.xlsx` (Sheet1) | 232 state Senate polls, Aug 27 to Oct 15, 2026 | `Date`, `State`, `Pollster`, `Dem%`, `Rep%`, `SampleSize`, `LVorRV`, `Partisan (Pollster or Sponsor)`, `Generic`, `Bigger_Field`, `Pollster Rank` (5 to 10), `Typical Error` (blank in every row) | Course professor, Oct 15 release, with one change (below) |
| `National_Polls.xlsx` (Sheet1) | 37 presidential approval polls, Sep 21 to Oct 15, 2026 | `Date`, `Pollster`, `Approval`, `Disapproval`, `SampleSize`, `Type` (Adults, RV or LV), `Pollster Ranking`, `Partisan` | Course professor, Oct 15 release |
| `leans_and_regions.csv` | 50 states plus a source row | `State`, `PartisanLean` (Cook PVI, vote share; negative = Republican), `Region` (Census division) | Course professor |
| `Events.xlsx` | 4 opinion events, 11 access rows (5 active), 1 map scenario | Our event register. The `Readme` sheet defines every column; the `derivation` and `source` columns say where each number came from | Our group |
| `RV_LV_pairs.xlsx` | 7 pairs (5 used) | Surveys reported among both registered and likely voters, plus where to find more | Our group |

## Change log

| Date | File | Change | Why |
| --- | --- | --- | --- |
| 2026-10-15 | `Midterm_Polls.xlsx` | Marist, Iowa, Sept 22 (sheet row 151): `LVorRV` changed from LV to RV | Marist's tables (SNVT26R) report this poll among registered voters only: Turek 50, Hinson 42. See `notes/Data_check_2026-10-15.xlsx` |

Nothing else was edited. The script handles some issues in code: pollster spelling variants are merged, one survey released several ways counts once, a lowercase `lV` is read as LV, and a national poll with sample size 0 gets zero weight.

## Open flags

The data check found 36 flags. Two high-severity ones are still in the professor's files as released, waiting on a group decision:

- `Midterm_Polls.xlsx`, sheet row 61: New Mexico, SurveyUSA, Oct 5, 54 to 47 (n = 567). The two shares add to more than 100, so one is probably a typo. Check the release.
- `National_Polls.xlsx`, sheet row 23: AlphaROC, Oct 1, appears twice with identical values, so it counts double in the approval average.

The other 34 flags (medium, check and low) are listed with what each one means in `notes/Data_check_2026-10-15.xlsx`.

## Originals

`original/2026-10-09/` and `original/2026-10-15/` hold the professor's files exactly as released. The Oct 9 folder also has that week's notes.
