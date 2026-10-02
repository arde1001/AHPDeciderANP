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

Instead of pairwise comparisons, a leaf criterion can score the alternatives
by **direct values** (measured data on a ratio scale, normalized as x / sum
for benefit criteria and (1/x) / sum(1/x) for cost criteria) or by
**ratings** (absolute measurement: the rating levels are compared pairwise
once, idealized so the best level is 1, and each alternative gets a level).
"""

from __future__ import annotations

import dataclasses
import math
import uuid
from collections.abc import Iterator
from dataclasses import dataclass, field

import numpy as np

from .pairwise import Comparison, ComparisonSet, PairwiseResult, analyze

GOAL_ID = "goal"
SYNTHESIS_MODES = ("distributive", "ideal")
SCORING_MODES = ("pairwise", "direct", "ratings")
DIRECTIONS = ("benefit", "cost")
# default rating scale: names and the weights the default level judgments approximate
DEFAULT_LEVELS = (("Excellent", 9), ("Very good", 5), ("Good", 3), ("Fair", 2), ("Poor", 1))


def new_id() -> str:
    return uuid.uuid4().hex[:8]


def levels_key(leaf_id: str) -> str:
    """Comparison key of a ratings leaf's level comparison."""
    return f"levels:{leaf_id}"


@dataclass
class RatingLevel:
    name: str
    id: str = field(default_factory=new_id)


@dataclass
class LeafInput:
    """How the alternatives are scored under one leaf criterion."""

    mode: str = "pairwise"  # pairwise | direct | ratings
    direction: str = "benefit"  # direct values: benefit (higher is better) | cost (lower is better)
    unit: str = ""
    values: dict[str, float] = field(default_factory=dict)  # alternative id -> measured value
    levels: list[RatingLevel] = field(default_factory=list)
    ratings: dict[str, str] = field(default_factory=dict)  # alternative id -> level id

    def is_default(self) -> bool:
        return self == LeafInput()


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
        self.leaf_inputs: dict[str, LeafInput] = {}  # only leaves that are not plain pairwise
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
        """Forget comparisons, scoring data and judgments of deleted nodes, alternatives and levels.

        Scoring data of a criterion that gained sub-criteria is kept (and
        ignored), so removing the sub-criteria again restores it.
        """
        live = {n.id: n for n, _, _ in self.walk()}
        alt_ids = {a.id for a in self.alternatives}
        self.leaf_inputs = {k: v for k, v in self.leaf_inputs.items() if k in live}
        for inp in self.leaf_inputs.values():
            level_ids = {lv.id for lv in inp.levels}
            inp.values = {a: v for a, v in inp.values.items() if a in alt_ids}
            inp.ratings = {a: lv for a, lv in inp.ratings.items() if a in alt_ids and lv in level_ids}
        kept = {}
        for key, comparison in self.comparisons.items():
            if key in live:
                comparison.prune({x.id for x in self.items_under(live[key])})
                kept[key] = comparison
            elif key.startswith("levels:") and key[7:] in self.leaf_inputs:
                comparison.prune({lv.id for lv in self.leaf_inputs[key[7:]].levels})
                kept[key] = comparison
        self.comparisons = kept

    def warnings(self) -> list[str]:
        out = []
        if len(self.alternatives) < 2:
            out.append("Add at least two alternatives.")
        if not self.root.children:
            out.append("No criteria: alternatives are compared directly against the goal.")
        for node, _, _ in self.walk():
            if len(node.children) == 1:
                out.append(f"“{node.name}” has a single sub-criterion; it gets 100% of the weight.")
        for leaf in self.leaves():
            problem = self.scoring_problem(leaf)
            if problem:
                out.append(f"“{leaf.name}”: {problem} Its alternatives count as equal until this is fixed.")
        return out

    # ---- scoring method of leaf criteria -------------------------------

    def scoring(self, leaf_id: str) -> LeafInput:
        """The scoring settings of a leaf (created on first use)."""
        return self.leaf_inputs.setdefault(leaf_id, LeafInput())

    def scoring_mode(self, node: Criterion) -> str:
        inp = self.leaf_inputs.get(node.id)
        return inp.mode if inp is not None else "pairwise"

    def set_scoring_mode(self, leaf_id: str, mode: str) -> None:
        if mode not in SCORING_MODES:
            raise ValueError(mode)
        inp = self.scoring(leaf_id)
        inp.mode = mode
        if mode == "ratings" and not inp.levels:
            self._default_levels(leaf_id)
        if inp.is_default():
            del self.leaf_inputs[leaf_id]

    def _default_levels(self, leaf_id: str) -> None:
        inp = self.scoring(leaf_id)
        inp.levels = [RatingLevel(name) for name, _ in DEFAULT_LEVELS]
        comp = self.comparison(levels_key(leaf_id))
        weights = [w for _, w in DEFAULT_LEVELS]
        for i, a in enumerate(inp.levels):
            for j in range(i + 1, len(inp.levels)):
                comp.set(a.id, inp.levels[j].id, weights[i] / weights[j])

    def add_level(self, leaf_id: str, name: str) -> RatingLevel:
        level = RatingLevel(name)
        self.scoring(leaf_id).levels.append(level)
        return level

    def remove_level(self, leaf_id: str, level_id: str) -> None:
        inp = self.scoring(leaf_id)
        inp.levels = [lv for lv in inp.levels if lv.id != level_id]
        self.cleanup()

    def move_level(self, leaf_id: str, level_id: str, delta: int) -> None:
        _move(self.scoring(leaf_id).levels, level_id, delta)

    def level_priorities(self, leaf_id: str, overrides: dict[str, np.ndarray] | None = None) -> PairwiseResult | None:
        inp = self.leaf_inputs.get(leaf_id)
        if inp is None or not inp.levels:
            return None
        key = levels_key(leaf_id)
        result = analyze(self.comparisons.get(key, Comparison()).matrix([lv.id for lv in inp.levels]))
        if overrides and key in overrides:
            result = dataclasses.replace(result, priorities=np.asarray(overrides[key], float))
        return result

    def scoring_problem(self, leaf: Criterion) -> str | None:
        """Why a direct/ratings leaf can't score the alternatives yet, or None."""
        mode = self.scoring_mode(leaf)
        if leaf.children or mode == "pairwise" or not self.alternatives:
            return None
        inp = self.leaf_inputs[leaf.id]
        if mode == "direct":
            missing = [a.name for a in self.alternatives if a.id not in inp.values]
            if missing:
                return f"no value for {', '.join(missing)}."
            values = [inp.values[a.id] for a in self.alternatives]
            if any(not math.isfinite(v) or v < 0 for v in values):
                return "values must be zero or positive (ratio scale)."
            if inp.direction == "cost" and any(v == 0 for v in values):
                return "a cost criterion can't have a value of 0 (lower is better means 1/value)."
            if sum(values) == 0:
                return "all values are 0."
            return None
        if not inp.levels:
            return "no rating levels."
        missing = [a.name for a in self.alternatives if a.id not in inp.ratings]
        if missing:
            return f"{', '.join(missing)} not rated."
        return None

    def _scored_priorities(self, leaf: Criterion, level_result: PairwiseResult | None) -> np.ndarray:
        """Alternative priorities of a direct/ratings leaf (equal if the data is incomplete)."""
        m = len(self.alternatives)
        if self.scoring_problem(leaf):
            return np.full(m, 1.0 / m)
        inp = self.leaf_inputs[leaf.id]
        if inp.mode == "direct":
            v = np.array([inp.values[a.id] for a in self.alternatives], float)
            if inp.direction == "cost":
                v = 1.0 / v
        else:
            ideal = level_result.priorities / level_result.priorities.max()
            index = {lv.id: k for k, lv in enumerate(inp.levels)}
            v = np.array([ideal[index[inp.ratings[a.id]]] for a in self.alternatives])
        return v / v.sum() if v.sum() > 0 else np.full(m, 1.0 / m)

    # ---- comparisons ---------------------------------------------------

    def comparison(self, key: str) -> Comparison:
        return self.comparisons.setdefault(key, Comparison())

    def comparison_sets(self) -> list[ComparisonSet]:
        sets = []
        for node, _, _ in self.walk():
            mode = "criteria" if node.children else self.scoring_mode(node)
            if mode == "direct":
                continue
            if mode == "ratings":
                levels = self.leaf_inputs[node.id].levels
                if len(levels) >= 2:
                    sets.append(ComparisonSet(
                        key=levels_key(node.id),
                        title=f"Rating levels for “{node.name}”",
                        group="Rating scales",
                        item_ids=[lv.id for lv in levels],
                        item_names=[lv.name for lv in levels],
                    ))
                continue
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
            mode = "criteria" if node.children else self.scoring_mode(node)
            if mode in ("direct", "ratings"):
                levels = self.level_priorities(node.id, overrides) if mode == "ratings" else None
                if levels is not None:
                    local[levels_key(node.id)] = levels
                p = self._scored_priorities(node, levels)
                # no judgments, so no consistency to report (cr=None)
                local[node.id] = PairwiseResult(p, float(len(p)), 0.0, 0.0, None)
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
            "scoring": {
                leaf_id: {
                    "mode": inp.mode,
                    "direction": inp.direction,
                    "unit": inp.unit,
                    "values": dict(inp.values),
                    "levels": [{"id": lv.id, "name": lv.name} for lv in inp.levels],
                    "ratings": dict(inp.ratings),
                }
                for leaf_id, inp in self.leaf_inputs.items()
                if not inp.is_default()
            },
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
        # "scoring" was added in format version 2; older files have only pairwise leaves
        for leaf_id, d in data.get("scoring", {}).items():
            mode = d.get("mode", "pairwise")
            direction = d.get("direction", "benefit")
            model.leaf_inputs[leaf_id] = LeafInput(
                mode=mode if mode in SCORING_MODES else "pairwise",
                direction=direction if direction in DIRECTIONS else "benefit",
                unit=str(d.get("unit", "")),
                values={a: float(v) for a, v in d.get("values", {}).items()},
                levels=[RatingLevel(lv["name"], lv.get("id") or new_id()) for lv in d.get("levels", [])],
                ratings=dict(d.get("ratings", {})),
            )
        model.cleanup()
        return model


def _move(items: list, item_id: str, delta: int) -> None:
    idx = next((k for k, x in enumerate(items) if x.id == item_id), None)
    if idx is None:
        return
    target = idx + delta
    if 0 <= target < len(items):
        items[idx], items[target] = items[target], items[idx]
