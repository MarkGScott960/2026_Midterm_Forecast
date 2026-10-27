# Model 3: DadBod — Swing vs Literal

DadBod is the third forecast model. It is as slim as Ozempic, with a short list of team-set weights at the top, but it adds safeguards:

- it trusts a race's polls more when the race has more of them
- it penalizes one pollster flooding a race
- it corrects for pollsters' known leans
- it allows for polls, fundamentals and Kalshi making the same mistake
- it finds the Kalshi markets on its own
- it uses Kalshi's live polling averages as an extra source for the national numbers

Every model run has a companion **`Model Testing.ipynb`** notebook that checks the data and stress-tests the settings.

It reports two numbers:
1. **P(Democrats hold at least 51 seats).** With a Republican vice president breaking ties, Democrats need 51 for control.
2. **The predicted number of Democratic seats.** This is the average over all simulated elections, counting independents who caucus with Democrats.

Like Ozempic, DadBod comes in two variants that are **identical except for the "fundamentals"**, the expectation for a race before looking at its polls.

| | DadBod_Swing | DadBod_Literal |
|---|---|---|
| Fundamentals | 2024 state result **+ national swing since 2024** | **Weighted average** of 2024 state result, generic ballot and approval (8 : 4 : 1) |
| **P(D ≥ 51)** | **58.3%** | **46.6%** |
| **Predicted D seats** | **51.2** (median 51, 80% range 48–55) | **50.3** (median 50, 80% range 46–54) |
| Same model, Kalshi weight 0 | 57.3%, 51.2 seats | 45.1%, 50.2 seats |
| Kalshi on its own | 63.5% (control market), 51.7 seats (sum of race odds) | same |

*Run on Oct 26 from the saved data in `Data_Cache/`. Re-run for live numbers.*

---

## Contents
1. [Folder layout and how to run](#1-folder-layout-and-how-to-run)
2. [The model in plain English](#2-the-model-in-plain-english)
3. [Every setting, explained](#3-every-setting-explained)
4. [Notes on specific features](#4-notes-on-specific-features)
5. [Swing vs Literal: differences, pros and cons](#5-swing-vs-literal-differences-pros-and-cons)
6. [Race-by-race comparison](#6-race-by-race-comparison)
7. [Model Testing notebook](#7-model-testing-notebook)
8. [How DadBod differs from Model 1 and Ozempic](#8-how-dadbod-differs-from-model-1-and-ozempic)
9. [Re-running, and the 9 AM election-day run](#9-re-running-and-the-9-am-election-day-run)
10. [Known weaknesses](#10-known-weaknesses)

---

## 1. Folder layout and how to run

```
Models/DadBod_Model/
├── README.md                         <- this file
├── Data_Cache/                       <- last good download of every source (shared by both variants)
│   ├── votehub_senate_cache.csv          state Senate polls
│   ├── votehub_generic_ballot_cache.csv  generic-ballot polls
│   ├── votehub_approval_cache.csv        Trump approval polls
│   ├── kalshi_races_cache.csv            every race's Kalshi markets (names + prices) + Senate-control market
│   ├── kalshi_national_cache.csv         Kalshi's approval / generic-ballot polling-average markets
│   └── kalshi_history_cache.csv          daily Kalshi closes (only pulled for backtests)
├── DadBod_Swing/
│   ├── dadbod_swing.ipynb            the model
│   ├── Model Testing.ipynb           checks, diagnostics, stress tests, trajectory
│   └── Output/                       results (+ Output/testing/ from Model Testing)
└── DadBod_Literal/  (same three items)
```

**To run:**
1. Open the variant's model notebook, run the **install** cell once per computer, and restart the kernel if it installed anything.
2. Edit **CONFIG** if you want; the cell after it shows the formula with your numbers filled in.
3. *Run All.*
4. Open **`Model Testing.ipynb`** in the same folder and *Run All*. It runs the model notebook itself first, so it always tests the current code and settings.

Each takes well under a minute; Model Testing takes about 15 seconds after the first run.

**Outputs (`Output/`):**

| File | What |
|---|---|
| `headline.json` | The two numbers, the no-Kalshi version, Kalshi's numbers, the national signals, which sources were live vs saved copies, and the exact CONFIG |
| `race_table.csv` | Every race: polls, effective number of polls, reliability, fundamentals, Kalshi margin, each source's share, final margin, uncertainty, P(win), Kalshi P, rating |
| `polls_used.csv` | Every poll in the window with each weighting factor, house effect and adjustment |
| `national_signals.csv` | The generic ballot and net approval: VoteHub polls, Kalshi average, how each was weighted, and the combined value |
| `seat_distribution.csv` / `.png`, `model_vs_kalshi.png` | Charts |
| `testing/` | From Model Testing: `checks.csv`, `coverage.csv`, `sensitivity_sweep.csv`, `sensitivity_tornado.png`, `toggles.csv`, `trajectory.csv` / `.png` |

---

## 2. The model in plain English

**The question:** in each of 35 Senate races, by how much will the Democrat (or a credible independent) beat or lose to the Republican? Then, across all 35, how often do Democrats reach 51 seats?

**Three sources of evidence for each race:**
1. **Polls:** a weighted average of the race's recent polls (last 28 days).
2. **Fundamentals:** what we'd expect with *no* polls, based on how the state voted in 2024, the national mood, and whether an incumbent is running.
3. **Kalshi:** the prediction market's win probability for the race, turned into a margin.

**Blending them:**

$$\text{margin} = \frac{W_P \cdot r \cdot \text{polls} + W_F \cdot \text{fundamentals} + W_K \cdot \text{Kalshi}}{W_P \cdot r + W_F + W_K}$$

| Symbol | Meaning | Default |
|---|---|---|
| W_P, W_F, W_K | How much the team trusts polls, fundamentals and Kalshi | 10, 5, 1 |
| r | **Poll reliability**, 0 to 1: how much of W_P a race earns given how much polling it has | `"auto"` |

So a heavily polled race is about 60% polls, 33% fundamentals and 7% Kalshi. A race with one poll is about 43% polls, and a race with none is 83% fundamentals and 17% Kalshi.

**From margins to seats:**
- Each race's margin gets an **uncertainty range**, which is wider when the evidence is thin or the sources disagree.
- The model then **simulates the election 10,000 times**. In each simulation every race is drawn from its range, and related states move together: a national swing hits everyone, and states in the same region or with similar politics move more alike.
- Counting Democratic seats in each simulation gives **P(51+)** (the share of simulations with 51 or more) and the **predicted seats** (the average).

Every step in the notebook starts with a plain-English explanation, and there is a glossary at the top.

---

## 3. Every setting, explained

All of these are in the **CONFIG** cell at the top of each model notebook. **Weights are relative:** 10 / 5 / 1 means the same as 20 / 10 / 2.

### Run
| Setting | Default | What it means | Raise it → | Lower it → |
|---|---|---|---|---|
| `AS_OF_DATE` | `None` (today) | Run the model as if it were an earlier date (backtest) | — | — |
| `N_SIMS` | 10,000 | Number of simulated elections | Smoother numbers, slower (10k ≈ ±0.5 pt on P(51+)) | Faster, noisier |

### The blend
| Setting | Default | What it means | Raise it → | Lower it → |
|---|---|---|---|---|
| `W_POLLS` | 10 | Trust in each race's own polls | Polls dominate | Fundamentals and Kalshi matter more |
| `W_FUNDAMENTALS` | 5 | Trust in the "no polls" expectation | Results pulled toward 2024 + national mood | Polls matter more |
| `W_KALSHI` | 1 | Trust in Kalshi's race market (low on purpose) | Model moves toward the market | 0 = Kalshi shown for comparison only |
| `POLL_RELIABILITY` | `"auto"` | How poll trust grows with the number of polls (section 4) | A number k: higher k = more polls needed to earn full trust | `0` = off |

### Which polls count
| Setting | Default | What it means |
|---|---|---|
| `WINDOW_DAYS` | 28 | Only polls that **ended** in the last 28 days count |
| `WINDOW_OLDEST_WEIGHT` | 0.25 | A poll 28 days old counts 25% as much as today's; weight falls in a straight line in between. 1.0 = no age penalty within the window; 0 = fades to nothing |

### How much each poll counts
| Setting | Default | What it means |
|---|---|---|
| `POPULATION_WEIGHTS` | LV 1.0 : RV 0.9 : A 0.8 | Likely voters : registered voters : all adults. All adults is lowest because many adults don't vote. |
| `REFERENCE_SAMPLE` | 800 | A poll this size gets sample-size weight 1.0. Only rescales every poll by the same factor; doesn't change which polls count more. |
| `SAMPLE_SIZE_EXPONENT` | 0.5 | Sample-size weight = (n ÷ 800)^0.5. 0.5 (square root) is the statistics default, since poll error shrinks with √n, so a 3,200-person poll counts 2×, not 4×, an 800-person poll. 0 = ignore size; 1 = proportional to size. |
| `SAMPLE_SIZE_CAP` | 2,500 | Bigger polls count as 2,500, so huge online panels can't dominate |
| `MISSING_SAMPLE_SIZE` | 600 | Size assumed when a poll doesn't report one |
| `FLOOD_EXPONENT` | 0.5 | A pollster with k polls of the same race gets 1/k^0.5 per poll, so together they count like √k polls. 0 = no penalty; 1 = the pollster counts once in total. Every poll still counts (the Alaska point from the meeting); a repeat pollster just can't drown out the others. |
| `PARTISAN_SHIFT` | 3.0 | Points moved against the sponsor of a party/campaign poll |
| `UNRATED_POLLSTERS` | `"random"` | How pollsters VoteHub hasn't graded are treated (section 4) |
| `HOUSE_EFFECTS` | `True` | Subtract each graded pollster's known lean (section 4) |

### National signals
| Setting | Default | What it means |
|---|---|---|
| `NAT_KALSHI_POLL_EQUIV` | 5 | How many polls Kalshi's polling averages count as when blended with VoteHub's national polls (section 4) |

### Fundamentals (differ by variant)
| Variant | Setting | Default | What it means |
|---|---|---|---|
| Swing | `W_GENERIC_BALLOT` | 2 | Weight of the generic ballot in "today's national mood" |
| Swing | `W_APPROVAL` | 1 | Weight of approval in "today's national mood" |
| Literal | `W_STATE_2024` | 8 | Weight of the state's 2024 presidential margin |
| Literal | `W_GENERIC_BALLOT` | 4 | Weight of the generic ballot |
| Literal | `W_APPROVAL` | 1 | Weight of approval |
| both | `INCUMBENCY_PTS` | 3.0 | Points toward the party of an incumbent on the ballot (elected or appointed). Open seats get 0. |

### Uncertainty
| Setting | Default | What it means |
|---|---|---|
| `CORRELATED_ERRORS` | `True` | Assume polls, fundamentals and Kalshi tend to miss in the same direction (section 4) |
| `SOURCE_ERROR_CORR` | 0.3 | How strongly they miss together when on (0 = independent, 1 = identical) |

Fixed constants live in **SETTINGS**: error sizes carried over from Model 1, the Senate map, API addresses, and the fallback tables. They're documented in the notebook but not meant for tuning.

---

## 4. Notes on specific features

### Poll reliability (`POLL_RELIABILITY`)
A race with one poll shouldn't trust it as much as a race with fifteen. Each race's poll weight is `W_POLLS × r`.

| Setting | Formula | 1 poll | 3 polls | 9 polls | When to use |
|---|---|---|---|---|---|
| `"auto"` (default) | r = 4.5² / (5² ÷ n_eff + 4.5²) | 45% | 71% | 88% | **Best practice.** Comes from the model's own error sizes: one poll misses by about 5 points, and all of a state's polls share a 4.5-point error that never averages away. So more polls help, with diminishing returns. Same logic as Model 1's Bayesian weighting. |
| a number k, e.g. `3` | r = n_eff / (n_eff + k) | 25% | 50% | 75% | A simpler rule of thumb: "half trust at k polls". Higher k is stricter. |
| `0` | r = 1 | 100% | 100% | 100% | Off: any polling gets the full weight (Ozempic's behavior) |

`n_eff` is the **effective** number of polls: 3 equally weighted polls = 3, while 1 heavy poll plus 2 light ones ≈ 1.5. The sweep shows this setting moves P(51+) between 53% and 61% (Swing).

### Ungraded pollsters get a random grade, redrawn in every simulation
VoteHub grades only 42 pollsters. In the current window **31 firms (49 of 89 polls) are ungraded**, including PPP, Mason-Dixon, Elon/YouGov, co/efficient and ActiVote. With `UNRATED_POLLSTERS = "random"`:

- **In every single simulation**, each ungraded *firm* is given the grade, accuracy **and lean** of a randomly picked VoteHub-graded firm. All of that firm's polls share the pick.
- **The next simulation draws again.** Over 10,000 simulations, the firm is sometimes treated as an A+ pollster and sometimes as a D, in proportion to how common each grade is (3 A+, 8 A, 11 B, 9 C, 11 D).
- The effect is that our uncertainty about these firms shows up in the probabilities, instead of a fixed penalty for not being graded.
- Tables show the *average* weight an ungraded poll gets.
- **Assumption:** ungraded firms are assumed to look like graded ones. `"fixed"` gives them the lowest grade instead (Model 1's behavior). The sweep shows the choice moves P(51+) by about 1 point.

### House effects (`HOUSE_EFFECTS`)
VoteHub's scorecard lists each graded pollster's typical lean (SurveyUSA D+2.3, Trafalgar R+1.4, Quantus R+1.0, Change Research D+1.3, …). With this on, that lean is subtracted from the firm's polls. Partisan-sponsored polls are skipped, since they already get `PARTISAN_SHIFT`. Ungraded firms get the lean of their random draw. **Effect today:** margins move by 0.5 points at most, and P(51+) moves by under 1 point.

### Correlated errors (`CORRELATED_ERRORS`, `SOURCE_ERROR_CORR`)
When the polls miss, Kalshi traders, who read the same polls, and the fundamentals usually miss the same way. Treating the three as independent makes the model **overconfident**. With this on (ρ = 0.3), each race's range is about 15% wider: the average race SD goes from 5.1 to 5.7 points. **Effect today:** close races move toward 50-50 (Maine 94% → 92% in Swing), and P(51+) barely moves, because the extra uncertainty pushes in both directions.

### The two toggles together
`HOUSE_EFFECTS` changes each poll's **margin**; `CORRELATED_ERRORS` changes each race's **uncertainty**. They don't interact, so **both, either, or neither can be on**:

| HOUSE_EFFECTS | CORRELATED_ERRORS | Meaning | P(D ≥ 51), Swing | P(D ≥ 51), Literal |
|---|---|---|---|---|
| off | off | Raw polls, sources treated as independent | 57.4% | 44.9% |
| off | on | Raw polls, honest (wider) uncertainty | 57.2% | 46.0% |
| on | off | Lean-corrected polls, narrower uncertainty | 58.4% | 45.5% |
| **on** | **on** | **Default:** lean-corrected polls, honest uncertainty | **57.9%** | **46.3%** |

*(3,000-simulation runs from Model Testing, section E2.)*

### National signals: Kalshi averages as an additional source (`NAT_KALSHI_POLL_EQUIV`)
The generic ballot and approval feed the fundamentals. VoteHub's feed of national polls nearly dried up after June: approval went from about 61 polls a month to 0–7, and the generic ballot from about 49 to 1–5. So DadBod adds **Kalshi's polling-average markets as a second, always-on source**:
- RCP approval (`KXTRUMPAPPROVE`)
- VoteHub approval (`KXTRUMPVH`)
- VoteHub generic ballot (`KXGENERICBALLOTVOTEHUB`)

The open market in each series is found automatically each run.

**How they're combined:** for each signal,

$$\text{signal} = \frac{n_{\text{polls}} \cdot \text{VoteHub poll average} + K \cdot \text{Kalshi average}}{n_{\text{polls}} + K}$$

- n_polls is the effective number of VoteHub polls used.
- **K = `NAT_KALSHI_POLL_EQUIV` (default 5)**: the Kalshi average counts as much as 5 polls.

**To change it:** set `NAT_KALSHI_POLL_EQUIV` in CONFIG. Higher (e.g. 20) leans mostly on the market averages; `0` ignores them and uses VoteHub polls only. Today, polls say D+9.2 on the generic ballot and Kalshi says D+10.1, giving a combined D+9.7. Net approval is −22.3 from polls and −21.4 from Kalshi, giving −21.8. The sweep shows K moves P(51+) by under 2 points.

**RCP and VoteHub approval are combined *before* Kalshi is blended with the polls.** Both are Kalshi markets tracking mostly the same polls, so they're averaged into one "Kalshi approval" number first. That single number is then blended with VoteHub's approval polls at weight K.

**Reading a value out of a Kalshi market:**
- *Bucket markets* (RCP: "38.2%? 38.3%? …"): the probability-weighted middle of the buckets.
- *Weekly "above X%?" markets* (VoteHub): X + Φ⁻¹(price) × 0.5 pts. A price of 0.50 means the average is at X; 0.62 means a little above. The 0.5 is `KALSHI_UPDOWN_SD`, a typical week's move.

**How approve % becomes net approval:** the Kalshi approval markets give only **approve %**, but the model uses **net approval** (approve − disapprove). Disapprove is estimated from the share of people who answer neither:

$$\text{disapprove} = 100 - \text{approve} - U, \qquad \text{net} = 2 \times \text{approve} - 100 + U$$

**U** is the average of (100 − approve − disapprove) in VoteHub's approval polls from the last 90 days, or the last 10 polls if there are fewer. It's measured fresh each run (3.3 points today). Example: Kalshi approve 37.6% → disapprove 100 − 37.6 − 3.3 = 59.1% → net −21.5.

**Generic ballot conversion:** VoteHub's average is the raw D − R gap. The model uses the two-party gap, so the raw gap is scaled by 100 ÷ (D% + R%), with D% + R% averaged over recent VoteHub generic-ballot polls (about 90).

**Backtests** skip the Kalshi national averages and use polls only (agreed). Kalshi doesn't keep reliable history for these short-lived weekly markets.

### Kalshi markets are found automatically
Kalshi's market codes are inconsistent: Kentucky's race is `SENATELA-26` ("LA" = Louisiana!) and Louisiana's is `KXSENATELA-26NOV`. So each run:
1. Lists Kalshi's Senate-tagged series.
2. Finds events titled **"*State* Senate winner?"** for 2026. That matches by the title Kalshi shows people, not the code. If Kalshi has two events for one race, the busier one is used.
3. Takes **nominee names** from the market names. For Alaska, Kalshi lists "Republican party / Democratic party", so the hand table supplies Peltola and Sullivan.
4. Finds the Senate-control market the same way.

The hand tables in SETTINGS (`KALSHI_EVENTS_FALLBACK`, `NOMINEES_FALLBACK`) are **only a check and a backup**. Model Testing flags any race where the search found something different from the table, or had to fall back to it. **If a nominee ever changes, the search picks it up automatically.**

### Adults weight (0.8)
All-adult samples include many non-voters, so they count 0.8, below registered voters (0.9) and likely voters (1.0). This matches Model 1's national-poll setting and Ozempic. Change it in `POPULATION_WEIGHTS`. The sweep shows LV:RV:A weighting barely moves the result, because about 95% of recent Senate polls are LV.

---

## 5. Swing vs Literal: differences, pros and cons

The variants differ **only** in the fundamentals:

**Swing:**
$$\text{fund} = \text{2024 state margin} + (\text{today's national mood} - \text{2024 national margin}) \pm \text{incumbency}$$
Today: national mood D+9.0, 2024 nationally R+1.5, so **every state moves 10.5 points toward Democrats**.

**Literal:**
$$\text{fund} = \frac{8 \cdot \text{2024 state margin} + 4 \cdot \text{generic ballot} + 1 \cdot \text{approval margin}}{13} \pm \text{incumbency}$$

| State (2024) | Swing fundamentals | Literal fundamentals |
|---|---|---|
| Maine (D+6.9, Collins running) | D+14.4 | D+4.8 |
| Texas (R+13.7, open) | R+3.2 | R+4.9 |
| Wyoming (R+45.8, open) | R+35.3 | R+24.6 |

**Why they disagree.** Literal treats two *national* numbers as if they were state results. In effect it (a) keeps only 8/13 ≈ 62% of each state's own lean and (b) passes through only 38% of today's national mood. The two formulas give the same answer for a state that voted about **R+17.5** in 2024:
- **Bluer than that** (every competitive race this year): Literal is more Republican.
- **Redder than that** (all Safe R): Literal is more Democratic, which wins nothing.

That's the whole ~12-point gap in P(51+).

| | **Swing** | **Literal** |
|---|---|---|
| **Pros** | Standard method in forecasting (uniform national swing). Units are consistent: a state margin plus a change in national margin is still a state margin. Matches the meeting priorities: 2024 margin "heavily" as the full baseline, generic ballot "heavily", sentiment "less". Few weights, and they're insensitive (generic ballot vs approval moves P(51+) only 52–59%), because both national signals agree. | Exactly the blackboard formula, easy to present. Partly "forgets" 2024, a crude regression to the mean: 2024 was one candidate-specific election, and Senate candidates (Collins, Osborn, Peltola, Brown) often run ahead of their party. Leans less on the national mood, so it's hurt less if the generic ballot is overstating Democrats. |
| **Cons** | Assumes every state moves by the same amount; real swings vary by state. Relies fully on the national mood being measured correctly (the thinnest data we have; section 10). | Mixes state and national numbers, so safe states drift toward 50-50 (a neutral year would put Wyoming at R+28 and Massachusetts at D+15). Systematically more Republican in exactly the competitive races. **Very sensitive to its own weights:** the 2024 and generic-ballot weights each move P(51+) between about 25% and 60%. |
| **Today** | 58.3%, 51.2 seats | 46.6%, 50.3 seats |
| **Closest to Kalshi (63.5%)?** | Yes, about 5 points below | About 17 points below |

**Middle ground**, if the group likes Literal's "don't fully trust 2024" idea: use Swing with a lower `W_FUNDAMENTALS`, or a stricter `POLL_RELIABILITY`. Both are in the sweep.

---

## 6. Race-by-race comparison

| State | Polls (n) | r | Polls | Fund. Swing | Fund. Literal | P(D) Swing | P(D) Literal | Kalshi |
|---|---|---|---|---|---|---|---|---|
| Maine | 6 | 77% | D+1.4 | D+14.4 | D+4.8 | 93% | 75% | 60% |
| Michigan | 7 | 80% | D+2.2 | D+9.1 | D+2.7 | 87% | 73% | 66% |
| Ohio | 10 | 86% | D+4.4 | R+3.7 | R+6.3 | 66% | 57% | 68% |
| Minnesota | 3 | 69% | D+3.3 | D+14.7 | D+6.2 | 95% | 85% | 84% |
| Texas | 14 | 90% | D+2.3 | R+3.2 | R+4.9 | 55% | 49% | 64% |
| Iowa | 9 | 86% | D+0.1 | R+2.7 | R+4.6 | 41% | 35% | 40% |
| Alaska | 3 | 65% | D+0.7 | R+5.7 | R+7.5 | 36% | 29% | 75% |
| New Hampshire | 1 | 45% | D+7.6 | D+13.3 | D+5.3 | 97% | 91% | 90% |
| Kansas | 1 | 45% | R+0.4 | R+8.6 | R+9.4 | 17% | 16% | 40% |
| South Carolina | 1 | 45% | R+0.4 | R+10.4 | R+10.4 | 13% | 13% | 21% |
| Nebraska (Osborn) | 2 | 61% | R+3.0 | R+13.0 | R+12.0 | 9% | 10% | 26% |
| North Carolina | 7 | 82% | D+10.7 | D+7.3 | D+1.6 | 98% | 95% | 97% |
| Georgia | 4 | 75% | D+8.7 | D+11.3 | D+5.2 | 97% | 95% | 94% |

What stands out:
- **Poll reliability at work:** Kansas and South Carolina have one poll each. Both polls are nearly tied, but at r = 45% the fundamentals (R+9 to R+10) pull them to Likely R.
- **Alaska** is the biggest model-vs-market gap: polls tied, fundamentals R+6 to R+8, Kalshi 75% for Peltola. **Maine** is the other one, where Swing (93%) is far more confident than Kalshi (60%). Both are flagged in Model Testing.
- **Maine and Michigan** account for most of the Swing–Literal gap.

---

## 7. Model Testing notebook

Each variant has its own `Model Testing.ipynb`. It runs the model notebook first, then:

| Section | What it does |
|---|---|
| **A. Data checks** | Was each source downloaded live or read from a saved copy? How old are the newest state and national polls? Did the Kalshi search find all 35 races, and does it agree with the hand table? Are nominees from Kalshi? How many polls were dropped for missing nominees? How much weight comes from ungraded pollsters? How much data is behind each national signal? |
| **B. Model sanity checks** | Probabilities between 0 and 1, source shares add to 100%, possible seat counts, mean seats = sum of race probabilities, simulation noise on P(51+) |
| **C. Coverage by race** | Polls, effective polls, reliability and newest poll for every race. Flags contested races (Kalshi 15–85%) with under 3 effective polls or nothing in 14 days. |
| **D. Disagreements with Kalshi** | Races where model and market differ by over 25 points |
| **E1. Sensitivity sweep** | Every setting varied one at a time, with a tornado chart |
| **E2. Toggles** | All four HOUSE_EFFECTS × CORRELATED_ERRORS combinations |
| **E3. Seeds** | The full model re-run with 5 random seeds, to show simulation noise |
| **F. Trajectory** | Weekly backtests since Sep 7, each using only the polls released by then and that day's Kalshi race prices, charted against Kalshi's own control odds |
| **G. Summary** | Every check as PASS / WARN / FAIL, saved to `Output/testing/checks.csv` |

**Current results:** 24 PASS, 13 WARN (Swing) / 12 WARN (Literal), 0 FAIL. The WARNs are:
- **Expected in my workspace:** saved copies used because I can't reach the APIs, and a VoteHub generic-ballot poll 22 days old.
- **Real flags:** thin polling in Alaska, Kansas, Minnesota, Nebraska and South Carolina; and the Alaska (and in Swing, Maine) disagreements with Kalshi.

**Most influential settings (Swing):** `W_FUNDAMENTALS` (49–68%), `W_POLLS` (50–64%), `INCUMBENCY_PTS` (54–64%), `POLL_RELIABILITY` (53–61%).
**For Literal:** `W_GENERIC_BALLOT` and `W_STATE_2024` (each about 24–61%), then `W_FUNDAMENTALS` (36–68%).

**Trajectory (Swing):** 19% on Sep 7 → 42% on Sep 28 → 55% on Oct 5 → 58% now. Kalshi went from 55% to 64% over the same period. The early weeks run on fundamentals alone in the snapshot data, which only holds polls from Sep 24; a live run has the full poll history.

---

## 8. How DadBod differs from Model 1 and Ozempic

| | Model 1 | Ozempic | **DadBod** |
|---|---|---|---|
| State polls | Adler spreadsheet | VoteHub API | VoteHub API |
| Poll window | all, 21-day half-life | 28 days, linear fade | 28 days, linear fade (configurable) |
| Polls vs fundamentals | Bayesian precision | fixed 10 : 5 : 1 | 10 : 5 : 1 **× poll reliability** |
| Sample-size weight | √(n/800), cap 2,500 | same, fixed | same, **every piece configurable** |
| Flooding penalty | 1/√k | none | **1/k^0.5, configurable** |
| House effects | off (estimated, optional) | none | **VoteHub scorecard leans, on/off** |
| Ungraded pollsters | lowest grade | random grade per simulation | random grade **+ lean** per simulation |
| National signals | spreadsheet approval + VoteHub generic ballot | VoteHub polls only | VoteHub polls **+ Kalshi averages (K = 5)** |
| Kalshi races | — | input + comparison, hand-coded tickers | input + comparison, **found automatically** |
| Source errors | — | independent | **correlated (on/off)** |
| Testing | in-notebook sweep | in-notebook sweep | **separate Model Testing notebook** |
| P(D ≥ 51) today | 64.6% | 58.5% / 48.2% | 58.3% / 46.6% |

---

## 9. Re-running, and the 9 AM election-day run

The models will be re-run repeatedly, with the final run at **9 AM on Nov 3**.

- **Leave `AS_OF_DATE = None`.** On election day the days-to-election term drops to zero, so the last run carries no allowance for opinion shifting before the vote and will be a little more confident than earlier runs. That's correct, not a bug.
- **Run on a computer with internet access** (your machine). Each run downloads fresh polls and Kalshi prices and refreshes `Data_Cache/`. Check Model Testing section A: every source should say **live**.
- **Each run overwrites `Output/`.** To keep the published 9 AM numbers, copy `Output/` somewhere, or use the `run_all` script we'll build next.
- **Scheduled run (not set up; noted for later).** To fire automatically at 9 AM you'd need:
  1. A small script that executes the notebooks (the planned `run_all.py`).
  2. A Windows Task Scheduler task that runs it with the same Python Jupyter uses (e.g. `C:\...\python.exe run_all.py`), starting in the repo folder.
  3. The computer awake and online at 9 AM ("wake the computer to run this task" turned on).
  4. Ideally, a timestamped copy of each run's outputs so the 9 AM result is preserved.

---

## 10. Known weaknesses

Ranked by how much they could move the answer.

1. **The national mood rests on thin data.** VoteHub's national poll feed collapsed after June. The Kalshi averages fill the gap, but they're market readings of RCP's and VoteHub's averages, not polls. The fundamentals carry about a third of every race, so this is the weakest link, especially for Swing, which relies on the national mood entirely.
2. **Swing vs Literal is a ~12-point decision** (section 5), and within Literal the fundamentals weights are very sensitive.
3. **Thin races lean on fundamentals.** Kansas, South Carolina, New Hampshire and Montana each have one poll in the window. That's the intended behavior of poll reliability, but those races depend heavily on the 2024 baseline and the national mood.
4. **Ungraded pollsters are assumed to look like graded ones.** If ungraded firms are worse on average, the random draw gives them too much weight. The sweep says it matters by about 1 point.
5. **House effects come from past elections.** A pollster's 2024 lean may not carry into 2026. The effect is small (under 1 point).
6. **Uniform swing / uniform shrinkage.** Neither variant lets states swing by different amounts (e.g. more in suburban states), except through their polls.
7. **Kalshi's national-average values are approximations.** The "above X%?" markets reveal the average only roughly (X plus a nudge), and RCP's buckets have open-ended ends. Both are close enough at K = 5 polls.
8. **Backtests aren't perfectly blind.** Pollster grades, nominee lists and 2024 results are today's versions, and national Kalshi averages are skipped in backtests.
9. **Independents other than Osborn** (Bodnar, Bengs, Achilles) count as Democratic seats if they win. All are below 10% on Kalshi.
10. **Simulation noise.** At 10,000 simulations P(51+) is accurate to about ±1 point (Model Testing E3). Raise `N_SIMS` if you need more precision.
