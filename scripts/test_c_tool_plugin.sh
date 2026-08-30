#!/bin/sh
set -eu

project_dir=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
temporary_dir=$(mktemp -d)
trap 'rm -rf "$temporary_dir"' EXIT HUP INT TERM

case "$(uname -s)" in
  Darwin)
    extension=dylib
    shared_flag=-dynamiclib
    ;;
  *)
    extension=so
    shared_flag=-shared
    ;;
esac

plugin="$temporary_dir/libharness_c_tool_fixture.$extension"
cc "$shared_flag" -fPIC -std=c11 -Wall -Wextra -Werror \
  -I "$project_dir/include" \
  "$project_dir/integration/c_tool_plugin_fixture.c" \
  -o "$plugin"

HARNESS_C_TOOL_PLUGIN="$plugin" \
  coil run "$project_dir/integration/c_tool_plugin_integration.coil"
