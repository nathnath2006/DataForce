# M4 methods review

Read-only review of the M4 blocks, `scoring.py` and Explain. Date 2026-10-19. Scripts and outputs: `/private/tmp/claude-501/-Users-a1234-Documents-GitHub/09ecc94a-9687-4eaa-8fb7-441ce6fde086/scratchpad/methods/` (`e1`..`e11`). All experiments are synthetic and seeded. They show direction and size of effects, not exact production rates.

## Summary

| # | Method | Verdict | Severity | Minimal fix |
|---|---|---|---|---|
| 1 | SVM/SVR verdict, Platt, 20k cap | Sound with caveat | Medium | Fit Platt on held-out data; show "probability not verified"; caveat on results and scores |
| 2 | Chronological split and random-split use | Fix needed | High | Warn on random split of dated data; flag the inflated test share; guard post-close features |
| 3 | Deal velocity | Fix needed | High | Per-stage min n, calibrated thresholds, treat open stays separately |
| 4 | Engagement score | Sound with caveat | Medium | Label heuristic/not verified; absent accounts are missing, say so; smooth the 30-day cliff |
| 5 | Touchpoint ratio | Fix needed | Medium | Minimum outreach (suggest 10), then null with reason; add a CI |
| 6 | Weighted forecast | Sound with caveat | Medium | Offer historical stage-to-win rates with Wilson CI; show a forecast band |
| 7 | Fuzzy dedup | Sound with caveat | Medium | Strip articles, add a second blocking key, digit guard, show similarity |
| 8 | Scoring (imputation, k-means) | Fix needed | High | Per-row imputed flag; imputed rows are not "verified" |
| 9 | Explain BH | Fix needed | High | One pooled BH across the Explain run |
| 10 | Window / QoQ | Fix needed | Medium | Densify periods; null growth on a gap, zero, or negative base |

## 1. SVM / SVR verdict (e1, e1b, e11)

- **Same rule as logistic and linear.** SVM, logistic and linear share one path in `model.py`:
  - classifiers: Wilson accuracy CI against the majority-class baseline, bootstrap AUC CI above 0.5, held-out test n and class counts;
  - regressors: R2 CI above 0, against the test mean.
  - Verdicts use held-out rows only. Sound.
- **Platt on training decision values.** Test: 8 features, 5,000 held-out rows, 5 repeats (Brier and ECE, lower is better).

  | Setting | ECE, Platt on train | ECE, Platt on held-out | Logistic Brier vs SVM Brier |
  |---|---|---|---|
  | Default C=1, n=300 | 0.058 | 0.017 | 0.145 vs 0.157 |
  | Default C=1, n=2,000 | 0.040 | 0.017 | 0.141 vs 0.145 |
  | C=100, n=300 | 0.273 | 0.017 | 0.147 vs 0.283 |
  | C=100, gamma=0.5, n=2,000 | 0.214 | 0.037 | 0.140 vs 0.235 |

  - With default settings, probabilities are acceptable.
  - With a high C (allowed up to 1000) the probabilities are badly overconfident. Among rows shown above 90%, the real rate was 20-26 points lower.
  - The caveat exists only in the config form (`ConfigForm.tsx:250`), not on the result, the Save dialog or the scores.
  - The verdict does not test probability quality at all. "Verified" reads as covering the probability.
- **20,000-row cap** (the sample is random and unstratified):
  - balanced data: AUC 0.8954 at 20k vs 0.8980 at 60k (+0.003; 8 s vs 42 s);
  - 17% positives: 0.8814 vs 0.8780 (no loss).
  - Sound. It is warned. For very rare positives, stratify the sample.
- **Fix.**
  - Fit Platt on a held-out slice of train (or use cross-validated Platt).
  - Add Brier to the metrics and label the probability "verified" only when its Brier beats the base-rate Brier on test.
  - Otherwise print "probability not verified" on the result and on the score.

## 2. Chronological split (e2)

- **Ties go to the test set.** Sound in principle (no time overlap). The test share is silently inflated: 40% of deals closing on the last day of a month gave a 40% test set when 25% was requested. Fix: warn when the realised share differs by more than 5 points.
- **Random split is still the default, with no warning.** The engine checks only that train and test come from the same split block (`engine.py:141`).
  - Setup: the relationship between feature and win decays over time.
  - Random split: AUC 0.766 (CI 0.733-0.799), **verified**.
  - Chronological split: AUC 0.558, not verified.
- **Target leakage is not detected.** A feature known only after close (`cycle_days`) lifted AUC from 0.545 to 0.887 and the model was **verified**. The split is correct in time, but the feature is not available at prediction time.
- **Fix.**
  - Show a non-blocking note "random split: time order ignored" when the data has a date, and default to chronological for deal tables.
  - Add a one-line "only use columns known at scoring time" warning to Model.
  - Optionally flag columns named like `cycle`, `days_to_close`, `closed_*`.

## 3. Deal velocity (e3)

- **The index is biased low, and the thresholds are not calibrated.** Null world: every deal drawn from the same lognormal stage process (median 20 days, sigma 0.9, 3 stages). The sum of per-stage medians is smaller than a typical sum of skewed durations.
  - Result: **47% of deals were "stagnant" (index < 0.75), 21% "fast_track", 33% normal**, with no real difference between deals.
  - The thresholds 1.25 and 0.75 have no uncertainty and do not match a stated false-flag rate.
- **Median includes the deal itself.** The share of deals flagged in a null world, in-sample vs leave-one-out:

  | Completed stays per stage | In-sample | Leave-one-out |
  |---|---|---|
  | 3 | 54% | 72% |
  | 10 | 64% | 69% |
  | 200 | 67% | 67% |

- **Benchmark noise.** The bootstrap CI half-width of a stage median, as a share of the median:

  | n | Half-width |
  |---|---|
  | 3 | 110% |
  | 10 | 75% |
  | 30 | 40% |
  | 100 | 22% |

  The M1 median gate allows 30%. The velocity view shows n per stage but gates nothing.
- **Open stage versus completed-only benchmark.** The bias depends on the data, not only toward stagnant.
  - Deals that eventually complete: open stays are short so far, so open deals are over-flagged **fast** (38% vs 21% oracle).
  - With 10% of deals going silent in a stage: 65% of open deals flagged stagnant (vs 47%).
  - Completed-only benchmarks also drop the long stays still open (censoring).
- **Fix.**
  - Use the geometric mean of per-stage ratios, or the percentile within the stage.
  - Set thresholds as empirical quartiles of the index, or bootstrap the flag.
  - Exclude stages with fewer than 30 completed stays (the M1 `min_n`) from the index, and mark the deal "insufficient".
  - Report open stays separately as "already longer than X% of completed stays".

## 4. Engagement score (e4)

- **Disclosure.** The formula and weights are shown, but never labelled as a heuristic. The view has no status.
- **Weights.** Alternative plausible weights keep the overall rank (Spearman 0.94-0.98) but change the top 30 by 4-10 accounts (overlap 20-26 of 30). With no quiet penalty the top 30 changes by 4.
- **Cliff.** 10 emails with the last one on day 30 score 10; on day 31 they score 5.
- **Accounts with no activities are missing, not zero.** The account list comes from the input rows (`keys`), so an account with no activity does not appear.
  - Example: input of A, B, C, D with activities for A and B gave an output of A and B only.
  - An account appears with a score of 0 only if it has an old, future-dated or undated row.
- **Fix.**
  - Label "heuristic, not verified" in the view and in the Score output.
  - Join to the accounts table explicitly and fill 0.
  - Replace the cliff with a smooth decay.
  - Real validation: score at date t against the win/loss outcome after t on held-out deals.

## 5. Touchpoint ratio (e5)

- 1 email + 1 meeting gives 3.0, with no uncertainty.
- Spread of the ratio for reps with the same true meeting rate (0.3), and rank correlation with the true rate:

  | Outreach per rep | SD of the ratio | Rank correlation |
  |---|---|---|
  | 2 | 0.97 | 0.32 |
  | 5 | 0.61 | 0.46 |
  | 10 | 0.43 | 0.62 |
  | 100 | 0.14 | 0.93 |

- Shrinkage toward the pooled rate (10 pseudo-outreach) changed ranks by only 0.01-0.02, so it is not the fix. A minimum count is.
- **Fix.** Null below 10 outreach (or the M1 gate of 30), with the reason shown. Add a Wilson CI on meetings per outreach.

## 6. Weighted forecast (e6)

- **Labelled** as the user's assumptions, in the run warning and in the form. Sound.
- **Bias if the defaults are wrong.** If the true win rates are 4/12/35/70% against 10/20/40/60%, the default forecast is 642k against 544k expected (+18%). Prospecting alone is overstated 2.5 times.
- **No band.** For 60 open deals the sd of realised revenue is about 26% of the weighted sum (90% range 322k-788k).
- **Historical rates.** Computable from `stage_events`: among deals that reached a stage and have since closed (open deals excluded, to avoid censoring), the win rate with a Wilson CI. The CI half-width is 14 points at n=30 and 8 points at n=100. Use them only when the existing min n, wins and losses gates pass, otherwise fall back to the assumptions with the label.
- **Fix.** Add a "historical" mode and a simulated forecast interval.

## 7. Fuzzy dedup (e7)

Illustrative only: 20 true-duplicate and 20 near-miss pairs, written by hand.

| Threshold | JW recall | JW false pairs | Lev recall | Lev false pairs |
|---|---|---|---|---|
| 0.85 | 80% | 16 of 20 | 55% | 3 of 20 |
| 0.92 (default) | 70% | 7 of 20 | 40% | 1 of 20 |
| 0.95 | 65% | 3 of 20 | 30% | 0 of 20 |

- **Jaro-Winkler prefix bias.** It rewards a shared prefix, so "Smith Consulting" and "Smith Construction" (0.916) and "Acme Industries" and "Acme Industrial" (0.947) are close. Levenshtein misses reordered or abbreviated names.
- **Single linkage chains.** "Store 101" to "Store 104" all merged into one group.
- **Blocking by first character.** "The Acme" vs "Acme" has JW 0.458 (different block, and the similarity is low anyway). `block_prefix` 2 and 3 do not help. "Xerox" and "Zerox" are also missed.
- **Fix.**
  - Normalise leading articles and prepositions ("the", "le", "la", "de").
  - Add a second block key (first token, or the first three characters of the sorted tokens).
  - Never match when the digit tokens differ.
  - Output the best pair similarity and call the groups "candidates to review".

## 8. Scoring (e8)

- **Mismatch confirmed.** Training and the held-out verdict drop rows with missing features. Scoring imputes the training mean.
- **Informative missingness** (amount missing more often for small or lost deals, 47% missing):
  - the verdict is **verified**, AUC 0.80, on the complete rows;
  - on the imputed rows AUC is 0.73, the mean probability 0.63 against an observed rate of 0.27 (Brier 0.31 against 0.17).
- **Random 30% missing:** AUC 0.85 on complete rows against 0.685 on imputed rows.
- **What the user sees.** The score view carries the model's "verified" status and a note with a count (`score.py`), but no per-row flag, so imputed rows look verified.
- **Fix.** Add a `score_imputed` column. Mark imputed rows "not verified". A cleaner option is to train with a missing-indicator and verify on rows with the same missingness.
- **k-means.** Rows with a missing feature stay unscored (null), which matches training. Good. Status is "exploratory", with no stability check beyond silhouette. Sound with caveat.

## 9. Explain BH (e9)

- Setup: 10 attributes with 5 groups each, 1,500 deals, win rate about 30%, the real stats block. The pooled run applies BH over all 50 p-values and requires the per-attribute verified status as well, so it is slightly stricter than a true pooled implementation.

| World | Runs with at least 1 false "verified" (per attribute / pooled) | False verified per run | True verified per run |
|---|---|---|---|
| No effects (300 runs) | 34% / 4% | 0.48 / 0.04 | - |
| 2 real effects (150 runs) | 56% / 19% | 0.89 / 0.23 | 1.75 / 1.45 (of 2) |

- **Fix.** Pool all p-values of the Explain run into one BH call. This needs the stats block to expose its pending p-values, or a `q_override` parameter. Expected cost is about 0.3 true findings per run in this setting.

## 10. Window / QoQ (e10)

- **A gap is absent, not zero.** Rep a has Q1=100, Q2=50, Q4=200 (no Q3). Q4 is reported as `+3.0` "QoQ" (it is really Q4 vs Q2), without a warning.
- **Tiny base:** 1 to 5,000 gives +4,999 (499,900%).
- **Negative base:** -100 to 50 gives -1.5, which is the wrong sign for a rise.
- **Fix.**
  - Densify periods per partition (min to max). Let the user choose "missing = 0" or null.
  - Use null when the previous period is not adjacent, is 0, or is negative.
  - Consider a minimum base.

## Resolution (2026-10-19)

Applied by a developer and checked by the tech lead. The tests are in `backend/tests/flows/`:
`test_pooled_bh.py`, `test_split_leakage.py`, `test_svm_platt.py`, and additions to
`test_scoring.py`, `test_m4_blocks.py` and `test_batch1.py`.

| # | Fix | State | Measured after |
|---|---|---|---|
| 9 | **Explain:** one BH across every attribute of a run. The stats block is split into `prepare` and `finish`, so the p-values are pooled before the verdict | done | With 5 null attributes over 120 runs, runs with a false verified finding went from 16 % to 3 % |
| 8 | **Scoring:** a per-row `score_imputed` column; the count goes in the notes and in *Score now*; imputed rows are not covered by the verdict | done | n/a |
| 3 | **Velocity:** the index is the median of the per-stay percentiles within the stage's completed stays (bounded, unlike a ratio). Fast track is ≤ 0.25 and stagnant ≥ 0.75. A stage needs at least 30 completed stays, otherwise its stays are marked *insufficient* with a reason. Open stays past the stage's p75 are flagged `stalled_in_stage` | done | Null with 3 stages: 31 % of deals flagged, down from 68 %. Identical deals: 0 flags. Saved flows still load (the old thresholds are dropped) |
| 2 | **Split:** a warning when a random split cuts dated data, and when a boundary tie moves the test share more than 5 points. A model of `is_won` or `is_closed` on deals with a post-outcome feature is *not verified*, and the reason names the column | done | n/a |
| 1 | **SVM:** Platt is fitted on 3-fold out-of-fold decision values. A caveat on results, saved models and scores says the verdict covers ranking and accuracy, not calibration | done | ECE at C=100 went from 0.28 to 0.045, for about 9 s extra at 20,000 rows |
| 5 | **Touchpoint:** a minimum outreach count (default 10), below which the ratio is empty with a reason | partly | No interval: meetings are not a subset of outreach, so a Wilson interval does not apply |
| 10 | **Window:** periods are densified (a missing period counts as 0 in a sum); growth is empty on a zero, negative or missing base; an absolute-change column; a warning count | done | n/a |
| 4 | **Engagement:** labelled a heuristic; accounts without activities are said to be absent, not zero | partly | The 30-day cliff is not smoothed |
| 6 | **Forecast:** the default stage probabilities are labelled as assumptions | partly | Historical stage-to-win rates with a Wilson band need a second input. Left for later |
| 7 | **Dedup:** leading articles stripped, a second blocking key, a digit guard, and a `dedup_similarity` column | done | n/a |
