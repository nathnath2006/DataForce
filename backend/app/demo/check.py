"""Compare a stats-engine ScanReport with the generator's ground truth. Pure."""

from __future__ import annotations

from pydantic import BaseModel

from app.domain.enums import StatStatus
from app.domain.schemas import EffectFinding, GroundTruth, PlantedEffect, ScanReport


class CheckResult(BaseModel):
    found: list[PlantedEffect]  # planted effects with a matching verified finding
    missed: list[PlantedEffect]  # planted effects without one
    small_groups_ok: bool  # no verified finding on any declared small group
    false_positives: list[
        EffectFinding
    ]  # verified findings in a null cell / wrong-direction planted / small groups
    other_real: list[EffectFinding] = []  # verified, not a false positive, not a required effect
    passed: bool

    def summary(self) -> str:
        return (
            f"passed={self.passed} found={len(self.found)} missed={len(self.missed)} "
            f"small_groups_ok={self.small_groups_ok} false_positives={len(self.false_positives)} "
            f"other_real={len(self.other_real)}"
        )


def check_against_truth(report: ScanReport, truth: GroundTruth) -> CheckResult:
    """Rules:

    * every planted effect needs a verified finding with the same dimension, group, metric and
      direction;
    * false positive: a verified finding in a null cell (`truth.null_cells`, plus every cell of
      `truth.null_dimensions`), or on a planted (dimension, group, metric) with the wrong
      direction, or on a small group (too few rows to conclude);
    * any other verified finding (e.g. the mirror 'outbound low' of 'inbound high') is real but
      not required: it is listed in `other_real`, never dropped and never a failure.
    """
    verified = [f for f in report.findings if f.status == StatStatus.VERIFIED]
    found: list[PlantedEffect] = []
    missed: list[PlantedEffect] = []
    for eff in truth.planted:
        hit = any(
            f.dimension == eff.dimension
            and f.group == eff.group
            and f.metric == eff.metric
            and f.direction == eff.direction
            for f in verified
        )
        (found if hit else missed).append(eff)

    small = {(str(d), g) for d, g in truth.small_groups}
    small_hits = [f for f in verified if (str(f.dimension), f.group) in small]
    null_dims = {str(d) for d in truth.null_dimensions}
    null_cells = {(str(d), str(m)) for d, m in truth.null_cells}
    planted_keys = {(str(e.dimension), e.group, str(e.metric)) for e in truth.planted}
    planted_dir = {(str(e.dimension), e.group, str(e.metric)): e.direction for e in truth.planted}

    def is_false_positive(f: EffectFinding) -> bool:
        if str(f.dimension) in null_dims or (str(f.dimension), str(f.metric)) in null_cells:
            return True
        key = (str(f.dimension), f.group, str(f.metric))
        if key in planted_keys and f.direction != planted_dir[key]:
            return True
        return (str(f.dimension), f.group) in small

    false_pos = [f for f in verified if is_false_positive(f)]
    other_real = [f for f in verified if not is_false_positive(f)]
    # a finding that is the planted effect itself is "found", not "other"
    other_real = [
        f
        for f in other_real
        if not any(
            (str(f.dimension), f.group, str(f.metric)) == (str(e.dimension), e.group, str(e.metric))
            for e in truth.planted
        )
    ]

    small_ok = not small_hits
    passed = not missed and small_ok and not false_pos
    return CheckResult(
        found=found,
        missed=missed,
        small_groups_ok=small_ok,
        false_positives=false_pos,
        other_real=other_real,
        passed=passed,
    )
