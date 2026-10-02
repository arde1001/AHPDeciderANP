# AHP / ANP Decision Maker

A desktop program (Python + Qt) for multi-criteria decisions with Saaty's
**Analytic Hierarchy Process (AHP)** and **Analytic Network Process (ANP)**.
You enter the goal, criteria, alternatives and pairwise comparisons on the 1–9
scale in a GUI. The program returns priorities, consistency checks, supermatrices,
a ranking and a sensitivity analysis.

## Install and run

```sh
cd ~/Projects/ahp_anp_decisionmaker
python -m venv .venv
.venv/bin/pip install -e '.[test]'
.venv/bin/decisionmaker                 # or: .venv/bin/python -m decisionmaker
.venv/bin/decisionmaker project.json    # open a saved project directly
```

Requires Python ≥ 3.10, PySide6, numpy and matplotlib. They're installed from
PyPI, so no system Qt/Tk packages are needed.

To add it to the application menu / launcher (creates the venv first if it
doesn't exist):

```sh
./install-desktop-entry.sh            # writes ~/.local/share/applications/decisionmaker.desktop
./install-desktop-entry.sh --remove   # uninstall
```

## Using it

The welcome screen offers a new AHP or ANP project, opening a saved one, or one
of two bundled examples (*File → Open example*).

**AHP** tabs:

1. **Model**: set the goal and build the criteria tree (criteria can nest to any
   depth) and the list of alternatives. Double-click or press F2 to rename.
2. **Comparisons**: one entry per node that has at least two things below it.
   For each pair, click the classic `9 … 2 1 2 … 9` row, or type `3` or `1/5`
   into the matrix. The priorities and CR update live. When CR > 0.10, the
   most inconsistent judgments are highlighted, each with a suggested value and
   an **Apply** button.
3. **Results**: ranking table and bar chart, local and global criteria weights,
   and the consistency of every matrix (double-click a row to open that
   matrix). Switch between *distributive* and *ideal* synthesis.
4. **Sensitivity**: pick any comparison and element, then sweep its weight from
   0 to 1 (its siblings keep their ratios). The chart shows every alternative's
   score. The points where the best alternative changes are marked and listed.
   Click or drag on the chart to probe a weight.

**ANP** tabs:

1. **Network**: clusters and their nodes, the *alternatives cluster*, and the
   *start (goal) node*. The *Start from template* button creates
   Goal → Criteria ⇄ Alternatives with feedback links.
2. **Connections**: a grid of checkboxes. Row *i*, column *j* ticked means
   "compare *i* with respect to *j*", which is exactly the supermatrix cell it
   fills. There are bulk *Link all* / *Unlink all* buttons for cluster → cluster.
3. **Comparisons**: node comparisons (the nodes of cluster C that a node links
   to) and cluster comparisons (the clusters a cluster links to).
4. **Supermatrices**: unweighted, cluster weights, weighted and limit.
5. **Results**: ranking, the limit priority of every node (raw and normalized
   per cluster), consistency, and warnings.
6. **Sensitivity**: works like AHP, for any node or cluster comparison.

*File* menu: save and open projects (`.json`), *Export results as CSV*
(ranking, weights or limit priorities, and a consistency table), and recent
files. *Help → Guide* explains the scale and the math.

## Method details

- **Priorities**: the normalized principal right eigenvector of the reciprocal
  matrix. Pairs that haven't been judged count as 1 (equal) and are flagged as
  incomplete.
- **Consistency**: CI = (λmax − n)/(n − 1) and CR = CI/RI, using Saaty's RI for
  n ≤ 15 and the Alonso–Lamata fit above that. CR ≤ 0.10 counts as acceptable.
  Hints rank judgments by |ln(aᵢⱼ·wⱼ/wᵢ)|, and each suggestion is wᵢ/wⱼ snapped
  to the scale.
- **AHP synthesis**: an alternative's score is Σ over leaf criteria of
  global weight × local priority. *Ideal* mode divides each leaf's priorities
  by their maximum, then renormalizes.
- **ANP**: the weighted supermatrix is the unweighted blocks × cluster weights,
  with columns renormalized. Nodes that link to nothing (sinks) get a 1 on the
  diagonal, as in Saaty's hierarchy formulation. The limit is found by repeated
  squaring. If the powers cycle, the Cesàro average over one cycle is used.
  Results are `limit @ start`, where start is the goal node (auto-detected as
  the only node nothing links into) or uniform. A plain hierarchy entered as a
  network reproduces the AHP result exactly, and a test checks this.
- **Sensitivity**: the local priority vector of one comparison is replaced
  through `evaluate(overrides=…)`. The judgments themselves are never modified.

## Project layout

```
decisionmaker/
  core/            # no GUI dependencies
    pairwise.py    # scale, eigenvector, CR, hints, id-keyed Comparison
    ahp.py         # AHPModel: criteria tree, synthesis, JSON
    anp.py         # ANPModel: clusters, links, supermatrices, limit matrix
    sensitivity.py # one-at-a-time weight sweep and rank-reversal points
    project.py     # save/load JSON, CSV export
  gui/             # PySide6 widgets (main window, editors, charts)
  examples/        # laptop_ahp.json, car_anp.json
tests/             # core math + offscreen GUI smoke tests
```

Judgments are stored by item id, not by position. Renaming, reordering or
adding items keeps every judgment that still applies.

## Tests

```sh
.venv/bin/pytest            # the GUI tests run with QT_QPA_PLATFORM=offscreen
```
