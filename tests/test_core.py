from pathlib import Path

import numpy as np
import pytest

from decisionmaker.core import project
from decisionmaker.core.ahp import GOAL_ID, AHPModel
from decisionmaker.core.anp import ANPModel, cluster_key, limit_matrix, node_key
from decisionmaker.core.pairwise import (
    Comparison,
    analyze,
    format_judgment,
    parse_judgment,
    random_index,
    reweight,
    snap_to_scale,
)
from decisionmaker.core.sensitivity import run_sensitivity

EXAMPLES = Path(__file__).resolve().parents[1] / "decisionmaker" / "examples"


# ---- pairwise ----------------------------------------------------------


def test_parse_and_format_judgments():
    assert parse_judgment("3") == 3
    assert parse_judgment(" 1/5 ") == pytest.approx(0.2)
    assert parse_judgment("0.34") == pytest.approx(1 / 3)
    assert format_judgment(1 / 7) == "1/7"
    assert format_judgment(9) == "9"
    for bad in ["", "abc", "10", "1/10", "0", "-3"]:
        with pytest.raises(ValueError):
            parse_judgment(bad)


def test_snap_to_scale():
    assert snap_to_scale(2.9) == 3
    assert snap_to_scale(0.3) == pytest.approx(1 / 3)
    assert snap_to_scale(50) == 9


def test_consistent_matrix_recovers_ratios():
    # w = (4, 2, 1) / 7
    m = np.array([[1, 2, 4], [1 / 2, 1, 2], [1 / 4, 1 / 2, 1]])
    r = analyze(m)
    assert r.priorities == pytest.approx(np.array([4, 2, 1]) / 7)
    assert r.lambda_max == pytest.approx(3)
    assert r.cr == pytest.approx(0, abs=1e-9)
    assert r.consistent
    assert r.hints == []


def test_saaty_textbook_example():
    m = np.array([[1, 1 / 3, 1 / 2], [3, 1, 3], [2, 1 / 3, 1]])
    r = analyze(m)
    assert r.priorities == pytest.approx([0.1571, 0.5936, 0.2493], abs=1e-3)
    assert r.lambda_max == pytest.approx(3.0536, abs=1e-3)
    assert r.cr == pytest.approx(0.0462, abs=1e-3)


def test_inconsistent_matrix_hints_point_at_bad_judgment():
    # consistent chain w = (8, 4, 2, 1), except a14 is 1/8 instead of 8
    w = np.array([8, 4, 2, 1])
    m = w[:, None] / w[None, :]
    m[0, 3], m[3, 0] = 1 / 8, 8
    r = analyze(m)
    assert not r.consistent
    top = r.hints[0]
    assert (top.i, top.j) == (0, 3)
    assert top.suggested > top.current  # nudges the judgment the right way


def test_two_items_have_no_cr():
    r = analyze(np.array([[1, 5], [1 / 5, 1]]))
    assert r.cr is None and r.consistent
    assert r.priorities == pytest.approx([5 / 6, 1 / 6])


def test_random_index_extends_past_15():
    assert random_index(3) == 0.58
    assert 1.55 < random_index(20) < 1.7


def test_comparison_is_keyed_by_id():
    c = Comparison()
    c.set("a", "b", 3)
    c.set("c", "b", 1 / 5)
    assert c.get("b", "a") == pytest.approx(1 / 3)
    assert c.matrix(["b", "c", "a"])[1, 0] == pytest.approx(1 / 5)
    c.set("b", "a", 2)  # overwrite from the other side
    assert c.get("a", "b") == pytest.approx(1 / 2)
    assert len(c) == 2
    c.prune({"a", "b"})
    assert len(c) == 1 and not c.is_set("b", "c")
    assert Comparison.from_json(c.to_json()).get("a", "b") == pytest.approx(0.5)


def test_reweight_keeps_ratios_of_others():
    w = reweight(np.array([0.5, 0.3, 0.2]), 0, 0.8)
    assert w.sum() == pytest.approx(1)
    assert w[0] == pytest.approx(0.8)
    assert w[1] / w[2] == pytest.approx(1.5)
    assert reweight(np.array([1.0, 0.0, 0.0]), 0, 0.4) == pytest.approx([0.4, 0.3, 0.3])


# ---- AHP ---------------------------------------------------------------


def small_ahp():
    m = AHPModel("Pick")
    c1 = m.add_criterion("C1")
    c2 = m.add_criterion("C2")
    s1 = m.add_criterion("S1", c2.id)
    s2 = m.add_criterion("S2", c2.id)
    x = m.add_alternative("X")
    y = m.add_alternative("Y")
    m.comparison(GOAL_ID).set(c1.id, c2.id, 3)  # C1 .75, C2 .25
    m.comparison(c2.id).set(s1.id, s2.id, 1)  # S1 .125, S2 .125 global
    m.comparison(c1.id).set(x.id, y.id, 4)  # X .8
    m.comparison(s1.id).set(x.id, y.id, 1 / 4)  # X .2
    m.comparison(s2.id).set(x.id, y.id, 1)  # X .5
    return m, (c1, c2, s1, s2, x, y)


def test_ahp_synthesis_by_hand():
    m, (c1, c2, s1, s2, x, y) = small_ahp()
    r = m.evaluate()
    assert r.global_weights[c1.id] == pytest.approx(0.75)
    assert r.global_weights[s2.id] == pytest.approx(0.125)
    assert r.local_weights[s1.id] == pytest.approx(0.5)
    expected_x = 0.75 * 0.8 + 0.125 * 0.2 + 0.125 * 0.5
    assert r.alternative_scores == pytest.approx([expected_x, 1 - expected_x])
    assert r.ranking() == [0, 1]


def test_ahp_ideal_mode():
    m, _ = small_ahp()
    r = m.evaluate(synthesis="ideal")
    x = 0.75 * 1 + 0.125 * (0.2 / 0.8) + 0.125 * 1
    y = 0.75 * (0.2 / 0.8) + 0.125 * 1 + 0.125 * 1
    assert r.alternative_scores == pytest.approx([x / (x + y), y / (x + y)])


def test_ahp_structure_edits_keep_judgments():
    m, (c1, c2, s1, s2, x, y) = small_ahp()
    z = m.add_alternative("Z")
    assert m.comparison(c1.id).get(x.id, y.id) == 4  # still there
    m.remove_alternative(y.id)
    assert not m.comparison(c1.id).is_set(x.id, y.id)
    m.remove_criterion(c2.id)  # removes S1/S2 and their comparisons
    assert s1.id not in m.comparisons and m.find(s2.id) is None
    assert [s.key for s in m.comparison_sets()] == [c1.id]  # only X vs Z under C1
    assert z.id in m.comparison_sets()[0].item_ids


def test_ahp_without_criteria_compares_alternatives_against_goal():
    m = AHPModel("G")
    a, b = m.add_alternative("A"), m.add_alternative("B")
    m.comparison(GOAL_ID).set(a.id, b.id, 3)
    assert m.evaluate().alternative_scores == pytest.approx([0.75, 0.25])


def test_ahp_move():
    m, (c1, c2, *_rest) = small_ahp()
    m.move_criterion(c2.id, -1)
    assert [c.name for c in m.root.children] == ["C2", "C1"]
    m.move_criterion(c2.id, -1)  # already first: no-op
    assert m.root.children[0].id == c2.id


# ---- ANP ---------------------------------------------------------------


def test_limit_matrix_of_periodic_chain_is_cesaro_average():
    w = np.array([[0.0, 1.0], [1.0, 0.0]])
    lim, status = limit_matrix(w)
    assert lim == pytest.approx(np.full((2, 2), 0.5))
    assert "cyclic" in status


def test_limit_matrix_converges_to_stationary_distribution():
    w = np.array([[0.5, 0.2], [0.5, 0.8]])
    lim, status = limit_matrix(w)
    assert status == "converged"
    # stationary: x = W x -> x = (2/7, 5/7)
    assert lim[:, 0] == pytest.approx([2 / 7, 5 / 7])
    assert lim[:, 1] == pytest.approx([2 / 7, 5 / 7])


def ahp_as_anp(ahp: AHPModel) -> ANPModel:
    """Rebuild a one-level AHP model as an ANP network (goal -> criteria -> alternatives)."""
    anp = ANPModel(ahp.goal)
    gc = anp.add_cluster("Goal")
    goal = anp.add_node(gc.id, ahp.goal)
    cc = anp.add_cluster("Criteria")
    ac = anp.add_cluster("Alternatives")
    crit = {c.id: anp.add_node(cc.id, c.name) for c in ahp.root.children}
    alts = {a.id: anp.add_node(ac.id, a.name) for a in ahp.alternatives}
    for old, new in crit.items():
        anp.set_link(goal.id, new.id, True)
        for alt in alts.values():
            anp.set_link(new.id, alt.id, True)
        src = ahp.comparison(old)
        dst = anp.comparison(node_key(new.id, ac.id))
        for a in ahp.alternatives:
            for b in ahp.alternatives:
                if src.is_set(a.id, b.id):
                    dst.set(alts[a.id].id, alts[b.id].id, src.get(a.id, b.id))
    src = ahp.comparison(GOAL_ID)
    dst = anp.comparison(node_key(goal.id, cc.id))
    for a in ahp.root.children:
        for b in ahp.root.children:
            if src.is_set(a.id, b.id):
                dst.set(crit[a.id].id, crit[b.id].id, src.get(a.id, b.id))
    return anp


def test_anp_hierarchy_reproduces_ahp():
    ahp = project.load(EXAMPLES / "laptop_ahp.json")
    # flatten the example to one level so it can be expressed as a plain hierarchy network
    perf = next(c for c in ahp.root.children if c.children)
    ahp.remove_criterion(perf.id)
    anp = ahp_as_anp(ahp)
    ra, rn = ahp.evaluate(), anp.evaluate()
    assert anp.effective_start_node() is not None  # the goal is detected automatically
    assert len(rn.sinks) == len(ahp.alternatives)  # alternatives are absorbing
    assert rn.alternative_scores == pytest.approx(ra.alternative_scores, abs=1e-9)


def test_anp_feedback_network_is_start_independent():
    anp = project.load(EXAMPLES / "car_anp.json")
    r = anp.evaluate()
    assert r.limit_status == "converged"
    assert r.weighted.sum(axis=0) == pytest.approx(np.ones(len(r.node_ids)))
    # criteria + alternatives form one strongly connected component: columns agree
    alt_rows = [r.node_ids.index(i) for i in r.alternative_ids]
    cols = r.limit[np.ix_(alt_rows, range(len(r.node_ids)))]
    assert np.allclose(cols, cols[:, [1]])
    assert r.alternative_scores.sum() == pytest.approx(1)
    # stationary vector of the weighted supermatrix
    assert r.weighted @ r.priorities == pytest.approx(r.priorities)


def test_anp_cluster_weights_scale_blocks():
    anp = ANPModel()
    c1, c2 = anp.add_cluster("A"), anp.add_cluster("B")
    a1, a2 = anp.add_node(c1.id, "a1"), anp.add_node(c1.id, "a2")
    b1, b2 = anp.add_node(c2.id, "b1"), anp.add_node(c2.id, "b2")
    for j in (a1, a2):
        for i in (a1, a2, b1, b2):
            if i is not j:
                anp.set_link(j.id, i.id, True)
    for j in (b1, b2):
        for i in (a1, a2):
            anp.set_link(j.id, i.id, True)
    anp.comparison(cluster_key(c1.id)).set(c1.id, c2.id, 1 / 3)  # A: .25, B: .75
    r = anp.evaluate()
    col = r.node_ids.index(a1.id)
    assert r.cluster_matrix[:, 0] == pytest.approx([0.25, 0.75])
    assert r.weighted[r.node_ids.index(a2.id), col] == pytest.approx(0.25)  # only node of A linked
    assert r.weighted[r.node_ids.index(b1.id), col] == pytest.approx(0.375)
    assert r.weighted.sum(axis=0) == pytest.approx(np.ones(4))


def test_anp_cleanup_keeps_judgments_of_unlinked_nodes():
    anp = project.load(EXAMPLES / "car_anp.json")
    crit = next(c for c in anp.clusters if c.name == "Criteria")
    goal = anp.clusters[0].nodes[0]
    key = node_key(goal.id, crit.id)
    cost = crit.nodes[0]
    anp.set_link(goal.id, cost.id, False)
    anp.cleanup()
    assert len(anp.comparison(key)) == 3
    anp.remove_node(cost.id)
    assert len(anp.comparison(key)) == 1


# ---- sensitivity & files ------------------------------------------------


def test_sensitivity_matches_base_and_finds_reversal():
    m, (c1, *_rest) = small_ahp()
    s = run_sensitivity(m, GOAL_ID, 0, steps=201)
    assert s.current_weight == pytest.approx(0.75)
    assert s.scores_at(0.75) == pytest.approx(m.evaluate().alternative_scores, abs=1e-3)
    # X wins when C1 dominates, Y wins when C2 dominates -> one reversal
    assert len(s.reversals) == 1
    rev = s.reversals[0]
    assert (rev.before, rev.after) == (1, 0)
    # at the crossing X and Y tie: 0.8 w + 0.35 (1 - w) = 0.5
    assert rev.weight == pytest.approx(0.15 / 0.45, abs=1e-3)


def test_anp_sensitivity_runs():
    anp = project.load(EXAMPLES / "car_anp.json")
    key = next(s.key for s in anp.comparison_sets() if s.key.startswith("cluster:"))
    s = run_sensitivity(anp, key, 0, steps=21)
    assert s.scores.shape == (21, 3)
    # weight 1 for the criteria cluster cuts the alternatives off entirely
    assert np.allclose(s.scores[:-1].sum(axis=1), 1)
    assert np.allclose(s.scores[-1], 0)
    assert all(r.weight < 1 for r in s.reversals)


@pytest.mark.parametrize("name", ["laptop_ahp.json", "car_anp.json"])
def test_roundtrip_and_csv(tmp_path, name):
    model = project.load(EXAMPLES / name)
    out = tmp_path / "p.json"
    project.save(model, out)
    again = project.load(out)
    assert project.model_to_dict(again) == project.model_to_dict(model)
    assert again.evaluate().alternative_scores == pytest.approx(model.evaluate().alternative_scores)
    csv_path = tmp_path / "r.csv"
    project.export_csv(model, csv_path)
    text = csv_path.read_text()
    assert "Consistency" in text and "Alternatives" in text


def test_load_rejects_unknown_type():
    with pytest.raises(ValueError):
        project.model_from_dict({"type": "xyz"})
