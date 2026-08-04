#!/bin/bash
# =========================================================
# teardown_netns.sh
#
# Removes everything created by setup_netns.sh.
#
# Usage:
#   sudo ./teardown_netns.sh <num_parties>
# =========================================================

NUM_PARTIES=${1:-5}
BRIDGE=br0

for i in $(seq 1 "$NUM_PARTIES"); do
    ip netns del "party$i" 2>/dev/null || true
    ip link del "veth$i" 2>/dev/null || true
done

ip link del "$BRIDGE" 2>/dev/null || true

echo "Teardown complete."
ip netns list
