"""
receiver.py

Two-party communication cost test: the receiving side.
Listens for one TCP connection, receives all data the sender sends,
and reports total bytes received and elapsed time.

Usage:
  sudo ip netns exec party1 python3 receiver.py --host 10.10.0.2 --port 9000
"""

import argparse
import socket
import time


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", required=True)
    parser.add_argument("--port", type=int, default=9000)
    args = parser.parse_args()

    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server.bind((args.host, args.port))
    server.listen(1)

    print(f"[receiver] listening on {args.host}:{args.port}")

    conn, addr = server.accept()
    print(f"[receiver] connection from {addr}")

    total_bytes = 0
    start = time.perf_counter()

    while True:
        chunk = conn.recv(1024 * 1024)
        if not chunk:
            break
        total_bytes += len(chunk)

    elapsed = time.perf_counter() - start

    conn.close()
    server.close()

    mb = total_bytes / (1024 * 1024)
    throughput = mb / elapsed if elapsed > 0 else float("inf")

    print(f"[receiver] total data received : {mb:.4f} MB")
    print(f"[receiver] elapsed time        : {elapsed:.6f} s")
    print(f"[receiver] throughput          : {throughput:.4f} MB/s")


if __name__ == "__main__":
    main()
