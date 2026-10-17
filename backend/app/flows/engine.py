"""Flow execution: topological order, ancestors of the target only, per-node errors."""

from __future__ import annotations

import time

import pandas as pd

from app.domain.schemas import GateConfig
from app.flows.blocks import REGISTRY, BlockError, BlockOutput, Ctx
from app.flows.blocks._common import dtype_of, jsonable
from app.flows.ports import FlowLimits, SourceError, SourceLoader
from app.flows.schemas import PORTS, ColumnInfo, FlowGraph, NodeResult


def _result(node_id: str, out: BlockOutput, limits: FlowLimits, ms: int) -> NodeResult:
    df = out.frames.get("out") if "out" in out.frames else next(iter(out.frames.values()), None)
    if df is None:
        return NodeResult(
            node_id=node_id,
            status="ok",
            n_rows=out.n_rows,
            view=out.view,
            warnings=out.warnings,
            elapsed_ms=ms,
        )
    kinds = [dtype_of(df.iloc[:, i]) for i in range(df.shape[1])]
    head = df.head(min(limits.preview_rows, 100))
    cols = [str(c) for c in df.columns]
    preview = []
    for row in head.itertuples(index=False):
        preview.append(
            {c: jsonable(v, k == "date") for c, v, k in zip(cols, row, kinds, strict=True)}
        )
    return NodeResult(
        node_id=node_id,
        status="ok",
        n_rows=len(df),
        columns=[ColumnInfo(name=c, dtype=k) for c, k in zip(cols, kinds, strict=True)],  # type: ignore[arg-type]
        preview=preview,
        view=out.view,
        warnings=out.warnings,
        elapsed_ms=ms,
    )


def run_graph(
    graph: FlowGraph,
    loader: SourceLoader,
    gates: GateConfig,
    limits: FlowLimits,
    target: str | None = None,
) -> dict[str, NodeResult]:
    nodes = {n.id: n for n in graph.nodes}
    if target is not None and target not in nodes:
        return {
            target: NodeResult(
                node_id=target, status="error", error="the target block does not exist"
            )
        }
    incoming: dict[str, list[tuple[str, str, str]]] = {i: [] for i in nodes}
    for e in graph.edges:
        incoming[e.target].append((e.target_port, e.source, e.source_port))
    wanted: set[str] = set()
    stack = [target] if target else list(nodes)
    while stack:
        i = stack.pop()
        if i in wanted:
            continue
        wanted.add(i)
        stack.extend(s for _, s, _ in incoming[i])
    order: list[str] = []
    done: set[str] = set()
    pending = [n.id for n in graph.nodes if n.id in wanted]
    while pending:  # Kahn, ties in graph order
        ready = [i for i in pending if all(s in done for _, s, _ in incoming[i])]
        order.append(ready[0])
        done.add(ready[0])
        pending.remove(ready[0])

    ctx = Ctx(gates=gates, limits=limits, loader=loader)
    deadline = time.monotonic() + limits.timeout_s
    results: dict[str, NodeResult] = {}
    frames: dict[tuple[str, str], pd.DataFrame] = {}
    for nid in order:
        if any(results[s].status != "ok" for _, s, _ in incoming[nid]):
            results[nid] = NodeResult(node_id=nid, status="skipped")
            continue
        if time.monotonic() >= deadline:
            results[nid] = NodeResult(
                node_id=nid, status="error", error=f"time limit of {limits.timeout_s:g} s exceeded"
            )
            continue
        node = nodes[nid]
        start = time.monotonic()
        try:
            inputs: dict[str, pd.DataFrame] = {}
            for port in PORTS[node.config.type][0]:
                edge = next((x for x in incoming[nid] if x[0] == port), None)
                if edge is None:
                    raise BlockError(f"input '{port}' is not connected")
                inputs[port] = frames[(edge[1], edge[2])]
            out = REGISTRY[node.config.type](node.config, inputs, ctx)
            for port, df in out.frames.items():
                frames[(nid, port)] = df
            results[nid] = _result(nid, out, limits, int((time.monotonic() - start) * 1000))
        except (BlockError, SourceError) as e:
            results[nid] = NodeResult(node_id=nid, status="error", error=str(e)[:500])
        except Exception as e:  # never leak data or a stack trace
            results[nid] = NodeResult(
                node_id=nid,
                status="error",
                error=f"this block could not run ({type(e).__name__}); check its settings",
            )
    return results
