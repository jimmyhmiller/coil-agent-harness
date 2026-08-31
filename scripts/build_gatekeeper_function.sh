#!/bin/sh
set -eu

project_dir=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
curl_link=
case "$(uname -s)" in
  Darwin)
    extension=dylib
    curl_link=
    ;;
  MINGW*|MSYS*|CYGWIN*) extension=dll ;;
  *)
    extension=so
    # Coil's bundled Linux curl archives are intended for executables and are
    # not PIC. A shared function must use the platform's shared libcurl.
    curl_link=-lcurl
    ;;
esac

output="$project_dir/build/libcoil_agent_harness.$extension"
mkdir -p "$project_dir/build"
(cd "$project_dir" && coil build src/gatekeeper_function.coil --shared $curl_link -o "$output")
printf '%s\n' "$output"
