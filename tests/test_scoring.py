"""Leaf scoring by direct values and ratings, and loading version-1 project files."""

import json
import zipfile
from pathlib import Path

import numpy as np
import pytest

from decisionmaker.core import project
from decisionmaker.core.ahp import DEFAULT_LEVELS, GOAL_ID, AHPModel, levels_key
from decisionmaker.core.exchange import build_tables, export_csv_zip
from decisionmaker.core.sensitivity import run_sensitivity

HERE = Path(__file__).resolve().parent
EXAMPLES = HERE.parent / "decisionmaker" / "examples"


def model_with_leaves():
    m = AHPModel("Pick")
    battery = m.add_criterion("Battery")
    price = m.add_criterion("Price")
    looks = m.add_criterion("Looks")
    alts = [m.add_alternative(n) for n in ("A", "B", "C")]
    m.comparison(GOAL_ID).set(battery.id, price.id, 1)
    m.comparison(GOAL_ID).set(battery.id, looks.id, 1)
    m.comparison(GOAL_ID).set(price.id, looks.id, 1)
    return m, battery, price, looks, alts


def test_direct_benefit_and_cost():
    m, battery, price, _looks, (a, b, c) = model_with_leaves()
    m.set_scoring_mode(battery.id, "direct")
    m.scoring(battery.id).values = {a.id: 10, b.id: 5, c.id: 15}
    m.set_scoring_mode(price.id, "direct")
    inp = m.scoring(price.id)
    inp.direction = "cost"
    inp.values = {a.id: 100, b.id: 200, c.id: 400}
    r = m.evaluate()
    assert r.local[battery.id].priorities == pytest.approx([1 / 3, 1 / 6, 1 / 2])
    inv = np.array([1 / 100, 1 / 200, 1 / 400])
    assert r.local[price.id].priorities == pytest.approx(inv / inv.sum())
    assert r.local[battery.id].cr is None  # no judgments -> nothing to be inconsistent
    keys = {s.key for s in m.comparison_sets()}
    assert battery.id not in keys and price.id not in keys


def test_scaling_by_mean_or_sum_is_the_same():
    m, battery, *_rest, (a, b, c) = model_with_leaves()
    m.set_scoring_mode(battery.id, "direct")
    m.scoring(battery.id).values = {a.id: 10, b.id: 5, c.id: 15}
    first = m.evaluate().local[battery.id].priorities
    m.scoring(battery.id).values = {a.id: 10 / 10, b.id: 5 / 10, c.id: 15 / 10}  # divided by the mean
    assert m.evaluate().local[battery.id].priorities == pytest.approx(first)


def test_ratings_use_idealized_level_weights():
    m, _battery, _price, looks, (a, b, c) = model_with_leaves()
    m.set_scoring_mode(looks.id, "ratings")
    levels = m.scoring(looks.id).levels
    assert [lv.name for lv in levels] == [name for name, _ in DEFAULT_LEVELS]
    assert levels_key(looks.id) in {s.key for s in m.comparison_sets()}
    m.scoring(looks.id).ratings = {a.id: levels[0].id, b.id: levels[2].id, c.id: levels[0].id}
    r = m.evaluate()
    lp = r.local[levels_key(looks.id)].priorities
    assert r.local[levels_key(looks.id)].consistent  # the default scale is consistent
    ideal = lp / lp.max()
    expected = np.array([ideal[0], ideal[2], ideal[0]])
    assert r.local[looks.id].priorities == pytest.approx(expected / expected.sum())
    # sensitivity on the rating scale itself works through the same override mechanism
    s = run_sensitivity(m, levels_key(looks.id), 0, steps=11)
    assert s.scores.shape == (11, 3)


def test_incomplete_data_counts_as_equal_and_warns():
    m, battery, price, looks, (a, b, c) = model_with_leaves()
    m.set_scoring_mode(battery.id, "direct")
    m.scoring(battery.id).values = {a.id: 10}
    m.set_scoring_mode(price.id, "direct")
    m.scoring(price.id).direction = "cost"
    m.scoring(price.id).values = {a.id: 0, b.id: 1, c.id: 2}
    m.set_scoring_mode(looks.id, "ratings")
    r = m.evaluate()
    for leaf in (battery, price, looks):
        assert r.local[leaf.id].priorities == pytest.approx([1 / 3] * 3)
    text = " ".join(m.warnings())
    assert "no value for B, C" in text and "can't have a value of 0" in text and "not rated" in text


def test_switching_back_to_pairwise_keeps_judgments():
    m, battery, *_rest, (a, b, c) = model_with_leaves()
    m.comparison(battery.id).set(a.id, b.id, 5)
    m.set_scoring_mode(battery.id, "direct")
    m.set_scoring_mode(battery.id, "pairwise")
    assert battery.id not in m.leaf_inputs or m.leaf_inputs[battery.id].mode == "pairwise"
    assert m.comparison(battery.id).get(a.id, b.id) == 5
    assert battery.id in {s.key for s in m.comparison_sets()}


def test_cleanup_prunes_alternatives_and_levels():
    m, battery, _price, looks, (a, b, c) = model_with_leaves()
    m.set_scoring_mode(battery.id, "direct")
    m.scoring(battery.id).values = {a.id: 1, b.id: 2, c.id: 3}
    m.set_scoring_mode(looks.id, "ratings")
    levels = m.scoring(looks.id).levels
    m.scoring(looks.id).ratings = {a.id: levels[0].id, b.id: levels[1].id, c.id: levels[1].id}
    m.remove_alternative(c.id)
    assert c.id not in m.scoring(battery.id).values
    m.remove_level(looks.id, levels[1].id)
    assert m.scoring(looks.id).ratings == {a.id: levels[0].id}
    assert len(m.comparison(levels_key(looks.id))) == 6  # 4 levels left: 4*3/2 pairs
    # a scored leaf that gains a sub-criterion stops being scored, but its data is kept
    sub = m.add_criterion("Sub", battery.id)
    assert battery.id in m.leaf_inputs
    m.remove_criterion(sub.id)
    assert m.scoring_mode(battery) == "direct"


def test_save_load_roundtrip_with_scoring(tmp_path):
    m, battery, _price, looks, (a, b, c) = model_with_leaves()
    m.set_scoring_mode(battery.id, "direct")
    inp = m.scoring(battery.id)
    inp.values, inp.unit, inp.direction = {a.id: 10, b.id: 5, c.id: 15}, "h", "benefit"
    m.set_scoring_mode(looks.id, "ratings")
    m.scoring(looks.id).ratings = {x.id: m.scoring(looks.id).levels[k].id for k, x in enumerate((a, b, c))}
    path = tmp_path / "p.json"
    project.save(m, path)
    data = json.loads(path.read_text())
    assert data["version"] == 2 and set(data["scoring"]) == {battery.id, looks.id}
    again = project.load(path)
    assert again.scoring(battery.id).unit == "h"
    assert again.evaluate().alternative_scores == pytest.approx(m.evaluate().alternative_scores)


@pytest.mark.parametrize("name", ["laptop_ahp_v1.json", "car_anp_v1.json"])
def test_version_1_files_still_load(tmp_path, name):
    old = HERE / "data" / name
    data = json.loads(old.read_text())
    assert data["version"] == 1 and "scoring" not in data
    model = project.load(old)
    if model.kind == "ahp":
        assert model.leaf_inputs == {}
        assert all(model.scoring_mode(leaf) == "pairwise" for leaf in model.leaves())
    # same results as the bundled example, and it re-saves as version 2
    current = project.load(EXAMPLES / name.replace("_v1", ""))
    assert model.evaluate().alternative_scores == pytest.approx(current.evaluate().alternative_scores)
    project.save(model, tmp_path / "new.json")
    assert json.loads((tmp_path / "new.json").read_text())["version"] == 2


def test_newer_format_is_rejected_clearly():
    with pytest.raises(ValueError, match="newer"):
        project.model_from_dict({"format": "ahp-anp-decisionmaker", "version": 99, "type": "ahp"})


def test_export_includes_scores(tmp_path):
    m, battery, _price, looks, (a, b, c) = model_with_leaves()
    m.set_scoring_mode(battery.id, "direct")
    m.scoring(battery.id).values = {a.id: 10, b.id: 5, c.id: 15}
    m.set_scoring_mode(looks.id, "ratings")
    m.scoring(looks.id).ratings = {x.id: m.scoring(looks.id).levels[0].id for x in (a, b, c)}
    tables = build_tables(m)
    assert len(tables.scores) == 1 + 2 * 3
    assert any(t.compared == "Rating levels" for t in tables.matrices)
    export_csv_zip(m, tmp_path / "x.zip")
    with zipfile.ZipFile(tmp_path / "x.zip") as z:
        assert "scores.csv" in z.namelist()
    project.export_csv(m, tmp_path / "summary.csv")
    assert "direct" in (tmp_path / "summary.csv").read_text()
