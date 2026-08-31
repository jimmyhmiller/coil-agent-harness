#!/bin/sh
set -eu

project_dir=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
case "$(uname -s)" in
  Darwin) extension=dylib ;;
  *) extension=so ;;
esac

plugin="$project_dir/build/libharness_coil_tool_fixture.$extension"
mkdir -p "$project_dir/build"
coil build "$project_dir/integration/coil_tool_plugin_fixture.coil" \
  --shared \
  -o "$plugin"

HARNESS_C_TOOL_PLUGIN="$plugin" \
  coil run "$project_dir/integration/c_tool_plugin_integration.coil"
