// The reference behind every warning and "not verified" reason the app shows.
// `match` recognises the backend's own wording (backend/app/stats/gates.py, backend/app/flows/blocks/*):
// keep both in sync when a message changes. Pure data, tested in catalog.test.ts.

export type DocGroup = "Basics" | "Statistics gates" | "Models" | "Flow warnings" | "AI";

export interface DocEntry {
  id: string;
  group: DocGroup;
  title: string;
  /** One line, shown in lists and tooltips. */
  summary: string;
  /** What the message means, in plain words. */
  means: string;
  /** Why the app holds the result back. */
  why: string;
  /** What to do about it. */
  fix: string[];
  match?: RegExp;
}

export const DOCS: DocEntry[] = [
  // ---- basics ----
  {
    id: "verified", group: "Basics", title: "Verified and not verified",
    summary: "A result is verified only when it passes every gate; anything else is shown grey.",
    means: "Every number in DataForce is computed in code with a confidence interval. A comparison or a model is labelled verified only when it passes all the gates below (enough rows, enough wins and losses, a narrow enough interval, a significant difference after correction for multiple tests).",
    why: "A difference seen on a few deals is often luck. Showing it with the same weight as a solid result would invite decisions on noise.",
    fix: ["Read a not-verified item as a lead to check, never as a result.", "Open its reasons: each one links to its own page here."],
  },
  {
    id: "confidence-interval", group: "Basics", title: "Confidence interval (CI)",
    summary: "The range the true value is likely in, at 95% confidence by default.",
    means: "\"42% (35% to 49%)\" means the data are consistent with any win rate between 35% and 49%. The narrower the range, the more precise the estimate. Win rates use a Wilson interval; medians and differences of medians use the bootstrap.",
    why: "A single number hides how uncertain it is. The interval makes that uncertainty visible.",
    fix: ["Compare intervals, not only the central values: two groups whose intervals overlap a lot may not differ at all."],
  },
  {
    id: "q-value", group: "Basics", title: "p-value, q-value and false discoveries",
    summary: "q is the p-value corrected for running many comparisons at once.",
    means: "The scan and the stats block test many groups at the same time. With 20 tests, one will look significant by chance at p < 0.05. DataForce applies the Benjamini-Hochberg correction and keeps a finding only when its q-value is below the false discovery rate (FDR, 0.05 by default).",
    why: "Without the correction, the more groups you test, the more lucky results you would see.",
    fix: ["Test fewer, better-chosen groups: the correction is milder.", "Collect more closed deals."],
  },
  {
    id: "bootstrap", group: "Basics", title: "Bootstrap",
    summary: "Resampling the data many times to measure how much a median can move.",
    means: "Medians have no simple formula for their interval. DataForce redraws the rows with replacement (2,000 times by default, with a fixed seed so results repeat) and reads the interval from those redraws.",
    why: "It gives honest intervals for skewed values such as deal amounts and cycle lengths.",
    fix: ["Nothing to do: it is how medians are measured. Very large inputs may lower the number of redraws (see below)."],
  },
  {
    id: "exact-count", group: "Basics", title: "Exact count",
    summary: "A plain SQL count, not an estimate.",
    means: "Tiles and tags marked exact count are counted directly in the database. They carry no interval because nothing is estimated.",
    why: "Counts and statistics are kept visibly apart, so a count is never mistaken for a tested finding.",
    fix: ["Use counts to describe the data; use verified comparisons to draw conclusions."],
  },
  // ---- statistics gates ----
  {
    id: "small-n", group: "Statistics gates", title: "Too few rows (n below the minimum)",
    summary: "The group has fewer rows than the minimum sample size (30 by default).",
    means: "\"n = 12 < 30\" means the group, or the rest it is compared with, has 12 rows while at least 30 are needed. \"group:\" and \"rest:\" say which side is short.",
    why: "With few rows a rate or a median swings a lot from one deal to the next; the result would not repeat.",
    fix: ["Widen the group (a broader segment, a longer period).", "Wait for more deals to close.", "The minimum is GATE_MIN_N in backend/.env; lowering it makes results less reliable."],
    match: /^(?:(?:group|rest): )?n = \d+ < \d+/,
  },
  {
    id: "few-wins", group: "Statistics gates", title: "Too few wins or losses",
    summary: "A win rate needs at least 10 wins and 10 losses on each side by default.",
    means: "\"only 4 wins (< 10)\" means the group won 4 deals; a win rate built on so few outcomes is unstable even when n is large.",
    why: "A rate near 0% or 100% from few events has a very wide true range.",
    fix: ["Compare a broader group or a longer period.", "The minimums are GATE_MIN_WINS and GATE_MIN_LOSSES."],
    match: /only -?\d+ (wins|losses) \(</,
  },
  {
    id: "win-count-unknown", group: "Statistics gates", title: "Win count unknown",
    summary: "The outcome of some deals is not known, so the win gate cannot be checked.",
    means: "One side of the comparison has no usable won / lost outcome.",
    why: "The gate fails closed: when it cannot be checked, the result is not verified.",
    fix: ["Check that closed deals have a stage of won or lost."],
    match: /win count unknown/,
  },
  {
    id: "ci-wide", group: "Statistics gates", title: "Interval too wide",
    summary: "The confidence interval is wider than the precision limit.",
    means: "For a rate, \"CI ±18.0 pts > ±15 pts\" means the true value could be 18 points above or below the estimate. For a median, the limit is relative: \"±45% of the median > ±30%\".",
    why: "An estimate that could be anywhere in a 36-point range does not support a decision.",
    fix: ["More rows narrow the interval.", "The limits are GATE_MAX_CI_HALFWIDTH_PTS and GATE_MAX_CI_REL_HALFWIDTH."],
    match: /CI ±[\d.]+(?: pts|%)/,
  },
  {
    id: "ci-not-computable", group: "Statistics gates", title: "Interval not computable",
    summary: "The data did not allow an interval to be computed.",
    means: "Usually all values are identical, missing, or the group is empty. \"median is 0: relative CI undefined\" is the same case for medians.",
    why: "Every gate fails closed: no interval, no verified result.",
    fix: ["Look at the data in the Table and Columns tabs of the block to see what is missing."],
    match: /CI not comput|median is 0: relative CI undefined/,
  },
  {
    id: "not-significant", group: "Statistics gates", title: "Not significant after correction (q too high)",
    summary: "The difference could be luck once all the comparisons are taken into account.",
    means: "\"q = 0.21 >= 0.05\" means that, after correcting for the number of groups tested, the chance of seeing this difference by luck is too high. \"no p-value\" means the test could not run.",
    why: "See p-value, q-value and false discoveries.",
    fix: ["Test fewer groups.", "Collect more data.", "The rate is STATS_FDR_ALPHA."],
    match: /\bq = .+ >= |no p-value/,
  },
  {
    id: "includes-zero", group: "Statistics gates", title: "Difference interval includes 0",
    summary: "The group may be no different from the rest.",
    means: "\"difference CI [-3.0, +9.5] pts includes 0\" means the group could be 3 points worse or 9.5 points better than the rest: no difference is a possibility.",
    why: "If zero is plausible, the direction of the effect is not established.",
    fix: ["More rows on both sides narrow the interval."],
    match: /difference CI .*(includes 0|not computed)/,
  },
  {
    id: "multiplied", group: "Statistics gates", title: "Rows multiplied by a join",
    summary: "An upstream join duplicated rows, so every count downstream is inflated.",
    means: "A left row matched several right rows (one deal with several meetings, for example). The join warns, and stats and models below it are not verified.",
    why: "Counting the same deal three times makes n look three times bigger than it is, and intervals look falsely precise.",
    fix: ["Group the right side to one row per key before the join (Group / aggregate block).", "Or join on a key that is unique on the right."],
    match: /duplicated by an upstream join|rows multiplied by the join/,
  },
  // ---- models ----
  {
    id: "test-small", group: "Models", title: "Test set too small",
    summary: "Too few rows were held out to measure the model.",
    means: "The model is scored on the test rows of the split block. \"test set too small (n = 18 < 30)\" means there are not enough of them.",
    why: "A score on a handful of rows is mostly luck.",
    fix: ["Raise the test fraction of the Train / test split block, or use more data."],
    match: /test set too small/,
  },
  {
    id: "few-classes", group: "Models", title: "Too few positive or negative rows in test",
    summary: "A classifier needs both outcomes in its test rows.",
    means: "\"only 6 positive rows in test (< 10)\" means the test rows hold too few examples of the outcome you predict.",
    why: "The model cannot be shown to tell the two outcomes apart.",
    fix: ["Stratify the split on the target column.", "Use more data."],
    match: /(positive|negative) rows in test|one class in test/,
  },
  {
    id: "no-better-than-baseline", group: "Models", title: "No better than a baseline",
    summary: "The model does not beat a trivial guess on the test rows.",
    means: "Regression: \"R2 CI low <= 0\" means it may predict no better than the average. Classification: \"AUC CI low <= 0.5\" means it may rank no better than chance, and \"accuracy CI low <= majority-class baseline\" means always guessing the most common outcome may do as well.",
    why: "A model that a trivial rule matches adds nothing and may mislead.",
    fix: ["Try other features.", "Check for missing values in the features (Columns tab).", "Coefficients describe associations, not causes, even when verified."],
    match: /R2 CI|AUC CI low|majority-class baseline/,
  },
  {
    id: "leak", group: "Models", title: "Train and test may overlap",
    summary: "The model's train and test inputs do not come from the same split block.",
    means: "When the test rows may also be in the training rows, the model is scored on data it has already seen.",
    why: "The score would look much better than the model really is.",
    fix: ["Connect both the train and the test ports of the model to the same Train / test split block."],
    match: /overlap the training rows/,
  },
  // ---- flow warnings ----
  {
    id: "rows-capped", group: "Flow warnings", title: "Rows capped",
    summary: "The input had more rows than the flow limit; only the first ones are used.",
    means: "Each dataset and block is limited to FLOW_MAX_ROWS rows (200,000 by default). Rows past the limit are left out.",
    why: "It bounds memory and run time on this computer.",
    fix: ["Filter earlier in the flow.", "Or raise the limit (Admin shows the current value)."],
    match: /rows capped at|pivot rows capped/,
  },
  {
    id: "rows-excluded", group: "Flow warnings", title: "Rows with missing values excluded",
    summary: "Rows missing the group, the outcome or the x value were left out.",
    means: "The stats block needs both a group and an outcome on every row; the chart needs an x. The message gives the exact number left out.",
    why: "A missing value cannot be counted in either group without guessing.",
    fix: ["Check the Columns tab of the input block for the share of missing values.", "Fill the missing data in the CRM if it matters."],
    match: /missing (group or outcome excluded|x dropped)/,
  },
  {
    id: "bootstrap-lowered", group: "Flow warnings", title: "Bootstrap redraws lowered",
    summary: "The input is large, so fewer bootstrap redraws were used to bound the work.",
    means: "Median comparisons redraw the data many times. On large inputs the number of redraws is lowered so the run finishes in time.",
    why: "Fewer redraws make the interval slightly less precise, never biased.",
    fix: ["Filter or sample the input first if you need the full number of redraws."],
    match: /bootstrap resamples lowered/,
  },
  {
    id: "view-truncated", group: "Flow warnings", title: "View truncated",
    summary: "The pivot or chart shows part of the result to stay readable.",
    means: "Pivots keep the most frequent column values (max_columns) and show the first rows; charts keep max_points points.",
    why: "A table with thousands of columns or a chart with a million points cannot be read.",
    fix: ["Filter the input, or raise max columns / max points in the block settings."],
    match: /pivot column values dropped|pivot view shows the first|chart truncated/,
  },
  // ---- AI ----
  {
    id: "ai-badge", group: "AI", title: "The yellow AI badge",
    summary: "Marks anything an AI model produced: a name, a class, a proposal.",
    means: "Titles classified by AI, themes named by AI and org-chart links found by AI carry the badge. The AI never computes a number.",
    why: "AI output can be wrong; it must never look like a checked fact.",
    fix: ["Review AI-made items before relying on them; your corrections always win."],
  },
  {
    id: "unverified-numbers", group: "AI", title: "Numbers not found in the data",
    summary: "The assistant wrote a number that code could not find in the record's data.",
    means: "Every number in an answer is checked against the data sent to the model. Those it cannot find are listed in a warning.",
    why: "Models sometimes invent figures.",
    fix: ["Treat the listed numbers as unverified.", "Ask again, or check the record itself."],
    match: /Numbers not found in the data/,
  },
  {
    id: "screening", group: "AI", title: "Theme tests are screening, not proof",
    summary: "A theme found in these meetings and tested on the same deals is a lead.",
    means: "The theme was discovered in the same meetings it is tested on, many themes are tested one by one, and deals differ in how often they were met.",
    why: "All three raise the odds of a lucky verified result.",
    fix: ["Confirm a lead on new deals before acting on it."],
  },
];

/** The entry explaining a backend reason or warning, or null when none matches. */
export function docFor(text: string): DocEntry | null {
  return DOCS.find((d) => d.match?.test(text)) ?? null;
}

export const DOC_GROUPS: DocGroup[] = ["Basics", "Statistics gates", "Models", "Flow warnings", "AI"];

/** Case-insensitive search over title, summary and body. */
export function searchDocs(q: string): DocEntry[] {
  const t = q.trim().toLowerCase();
  if (!t) return DOCS;
  return DOCS.filter((d) => [d.title, d.summary, d.means, d.why, ...d.fix].some((x) => x.toLowerCase().includes(t)));
}
