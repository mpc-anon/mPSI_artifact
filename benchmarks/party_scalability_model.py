"""
Party-count scalability benchmark, reproducing Figure 5(d)-(f):
online computation cost and communication volume as the number of
parties n grows, with the corruption threshold fixed at t=3 and the
universe size fixed at m=2^20, matching the paper's Experimental
Setup (Section IV) for this sweep ("varying n while fixing t=3").

NOTE: the paper states only that computation and communication
exhibit "near-linear growth as n increases" and does not list the
exact n values plotted in Figure 5(d)-(f). The range below (up to
n=100) is chosen to demonstrate scalability well beyond the (n,t)
grid tabulated in Table V/VI (n <= 15). If the original experiment
used a different n range, edit N_VALUES below to match before
claiming this script reproduces the figure's exact data points.

Like online_cost_model.py (Part 3), this script benchmarks the
REAL computation time of the pivot's online-phase operations, and
computes communication volume ANALYTICALLY from the protocol's
message sizes (same formulas as online_cost_model.py). To obtain a
real-network total execution time for a given n (matching Figure
5(f)), feed this script's reported communication volume (MB) for
that n into network/run_comm_test.sh, as described in Part 4.
"""

import time
import numpy as np

# =========================================================
# Parameters
# =========================================================

REAL_M = 2 ** 20   # fixed universe size, matching Figure 5(d)-(f)
NUM_THREADS = 16
T_FIXED = 3        # fixed corruption threshold, matching Figure 5(d)-(f)

FIELD_BITS = 40
DTYPE = np.uint64
REPEAT = 10

rng = np.random.default_rng()
MASK = np.uint64((1 << FIELD_BITS) - 1)

# Party counts to sweep. Edit this list if the original experiment
# used different values (see NOTE above).
N_VALUES = [4, 10, 15, 25, 50, 75, 100]

# LAN/WAN analytical total-time model (same as online_cost_model.py):
# Total Time = Comm Volume / Bandwidth + RTT. This is an ANALYTICAL
# estimate; network/run_comm_test.sh (Part 4) provides a REAL,
# tc-emulated measurement to validate it.
LAN_BANDWIDTH_BPS = 10e9   # 10 Gbps
LAN_RTT_S = 0.02e-3        # 0.02 ms
WAN_BANDWIDTH_BPS = 200e6  # 200 Mbps
WAN_RTT_S = 96e-3          # 96 ms


def total_time_seconds(comm_bits, bandwidth_bps, rtt_s):
    return comm_bits / bandwidth_bps + rtt_s

# =========================================================
# Random Data
# =========================================================

def random_vector(ell):
    return rng.integers(0, 1 << FIELD_BITS, size=ell, dtype=DTYPE)


def random_scalar():
    return rng.integers(1, 1 << FIELD_BITS, dtype=DTYPE)

# =========================================================
# Operations
# =========================================================

def vector_xor(a, b, out=None):
    return np.bitwise_xor(a, b, out=out)


def scalar_vector_mul(delta, vector):
    """Vectorized scalar-vector multiplication used for
    online-phase timing measurements (same convention as
    online_cost_model.py)."""
    result = np.empty_like(vector)
    np.multiply(vector, delta, out=result)
    np.bitwise_and(result, MASK, out=result)
    return result

# =========================================================
# Communication (analytical, same formulas as online_cost_model.py)
# =========================================================

def bits_to_mb(bits):
    return bits / 8 / 1024 / 1024


def single_vector_bits(ell):
    return ell * FIELD_BITS


def pivot_comm_bits(n, t, ell):
    num_clients = max(0, n - t - 1)
    recv_from_clients = num_clients * single_vector_bits(ell)
    send_gbf_n_minus_1 = single_vector_bits(ell)
    broadcast_g_prime = t * single_vector_bits(ell)
    recv_ggamma = t * single_vector_bits(ell)
    send_bits = send_gbf_n_minus_1 + broadcast_g_prime
    recv_bits = recv_from_clients + recv_ggamma
    return send_bits + recv_bits


def total_comm_bits(n, t, ell):
    num_clients = max(0, n - t - 1)
    client_send = num_clients * single_vector_bits(ell)
    pivot_send = single_vector_bits(ell) + t * single_vector_bits(ell)
    server_send = t * single_vector_bits(ell)
    return client_send + pivot_send + server_send

# =========================================================
# Benchmark: Pivot cost (dominant online-phase cost; grows with n)
# =========================================================

def benchmark_pivot(n, t, ell):
    """Supports the extreme case t = n-1; identical structure to
    online_cost_model.py's benchmark_pivot."""
    times = []

    for _ in range(REPEAT):
        start = time.perf_counter()

        g_n = random_vector(ell)
        num_clients = max(0, n - t - 1)
        for _ in range(num_clients):
            v = random_vector(ell)
            vector_xor(g_n, v, out=g_n)

        g_prime = random_vector(ell)
        for _ in range(t):
            v = random_vector(ell)
            vector_xor(g_prime, v, out=g_prime)

        delta_n = random_scalar()
        ggamma_n = scalar_vector_mul(delta_n, g_prime)
        b_n = random_vector(ell)
        vector_xor(ggamma_n, b_n, out=ggamma_n)

        for _ in range(t):
            v = random_vector(ell)
            vector_xor(ggamma_n, v, out=ggamma_n)

        end = time.perf_counter()
        times.append(end - start)

    return min(times)

# =========================================================
# Run
# =========================================================

if __name__ == "__main__":
    # ell_compute: per-thread working length, used for real-timed
    # computation. ell_comm: full vector length, used for all
    # communication formulas (communication does not benefit from
    # local parallelism -- see online_cost_model.py for the same
    # convention).
    m_prime = max(1, REAL_M // NUM_THREADS)
    ell_compute = 8 * m_prime
    ell_comm = 8 * REAL_M

    print("\n================ Party-Count Scalability (Figure 5(d)-(f)) ================\n")
    print(f"m           = {REAL_M}")
    print(f"m'          = {m_prime}")
    print(f"ell_compute = 8m' = {ell_compute}")
    print(f"ell_comm    = 8m  = {ell_comm}")
    print(f"t           = {T_FIXED} (fixed)")
    print(f"field       = GF(2^{FIELD_BITS})")
    print(f"repeat      = {REPEAT}")

    for n in N_VALUES:
        pivot_time = benchmark_pivot(n, T_FIXED, ell_compute)
        pivot_comm = pivot_comm_bits(n, T_FIXED, ell_comm)
        total_comm = total_comm_bits(n, T_FIXED, ell_comm)
        num_clients = max(0, n - T_FIXED - 1)

        lan_time = total_time_seconds(total_comm, LAN_BANDWIDTH_BPS, LAN_RTT_S)
        wan_time = total_time_seconds(total_comm, WAN_BANDWIDTH_BPS, WAN_RTT_S)

        print(f"\nn = {n:<4} clients = {num_clients}")
        print(f"  Computation (pivot)      : {pivot_time:.6f} s")
        print(f"  Pivot communication      : {bits_to_mb(pivot_comm):.2f} MB")
        print(f"  Total communication      : {bits_to_mb(total_comm):.2f} MB")
        print(f"  LAN total time           : {lan_time:.4f} s")
        print(f"  WAN total time           : {wan_time:.4f} s")
