import { useThemeChoice } from "../theme";
import "@xyflow/react/dist/style.css";
import {
  Background, Controls, Handle, MiniMap, Position, ReactFlow, ReactFlowProvider, addEdge, useEdgesState,
  useNodesState, useReactFlow, type Connection, type NodeProps, type NodeTypes,
} from "@xyflow/react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useParams } from "react-router";
import { useWs } from "../context";
import { ErrorNote, Loading, Tag, useAction, useLoad } from "../ui";
import { ConfigForm } from "./ConfigForm";
import { flowApi } from "./flowApi";
import {
  BLOCKS, PALETTE_GROUPS, PORTS, blockTitle, connectionError, defaultConfig, fromFlow, inputColumns, newId, normalizeGraph,
  outputColumns, toFlowEdges, toFlowNodes, validateGraph, type BlockData, type BlockNode,
} from "./graph";
import { nodeState } from "./nodeState";
import { ResultsPanel } from "./Results";
import type { BlockType, FlowOut, NodeResult } from "./types";
import "./flows.css";

const MIME = "application/x-dataforce-block";

function summary(d: BlockData): string {
  const c = d.config;
  switch (c.type) {
    case "dataset": return c.dataset.source === "crm" ? `CRM: ${c.dataset.table}` : c.dataset.source === "file" ? "File" : "PostgreSQL";
    case "filter": return `${c.conditions.length} condition(s)`;
    case "group": return c.by.join(", ");
    case "pivot": return c.rows.join(", ");
    case "stats": return c.group_by ? `${c.outcome} by ${c.group_by}` : "";
    case "chart": return c.kind;
    case "model": return c.target;
    default: return "";
  }
}

/** Hexagon glyph for dataset (source) and model blocks. */
function Hexagon() {
  return (
    <svg className="fnode-glyph" viewBox="0 0 16 16" aria-hidden="true"><polygon points="8,1.5 14,4.75 14,11.25 8,14.5 2,11.25 2,4.75" /></svg>
  );
}

function BlockView({ id, data, selected }: NodeProps<BlockNode>) {
  const res = (data as BlockData & { result?: NodeResult }).result;
  const ports = PORTS[data.config.type];
  const glyph = data.config.type === "dataset" || data.config.type === "model";
  return (
    <div className={`fnode ${nodeState(res, !!selected)}`}>
      <div className="fnode-head">
        {glyph && <Hexagon />}
        <div className="fnode-title">{data.label || blockTitle(data.config.type)}</div>
      </div>
      <div className="fnode-sub">{summary(data)}</div>
      {res && (
        <div className="fnode-status">
          {res.status === "ok" && <Tag kind="ok">{res.n_rows ?? "ok"}{res.n_rows != null ? " rows" : ""}</Tag>}
          {res.status === "error" && <Tag kind="bad" >error</Tag>}
          {res.status === "skipped" && <Tag kind="mute">skipped</Tag>}
          {res.warnings.length > 0 && <Tag kind="warn">{res.warnings.length} warning(s)</Tag>}
        </div>
      )}
      {ports.inputs.map((p, i) => (
        <Handle key={p} id={p} type="target" position={Position.Left} style={{ top: 28 + i * 22 }}>
          <span className="plabel in">{p}</span>
        </Handle>
      ))}
      {ports.outputs.map((p, i) => (
        <Handle key={p} id={p} type="source" position={Position.Right} style={{ top: 28 + i * 22 }}>
          <span className="plabel out">{p}</span>
        </Handle>
      ))}
      <span hidden>{id}</span>
    </div>
  );
}
const nodeTypes: NodeTypes = { block: BlockView };

export function FlowEditorPage() {
  const { ws } = useWs();
  const { flowId = "" } = useParams();
  const flow = useLoad(() => flowApi.get(ws.slug, flowId), [ws.slug, flowId]);
  if (flow.loading && !flow.data) return <Loading />;
  if (!flow.data) return <ErrorNote error={flow.error} />;
  return <ReactFlowProvider><Editor key={flow.data.id} slug={ws.slug} flow={flow.data} /></ReactFlowProvider>;
}

function Editor({ slug, flow }: { slug: string; flow: FlowOut }) {
  const [nodes, setNodes, onNodesChange] = useNodesState<BlockNode>(toFlowNodes(flow.graph));
  const [edges, setEdges, onEdgesChange] = useEdgesState(toFlowEdges(flow.graph));
  const [name, setName] = useState(flow.name);
  const [saved, setSaved] = useState(() => JSON.stringify([flow.name, normalizeGraph(flow.graph)]));
  const [results, setResults] = useState<Record<string, NodeResult>>({});
  const [sel, setSel] = useState<string | null>(null);
  const [msg, setMsg] = useState<string | null>(null);
  const rf = useReactFlow();
  const colorMode = useThemeChoice();
  const wrap = useRef<HTMLDivElement>(null);
  const cat = useLoad(() => flowApi.catalog(slug), [slug]);
  const files = useLoad(() => flowApi.files(slug), [slug]);
  const save = useAction();
  const run = useAction();

  const graph = useMemo(() => fromFlow(nodes, edges), [nodes, edges]);
  const dirty = JSON.stringify([name, graph]) !== saved;

  const guardPushed = useRef(false);
  // leave guard: tab close, and in-app link clicks (BrowserRouter has no blocker)
  useEffect(() => {
    if (!dirty) return;
    const before = (ev: BeforeUnloadEvent) => { ev.preventDefault(); };
    const click = (ev: MouseEvent) => {
      const a = (ev.target as Element | null)?.closest?.("a[href]");
      if (a && !ev.defaultPrevented && !window.confirm("You have unsaved changes. Leave this page?")) {
        ev.preventDefault(); ev.stopPropagation();
      }
    };
    // Back / Forward (SR11-01): re-push this page, then leave only if the user confirms.
    const here = window.location.href;
    if (!guardPushed.current) { guardPushed.current = true; window.history.pushState({ dfGuard: true }, "", here); }
    const pop = () => {
      if (window.confirm("You have unsaved changes. Leave this page?")) {
        window.removeEventListener("popstate", pop);
        window.history.back();
      } else {
        window.history.pushState({ dfGuard: true }, "", here);
      }
    };
    window.addEventListener("beforeunload", before);
    window.addEventListener("popstate", pop);
    document.addEventListener("click", click, true);
    return () => {
      window.removeEventListener("beforeunload", before);
      window.removeEventListener("popstate", pop);
      document.removeEventListener("click", click, true);
    };
  }, [dirty]);

  const shown = useMemo(() => nodes.map((n) => ({ ...n, data: { ...n.data, result: results[n.id] } })), [nodes, results]);
  const selected = nodes.find((n) => n.id === sel) ?? null;
  const ctx = useMemo(() => ({ results, catalog: cat.data, files: files.data ?? [] }), [results, cat.data, files.data]);

  const isValid = useCallback((c: Connection | { source: string; target: string; sourceHandle?: string | null; targetHandle?: string | null }) =>
    connectionError(nodes.map((n) => ({ id: n.id, type: n.data.config.type })), edges,
      { source: c.source, target: c.target, sourceHandle: c.sourceHandle ?? null, targetHandle: c.targetHandle ?? null }) === null, [nodes, edges]);
  const onConnect = useCallback((c: Connection) => {
    if (!isValid(c)) return;
    setEdges((es) => addEdge({ ...c, id: newId("e", es.map((e) => e.id)) }, es));
  }, [isValid, setEdges]);

  const onDrop = (ev: React.DragEvent) => {
    ev.preventDefault();
    const type = ev.dataTransfer.getData(MIME) as BlockType;
    if (!BLOCKS.some((b) => b.type === type)) return;
    const position = rf.screenToFlowPosition({ x: ev.clientX, y: ev.clientY });
    setNodes((ns) => [...ns, { id: newId("n", ns.map((n) => n.id)), type: "block", position, data: { config: defaultConfig(type), label: null } }]);
  };
  const addBlock = (type: BlockType) =>
    setNodes((ns) => [...ns, { id: newId("n", ns.map((n) => n.id)), type: "block", position: { x: 40 + ns.length * 24, y: 40 + ns.length * 24 }, data: { config: defaultConfig(type), label: null } }]);

  const patch = (id: string, d: Partial<BlockData>) => setNodes((ns) => ns.map((n) => (n.id === id ? { ...n, data: { ...n.data, ...d } } : n)));

  const doSave = () => void save.run(async () => {
    const errs = validateGraph(graph);
    if (errs.length) throw new Error(errs[0]);
    const out = await flowApi.update(slug, flow.id, { name: name.trim() || flow.name, graph });
    setSaved(JSON.stringify([name, normalizeGraph(out.graph)])); setMsg("Saved");
  });
  const doRun = (target?: string) => void run.run(async () => {
    setMsg(null);
    const r = await flowApi.run(slug, graph, target);
    setResults((old) => (target ? { ...old, ...r.results } : r.results));
  });

  const selCols = selected ? (() => {
    const t = selected.data.config.type;
    const port = t === "model" ? "test" : t === "join" ? "left" : "in";
    const cols = t === "dataset" ? [] : inputColumns(graph, selected.id, port, ctx);
    return { cols, right: t === "join" ? inputColumns(graph, selected.id, "right", ctx) : [] };
  })() : { cols: [], right: [] };
  void outputColumns;

  return (
    <section className="editor">
      <div className="toolbar row wrap">
        <input aria-label="Flow name" className="flowname" value={name} maxLength={200} onChange={(e) => setName(e.target.value)} />
        {dirty && <Tag kind="warn">unsaved changes</Tag>}
        {!dirty && msg && <span className="muted small">{msg}</span>}
        <span className="grow" />
        <button onClick={doSave} disabled={save.busy || !dirty}>Save</button>
        <button className="primary" onClick={() => doRun()} disabled={run.busy || nodes.length === 0}>{run.busy ? "Running…" : "Run all"}</button>
        <button onClick={() => selected && doRun(selected.id)} disabled={run.busy || !selected}>Run selected</button>
      </div>
      <ErrorNote error={save.error} /><ErrorNote error={run.error} />
      <div className="workspace">
        <aside className="palette card" aria-label="Blocks">
          {PALETTE_GROUPS.map((g) => (
            <div key={g}><h3>{g}</h3>
              {BLOCKS.filter((b) => b.group === g).map((b) => (
                <div key={b.type} className="pitem" draggable onDragStart={(ev) => { ev.dataTransfer.setData(MIME, b.type); ev.dataTransfer.effectAllowed = "move"; }}
                  role="button" tabIndex={0} onKeyDown={(ev) => { if (ev.key === "Enter") addBlock(b.type); }} onDoubleClick={() => addBlock(b.type)}>
                  {b.title}
                </div>
              ))}
            </div>
          ))}
          <p className="muted small">Drag onto the canvas, or double-click to add.</p>
        </aside>
        <div className="canvas" ref={wrap} onDragOver={(ev) => { ev.preventDefault(); ev.dataTransfer.dropEffect = "move"; }} onDrop={onDrop}>
          <ReactFlow nodes={shown} edges={edges} nodeTypes={nodeTypes} onNodesChange={onNodesChange} onEdgesChange={onEdgesChange}
            onConnect={onConnect} isValidConnection={isValid} onSelectionChange={({ nodes: s }) => setSel(s[0]?.id ?? null)}
            deleteKeyCode="Backspace" fitView colorMode={colorMode}>
            <Background /><Controls /><MiniMap pannable zoomable />
          </ReactFlow>
        </div>
        <aside className="config card" aria-label="Block settings">
          {!selected ? <p className="muted">Select a block to configure it.</p> : (
            <div className="stack tight">
              <h3>{blockTitle(selected.data.config.type)}</h3>
              <label>Label<input value={selected.data.label ?? ""} maxLength={100} onChange={(e) => patch(selected.id, { label: e.target.value })} /></label>
              <ConfigForm slug={slug} config={selected.data.config} onChange={(config) => patch(selected.id, { config })}
                cols={selCols.cols.length || selected.data.config.type !== "dataset" ? selCols.cols : []} rightCols={selCols.right}
                catalog={cat.data} files={files.data ?? []} onFilesChanged={files.reload} />
              <button className="danger" onClick={() => { setNodes((ns) => ns.filter((n) => n.id !== selected.id)); setEdges((es) => es.filter((e) => e.source !== selected.id && e.target !== selected.id)); }}>Delete block</button>
            </div>
          )}
        </aside>
      </div>
      <div className="card resultsbox">
        <ResultsPanel result={sel ? results[sel] : undefined} title={selected ? (selected.data.label || blockTitle(selected.data.config.type)) : "a block"} />
      </div>
    </section>
  );
}
