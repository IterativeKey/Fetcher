#!/usr/bin/env bash
# Egress auditor for the Fetcher stack.
#
# Verifies with your own eyes that the containers only connect to the servers
# you ask for (plus expected extra traffic: DNS, BT/DHT peers when torrenting).
#
# Modes:
#   netcheck.sh snap     (default) decode every open TCP connection of
#                        fetcher-aria2 and fetcher-api right now, from
#                        /proc/net/tcp - needs nothing but docker.
#   netcheck.sh [secs]   live-capture destinations on the compose bridge for
#                        <secs> seconds (default 60; needs sudo tcpdump). Run
#                        on the Linux host/NAS (Docker Desktop hides the bridge
#                        behind its VM).
#
# Internal/RFC1918 addresses are marked "internal" - those are
# container-to-container RPC or DNS, not external destinations.

set -euo pipefail

CONTAINERS=${CONTAINERS:-"fetcher-aria2 fetcher-egress fetcher-api"}

hex_ip() { printf '%d.%d.%d.%d' 0x${1:6:2} 0x${1:4:2} 0x${1:2:2} 0x${1:0:2}; }

classify() {
  local ip=$1 port=$2
  case $ip in
    10.*|127.*|192.168.*|172.1[6-9].*|172.2?.*|172.3[01].*) echo "internal  $ip:$port" ;;
    *)                                                     echo "WAN       $ip:$port" ;;
  esac
}

snap() {
  for c in $CONTAINERS; do
    echo "=== $c ==="
    # /proc/net/tcp: col2=local, col3=remote (hex, port); state col4: 01=ESTAB
    docker exec "$c" awk 'NR>1 && $4=="01" {print $3}' /proc/net/tcp 2>/dev/null \
    | while read -r remote; do
        # little-endIAN: aabbccdd means dd:cc:bb:aa
        iphex=${remote%%:*}
        porthex=${remote##*:}
        port=$((16#$porthex))
        ip=$(hex_ip "$iphex")
        classify "$ip" "$port"
      done | sort | uniq -c | sort -rn || true
  done
}

capture() {
  local secs=${1:-60} net idx candidate bridge tmp pid
  for candidate in frontnet fetcher_frontnet; do
    if docker network inspect "$candidate" >/dev/null 2>&1; then net=$candidate; break; fi
  done
  [ -n "${net:-}" ] || { echo "compose network not found; check: docker network ls" >&2; exit 1; }
  bridge=$(docker network inspect "$net" \
    --format '{{if .Options."com.docker.network.bridge.name"}}{{.Options."com.docker.network.bridge.name"}}{{else}}br-{{slice .Id 0 12}}{{end}}')

  echo "capturing $secs s on $bridge, summarizing destinations ..."
  tmp=$(mktemp)
  sudo tcpdump -i "$bridge" -n -q -l "tcp or udp" 2>/dev/null > "$tmp" &
  pid=$!
  sleep "$secs"
  sudo kill "$pid" 2>/dev/null || true
  wait "$pid" 2>/dev/null || true

  echo "=== destinations contacted (count dst ip:port) ==="
  # tcpdump -q format: 'IP <src.ip.port> > <dst.ip.port>: proto'
  grep -oE 'IP [0-9.]+\.[0-9]+ > [0-9.]+\.[0-9]+' "$tmp" | awk '{print $4}' \
    | awk -F. '{ ip=$1"."$2"."$3"."$4
                 if ($1==10 || $1==127 || ($1==192 && $2==168) \
                     || ($1==172 && $2>=16 && $2<=31)) cls="internal"
                 else cls="WAN"
                 print cls, ip"."$5 }' \
    | sort | uniq -c | sort -rn | sed 's/^/  /'
  rm -f "$tmp"
}

case ${1:-snap} in
  snap)    snap ;;
  help|-h) sed -n '2,11p' "$0" ;;
  *)       capture "$1" ;;
esac
