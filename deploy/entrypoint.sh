#!/usr/bin/env bash
# Runs as root. Loads a fail-closed egress firewall for the app uid, then drops to it.
# DNS rebinding defence: even if a hostname passes the in-app SSRF guard and then
# re-resolves to a private address, the kernel drops the connection.
set -euo pipefail

APP_USER=pwuser
APP_UID=$(id -u "$APP_USER")
APP_GID=$(id -g "$APP_USER")

# Allow UDP 53 only to the resolvers in /etc/resolv.conf. TCP 53 stays blocked, so the
# resolver cannot be used as a generic TCP target (egress-check probes [fdaa::3]:53 over TCP).
dns_rules=""
for ns in $(awk '$1 == "nameserver" {print $2}' /etc/resolv.conf); do
  case "$ns" in
    *:*) dns_rules+="    meta skuid $APP_UID ip6 daddr $ns udp dport 53 accept"$'\n' ;;
    *)   dns_rules+="    meta skuid $APP_UID ip daddr $ns udp dport 53 accept"$'\n' ;;
  esac
done
if [ -z "$dns_rules" ]; then
  echo "entrypoint: no nameserver in /etc/resolv.conf, refusing to start" >&2
  exit 1
fi

# Loopback is blocked entirely: Bureau agents dispatch to each other in-process
# (uagents dispatcher), and Playwright talks to Chromium over a pipe, not localhost.
# "established,related" lets the app answer inbound connections (e.g. fly proxy to the
# Bureau port); an outbound connection to a blocked range never gets established.
nft -f - <<EOF
table inet a11y_egress
delete table inet a11y_egress
table inet a11y_egress {
  chain output {
    type filter hook output priority 0; policy accept;
    meta skuid != $APP_UID accept
    ct state established,related accept
$dns_rules
    ip daddr { 10.0.0.0/8, 172.16.0.0/12, 192.168.0.0/16, 100.64.0.0/10, 127.0.0.0/8, 169.254.0.0/16, 0.0.0.0/8 } drop
    ip6 daddr { fc00::/7, fe80::/10, ::1/128, ::ffff:0:0/96 } drop
  }
}
EOF

# Fail closed: refuse to start unless the table is really there.
nft list chain inet a11y_egress output >/dev/null

cd /app
export HOME="/home/$APP_USER"
exec setpriv --reuid="$APP_UID" --regid="$APP_GID" --init-groups --inh-caps=-all \
  python3 -m agents.lead
