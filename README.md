# WillItMod Dev Community Store

## License (READ THIS FIRST)

This repository is source-available under the **Business Source License 1.1
(BSL 1.1)**. It is **NOT** an open source repository.

- No resale / no redistributed packages, stores, or release bundles without a
  commercial license: [COMMERCIAL_LICENSE.md](COMMERCIAL_LICENSE.md)
- No public forks, mirrors, or derivative redistributions without explicit
  written permission: [NO_FORK_POLICY.md](NO_FORK_POLICY.md)
- License: [LICENSE](LICENSE)
- Branding: [TRADEMARK.md](TRADEMARK.md)

Development/test app store for WillItMod apps.

## Apps

### Hosted / utility apps

- **AxeBench (Dev)** (`willitmod-dev-axebench`) - `4.0.28-dev`
- **AxeLive (Dev)** (`willitmod-dev-axelive`) - `1.4.2-dev`
- **AxeMIG** (`willitmod-dev-axemig`) - `0.1.21-dev`
- **Fumbrel** (`willitmod-dev-fumbrel`) - `0.1.0-dev`, Umbrel recovery only

### Node + solo pool / mining apps

- **AxeBTC** (`willitmod-dev-btc`) - `0.7.82.17-dev`
- **AxeBCH** (`willitmod-dev-bch`) - `0.9.26-dev`
- **AxeBCH2** (`willitmod-dev-axebch2`) - `0.2.0.12-dev`
- **AxeBC2** (`willitmod-dev-bc2`) - `0.1.22-dev`
- **AxeDGB** (`willitmod-dev-dgb`) - `0.9.189-dev`
- **AxePPC** (`willitmod-dev-ppc`) - `0.2.37-dev`
- **AxeXEC** (`willitmod-dev-xec`) - `0.1.24-dev`
- **5tratSmack** (`willitmod-dev-5tratsmack`) - `0.11.21`
- **FracAttack** (`willitmod-dev-fracattack`) - `0.1.11`
- **PowPow** (`willitmod-dev-powpow`) - `0.2.37-dev`

Use the app manifest in each app directory as the current source of truth for the store-visible version number.

The Umbrel catalogue contains 14 apps. 5tratDiag (`willitmod-dev-axediagnostics`,
`0.1.8`) is a separate 5tratumOS-only app in `willitmod-dev-5tratumos-diagnostics`;
it has no Umbrel manifest. Fumbrel is Umbrel-only and must not be imported into
the native 5tratumOS catalogue.

See [the current compatibility matrix](COMPATIBILITY-2026-10-14.md) for exact
image pins, architectures, static checks and runtime qualification status.

See [Umbrel 1.x and 2.0 compatibility](UMBREL-COMPATIBILITY.md) for the DEV
packaging changes, version table and verification scope.

For the broader cross-store version matrix and changelog pointers, see `https://github.com/WillItMod/AxeSuite/blob/main/docs/releases.md`.

## Quick setup (solo mining)

1. Install the app and let the node sync.
2. Point miners at:
   - BTC: `stratum+tcp://<host-ip>:7890`
   - BCH: `stratum+tcp://<host-ip>:4567`
   - BCH2: `stratum+tcp://<host-ip>:9265`
   - BC2: `stratum+tcp://<host-ip>:2345`
   - DGB (SHA256): `stratum+tcp://<host-ip>:5678`
   - DGB (Scrypt): `stratum+tcp://<host-ip>:5679`
   - XEC: `stratum+tcp://<host-ip>:4321`
   - PPC: `stratum+tcp://<host-ip>:8765`
   - 5TRAT: `stratum+tcp://<host-ip>:57557`
   - PowPow (LTC + DOGE merged mining): `stratum+tcp://<host-ip>:9555`

Hosted / utility apps such as AxeBench, AxeLive, and AxeMIG are dashboard/UI apps rather than miner endpoints.

## Address format notes

**BCH**
Many wallets (e.g. Trust Wallet) show Bitcoin Cash addresses in CashAddr format (`q...` / `p...`).

For maximum compatibility with ckpool/miners, use a legacy BCH Base58 address (`1...` / `3...`) as the payout address. If your wallet only shows CashAddr, convert it to legacy (or enable legacy display) before saving.

**XEC**
Many wallets show eCash addresses in CashAddr format (`ecash:q...` / `ecash:p...`).

Payout address supports both legacy Base58 (`1...` / `3...`) and CashAddr (`ecash:q...` / `ecash:p...`).

**DGB**
Use a DigiByte address (typically Base58 `D...` / `S...` or Bech32 `dgb1...`).

## Security / provenance

- BCHN runs from `ghcr.io/willitmod/bitcoin-cash-node:v29.0.0-wm3`.
- ckpool (XEC) runs from `ghcr.io/willitmod/ecash-ckpool-solo` (pinned by tag in `docker-compose.yml`).
- BTC node selector runs from `ghcr.io/willitmod/axebtc-bitcoind-switch` (pinned by version tag in `docker-compose.yml`).
- BC2 node runs from `ghcr.io/willitmod/bitcoinii-core` (pinned by version tag in `docker-compose.yml`).
- XEC node runs from `ghcr.io/willitmod/xecd-abc:0.33.4-nojemalloc-r1`.
- PPC builds the local `data/peercoind/Dockerfile` from the official Peercoin
  `0.15.1ppc` release archive for AMD64 or ARM64; it does not pull a published node image.
- Recipes orchestrate Docker images and app-specific build contexts. Versioned
  patches and local build inputs in each app directory are part of its package.
