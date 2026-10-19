import { useRef, useState, type ReactNode } from "react";
import { ErrorNote, Field, useAction, useLoad } from "../ui";
import { flowApi } from "./flowApi";
import { DEFAULT_PROBABILITIES, parseScalar, showScalar } from "./graph";
import type {
  AggFn, BlockConfig, Catalog, ColumnInfo, Computed, Condition, DatasetSource, FileOut, FilterOp, WindowFn,
} from "./types";

type Cfg<T extends BlockConfig["type"]> = Extract<BlockConfig, { type: T }>;
const AGG_FNS: AggFn[] = ["count", "count_distinct", "sum", "mean", "median", "min", "max"];
const OPS: FilterOp[] = ["eq", "ne", "lt", "le", "gt", "ge", "contains", "not_contains", "is_null", "not_null", "in"];

function ColSelect(props: {
  cols: ColumnInfo[]; value: string | null; onChange: (v: string) => void; allowNone?: boolean; label?: string;
}) {
  const known = props.value === null || props.value === "" || props.cols.some((c) => c.name === props.value);
  return (
    <select aria-label={props.label ?? "column"} value={props.value ?? ""} onChange={(ev) => props.onChange(ev.target.value)}>
      <option value="">{props.allowNone ? "(none)" : "Choose a column"}</option>
      {!known && <option value={props.value ?? ""}>{props.value} (unknown)</option>}
      {props.cols.map((c) => <option key={c.name} value={c.name}>{c.name}</option>)}
    </select>
  );
}

function MultiCols(props: { cols: ColumnInfo[]; value: string[]; onChange: (v: string[]) => void }) {
  const names = [...props.cols.map((c) => c.name), ...props.value.filter((v) => !props.cols.some((c) => c.name === v))];
  return (
    <div className="checks">
      {names.length === 0 && <span className="muted small">No columns known yet. Connect an input or run upstream.</span>}
      {names.map((n) => (
        <label key={n} className="check">
          <input type="checkbox" checked={props.value.includes(n)}
            onChange={(ev) => props.onChange(ev.target.checked ? [...props.value, n] : props.value.filter((x) => x !== n))} />
          {n}
        </label>
      ))}
    </div>
  );
}

function ListEditor<T>(props: {
  items: T[]; onChange: (v: T[]) => void; make: () => T; addLabel: string; render: (item: T, set: (t: T) => void) => ReactNode;
}) {
  return (
    <div className="stack tight">
      {props.items.map((it, i) => (
        <div className="row-card" key={i}>
          {props.render(it, (t) => props.onChange(props.items.map((x, j) => (j === i ? t : x))))}
          <button type="button" className="ghost" aria-label="Remove" onClick={() => props.onChange(props.items.filter((_, j) => j !== i))}>×</button>
        </div>
      ))}
      <button type="button" onClick={() => props.onChange([...props.items, props.make()])}>{props.addLabel}</button>
    </div>
  );
}

export interface FormProps {
  slug: string; config: BlockConfig; onChange: (c: BlockConfig) => void;
  cols: ColumnInfo[]; rightCols: ColumnInfo[]; catalog: Catalog | null;
  files: FileOut[]; onFilesChanged: () => void;
}

function ConditionList(props: { cols: ColumnInfo[]; items: Condition[]; onChange: (v: Condition[]) => void }) {
  return (
    <ListEditor<Condition> items={props.items} onChange={props.onChange}
      make={() => ({ column: "", op: "eq", value: null })} addLabel="Add condition"
      render={(it, set) => (
        <div className="stack tight grow">
          <ColSelect cols={props.cols} value={it.column} onChange={(column) => set({ ...it, column })} />
          <select aria-label="operator" value={it.op} onChange={(ev) => set({ ...it, op: ev.target.value as FilterOp })}>
            {OPS.map((o) => <option key={o}>{o}</option>)}
          </select>
          {it.op !== "is_null" && it.op !== "not_null" && (
            <input aria-label="value" key={it.op} placeholder={it.op === "in" ? "a, b, c" : "value"}
              defaultValue={Array.isArray(it.value) ? it.value.map(showScalar).join(", ") : showScalar(it.value)}
              onBlur={(ev) => set({ ...it, value: it.op === "in" ? ev.target.value.split(",").map(parseScalar).filter((x) => x !== null) : parseScalar(ev.target.value) })} />
          )}
        </div>
      )} />
  );
}

const WINDOW_FNS: { fn: WindowFn; label: string }[] = [
  { fn: "lag", label: "lag (previous value)" }, { fn: "lead", label: "lead (next value)" },
  { fn: "rolling_mean", label: "rolling mean" }, { fn: "rolling_sum", label: "rolling sum" },
  { fn: "rolling_count", label: "rolling count" }, { fn: "rank", label: "rank (by the order column)" },
  { fn: "row_number", label: "row number" }, { fn: "pct_change", label: "percent change" },
];

export function ConfigForm(p: FormProps) {
  const c = p.config;
  switch (c.type) {
    case "dataset": return <DatasetForm {...p} c={c} />;
    case "filter": return (
      <div className="stack tight">
        <Field label="Keep rows that match">
          <select value={c.mode} onChange={(ev) => p.onChange({ ...c, mode: ev.target.value as "all" | "any" })}>
            <option value="all">all conditions (AND)</option><option value="any">any condition (OR)</option>
          </select>
        </Field>
        <ConditionList cols={p.cols} items={c.conditions} onChange={(conditions) => p.onChange({ ...c, conditions })} />
      </div>
    );
    case "sort": return (
      <div className="stack tight">
        <ListEditor items={c.keys} onChange={(keys) => p.onChange({ ...c, keys })} make={() => ({ column: "", descending: false })} addLabel="Add key"
          render={(it, set) => (
            <div className="row wrap grow">
              <ColSelect cols={p.cols} value={it.column} onChange={(column) => set({ ...it, column })} />
              <label className="check"><input type="checkbox" checked={it.descending} onChange={(ev) => set({ ...it, descending: ev.target.checked })} />descending</label>
            </div>
          )} />
        <Field label="Limit (optional)">
          <input type="number" min={1} value={c.limit ?? ""} onChange={(ev) => p.onChange({ ...c, limit: ev.target.value ? Number(ev.target.value) : null })} />
        </Field>
      </div>
    );
    case "columns": return <ColumnsForm {...p} c={c} />;
    case "group": return (
      <div className="stack tight">
        <strong>Group by</strong>
        <MultiCols cols={p.cols} value={c.by} onChange={(by) => p.onChange({ ...c, by })} />
        <strong>Aggregations</strong>
        <ListEditor items={c.aggregations} onChange={(aggregations) => p.onChange({ ...c, aggregations })}
          make={() => ({ column: null, fn: "count" as AggFn, as: "" })} addLabel="Add aggregation"
          render={(it, set) => (
            <div className="stack tight grow">
              <select aria-label="function" value={it.fn} onChange={(ev) => set({ ...it, fn: ev.target.value as AggFn })}>
                {AGG_FNS.map((f) => <option key={f}>{f}</option>)}
              </select>
              <ColSelect cols={p.cols} value={it.column} allowNone={it.fn === "count"} onChange={(column) => set({ ...it, column: column || null })} />
              <input aria-label="result name" placeholder="result name" value={it.as} onChange={(ev) => set({ ...it, as: ev.target.value })} />
            </div>
          )} />
      </div>
    );
    case "join": return (
      <div className="stack tight">
        <Field label="Join type">
          <select value={c.how} onChange={(ev) => p.onChange({ ...c, how: ev.target.value as "inner" | "left" })}>
            <option value="left">left (keep every left row)</option><option value="inner">inner (matches only)</option>
          </select>
        </Field>
        <ListEditor items={c.on} onChange={(on) => p.onChange({ ...c, on })} make={() => ({ left: "", right: "" })} addLabel="Add key pair"
          render={(it, set) => (
            <div className="stack tight grow">
              <ColSelect cols={p.cols} value={it.left} label="left column" onChange={(left) => set({ ...it, left })} />
              <ColSelect cols={p.rightCols} value={it.right} label="right column" onChange={(right) => set({ ...it, right })} />
            </div>
          )} />
        <Field label="Suffix for clashing right names">
          <input value={c.suffix} maxLength={20} onChange={(ev) => p.onChange({ ...c, suffix: ev.target.value || "_right" })} />
        </Field>
      </div>
    );
    case "pivot": return (
      <div className="stack tight">
        <strong>Rows</strong>
        <MultiCols cols={p.cols} value={c.rows} onChange={(rows) => p.onChange({ ...c, rows })} />
        <Field label="Columns"><ColSelect cols={p.cols} value={c.columns} allowNone onChange={(v) => p.onChange({ ...c, columns: v || null })} /></Field>
        <Field label="Function">
          <select value={c.fn} onChange={(ev) => p.onChange({ ...c, fn: ev.target.value as AggFn })}>{AGG_FNS.map((f) => <option key={f}>{f}</option>)}</select>
        </Field>
        <Field label="Values"><ColSelect cols={p.cols} value={c.values} allowNone={c.fn === "count"} onChange={(v) => p.onChange({ ...c, values: v || null })} /></Field>
        <label className="check"><input type="checkbox" checked={c.totals} onChange={(ev) => p.onChange({ ...c, totals: ev.target.checked })} />Show totals</label>
        <Field label="Max columns"><input type="number" min={1} max={200} value={c.max_columns} onChange={(ev) => p.onChange({ ...c, max_columns: clamp(Number(ev.target.value), 1, 200) })} /></Field>
      </div>
    );
    case "stats": return (
      <div className="stack tight">
        <Field label="Group by"><ColSelect cols={p.cols} value={c.group_by} onChange={(group_by) => p.onChange({ ...c, group_by })} /></Field>
        <Field label="Outcome"><ColSelect cols={p.cols} value={c.outcome} onChange={(outcome) => p.onChange({ ...c, outcome })} /></Field>
        <Field label="Outcome kind">
          <select value={c.outcome_kind} onChange={(ev) => p.onChange({ ...c, outcome_kind: ev.target.value as "rate" | "median" })}>
            <option value="rate">rate (share of successes)</option><option value="median">median (numeric)</option>
          </select>
        </Field>
        {c.outcome_kind === "rate" && (
          <Field label="Success value"><input value={showScalar(c.success_value)} onChange={(ev) => p.onChange({ ...c, success_value: parseScalar(ev.target.value) })} /></Field>
        )}
        <p className="muted small">Results are marked verified only when every statistical gate passes.</p>
      </div>
    );
    case "chart": return (
      <div className="stack tight">
        <Field label="Kind">
          <select value={c.kind} onChange={(ev) => p.onChange({ ...c, kind: ev.target.value as typeof c.kind, agg: ev.target.value === "scatter" ? "none" : c.agg === "none" ? "count" : c.agg })}>
            <option>bar</option><option>line</option><option>scatter</option>
          </select>
        </Field>
        <Field label="X"><ColSelect cols={p.cols} value={c.x} onChange={(x) => p.onChange({ ...c, x })} /></Field>
        <Field label="Aggregation">
          <select value={c.agg} onChange={(ev) => p.onChange({ ...c, agg: ev.target.value as typeof c.agg })}>
            {["count", "sum", "mean", "median", "none"].map((a) => <option key={a}>{a}</option>)}
          </select>
        </Field>
        <Field label="Y"><ColSelect cols={p.cols} value={c.y} allowNone={c.agg === "count"} onChange={(y) => p.onChange({ ...c, y: y || null })} /></Field>
        <Field label="Series (optional)"><ColSelect cols={p.cols} value={c.series} allowNone onChange={(s) => p.onChange({ ...c, series: s || null })} /></Field>
        <Field label="Max points"><input type="number" min={10} max={10000} value={c.max_points} onChange={(ev) => p.onChange({ ...c, max_points: clamp(Number(ev.target.value), 10, 10000) })} /></Field>
      </div>
    );
    case "split": return (
      <div className="stack tight">
        <Field label={`Test fraction (${c.test_fraction})`}>
          <input type="range" min={0.1} max={0.5} step={0.05} value={c.test_fraction} onChange={(ev) => p.onChange({ ...c, test_fraction: Number(ev.target.value) })} />
        </Field>
        <Field label="Mode">
          <select value={c.mode ?? "random"} onChange={(ev) => p.onChange({ ...c, mode: ev.target.value as "random" | "chronological", stratify: ev.target.value === "chronological" ? null : c.stratify })}>
            <option value="random">random</option><option value="chronological">chronological (test = latest rows)</option>
          </select>
        </Field>
        {c.mode === "chronological" ? (
          <Field label="Date column"><ColSelect cols={p.cols.filter((x) => x.dtype === "date" || x.dtype === "datetime")} value={c.date_column ?? null} onChange={(d) => p.onChange({ ...c, date_column: d || null })} /></Field>
        ) : (
          <>
            <Field label="Seed"><input type="number" value={c.seed} onChange={(ev) => p.onChange({ ...c, seed: Math.trunc(Number(ev.target.value)) })} /></Field>
            <Field label="Stratify by (optional)"><ColSelect cols={p.cols} value={c.stratify} allowNone onChange={(s) => p.onChange({ ...c, stratify: s || null })} /></Field>
          </>
        )}
        {c.mode === "chronological" && <p className="muted small">Rows sharing the boundary date all go to the test set, so train and test never overlap in time. Rows without a date are left out.</p>}
      </div>
    );
    case "model": return (
      <div className="stack tight">
        <Field label="Model">
          <select value={c.kind} onChange={(ev) => p.onChange({ ...c, kind: ev.target.value as typeof c.kind })}>
            <option value="logistic_regression">Logistic regression (yes / no target)</option>
            <option value="linear_regression">Linear regression (number target)</option>
            <option value="svm">SVM (yes / no target)</option>
            <option value="svr">SVR (number target)</option>
          </select>
        </Field>
        <Field label="Target"><ColSelect cols={p.cols} value={c.target} onChange={(target) => p.onChange({ ...c, target })} /></Field>
        {(c.kind === "logistic_regression" || c.kind === "svm") && (
          <Field label="Positive value"><input value={showScalar(c.positive_value)} onChange={(ev) => p.onChange({ ...c, positive_value: parseScalar(ev.target.value) })} /></Field>
        )}
        <strong>Features</strong>
        <MultiCols cols={p.cols.filter((x) => x.name !== c.target)} value={c.features} onChange={(features) => p.onChange({ ...c, features })} />
        {(c.kind === "svm" || c.kind === "svr") && (
          <>
            <Field label="Kernel">
              <select value={c.kernel ?? "rbf"} onChange={(ev) => p.onChange({ ...c, kernel: ev.target.value as "rbf" | "linear" })}>
                <option value="rbf">RBF</option><option value="linear">linear</option>
              </select>
            </Field>
            <Field label="C (penalty)"><input type="number" min={0.001} max={1000} step="any" value={c.C ?? 1} onChange={(ev) => p.onChange({ ...c, C: clamp(Number(ev.target.value), 0.001, 1000) })} /></Field>
            <Field label="Gamma (empty = automatic)"><input type="number" min={0} step="any" value={c.gamma ?? ""} onChange={(ev) => p.onChange({ ...c, gamma: ev.target.value && Number(ev.target.value) > 0 ? Number(ev.target.value) : null })} /></Field>
            <p className="muted small">At most 20,000 training rows are used (SVM training is quadratic). The probability comes from Platt scaling on the training rows.</p>
          </>
        )}
        <p className="muted small">Coefficients show associations, not causes. A model is verified only when it beats the baseline on held-out rows.</p>
      </div>
    );
    case "cluster": return (
      <div className="stack tight">
        <Field label={`Clusters (k = ${c.k})`}>
          <input type="range" min={2} max={20} value={c.k} onChange={(ev) => p.onChange({ ...c, k: Number(ev.target.value) })} />
        </Field>
        <Field label="Seed"><input type="number" value={c.seed} onChange={(ev) => p.onChange({ ...c, seed: Math.trunc(Number(ev.target.value)) })} /></Field>
        <strong>Features</strong>
        <MultiCols cols={p.cols.filter((x) => x.dtype === "number" || x.dtype === "integer")} value={c.features} onChange={(features) => p.onChange({ ...c, features })} />
        <p className="muted small">Clusters describe the data; they are always exploratory.</p>
      </div>
    );
    case "dedup": return (
      <div className="stack tight">
        <Field label="Text column"><ColSelect cols={p.cols} value={c.column} onChange={(column) => p.onChange({ ...c, column })} /></Field>
        <Field label="Method">
          <select value={c.method} onChange={(ev) => p.onChange({ ...c, method: ev.target.value as typeof c.method })}>
            <option value="jaro_winkler">Jaro-Winkler</option><option value="levenshtein">Levenshtein ratio</option>
          </select>
        </Field>
        <Field label={`Threshold (${c.threshold})`}>
          <input type="range" min={0.5} max={1} step={0.01} value={c.threshold} onChange={(ev) => p.onChange({ ...c, threshold: Number(ev.target.value) })} />
        </Field>
        <Field label="Blocking prefix (letters that must match)">
          <input type="number" min={1} max={4} value={c.block_prefix} onChange={(ev) => p.onChange({ ...c, block_prefix: clamp(Math.trunc(Number(ev.target.value)), 1, 4) })} />
        </Field>
        <p className="muted small">Case, accents, punctuation and legal suffixes (SAS, Inc, Ltd, GmbH, Corp, Group) are ignored. Adds dedup_group and is_master (the most complete row). Up to 50,000 rows. This never merges CRM records.</p>
      </div>
    );
    case "aging": return (
      <div className="stack tight">
        <Field label="Date column"><ColSelect cols={p.cols} value={c.column} onChange={(column) => p.onChange({ ...c, column })} /></Field>
        <Field label="Age column name"><input value={c.alias} onChange={(ev) => p.onChange({ ...c, alias: ev.target.value })} /></Field>
        <Field label="Stagnant after (days)"><input type="number" min={0} value={c.stagnant_after_days} onChange={(ev) => p.onChange({ ...c, stagnant_after_days: clamp(Math.trunc(Number(ev.target.value)), 0, 36500) })} /></Field>
        <strong>Only flag rows that match</strong>
        <Field label="Match">
          <select value={c.where_mode} onChange={(ev) => p.onChange({ ...c, where_mode: ev.target.value as "all" | "any" })}>
            <option value="all">all conditions (AND)</option><option value="any">any condition (OR)</option>
          </select>
        </Field>
        <ConditionList cols={p.cols} items={c.where} onChange={(where) => p.onChange({ ...c, where })} />
        <p className="muted small">Age is the run date minus the date, in days. Rows without a date get no age and are not stagnant.</p>
      </div>
    );
    case "forecast": return (
      <div className="stack tight">
        <Field label="Amount"><ColSelect cols={p.cols.filter((x) => x.dtype === "number" || x.dtype === "integer")} value={c.amount} onChange={(amount) => p.onChange({ ...c, amount })} /></Field>
        <Field label="Stage"><ColSelect cols={p.cols} value={c.stage} onChange={(stage) => p.onChange({ ...c, stage })} /></Field>
        <Field label="Totals by (optional)"><ColSelect cols={p.cols} value={c.group_by} allowNone onChange={(g) => p.onChange({ ...c, group_by: g || null })} /></Field>
        <strong>Stage probability (%)</strong>
        <ListEditor<[string, number]> items={Object.entries(c.probabilities)}
          onChange={(l) => p.onChange({ ...c, probabilities: Object.fromEntries(l.filter(([k]) => k)) })} make={() => ["", 0]} addLabel="Add stage"
          render={(it, set) => (
            <div className="row grow">
              <input aria-label="stage" placeholder="stage" value={it[0]} onChange={(ev) => set([ev.target.value, it[1]])} />
              <input aria-label="probability" type="number" min={0} max={100} value={it[1]} onChange={(ev) => set([it[0], clamp(Number(ev.target.value), 0, 100)])} />
            </div>
          )} />
        <button type="button" onClick={() => p.onChange({ ...c, probabilities: { ...DEFAULT_PROBABILITIES } })}>Reset to defaults</button>
        <p className="muted small">Probabilities are your assumptions, not a statistical estimate. Adds probability and weighted_amount; with a totals column the output is one row per group.</p>
      </div>
    );
    case "window": return (
      <div className="stack tight">
        <Field label="Function">
          <select value={c.fn} onChange={(ev) => p.onChange({ ...c, fn: ev.target.value as WindowFn })}>
            {WINDOW_FNS.map((f) => <option key={f.fn} value={f.fn}>{f.label}</option>)}
          </select>
        </Field>
        {c.fn !== "rank" && c.fn !== "row_number" && (
          <Field label="Value column"><ColSelect cols={p.cols.filter((x) => x.dtype === "number" || x.dtype === "integer")} value={c.column} onChange={(column) => p.onChange({ ...c, column: column || null })} /></Field>
        )}
        <Field label="Order by"><ColSelect cols={p.cols} value={c.order_by} onChange={(order_by) => p.onChange({ ...c, order_by })} /></Field>
        <label className="check"><input type="checkbox" checked={c.descending} onChange={(ev) => p.onChange({ ...c, descending: ev.target.checked })} />descending</label>
        <strong>Partition by (optional)</strong>
        <MultiCols cols={p.cols} value={c.partition_by} onChange={(partition_by) => p.onChange({ ...c, partition_by })} />
        {(c.fn === "lag" || c.fn === "lead" || c.fn === "pct_change" || c.fn.startsWith("rolling")) && (
          <Field label={c.fn.startsWith("rolling") ? "Window size (rows)" : "Offset (rows)"}>
            <input type="number" min={1} max={1000} value={c.k} onChange={(ev) => p.onChange({ ...c, k: clamp(Math.trunc(Number(ev.target.value)), 1, 1000) })} />
          </Field>
        )}
        <Field label="Sum per period first (optional)">
          <select value={c.period ?? ""} onChange={(ev) => p.onChange({ ...c, period: (ev.target.value || null) as typeof c.period })}>
            <option value="">no, use rows as they are</option><option value="month">month</option><option value="quarter">quarter</option><option value="year">year</option>
          </select>
        </Field>
        <Field label="Result column name"><input value={c.alias} onChange={(ev) => p.onChange({ ...c, alias: ev.target.value })} /></Field>
        <p className="muted small">With a period, the value column is summed per partition and period (order by a date), then the function runs on those totals: percent change by quarter gives quarter-on-quarter growth. Null order values sort last.</p>
      </div>
    );
    case "domain": return (
      <div className="stack tight">
        <Field label="Email or URL column"><ColSelect cols={p.cols} value={c.column} onChange={(column) => p.onChange({ ...c, column })} /></Field>
        <Field label="Domain column name"><input value={c.alias} onChange={(ev) => p.onChange({ ...c, alias: ev.target.value })} /></Field>
        <p className="muted small">Adds the domain and is_free_webmail (gmail.com, outlook.com, hotmail.*, yahoo.*, orange.fr, free.fr, proton.me and similar). Text parsing only: no DNS or MX lookup is made.</p>
      </div>
    );
  }
}

const clamp = (n: number, lo: number, hi: number) => Math.min(hi, Math.max(lo, Number.isFinite(n) ? n : lo));

function ColumnsForm(p: FormProps & { c: Cfg<"columns"> }) {
  const { c } = p;
  return (
    <div className="stack tight">
      <label className="check"><input type="checkbox" checked={c.keep === null} onChange={(ev) => p.onChange({ ...c, keep: ev.target.checked ? null : p.cols.map((x) => x.name) })} />Keep all columns</label>
      {c.keep !== null && <MultiCols cols={p.cols} value={c.keep} onChange={(keep) => p.onChange({ ...c, keep })} />}
      <strong>Rename</strong>
      <ListEditor<[string, string]> items={Object.entries(c.rename)}
        onChange={(l) => p.onChange({ ...c, rename: Object.fromEntries(l.filter(([a]) => a)) })} make={() => ["", ""]} addLabel="Add rename"
        render={(it, set) => (
          <div className="stack tight grow">
            <ColSelect cols={p.cols} value={it[0]} onChange={(v) => set([v, it[1]])} />
            <input aria-label="new name" placeholder="new name" value={it[1]} onChange={(ev) => set([it[0], ev.target.value])} />
          </div>
        )} />
      <strong>Computed columns</strong>
      <ListEditor<Computed> items={c.computed} onChange={(computed) => p.onChange({ ...c, computed })}
        make={() => ({ name: "", op: "add", left: { column: null, value: null }, right: { column: null, value: null } })} addLabel="Add computed column"
        render={(it, set) => <ComputedRow cols={p.cols} it={it} set={set} />} />
    </div>
  );
}

function OperandInput(props: { cols: ColumnInfo[]; v: { column?: string | null; value?: number | null } | null | undefined; onChange: (o: { column: string | null; value: number | null }) => void; label: string }) {
  const isConst = props.v?.column == null && props.v?.value != null;
  return (
    <div className="row">
      <select aria-label={`${props.label} kind`} value={isConst ? "const" : "col"}
        onChange={(ev) => props.onChange(ev.target.value === "const" ? { column: null, value: 0 } : { column: null, value: null })}>
        <option value="col">column</option><option value="const">number</option>
      </select>
      {isConst
        ? <input type="number" aria-label={props.label} value={props.v?.value ?? 0} onChange={(ev) => props.onChange({ column: null, value: Number(ev.target.value) })} />
        : <ColSelect cols={props.cols} label={props.label} value={props.v?.column ?? null} onChange={(column) => props.onChange({ column: column || null, value: null })} />}
    </div>
  );
}

function ComputedRow(props: { cols: ColumnInfo[]; it: Computed; set: (c: Computed) => void }) {
  const { it, set } = props;
  return (
    <div className="stack tight grow">
      <input aria-label="new column name" placeholder="new column name" value={it.name} onChange={(ev) => set({ ...it, name: ev.target.value })} />
      <select aria-label="operation" value={it.op} onChange={(ev) => set({ ...it, op: ev.target.value as Computed["op"] })}>
        {["add", "sub", "mul", "div", "days_between", "bucket"].map((o) => <option key={o}>{o}</option>)}
      </select>
      <OperandInput cols={props.cols} v={it.left} label="left" onChange={(left) => set({ ...it, left })} />
      {it.op === "bucket" ? (
        <>
          <input aria-label="edges" placeholder="edges, ascending: 10, 100" defaultValue={(it.edges ?? []).join(", ")}
            onBlur={(ev) => set({ ...it, edges: ev.target.value.split(",").map((x) => x.trim()).filter(Boolean).map(Number).filter(Number.isFinite) })} />
          <input aria-label="labels" placeholder="labels, one more than edges" defaultValue={(it.labels ?? []).join(", ")}
            onBlur={(ev) => set({ ...it, labels: ev.target.value.split(",").map((x) => x.trim()).filter(Boolean) })} />
        </>
      ) : <OperandInput cols={props.cols} v={it.right} label="right" onChange={(right) => set({ ...it, right })} />}
    </div>
  );
}

function DatasetForm(p: FormProps & { c: Cfg<"dataset"> }) {
  const { c } = p;
  const d = c.dataset;
  const set = (dataset: DatasetSource) => p.onChange({ ...c, dataset });
  return (
    <div className="stack tight">
      <Field label="Source">
        <select value={d.source} onChange={(ev) => {
          const s = ev.target.value;
          set(s === "crm" ? { source: "crm", table: "deals" } : s === "file" ? { source: "file", file_id: p.files[0]?.id ?? "" } : { source: "postgres", connection_id: "", table: "", query: null });
        }}>
          <option value="crm">CRM</option><option value="file">File (CSV / Excel)</option><option value="postgres">PostgreSQL</option>
        </select>
      </Field>
      {d.source === "crm" && (
        <Field label="Table">
          <select value={d.table} onChange={(ev) => set({ source: "crm", table: ev.target.value as typeof d.table })}>
            {["deals", "accounts", "contacts", "companies", "meetings", "activities", "stage_events", "tasks"].map((t) => <option key={t}>{t}</option>)}
          </select>
        </Field>
      )}
      {d.source === "file" && <FileForm {...p} fileId={d.file_id} onPick={(file_id) => set({ source: "file", file_id })} />}
      {d.source === "postgres" && <PgForm {...p} d={d} set={set} />}
    </div>
  );
}

function FileForm(p: FormProps & { fileId: string; onPick: (id: string) => void }) {
  const a = useAction();
  const ref = useRef<HTMLInputElement>(null);
  const picked = p.files.find((f) => f.id === p.fileId);
  const upload = (f: File | undefined) => {
    if (!f) return;
    void a.run(async () => {
      const out = await flowApi.upload(p.slug, f);
      p.onFilesChanged();
      p.onPick(out.id);
      if (ref.current) ref.current.value = "";
    });
  };
  return (
    <div className="stack tight">
      <Field label="Existing file">
        <select value={p.fileId} onChange={(ev) => p.onPick(ev.target.value)}>
          <option value="">Choose a file</option>
          {p.files.map((f) => <option key={f.id} value={f.id}>{f.name} ({f.n_rows} rows)</option>)}
        </select>
      </Field>
      {picked && <p className="muted small">{picked.n_rows} rows, {picked.columns.length} columns{picked.sheet ? `, sheet ${picked.sheet}` : ""}</p>}
      <Field label="Or upload a CSV or XLSX file">
        <input ref={ref} type="file" accept=".csv,.xlsx" disabled={a.busy} onChange={(ev) => upload(ev.target.files?.[0])} />
      </Field>
      {a.busy && <span className="muted small">Uploading…</span>}
      <ErrorNote error={a.error} />
    </div>
  );
}

function PgForm(p: FormProps & { d: Extract<DatasetSource, { source: "postgres" }>; set: (d: DatasetSource) => void }) {
  const { d } = p;
  const conns = useLoad(() => flowApi.connections(p.slug), [p.slug]);
  const tables = useLoad(() => (d.connection_id ? flowApi.tables(p.slug, d.connection_id) : Promise.resolve([])), [p.slug, d.connection_id]);
  const [mode, setMode] = useState<"table" | "query">(d.query != null ? "query" : "table");
  const upd = (patch: Partial<typeof d>) => p.set({ ...d, ...patch });
  return (
    <div className="stack tight">
      <Field label="Connection">
        <select value={d.connection_id} onChange={(ev) => upd({ connection_id: ev.target.value, table: mode === "table" ? "" : null })}>
          <option value="">Choose a connection</option>
          {conns.data?.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
        </select>
      </Field>
      <ErrorNote error={conns.error} />
      {conns.data?.length === 0 && <p className="muted small">Add a connection in Settings first.</p>}
      <div className="row">
        <label className="check"><input type="radio" checked={mode === "table"} onChange={() => { setMode("table"); upd({ table: "", query: null }); }} />Table</label>
        <label className="check"><input type="radio" checked={mode === "query"} onChange={() => { setMode("query"); upd({ table: null, query: "" }); }} />SELECT</label>
      </div>
      {mode === "table" ? (
        <Field label="Table">
          <select value={d.table ?? ""} onChange={(ev) => upd({ table: ev.target.value, query: null })}>
            <option value="">Choose a table</option>
            {tables.data?.map((t) => { const v = t.schema === "public" ? t.name : `${t.schema}.${t.name}`; return <option key={v} value={v}>{v}</option>; })}
          </select>
        </Field>
      ) : (
        <Field label="One SELECT statement (read-only)">
          <textarea rows={6} spellCheck={false} value={d.query ?? ""} onChange={(ev) => upd({ query: ev.target.value, table: null })} />
        </Field>
      )}
      <ErrorNote error={tables.error} />
    </div>
  );
}
