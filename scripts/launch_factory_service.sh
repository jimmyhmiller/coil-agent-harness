#!/bin/sh
set -eu

runner=${HARNESS_FACTORY_RUNNER:-/usr/local/libexec/coil-agent-harness/run_factory_service.sh}
nohup "$runner" "$@" </dev/null >/dev/null 2>&1 &
