#!/bin/sh
# Stands in for `ssh` in ssh_tunnel_test.coil so the supervisor's failure paths can
# be exercised without a reachable SSH server. Every real ssh argument is ignored;
# behavior is chosen by SSH_TUNNEL_FIXTURE_MODE.
#
#   refuse  exit immediately with a diagnostic on stderr, the way ssh reports a
#           rejected key or an unusable forward
#   hang    stay alive without ever binding the forwarded port, the way a
#           connection that stalls after spawn would look
case "${SSH_TUNNEL_FIXTURE_MODE:-refuse}" in
  refuse)
    echo "fixture refused: Permission denied (publickey)." >&2
    exit 255
    ;;
  hang)
    sleep 30
    ;;
esac
