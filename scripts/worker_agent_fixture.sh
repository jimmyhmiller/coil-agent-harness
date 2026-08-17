#!/bin/sh
set -eu

prompt=${4:-}
if [ "$prompt" = "block until the worker is stopped" ]; then
  sleep 3
fi

echo '{"version":1,"event":"model.response.delta","payload":"fixture progress"}' >&2
echo 'fixture result'
