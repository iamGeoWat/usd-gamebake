#!/usr/bin/env bash
# Apply the godot-usd patch series (patches/godot-usd/*.patch, in order) to the pinned submodule extern/godot-usd.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
SUB="$ROOT/extern/godot-usd"
[ -f "$SUB/SConstruct" ] || git -C "$ROOT" submodule update --init extern/godot-usd
for p in "$ROOT"/patches/godot-usd/*.patch; do
	if git -C "$SUB" apply --reverse --check "$p" 2>/dev/null; then
		echo "already applied: $(basename "$p")"
	else
		git -C "$SUB" apply "$p"
		echo "applied: $(basename "$p")"
	fi
done
