# Model 2: Ozempic — Swing vs Literal

Ozempic is the slimmed-down version of Model 1 (`Models/Model_Full_Configs`). It keeps Model 1's backbone (weighted polls, fundamentals, correlated simulations) but exposes only a handful of weights for the team to argue about, pulls everything live from VoteHub and Kalshi, and reports two numbers:

1. **P(Democrats hold at least 51 seats)**
2. **Predicted number of Democratic seats** (mean of 10,000 simulations, including caucusing independents)

It comes in two variants that are **identical except for how the fundamentals are calculated**. Both are here so the group can compare and choose.

| | Ozempic_Swing | Ozempic_Literal |
|---|---|---|
| Fundamentals | 2024 state margin **+ national swing since 2024** | **Weighted average** of 2024 state margin, generic ballot, approval (8 : 4 : 1) |
| **P(D ≥ 51)** | **58.5%** | **48.2%** |
| **Predicted D seats** | **51.2** (median 51, 80% range 48–55) | **50.5** (median 50, 80% range 47–55) |
| Same model with Kalshi weight 0 | 57.6%, 51.2 seats | 47.3%, 50.4 seats |
| Kalshi on its own | 63.5% (control market), 51.7 seats (sum of race odds) | same |

*Numbers as of 2026-10-26 from the data in `Data_Cache/` (VoteHub polls through Oct 22, Kalshi prices from Oct 26). They will change when you re-run with live data.*

**What changed in this version (v2)**
- Install cell at the top of each notebook (`%pip install` of everything that doesn't ship with Python, including `jinja2`, which the race table needs).
- Backtesting (`AS_OF_DATE`) no longer crashes when no polls fall in the window, and it no longer leaks the future. Only polls *published* by that date count, and **Kalshi prices are that day's closing prices**, pulled from Kalshi's price history.
- Pollsters VoteHub doesn't grade get a **random VoteHub grade, redrawn in every simulation**, instead of the lowest grade (section 2).
- Cosmetic: the mean-seats marker no longer hides the 51-seat line, and the Literal summary prints "62%" instead of "+0.62".

---

## Contents
1. [Folder layout and how to run](#1-folder-layout-and-how-to-run)
2. [What changed from Model 1](#2-what-changed-from-model-1)
3. [The two fundamentals formulas](#3-the-two-fundamentals-formulas)
4. [Why the variants disagree](#4-why-the-variants-disagree)
5. [Arguments for each](#5-arguments-for-each)
6. [Race-by-race comparison](#6-race-by-race-comparison)
7. [What the sweep says](#7-what-the-sweep-says)
8. [Backtesting](#8-backtesting)
9. [Known weaknesses](#9-known-weaknesses)
10. [Decisions for the group](#10-decisions-for-the-group)

---

## 1. Folder layout and how to run

```
Models/Model_Ozempic/
├── README.md                     <- this file
├── Data_Cache/                   <- last good API pulls (shared by both variants)
│   ├── votehub_senate_cache.csv
│   ├── votehub_generic_ballot_cache.csv
│   ├── votehub_approval_cache.csv
│   ├── kalshi_cache.csv          <- today's Kalshi prices
│   └── kalshi_history_cache.csv  <- daily Kalshi closes, only pulled when AS_OF_DATE is set
├── Ozempic_Swing/
│   ├── ozempic_swing.ipynb
│   └── Output/                   <- results for this variant
└── Ozempic_Literal/
    ├── ozempic_literal.ipynb
    └── Output/
```

Shared inputs in `Data/`:
- `pres_2024_results.csv`: Trump % and Harris % by state, plus a National row (certified results, from Wikipedia's results-by-state table)
- `votehub_pollster_scorecards.csv`: VoteHub's grade, percent error and house effect for the 42 pollsters it scores, with an `Aliases` column mapping them to the names VoteHub's poll API uses (for example, "Siena-NYT" ↔ "The New York Times/Siena University")

**To run:**
1. Run the **install cell** once per computer. Restart the kernel if it installed anything.
2. Edit `CONFIG` if you want.
3. *Run All*.

The notebook finds the repo root by walking up to the folder that contains `Data/`, so it works no matter where Jupyter starts.

Each run writes these files to its own `Output/`:

| File | What |
|---|---|
| `headline.json` | The two numbers, the no-Kalshi comparison, Kalshi's numbers, national signals, and the CONFIG used |
| `race_table.csv` | Every race: 2024 margin, polling average, fundamentals, Kalshi's implied margin, each source's share, final margin, P(win), Kalshi's P, rating |
| `polls_used.csv` | Every poll in the window, with each weighting factor and an `unrated` flag |
| `seat_distribution.csv` / `.png` | Seat histogram |
| `model_vs_kalshi.png` | Model P(win) vs Kalshi P(win) per race |
| `sensitivity_sweep.csv` / `sensitivity_tornado.png` | One-at-a-time sweep over CONFIG |

If VoteHub or Kalshi is unreachable, the notebook says so and falls back to `Data_Cache/`. Every successful pull refreshes the cache.

---

## 2. What changed from Model 1

| | Model 1 (Full Configs) | Ozempic |
|---|---|---|
| State polls | `Midterm_Polls.xlsx` (hand-entered) | **VoteHub API only** (`poll_type=us-senator`), per the meeting notes |
| Poll age | All polls, exponential decay (21-day half-life) | **Last 28 days only**, weight falls linearly from 100% today to 25% at day 28 |
| Combining sources | Bayesian: prior and polls weighted by precision | **Fixed weights: Polls 10 : Fundamentals 5 : Kalshi 1** |
| Fundamentals | PVI × 2 + national environment + incumbency (±2) | 2024 presidential margin based (two variants) + **incumbency ±3** |
| Kalshi | Not used | **Input at weight 1 plus a side-by-side comparison**; backtests use that day's prices |
| LV / RV / Adults | 1.0 / 0.85 / 0.7 | **1.0 / 0.9 / 0.8** (blackboard 100:90) |
| Partisan sponsor | Weight × 0.6 and shift 3 pts | **Shift 3 pts against the sponsor**, no weight penalty |
| Pollster quality | Spreadsheet rank 5–10; unrated = 5 | VoteHub grade → same 5–10 scale (A+ 10, A 9, B 8, C 7, D 6) |
| Accuracy | Column was blank, so no effect | VoteHub "percent error": `(median / pollster)²`, clipped to 0.5–2 |
| **Ungraded pollsters** | Fixed lowest rank (5) | **Random VoteHub grade + error, redrawn in every simulation** (below) |
| Same pollster polling a state repeatedly | Flood penalty `1/√k` | **None**: every poll counts on its own (the Alaska point from the meeting) |
| Number of settings | ~90 | **11 weights in CONFIG** (Swing) / 12 (Literal), plus `AS_OF_DATE` |

Carried over unchanged from Model 1: the Senate map, holdover seats, incumbent status, Osborn's 80% chance of caucusing with Democrats, the undecided-voter treatment, poll error constants, Student-t errors with a shared tail, and the region + lean correlation structure.

### How each race's number is built

```
polls_s   = weighted average of the state's polls in the last 28 days (after the partisan shift)
fund_s    = Swing or Literal formula (section 3)
kalshi_s  = Φ⁻¹(Kalshi P) × σ_s       <- the margin that would give Kalshi's probability under our own uncertainty

margin_s  = (10·polls_s + 5·fund_s + 1·kalshi_s) / 16       (weights renormalize if a source is missing)
```

A race with polls gets 62.5% polls, 31.25% fundamentals and 6.25% Kalshi. A race with no polls in the window (currently Colorado, Delaware, Oregon, New Jersey, Virginia, Kentucky, Louisiana, Tennessee, Oklahoma, Idaho, West Virginia, Wyoming) gets 83% fundamentals and 17% Kalshi.

### Ungraded pollsters: a random grade in every simulation

VoteHub grades only 42 pollsters. **31 pollsters in the current window aren't among them, accounting for 49 of its 89 polls** and about half of the poll weight. Examples include PPP, Mason-Dixon, Elon/YouGov, co/efficient and ActiVote. Model 1 and Ozempic v1 gave every one of these the lowest rank, which treats "no grade" as "bad grade".

With `UNRATED_POLLSTERS = "random"` (the default):
- **In each of the 10,000 simulations**, every ungraded *pollster* is assigned the grade **and** error of a randomly drawn VoteHub-graded pollster. All of that pollster's polls share the draw.
- The draws come from VoteHub's actual scorecard distribution: 3 A+, 8 A, 11 B, 9 C, 11 D.
- The state polling averages are recomputed with those weights before that simulation's election is drawn.
- Over 10,000 simulations, the uncertainty about how good these pollsters are shows up in the win probabilities, instead of as a fixed penalty.
- Tables and `polls_used.csv` show the **average** weight an ungraded poll gets (quality 0.76, accuracy 1.08, vs 0.5 and 1.0 before).

**Cost:** one 10,000 × 89 weight matrix and a matrix multiply. The whole notebook runs in about 2–3 seconds, so this adds nothing noticeable.

**Effect:** small: 58.0% → 58.5% (Swing), 47.7% → 48.2% (Literal). The weighting matters less than it sounds, because graded and ungraded pollsters mostly agree within each state.

**Assumption to be aware of:** ungraded pollsters are assumed to look like graded ones. If anything, VoteHub tends to grade established firms, so ungraded firms may be somewhat worse on average. Setting `"fixed"` restores the old behavior.

### Kalshi

Kalshi has markets for all 35 races. The notebook reads each race's Republican market and uses P(opposition) = 1 − P(R), which handles three-way races such as Nebraska (Osborn) and Montana (Bodnar). Kalshi's tickers are **not consistent**: Kentucky is under `SENATELA-26`, Louisiana under `KXSENATELA-26NOV`, and Florida and Ohio under `SENATEFLS-26` / `SENATEOHS-26`. Each race's ticker is therefore spelled out in `SETTINGS["KALSHI_EVENTS"]`; all 35 were checked by hand on Oct 26. At weight 1 of 16, Kalshi moves P(51+) by about one point. Its main use is the comparison.

---

## 3. The two fundamentals formulas

Notation: `margin2024_s` = Harris − Trump in the state; `GB` = generic-ballot margin (D − R, two-party); `AP` = approval converted to a margin = `0.35 × −(net approval)`; `inc` = ±3 toward an incumbent on the ballot, 0 for open seats.

Today's national inputs are the same in both variants: **GB = D+9.0** and **net approval −22.3 → AP = D+7.8**. Section 9 explains why these rest on stale data.

### Swing (`Ozempic_Swing`)

```
national_now = (2·GB + 1·AP) / 3                       = D+8.6
swing        = national_now − (Harris−Trump nationally, 2024 = R+1.5)   = +10.1 toward D
fund_s       = margin2024_s + swing + inc
```

This is a **uniform swing**: every state starts from its own 2024 result and moves by however much the country has moved since 2024. The weights (GB 2, approval 1) decide only how the two national signals average into "today's national environment".

### Literal (`Ozempic_Literal`)

```
fund_s = (8·margin2024_s + 4·GB + 1·AP) / 13 + inc
```

This is the blackboard formula taken at face value.

### Worked examples

| State | 2024 | Swing fundamentals | Literal fundamentals |
|---|---|---|---|
| Maine (Collins running, −3) | D+6.9 | 6.9 + 10.1 − 3 = **D+14.0** | (8·6.9 + 4·9.0 + 7.8)/13 − 3 = **D+4.6** |
| Texas (open) | R+13.7 | −13.7 + 10.1 = **R+3.6** | (8·−13.7 + 36 + 7.8)/13 = **R+5.0** |
| Wyoming (open) | R+45.8 | −45.8 + 10.1 = **R+35.7** | (8·−45.8 + 43.8)/13 = **R+24.8** |

---

## 4. Why the variants disagree

The two formulas treat the 2024 baseline differently.

- **Swing** passes the full national shift (+10.1) through to every state.
- **Literal** uses GB and approval as stand-ins for the state's own margin, with 5/13 ≈ 38% of the weight. It never subtracts 2024's national result, so in effect it does two things at once:
  1. It **shrinks every state's lean by 38% toward zero**. Wyoming's R+46 becomes R+25.
  2. It **adds only 38% of today's national margin**, not the full change since 2024.

Setting the two equal shows where they cross:

```
margin2024 + 10.1  =  (8·margin2024 + 43.8) / 13      →   margin2024 = R+17.5
```

- **For every state bluer than R+17.5 in 2024**, Literal is more Republican than Swing. That covers every competitive race this year.
- **For states redder than R+17.5**, Literal is more Democratic. Those races are Safe R either way.

That asymmetry explains the 10-point gap in P(51+). Literal costs Democrats ground exactly where control is decided and gives it back where it doesn't matter. Under Literal, a perfectly neutral national environment would still put Wyoming at only R+28 and Massachusetts at only D+15.

---

## 5. Arguments for each

**For Swing**
- It is the standard way fundamentals models use past results (uniform national swing). Its assumptions are easy to state: states keep their relative partisanship, and the map moves with the national mood.
- Units are consistent: a state margin plus a change in national margin is still a state margin. Literal averages a state number with two national numbers.
- The weights mean what they say: GB 2 : approval 1 is "how do we measure the national mood?"
- It matches the meeting priorities: 2024 state margin "heavily" (the full baseline), generic ballot "heavily", sentiment "weighted less".

**For Literal**
- It is exactly what we wrote on the board, which makes it easy to explain in the presentation.
- Shrinking toward the national average is a crude form of regression to the mean. 2024 was one candidate-specific election, and Senate races are less nationalized than presidential ones (Collins, Osborn, Peltola and Brown all run ahead of their party).
- It leans less on a single national number. If the generic ballot is overstating Democrats, Literal is hurt less.

**Caveat on both:** polls carry 62.5% of each race's margin, so the fundamentals formula matters most where polls are thin or disagree with fundamentals: Maine, Michigan and Minnesota (section 6).

A middle ground, if the group likes Literal's "don't trust 2024 completely" idea: Swing with a lower `W_FUNDAMENTALS`. The sweep shows P(51+) going from 58% to 67% when `W_FUNDAMENTALS` goes from 5 to 0.

---

## 6. Race-by-race comparison

| State | 2024 | Polls (28 d) | Fund. Swing | Fund. Literal | P(D) Swing | P(D) Literal | Kalshi |
|---|---|---|---|---|---|---|---|
| Maine | D+6.9 | D+1.6 | D+14.0 | D+4.6 | 93% | 77% | 60% |
| Michigan | R+1.4 | D+2.1 | D+8.7 | D+2.5 | 88% | 74% | 66% |
| Ohio | R+11.2 | D+4.4 | R+4.1 | R+6.5 | 69% | 61% | 68% |
| Minnesota | D+4.2 | D+3.9 | D+14.3 | D+6.0 | 96% | 88% | 84% |
| Texas | R+13.7 | D+2.1 | R+3.6 | R+5.0 | 53% | 47% | 64% |
| Iowa | R+13.2 | R+0.0 | R+3.1 | R+4.8 | 38% | 33% | 40% |
| Alaska | R+13.1 | D+0.6 | R+6.0 | R+7.7 | 36% | 31% | 75% |
| New Hampshire | D+2.8 | D+7.5 | D+12.9 | D+5.1 | 97% | 93% | 90% |
| Kansas | R+16.1 | R+1.1 | R+9.0 | R+9.5 | 20% | 19% | 40% |
| South Carolina | R+17.9 | R+1.0 | R+10.8 | R+10.6 | 16% | 17% | 21% |
| Nebraska (Osborn) | R+20.5 | R+3.1 | R+13.4 | R+12.2 | 7% | 8% | 26% |
| North Carolina | R+3.2 | D+10.7 | D+6.9 | D+1.4 | 99% | 97% | 97% |
| Georgia | R+2.2 | D+8.4 | D+10.9 | D+5.0 | 98% | 96% | 94% |

What stands out:
- **Maine and Michigan** account for most of the gap between the variants. Polls are close, but under Swing the 2024 baseline plus a D+10 swing is a comfortable Democratic lead. Swing is far more confident than Kalshi in both.
- **Alaska** is the biggest model-vs-market gap in both variants: Kalshi has Peltola at 75%, the model at 31–36%. The polls are tied, but the R+13 baseline and Sullivan's incumbency pull the fundamentals to about R+6 to R+8. This is the "candidate quality" case Kalshi was meant to catch. At weight 1/16 it can't move it much.
- **Texas, Kansas and Nebraska** also have Kalshi more bullish on Democrats than either variant.
- Near R+17.5 (South Carolina, Nebraska, Kansas) the variants agree, as section 4 predicts.

---

## 7. What the sweep says

Each CONFIG weight is changed one at a time with 3,000 simulations. The range shown is the P(D ≥ 51) span across the values tried.

| Setting (values tried) | Swing | Literal |
|---|---|---|
| `W_FUNDAMENTALS` (0, 2.5, 5, 10) | 47–67% | 35–67% |
| `W_POLLS` (5, 10, 20) | 48–65% | 36–58% |
| `W_GENERIC_BALLOT` | 55–59% (0–4) | **26–61% (0–8)** |
| `W_STATE_2024` (Literal: 4–32) | — | **28–63%** |
| `W_APPROVAL` (0–2) | 58–60% | 44–52% |
| `INCUMBENCY_PTS` (0–5) | 55–64% | 44–54% |
| `W_KALSHI` (0–5) | 58–63% | 47–52% |
| `WINDOW_DAYS` (14–42) | 56–59% | 45–49% |
| `WINDOW_OLDEST_WEIGHT` (0–1) | 58–61% | 48–49% |
| `UNRATED_POLLSTERS` (fixed / random) | 58–59% | 48–49% |
| `POPULATION_WEIGHTS`, `PARTISAN_SHIFT` | < 1 pt | < 1 pt |

Literal is very sensitive to its fundamentals weights, because they change both how much state lean is kept *and* how much of the national environment gets through. Swing barely reacts to GB vs approval because both national signals currently say about D+8 to D+9. In both variants the polls-vs-fundamentals balance is the biggest lever.

(The 42-day window here looks almost the same as 28 days only because the snapshot cache starts on Sep 24. A live run pulls the full history.)

---

## 8. Backtesting

Set `AS_OF_DATE` (e.g. `"2026-10-01"`) to see what the model would have said on that date:

- **Polls:** only polls that *ended* by that date **and** were *published* by it (VoteHub's `created_at`) count. Without the second check, a poll fielded Sep 28 but released Oct 3 would leak into an Oct 1 run.
- **Generic ballot and approval:** same rule.
- **Kalshi:** the notebook pulls each market's daily price history (`candlesticks` endpoint, one call per market, cached in `kalshi_history_cache.csv`) and uses the **last close on or before that date** (bid/ask midpoint, or last trade if the book was empty). A market with no trades yet by then simply drops out of that race, and the weights renormalize.
- **No polls in the window:** if the date is earlier than any poll, every race runs on fundamentals and Kalshi alone instead of crashing.

Checked with the snapshot data: Aug 1, Sep 15, Oct 1 and Oct 15 all run. On Oct 1, Maine's Kalshi input is 58.5% (that day's close) rather than today's 59.5%. The snapshot only holds Kalshi closes for Sep 15, Oct 1 and Oct 15; a live run pulls every day since `KALSHI_HISTORY_START` (Jun 1).

**Limits:** the pollster grades, nominee list and 2024 results are today's versions, so a backtest isn't a perfectly blind re-run. That's fine for these inputs, since none of them changed in October.

---

## 9. Known weaknesses

Ranked by how much they could move the answer.

1. **VoteHub's national polls dried up after June.** Your live pull has the full history, and the monthly counts are:

   | Month | Jan–Jun (avg) | Jul | Aug | Sep | Oct |
   |---|---|---|---|---|---|
   | Approval polls | ~61 | 0 | 7 | 0 | 2 |
   | Generic-ballot polls | ~49 | 1 | 5 | 4 | 2 |

   Only 2 approval and 3 generic-ballot polls fall in the 4-week window, so each signal falls back to its 5 most recent polls. Approval currently rests on polls from Aug 24 to Oct 6. VoteHub still publishes an up-to-date *average* on its website (Kalshi has markets that settle on it), so the polls exist; the API just isn't carrying them. The old `National_Polls.xlsx` had 34 approval polls from Sep 21 to Oct 14. Both national signals feed the fundamentals, which carry 31% of every race, so this is the weakest input. DadBod is meant to address it.
2. **Fixed weights ignore how many polls a race has.** Rhode Island (1 poll) gets the same 62.5% poll weight as Texas (14 polls). Model 1's precision weighting handled this automatically; fixed weights can't.
3. **Race SD assumes polls, fundamentals and Kalshi make independent errors.** They are correlated (Kalshi traders read the same polls), so the stated uncertainty is somewhat too small and win probabilities somewhat too confident. The resulting SDs (about 4–5 pts with polls, 6.4 without) are close to Model 1's, so the two remain comparable.
4. **Ungraded pollsters are assumed to look like graded ones** (section 2). If ungraded firms are worse on average, the random draw gives them too much weight. The sweep shows this changes P(51+) by under 1 point.
5. **Kalshi as a margin.** Converting a probability to a margin uses the model's own race SD. Markets above 99% are clipped, which slightly pulls safe races toward the middle; none of those races are close.
6. **"Percent Error" on VoteHub's scorecard** is used only *relative* to the median pollster, because VoteHub doesn't say whether it is error on vote share or on margin.
7. **Nominee table.** VoteHub lists candidates by name, not party, so each poll is matched to `SETTINGS["NOMINEES"]` by surname. Idaho, Montana and South Dakota use "highest-polling non-Republican" (the Sheet2 independent rule). Polls without both nominees are dropped (none in the current window).
8. **Independents other than Osborn** (Bodnar, Bengs, Achilles) count as Democratic seats if they win. All three are below 10% on Kalshi.
9. **Partisan national polls** (generic ballot and approval) are weighted × 0.6, a hard-coded Model 1 constant, while partisan *state* polls get the 3-point shift instead. This is minor, since VoteHub marks almost no national polls as partisan.

---

## 10. Decisions for the group

1. **Swing or Literal.** Swing currently gives 58.5% / 51.2 seats; Literal gives 48.2% / 50.5.
2. **Polls 10 : Fundamentals 5.** This balance moves the answer more than anything else, and fixed weights can't account for how many polls a race has (weakness 2).
3. **Kalshi weight.** At weight 1 it is effectively a comparison. To visibly account for "events and candidate quality" (Alaska, Texas, Nebraska) it would need roughly weight 3–5; the sweep shows P(51+) going from 58% to 63% (Swing) at weight 5.
4. **National data** (weakness 1): stay VoteHub-only, add `National_Polls.xlsx` back for approval, or use the Kalshi-implied averages.
5. **Incumbency for appointed senators** (Moody, Husted, Darline Graham): currently the full 3 pts, the same as elected incumbents. Model 1 gave them half.
