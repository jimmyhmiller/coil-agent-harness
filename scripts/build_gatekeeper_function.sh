#!/bin/sh
set -eu

project_dir=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
case "$(uname -s)" in
  Darwin) extension=dylib ;;
  MINGW*|MSYS*|CYGWIN*) extension=dll ;;
  *) extension=so ;;
esac

output="$project_dir/build/libcoil_agent_harness.$extension"
mkdir -p "$project_dir/build"
coil build "$project_dir/src/gatekeeper_function.coil" --shared -o "$output"
printf '%s\n' "$output"
