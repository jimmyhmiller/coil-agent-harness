#!/bin/sh
set -eu

project_dir=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
gatekeeper_dir=${GATEKEEPER_DIR:-"$project_dir/../gatekeeper"}
gatekeeper_bin="$gatekeeper_dir/target/debug/gatekeeper"
token=gatekeeper-harness-integration-token
port=18789

dylib=$($project_dir/scripts/build_gatekeeper_function.sh | tail -n 1)
cargo build --manifest-path "$gatekeeper_dir/Cargo.toml" -p gatekeeper

config=$(mktemp "$project_dir/build/gatekeeper-e2e.XXXXXX.toml")
journal=$(mktemp "$project_dir/build/gatekeeper-e2e.XXXXXX.jsonl")
log=$(mktemp "$project_dir/build/gatekeeper-e2e.XXXXXX.log")
unauthorized=$(mktemp "$project_dir/build/gatekeeper-e2e.XXXXXX.out")
describe=$(mktemp "$project_dir/build/gatekeeper-e2e.XXXXXX.describe.json")
tools=$(mktemp "$project_dir/build/gatekeeper-e2e.XXXXXX.tools.json")
created=$(mktemp "$project_dir/build/gatekeeper-e2e.XXXXXX.created.json")
events=$(mktemp "$project_dir/build/gatekeeper-e2e.XXXXXX.events.json")
stream=$(mktemp "$project_dir/build/gatekeeper-e2e.XXXXXX.stream.txt")
worker_result=$(mktemp "$project_dir/build/gatekeeper-e2e.XXXXXX.worker.json")
resumed=$(mktemp "$project_dir/build/gatekeeper-e2e.XXXXXX.resumed.txt")

cleanup() {
  if [ "${server_pid:-}" ]; then
    kill "$server_pid" 2>/dev/null || true
    wait "$server_pid" 2>/dev/null || true
  fi
  rm -f "$config" "$journal" "$log" "$unauthorized" "$describe" "$tools" "$created" "$events" "$stream" "$worker_result" "$resumed"
}
trap cleanup EXIT INT TERM

sed "s|@HARNESS_DYLIB@|$dylib|g" \
  "$project_dir/integration/gatekeeper-test.toml.in" > "$config"

GATEKEEPER_TOKEN=$token HARNESS_JOURNAL_PATH=$journal \
  "$gatekeeper_bin" --config "$config" > "$log" 2>&1 &
server_pid=$!

attempt=0
while ! curl -sS -o /dev/null "http://127.0.0.1:$port/agents/v1/tools" 2>/dev/null; do
  attempt=$((attempt + 1))
  if [ "$attempt" -ge 100 ]; then
    cat "$log" >&2
    exit 1
  fi
  sleep 0.05
done

status=$(curl -sS -o "$unauthorized" -w '%{http_code}' \
  "http://127.0.0.1:$port/agents/v1/tools")
[ "$status" = 401 ]

curl -fsS -H "Authorization: Bearer $token" \
  "http://127.0.0.1:$port/describe" > "$describe"
grep -q '"name": "coil-agent-harness"' "$describe"
grep -q '"lifecycle": "service"' "$describe"

curl -fsS -H "Authorization: Bearer $token" \
  "http://127.0.0.1:$port/agents/v1/tools" > "$tools"
grep -q '"name":"echo"' "$tools"

pids=""
request_number=0
while [ "$request_number" -lt 8 ]; do
  curl -fsS -H "Authorization: Bearer $token" \
    "http://127.0.0.1:$port/agents/v1/tools" > /dev/null &
  pids="$pids $!"
  request_number=$((request_number + 1))
done
for request_pid in $pids; do
  wait "$request_pid"
done

curl -fsS -H "Authorization: Bearer $token" \
  -H 'Content-Type: application/json' \
  --data '{"version":1,"command_id":"gk-e2e-create","run_id":"gk-e2e-run","provider":"openai","model":"gpt-5","prompt":"hello","execution_target":"worker"}' \
  "http://127.0.0.1:$port/agents/v1/runs" > "$created"
grep -q '"status":"queued"' "$created"

curl -fsS -H "Authorization: Bearer $token" \
  "http://127.0.0.1:$port/agents/v1/runs/gk-e2e-run/events?after=0" > "$events"
grep -q '"actor":"gatekeeper"' "$events"
grep -q '"next_cursor":' "$events"

# Keep one real HTTP response open, observe its first event, cause a later
# durable event from another request, and prove both arrive on the same SSE
# connection before it reaches EOF at the run's terminal state.
curl -fsSN -H "Authorization: Bearer $token" \
  "http://127.0.0.1:$port/agents/v1/runs/gk-e2e-run/events/stream?after=0" \
  > "$stream" &
stream_pid=$!
attempt=0
while ! grep -q 'run.created' "$stream" 2>/dev/null; do
  attempt=$((attempt + 1))
  if [ "$attempt" -ge 100 ]; then
    cat "$log" >&2
    exit 1
  fi
  sleep 0.05
done

curl -fsS -H "Authorization: Bearer $token" -H 'Content-Type: application/json' \
  --data '{"version":1,"worker_id":"gk-e2e-worker","capabilities":{"agent_process":true}}' \
  "http://127.0.0.1:$port/agents/v1/workers/register" > "$worker_result"
curl -fsS -H "Authorization: Bearer $token" -H 'Content-Type: application/json' \
  --data '{"version":1,"command_id":"gk-e2e-lease","worker_id":"gk-e2e-worker","lease_ms":30000}' \
  "http://127.0.0.1:$port/agents/v1/workers/claim" > "$worker_result"
curl -fsS -H "Authorization: Bearer $token" -H 'Content-Type: application/json' \
  --data '{"version":1,"command_id":"gk-e2e-progress","run_id":"gk-e2e-run","worker_id":"gk-e2e-worker","lease_id":"gk-e2e-lease","event":{"event":"model.response.delta","text":"streamed token"}}' \
  "http://127.0.0.1:$port/agents/v1/workers/progress" > "$worker_result"
curl -fsS -H "Authorization: Bearer $token" -H 'Content-Type: application/json' \
  --data '{"version":1,"run_id":"gk-e2e-run","worker_id":"gk-e2e-worker","lease_id":"gk-e2e-lease","outcome":"succeeded","output":"done"}' \
  "http://127.0.0.1:$port/agents/v1/workers/complete" > "$worker_result"
wait "$stream_pid"
grep -q '^id: ' "$stream"
grep -q 'model.response.delta' "$stream"
grep -q 'run.completed' "$stream"

last_event_id=$(awk '/^id: / { value=$2 } END { print value }' "$stream")
[ -n "$last_event_id" ]
curl -fsSN -H "Authorization: Bearer $token" \
  -H "Last-Event-ID: $last_event_id" \
  "http://127.0.0.1:$port/agents/v1/runs/gk-e2e-run/events/stream" > "$resumed"
[ ! -s "$resumed" ]

printf 'gatekeeper function integration: ok\n'
