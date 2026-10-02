"""Analytic Hierarchy Process: goal -> criteria tree -> alternatives.

Every criterion that has sub-criteria gets a pairwise comparison of those
sub-criteria; every leaf criterion gets a pairwise comparison of the
alternatives with respect to it. The goal is the root of the tree, so a model
without criteria compares the alternatives directly against the goal.

Global criterion weights are products of local weights down the tree. The
final score of an alternative is the sum over leaf criteria of
global_weight(leaf) * priority(alternative | leaf) ("distributive" mode). In
"ideal" mode each leaf's alternative priorities are first divided by their
maximum, which prevents rank reversal when alternatives are added or removed.
"""

from __future__ import annotations

import dataclasses
import uuid
from collections.abc import Iterator
from dataclasses import dataclass, field

import numpy as np

from .pairwise import Comparison, ComparisonSet, PairwiseResult, analyze

GOAL_ID = "goal"
SYNTHESIS_MODES = ("distributive", "ideal")


def new_id() -> str:
    return uuid.uuid4().hex[:8]


@dataclass
class Criterion:
    name: str
    id: str = field(default_factory=new_id)
    children: list[Criterion] = field(default_factory=list)


@dataclass
class Alternative:
    name: str
    id: str = field(default_factory=new_id)


@dataclass
class AHPResult:
    local: dict[str, PairwiseResult]  # comparison key (node id) -> analysis
    local_weights: dict[str, float]  # criterion id -> weight within its parent
    global_weights: dict[str, float]  # criterion id -> weight relative to the goal
    by_leaf: dict[str, np.ndarray]  # leaf id -> alternative priorities used in synthesis
    alternative_ids: list[str]
    alternative_names: list[str]
    alternative_scores: np.ndarray
    synthesis: str

    def ranking(self) -> list[int]:
        return sorted(range(len(self.alternative_scores)), key=lambda k: -self.alternative_scores[k])


class AHPModel:
    kind = "ahp"

    def __init__(self, goal: str = "Goal"):
        self.root = Criterion(goal, GOAL_ID)
        self.alternatives: list[Alternative] = []
        self.comparisons: dict[str, Comparison] = {}
        self.synthesis = "distributive"

    # ---- structure -----------------------------------------------------

    @property
    def goal(self) -> str:
        return self.root.name

    @goal.setter
    def goal(self, name: str) -> None:
        self.root.name = name

    def walk(self) -> Iterator[tuple[Criterion, Criterion | None, int]]:
        """Pre-order (node, parent, depth), starting with the goal at depth 0."""
        stack: list[tuple[Criterion, Criterion | None, int]] = [(self.root, None, 0)]
        while stack:
            node, parent, depth = stack.pop()
            yield node, parent, depth
            for child in reversed(node.children):
                stack.append((child, node, depth + 1))

    def find(self, node_id: str) -> Criterion | None:
        return next((n for n, _, _ in self.walk() if n.id == node_id), None)

    def parent_of(self, node_id: str) -> Criterion | None:
        return next((p for n, p, _ in self.walk() if n.id == node_id), None)

    def leaves(self) -> list[Criterion]:
        return [n for n, _, _ in self.walk() if not n.children]

    def path(self, node_id: str) -> list[str]:
        """Names from the top-level criterion down to `node_id` (goal excluded)."""
        names: list[str] = []
        node = self.find(node_id)
        while node is not None and node.id != GOAL_ID:
            names.append(node.name)
            node = self.parent_of(node.id)
        return names[::-1]

    def add_criterion(self, name: str, parent_id: str = GOAL_ID) -> Criterion:
        parent = self.find(parent_id)
        if parent is None:
            raise KeyError(parent_id)
        criterion = Criterion(name)
        parent.children.append(criterion)
        self.cleanup()
        return criterion

    def remove_criterion(self, node_id: str) -> None:
        parent = self.parent_of(node_id)
        if parent is None:
            raise ValueError("the goal cannot be removed")
        parent.children = [c for c in parent.children if c.id != node_id]
        self.cleanup()

    def move_criterion(self, node_id: str, delta: int) -> None:
        parent = self.parent_of(node_id)
        if parent is not None:
            _move(parent.children, node_id, delta)

    def add_alternative(self, name: str) -> Alternative:
        alt = Alternative(name)
        self.alternatives.append(alt)
        return alt

    def remove_alternative(self, alt_id: str) -> None:
        self.alternatives = [a for a in self.alternatives if a.id != alt_id]
        self.cleanup()

    def move_alternative(self, alt_id: str, delta: int) -> None:
        _move(self.alternatives, alt_id, delta)

    def items_under(self, node: Criterion) -> list[Criterion] | list[Alternative]:
        """What is compared with respect to `node`: sub-criteria, or alternatives at a leaf."""
        return node.children if node.children else self.alternatives

    def cleanup(self) -> None:
        """Forget comparisons of deleted nodes and judgments of deleted items."""
        live = {n.id: n for n, _, _ in self.walk()}
        self.comparisons = {k: c for k, c in self.comparisons.items() if k in live}
        for key, comparison in self.comparisons.items():
            comparison.prune({x.id for x in self.items_under(live[key])})

    def warnings(self) -> list[str]:
        out = []
        if len(self.alternatives) < 2:
            out.append("Add at least two alternatives.")
        if not self.root.children:
            out.append("No criteria: alternatives are compared directly against the goal.")
        for node, _, _ in self.walk():
            if len(node.children) == 1:
                out.append(f"“{node.name}” has a single sub-criterion; it gets 100% of the weight.")
        return out

    # ---- comparisons ---------------------------------------------------

    def comparison(self, key: str) -> Comparison:
        return self.comparisons.setdefault(key, Comparison())

    def comparison_sets(self) -> list[ComparisonSet]:
        sets = []
        for node, _, _ in self.walk():
            items = self.items_under(node)
            if len(items) < 2:
                continue
            if node.children:
                what = "Criteria" if node.id == GOAL_ID else "Sub-criteria"
                group = "Criteria"
            else:
                what = "Alternatives"
                group = "Alternatives"
            sets.append(
                ComparisonSet(
                    key=node.id,
                    title=f"{what} with respect to “{node.name}”",
                    group=group,
                    item_ids=[x.id for x in items],
                    item_names=[x.name for x in items],
                )
            )
        return sets

    # ---- evaluation ----------------------------------------------------

    def evaluate(
        self, overrides: dict[str, np.ndarray] | None = None, synthesis: str | None = None
    ) -> AHPResult:
        """Synthesize the hierarchy.

        `overrides` replaces the local priority vector of a comparison set
        (keyed like `comparison_sets()`), which is how sensitivity analysis
        perturbs the model without touching the judgments.
        """
        synthesis = synthesis or self.synthesis
        overrides = overrides or {}
        local: dict[str, PairwiseResult] = {}
        for node, _, _ in self.walk():
            ids = [x.id for x in self.items_under(node)]
            if not ids:
                continue
            result = analyze(self.comparisons.get(node.id, Comparison()).matrix(ids))
            if node.id in overrides:
                result = dataclasses.replace(result, priorities=np.asarray(overrides[node.id], float))
            local[node.id] = result

        local_w = {GOAL_ID: 1.0}
        global_w = {GOAL_ID: 1.0}
        for node, _, _ in self.walk():
            for k, child in enumerate(node.children):
                local_w[child.id] = float(local[node.id].priorities[k])
                global_w[child.id] = global_w[node.id] * local_w[child.id]

        m = len(self.alternatives)
        scores = np.zeros(m)
        by_leaf = {}
        if m:
            for leaf in self.leaves():
                v = local[leaf.id].priorities
                if synthesis == "ideal":
                    v = v / v.max()
                by_leaf[leaf.id] = v
                scores += global_w[leaf.id] * v
            total = scores.sum()
            if total > 0:
                scores /= total

        return AHPResult(
            local=local,
            local_weights=local_w,
            global_weights=global_w,
            by_leaf=by_leaf,
            alternative_ids=[a.id for a in self.alternatives],
            alternative_names=[a.name for a in self.alternatives],
            alternative_scores=scores,
            synthesis=synthesis,
        )

    # ---- serialization -------------------------------------------------

    def to_dict(self) -> dict:
        def node(c: Criterion) -> dict:
            return {"id": c.id, "name": c.name, "children": [node(x) for x in c.children]}

        return {
            "type": self.kind,
            "goal": self.goal,
            "synthesis": self.synthesis,
            "criteria": [node(c) for c in self.root.children],
            "alternatives": [{"id": a.id, "name": a.name} for a in self.alternatives],
            "comparisons": {k: c.to_json() for k, c in self.comparisons.items() if len(c)},
        }

    @classmethod
    def from_dict(cls, data: dict) -> AHPModel:
        def node(d: dict) -> Criterion:
            return Criterion(d["name"], d.get("id") or new_id(), [node(x) for x in d.get("children", [])])

        model = cls(data.get("goal", "Goal"))
        model.synthesis = data.get("synthesis", "distributive")
        if model.synthesis not in SYNTHESIS_MODES:
            model.synthesis = "distributive"
        model.root.children = [node(c) for c in data.get("criteria", [])]
        model.alternatives = [Alternative(a["name"], a.get("id") or new_id()) for a in data.get("alternatives", [])]
        model.comparisons = {k: Comparison.from_json(v) for k, v in data.get("comparisons", {}).items()}
        model.cleanup()
        return model


def _move(items: list, item_id: str, delta: int) -> None:
    idx = next((k for k, x in enumerate(items) if x.id == item_id), None)
    if idx is None:
        return
    target = idx + delta
    if 0 <= target < len(items):
        items[idx], items[target] = items[target], items[idx]
