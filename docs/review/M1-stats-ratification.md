# M1 stats engine and synthetic data: independent ratification

Reviewer: independent statistics review (read-only). Date: 2026-10-17. Scope: D1-D8 and E of docs/DECISIONS.md, `backend/app/stats/*`, `backend/app/demo/*` and their tests. Reference code was written from the formulas and scipy, not from project functions. Scripts are outside the repo (session scratchpad `statsreview/`).

## Verdict: RATIFIED WITH FIXES

The statistical methods are implemented correctly. Three things need fixing before the "verified" label can be fully trusted: findings do not apply the CI-width gate (I1), the truth checker hides most false positives (I2), and the reliability claims in the decisions doc are too optimistic (I3). I4 is a generator crash on rare seeds.

## 1. Methods (what each does, and agreement with my independent reference)

| Method | What it does (plain language) | Cases tested | Max difference vs reference | Result |
|---|---|---|---|---|
| Wilson CI | Range of plausible true win rates that stays sensible with few deals, even at 0% or 100% | k=0, k=n, n=1, n=30, 3/3 | 2e-16 | OK |
| Newcombe hybrid (method 10) | Range of plausible values for the gap between two win rates; published example 56/70 vs 48/80 gives (0.0524, 0.3339), reproduced | 7 cases incl. 0/10 vs 0/10, 10/10 vs 0/10, 1/1 vs 1/1 | 2e-16 | OK |
| Percentile bootstrap (median, median difference) | Re-draws the deals many times with replacement, takes the 2.5th/97.5th percentile of the resulting medians | seeded; identical to my own implementation with the same seed. Coverage 94.3% (300 sims, lognormal, n=40) | 0 | OK |
| Fisher exact, two-sided | Exact probability of a win-rate gap this large by chance | same 7 cases | 2e-16 vs own hypergeometric sum | OK |
| Mann-Whitney U, two-sided, tie-corrected | Tests whether one group tends to have bigger values (rank based) | ties, all identical (p=1), n=1, heavy ties, lognormal | 0 for n>8 or with ties; 3v3 no ties uses scipy exact (0.10 vs my asymptotic 0.081, expected) | OK |
| Benjamini-Hochberg | Adjusts p-values so that about 5% of what is called "found" is allowed to be false | 200 random vectors with ties/1.0s, cap at 1 | 0 | OK (monotone, capped, NaN excluded) |

Wilson coverage at n=30, p=0.1 was 97.1% (conservative, as expected).

## 2. Gates and finding rule (D4 / D5)

| Item | Expected | Observed | Status |
|---|---|---|---|
| n < 30 fails | yes | yes; thresholds come from `GateConfig` built from Settings | OK |
| Win rate wins<10 / losses<10 | fails | yes (group stat and finding sides) | OK |
| Rate CI half-width > 15 pts | fails | yes; boundary 15.0 passes, 20.0 fails | OK |
| Median CI half-width > 30% of estimate | fails | 30% passes, 31% fails; estimate 0 with width fails; negative estimate uses abs | OK |
| NaN/None | fail closed | caught (`_bad`), reason "CI not computable" / "no p-value" / "difference CI not computed" | OK |
| inf | fail closed | est=inf with high=inf passes (inf/inf=NaN, NaN > 0.3 is False); wins=None on a win-rate finding passes | Low (I5) |
| Finding verified only if both sides pass gates | n, wins, losses, and CI width on both sides | only n/wins/losses on both sides; CI width is NOT checked for either side of a finding | ISSUE I1 |
| q < 0.05 and difference CI excludes 0 | both | both required, reasons given | OK |
| BH once across the whole scan | one family | one `benjamini_hochberg` call over all dimension x group x metric tests, including tests whose sides fail gates (conservative) | OK |
| Every failure has a reason | yes | yes, human-readable strings | OK |
| amount_band x amount excluded | tautology | excluded, noted in report | OK |

## 3. D6, D7, D8

| Item | Observed | Status |
|---|---|---|
| D6 missing counted and excluded, never a group | `value_of` returns None for None/blank; `_split` drops them; `missing` per dimension, plus `closed_on` and `amount` | OK |
| D7 "not verified is not no effect" | present in `ScanReport.notes` | OK |
| D8 exact aggregates without CI | not in M1 scope of these files (SQL layer); engine only produces CI stats | not assessed here |

## 4. Group-vs-rest design

| Item | Observed | Status |
|---|---|---|
| Rest = complement among rows with a non-missing value on that dimension | yes (`rest` built from the same `_split`); a row missing the dimension is in neither side | OK |
| Double counting | none; each row sits in exactly one group per dimension | OK |
| Cycle only on closed deals with both dates | `cycle_days` requires `won is not None` and both dates | OK |
| Win rate only on closed deals | yes | OK |
| Multiple looks | each dimension is tested separately, so one deal appears in several dimensions' tests; BH is valid under this positive dependence | OK |

## 5. Synthetic data vs E

| Item | Observed | Status |
|---|---|---|
| Inbound ~70%, outbound ~12%, partner/event ~30% | as coded; 98%/94.7% detection of inbound | OK |
| Cycle 30/60/110, amount 8k/20k/60k, 2% outliers x5 | as coded | OK |
| Referral capped under the gate | closed referral max 25 over 200 seeds; 0 verified referral findings in 400 runs | OK |
| Null dimensions industry/region/owner | industry and region balanced within segment; chi-square independence tests: industry~lead_source rejected in 2.5% of 200 seeds, owner~lead_source 5%, owner~segment 9.5% (random assignment, mild; this is the source of the small owner x amount/win rate false positives) | OK, Low (I6) |
| Noise variant: no effect anywhere | one distribution for all; 1 verified finding in 298 runs | OK |
| Missing values | lead 8.0%, amount 5.1%, industry 4.8%, region 5.1%, closed_on 2.4% | OK |
| FR/EN titles | mixed FR/EN titles with casing/typo noise | OK |
| Determinism | same seed gives identical JSON; different seed differs | OK |
| `check_against_truth` strictness | ignores mirror findings (fine for the outbound low rate, which is a real effect), BUT only counts verified findings on industry/region/owner/small groups as false positives. Truly null cells that are not checked: segment x win_rate, lead_source x cycle/amount, amount_band x win_rate | ISSUE I2 |

## 6. Calibration (own simulation, in memory, seeds 1000-1299, 500 bootstrap resamples; 100 seeds re-run at the default 2000 gave the same outcome counts to within 1 dataset)

Planted variant (n=300 datasets, 200 deals each):

| Planted effect | Detected | Rate |
|---|---|---|
| inbound win rate higher | 284 / 300 | 94.7% |
| segment enterprise cycle higher | 300 / 300 | 100% |
| segment smb cycle lower | 300 / 300 | 100% |
| segment enterprise amount higher | 300 / 300 | 100% |
| segment smb amount lower | 300 / 300 | 100% |
| referral (small group) verified | 0 / 300 | 0% (correct) |

| Dataset-level rate | Count | Rate |
|---|---|---|
| Planted: at least one verified finding in a truly null cell (my definition) | 19 / 300 | 6.3% |
| Planted: false positive as counted by `check_against_truth` | 7 / 300 | 2.3% |
| Planted: `check_against_truth` fails (miss or false positive) | 23 / 300 | 7.7% |
| Noise: at least one verified finding (all cells null) | 1 / 298 | 0.3% |
| Planted: verified finding whose own group stat is "not verified" (I1) | 12 / 300 | 4.0% |

Claims: "about 3% of datasets fail" is not supported; the measured failure rate is about 8% (the 60-seed sweep is too small to resolve 3% vs 8%). A BH threshold of 5% FDR does not limit the chance of at least one false finding per dataset to 5%; with about 10 true findings in the family, 5% of the rejections can be false, so about 6% of planted datasets contain one. The noise claim "at most 10%" holds (0.3%). The test requirement of 18 of 20 seeds passing (90%) is consistent with the measured 92%, but with little margin.

## Issues

**I1 (Medium). Findings do not apply the CI-width gate to either side.** D4/D5 say a finding needs both sides to pass the gates, and D4 defines the gates as including CI half-width. `gate_finding` only checks n, wins and losses. Evidence: in 12 of 300 planted datasets a verified finding sits on a group whose own stat is "not verified" (e.g. segment=enterprise x amount, 3 times; owner rep2 x amount twice; amount_band <10k x cycle). Some of these count as "found" planted effects. Minimal fix: in `gate_side`, pass the side's CI (the rest side CI also needs computing) to `gate_rate`/`gate_median` and append their reasons, or state explicitly in D5 that finding verification uses only the n/wins/losses part and update the docs.

**I2 (Medium). `check_against_truth` hides most false positives.** Of 19 datasets with a verified finding in a truly null cell, the checker reported 7. Not counted: segment x win_rate (win is independent of segment by construction), lead_source x cycle and x amount, amount_band x win_rate. Minimal fix: derive null cells from the ground truth as (dimension, metric) pairs: every metric outside the planted ones for planted dimensions is null, and amount_band x win_rate is null; flag any verified finding there (mirrors of planted effects stay allowed).

**I3 (Medium). Reliability claims in DECISIONS.md E and tests are too optimistic.** "About 3% fail" versus measured 7.7% (planted) and 6.3% dataset-level false positives. Fix: restate as "about 5-8% of 200-deal datasets show a false positive or miss the inbound effect (BH controls the share of false findings among findings, not the chance of any)", and add a tests/demo seed-sweep assertion using the full null-cell definition (I2) with a threshold of at least 90%.

**I4 (Medium). Generator crashes for rare seeds.** `generate("noise", 1121)` and `generate("noise", 1219)` raise `ValueError: low >= high` at `rng.integers(cycle_days, HISTORY_DAYS + 1)` when a log-normal cycle exceeds 730 days (2 of 300 noise seeds). Fix: clamp `cycle_days = min(cycle_days, HISTORY_DAYS)` (note it changes the stream only for those seeds).

**I5 (Low). Gates fail open on inf and on a missing wins count.** `gate_median(40, inf, 1, inf)` returns no reason, and `gate_finding` for win rate with `wins=None` skips the wins/losses test. Unreachable with current data but cheap to close: treat `not math.isfinite` as bad in `_bad`, and require wins for `Metric.WIN_RATE`.

**I6 (Low). Mild owner~segment association.** Owner and segment are assigned independently by quota, so any given dataset can have owners with different segment mixes; owner x amount (6 of the 19 null-cell false positives) is affected. Fix if wanted: assign owners balanced within each segment, as industry and region already are.

---

## Resolution (fix pass, 2026-10-17)

Fixed by fix engineer B and checked by the tech lead. The tech lead also ran an independent 100-seed sweep on seeds 3000–3099, which none of the engineers used.

| Issue | Status | Where | Test |
|---|---|---|---|
| I1 CI-width gate not applied to either side of a finding | **Fixed.** The group and the rest must each pass the CI-width gate: Wilson for rates, bootstrap for medians. Reasons are labelled `group:` or `rest:`. Recorded as DECISIONS D9. | `app/stats/gates.py`, `app/stats/engine.py` | `test_finding_applies_ci_width_gate_to_both_sides` |
| I2 lenient `check_against_truth` | **Fixed.** `GroundTruth.null_cells` lists every cell with no planted dependence. A false positive is a verified finding in a null cell, on a small group, or on a planted group in the wrong direction. Real side effects are listed in `CheckResult.other_real`. | `app/domain/schemas.py`, `app/demo/generator.py`, `app/demo/check.py` | `test_null_cell_false_positive_even_in_a_non_null_dimension`, `test_other_real_is_listed_not_dropped` |
| I3 over-optimistic "≈3%" claim | **Fixed.** DECISIONS §E now gives the measured rates. The sweep test asserts them on fixed seeds 1000–1049. | `docs/DECISIONS.md`, `tests/demo/test_engine_truth.py` | `test_seed_sweep_calibration` |
| I4 generator crash (noise seeds 1121, 1219) | **Fixed.** The cycle length is clamped to the history window. | `app/demo/generator.py` | `test_noise_seeds_that_used_to_crash_the_generator[1121/1219]` |
| I5 gates fail open on inf, or on wins=None | **Fixed.** Non-finite values count as bad, and a win-rate finding without a win count is "not verified". | `app/stats/gates.py` | `test_non_finite_fails_closed_and_missing_wins` |
| I6 owner mildly linked to segment | **Fixed.** Owners are balanced within each (segment, lead source) cell. | `app/demo/generator.py` | `test_owner_is_balanced_within_segment` |

**Calibration after the fixes** (500 resamples, in memory):

| Measure | Seeds 1000–1099 (fixer) | Seeds 3000–3099 (tech lead) |
|---|---|---|
| Inbound win rate detected | 96% | 93% |
| Enterprise / SMB cycle detected | 99% / 100% | 100% / 100% |
| Enterprise / SMB amount detected | 98% / 97% | 100% / 99% |
| Planted datasets with ≥1 false positive | 0% | 1% |
| Planted datasets where the check fails | 10% | 8% |
| Noise datasets with any verified finding | 1% | 1% |

Verdict after the fixes: **RATIFIED**. All six issues are closed. The engine misses a planted effect in about 1 dataset in 10, almost always the inbound effect, which sits close to the minimum for a verdict at about 55 deals. It shows a spurious finding in about 1 in 100.
