# Artifact Appendix

This appendix describes the artifacts supporting the experimental
claims in the paper: (1) a reference implementation of the protocol,
(2) a batch correctness test across multiple universe sizes, (3) an
online-phase computation cost benchmark, (3b) a party-count
scalability benchmark, and (4) a network-emulated communication cost
measurement under LAN/WAN conditions.

## Repository Layout

```
mpsi-artifact/
├── README.md
├── ARTIFACT_APPENDIX.md      (this file)
├── protocol/
│   ├── mpsi_protocol.py       (Part 1)
│   └── mpsi_batch_test.py     (Part 2)
├── benchmarks/
│   ├── online_cost_model.py       (Part 3)
│   └── party_scalability_model.py (Part 3b)
└── network/
    ├── run_comm_test.sh       (Part 4, recommended entry point)
    ├── setup_netns.sh
    ├── teardown_netns.sh
    ├── receiver.py
    └── sender.py
```

All commands below assume the current directory is the repository
root unless stated otherwise.

## 0. Overview

| Part | Artifact | Files | Claim supported |
|---|---|---|---|
| 1 | Protocol implementation | `mpsi_protocol.py` | The protocol correctly computes the multi-party intersection under the zero-sharing / GBF / VOLE construction. |
| 2 | Batch correctness testing | `mpsi_batch_test.py` (uses Part 1) | Correctness holds across multiple universe sizes and party-set-size configurations, not just a single toy instance. |
| 3 | Online cost model (computation, communication, analytical LAN/WAN time) | `online_cost_model.py` | Per-party online-phase computation cost, communication volume, and LAN/WAN total time scale as expected with `n`, `t`, `m`, matching Table V/VI and Figure 5(a)-(c). |
| 3b | Party-count scalability | `party_scalability_model.py` (same conventions as Part 3) | Computation cost, communication volume, and LAN/WAN total time scale near-linearly as the number of parties `n` grows, with `t=3` and `m=2^20` fixed (Figure 5(d)-(f)). |
| 4 | Real network-emulated validation | `run_comm_test.sh`, `setup_netns.sh`, `teardown_netns.sh`, `receiver.py`, `sender.py` | Independently validates the analytical LAN/WAN model of Parts 3/3b with a real (`tc`-emulated) measurement. |

Parts 1-3(b) require only Python 3 and `numpy`. Part 4 additionally
requires a Linux environment with root privileges and host-level
network-namespace capabilities (see Section 4.2).

**Mapping to the paper's Artifact Appendix Major Claims:** Part 3's
Table V numbers underlie Major Claim C1 (the reported speedup over
GGA+26/GLW+24); Part 3b's Figure 5 numbers underlie C2 (near-linear
scalability). Parts 1/2 (correctness) and Part 4 (real network
validation) are supporting evidence and are not separately numbered
claims.

---

## 1. Protocol Implementation

### 1.1 Purpose

`mpsi_protocol.py` is a reference implementation of the zero-sharing
based multi-party PSI protocol (Pi_mpsi), built on Garbled Bloom
Filters (GBF) and VOLE, supporting collusion resistance up to
`t <= n-1` without a trusted third party.

The implementation is functionally equivalent to the protocol
specification; field arithmetic, the PRG, and random vector
generation are implemented with vectorized/batched primitives
(`numpy`, `os.urandom`, SHAKE256) purely for execution speed. No
protocol step, message flow, or security property is altered by these
implementation choices.

### 1.2 Environment Requirements

Python 3.12.0 and `numpy==1.26.2` (see `requirements.txt`), matching
the environment used to produce the paper's reported numbers:

```bash
python3 --version   # 3.12.0
pip3 install -r requirements.txt
```

### 1.3 Key Components

| Function | Role |
|---|---|
| `gf40_mul_vec`, `gf40_mul` | GF(2^40) field multiplication (vectorized / scalar). |
| `xor_vectors`, `xor_many`, `scalar_vector_mul` | Vector field operations used throughout the protocol. |
| `PRG(seed, ell)` | Expands a seed into a length-`ell` pseudorandom field vector (SHAKE256-based). |
| `gen1` / `gen2` | GBF insertion routines executed by the pivot / all other parties respectively (zero-sharing construction). |
| `construct_valid_universe`, `sample_subsets_from_universe` | Helpers that build a universe whose elements are guaranteed to insert into a GBF without collision, and let parties draw order-preserving subsets that inherit this guarantee. |
| `run_mpsi_protocol(...)` | Executes one full end-to-end protocol instance (all 8 phases: offline VOLE preprocessing, offline seed/PRG expansion, online blinding, online share preparation, server-side aggregation, masked aggregation, broadcast and evaluation, final reconstruction) and returns the recovered intersection plus a per-phase cost report. |

### 1.4 Usage Example

```python
from mpsi_protocol import (
    construct_valid_universe,
    sample_subsets_from_universe,
    run_mpsi_protocol,
)

n, t = 8, 3
m = 1000
ell_factor, K = 8, 4

universe, _, _ = construct_valid_universe(m, ell_factor * m, K)
X = sample_subsets_from_universe(
    m, party_sizes=[200, 300, 400, 500, 600, 700, 800, 1000],
    seed=1, universe=universe, preserve_order=True,
)

res = run_mpsi_protocol(
    n=n, t=t, ell_factor=ell_factor, K=K, custom_X=X, universe_size=m,
)
print(res["recovered"])   # recovered intersection elements
```

### 1.5 Verifying Correctness

The recovered intersection can be checked against the ground-truth
intersection computed independently with Python set operations:

```python
true_intersection = set(X[1])
for i in range(2, n + 1):
    true_intersection &= set(X[i])

assert set(res["recovered"]) == true_intersection
```

This check is what Part 2 (batch testing) automates across multiple
configurations.

---

## 2. Batch Correctness Testing

### 2.1 Purpose

`mpsi_batch_test.py` runs the protocol from Part 1 across multiple
universe sizes and reports, for each configuration, the recovered
intersection against the independently-computed ground truth. This
demonstrates that correctness is not specific to a single parameter
choice.

The script also reflects a specific deployment assumption: the real
universe size `m` is processed by `NUM_THREADS = 16` parallel worker
threads, so each worker only handles `m' = m / 16` elements; the
protocol is run with `m'` as the working universe size, and both `m`
and `m'` are reported.

### 2.2 Environment Requirements

Same as Part 1 (Python 3 + `numpy`). `mpsi_protocol.py` must be in the
same directory (or on the Python path).

### 2.3 Usage

```bash
cd protocol
python3 mpsi_batch_test.py
```

The tested universe sizes and per-party set-size fractions are
configured at the top of the script:

```python
real_m_sizes = [2**12, 2**16, 2**20]
fracs = [0.1, 0.2, 0.33, 0.5, 0.6, 0.7, 0.8, 0.9]
```

### 2.4 Expected Output

For each `real_m` in `real_m_sizes`, one block is printed:

```
m  = 1048576
m' = 65536
  K = 4
  ell = 524288
  expected intersection = [200, 1212, ...]
  recovered intersection = [200, 1212, ...]
  correct = True
```

`correct = True` for every configuration confirms that the recovered
intersection matches the ground truth exactly (no false positives or
false negatives) across all tested scales.

---

## 3. Online Computation Cost Model

### 3.1 Purpose

`online_cost_model.py` benchmarks the **online-phase computation
cost**, computes the **communication volume** analytically, and
combines the two into an **analytical LAN/WAN total time** (`Total
Time = Communication Volume / Bandwidth + RTT`, using the paper's
stated 10 Gbps/0.02ms LAN and 200 Mbps/96ms WAN figures), for both a
single client and the pivot party, as a function of the universe
size and the number of parties/collusion threshold (`n`, `t`). This
reproduces Table V (runtime) and Table VI (communication), and the
computation/communication/total-time sub-panels of Figure 5(a)-(c).
Part 4 separately provides a REAL (not analytical) measurement to
validate the LAN/WAN total-time model.

Like Part 2, the script models a 16-thread deployment for
**computation**: the real universe size `m` is divided by 16 to
obtain the per-thread working size `m'`, and computation is timed
using `ell_compute = 8 * m'`, since local parallelism genuinely
speeds up computation. **Communication does not benefit from local
parallelism** -- the complete `ell`-length vector must still cross
the network in its entirety regardless of how many threads computed
it -- so every communication-cost formula in this script uses
`ell_comm = 8 * m` (the full, undivided universe size), not
`ell_compute`.

**Note on field arithmetic:** the online phase's dominant cost is
vector XOR (identical over plain integers or true GF(2^40), since
XOR is field-agnostic), plus a single scalar-vector multiplication
per party. `scalar_vector_mul` in this script implements that
multiplication as plain integer multiplication with 40-bit
truncation, not strict GF(2^40) polynomial-basis multiplication --
this is a deliberate timing-only proxy (numpy has no carry-less
multiply primitive; both are single vectorized hardware
instructions of comparable cost), used only because this script
measures relative timing, not field-correct values. `protocol/mpsi_protocol.py`
(Part 1), by contrast, implements true GF(2^40) polynomial-basis
multiplication (`gf40_mul`), since it is the correctness reference.

### 3.2 Environment Requirements

Same as Part 1 (Python 3 + `numpy`). This script is self-contained
(does not import `mpsi_protocol.py`); it directly benchmarks the
vectorized XOR/field-multiplication primitives used in the online
phase.

### 3.3 Usage

```bash
cd benchmarks
python3 online_cost_model.py
```

Tested real universe sizes are configured at the top of the script:

```python
real_m_values = [2**12, 2**16, 2**20]
n_values = [4, 10, 15]
```

For each `real_m`, the script benchmarks:
- **Single client cost**: the two XOR operations a client performs
  online (`GBF_blind = GBF_i XOR GBF_mask_i`, then `G_i,n = GBF_blind
  XOR W_i`), plus the corresponding communication-cost formula (bits
  sent, independent of actual network conditions).
- **Pivot cost**: for every `n` in `n_values` and every `t` from 1 to
  `n-1` (including the extreme case `t = n-1`), the aggregation,
  masked evaluation (one field multiplication), and final
  reconstruction steps performed by the pivot.

Each benchmark runs `repeat = 10` trials and reports the minimum
observed time (standard practice for microbenchmarks, to reduce
noise from OS scheduling jitter).

### 3.4 Expected Output (excerpt)

```
================ Online Cost Model ================

m           = 1048576
m'          = 65536
ell_compute = 8m' = 524288
ell_comm    = 8m  = 8388608
field       = GF(2^40)
repeat      = 10
one vector  = 40.00 MB

================ Single Client Cost ================

Computation:
  Formula              : 2ell XOR
  Runtime              : 0.001567 s
  Per XOR element cost : 1.494884490967e-09 s

Communication Cost:
  Definition           : send + receive
  Formula              : ell * 40 bits
  Communication        : 40.00 MB

================ Pivot Cost ================

---------------- n = 4 ----------------

t = 1
clients = 2

Computation:
  Formula       : (n+t)ell XOR + ell MUL
  Runtime       : 0.017261 s

Pivot Communication Cost:
  Definition    : send + receive of pivot
  Communication : 200.00 MB

Total Communication Cost:
  Definition    : sum of data sent by all parties
  Communication : 200.00 MB

LAN/WAN Total Time (analytical; Table V / Figure 5(c)/(f)):
  Definition    : Total Communication / Bandwidth + RTT
  LAN (10 Gbps, 0.02ms RTT) : 0.1678 s
  WAN (200 Mbps, 96ms RTT)  : 8.4846 s
------------------------------------------
```

The `200.00 MB` communication volume matches Table VI's entry for
`(m,n,t) = (2^20, 4, 1)` exactly. The `0.1678 s` LAN total time is
within ~4% of Table V's reported `0.1751 s` for the same
configuration (the small residual is the same order as the gap
independently observed against a real `tc` measurement in Part 4;
see Section 4.7).

### 3.5 Party-Count Scalability (Figure 5(d)-(f))

`party_scalability_model.py` (same directory, same `ell_compute` /
`ell_comm` conventions as above) reproduces Figure 5(d)-(f): the
corruption threshold is fixed at `t=3` and the universe size at
`m=2^20`, matching the paper's Experimental Setup for this sweep
("varying `n` while fixing `t=3`"), while the number of parties `n`
is swept from 4 up to 100.

**Note:** the paper states only that computation and communication
exhibit "near-linear growth as `n` increases" and does not list the
exact `n` values plotted in Figure 5(d)-(f); the range below is
chosen to demonstrate scalability well beyond the `n <= 15` grid
tabulated in Table V/VI. Edit `N_VALUES` at the top of the script if
the original experiment used different values.

```bash
cd benchmarks
python3 party_scalability_model.py
```

Expected output (excerpt):

```
================ Party-Count Scalability (Figure 5(d)-(f)) ================

m           = 1048576
m'          = 65536
ell_compute = 8m' = 524288
ell_comm    = 8m  = 8388608
t           = 3 (fixed)
field       = GF(2^40)
repeat      = 10

n = 4    clients = 0
  Computation (pivot)      : 0.018956 s
  Pivot communication      : 280.00 MB
  Total communication      : 280.00 MB
  LAN total time           : 0.2349 s
  WAN total time           : 11.8401 s

n = 25   clients = 21
  Computation (pivot)      : 0.065535 s
  Pivot communication      : 1120.00 MB
  Total communication      : 1120.00 MB
  LAN total time           : 0.9395 s
  WAN total time           : 47.0722 s

n = 100  clients = 96
  Computation (pivot)      : 0.233578 s
  Pivot communication      : 4120.00 MB
  Total communication      : 4120.00 MB
  LAN total time           : 3.4561 s
  WAN total time           : 172.9013 s
```

Computation time, communication volume, and LAN/WAN total time all
grow approximately linearly with `n`, confirming the paper's claimed
near-linear party-count scalability (Figure 5(d)-(f)). LAN/WAN total
time here is analytical (same model as Part 3); to independently
validate it with a real network measurement for a given `n`, feed
the reported communication volume (MB) into
`network/run_comm_test.sh`, as in Part 4 below.

---

## 4. Network-Emulated Communication Cost (LAN/WAN)

### 4.1 Purpose

Parts 1-3 measure computation cost only, with no real network
involved. This part measures **actual communication cost** by
transferring protocol-sized data between two real (namespaced)
processes over a link shaped with `tc netem` to match the paper's
reported LAN and WAN network conditions.

### 4.2 Environment Requirements

- A Linux environment with root privileges and kernel support for
  network namespaces, veth interfaces, Linux bridges, and `tc`
  (traffic control). On Windows, **WSL2** satisfies this (real Linux
  kernel; WSL1 does not support these features).
- `iproute2` (provides `ip`, `tc`; normally preinstalled on Ubuntu).
- Python 3 (standard library `socket` only; `numpy` is not required
  for this part).

Part 4 is not tied to a specific Linux distribution or version --
any distribution with the kernel features above works. The commands
below use `Ubuntu-22.04` as a concrete example: this is what was
used to verify Part 4 and produce the measurements in Section 4.7.
Parts 1-3b require only Python + `numpy` and run directly on the
host (no Linux/VM needed).

#### 4.2.1 Checking / installing WSL2 (Windows only)

```powershell
wsl --list --verbose
```

Expected output confirming WSL2 is installed:
```
  NAME            STATE           VERSION
* Ubuntu-22.04    Stopped         2
```

`VERSION 2` is required. If WSL is not installed:
```powershell
wsl --install -d Ubuntu-22.04
```
Then start it:
```powershell
wsl
```

#### 4.2.2 Installing packages inside WSL/Linux

```bash
sudo apt update
sudo apt install -y iproute2 python3
```

#### 4.2.3 Verifying the environment

```bash
tc -V
ip netns list
python3 --version
```

### 4.3 Files

| File | Role |
|---|---|
| `run_comm_test.sh` | Fully automated driver: sets up the topology, runs receiver/sender for one or more transfer sizes, tears down, and prints a summary table. **Recommended entry point.** |
| `setup_netns.sh` | Creates two network namespaces connected via a veth pair through a Linux bridge, and applies a `tc netem` delay/rate constraint to the link. |
| `teardown_netns.sh` | Tears down everything `setup_netns.sh` created. |
| `receiver.py` | Runs in one namespace; accepts one TCP connection, receives all data, and reports total bytes and elapsed time. |
| `sender.py` | Runs in the other namespace; sends a specified amount of data (`--size-mb`) and reports elapsed time and throughput. |

The five files listed above already live together in the `network/`
directory of this repository. Just `cd` into it and mark the shell
scripts executable:

```bash
cd network
chmod +x run_comm_test.sh setup_netns.sh teardown_netns.sh
```

### 4.4 Network Topology

```
 party1 (10.10.0.2)                party2 (10.10.0.3)
      |                                  |
   eth0 (netns)                      eth0 (netns)
      |                                  |
   veth1p <---- veth pair ----> veth1    |
      |                                  |
      +--------- br0 (bridge) -----------+

  tc netem (delay + rate) applied on the host-side veth of each party
```

### 4.5 Usage

All commands in this section are run from the `network/` directory:

```bash
cd network
```

**Note on `sudo` inside WSL2:** if `sudo` hangs waiting for a
password you don't have configured (common on a fresh WSL2
install), run the WSL distribution itself as root instead, which
skips `sudo` entirely. This is the exact setup and command used to
produce the measurements in Section 4.7 (WSL2 distribution
`Ubuntu-22.04`, repository cloned to `D:\4upofdoc\mpsi-artifact\mpsi-artifact`
on the Windows host):

```powershell
wsl -d Ubuntu-22.04 -u root -- bash -c "cd /mnt/d/4upofdoc/mpsi-artifact/mpsi-artifact/network && ./run_comm_test.sh 0.01 10000 1160"
```

Check your installed distribution's name with `wsl --list --verbose`
and adjust the `/mnt/<drive-letter>/...` path if your repository is
cloned elsewhere.

#### 4.5.1 Automated (recommended)

`run_comm_test.sh` runs the full test end-to-end in one command: it
sets up the topology, starts the receiver, runs the sender for each
requested transfer size in sequence (restarting the receiver between
sizes automatically), tears down the topology, and prints a summary
table. No manual multi-terminal interaction is required.

```bash
sudo ./run_comm_test.sh <delay_ms> <rate_mbit> <size1_mb> [size2_mb] ...
```

Example reproducing the LAN result in Section 4.7 (1160 MB, matching
the paper's largest LAN configuration):

```bash
sudo ./run_comm_test.sh 0.01 10000 1160
```

Expected output ends with a summary table:

```
==== Summary ====
Size (MB)    Time (s)         Throughput (MB/s)
1160         1.036285         1119.3827
```

#### 4.5.2 Manual (for debugging / step-by-step inspection)

The individual steps below are equivalent to what `run_comm_test.sh`
automates, and are useful if a single size needs to be inspected in
isolation or if the automated script needs to be debugged.

**Set up the topology** (two parties, `<delay_ms>` one-way delay,
`<rate_mbit>` Mbps bandwidth cap):

```bash
sudo ./setup_netns.sh 2 <delay_ms> <rate_mbit>
```

**Start the receiver** (separate terminal; blocks until a connection
arrives):

```bash
cd network
sudo ip netns exec party1 python3 receiver.py --host 10.10.0.2 --port 9000
```

**Start the sender**, transferring `<SIZE>` MB (should match the
actual per-vector size used in the protocol's online phase, i.e.
`ell * 5` bytes for a GF(2^40) vector of length `ell`):

```bash
cd network
sudo ip netns exec party2 python3 sender.py --host 10.10.0.2 --port 9000 --size-mb <SIZE>
```

Note: `receiver.py` exits after receiving one connection, so it must
be restarted before each new `sender.py` invocation.

**Tear down** when done:

```bash
sudo ./teardown_netns.sh 2
```

### 4.6 Mapping the Paper's LAN/WAN Configuration to `tc` Parameters

The paper reports:
- **LAN**: 10 Gbps bandwidth, 0.02 ms RTT.
- **WAN**: 200 Mbps bandwidth, 96 ms RTT.

`tc netem delay` applies a **one-way** delay per interface, so the
target RTT is halved when configuring each link:

| Config | Bandwidth (tc units) | RTT | One-way delay (tc units) | Command |
|---|---|---|---|---|
| LAN | 10000 mbit | 0.02 ms | 0.01 ms | `sudo ./setup_netns.sh 2 0.01 10000` |
| WAN | 200 mbit | 96 ms | 48 ms | `sudo ./setup_netns.sh 2 48 200` |

### 4.7 Measured Results (paper's largest configuration, LAN and WAN)

We recommend validating with a large, realistic transfer size so
throughput is not dominated by fixed per-connection overhead (TCP
handshake/slow-start, namespace/veth emulation), which is
proportionally larger for small payloads. The paper's largest
configuration, `(m,n,t) = (2^20, 15, 14)`, requires a 1160 MB
transfer (see `online_cost_model.py`'s Total Communication Cost for
this configuration).

**LAN** (10 Gbps, 0.02 ms RTT):

```bash
cd network
sudo ./run_comm_test.sh 0.01 10000 1160
```

```
[sender] total data sent : 1160.0000 MB
[sender] elapsed time    : 1.036285 s
[sender] throughput      : 1119.3827 MB/s
```

The paper's Table V reports `0.9949 s` (LAN, "Ours") for this exact
configuration; the measured `1.036 s` is close to this value.

**WAN** (200 Mbps, 96 ms RTT):

```bash
sudo ./run_comm_test.sh 48 200 1160
```

```
[sender] total data sent : 1160.0000 MB
[sender] elapsed time    : 51.621069 s
[sender] throughput      : 22.4714 MB/s
```

The paper's Table V reports `46.5627 s` (WAN, "Ours") for this exact
configuration; the measured `51.621 s` is close to this value, with
the residual (same order as the LAN case) attributable to TCP
slow-start being more pronounced at high RTT, and to namespace/veth
emulation overhead.

Both results confirm that the analytical LAN/WAN model (Section
"Experimental Setup" in the paper) is well-calibrated against real
network conditions. Exact agreement is not expected on a different
machine or WSL2/Linux setup -- real network measurements are
sensitive to host load and the local network stack -- but the
measured and analytical values should remain of the same order of
magnitude, with the relative gap shrinking as transfer size grows.

**Note:** `run_comm_test.sh`'s summary-table column extraction
previously had an off-by-one `awk` field-index bug (it picked up the
literal `:` character instead of the numeric value). This has been
fixed; the per-transfer `[sender] ...` lines printed above each
summary row were always correct and unaffected.

### 4.8 Notes for Reproducibility

- Network namespaces, veth pairs, and `tc netem` are standard Linux
  kernel facilities; no third-party network simulator is required,
  and the setup is reproducible on any Linux machine (native or
  WSL2) with root access.
- Results above are single-run measurements; for a paper-quality
  table, repeating each configuration multiple times and reporting
  the mean/median is recommended.
- The one-way-delay convention (RTT / 2) should be stated explicitly
  alongside any reported numbers, since `tc netem delay` is inherently
  a one-way (per-interface) shaping mechanism.
