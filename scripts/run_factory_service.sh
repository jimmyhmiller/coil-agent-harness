#!/bin/sh
set -eu

request_id=$1
workflow=$2
project=$3
provider=${4:-codex}
model=${5:-gpt-5.6-luna}
state_root=${HARNESS_FACTORY_STATE_ROOT:-/var/lib/gatekeeper/harness-factory}
harness_bin=${HARNESS_BIN:-/usr/local/bin/coil-agent-harness}
request_root="$state_root/requests"
status_file="$request_root/$request_id.json"
status_new="$status_file.new"
log_file="$request_root/$request_id.log"

mkdir -p "$request_root"
printf '{"version":1,"request_id":"%s","workflow":"%s","project":"%s","status":"running","log":"%s"}\n' \
  "$request_id" "$workflow" "$project" "$log_file" > "$status_new"
mv "$status_new" "$status_file"

set +e
(
  cd "$state_root"
  "$harness_bin" factory run "$HARNESS_WORKFLOW_ROOT/$workflow" \
    --project "$project" --provider "$provider" --model "$model"
) > "$log_file" 2>&1
exit_code=$?
set -e

if [ "$exit_code" -eq 0 ]; then
  status=completed
else
  status=failed
fi
printf '{"version":1,"request_id":"%s","workflow":"%s","project":"%s","status":"%s","exit_code":%s,"log":"%s"}\n' \
  "$request_id" "$workflow" "$project" "$status" "$exit_code" "$log_file" > "$status_new"
mv "$status_new" "$status_file"
