#!/usr/bin/env bash
# Build the patched godot-usd GDExtension and install it into the tools project (godot/project/bin).
#
#   USD_SDK_PATH   an OpenUSD install prefix (include/ + lib/; see README for the build_usd.py line)       [required]
#   GODOT          the Godot editor you will bake with (its API is dumped so the extension matches it)     [required]
#   PRECISION      single | double -- must match that editor (default: single)
#   TARGET         template_debug (default) -- editor import plugins load the debug build
#   GODOT_CPP_PATH a godot-cpp checkout (default: extern/godot-cpp, cloned on first use)
#   TBB_SDK_PATH   oneTBB prefix (default: USD_SDK_PATH, where build_usd.py installs it)
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
: "${USD_SDK_PATH:?set USD_SDK_PATH to your OpenUSD install prefix}"
: "${GODOT:?set GODOT to your Godot editor binary}"
PRECISION="${PRECISION:-single}"
TARGET="${TARGET:-template_debug}"
GODOT_CPP_PATH="${GODOT_CPP_PATH:-$ROOT/extern/godot-cpp}"
TBB_SDK_PATH="${TBB_SDK_PATH:-$USD_SDK_PATH}"
case "$(uname -s)" in Darwin) PLATFORM=macos ;; Linux) PLATFORM=linux ;; *) PLATFORM=windows ;; esac
ARCH="${ARCH:-$(uname -m | sed 's/aarch64/arm64/')}"
[ -d "$GODOT_CPP_PATH" ] || git clone --depth 1 https://github.com/godotengine/godot-cpp "$GODOT_CPP_PATH"
"$ROOT/scripts/apply_patches.sh"
mkdir -p "$ROOT/build/api"
(cd "$ROOT/build/api" && "$GODOT" --headless --dump-extension-api --dump-gdextension-interface >/dev/null 2>&1)
EXTRA=()
[ "$PRECISION" = double ] && EXTRA+=(precision=double)
(cd "$ROOT/extern/godot-usd" && GODOT_CPP_PATH="$GODOT_CPP_PATH" USD_SDK_PATH="$USD_SDK_PATH" TBB_SDK_PATH="$TBB_SDK_PATH" \
	scons platform="$PLATFORM" arch="$ARCH" target="$TARGET" custom_api_file="$ROOT/build/api/extension_api.json" "${EXTRA[@]}" -j"$(getconf _NPROCESSORS_ONLN)")
mkdir -p "$ROOT/godot/project/bin"
cp "$ROOT"/extern/godot-usd/project/bin/libgodot_usd.* "$ROOT/godot/project/bin/"
echo "installed: $(ls "$ROOT/godot/project/bin" | grep libgodot_usd | tr '\n' ' ')"
