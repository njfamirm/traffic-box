#!/usr/bin/env bash
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BIN_DIR="$HOME/.local/bin"
mkdir -p "$BIN_DIR"

echo "=== Installing Traffic-Box ==="

# Symlink CLI wrapper
cat << WRAPPER > "$BIN_DIR/traffic-box"
#!/usr/bin/env bash
export PYTHONPATH="$REPO_DIR/src:\${PYTHONPATH:-}"
exec python3 -m traffic_box.cli "\$@"
WRAPPER
chmod +x "$BIN_DIR/traffic-box"

# Symlink GUI wrapper
cat << WRAPPER > "$BIN_DIR/traffic-box-gui"
#!/usr/bin/env bash
export PYTHONPATH="$REPO_DIR/src:\${PYTHONPATH:-}"
exec python3 -m traffic_box.gui "\$@"
WRAPPER
chmod +x "$BIN_DIR/traffic-box-gui"

# Update dotfiles singbox-gui to use traffic-box or point directly
if [ -d "$HOME/dotfiles/bin" ]; then
    ln -sf "$BIN_DIR/traffic-box-gui" "$HOME/dotfiles/bin/singbox-gui"
fi

echo "Created symlinks in $BIN_DIR"
echo "Populating initial profiles..."
"$BIN_DIR/traffic-box" sub

echo "=== Traffic-Box Setup Complete ==="
