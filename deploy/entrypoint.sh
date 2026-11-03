#!/usr/bin/env bash
# Runs as root. Loads a fail-closed egress firewall for the app uid, then drops to it.
# DNS rebinding defence: even if a hostname passes the in-app SSRF guard and then
# re-resolves to a private address, the kernel drops the connection.
set -euo pipefail

APP_USER=pwuser
APP_UID=$(id -u "$APP_USER")
APP_GID=$(id -g "$APP_USER")

# Allow UDP 53 only to the resolvers in /etc/resolv.conf. TCP 53 stays blocked, so the
# resolver cannot be used as a generic TCP target.
dns_rules=""
for ns in $(awk '$1 == "nameserver" {print $2}' /etc/resolv.conf); do
  case "$ns" in
    *:*) dns_rules+="    ip6 daddr $ns udp dport 53 accept"$'\n' ;;
    *)   dns_rules+="    ip daddr $ns udp dport 53 accept"$'\n' ;;
  esac
done
if [ -z "$dns_rules" ]; then
  echo "entrypoint: no nameserver in /etc/resolv.conf, refusing to start" >&2
  exit 1
fi

# Default drop for the app uid only (chain app_out). The base chain stays policy accept so
# socketless kernel packets (SYN-ACKs from request sockets, RSTs) used by fly ssh/proxy
# are never caught. The app uid may only resolve DNS and open TCP 80/443 to public
# addresses. Every dependency host in the installed packages uses 443: agentverse.ai
# (mailbox, Almanac API), grpc-dorado.fetch.ai and grpc-fetchhub.fetch.ai (cosmpy
# grpc+https, default port 443). No other port is needed.
# Loopback is blocked entirely: Bureau agents dispatch to each other in-process
# (uagents dispatcher), and Playwright talks to Chromium over a pipe, not localhost.
# "established,related" lets the app answer inbound connections (e.g. fly proxy to the
# Bureau port); an outbound connection to a blocked range never gets established.
# The DNS accepts stay above the drops: Fly's resolver fdaa::3 sits inside fc00::/7.
# ponytail: Teredo 2001::/32 and 6to4 relay 192.88.99.0/24 are left to the 80/443 restriction.
nft -f - <<EOF
table inet a11y_egress
delete table inet a11y_egress
table inet a11y_egress {
  chain output {
    type filter hook output priority 0; policy accept;
    meta skuid $APP_UID goto app_out
  }
  chain app_out {
    ct state established,related accept
$dns_rules
    ip daddr { 0.0.0.0/8, 10.0.0.0/8, 100.64.0.0/10, 127.0.0.0/8, 169.254.0.0/16, 172.16.0.0/12, 192.0.0.0/24, 192.0.2.0/24, 192.168.0.0/16, 198.18.0.0/15, 198.51.100.0/24, 203.0.113.0/24, 224.0.0.0/4, 240.0.0.0/4, 255.255.255.255/32 } drop
    ip6 daddr { ::/128, ::1/128, ::ffff:0:0/96, 64:ff9b::/96, 64:ff9b:1::/48, 100::/64, 2001:db8::/32, 2002::/16, fc00::/7, fe80::/10, ff00::/8 } drop
    tcp dport { 80, 443 } accept
    drop
  }
}
EOF

# Fail closed: refuse to start unless the app uid is routed into app_out and app_out ends in drop.
# (nft may print the uid as a name, so accept either form.)
nft list chain inet a11y_egress output | grep -Eq "meta skuid (\"?$APP_USER\"?|$APP_UID) goto app_out"
nft list chain inet a11y_egress app_out | grep -v '^\s*}' | grep -v '^\s*$' | tail -n 1 | grep -qx '\s*drop'

cd /app
export HOME="/home/$APP_USER"
exec setpriv --reuid="$APP_UID" --regid="$APP_GID" --init-groups --inh-caps=-all \
  python3 -m agents.lead
