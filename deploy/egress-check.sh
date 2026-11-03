#!/usr/bin/env bash
# Acceptance test for the egress firewall. Run as root on the machine:
#   fly ssh console -C /app/deploy/egress-check.sh
# Root puts dummy addresses on lo with listeners it can prove it reaches, then checks
# that the app uid cannot. Exits non-zero on any unexpected or inconclusive result.
set -uo pipefail

APP_USER=pwuser
APP_UID=$(id -u "$APP_USER")
APP_GID=$(id -g "$APP_USER")
failures=0

BLOCKED_V4=(198.18.0.1 192.0.2.1 10.99.0.1)
BLOCKED_V6=(2001:db8::1 64:ff9b::1)
ALLOWED=100.0.0.1  # public-looking (outside 100.64/10), positive control

# probe tcp <host> <port> | https <url>: exit 0 connected, 1 OSError. Anything else is a probe error.
PROBE='
import socket, sys, urllib.request
try:
    if sys.argv[1] == "tcp":
        socket.create_connection((sys.argv[2], int(sys.argv[3])), timeout=5).close()
    elif urllib.request.urlopen(sys.argv[2], timeout=10).status != 200:
        sys.exit(1)
except OSError:
    sys.exit(1)
sys.exit(0)
'
as_app() { setpriv --reuid="$APP_UID" --regid="$APP_GID" --init-groups python3 -c "$PROBE" "$@" >/dev/null 2>&1; }
as_root() { python3 -c "$PROBE" "$@" >/dev/null 2>&1; }

pass() { echo "PASS $1"; }
fail() { echo "FAIL $1"; failures=$((failures + 1)); }

listener_pid=""
cleanup() {
  [ -n "$listener_pid" ] && kill "$listener_pid" 2>/dev/null
  for a in "${BLOCKED_V4[@]}" "$ALLOWED"; do ip addr del "$a/32" dev lo 2>/dev/null; done
  for a in "${BLOCKED_V6[@]}"; do ip addr del "$a/128" dev lo 2>/dev/null; done
}
trap cleanup EXIT

for a in "${BLOCKED_V4[@]}" "$ALLOWED"; do ip addr add "$a/32" dev lo; done
for a in "${BLOCKED_V6[@]}"; do ip addr add "$a/128" dev lo nodad; done

# Root listeners: no accept() needed, the kernel completes the handshake on a listening socket.
python3 - "${BLOCKED_V4[@]}" "${BLOCKED_V6[@]}" "$ALLOWED" <<'EOF' &
import socket, sys, time
socks = []
targets = [(a, 80) for a in sys.argv[1:]] + [(sys.argv[-1], 8080)]
for host, port in targets:
    s = socket.socket(socket.AF_INET6 if ":" in host else socket.AF_INET)
    s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    s.bind((host, port))
    s.listen(16)
    socks.append(s)
time.sleep(120)
EOF
listener_pid=$!
sleep 1

expect_blocked() {  # expect_blocked <host> <port>
  local label="$1:$2"
  as_root tcp "$1" "$2"; local root=$?
  if [ "$root" -ne 0 ]; then fail "inconclusive: root cannot reach $label (exit $root)"; return; fi
  as_app tcp "$1" "$2"; local app=$?
  case "$app" in
    1) pass "app uid blocked: $label (root reaches it)" ;;
    0) fail "app uid reached $label" ;;
    *) fail "probe error as app uid for $label (exit $app)" ;;
  esac
}

expect_reachable() {  # expect_reachable <probe args...>
  local label="${*:2}"
  as_app "$@"; local app=$?
  case "$app" in
    0) pass "app uid reachable: $label" ;;
    1) fail "app uid cannot reach $label" ;;
    *) fail "probe error as app uid for $label (exit $app)" ;;
  esac
}

if nft list chain inet a11y_egress output 2>/dev/null | grep -Eq "meta skuid (\"?$APP_USER\"?|$APP_UID) goto app_out"; then
  pass "output chain sends the app uid to app_out"
else
  fail "output chain missing the app uid goto app_out rule"
fi
if nft list chain inet a11y_egress app_out 2>/dev/null | grep -v '^\s*}' | grep -v '^\s*$' | tail -n 1 | grep -qx '\s*drop'; then
  pass "app_out ends in an explicit drop"
else
  fail "app_out missing or does not end in drop"
fi

for a in "${BLOCKED_V4[@]}" "${BLOCKED_V6[@]}"; do expect_blocked "$a" 80; done
expect_reachable tcp "$ALLOWED" 80        # allow rule works and the blocks are not blanket
expect_blocked "$ALLOWED" 8080            # port restriction (default drop)
expect_reachable https https://example.com/  # DNS + real public egress

if [ "$failures" -ne 0 ]; then echo "$failures unexpected result(s)"; exit 1; fi
echo "all egress checks as expected"
