# Pray_For_The_Floor — Model 4

**Model 1's Bayesian backbone, rebuilt on live data, with the strongest pieces of Ozempic and DadBod added.**

| File | What it is |
|---|---|
| `pray_for_the_floor.ipynb` | The model. Run the install cell once, then *Run All* |
| `Model Testing.ipynb` | Checks, diagnostics, sensitivity sweep, toggles, random-seed test, weekly backtests. Runs the model notebook first |
| `model.json` | Registers the model with `run_all.py` (id `pray_for_the_floor`) |
| `Data_Cache/` | Last good download of every source. Used automatically if a website is down |
| `Output/` | Results (created on the first run). `Output/standard/` is read by `run_all.py`; `Output/testing/` by Model Testing |

Outputs: **P(Democrats hold at least 51 seats)** and **the predicted number of Democratic seats** (mean over 10,000 simulations, independents who caucus with Democrats included).

---

## 1. How it works, in plain English

1. **Download** VoteHub's Senate, generic-ballot and approval polls, Kalshi's race markets, and Kalshi's polling-average markets. Kalshi markets are found automatically by title, and candidate names come from Kalshi.
2. **Clean and weight the polls** exactly as Model 1 does: recency, sample size, LV/RV/adults, partisan sponsor, generic ballot, full field, pollster quality, past accuracy, flooding, and survey versions. The one difference is that pollster quality, accuracy and lean now come from **VoteHub's scorecard**.
3. **Measure the national mood** from the generic ballot and approval, as in Model 1. Each signal now blends VoteHub's polls with **Kalshi's polling averages** (counted as 5 polls).
4. **Build each race's prior** (Model 1): 2 × partisan lean + national environment ± incumbency.
5. **Bayesian update with three sources.** The prior, the polls, and **Kalshi's implied margin** are combined by precision (1 ÷ uncertainty²). The most certain source counts most, and Kalshi is deliberately given low precision.
6. **Simulate 10,000 elections** with Model 1's correlated, fat-tailed draws. In **every** simulation, each pollster VoteHub hasn't graded gets the grade, past error and lean of a randomly drawn graded pollster, and the state's poll average and Bayesian estimate are recomputed before the race is drawn.
7. **Count seats** in each simulation to get P(51+) and the average.

## 2. What's kept from Model 1, and what's new

| Part | Model 1 | Pray_For_The_Floor | From |
|---|---|---|---|
| State polls | Adler's spreadsheet (last poll Oct 14; no longer updated) | **VoteHub API**, refreshed every run | Ozempic/DadBod |
| Approval polls | Spreadsheet | **VoteHub API** | Ozempic/DadBod |
| Generic ballot | VoteHub | VoteHub | — |
| National signals | polls only | polls **+ Kalshi averages** (RCP + VoteHub approval, VoteHub generic ballot), `NAT_KALSHI_POLL_EQUIV = 5` | DadBod |
| Pollster quality | spreadsheet rank column | **VoteHub grade** → Model 1's 5–10 scale | DadBod |
| Pollster accuracy | column blank → everyone 4.0 | **VoteHub past error**; weight clipped to 0.5–2× | DadBod (clip) |
| Pollster lean | partisan sponsors only (+ optional estimate) | + **scorecard lean** (`SCORECARD_HOUSE_EFFECTS`, on) | DadBod |
| Ungraded pollsters | rank 5 + 4.0 error, fixed | **random graded pollster, redrawn every simulation** (`UNRATED_POLLSTERS = "random"`) | Ozempic/DadBod, extended |
| Full field / generic | spreadsheet columns | detected from VoteHub's answers (3+ candidates; party names instead of people) | new |
| Recency | half-life 21 days | same by default; `RECENCY_MODE = "window"` for the 28-day linear window | Ozempic/DadBod |
| Prior | PVI × 2 + environment ± incumbency, SD 7.5 | unchanged | Model 1 |
| Combination | Bayesian: prior + polls | Bayesian: prior + polls **+ Kalshi** (`KALSHI_SD = 17`) | new |
| Thin races | Bayesian precision | same by default; `POLL_RELIABILITY = k` adds DadBod's extra discount | DadBod |
| Source errors | independent | **correlated** (ρ = 0.3, `CORRELATED_ERRORS`): same weights, wider ranges | DadBod |
| Kalshi races | not used | **input + comparison**, found automatically by title | DadBod |
| Simulation | correlated Student-t, shared tail | unchanged | Model 1 |
| Checks & sweep | bottom of the notebook | separate **Model Testing** notebook (Model 1's sweep + the new settings) | DadBod |
| Backtests | `AS_OF_DATE` on poll end date | release date (no leaks); Kalshi race prices from that day | Ozempic/DadBod |

### Defaults kept from Model 1, not from the meeting notes
To keep "99% of Model 1", these defaults are Model 1's values. Change them in CONFIG if the team prefers the meeting-note values (which Ozempic and DadBod use):

| Setting | Default here (Model 1) | Meeting notes / DadBod |
|---|---|---|
| `INCUMBENCY_ADVANTAGE` | 2.0 (appointed 1.0) | 3.0 |
| `POPULATION_WEIGHTS` | LV 1.0 : RV 0.85 : A 0.7 | 1.0 : 0.9 : 0.8 |
| `PARTISAN_HOUSE_EFFECTS` | 3 pts + weight 0.6 | 3 pts, no weight cut |
| Recency | half-life 21 days (all polls) | last 28 days, linear |

The Model Testing sweep includes all four, so you can see how much each one matters.

## 3. How Kalshi enters

**Race markets.** Kalshi's probability is turned into a margin using the race's own prior + polls uncertainty σ: margin = Φ⁻¹(P) × σ. Example: 75% with σ = 5 → D+3.4. That margin is a third Bayesian input with precision 1 ÷ `KALSHI_SD`²:

| `KALSHI_SD` | Kalshi's share of the final margin (test run) | Meaning |
|---|---|---|
| `None` or `0` | 0% | Comparison only |
| 25 | ~3–4% polled / 8% unpolled | Very light |
| **17 (default)** | **~5–9% polled / 16% unpolled** | About 1/5 of the prior's precision: the team's "fundamentals 5 : Kalshi 1" |
| 12 | ~10–16% polled / 28% unpolled | Moderate |
| 8 | ~20–30% polled / 47% unpolled | Heavy |

(Approximate; the race table's `share_kalshi` column shows each race's actual share.)

**National markets.** RCP and VoteHub approval averages are averaged together first, converted from approve % to net approval (net = 2 × approve − 100 + U, where U is the share answering neither in recent VoteHub polls), then blended with the VoteHub approval polls as if they were 5 polls. The VoteHub generic-ballot market is converted to the two-party basis and blended the same way.

**Backtests** use each race market's closing price on that day. The national markets are skipped (polls only), because their history isn't reliably available.

## 4. Ungraded pollsters: random grades every simulation

About half the polls come from firms VoteHub hasn't graded. Model 1 gave them the lowest rank and a 4-point error, which treats every unknown firm as bad. Here, with `UNRATED_POLLSTERS = "random"`:

- In **each** of the 10,000 simulations, each ungraded firm is assigned a randomly drawn **graded** firm's grade, past error and lean. All of that firm's polls share the draw, and it's redrawn in the next simulation.
- For that simulation, the state's poll average, poll uncertainty and Bayesian estimate are recomputed before the race is drawn. Uncertainty about unknown pollsters therefore spreads into the results instead of being fixed at one guess.
- Tables show the pool *average* for these firms. Model Testing (section E4) compares "random" with Model 1's "fixed" rule. In the test run that was 59.6% vs 57.2%.
- National (approval and generic-ballot) polls keep Model 1's fixed rule.

## 5. Poll reliability

Model 1's Bayesian precision already trusts thin races less. A state's poll uncertainty is √(single-poll SD² ÷ n_eff + 4.5² + undecided SD²), so one poll gives about 6.7 points of uncertainty and nine polls about 4.8. That is the default (`POLL_RELIABILITY = "bayesian"`).

Setting a number k additionally multiplies poll precision by n_eff ÷ (n_eff + k) (DadBod's rule: half weight at k effective polls). This leans harder on the prior and Kalshi in thinly polled races. It isn't on by default because it would discount thin races twice.

## 6. On/off toggles

| Toggle | Changes | Default |
|---|---|---|
| `SCORECARD_HOUSE_EFFECTS` | each poll's margin (removes the pollster's known lean) | on |
| `ESTIMATE_HOUSE_EFFECTS` | each poll's margin (Model 1's data-driven estimate) | off. Don't turn both on: Model Testing warns |
| `CORRELATED_ERRORS` | each race's uncertainty (wider), not its margin | on |
| `UNRATED_POLLSTERS` | `"random"` / `"fixed"` | random |
| `RECENCY_MODE` | `"half_life"` / `"window"` | half_life |

Any combination is valid. Model Testing E3 shows all four combinations of the house-effect and correlated-error toggles.

## 7. Running it

- **On its own:** open `pray_for_the_floor.ipynb`, run the install cell once, then *Run All*. Then open `Model Testing.ipynb` and *Run All* (about 30 seconds to a few minutes).
- **With the other models:** `python run_all.py` from the repo root runs it automatically through `model.json`. `python run_all.py --only pray_for_the_floor` runs just this one; the report still shows all models.
- **Backtest:** set `AS_OF_DATE = "2026-10-15"`. The first backtest downloads Kalshi's daily price history (about 30 seconds) and saves it to `Data_Cache/`.

## 8. Settings that matter most (test run)

From the Model Testing sweep, P(51+) ranged:

| Setting | Range of P(51+) |
|---|---|
| `PRIOR_SD` (4 → 14) | 36% – 65% |
| `ENV_SLOPE` (0 → 0.7) | 45% – 71% |
| `POLL_PRECISION_MULT` (0.5 → 4) | 53% – 75% |
| `SYSTEMATIC_POLL_ERROR_SD` (2.5 → 7) | 52% – 70% |
| `POLL_RELIABILITY` | 53% – 60% |
| `KALSHI_SD` (off → 8) | 59% – 61% |

These are from a test run on saved data with fewer polls than the live feed. Re-run Model Testing on live data before relying on them.

## 9. Weaknesses and open issues

1. **Kalshi is partly double-counted.** Kalshi traders read the same polls. `CORRELATED_ERRORS` widens the ranges to reflect this but doesn't lower Kalshi's weight; the low default precision is what keeps the effect small.
2. **Kalshi's implied margin is scaled by this model's own uncertainty,** and probabilities are clipped at 1–99%. In lopsided races (Wyoming, Massachusetts), this pulls the final margin a few points toward the middle. It doesn't change who's favored.
3. **Random grades are drawn from graded firms,** which tend to be established pollsters. That may be generous to unknown firms. `"fixed"` is the pessimistic alternative; Model Testing E4 shows the gap.
4. **National polls from ungraded firms keep the fixed lowest rank** (no per-simulation draw), as in Model 1.
5. **The pollster scorecard is a static file** (`Data/votehub_pollster_scorecards.csv`). It isn't refreshed from VoteHub each run.
6. **Candidate matching is by surname.** Alaska's opposition nominee comes from the fallback table because Kalshi lists a party name there. Generic-ballot detection relies on answers naming a party ("Democrat", "Republican").
7. **Half-life mode keeps every poll since the start of the cycle.** Old polls count very little but still add to the effective number of polls. `RECENCY_MODE = "window"` drops them.
8. **Backtests use polls only for the national signals,** because Kalshi's history for the weekly national markets isn't reliably available.
9. **Incumbent status and the Senate map are hand-maintained** in CONFIG. Re-check before the final run.
10. **This is not Model 1 on the same data.** Model 1 still reads Adler's spreadsheet, which has Adler's hand-coded fields and polls VoteHub may not have. Differences between the two in `run_all.py`'s report come partly from data, not just method.
11. **Closeness to Kalshi isn't accuracy.** Until results are in, agreement with the market or with other models shows similarity, not correctness.
