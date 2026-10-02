# AHP / ANP Decision Maker

A desktop program (Python + Qt) for multi-criteria decisions with Saaty's
**Analytic Hierarchy Process (AHP)** and **Analytic Network Process (ANP)**.
You enter the goal, criteria, alternatives and pairwise comparisons on the 1–9
scale in a GUI. The program returns priorities, consistency checks, supermatrices,
a ranking and a sensitivity analysis.

## Install and run

You need **Python 3.10 or newer** (`python3 --version`) and **git**. All other
dependencies (PySide6/Qt, numpy, matplotlib, openpyxl) come from PyPI into a
virtual environment, so you don't need system Qt packages or admin rights.

**Linux / macOS**

```sh
git clone https://github.com/arde1001/AHPDeciderANP.git
cd AHPDeciderANP
python3 -m venv .venv
.venv/bin/pip install -e '.[test]'
.venv/bin/decisionmaker                  # start the app
.venv/bin/decisionmaker project.json     # or open a saved project directly
```

**Windows** (PowerShell or cmd)

```bat
git clone https://github.com/arde1001/AHPDeciderANP.git
cd AHPDeciderANP
py -m venv .venv
.venv\Scripts\pip install -e ".[test]"
.venv\Scripts\decisionmaker
```

`python -m decisionmaker` also works from inside the activated environment.
To try it quickly, click one of the two **Example** buttons on the welcome screen
(an AHP laptop choice, an ANP car purchase), then look at the *Results* and
*Sensitivity* tabs.

**Optional, Linux:** add it to the application menu or launcher. This creates
the virtual environment first if it doesn't exist yet:

```sh
./install-desktop-entry.sh            # writes ~/.local/share/applications/decisionmaker.desktop
./install-desktop-entry.sh --remove   # uninstall
```

### Troubleshooting

- **`qt.qpa.plugin: Could not load the Qt platform plugin "xcb"`** (Linux,
  usually minimal X11 installs): install Qt's X11 runtime libraries.
  - Debian/Ubuntu: `sudo apt install libxcb-cursor0 libxkbcommon-x11-0 libegl1`
  - Fedora: `sudo dnf install xcb-util-cursor libxkbcommon-x11`
  - Arch: `sudo pacman -S xcb-util-cursor`

  On Wayland you can also try `QT_QPA_PLATFORM=wayland .venv/bin/decisionmaker`.
- **`pip` can't find a PySide6 version**: your Python is too old or too new for
  the published wheels. Use a Python version from python.org that PySide6
  supports (3.10–3.13 are safe choices).
- **Light/dark look:** the app follows the system's light or dark theme where
  Qt can detect it (Windows, macOS, GNOME/KDE). Elsewhere it starts light.

## Using it

The welcome screen offers a new AHP or ANP project, opening a saved one, or one
of two bundled examples (*File → Open example*).

**AHP** tabs:

1. **Model**: set the goal and build the criteria tree (criteria can nest to any
   depth) and the list of alternatives. Double-click or press F2 to rename.
2. **Scoring**: for each lowest-level criterion, choose how the alternatives
   are scored:
   - *Pairwise comparison* (the default, classic AHP).
   - *Direct values*: measured data on a ratio scale, such as hours or euros.
     Priorities are value / sum for benefit criteria (higher is better) and
     (1/value) / Σ(1/value) for cost criteria (lower is better).
   - *Ratings*: compare rating levels such as Excellent…Poor once, then give
     each alternative a level. Each level's weight is idealized (best = 1).
   Missing data is flagged, and that criterion counts its alternatives as equal
   until it's filled in.
3. **Comparisons**: one entry per node that has at least two things below it,
   plus the rating-level scales.
   For each pair, click the classic `9 … 2 1 2 … 9` row, or type `3` or `1/5`
   into the matrix. The priorities and CR update live. When CR > 0.10, the
   most inconsistent judgments are highlighted, each with a suggested value and
   an **Apply** button.
4. **Results**: ranking table and bar chart, local and global criteria weights,
   and the consistency of every matrix (double-click a row to open that
   matrix). Switch between *distributive* and *ideal* synthesis.
5. **Sensitivity**: pick any comparison and element, then sweep its weight from
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

*File* menu: save and open projects (`.json`), *Export* (below), and recent
files. *Help → Guide* explains the scale and the math.

## Exporting to other AHP/ANP software

The `.json` project format belongs to this app only. No other AHP/ANP program
shares a file format, so *File → Export → Model and matrices* writes the whole
model as plain tables. Spreadsheets, scripts and people re-entering the model
in other tools can all read it. It comes as one Excel workbook (`Ctrl+E`) or as
a zip of UTF-8 CSV files with the same content:

| Sheet / file | Contents | Use it for |
|---|---|---|
| About / `README.txt` | Scale and matrix conventions, import tips | Read first |
| Structure | Goal → criteria tree and alternatives (AHP), or clusters and nodes (ANP), with ids | Rebuilding the model |
| Connections (ANP) | 0/1 node matrix: row *i*, column *j* = 1 when *i* is compared w.r.t. *j* (SuperDecisions: node *j* connects to *i*) | Rebuilding the network links |
| Judgments | One row per pair: A, B, numeric a<sub>AB</sub>, `1/3` text, **Preferred** item + **Intensity 1–9**, verbal label, judged yes/no | Verbal or questionnaire entry (Expert Choice / Comparion, SpiceLogic…) |
| Comparisons | Index of all matrices with λmax, CI, RI, CR, and links to the sheets | Overview and cross-checking CR |
| `M01 …`, `M02 …` | Full reciprocal matrix per comparison, labels in the first row and column, priorities in the last column. Excel shows them as fractions but stores them as numbers | Matrix or numerical entry, R/Python (`pandas.read_csv(f, index_col=0)`) |
| Scores (AHP) | Direct values and ratings per alternative for criteria not scored pairwise | Data or ratings entry in the other tool |
| Results | Ranking (AHP: distributive **and** ideal), weights or limit priorities | Comparing with the other tool's output |
| Unweighted, cluster, weighted, limit supermatrix (ANP) | The four matrices | Cross-checking SuperDecisions |

These files are meant for reading and re-entry. They can't be imported straight
into those programs' own project files, because their formats are proprietary
or undocumented. A test re-enters a model from the Judgments table alone and
checks that it gives identical results. *Results summary (single CSV)* is the
short report from earlier versions.

## Method details

Project files carry a format version. Version-1 files from earlier releases
load unchanged (every criterion is scored pairwise). Saving writes version 2.

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
    project.py     # save/load JSON, results summary CSV
    exchange.py    # interchange export: Excel workbook / CSV zip
  gui/             # PySide6 widgets (main window, editors, charts)
  examples/        # laptop_ahp.json, car_anp.json
tests/             # core math + offscreen GUI smoke tests
```

Judgments are stored by item id, not by position. Renaming, reordering or
adding items keeps every judgment that still applies.

## Tests

```sh
.venv/bin/pytest            # Windows: .venv\Scripts\pytest
```

The GUI tests run headless (`QT_QPA_PLATFORM=offscreen`), so they need no
display and don't open any windows.

## License

MIT License. Copyright © 2026 arde1001. See [LICENSE](LICENSE).
