#!/usr/bin/env bash
# Install a desktop launcher (app menu / rofi / launcher entry) for this checkout.
# Usage: ./install-desktop-entry.sh            install or update
#        ./install-desktop-entry.sh --remove   uninstall
set -euo pipefail

here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
apps="${XDG_DATA_HOME:-$HOME/.local/share}/applications"
icons="${XDG_DATA_HOME:-$HOME/.local/share}/icons/hicolor/scalable/apps"
desktop="$apps/decisionmaker.desktop"
icon="$icons/decisionmaker.svg"

if [[ "${1:-}" == "--remove" ]]; then
    rm -f "$desktop" "$icon"
    update-desktop-database -q "$apps" 2>/dev/null || true
    echo "Removed $desktop"
    exit 0
fi

bin="$here/.venv/bin/decisionmaker"
if [[ ! -x "$bin" ]]; then
    echo "Creating the virtualenv in $here/.venv ..."
    python -m venv "$here/.venv"
    "$here/.venv/bin/pip" install -q -e "$here"
fi

mkdir -p "$apps" "$icons"
install -m 644 "$here/decisionmaker/gui/icon.svg" "$icon"
cat > "$desktop" <<EOF
[Desktop Entry]
Type=Application
Name=AHP / ANP Decision Maker
GenericName=Multi-criteria decision analysis
Comment=Rank alternatives with pairwise comparisons (Analytic Hierarchy / Network Process)
Exec=$bin %f
Icon=decisionmaker
Terminal=false
Categories=Office;
Keywords=AHP;ANP;decision;MCDA;pairwise;criteria;Saaty;
StartupWMClass=decisionmaker
EOF
update-desktop-database -q "$apps" 2>/dev/null || true
echo "Installed $desktop"
