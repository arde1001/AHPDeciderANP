"""Saving/loading projects as JSON and exporting results as CSV."""

from __future__ import annotations

import csv
import json
import math
from pathlib import Path

from .ahp import GOAL_ID, AHPModel
from .anp import ANPModel

FORMAT = "ahp-anp-decisionmaker"
VERSION = 2  # 2: AHP leaf scoring methods (direct values, ratings); version 1 files load unchanged

Model = AHPModel | ANPModel


def model_to_dict(model: Model) -> dict:
    return {"format": FORMAT, "version": VERSION, **model.to_dict()}


def model_from_dict(data: dict) -> Model:
    if data.get("format") not in (None, FORMAT):
        raise ValueError("not an AHP/ANP decision maker project")
    version = data.get("version", 1)
    if not isinstance(version, int) or version > VERSION:
        raise ValueError(f"project format version {version} is newer than this program supports ({VERSION}); update the program")
    kind = data.get("type")
    if kind == "ahp":
        return AHPModel.from_dict(data)
    if kind == "anp":
        return ANPModel.from_dict(data)
    raise ValueError(f"unknown project type: {kind!r}")


def save(model: Model, path: str | Path) -> None:
    Path(path).write_text(json.dumps(model_to_dict(model), indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def load(path: str | Path) -> Model:
    return model_from_dict(json.loads(Path(path).read_text(encoding="utf-8")))


def _fmt(x: float) -> str:
    return "" if x is None or (isinstance(x, float) and math.isnan(x)) else f"{x:.6f}"


def _consistency_rows(model: Model, result) -> list[list[str]]:
    rows = [["Comparison", "Items", "Judgments made", "lambda_max", "CI", "CR", "Consistent (CR <= 0.10)"]]
    for s in model.comparison_sets():
        r = result.local.get(s.key)
        if r is None:
            continue
        pairs = len(s.item_ids) * (len(s.item_ids) - 1) // 2
        made = model.comparisons[s.key].count_set(s.item_ids) if s.key in model.comparisons else 0
        rows.append([
            s.title, str(len(s.item_ids)), f"{made}/{pairs}", _fmt(r.lambda_max), _fmt(r.ci),
            "" if r.cr is None else _fmt(r.cr), "yes" if r.consistent else "no",
        ])
    return rows


def export_csv(model: Model, path: str | Path) -> None:
    """Write weights, ranking and consistency of the model to one CSV file."""
    result = model.evaluate()
    rows: list[list[str]] = [["Decision", model.goal], ["Method", model.kind.upper()]]

    rows += [[], ["Alternatives"], ["Rank", "Alternative", "Score"]]
    for rank, k in enumerate(result.ranking(), 1):
        rows.append([str(rank), result.alternative_names[k], _fmt(result.alternative_scores[k])])

    if isinstance(model, AHPModel):
        rows[1].append(f"synthesis: {model.synthesis}")
        rows += [[], ["Criteria"], ["Criterion path", "Level", "Local weight", "Global weight", "Alternatives scored by"]]
        for node, _, depth in model.walk():
            if node.id == GOAL_ID:
                continue
            rows.append([
                " > ".join(model.path(node.id)), str(depth),
                _fmt(result.local_weights[node.id]), _fmt(result.global_weights[node.id]),
                "" if node.children else model.scoring_mode(node),
            ])
    else:
        rows += [[], ["Limit priorities"], ["Cluster", "Node", "Limit priority", "Normalized by cluster"]]
        for k in range(len(result.node_ids)):
            rows.append([result.node_clusters[k], result.node_names[k], _fmt(result.priorities[k]), _fmt(result.normalized[k])])
        rows += [[], ["Limit matrix status", result.limit_status]]

    rows += [[], ["Consistency"]] + _consistency_rows(model, result)

    with open(path, "w", newline="", encoding="utf-8") as f:
        csv.writer(f).writerows(rows)
