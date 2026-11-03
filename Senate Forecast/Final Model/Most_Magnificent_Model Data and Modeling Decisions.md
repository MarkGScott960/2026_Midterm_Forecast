# Most\_Magnificent\_Model: Data and Modeling Decisions

Oct 29, 2026 - @Mark (updated Oct 31)

## Output

Most\_Magnificent\_Model gives three outputs: the chance Democrats hold at least 51 Senate seats (Republicans hold the VP tiebreak), the expected number of Democratic seats, and each race's chance of a Democratic or independent win. It combines three sources for every race, polls, fundamentals and the Kalshi prediction market, then simulates the election 100,000 times.

- **When it runs:** every 3 hours from Oct 29, 8:05 PM, with a final run at 9:00 AM on Nov 3. Each run refreshes all data.
- **Where results go:** `Senate Forecast/Final Model/Forecasts/latest.html` (dashboard), with every chart also saved as an HTML and PNG file for Quarto. Warnings from the built-in checks are logged to `Forecasts/model_warnings.xlsx`.
- **What each run saves (from the first run after Oct 31, 2:40 PM):** every input file the run used (the downloaded VoteHub and Kalshi data, the scorecard, lean and 2024 files, `calibration.json`, `candidate_history.csv` and the model notebook itself) goes to `Forecasts/<run>/inputs/` with a `manifest.json`. Any run from then on can be re-created exactly, for example to re-run the history with a changed method. Runs before that saved only their outputs.


## Where the data comes from

All poll and market data is downloaded fresh each run. If a site is down, the last saved copy is used and the dashboard notes it.

| Source | What we take from it | Used for |
| --- | --- | --- |
| VoteHub API | Every 2026 Senate general-election poll (pollster, dates, sample size, voter type, results) | The polling average in each race |
| VoteHub API | Generic-ballot and Trump approval polls | The national environment |
| VoteHub pollster scorecard (saved file) | Each pollster's grade (A+ to D), past accuracy and typical lean | Weighting and adjusting polls |
| Kalshi | Each race's win price, the Senate-control price, and markets on the RCP/VoteHub polling averages | A third input per race; national environment; comparison |
| Partisan lean file (Cook-style PVI) + Census regions | How much more R or D each state votes than the nation | Fundamentals; which states move together |
| 2024 presidential results | State and national margins | Candidate effects |
| `candidate_history.csv`  | Each competitive-race nominee's last top-of-ticket statewide result | Candidate effects |
| FiveThirtyEight `raw_polls.csv` (public) | Polls and certified results for every Senate race 1998-2022 | Calibrating the model's uncertainty and weights |

**Not used:** the  spreadsheets (`Midterm_Polls.xlsx`, `National_Polls.xlsx`).

## How polls are weighted and adjusted

Each poll's weight is the product of the factors below, and a race's polling average is the weighted average of its polls. Weights change how much a poll counts adn adjustments change the margin itself.

| Factor | Rule | Why |
| --- | --- | --- |
| Recency | Weight halves every 7 days | Tested on 1998-2022 races: shorter half-lives predicted results better; 7 days is nearly as accurate as the best (5) but steadier / more accurate in thinly polled races |
| Sample size | $\sqrt{n / 800}$, capped at n = 2,500 | Sampling error shrinks with $\sqrt{n}$; the cap stops huge online panels dominating |
| Voter type | Likely voters 1.0, registered 0.85, all adults 0.7 | Closest to who votes counts most; if a survey reports both, only the likely-voter version is kept |
| Partisan sponsor | Weight 0.6 and margin moved 3 pts against the sponsor | Campaign polls are released selectively |
| Generic question | 0.5 for "a Democrat vs a Republican" instead of named candidates | Measures party, not this race |
| Full field | 0.9 when third-party candidates are offered | Third-party support usually fades |
| Pollster quality | 0.5 (grade D) to 1.0 (grade A+) | VoteHub's grades |
| Past accuracy | Based on the pollster's past error, kept between 0.5x and 2x | Rewards firms that missed by less, without letting one dominate |
| Flooding | A firm with k polls of a race gets $1/\sqrt{k}$ per poll | One pollster can't drown out the others |

**Ungraded pollsters (about 40% of poll weight).** VoteHub grades only 42 firms. Instead of treating every unknown firm as the worst, each ungraded firm gets the grade, accuracy and lean of a randomly drawn graded firm, **redrawn in every one of the 100,000 simulations**. Our uncertainty about these firms then shows up in the probabilities. Using the lowest grade instead changed P(51+) by about 1 point. Two graded firms appeared in VoteHub under other names and were being treated as ungraded until Oct 31: "The Bullfinch Group" (scorecard: Bullfinch, grade D, leans D+2.0) and "The Washington Post/George Mason University Schar School" (WaPo-GMU, grade C). Both are now matched; the effect on the forecast is under 0.2 pts of P(51+).

**Margin adjustments:**

- **Undecided voters** are split in proportion to the decided vote.
- **Registered-voter polls** are shifted toward Democrats by the gap measured this year between the likely- and registered-voter versions of the same surveys (about +0.9 pts from 32 pairs; re-measured every run).
- **House effects:** each pollster's lean this year is measured from its last 60 days of polls against other pollsters' polls of the same states, then pulled toward its VoteHub scorecard lean (worth 5 polls). Examples: Quantus about 4.5 pts more Republican than other pollsters, InsiderAdvantage 1.5; Marist 1.6 and CNN 1.2 more Democratic. On 1998-2022 races this cut polling-average error from 4.7 to 4.4 pts.

## Fundamentals (what we'd expect without polls)

Each race starts from: 2 x the state's partisan lean + the national environment +/- incumbency + a candidate effect.

- **Partisan lean** is in vote share, so it's doubled to become a margin.
- **National environment** = 75% generic ballot + 25% Trump approval (each approval point is worth 0.35 pts of margin). The generic ballot gets more weight because it's already a margin; the approval slope is an assumption. VoteHub's national polls are 3-4 weeks old, so Kalshi's live averages of the RCP and VoteHub polling averages are blended in as if they were 5 polls, and stale VoteHub polls count for less.
- **Incumbency:** 3.8 pts for an elected incumbent on the ballot, 1 pt if appointed (FL, OH, SC). Estimated from 2014-2022 Senate races.
- **Candidate effects:** the lean-based starting point treats every nominee as generic, which badly misjudged races like Maine (Collins). So each nominee's last top-of-ticket statewide race (Senate, governor, at-large House) is compared with what a generic candidate of their party would have done that year. 30% of that over- or under-performance carries over, the share past Senate races support. Used for Collins, Sullivan, Peltola, Osborn, Ricketts, Brown, Cooper, Ossoff, Rogers, Marshall and Hyde-Smith. Down-ballot offices (e.g. Paxton as attorney general) aren't used.
- **Independents:** Osborn (Nebraska) counts as a Democratic seat with 80% probability if he wins (Professor Adler's figure).

## How the three sources are combined

Polls, fundamentals and Kalshi are averaged by how certain each one is (precision = $1/\text{uncertainty}^2$), so the most reliable source counts most. In a well-polled race that works out to roughly:

| Source | Uncertainty used | Typical share of a polled race |
| --- | --- | --- |
| Polls | Shrinks with more polls, never below 3.9 pts | \~65-70% |
| Fundamentals | 9.3 pts | \~13-16% |
| Kalshi | 8 pts | \~17-22% |

In races with no polls, fundamentals and Kalshi split the weight. Three corrections apply to Kalshi first:

- **Longshot bias:** markets overprice underdogs, so prices are stretched slightly away from 50% (5% becomes about 3%).
- **Prices under 6% or over 94% are ignored.** At the 1-5 cent floor a price only says "safe", and turning it into a margin dragged safe races toward 50-50.
- **Converting a price to a margin** uses at least 4.4 pts of uncertainty, the historical final-weeks error of a Senate polling average.

Why include Kalshi at all: it is a separate read on candidate quality and late news. At 17-22% it informs the forecast without replacing the polls.

## Uncertainty and simulations

The uncertainty settings were measured on every competitive Senate race from 1998-2022. In a replay of past races, the calibrated settings predicted winners better than our earlier guesses (Brier score 0.102 vs 0.107).

| Setting | Value | What it means |
| --- | --- | --- |
| National polling miss | 2.5 pts | In each simulation every race shares one national error, so all races can miss in the same direction |
| Regional miss | 1.5 pts | States in the same Census region share an extra error |
| State miss | The rest of each race's uncertainty | Race-specific surprises |
| Poll-error floor | 3.9 pts | Error all of a state's polls share; more polls can't remove it |
| Fundamentals uncertainty | 9.3 pts | How far results stray from lean + environment (2014-2022 era) |
| Opinion drift | $0.76 \times \sqrt{\text{days left}}$ pts | Room for late movement; zero on election day |
| Simulations | 100,000 per run | Simulation noise on P(51+) is about $\pm$0.3 pts |

Only the national error has fat tails, so a bad polling year can hit every race at once without producing absurd outcomes.

- **Does 2024 change the national miss?** The historical file stops at 2022. 2024 Senate polls overstated Democrats by about 3 pts (Silver Bulletin). Adding a 2024 year of that size to the calibration leaves the national miss at about 2.42 pts (2.43 without it): a 3-pt miss is already inside the range of past years (2020: 5.6, 2014: 4.0). The 2.5 pts used already covers it, so it was left unchanged.
- **Robustness:** with national polling misses 60% larger than history (4.0 pts instead of 2.5), P(D >= 51) is still about 72%. With a much smaller national miss (1.5 pts) it is about 84%. The expected seat count stays at about 52.4 in every case; this setting only changes how spread out the outcomes are.

## Options we tested and rejected

| Option | Decision | Why |
| --- | --- | --- |
| "Literal" fundamentals (8 : 4 : 1 weighted average of 2024 result, generic ballot, approval) | Rejected | Averaging a state margin with national numbers pulled safe states toward 50-50 and cost \~10 pts of P(51+); we use 2024 lean + national swing instead |
| Averaging all team models | Rejected | They share the same data, so averaging mostly mixes in weaker choices (stale data, uncalibrated settings) |
| Correcting for poll bias toward Democrats | Rejected | Polls overstated Democrats in 2014, 2016, 2020 and 2024 were close to even or mixed in 2018, and understated them in 2022 and in the 2025 governor races (NJ by about 9 pts). The pattern is strongest when Trump is on the ballot; 2026 is a midterm. Out-of-sample test on 2004-2022 Senate races, correcting each year by the average miss of earlier years: Brier 0.116 with the correction vs 0.110 without (midterms: 0.079 vs 0.075); a half-size correction also did worse (0.113). The yearly miss averages about 0.5 pts toward Democrats but swings about +/-2.9 pts from year to year, so its direction can't be predicted. A possible miss in either direction is handled by the national error in the simulations instead |
| Extra uncertainty for old polls (beyond 10 days) | Tested, not used | Recomputed with the model's own formula: -0.05 expected seats and under 0.5 pts of P(51+). Largest changes were Alaska 59% to 58% and Ohio 76% to 75%; it mainly affects safe states with one old poll (Idaho, Virginia) |
| Re-running the history chart after a method change | Not done | Runs before Oct 31 didn't save their input data, and the model's backtest mode can't rebuild the Kalshi national averages or the 3-hourly timing. The Oct 31 changes moved P(51+) by under 0.2 pts, inside normal run-to-run movement, so the published history is kept as it was |
| Adjusting old polls for the national trend | Rejected | Didn't reliably help on past races and made things slightly worse once house effects were added |
| Rylyn's events layer | Not used | Her own check showed 67.0% with events and 67.0% without |
| More than 100,000 simulations | Not needed | Simulation noise is already +/-0.3 pts; the real uncertainty is in the data |

## Caveats to state in the write-up

- **The model assumes polls are as likely to miss toward Democrats as toward Republicans.** History supports that, but it's the biggest risk: a uniform 1-pt miss toward Republicans lowers P(51+) by about 12 pts. This is the main reason the model sits above Kalshi's control market (about 67%).
- **The model and Kalshi agree on seats.** The model's expected seat count matches what Kalshi's race prices add up to (about 52). The gap in P(51+) is about how spread out the outcomes are, not the average.
- **Thin polling:** Kansas, Nebraska and South Carolina rest on about 2 effective polls each, so they lean more on fundamentals and Kalshi.
- **National mood data is stale:** VoteHub's national polls are 3-4 weeks old; Kalshi's polling-average markets fill the gap.
- **Judgment calls not set from history:** Kalshi's weight (as minimal as possible while remaining as a fall back for sparse polls), the approval-to-margin slope (0.35), and Osborn's 80% caucus probability.
- **Final numbers come from the 9:00 AM Nov 3 run**; the dashboard's history chart shows how stable the forecast was in the final days.
