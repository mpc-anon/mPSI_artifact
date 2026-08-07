import time
import numpy as np

# =========================================================
# Parameters
# =========================================================

# real universe sizes to test: m = 2^12, 2^16, 2^20
# each is split across 16 parallel threads, so the working
# size used internally is m' = m / 16
real_m_values = [2**12, 2**16, 2**20]
NUM_THREADS = 16

field_bits = 40
dtype = np.uint64
repeat = 10

rng = np.random.default_rng()
mask = np.uint64((1 << field_bits) - 1)

# =========================================================
# LAN/WAN analytical total-time model, matching the paper's
# Table V / Figure 5(c)/(f): Total Time = Comm Volume / Bandwidth
# + RTT. This is an ANALYTICAL estimate; network/run_comm_test.sh
# (Part 4) provides a REAL, tc-emulated measurement to validate it.
# =========================================================

LAN_BANDWIDTH_BPS = 10e9   # 10 Gbps
LAN_RTT_S = 0.02e-3        # 0.02 ms
WAN_BANDWIDTH_BPS = 200e6  # 200 Mbps
WAN_RTT_S = 96e-3          # 96 ms


def total_time_seconds(comm_bits, bandwidth_bps, rtt_s):
    return comm_bits / bandwidth_bps + rtt_s

# test different party sizes
n_values = [4, 10, 15]

# =========================================================
# Random Data
# =========================================================

def random_vector(ell):
    return rng.integers(
        0,
        1 << field_bits,
        size=ell,
        dtype=dtype
    )


def random_scalar():
    return rng.integers(
        1,
        1 << field_bits,
        dtype=dtype
    )

# =========================================================
# Operations
# =========================================================

def vector_xor(a, b, out=None):
    return np.bitwise_xor(a, b, out=out)


def scalar_vector_mul(delta, vector):
    """
    Vectorized scalar-vector multiplication used for
    online-phase timing measurements.
    """

    result = np.empty_like(vector)

    np.multiply(vector, delta, out=result)
    np.bitwise_and(result, mask, out=result)

    return result

# =========================================================
# Communication
# =========================================================

def bits_to_mb(bits):
    return bits / 8 / 1024 / 1024


def single_vector_bits(ell):
    return ell * field_bits

# =========================================================
# Per-party Communication Cost
# =========================================================

def single_client_comm_bits(ell):

    send_bits = single_vector_bits(ell)
    recv_bits = 0

    return send_bits + recv_bits


def pivot_comm_bits(n, t, ell):

    # number of clients
    num_clients = max(0, n - t - 1)

    # receive from clients
    recv_from_clients = (
        num_clients
        * single_vector_bits(ell)
    )

    # send GBF_{n-1}
    send_gbf_n_minus_1 = single_vector_bits(ell)

    # broadcast G'
    broadcast_g_prime = (
        t * single_vector_bits(ell)
    )

    # receive Ggamma_j
    recv_ggamma = (
        t * single_vector_bits(ell)
    )

    send_bits = (
        send_gbf_n_minus_1
        + broadcast_g_prime
    )

    recv_bits = (
        recv_from_clients
        + recv_ggamma
    )

    return send_bits + recv_bits

# =========================================================
# Total Communication Cost
# =========================================================

def total_comm_bits(n, t, ell):

    num_clients = max(0, n - t - 1)

    # client send
    client_send = (
        num_clients
        * single_vector_bits(ell)
    )

    # pivot send
    pivot_send = (
        single_vector_bits(ell)
        + t * single_vector_bits(ell)
    )

    # server send
    server_send = (
        t * single_vector_bits(ell)
    )

    return (
        client_send
        + pivot_send
        + server_send
    )

# =========================================================
# Benchmark: Single Client
# =========================================================

def benchmark_single_client(ell):

    times = []

    for _ in range(repeat):

        gbf_i = random_vector(ell)
        gbf_mask_i = random_vector(ell)
        w_i = random_vector(ell)

        start = time.perf_counter()

        gbf_blind = np.empty_like(gbf_i)

        # GBF_blind = GBF_i XOR GBF_mask_i
        vector_xor(gbf_i, gbf_mask_i, out=gbf_blind)

        # G_i,n = GBF_blind XOR W_i
        vector_xor(gbf_blind, w_i, out=gbf_blind)

        end = time.perf_counter()

        times.append(end - start)

    return min(times)

# =========================================================
# Benchmark: Pivot
# =========================================================

def benchmark_pivot(n, t, ell):

    """
    Supports the extreme case t = n-1.
    """

    times = []

    for _ in range(repeat):

        start = time.perf_counter()

        # =================================================
        # 1. Compute G_n
        # =================================================

        g_n = random_vector(ell)

        num_clients = max(0, n - t - 1)

        for _ in range(num_clients):

            v = random_vector(ell)

            vector_xor(g_n, v, out=g_n)

        # =================================================
        # 2. Compute G'
        # =================================================

        g_prime = random_vector(ell)

        for _ in range(t):

            v = random_vector(ell)

            vector_xor(g_prime, v, out=g_prime)

        # =================================================
        # 3. Compute Ggamma_n
        # =================================================

        delta_n = random_scalar()

        ggamma_n = scalar_vector_mul(
            delta_n,
            g_prime
        )

        b_n = random_vector(ell)

        vector_xor(
            ggamma_n,
            b_n,
            out=ggamma_n
        )

        # =================================================
        # 4. Final Reconstruction
        # =================================================

        for _ in range(t):

            v = random_vector(ell)

            vector_xor(
                ggamma_n,
                v,
                out=ggamma_n
            )

        end = time.perf_counter()

        times.append(end - start)

    return min(times)

# =========================================================
# Run
# =========================================================

for real_m in real_m_values:

    # ell_compute is the PER-THREAD working vector length: with
    # NUM_THREADS workers each handling a 1/NUM_THREADS share of the
    # universe, this is what benchmark_single_client/benchmark_pivot
    # actually time (real parallel speedup on computation).
    #
    # ell_comm is the FULL vector length. Communication volume does
    # NOT benefit from local parallelism -- the complete ell-length
    # vector must still cross the network in its entirety -- so all
    # communication formulas use ell_comm, not ell_compute.
    m_prime = max(1, real_m // NUM_THREADS)
    ell_compute = 8 * m_prime
    ell_comm = 8 * real_m

    print("\n================ Online Cost Model ================\n")

    print(f"m           = {real_m}")
    print(f"m'          = {m_prime}")
    print(f"ell_compute = 8m' = {ell_compute}")
    print(f"ell_comm    = 8m  = {ell_comm}")
    print(f"field       = GF(2^{field_bits})")
    print(f"repeat      = {repeat}")
    print(f"one vector  = {bits_to_mb(single_vector_bits(ell_comm)):.2f} MB")

    # =========================================================
    # Single Client
    # =========================================================

    print("\n================ Single Client Cost ================\n")

    client_time = benchmark_single_client(ell_compute)

    client_comm = single_client_comm_bits(ell_comm)

    print("Computation:")

    print(f"  Formula              : 2ell XOR")
    print(f"  Runtime              : {client_time:.6f} s")

    print(
        f"  Per XOR element cost : "
        f"{client_time / (2 * ell_compute):.12e} s"
    )

    print("\nCommunication Cost:")

    print(f"  Definition           : send + receive")
    print(f"  Formula              : ell * {field_bits} bits")

    print(
        f"  Communication        : "
        f"{bits_to_mb(client_comm):.2f} MB"
    )

    # =========================================================
    # Pivot
    # =========================================================

    print("\n================ Pivot Cost ================\n")

    for n in n_values:

        print(f"\n---------------- n = {n} ----------------\n")

        # include t = n-1
        for t in range(1, n):

            pivot_time = benchmark_pivot(n, t, ell_compute)

            pivot_comm = pivot_comm_bits(n, t, ell_comm)

            total_comm = total_comm_bits(n, t, ell_comm)

            num_clients = max(0, n - t - 1)

            print(f"t = {t}")

            print(f"clients = {num_clients}")

            if t == n - 1:
                print("EXTREME CASE: t = n - 1")

            print("\nComputation:")

            print(
                f"  Formula       : "
                f"(n+t)ell XOR + ell MUL"
            )

            print(
                f"  Runtime       : "
                f"{pivot_time:.6f} s"
            )

            print("\nPivot Communication Cost:")

            print(
                f"  Definition    : "
                f"send + receive of pivot"
            )

            print(
                f"  Communication : "
                f"{bits_to_mb(pivot_comm):.2f} MB"
            )

            print("\nTotal Communication Cost:")

            print(
                f"  Definition    : "
                f"sum of data sent by all parties"
            )

            print(
                f"  Communication : "
                f"{bits_to_mb(total_comm):.2f} MB"
            )

            lan_time = total_time_seconds(total_comm, LAN_BANDWIDTH_BPS, LAN_RTT_S)
            wan_time = total_time_seconds(total_comm, WAN_BANDWIDTH_BPS, WAN_RTT_S)

            print("\nLAN/WAN Total Time (analytical; Table V / Figure 5(c)/(f)):")

            print(
                f"  Definition    : "
                f"Total Communication / Bandwidth + RTT"
            )

            print(f"  LAN (10 Gbps, 0.02ms RTT) : {lan_time:.4f} s")
            print(f"  WAN (200 Mbps, 96ms RTT)  : {wan_time:.4f} s")

            print("------------------------------------------")
