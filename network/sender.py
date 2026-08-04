"""
sender.py

Two-party communication cost test: the sending side.
Sends a total of `--size-mb` megabytes of data to the receiver in one
TCP connection, and reports elapsed time.

Usage:
  sudo ip netns exec party2 python3 sender.py --host 10.10.0.2 --port 9000 --size-mb 5
"""

import argparse
import socket
import time


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", required=True)
    parser.add_argument("--port", type=int, default=9000)
    parser.add_argument("--size-mb", type=float, required=True,
                         help="total amount of data to send, in MB")
    args = parser.parse_args()

    total_bytes = int(args.size_mb * 1024 * 1024)
    chunk = b"\x00" * (1024 * 1024)  # 1 MB reusable buffer
    full_chunks, remainder = divmod(total_bytes, len(chunk))

    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)

    start = time.perf_counter()
    sock.connect((args.host, args.port))

    for _ in range(full_chunks):
        sock.sendall(chunk)
    if remainder:
        sock.sendall(chunk[:remainder])

    sock.close()
    elapsed = time.perf_counter() - start

    throughput = args.size_mb / elapsed if elapsed > 0 else float("inf")

    print(f"[sender] total data sent : {args.size_mb:.4f} MB")
    print(f"[sender] elapsed time    : {elapsed:.6f} s")
    print(f"[sender] throughput      : {throughput:.4f} MB/s")


if __name__ == "__main__":
    main()
