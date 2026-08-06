#!/bin/bash
# =========================================================
# run_comm_test.sh
#
# Fully automated communication-cost test: sets up the network
# topology, runs an iperf3 server/client pair for each configured
# transfer size, tears down, and prints a summary table.
# No manual multi-terminal interaction required.
#
# We use iperf3 (rather than a hand-rolled Python socket sender/
# receiver) because it is a widely-used, well-tuned benchmarking
# tool that gets substantially closer to the shaped link's
# theoretical bandwidth -- our own Python implementation left
# ~20-35% of the theoretical bandwidth on the table (TCP window/
# buffer tuning), whereas iperf3 was consistently within ~4-10% for
# the transfer sizes this artifact needs (tens of MB and up).
#
# IMPORTANT -- minimum transfer size: for very small transfers
# (we measured 5-10 MB on a 10 Gbps LAN), tc netem's token-bucket
# rate limiter has not yet been engaged by the time the transfer
# finishes, so the measured throughput can appear to EXCEED the
# configured rate (i.e. faster than "theoretical", not slower) --
# this reflects the local kernel buffer's burst capacity, not the
# shaped link's real sustained rate, and is not a bug in this
# script or in iperf3. Only trust these measurements for transfer
# sizes of at least a few tens of MB; do not use this script to
# validate the smallest Table VI entries (sub-MB to a few MB),
# which are too small for tc-based emulation to measure meaningfully.
#
# Usage:
#   sudo ./run_comm_test.sh <delay_ms> <rate_mbit> <size1_mb> [size2_mb] ...
#
# Example (LAN config, testing the paper's largest configuration):
#   sudo ./run_comm_test.sh 0.01 10000 1160
#
# Example (WAN config, same size):
#   sudo ./run_comm_test.sh 48 200 1160
# =========================================================

set -e

DELAY_MS=$1
RATE_MBIT=$2
shift 2
SIZES=("$@")

if [ -z "$DELAY_MS" ] || [ -z "$RATE_MBIT" ] || [ ${#SIZES[@]} -eq 0 ]; then
    echo "Usage: sudo ./run_comm_test.sh <delay_ms> <rate_mbit> <size_mb> [size_mb ...]"
    exit 1
fi

if ! command -v iperf3 >/dev/null 2>&1; then
    echo "iperf3 not found. Install it first, e.g.: sudo apt install -y iperf3"
    exit 1
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SERVER_IP="10.10.0.2"
PORT=5201
RESULTS_FILE=$(mktemp)

cleanup() {
    "$SCRIPT_DIR/teardown_netns.sh" 2 >/dev/null 2>&1 || true
    rm -f "$RESULTS_FILE"
}
trap cleanup EXIT

echo "==== Setting up network (delay=${DELAY_MS}ms, rate=${RATE_MBIT}mbit) ===="
"$SCRIPT_DIR/setup_netns.sh" 2 "$DELAY_MS" "$RATE_MBIT" >/dev/null

echo ""
for SIZE in "${SIZES[@]}"; do
    echo "---- Testing size = ${SIZE} MB ----"

    # bytes = size_mb * 1024 * 1024, rounded to the nearest integer
    BYTES=$(python3 -c "print(round(${SIZE} * 1024 * 1024))")

    ip netns exec party1 iperf3 -s -1 -p "$PORT" >/dev/null 2>&1 &
    SERVER_PID=$!

    # give the server a moment to bind before the client connects
    sleep 0.5

    JSON_LOG=$(mktemp)
    ip netns exec party2 iperf3 -c "$SERVER_IP" -p "$PORT" -n "$BYTES" -J > "$JSON_LOG" 2>&1

    wait "$SERVER_PID" 2>/dev/null || true

    read -r SEND_SECONDS SEND_BYTES SEND_BPS <<< "$(python3 -c "
import json
with open('$JSON_LOG') as f:
    d = json.load(f)
s = d['end']['sum_sent']
print(s['seconds'], s['bytes'], s['bits_per_second'])
")"

    SEND_MB=$(python3 -c "print(${SEND_BYTES} / 1024 / 1024)")
    SEND_THROUGHPUT_MBPS=$(python3 -c "print(${SEND_MB} / ${SEND_SECONDS})")

    echo "[iperf3] bytes sent      : ${SEND_BYTES} (requested ${BYTES})"
    echo "[iperf3] elapsed time    : ${SEND_SECONDS} s"
    echo "[iperf3] throughput      : ${SEND_THROUGHPUT_MBPS} MB/s (${SEND_BPS} bits/s)"
    echo ""

    echo "${SIZE},${SEND_SECONDS},${SEND_THROUGHPUT_MBPS}" >> "$RESULTS_FILE"

    rm -f "$JSON_LOG"
done

echo ""
echo "==== Summary ===="
printf "%-12s %-16s %-16s\n" "Size (MB)" "Time (s)" "Throughput (MB/s)"
while IFS=',' read -r size t thr; do
    printf "%-12s %-16s %-16s\n" "$size" "$t" "$thr"
done < "$RESULTS_FILE"
