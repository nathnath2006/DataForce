from __future__ import annotations

from typing import Any

import pandas as pd

from app.demo.generator import generate
from app.demo.inmemory import deal_rows
from app.domain.schemas import GateConfig
from app.flows.engine import run_graph
from app.flows.memory import MemoryLoader
from app.flows.ports import FlowLimits
from app.flows.schemas import FlowGraph

FAST = GateConfig(bootstrap_resamples=200)


def graph(nodes: list[tuple[str, dict[str, Any]]], edges: list[tuple[str, str, str, str]]):
    return FlowGraph.model_validate(
        {
            "nodes": [{"id": i, "position": {"x": 0, "y": 0}, "config": c} for i, c in nodes],
            "edges": [
                {
                    "id": f"e{k}",
                    "source": s,
                    "source_port": sp,
                    "target": t,
                    "target_port": tp,
                }
                for k, (s, sp, t, tp) in enumerate(edges)
            ],
        }
    )


def ds(table: str = "deals") -> dict[str, Any]:
    return {"type": "dataset", "dataset": {"source": "crm", "table": table}}


def run(frames, nodes, edges, target=None, gates=FAST, limits=None):
    return run_graph(
        graph(nodes, edges), MemoryLoader(frames), gates, limits or FlowLimits(), target
    )


def chain(frames, cfg, table="deals", gates=FAST, limits=None):
    """dataset -> block; returns the block's result."""
    r = run(
        frames,
        [("d", ds(table)), ("b", cfg)],
        [("d", "out", "b", "in")],
        gates=gates,
        limits=limits,
    )
    return r["b"]


def deals_frame(variant: str, seed: int, n: int = 600) -> pd.DataFrame:
    rows = deal_rows(generate(variant, seed, n))  # type: ignore[arg-type]
    return pd.DataFrame(
        {
            "lead_source": [r.lead_source for r in rows],
            "segment": [r.segment for r in rows],
            "is_won": [r.won for r in rows],
            "amount_eur": [r.amount for r in rows],
        }
    )
