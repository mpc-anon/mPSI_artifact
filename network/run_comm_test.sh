#!/bin/bash
# =========================================================
# run_comm_test.sh
#
# Fully automated communication-cost test: sets up the network
# topology, runs the receiver/sender pair for each configured
# transfer size, tears down, and prints a summary table.
# No manual multi-terminal interaction required.
#
# Usage:
#   sudo ./run_comm_test.sh <delay_ms> <rate_mbit> <size1_mb> [size2_mb] ...
#
# Example (LAN config, testing 5MB/50MB/1000MB):
#   sudo ./run_comm_test.sh 0.01 10000 5 50 1000
#
# Example (WAN config, testing one size matching a real vector):
#   sudo ./run_comm_test.sh 48 200 2.5
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

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PIVOT_IP="10.10.0.2"
PORT=9000
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

    # start receiver in the background, capture its output
    RECV_LOG=$(mktemp)
    ip netns exec party1 python3 "$SCRIPT_DIR/receiver.py" \
        --host "$PIVOT_IP" --port "$PORT" > "$RECV_LOG" 2>&1 &
    RECV_PID=$!

    # give the receiver a moment to bind before the sender connects
    sleep 0.5

    SEND_LOG=$(mktemp)
    ip netns exec party2 python3 "$SCRIPT_DIR/sender.py" \
        --host "$PIVOT_IP" --port "$PORT" --size-mb "$SIZE" > "$SEND_LOG" 2>&1

    wait "$RECV_PID"

    SEND_TIME=$(grep "elapsed time" "$SEND_LOG" | awk '{print $5}')
    SEND_THROUGHPUT=$(grep "throughput" "$SEND_LOG" | awk '{print $4}')

    cat "$SEND_LOG"
    echo ""

    echo "${SIZE},${SEND_TIME},${SEND_THROUGHPUT}" >> "$RESULTS_FILE"

    rm -f "$RECV_LOG" "$SEND_LOG"
done

echo ""
echo "==== Summary ===="
printf "%-12s %-16s %-16s\n" "Size (MB)" "Time (s)" "Throughput (MB/s)"
while IFS=',' read -r size t thr; do
    printf "%-12s %-16s %-16s\n" "$size" "$t" "$thr"
done < "$RESULTS_FILE"
