#!/usr/bin/env bash
# Acceptance test for the egress firewall. Run as root on the machine:
#   fly ssh console -C /app/deploy/egress-check.sh
# Probes run as the app uid. Exits non-zero on any unexpected result.
set -uo pipefail

APP_USER=pwuser
APP_UID=$(id -u "$APP_USER")
APP_GID=$(id -g "$APP_USER")
failures=0

# probe <tcp host port | https url>: exit 0 if reachable
PROBE='
import socket, sys, urllib.request
if sys.argv[1] == "tcp":
    socket.create_connection((sys.argv[2], int(sys.argv[3])), timeout=5).close()
else:
    assert urllib.request.urlopen(sys.argv[2], timeout=10).status == 200
'
as_app() { setpriv --reuid="$APP_UID" --regid="$APP_GID" --init-groups python3 -c "$PROBE" "$@" >/dev/null 2>&1; }
as_root() { python3 -c "$PROBE" "$@" >/dev/null 2>&1; }

report() {  # report <ok?> <label>
  if [ "$1" = 0 ]; then echo "PASS $2"; else echo "FAIL $2"; failures=$((failures + 1)); fi
}

expect_blocked() {  # expect_blocked <label> <probe args...>
  local label=$1; shift
  as_app "$@"; local app=$?
  as_root "$@" && ctl="reachable as root" || ctl="also unreachable as root, so this line proves less"
  report $(( app == 0 )) "app uid blocked: $label ($ctl)"
}

expect_reachable() {
  local label=$1; shift
  as_app "$@"; report $? "app uid reachable: $label"
}

nft list chain inet a11y_egress output >/dev/null 2>&1; report $? "nftables table inet a11y_egress loaded"

expect_blocked "http://169.254.169.254/ (metadata)" tcp 169.254.169.254 80
expect_blocked "http://[fdaa::3]:53 (Fly 6PN resolver over TCP)" tcp fdaa::3 53
if [ -n "${FLY_PRIVATE_IP:-}" ]; then
  expect_blocked "[$FLY_PRIVATE_IP]:8000 (own 6PN address)" tcp "$FLY_PRIVATE_IP" 8000
fi
expect_blocked "127.0.0.1:8000 (loopback Bureau port)" tcp 127.0.0.1 8000
expect_blocked "10.0.0.1:80 (RFC1918)" tcp 10.0.0.1 80
expect_reachable "https://example.com (needs DNS + public egress)" https https://example.com/

if [ "$failures" -ne 0 ]; then echo "$failures unexpected result(s)"; exit 1; fi
echo "all egress checks as expected"
