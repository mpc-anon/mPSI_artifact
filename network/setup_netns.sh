#!/bin/bash
# =========================================================
# setup_netns.sh
#
# Creates NUM_PARTIES isolated network namespaces (party1..partyN),
# connects each to a shared bridge (br0) in the root namespace via a
# veth pair, and applies a tc netem delay/rate limit on each party's
# host-side veth interface (so each party's link can have an
# independent simulated network condition).
#
# Usage:
#   sudo ./setup_netns.sh <num_parties> [delay_ms] [rate_mbit]
#
# Example (10 parties, 20ms delay, 100mbit each link):
#   sudo ./setup_netns.sh 10 20 100
# =========================================================

set -e

NUM_PARTIES=${1:-5}
DELAY_MS=${2:-20}
RATE_MBIT=${3:-100}

BRIDGE=br0
SUBNET_PREFIX="10.10.0"

echo "Setting up $NUM_PARTIES parties, delay=${DELAY_MS}ms, rate=${RATE_MBIT}mbit"

# ---- clean up any previous run first ----
ip link del "$BRIDGE" 2>/dev/null || true
for i in $(seq 1 "$NUM_PARTIES"); do
    ip netns del "party$i" 2>/dev/null || true
    ip link del "veth$i" 2>/dev/null || true
done

# ---- create bridge ----
ip link add name "$BRIDGE" type bridge
ip link set "$BRIDGE" up

for i in $(seq 1 "$NUM_PARTIES"); do
    ns="party$i"
    veth_host="veth$i"          # stays in root namespace, attached to bridge
    veth_ns="veth${i}p"         # moved into the party's namespace
    ip_addr="${SUBNET_PREFIX}.$((i + 1))/24"

    # create namespace
    ip netns add "$ns"

    # create veth pair
    ip link add "$veth_host" type veth peer name "$veth_ns"

    # attach host-side end to the bridge
    ip link set "$veth_host" master "$BRIDGE"
    ip link set "$veth_host" up

    # move the other end into the party's namespace
    ip link set "$veth_ns" netns "$ns"
    ip netns exec "$ns" ip link set "$veth_ns" name eth0
    ip netns exec "$ns" ip addr add "$ip_addr" dev eth0
    ip netns exec "$ns" ip link set eth0 up
    ip netns exec "$ns" ip link set lo up

    # apply tc netem on the HOST-side veth end: this shapes traffic
    # leaving/entering this party's link, independent of other parties
    tc qdisc add dev "$veth_host" root netem delay "${DELAY_MS}ms" rate "${RATE_MBIT}mbit"

    echo "  party$i -> $ip_addr  (veth: $veth_host <-> eth0 in netns $ns)"
done

echo ""
echo "Done. Namespaces:"
ip netns list

echo ""
echo "Example: run a command inside party1's namespace:"
echo "  sudo ip netns exec party1 python3 your_script.py"
