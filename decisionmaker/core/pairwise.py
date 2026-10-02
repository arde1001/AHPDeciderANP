"""Pairwise comparison matrices on Saaty's 1-9 scale.

A judgment a_ij says how strongly item i dominates item j. The matrix is
reciprocal (a_ji = 1 / a_ij) with ones on the diagonal. Priorities are the
normalized principal right eigenvector; consistency is measured by Saaty's
consistency ratio CR = CI / RI with CI = (lambda_max - n) / (n - 1).
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from fractions import Fraction

import numpy as np

# 1/9, 1/8, ..., 1/2, 1, 2, ..., 9
SCALE_VALUES: tuple[float, ...] = tuple(
    [1.0 / k for k in range(9, 1, -1)] + [float(k) for k in range(1, 10)]
)

VERBAL_SCALE: dict[int, str] = {
    1: "Equal",
    2: "Equal to moderate",
    3: "Moderate",
    4: "Moderate to strong",
    5: "Strong",
    6: "Strong to very strong",
    7: "Very strong",
    8: "Very strong to extreme",
    9: "Extreme",
}

# Saaty's random consistency index for n = 1..15.
_SAATY_RI = {
    1: 0.0, 2: 0.0, 3: 0.58, 4: 0.90, 5: 1.12, 6: 1.24, 7: 1.32, 8: 1.41,
    9: 1.45, 10: 1.49, 11: 1.51, 12: 1.48, 13: 1.56, 14: 1.57, 15: 1.59,
}

CR_THRESHOLD = 0.10


def random_index(n: int) -> float:
    """Random consistency index; Alonso & Lamata's fit beyond n = 15."""
    if n in _SAATY_RI:
        return _SAATY_RI[n]
    return (2.7699 * n - 4.3513 - n) / (n - 1)


def snap_to_scale(value: float) -> float:
    """Nearest value on the 1-9 scale (with reciprocals), measured in log space."""
    if value <= 0 or not math.isfinite(value):
        raise ValueError(f"judgment must be a positive number, got {value!r}")
    log_v = math.log(value)
    return min(SCALE_VALUES, key=lambda s: abs(math.log(s) - log_v))


def parse_judgment(text: str) -> float:
    """Parse '3', '1/5' or '0.2' into a scale value. Raises ValueError."""
    text = text.strip().replace(" ", "")
    if not text:
        raise ValueError("empty judgment")
    try:
        value = float(Fraction(text))
    except (ValueError, ZeroDivisionError):
        raise ValueError(f"not a number: {text!r}") from None
    if not (1 / 9 - 1e-9 <= value <= 9 + 1e-9):
        raise ValueError("judgment must be between 1/9 and 9")
    return snap_to_scale(value)


def format_judgment(value: float) -> str:
    """'3' for 3.0, '1/3' for 0.333..."""
    value = snap_to_scale(value)
    if value >= 1:
        return str(round(value))
    return f"1/{round(1 / value)}"


def describe_judgment(value: float) -> str:
    """Verbal meaning of the strength of a judgment, e.g. 'Strong'."""
    value = snap_to_scale(value)
    strength = round(value if value >= 1 else 1 / value)
    return VERBAL_SCALE[strength]


def reweight(priorities: np.ndarray, index: int, weight: float) -> np.ndarray:
    """Set one priority to `weight`; rescale the others to keep their ratios.

    This is the standard one-at-a-time sensitivity perturbation.
    """
    w = np.asarray(priorities, dtype=float).copy()
    n = len(w)
    if n == 1:
        return np.ones(1)
    rest = 1.0 - w[index]
    others = np.arange(n) != index
    if rest <= 1e-12:
        w[others] = (1.0 - weight) / (n - 1)
    else:
        w[others] = w[others] * (1.0 - weight) / rest
    w[index] = weight
    return w


@dataclass
class Inconsistency:
    """A judgment that disagrees with the priorities derived from the matrix."""

    i: int
    j: int
    current: float
    suggested: float
    deviation: float  # |ln(a_ij * w_j / w_i)|; 0 means perfectly consistent


@dataclass
class PairwiseResult:
    priorities: np.ndarray
    lambda_max: float
    ci: float
    ri: float
    cr: float | None  # None when n < 3 (always consistent)
    hints: list[Inconsistency] = field(default_factory=list)

    @property
    def n(self) -> int:
        return len(self.priorities)

    @property
    def consistent(self) -> bool:
        return self.cr is None or self.cr <= CR_THRESHOLD


def principal_eigenvector(matrix: np.ndarray) -> tuple[np.ndarray, float]:
    """Normalized principal right eigenvector and its eigenvalue."""
    n = matrix.shape[0]
    if n == 0:
        return np.zeros(0), 0.0
    if n == 1:
        return np.ones(1), 1.0
    values, vectors = np.linalg.eig(matrix)
    k = int(np.argmax(values.real))
    w = np.abs(vectors[:, k].real)
    return w / w.sum(), float(values[k].real)


def inconsistency_hints(matrix: np.ndarray, priorities: np.ndarray) -> list[Inconsistency]:
    """Upper-triangle judgments ranked by how far they are from w_i / w_j."""
    n = matrix.shape[0]
    hints = []
    for i in range(n):
        for j in range(i + 1, n):
            ratio = priorities[i] / priorities[j]
            deviation = abs(math.log(matrix[i, j] / ratio))
            suggested = snap_to_scale(ratio)
            if deviation > 1e-9:
                hints.append(Inconsistency(i, j, float(matrix[i, j]), suggested, deviation))
    hints.sort(key=lambda h: h.deviation, reverse=True)
    return hints


def analyze(matrix: np.ndarray) -> PairwiseResult:
    """Priorities and consistency of a reciprocal pairwise comparison matrix."""
    n = matrix.shape[0]
    w, lam = principal_eigenvector(matrix)
    if n < 3:
        return PairwiseResult(w, float(max(lam, n)), 0.0, 0.0, None)
    ci = max(0.0, (lam - n) / (n - 1))
    ri = random_index(n)
    cr = ci / ri if ri > 0 else 0.0
    return PairwiseResult(w, lam, ci, ri, cr, inconsistency_hints(matrix, w))


class Comparison:
    """Judgments between items, keyed by stable item ids.

    Keying by id (not by position) means adding, removing, renaming or
    reordering items keeps every judgment that still applies. Pairs that were
    never judged count as equal (1).
    """

    def __init__(self, judgments: dict[tuple[str, str], float] | None = None):
        self._j: dict[tuple[str, str], float] = {}
        for (a, b), v in (judgments or {}).items():
            self.set(a, b, v)

    def get(self, a: str, b: str) -> float:
        if a == b:
            return 1.0
        if (a, b) in self._j:
            return self._j[(a, b)]
        if (b, a) in self._j:
            return 1.0 / self._j[(b, a)]
        return 1.0

    def set(self, a: str, b: str, value: float) -> None:
        if a == b:
            return
        self._j.pop((b, a), None)
        self._j[(a, b)] = snap_to_scale(value)

    def is_set(self, a: str, b: str) -> bool:
        return (a, b) in self._j or (b, a) in self._j

    def count_set(self, ids: list[str]) -> int:
        return sum(
            self.is_set(ids[i], ids[j]) for i in range(len(ids)) for j in range(i + 1, len(ids))
        )

    def matrix(self, ids: list[str]) -> np.ndarray:
        n = len(ids)
        m = np.ones((n, n))
        for i in range(n):
            for j in range(i + 1, n):
                v = self.get(ids[i], ids[j])
                m[i, j] = v
                m[j, i] = 1.0 / v
        return m

    def prune(self, valid_ids: set[str]) -> None:
        """Drop judgments that reference items no longer in the set."""
        self._j = {k: v for k, v in self._j.items() if k[0] in valid_ids and k[1] in valid_ids}

    def __len__(self) -> int:
        return len(self._j)

    def to_json(self) -> list:
        return [[a, b, format_judgment(v)] for (a, b), v in self._j.items()]

    @classmethod
    def from_json(cls, data: list) -> Comparison:
        c = cls()
        for a, b, v in data:
            c.set(a, b, parse_judgment(str(v)))
        return c


@dataclass
class ComparisonSet:
    """One pairwise comparison the user has to make."""

    key: str
    title: str  # e.g. "Criteria w.r.t. Choose a car"
    group: str  # heading used to group sets in the UI
    item_ids: list[str]
    item_names: list[str]
