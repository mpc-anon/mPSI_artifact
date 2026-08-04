"""
Batch timing test for the mPSI protocol across multiple universe sizes.

This simulates a single independent thread's workload: the real
universe size is split across 16 parallel threads, so each thread
only processes m' = real_m / 16 elements. The protocol is run with
m' as the working universe size.
"""

from mpsi_protocol import (
    construct_valid_universe,
    sample_subsets_from_universe,
    run_mpsi_protocol,
)
import time

n, t = 8, 3
ell_factor, K = 8, 4

NUM_THREADS = 16

OFFLINE_PHASES = ("1. offline VOLE preprocessing", "2. offline seed and PRG")

# ============ real universe sizes to test, and each party's set size
# as a fraction of the (per-thread) universe ============
real_m_sizes = [2**12, 2**16, 2**20]
fracs = [0.1, 0.2, 0.33, 0.5, 0.6, 0.7, 0.8, 0.9]

for real_m in real_m_sizes:
    m_prime = max(1, real_m // NUM_THREADS)
    ell = ell_factor * m_prime
    party_sizes = [max(1, int(m_prime * f)) for f in fracs]

    universe, _, _ = construct_valid_universe(m_prime, ell, K)
    X = sample_subsets_from_universe(
        m_prime, party_sizes, seed=2, universe=universe, preserve_order=True
    )

    t0 = time.perf_counter()
    res = run_mpsi_protocol(
        n=n, t=t,
        ell_factor=ell_factor, K=K, kappa_bits=128,
        custom_X=X, universe_size=m_prime,
    )
    t1 = time.perf_counter()

    pt = res["cost"].phase_time
    offline_time = sum(v for k, v in pt.items() if k in OFFLINE_PHASES)

    true_intersection = set(X[1])
    for i in range(2, n + 1):
        true_intersection &= set(X[i])

    recovered = set(res["recovered"])
    correct = (recovered == true_intersection)

    print(f"m  = {real_m}")
    print(f"m' = {m_prime}")
    print(f"  K = {K}")
    print(f"  ell = {res['ell']}")
    print(f"  offline time  = {offline_time:.4f} s")
    print(f"  expected intersection = {sorted(true_intersection)}")
    print(f"  recovered intersection = {sorted(recovered)}")
    print(f"  correct = {correct}")
    print()
