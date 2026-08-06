# mPSI Artifact

Reference implementation and evaluation artifacts for the
zero-sharing based multi-party PSI protocol (Pi_mpsi), built on
Garbled Bloom Filters (GBF) and VOLE, supporting collusion resistance
up to `t <= n-1` without a trusted third party.

See **[ARTIFACT_APPENDIX.md](ARTIFACT_APPENDIX.md)** for the full,
step-by-step reproduction guide covering all parts below.

Requires Python 3.12.0 and `numpy==1.26.2` (see `requirements.txt`),
matching the environment used to produce the paper's reported
numbers. Part 4 additionally requires a Linux environment with root
privileges, `iproute2`, and `iperf3`; it is not tied to a specific
distribution or version (we verified it on Windows via WSL2 running
Ubuntu 22.04.5 LTS).

## Contents

| Path | Part | Description |
|---|---|---|
| `protocol/mpsi_protocol.py` | 1 | Protocol implementation; runnable standalone for a single instance. |
| `protocol/mpsi_batch_test.py` | 2 | Batch correctness test across multiple universe sizes. |
| `benchmarks/online_cost_model.py` | 3 | Online computation cost, communication volume, and analytical LAN/WAN total time (Table V/VI, Figure 5(a)-(c)). |
| `benchmarks/party_scalability_model.py` | 3b | Same, sweeping party count `n` up to 100 (Figure 5(d)-(f)). |
| `network/` | 4 | Real (tc/netns + iperf3) network measurement, validating Part 3/3b's analytical LAN/WAN model. |

## Quick Start

```bash
# Part 1: single protocol instance
python3 -m pip install -r requirements.txt
cd protocol
python3 mpsi_protocol.py

# Part 2: batch correctness test (imports and drives Part 1)
python3 mpsi_batch_test.py

# Part 3: online computation cost
cd ../benchmarks
python3 online_cost_model.py

# Part 3b: party-count scalability (Figure 5(d)-(f))
python3 party_scalability_model.py

# Part 4: network-emulated communication cost (Linux/WSL2, requires root + iperf3)
# 1160 MB matches the paper's largest LAN configuration (m=2^20, (n,t)=(15,14))
# -- avoid much smaller sizes; see ARTIFACT_APPENDIX.md Section 4.2.4
cd ../network
chmod +x *.sh
sudo ./run_comm_test.sh 0.01 10000 1160
```

Full details, expected outputs, and environment setup (including
WSL2 configuration) are in
[ARTIFACT_APPENDIX.md](ARTIFACT_APPENDIX.md).
