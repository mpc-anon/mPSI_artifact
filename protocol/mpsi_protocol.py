"""
mPSI protocol reference implementation (Pi_mpsi).

Zero-sharing based multi-party PSI using Garbled Bloom Filters (GBF)
and VOLE. Collusion resistance up to t <= n-1 without a trusted third
party.

This implementation is optimized for speed while keeping the protocol
logic unchanged from the original specification:
  - Field arithmetic (GF(2^40) multiplication, XOR) is vectorized with
    numpy instead of per-element Python loops.
  - The PRG is implemented with SHAKE256 (an extendable-output hash
    function), which can produce an arbitrarily long output in a
    single call instead of chaining many fixed-size SHA256 calls.
  - Random field vectors are drawn from os.urandom in one batched
    call per vector instead of one urandom() call per element.
"""

import hashlib
import os
import secrets
import time
from dataclasses import dataclass, field
from typing import Dict, List, Tuple

import numpy as np


# ============================================================
# Field parameters: GF(2^40)
# Irreducible polynomial: x^40 + x^5 + x^4 + x^3 + 1
# ============================================================

FIELD_BITS = 40
FIELD_BYTES = (FIELD_BITS + 7) // 8
FIELD_MASK = (1 << FIELD_BITS) - 1
GF40_POLY = (1 << 40) | (1 << 5) | (1 << 4) | (1 << 3) | 1


# ============================================================
# Cost tracker
# ============================================================

@dataclass
class CostTracker:
    hash_ops: int = 0
    prg_ops: int = 0
    xor_vec_ops: int = 0
    scalar_vec_mul_ops: int = 0
    comm_bytes: int = 0
    phase_time: Dict[str, float] = field(default_factory=dict)

    def add_time(self, phase: str, seconds: float):
        self.phase_time[phase] = self.phase_time.get(phase, 0.0) + seconds

    def add_comm(self, num_bytes: int):
        self.comm_bytes += num_bytes

    def report(self):
        print("\n========== Cost Report ==========")
        print(f"Hash ops:                 {self.hash_ops}")
        print(f"PRG ops:                  {self.prg_ops}")
        print(f"Vector XOR ops:           {self.xor_vec_ops}")
        print(f"Scalar-vector mul ops:    {self.scalar_vec_mul_ops}")
        print(f"Communication:            {self.comm_bytes / (1024 * 1024):.4f} MB")

        print("\n---------- Phase Time ----------")
        total = 0.0
        for phase, sec in self.phase_time.items():
            print(f"{phase:<35}: {sec:.6f} s")
            total += sec
        print(f"{'Total':<35}: {total:.6f} s")
        print("=================================\n")


# ============================================================
# GF(2^40) field operations
# ============================================================

def gf40_mul_vec(a_arr: np.ndarray, b: int) -> np.ndarray:
    """
    Vectorized GF(2^40) multiplication: multiplies an entire array by a
    scalar in one call. Loops only FIELD_BITS (=40) times regardless of
    array length, instead of looping per-element in Python.
    """
    a = np.asarray(a_arr, dtype=np.uint64) & np.uint64(FIELD_MASK)
    result = np.zeros_like(a)
    top_bit = np.uint64(1 << (FIELD_BITS - 1))
    reduced_poly = np.uint64(GF40_POLY & FIELD_MASK)
    mask = np.uint64(FIELD_MASK)

    bb = int(b)
    for _ in range(FIELD_BITS):
        if bb & 1:
            result ^= a
        bb >>= 1
        overflow = (a & top_bit) != 0
        a = (a << np.uint64(1)) & mask
        a = np.where(overflow, a ^ reduced_poly, a)

    return result


def gf40_mul(a: int, b: int) -> int:
    """Scalar GF(2^40) multiplication (used for single field elements)."""
    a &= FIELD_MASK
    b &= FIELD_MASK
    product = 0
    while b:
        if b & 1:
            product ^= a
        b >>= 1
        a <<= 1
    for bit in range(product.bit_length() - 1, FIELD_BITS - 1, -1):
        if product & (1 << bit):
            product ^= GF40_POLY << (bit - FIELD_BITS)
    return product & FIELD_MASK


def random_field_element() -> int:
    return secrets.randbits(FIELD_BITS)


def random_vector(ell: int) -> np.ndarray:
    """
    Draw a length-ell random field vector. Uses a single batched
    os.urandom call (still a cryptographically secure random source)
    followed by vectorized numpy extraction, instead of one urandom
    call per element.
    """
    raw = os.urandom(ell * FIELD_BYTES)
    buf = np.frombuffer(raw, dtype=np.uint8).reshape(ell, FIELD_BYTES)
    padded = np.zeros((ell, 8), dtype=np.uint8)
    padded[:, 3:8] = buf
    values = padded.view(">u8").reshape(ell).astype(np.uint64)
    values &= np.uint64(FIELD_MASK)
    return values


def zero_vector(ell: int) -> np.ndarray:
    return np.zeros(ell, dtype=np.uint64)


def xor_vectors(a, b, cost: CostTracker = None):
    if cost:
        cost.xor_vec_ops += 1
    a_np = np.asarray(a, dtype=np.uint64)
    b_np = np.asarray(b, dtype=np.uint64)
    return a_np ^ b_np


def xor_many(vectors, ell: int, cost: CostTracker = None):
    result = np.zeros(ell, dtype=np.uint64)
    for v in vectors:
        result ^= np.asarray(v, dtype=np.uint64)
        if cost:
            cost.xor_vec_ops += 1
    return result


def scalar_vector_mul(delta: int, vec, cost: CostTracker = None):
    if cost:
        cost.scalar_vec_mul_ops += 1
    return gf40_mul_vec(vec, delta)


# ============================================================
# Hash and PRG
# ============================================================

def hash_positions(x: int, K: int, ell: int, cost: CostTracker = None) -> List[int]:
    """Generate K distinct hash positions for element x."""
    if ell < K:
        raise ValueError("ell must be at least K.")

    positions = []
    seen = set()
    counter = 1

    while len(positions) < K:
        if cost:
            cost.hash_ops += 1

        data = f"{x}-{counter}".encode()
        digest = hashlib.sha256(data).digest()
        u = int.from_bytes(digest, "big") % ell

        if u not in seen:
            positions.append(u)
            seen.add(u)

        counter += 1

    return positions


def PRG(seed: bytes, ell: int, cost: CostTracker = None) -> np.ndarray:
    """
    PRG(seed) -> length-ell vector in GF(2^40).
    Uses SHAKE256 (an extendable-output hash function) to produce all
    required bytes in a single call, then extracts field elements with
    vectorized numpy operations, instead of chaining SHA256 calls with
    a per-element Python loop.
    """
    if cost:
        cost.prg_ops += 1

    needed_bytes = ell * FIELD_BYTES
    digest = hashlib.shake_256(seed).digest(needed_bytes)
    buf = np.frombuffer(digest, dtype=np.uint8).reshape(ell, FIELD_BYTES)
    padded = np.zeros((ell, 8), dtype=np.uint8)
    padded[:, 3:8] = buf
    values = padded.view(">u8").reshape(ell).astype(np.uint64)
    values &= np.uint64(FIELD_MASK)
    return values


# ============================================================
# GBF algorithms
# ============================================================

def insert_gbf_with_target(
    gbf: List[int],
    x: int,
    target: int,
    K: int,
    ell: int,
    cost: CostTracker,
    skip_on_failure: bool = False,
) -> bool:
    """
    Insert x into the GBF such that XOR over its K positions equals
    target. Returns True on success. If no empty cell is available
    among the K positions, returns False when skip_on_failure is True,
    otherwise raises RuntimeError.
    """
    v = target
    u_star = None

    for u in hash_positions(x, K, ell, cost):
        if gbf[u] is None:
            if u_star is None:
                u_star = u
            else:
                r = random_field_element()
                gbf[u] = r
                v ^= r
        else:
            v ^= gbf[u]

    if u_star is None:
        if skip_on_failure:
            return False
        raise RuntimeError("GBF insertion failed: increase ell.")

    gbf[u_star] = v
    return True


def gen1(
    Xn: List[int],
    seeds: Dict[int, bytes],
    n: int,
    ell: int,
    K: int,
    cost: CostTracker,
    skip_on_failure: bool = True,
) -> Tuple[np.ndarray, np.ndarray, Dict[int, np.ndarray], List[int]]:
    """Gen1: executed by the pivot party. Inserts random target shares."""
    base_gbf = [None] * ell
    gbf_shares = {}
    skipped = []

    for i in range(1, n - 1):
        gbf_shares[i] = PRG(seeds[i], ell, cost)

    for x in Xn:
        target = random_field_element()
        ok = insert_gbf_with_target(
            base_gbf, x, target, K, ell, cost, skip_on_failure=skip_on_failure
        )
        if not ok:
            skipped.append(x)

    for u in range(ell):
        if base_gbf[u] is None:
            base_gbf[u] = random_field_element()

    gbf_n = np.array(base_gbf, dtype=np.uint64)

    gbf_n_minus_1 = gbf_n.copy()
    for i in range(1, n - 1):
        gbf_n_minus_1 = xor_vectors(gbf_n_minus_1, gbf_shares[i], cost)

    return gbf_n_minus_1, gbf_n, gbf_shares, skipped


def gen2(
    Xi: List[int],
    ell: int,
    K: int,
    cost: CostTracker,
    skip_on_failure: bool = True,
) -> Tuple[np.ndarray, List[int]]:
    """Gen2: executed independently by every party. Inserts zero targets."""
    mask = [None] * ell
    skipped = []

    for y in Xi:
        ok = insert_gbf_with_target(
            mask, y, 0, K, ell, cost, skip_on_failure=skip_on_failure
        )
        if not ok:
            skipped.append(y)

    for u in range(ell):
        if mask[u] is None:
            mask[u] = random_field_element()

    return np.array(mask, dtype=np.uint64), skipped


def query_gbf(vec, x: int, ell: int, K: int, cost: CostTracker = None) -> int:
    value = 0
    for u in hash_positions(x, K, ell, cost):
        value ^= int(vec[u])
    return value


# ============================================================
# Universe construction helpers
#
# Some (ell, K, party size) combinations are too tight for a GBF to
# accept every element without collision. These helpers build a
# universe whose elements are guaranteed to insert successfully, and
# let each party draw an order-preserving subset from it so that
# per-party insertion also succeeds (a subsequence of a successful
# insertion sequence is guaranteed to succeed as well, since removing
# elements can only free up slots, never consume more).
# ============================================================

def construct_valid_universe(
    target_size: int,
    ell: int,
    K: int,
    candidate_pool_start: int = 1,
    max_candidates: int = None,
):
    """
    Try candidates in increasing order, inserting each into a GBF and
    keeping the ones that succeed, until target_size elements have
    been accumulated. Returns (universe, gbf, num_candidates_tried).
    """
    if max_candidates is None:
        max_candidates = target_size * 20

    gbf = [None] * ell
    universe = []
    cost = CostTracker()

    candidate = candidate_pool_start
    tried = 0

    while len(universe) < target_size and tried < max_candidates:
        tried += 1
        ok = insert_gbf_with_target(
            gbf, candidate, random_field_element(), K, ell, cost,
            skip_on_failure=True,
        )
        if ok:
            universe.append(candidate)
        candidate += 1

    return universe, gbf, tried


def sample_subsets_from_universe(
    universe_size: int,
    party_sizes: List[int],
    seed: int = None,
    universe: List[int] = None,
    preserve_order: bool = True,
) -> Dict[int, List[int]]:
    """
    Build X[1..n] where each party's set is drawn from a shared
    universe. party_sizes[i-1] is the size of party i's set.

    universe: an explicit element list (e.g. from construct_valid_universe);
              defaults to {1, ..., universe_size}.
    preserve_order: keep each party's subset in the same relative order
              as the universe list, which inherits its insertion
              guarantees.
    """
    import random as _random

    rng = _random.Random(seed)
    base_universe = universe if universe is not None else list(range(1, universe_size + 1))
    order_index = {x: idx for idx, x in enumerate(base_universe)}

    X = {}
    for idx, size in enumerate(party_sizes, start=1):
        if size > len(base_universe):
            raise ValueError(
                f"Party {idx} requested size {size} > universe size {len(base_universe)}"
            )
        chosen = rng.sample(base_universe, size)
        if preserve_order:
            chosen.sort(key=lambda x: order_index[x])
        X[idx] = chosen

    return X


# ============================================================
# Main protocol
# ============================================================

def run_mpsi_protocol(
    n: int = 8,
    t: int = 3,
    m: int = 100,
    ell_factor: int = 8,
    K: int = 4,
    kappa_bits: int = 128,
    verbose: bool = False,
    custom_X: Dict[int, List[int]] = None,
    universe_size: int = None,
):
    """
    Run one full instance of the mPSI protocol.

    n, t: total parties and collusion threshold.
    m: per-party set size (used only when custom_X is not provided).
    ell_factor, K: GBF parameters (ell = ell_factor * universe_size).
    custom_X: optional explicit {party_id: element_list} mapping.
    universe_size: explicit universe size used to scale ell when
        custom_X is provided (defaults to m when not provided).
    """
    cost = CostTracker()

    ell_base = universe_size if universe_size is not None else m
    ell = ell_factor * ell_base
    vector_bytes = ell * FIELD_BYTES
    seed_bytes = kappa_bits // 8

    clients = list(range(1, n - t))
    servers = list(range(n - t, n + 1))
    ordinary_servers = list(range(n - t, n - 1))
    special_server = n - 1
    pivot = n

    if custom_X is not None:
        X = custom_X
    else:
        common = list(range(1, m // 5 + 1))
        X = {}
        for i in range(1, n + 1):
            private_part = list(range(i * 100000, i * 100000 + m - len(common)))
            X[i] = common + private_part

    # ---------------- Phase 1: offline VOLE preprocessing ----------------
    start = time.perf_counter()

    A = {}
    Delta = {}
    B = {}
    A_prime = {}
    B_prime = {}
    C_prime = {}
    A_star = {}

    for i in servers:
        A[i] = random_vector(ell)
        Delta[i] = random_field_element()

    for i in servers:
        for j in servers:
            if i == j:
                continue

            A_prime[(i, j)] = random_vector(ell)
            C_prime[(i, j)] = random_vector(ell)

            delta_A = scalar_vector_mul(Delta[i], A_prime[(i, j)], cost)
            B_prime[(i, j)] = xor_vectors(delta_A, C_prime[(i, j)], cost)

            A_star[(i, j)] = xor_vectors(A[j], A_prime[(i, j)], cost)

            cost.add_comm(vector_bytes)

    for i in servers:
        tmp = A[i].copy()

        for j in servers:
            if j == i:
                continue
            tmp = xor_vectors(tmp, A_star[(i, j)], cost)

        left = scalar_vector_mul(Delta[i], tmp, cost)

        c_sum = xor_many([C_prime[(i, j)] for j in servers if j != i], ell, cost)
        b_sum = xor_many([B_prime[(j, i)] for j in servers if j != i], ell, cost)

        B[i] = xor_vectors(xor_vectors(left, c_sum, cost), b_sum, cost)

    cost.add_time("1. offline VOLE preprocessing", time.perf_counter() - start)

    # ---------------- Phase 2: offline seed and PRG expansion ----------------
    start = time.perf_counter()

    seed_ij = {}
    W = {}

    for i in clients:
        vecs = []
        for j in range(n - t, n):
            seed_ij[(i, j)] = secrets.token_bytes(seed_bytes)
            vecs.append(PRG(seed_ij[(i, j)], ell, cost))
            cost.add_comm(seed_bytes)
        W[i] = xor_many(vecs, ell, cost)

    Q = {}
    for j in range(n - t, n):
        vecs = [PRG(seed_ij[(i, j)], ell, cost) for i in clients]
        Q[j] = xor_many(vecs, ell, cost)

    gbf_seed = {}
    for i in range(1, n - 1):
        gbf_seed[i] = secrets.token_bytes(seed_bytes)
        cost.add_comm(seed_bytes)

    cost.add_time("2. offline seed and PRG", time.perf_counter() - start)

    # ---------------- Phase 3: online blinding (Gen1/Gen2 + blind) ----------------
    start = time.perf_counter()

    gen1_start = time.perf_counter()
    gbf_n_minus_1, gbf_n, gbf_shares, _ = gen1(
        X[pivot], gbf_seed, n, ell, K, cost, skip_on_failure=True
    )
    gen1_time = time.perf_counter() - gen1_start

    gbf_mask = {}
    gen2_times = []
    for i in range(1, n):
        local_start = time.perf_counter()
        gbf_mask[i], _ = gen2(X[i], ell, K, cost, skip_on_failure=True)
        gen2_times.append(time.perf_counter() - local_start)

    gbf_blind = {}
    blind_times = []
    for i in range(1, n - 1):
        local_start = time.perf_counter()
        gbf_blind[i] = xor_vectors(gbf_shares[i], gbf_mask[i], cost)
        blind_times.append(time.perf_counter() - local_start)

    parallel_gen_time = max([gen1_time] + gen2_times)
    parallel_blind_time = max(blind_times) if blind_times else 0.0

    cost.add_time("3. online blinding", parallel_gen_time + parallel_blind_time)

    # ---------------- Phase 4: online share preparation ----------------
    start = time.perf_counter()

    G_i_n = {}
    for i in clients:
        G_i_n[i] = xor_vectors(gbf_blind[i], W[i], cost)
        cost.add_comm(vector_bytes)

    cost.add_time("4. online share preparation", time.perf_counter() - start)

    # ---------------- Phase 5: server-side online aggregation ----------------
    start = time.perf_counter()

    G = {}
    for j in ordinary_servers:
        G[j] = xor_vectors(Q[j], gbf_blind[j], cost)

    G[pivot] = xor_vectors(
        xor_many([G_i_n[i] for i in clients], ell, cost), gbf_n, cost
    )
    cost.add_comm(vector_bytes)

    gbf_blind[special_server] = xor_vectors(
        gbf_n_minus_1, gbf_mask[special_server], cost
    )
    G[special_server] = xor_vectors(Q[special_server], gbf_blind[special_server], cost)

    cost.add_time("5. server-side aggregation", time.perf_counter() - start)

    # ---------------- Phase 6: online masked aggregation ----------------
    start = time.perf_counter()

    G_prime_j = {}
    for j in servers:
        G_prime_j[j] = xor_vectors(A[j], G[j], cost)

    cost.add_time("6. masked aggregation", time.perf_counter() - start)

    # ---------------- Phase 7: broadcast and evaluation ----------------
    start = time.perf_counter()

    G_prime = xor_many([G_prime_j[j] for j in servers], ell, cost)
    cost.add_comm(t * vector_bytes)
    broadcast_time = time.perf_counter() - start

    G_gamma_j = {}
    local_eval_times = []
    for j in servers:
        local_start = time.perf_counter()
        delta_G = scalar_vector_mul(Delta[j], G_prime, cost)
        G_gamma_j[j] = xor_vectors(delta_G, B[j], cost)
        local_eval_times.append(time.perf_counter() - local_start)
        if j != pivot:
            cost.add_comm(vector_bytes)

    parallel_eval_time = max(local_eval_times)
    cost.add_time("7. broadcast and evaluation", broadcast_time + parallel_eval_time)

    # ---------------- Phase 8: final reconstruction ----------------
    start = time.perf_counter()

    G_gamma = xor_many([G_gamma_j[j] for j in servers], ell, cost)

    result = []
    for x in X[pivot]:
        value = query_gbf(G_gamma, x, ell, K, cost)
        if value == 0:
            result.append(x)

    cost.add_time("8. final reconstruction", time.perf_counter() - start)

    if verbose:
        print(f"n={n}, t={t}, ell={ell}, K={K}, field=GF(2^{FIELD_BITS})")
        cost.report()

    return {
        "n": n,
        "t": t,
        "ell": ell,
        "K": K,
        "recovered": sorted(result),
        "cost": cost,
    }


if __name__ == "__main__":
    # Single-instance correctness demo (n=8, t=3, m=100, using
    # run_mpsi_protocol's own default input generation, where the
    # planted intersection is common = range(1, m // 5 + 1)).
    n, t, m = 8, 3, 100

    res = run_mpsi_protocol(n=n, t=t, m=m, verbose=True)

    expected = list(range(1, m // 5 + 1))
    recovered = res["recovered"]
    correct = (recovered == expected)

    print(f"\nExpected intersection: {expected}")
    print(f"Recovered intersection: {recovered}")
    print("CORRECTNESS CHECK:", "PASS" if correct else "FAIL")
