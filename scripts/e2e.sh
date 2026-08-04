#!/bin/sh
set -eu

live_codex=0
if [ "${1:-}" = "--live-codex" ]; then
  live_codex=1
elif [ "$#" -ne 0 ]; then
  echo "usage: sh scripts/e2e.sh [--live-codex]" >&2
  exit 64
fi

work_dir=$(mktemp -d "${TMPDIR:-/tmp}/coil-harness-e2e.XXXXXX")
server_pid=""
port=$((39000 + ($$ % 1000)))
token="coil-harness-e2e-token"
journal="$work_dir/events.jsonl"
base_url="http://127.0.0.1:$port"

cleanup() {
  if [ -n "$server_pid" ] && kill -0 "$server_pid" 2>/dev/null; then
    kill -TERM "$server_pid" 2>/dev/null || true
    wait "$server_pid" 2>/dev/null || true
  fi
  rm -rf "$work_dir"
}
trap cleanup EXIT INT TERM

fail() {
  echo "e2e: $*" >&2
  exit 1
}

assert_contains() {
  file=$1
  text=$2
  grep -F "$text" "$file" >/dev/null || fail "$file did not contain: $text"
}

request() {
  method=$1
  path=$2
  body=$3
  expected=$4
  output=$5
  if [ -n "$body" ]; then
    actual=$(curl -sS -o "$output" -w '%{http_code}' \
      -X "$method" \
      -H "Authorization: Bearer $token" \
      -H 'Content-Type: application/json' \
      --data "$body" \
      "$base_url$path")
  else
    actual=$(curl -sS -o "$output" -w '%{http_code}' \
      -X "$method" \
      -H "Authorization: Bearer $token" \
      "$base_url$path")
  fi
  [ "$actual" = "$expected" ] || fail "$method $path returned $actual, expected $expected: $(tr '\n' ' ' < "$output")"
}

start_server() {
  HARNESS_AUTH_TOKEN=$token ./harness serve "$port" "$journal" \
    >"$work_dir/server.out" 2>"$work_dir/server.err" &
  server_pid=$!
  attempt=0
  while [ "$attempt" -lt 50 ]; do
    if curl -sS -o /dev/null "$base_url/v1/runs/not-ready" 2>/dev/null; then
      return
    fi
    if ! kill -0 "$server_pid" 2>/dev/null; then
      fail "server exited during startup: $(tr '\n' ' ' < "$work_dir/server.err")"
    fi
    attempt=$((attempt + 1))
    sleep 0.1
  done
  fail "server did not become ready"
}

stop_server() {
  kill -TERM "$server_pid"
  wait "$server_pid" || fail "server did not shut down successfully"
  server_pid=""
}

wait_for_status() {
  run_id=$1
  wanted=$2
  output=$3
  attempt=0
  while [ "$attempt" -lt 200 ]; do
    request GET "/v1/runs/$run_id" "" 200 "$output"
    if grep -F "\"status\":\"$wanted\"" "$output" >/dev/null; then
      return
    fi
    attempt=$((attempt + 1))
    sleep 0.1
  done
  fail "run $run_id did not reach $wanted: $(tr '\n' ' ' < "$output")"
}

echo "e2e: verifying deterministic suites"
coil verify
sh scripts/check_file_size.sh
coil build -O1

echo "e2e: exercising authenticated HTTP, idempotency, failure, events, and recovery"
start_server

echo "e2e: rejecting a second process for the owned journal"
contender_port=$((port + 1000))
if HARNESS_AUTH_TOKEN=$token ./harness serve "$contender_port" "$journal" \
  >"$work_dir/contender.out" 2>"$work_dir/contender.err"; then
  fail "second harness process acquired an already-owned journal"
fi
assert_contains "$work_dir/contender.err" 'event journal is already owned by another harness process'

unauthorized_status=$(curl -sS -o "$work_dir/unauthorized.json" -w '%{http_code}' \
  "$base_url/v1/runs/missing")
[ "$unauthorized_status" = 401 ] || fail "unauthorized request returned $unauthorized_status"

request POST /v1/runs '{' 400 "$work_dir/invalid.json"
assert_contains "$work_dir/invalid.json" '"error":"invalid_json"'

missing_body='{"version":1,"command_id":"e2e-create-missing","run_id":"e2e-missing","provider":"not-a-provider","model":"none","prompt":"must fail without a model call"}'
request POST /v1/runs "$missing_body" 202 "$work_dir/create-missing.json"
request POST /v1/runs "$missing_body" 200 "$work_dir/replay-missing.json"
wait_for_status e2e-missing failed "$work_dir/missing-state.json"
request GET '/v1/runs/e2e-missing/events?after=0' "" 200 "$work_dir/missing-events.json"
assert_contains "$work_dir/missing-events.json" '"event":"run.created"'
assert_contains "$work_dir/missing-events.json" '"event":"run.failed"'

stop_server
start_server
wait_for_status e2e-missing failed "$work_dir/recovered-state.json"

if [ "$live_codex" -eq 1 ]; then
  echo "e2e: exercising live Codex app-server with gpt-5.6-luna"
  ./harness run codex gpt-5.6-luna 'Reply with exactly OK.' \
    >"$work_dir/codex-cli.out" 2>"$work_dir/codex-cli.events"
  assert_contains "$work_dir/codex-cli.out" 'OK'
  assert_contains "$work_dir/codex-cli.events" '"event":"run.completed"'

  codex_body='{"version":1,"command_id":"e2e-create-codex","run_id":"e2e-codex","provider":"codex","model":"gpt-5.6-luna","prompt":"Reply with exactly OK."}'
  request POST /v1/runs "$codex_body" 202 "$work_dir/create-codex.json"
  wait_for_status e2e-codex succeeded "$work_dir/codex-state.json"
  request GET '/v1/runs/e2e-codex/events?after=0' "" 200 "$work_dir/codex-events.json"
  assert_contains "$work_dir/codex-events.json" '"event":"model.response.delta"'
  assert_contains "$work_dir/codex-events.json" '"payload":"OK"'
  assert_contains "$work_dir/codex-events.json" '"event":"run.completed"'
fi

stop_server
echo "e2e: passed"
