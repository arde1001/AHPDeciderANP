"""One-at-a-time sensitivity analysis shared by the AHP and ANP models.

Pick one comparison set and one item in it, sweep that item's local priority
from 0 to 1 (the other items keep their ratios) and record the final
alternative scores at every step.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol

import numpy as np

from .pairwise import ComparisonSet, PairwiseResult, reweight


class EvaluationResult(Protocol):
    local: dict[str, PairwiseResult]
    alternative_names: list[str]
    alternative_scores: np.ndarray


class Evaluable(Protocol):
    def comparison_sets(self) -> list[ComparisonSet]: ...
    def evaluate(self, overrides: dict[str, np.ndarray] | None = None) -> EvaluationResult: ...


@dataclass
class RankReversal:
    weight: float
    before: int  # index of the top alternative just below `weight`
    after: int  # index of the top alternative just above it


@dataclass
class SensitivityResult:
    set_key: str
    item_index: int
    current_weight: float
    weights: np.ndarray  # shape (steps,)
    scores: np.ndarray  # shape (steps, n_alternatives)
    alternative_names: list[str]
    reversals: list[RankReversal] = field(default_factory=list)

    def scores_at(self, weight: float) -> np.ndarray:
        return np.array(
            [np.interp(weight, self.weights, self.scores[:, k]) for k in range(self.scores.shape[1])]
        )


def _top_changes(weights: np.ndarray, scores: np.ndarray) -> list[RankReversal]:
    """Where the best alternative changes, located by linear interpolation."""
    reversals = []
    if scores.shape[1] < 2:
        return reversals
    top = scores.argmax(axis=1)
    alive = scores.sum(axis=1) > 1e-12  # all-zero rows (alternatives cut off) have no winner
    for s in range(1, len(weights)):
        a, b = top[s - 1], top[s]
        if a == b or not (alive[s - 1] and alive[s]):
            continue
        # crossing of lines a and b between weights[s-1] and weights[s]
        d0 = scores[s - 1, a] - scores[s - 1, b]
        d1 = scores[s, a] - scores[s, b]
        t = d0 / (d0 - d1) if d0 != d1 else 0.5
        x = weights[s - 1] + t * (weights[s] - weights[s - 1])
        reversals.append(RankReversal(float(x), int(a), int(b)))
    return reversals


def run_sensitivity(model: Evaluable, set_key: str, item_index: int, steps: int = 101) -> SensitivityResult:
    base = model.evaluate()
    local = base.local[set_key].priorities
    weights = np.linspace(0.0, 1.0, steps)
    rows = []
    for p in weights:
        result = model.evaluate({set_key: reweight(local, item_index, p)})
        rows.append(result.alternative_scores)
    scores = np.array(rows) if rows and len(rows[0]) else np.zeros((steps, 0))
    return SensitivityResult(
        set_key=set_key,
        item_index=item_index,
        current_weight=float(local[item_index]),
        weights=weights,
        scores=scores,
        alternative_names=list(base.alternative_names),
        reversals=_top_changes(weights, scores),
    )
