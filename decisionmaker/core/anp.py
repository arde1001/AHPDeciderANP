"""Analytic Network Process: clusters of nodes with arbitrary dependence.

Conventions (the same as the supermatrix layout):

* A link ``(j, i)`` means node *i* is compared with respect to node *j*
  ("i influences j"). Its priority lands in row i, column j of the
  supermatrix.
* For every control node j and every cluster C that j links into, the linked
  nodes of C are compared pairwise with respect to j. One linked node gets
  priority 1.
* For every cluster D, the clusters its nodes link into are compared
  pairwise with respect to D, giving the cluster weight matrix.

Unweighted supermatrix W: block (C, D) column j holds the priorities of C's
nodes with respect to j. Weighted supermatrix: every block is multiplied by
its cluster weight and each column is renormalized to sum to 1 (a column is
short when its node links into only some of its cluster's target clusters).
Columns of nodes with no links at all (sinks, e.g. alternatives in a plain
hierarchy) get a 1 on the diagonal, which makes them absorbing, as in Saaty's
hierarchy-as-supermatrix formulation. The limit matrix is lim W^k, using the
Cesàro average when the powers cycle.

Final priorities are ``limit @ start``, where start is the unit vector of the
start (goal) node if there is one, else uniform. For a strongly connected
network every column of the limit matrix is the same, so the start does not
matter; for a network with sinks it does.
"""

from __future__ import annotations

import dataclasses
from dataclasses import dataclass, field

import numpy as np

from .ahp import _move, new_id
from .pairwise import Comparison, ComparisonSet, PairwiseResult, analyze


@dataclass
class Node:
    name: str
    id: str = field(default_factory=new_id)


@dataclass
class Cluster:
    name: str
    id: str = field(default_factory=new_id)
    nodes: list[Node] = field(default_factory=list)


def node_key(control_id: str, cluster_id: str) -> str:
    return f"node:{control_id}:{cluster_id}"


def cluster_key(cluster_id: str) -> str:
    return f"cluster:{cluster_id}"


def limit_matrix(w: np.ndarray, tol: float = 1e-10, max_squarings: int = 64) -> tuple[np.ndarray, str]:
    """lim W^k of a column-stochastic matrix, averaging over a cycle if periodic."""
    n = w.shape[0]
    if n == 0:
        return w.copy(), "empty"
    p = w.copy()
    for _ in range(max_squarings):
        q = p @ p
        done = np.abs(q - p).max() < tol
        p = q
        if done:
            break
    # p is a high power of W. If one more multiplication leaves it unchanged it
    # is the limit; otherwise the powers cycle and we average one full cycle.
    powers = [p]
    q = p
    for period in range(1, n + 1):
        q = q @ w
        if np.abs(q - p).max() < 1e-8:
            if period == 1:
                return p, "converged"
            return np.mean(powers, axis=0), f"cyclic with period {period}; Cesàro average used"
        powers.append(q)
    return np.mean(powers, axis=0), "did not converge; averaged the last powers"


@dataclass
class ANPResult:
    local: dict[str, PairwiseResult]
    node_ids: list[str]  # supermatrix order
    node_names: list[str]
    node_clusters: list[str]  # cluster name for each node
    cluster_ids: list[str]
    cluster_names: list[str]
    unweighted: np.ndarray
    cluster_matrix: np.ndarray
    weighted: np.ndarray
    limit: np.ndarray
    limit_status: str
    sinks: list[str]  # node ids given an absorbing diagonal
    start_node: str | None
    priorities: np.ndarray  # limit priorities of every node
    normalized: np.ndarray  # priorities normalized within each cluster (nan if the cluster sums to 0)
    alternative_ids: list[str]
    alternative_names: list[str]
    alternative_scores: np.ndarray

    def ranking(self) -> list[int]:
        return sorted(range(len(self.alternative_scores)), key=lambda k: -self.alternative_scores[k])


class ANPModel:
    kind = "anp"

    def __init__(self, goal: str = "Decision"):
        self.goal = goal
        self.clusters: list[Cluster] = []
        self.links: set[tuple[str, str]] = set()
        self.comparisons: dict[str, Comparison] = {}
        self.alternatives_cluster: str | None = None
        self.start_node: str | None = None

    # ---- structure -----------------------------------------------------

    def nodes(self) -> list[tuple[Node, Cluster]]:
        return [(n, c) for c in self.clusters for n in c.nodes]

    def node(self, node_id: str) -> Node | None:
        return next((n for n, _ in self.nodes() if n.id == node_id), None)

    def cluster(self, cluster_id: str) -> Cluster | None:
        return next((c for c in self.clusters if c.id == cluster_id), None)

    def cluster_of(self, node_id: str) -> Cluster | None:
        return next((c for n, c in self.nodes() if n.id == node_id), None)

    def add_cluster(self, name: str) -> Cluster:
        cluster = Cluster(name)
        self.clusters.append(cluster)
        return cluster

    def add_node(self, cluster_id: str, name: str) -> Node:
        cluster = self.cluster(cluster_id)
        if cluster is None:
            raise KeyError(cluster_id)
        node = Node(name)
        cluster.nodes.append(node)
        return node

    def remove_cluster(self, cluster_id: str) -> None:
        self.clusters = [c for c in self.clusters if c.id != cluster_id]
        self.cleanup()

    def remove_node(self, node_id: str) -> None:
        for c in self.clusters:
            c.nodes = [n for n in c.nodes if n.id != node_id]
        self.cleanup()

    def move_cluster(self, cluster_id: str, delta: int) -> None:
        _move(self.clusters, cluster_id, delta)

    def move_node(self, node_id: str, delta: int) -> None:
        cluster = self.cluster_of(node_id)
        if cluster is not None:
            _move(cluster.nodes, node_id, delta)

    def is_linked(self, control_id: str, node_id: str) -> bool:
        return (control_id, node_id) in self.links

    def set_link(self, control_id: str, node_id: str, on: bool) -> None:
        if on:
            self.links.add((control_id, node_id))
        else:
            self.links.discard((control_id, node_id))

    def targets(self, control_id: str, cluster: Cluster) -> list[Node]:
        """Nodes of `cluster` compared with respect to `control_id`."""
        return [n for n in cluster.nodes if (control_id, n.id) in self.links]

    def cluster_targets(self, cluster: Cluster) -> list[Cluster]:
        """Clusters that any node of `cluster` links into."""
        return [c for c in self.clusters if any(self.targets(j.id, c) for j in cluster.nodes)]

    def effective_alternatives_cluster(self) -> Cluster | None:
        if self.alternatives_cluster and self.cluster(self.alternatives_cluster):
            return self.cluster(self.alternatives_cluster)
        named = [c for c in self.clusters if "altern" in c.name.lower()]
        if named:
            return named[0]
        return self.clusters[-1] if self.clusters else None

    def effective_start_node(self) -> str | None:
        """The chosen start node, else the single node that nothing links into (the goal)."""
        if self.start_node and self.node(self.start_node):
            return self.start_node
        incoming = {i for _, i in self.links}
        outgoing = {j for j, _ in self.links}
        sources = [n.id for n, _ in self.nodes() if n.id in outgoing and n.id not in incoming]
        return sources[0] if len(sources) == 1 else None

    def cleanup(self) -> None:
        """Drop links, comparisons and judgments that refer to deleted things.

        Judgments of nodes that were merely unlinked are kept, so ticking a
        link again restores them.
        """
        live_nodes = {n.id for n, _ in self.nodes()}
        live_clusters = {c.id for c in self.clusters}
        self.links = {(j, i) for j, i in self.links if j in live_nodes and i in live_nodes}
        kept = {}
        for key, comparison in self.comparisons.items():
            parts = key.split(":")
            if parts[0] == "node" and parts[1] in live_nodes and parts[2] in live_clusters:
                comparison.prune({n.id for n in self.cluster(parts[2]).nodes})
                kept[key] = comparison
            elif parts[0] == "cluster" and parts[1] in live_clusters:
                comparison.prune(live_clusters)
                kept[key] = comparison
        self.comparisons = kept
        if self.alternatives_cluster not in live_clusters:
            self.alternatives_cluster = None
        if self.start_node not in live_nodes:
            self.start_node = None

    def warnings(self) -> list[str]:
        out = []
        alt = self.effective_alternatives_cluster()
        if alt is None or len(alt.nodes) < 2:
            out.append("The alternatives cluster needs at least two nodes.")
        incoming = {i for _, i in self.links}
        outgoing = {j for j, _ in self.links}
        for n, c in self.nodes():
            if n.id not in incoming and n.id not in outgoing:
                out.append(f"“{n.name}” ({c.name}) has no connections.")
            elif alt is not None and c.id == alt.id and n.id not in incoming:
                out.append(f"Alternative “{n.name}” is never compared with respect to anything.")
        if self.effective_start_node() is None and not self.start_node:
            out.append(
                "No single goal/start node found; results use the average over all columns of the "
                "limit matrix. Pick a start node if the network has a goal."
            )
        return out

    # ---- comparisons ---------------------------------------------------

    def comparison(self, key: str) -> Comparison:
        return self.comparisons.setdefault(key, Comparison())

    def comparison_sets(self) -> list[ComparisonSet]:
        sets = []
        for control, control_cluster in self.nodes():
            for cluster in self.clusters:
                items = self.targets(control.id, cluster)
                if len(items) >= 2:
                    sets.append(
                        ComparisonSet(
                            key=node_key(control.id, cluster.id),
                            title=f"“{cluster.name}” nodes with respect to “{control.name}”",
                            group=f"Nodes w.r.t. {control_cluster.name}",
                            item_ids=[n.id for n in items],
                            item_names=[n.name for n in items],
                        )
                    )
        for cluster in self.clusters:
            items = self.cluster_targets(cluster)
            if len(items) >= 2:
                sets.append(
                    ComparisonSet(
                        key=cluster_key(cluster.id),
                        title=f"Clusters with respect to cluster “{cluster.name}”",
                        group="Cluster comparisons",
                        item_ids=[c.id for c in items],
                        item_names=[c.name for c in items],
                    )
                )
        return sets

    # ---- evaluation ----------------------------------------------------

    def _analyze(self, key: str, ids: list[str], overrides: dict[str, np.ndarray]) -> PairwiseResult:
        result = analyze(self.comparisons.get(key, Comparison()).matrix(ids))
        if key in overrides:
            result = dataclasses.replace(result, priorities=np.asarray(overrides[key], float))
        return result

    def evaluate(self, overrides: dict[str, np.ndarray] | None = None) -> ANPResult:
        overrides = overrides or {}
        pairs = self.nodes()
        ids = [n.id for n, _ in pairs]
        index = {nid: k for k, nid in enumerate(ids)}
        cluster_index = {c.id: k for k, c in enumerate(self.clusters)}
        node_cluster = np.array([cluster_index[c.id] for _, c in pairs], dtype=int)
        n, m = len(ids), len(self.clusters)
        local: dict[str, PairwiseResult] = {}

        unweighted = np.zeros((n, n))
        for control, _ in pairs:
            for cluster in self.clusters:
                items = self.targets(control.id, cluster)
                if not items:
                    continue
                key = node_key(control.id, cluster.id)
                res = self._analyze(key, [x.id for x in items], overrides)
                local[key] = res
                for k, item in enumerate(items):
                    unweighted[index[item.id], index[control.id]] = res.priorities[k]

        cluster_matrix = np.zeros((m, m))
        for cluster in self.clusters:
            items = self.cluster_targets(cluster)
            if not items:
                continue
            key = cluster_key(cluster.id)
            res = self._analyze(key, [c.id for c in items], overrides)
            local[key] = res
            for k, item in enumerate(items):
                cluster_matrix[cluster_index[item.id], cluster_index[cluster.id]] = res.priorities[k]

        weighted = unweighted * cluster_matrix[np.ix_(node_cluster, node_cluster)] if n else unweighted.copy()
        sinks = []
        for j in range(n):
            s = weighted[:, j].sum()
            if s > 1e-12:
                weighted[:, j] /= s
            else:
                weighted[:, j] = 0.0
                weighted[j, j] = 1.0
                sinks.append(ids[j])

        limit, status = limit_matrix(weighted)
        start_node = self.effective_start_node()
        if n == 0:
            start = np.zeros(0)
        elif start_node is not None:
            start = np.zeros(n)
            start[index[start_node]] = 1.0
        else:
            start = np.full(n, 1.0 / n)
        priorities = limit @ start

        normalized = np.full(n, np.nan)
        for c in range(m):
            mask = node_cluster == c
            total = priorities[mask].sum()
            if total > 1e-12:
                normalized[mask] = priorities[mask] / total

        alt = self.effective_alternatives_cluster()
        alt_nodes = alt.nodes if alt else []
        scores = np.array([priorities[index[x.id]] for x in alt_nodes])
        if scores.sum() > 1e-12:
            scores = scores / scores.sum()

        return ANPResult(
            local=local,
            node_ids=ids,
            node_names=[x.name for x, _ in pairs],
            node_clusters=[c.name for _, c in pairs],
            cluster_ids=[c.id for c in self.clusters],
            cluster_names=[c.name for c in self.clusters],
            unweighted=unweighted,
            cluster_matrix=cluster_matrix,
            weighted=weighted,
            limit=limit,
            limit_status=status,
            sinks=sinks,
            start_node=start_node,
            priorities=priorities,
            normalized=normalized,
            alternative_ids=[x.id for x in alt_nodes],
            alternative_names=[x.name for x in alt_nodes],
            alternative_scores=scores,
        )

    # ---- serialization -------------------------------------------------

    def to_dict(self) -> dict:
        return {
            "type": self.kind,
            "goal": self.goal,
            "clusters": [
                {"id": c.id, "name": c.name, "nodes": [{"id": x.id, "name": x.name} for x in c.nodes]}
                for c in self.clusters
            ],
            "links": sorted([j, i] for j, i in self.links),
            "comparisons": {k: c.to_json() for k, c in self.comparisons.items() if len(c)},
            "alternatives_cluster": self.alternatives_cluster,
            "start_node": self.start_node,
        }

    @classmethod
    def from_dict(cls, data: dict) -> ANPModel:
        model = cls(data.get("goal", "Decision"))
        model.clusters = [
            Cluster(c["name"], c.get("id") or new_id(), [Node(x["name"], x.get("id") or new_id()) for x in c.get("nodes", [])])
            for c in data.get("clusters", [])
        ]
        model.links = {(j, i) for j, i in data.get("links", [])}
        model.comparisons = {k: Comparison.from_json(v) for k, v in data.get("comparisons", {}).items()}
        model.alternatives_cluster = data.get("alternatives_cluster")
        model.start_node = data.get("start_node")
        model.cleanup()
        return model
