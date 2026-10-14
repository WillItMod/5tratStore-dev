# DEV compatibility matrix, 14 October 2026

All 14 authoritative Umbrel apps are inventoried. No app is fully qualified for MAIN. Fresh official AMD64 Umbrel guests and a native 5tratumOS guest now supply bounded lifecycle, persistence, authentication and utility evidence. Full browser, physical device, synchronized node and accepted mining share checks remain pending. The original matrix remains a timestamped catalogue snapshot; later observations below do not turn partial checks into full receipts.

DEV baseline: `ab235b3b2dfd0b441a19bd373117d651d2e75d80`. [The detailed JSON matrix](COMPATIBILITY-2026-10-14.json) binds current manifest, Compose and portable package hashes, every declared service image and resolved platform digest, native recipes, source/image provenance and individual OS/architecture checks. Its evidence IDs and SHA256 hashes refer to retained audit artifacts outside this repository.

## Exact platforms and evidence limits

- Umbrel 1.7.4, official commit `66d817ed00a77cca68a1a8d94dd56fe2b9fffb0d`. [Official release](https://github.com/getumbrel/umbrel/releases/tag/1.7.4).
- Umbrel 2.0.0, official commit `9298257b0e904ca8d8270b1702672666343f0b86`. [Official release](https://github.com/getumbrel/umbrel/releases/tag/2.0.0).
- Native stock 5tratumOS 0.8.31 remains the release target. Current private source HEAD is `4c0d5aab2e5ac15db2f92d1ba175e05f1ebc281c`; release-bundle equivalence is pending. The existing native host reports 0.8.32-review3 with MUX review6 and retains unrelated work.
- Required image architectures are linux/amd64 and linux/arm64. Both amd64 VMs were inspected through authenticated access and register all 14 apps; prior state is AxeBC2 ready and the other 13 stopped. These observations are not fresh install/update qualification for this candidate. Isolated copies are required. No complete Umbrel ARM64 hardware target is available.
- Both exact AMD64 releases publish versioned ISOs and compressed disk images under `https://download.umbrel.com/release/<version>/`, with `SHA256SUMS` linked in their GitHub release bodies. Both compressed downloads and decompressed raw payloads now match the published checksums. Fresh VM boot and actual OS checks remain pending. Embedded installer images do not fetch a newer OS. The JSON records expected ISO/compressed/raw hashes.
- App parser/lifecycle contracts match 1.7.0 through 1.7.4. The 1.7.4 changes concern Tor images. This source comparison does not prove equivalent kernels, Docker, ingress or runtime behavior.
- Umbrel 1.7 inherits its real app-proxy sidecar from the OS; Umbrel 2 removes that service and uses the in-process gateway. The app registry audit covers declared application images; the inherited platform sidecar still needs actual OS checks.

## Later owned-lab observations

Task-owned Proxmox VMs 622 and 623 boot the checksum-verified official Umbrel 1.7.4 and 2.0.0 images; VM624 runs the verified public native 5tratumOS v0.8.31 payload on supported Debian13. Their x86-64-v2-AES CPUs have no AVX, AVX2 or BMI2. Router621 isolates the lab from production private networks. Existing VMs110/113 and host10.10.10.235 were preserved by this task.

Both Umbrel versions reproduced root-owned data mounts in AxeBench/AxeLive: profile/licensing errors and preferences lost after restart. Umbrel1.7 also reproduced AxeMIG's shared `server` hostname resolving other utilities. [DEV recipe PR60](https://github.com/WillItMod/5tratStore-dev/pull/60), head `d2babe9340097675a5d51be5b2ae0dc053bc999f`, fixes directory ownership without changing child files and uses AxeMIG's unique container name. Normal updates report revisions `4.0.28-dev.1`, `1.4.2-dev.1` and `0.1.21-dev.1`; original data and image identities survived restart/update on both guests. The integrated suite passed93 tests without skips. Bounded MIG copy/move/Undo, Bench profile operations and scoped Fumbrel repair/restore also passed. Interactive browser, hardware and real database migration qualification remain separate.

Native624's unmodified Bench/Live/MIG recipes passed191 bounded checks with persistent data, normal Off-update behavior and authenticated gateways. Native already creates the Bench/Live mounts as UID1000. Fumbrel was never installed or started there and remains Umbrel-only. The original published Fumbrel0.1.0 recovery bundle can remove the new utility hooks, so utility release awaits a matching reviewed Fumbrel catalogue.

PowPow's original relative `postgres/init` files are omitted by the native importer. A recipe candidate placing unchanged SQL under `data/postgres-init` initialized nine PostgreSQL tables on native624 and both official Umbrel versions; native normal stop retained its database. Review then found that ordinary Umbrel updates omit `data/` too. Fresh-install success therefore does not qualify upgrades. Missing-only seed delivery via update-whitelisted metadata and a startup hash guard is under review; no existing database is rewritten and no PowPow MAIN pass is claimed.

The BCH2 and XEC portable source candidates also built on native624 without AVX/AVX2/BMI2. Actual-source SHA256 vectors and final binary guards passed; both resulting executables returned zero for network-disabled `--help`. This proves the tested local CPU paths, not equivalence to separately published images or mining shares. DEV main later advanced to `5783f80763610b3b25817af9a85fbbdcb325d84f` through [PR59](https://github.com/WillItMod/5tratStore-dev/pull/59), publishing BCH2 `0.2.0.12-dev` / portable pool `0.1.34-dev`; the original matrix versions and CPU blocker entries below describe the earlier snapshot.

The Mac mini chat separately reports OS0.8.32 and MUX0.9.76 releases with recovered layouts retained on10.10.10.235. The user specifically requires preservation of Claude's visual layouts and code fixes. Runtime/source/backups are being compared with the final merged release before further OS/MUX work. Earlier native v0.8.31 lab checks do not automatically qualify v0.8.32.

`later_owned_lab_observations` in the JSON binds these reports to retained artifact hashes. All full-readiness cells remain pending; no application was promoted to MAIN by this task.

## Original catalogue snapshot

| App | Package version | Published image graph | Umbrel 1.7.4 | Umbrel 2.0.0 | Native 0.8.31 | Bounded local ARM64 evidence |
| --- | --- | --- | --- | --- | --- | --- |
| 5tratSmack | `0.11.21` | amd64, arm64 | Pending | Pending | Pending | None |
| AxeBCH2 | `0.2.0.11-dev` | amd64, arm64; CPU blocker | Pending | Pending | Pending | None |
| AxeBench (Dev) | `4.0.28-dev` | amd64, arm64 | Pending | Pending | Pending | 20 HTTP checks; restart/recreate/data retained |
| AxeLive (Dev) | `1.4.2-dev` | amd64, arm64 | Pending | Pending | Pending | 13 HTTP checks; restart/recreate/data retained |
| AxeMIG | `0.1.21-dev` | amd64, arm64 | Pending | Pending | Pending | 17 HTTP + 155 migration/Undo checks |
| AxeBC2 | `0.1.22-dev` | amd64, arm64 | Pending | Pending | Pending | None |
| AxeBCH | `0.9.26-dev` | amd64, arm64 | Pending | Pending | Pending | None |
| AxeBTC | `0.7.82.17-dev` | amd64, arm64 | Pending | Pending | Pending | None |
| AxeDGB | `0.9.189-dev` | amd64, arm64 | Pending | Pending | Pending | None |
| FracAttack | `0.1.11` | amd64, arm64 | Pending | Pending | Pending | None |
| Fumbrel | `0.1.0-dev` | amd64, arm64 | Pending | Pending | N/A, Umbrel only | None |
| PowPow | `0.2.37-dev` | amd64, arm64 | Pending | Pending | Pending | None |
| AxePPC | `0.2.37-dev` | amd64, arm64; local node builds passed | Pending | Pending | Pending | Offline Peercoin genesis/restart; graceful exit |
| AxeXEC | `0.1.24-dev` | amd64, arm64; CPU blocker | Pending | Pending | Pending | None |

Every applicable cell covers amd64 and arm64, with separate pending lifecycle, persistence, authentication, network and functional checks. Mining apps also require the synchronized node, pool and accepted-share path. Published image availability does not prove CPU suitability or a complete application graph. The catalogue has 82 applicable OS/architecture targets; native diagnostics adds two. None has a full current receipt.

AxeBench, AxeLive and AxeMIG passed 50 total direct-service HTTP checks on native ARM64, with bounded restart, recreation and retained disposable data checks. Gateway authentication, fixed catalogue networks and OS lifecycle were excluded. No real supported test miner was supplied for AxeBench/AxeLive. The initial AxeMIG HTTP run excluded the Docker socket. A separate exact-image run with a real Docker socket passed 155 function checks: simulation, copy, move, streamed logs, history, Undo, wallet/config/cookie exclusion, target-byte restoration and requested stop/restart behavior. Its fixtures contain small byte sequences rather than synchronized databases. UI discovery, USB operations, browser confirmations and OS authentication/install/update remain pending. There is no dry-run API or running-app refusal; simulation is the supported rehearsal and migrations stop selected projects. Undo leaves the restored target stopped. AxeBench reports `v4.0.28` while its package/image tag is `4.0.28-dev`; this is an observed difference, not a confirmed compatibility defect.

## Confirmed blockers and DEV candidates

AxeBCH2: `ghcr.io/willitmod/axebch2-ckpool:0.1.33-dev` resolves to index `sha256:23aea1aa3ceb86885c64562a1eba055b85e1758fea0ea6a4cd3a59d86f254763` and amd64 child `sha256:e100e9f3f69f7d38622a768a39109cc04944f292281b27d1c84ae096cbb496f6`. The pool selects an unconditional AVX2 SHA256 path, incompatible with the Umbrel 2.0 VM CPU without AVX/AVX2. Extracted ELF SHA256: `19b124c7eda7bb0e0c8990284f53f1fac0d46b02f9d75bc5b3bd24c410335d55`.

AxeXEC: `ghcr.io/willitmod/ecash-ckpool-solo:18b38ad` resolves to index `sha256:a719874a1c2e2e017c0904a0972d30047a632e3b65da5b7307b8fd38a217a520` and amd64 child `sha256:b882ad0c2465e228556ac54b1de681b66febe12fa8c1bbd8625930587ebdd133`. The pool selects an unconditional AVX2 SHA256 path, incompatible with the Umbrel 2.0 VM CPU without AVX/AVX2. Extracted ELF SHA256: `9f59bd595632fc82ed3933c48a87644e980d8fa2b39340d874e35638f87b93d7`. Its one-block and multi-block paths execute AVX/AVX2 and BMI2 instructions without CPU dispatch.

Portable [AxeBCH2 candidate PR #8](https://github.com/WillItMod/AxeBCH2_Build/pull/8), commit `c0f61fcf52bd8be6782fc1a8f81ad6ebb681e6a5`, and [AxeXEC candidate PR #1](https://github.com/WillItMod/ecash-ckpool-solo-docker/pull/1), commit `01fc6de76b7436718d3ef8e5f2e4cabd97870502`, passed complete ARM64 OCI builds, real-source SHA256 vectors, final symbol guards and network-disabled executable startup. Native AMD64 and ARM64 CI builds and executable startup now pass for both candidates. Actual OS/application/share acceptance remains pending. The initial BCH2 AMD64 emulated build hit a Jansson configure issue; native Forge comparison is in progress. No published image, catalogue pin or MAIN promotion has changed.

The shared BTC/BC2/FracAttack `docker-ckpool-solo:590fb2a` and BCH pool have a byte-identical scalar SHA256 path in static binary inspection. 5tratSmack also uses a scalar SHA path. PowPow has a CPU-guarded accelerated path with a baseline fallback. The inspected AxeDGB native hash library contains no AVX/BMI instructions. These are static observations of the exact recorded binaries, not normal mining or full OS readiness.

Fumbrel is intentionally Umbrel-only. Native exclusion DEV draft PR #48 addresses its native import and diagnostics-port conflict. Local regressions pass; deployment and release acceptance are pending. Native N/A is a scope decision, never a successful native runtime result.

AxePPC builds its Peercoin node on the host. It selects Peercoin `0.15.1ppc`, archive build `1af7509666a7`, for x86_64-linux-gnu or aarch64-linux-gnu. The exact recipe now builds on AMD64 and ARM64. Both downloaded archives match the official release digests, and their node binaries match the resulting images byte for byte. Offline mainnet genesis startup, restart, config/genesis-file preservation and graceful exit passed on native ARM64 and emulated AMD64, reporting `v0.15.1.0 Anisoptera`. Actual OS builds, normal networking and synchronized mining remain separate requirements. Redis has no persistent mount; its statistics behavior after recreation needs acceptance.

## Per-app images and required functional checks

The JSON contains full immutable index and platform digests for every declared service image. Exact recipe references follow. Mutable tags must use their recorded digest for a test and be rechecked before installation. Built image revisions, current source HEADs and public release references remain separate observations.

### 5tratSmack (willitmod-dev-5tratsmack)

Package `0.11.21`; display version pending actual runtime observation.

- `init_permissions`: `alpine:3.22.1@sha256:4bcff63911fcb4448bd4fdacec207030997caf25e9bea4045fa6c8c44de311d1`.
- `p2p-helper`: `ghcr.io/willitmod/5tratsmack-upnp:0.11.1@sha256:c85d527b8a12007be2565b200b99dfe46781ddaa773831852414d2cc5ad041d0`.
- `node-a`: `ghcr.io/willitmod/5tratsmack-core:0.11.2@sha256:7bf02513144c7a157965fb8e9ad5865f5e84fa679afa7cb61fc0a8e140a40070`.
- `swap`: `ghcr.io/willitmod/5tratsmack-kdf:0.11.17-rc.99a34a0ef5f5@sha256:c3ce7e638bdf55710fbfb607145d76c7d6e00b81a35e4c843645d9815f862087`.
- `ckpool`: `ghcr.io/willitmod/5tratsmack-ckpool:0.11.3-rc.a992f40e96d4@sha256:95a1a5f343d579206a0f8bb3c961cafa7500b5d487211a0cfb7b989cf34b895e`.
- `app`: `ghcr.io/willitmod/5tratsmack-app:0.11.21@sha256:09f3dc1eea85942781e4127b6d8836c32c7fa61a0a45cbffb99b40509c38e3bb`.

Required functional acceptance:

- Node RPC 57576 verifies canonical checkpoint height 300 and hash, main-chain anchors and non-IBD readiness before mining
- P2P helper state updates without preventing startup indefinitely when router UPnP is unavailable; node peers discovered from configured seeds
- CKPool validates configured payout, activation height 1000 and accepted share on 57557; worker identity and block coinbase outputzero payout proof
- Encrypted wallet create/restore/backup and recovery file handling with disposable isolated wallet; never transact existing wallets
- Swap control 7784 reads actual readiness; isolated trade wallet/network and public tape distinction; exercise prepare/review/cancel and uncertain-broadcast recovery using mocks/disposable funds only
- App 21226 opens through gateway, self-restart/updater flags remain off, unsupported OS update proxy is displayed accurately on Umbrel
- Preserve node/wallet/pool/UI/P2P/swap/updater state and exact current images across update/restart; direct/MUX and safe retention support with OS >= 0.8.25

App-specific limits: FIVETRAT_OS_UPDATE_PROXY_BASE targets native 5tratumOS host; portable Umbrel behavior must be verified. Pool log retention described by release requires native OS extension>=0.8.25; Umbrel equivalent is not established by packaging smoke. Wallet/swap functional acceptance must use isolated state, not existing funds.

### AxeBCH2 (willitmod-dev-axebch2)

Package `0.2.0.11-dev`; display version pending actual runtime observation.

- `init_permissions`: `alpine:3.22.1`.
- `app`: `ghcr.io/willitmod/axebch2-app:0.2.0.11@sha256:ec45d7191eb6eb378d71b84f30aaf9133911e53045c0272afba2161a2b45f2ad`.
- `bch2`: `ghcr.io/willitmod/axebch2-node:0.1.33-dev`.
- `ckpool`: `ghcr.io/willitmod/axebch2-ckpool:0.1.33-dev`.

Required functional acceptance:

- BitcoinCashII RPC connects on 8342 with expected mainnet chain and checkpoint; existing shadow-chain/resync/reindex markers remain effective
- CKPool getblocktemplate path and stratum accepted share on 9265, correct BCH2 worker/payout shown
- Existing Core tree ownership and file bytes unchanged by permission initializer; safe UI settings write retains existing owner
- Exact BCH2 active-chain block and coinbase payout proof; direct/MUX identity, best-share and block-alert proof withdrawal
- Run pool on actual target CPU; published linux/amd64 alone does not settle historical N3450 illegal-instruction issue

App-specific limits: Docker socket mount allows in-app restart; APP_SELF_RESTART_ENABLED=1 and APP_COMPOSE_PROJECT supplied by host. Test restart only on disposable installation. Confirmed published amd64 CKPool AVX2 incompatibility on the non-AVX2 VM. Complete ARM64 OCI build, actual-source SHA vectors, symbol guards and network-disabled executable --help passed. Native AMD64 and ARM64 CI builds/startup passed; exact-OS/full mining acceptance pending.

### AxeBench (Dev) (willitmod-dev-axebench)

Package `4.0.28-dev`; locally observed display `v4.0.28`.

- `server`: `ghcr.io/willitmod/axebench:v4.0.28-dev`.

Required functional acceptance:

- Authenticated page and API load; record backend/frontend versions and verify their approved relationship to package 4.0.28-dev (observed backend v4.0.28)
- Disposable/mock miner discovery and bounded offline scan; fleet status/cards recover from transient unavailable device
- Saved profiles, benchmarks and schedules survive service restart/update under /data
- Benchmark/device-control apply/reset only against a dedicated test miner with saved original settings; verify cancel/timeout and restore

### AxeLive (Dev) (willitmod-dev-axelive)

Package `1.4.2-dev`; locally observed display `v1.4.2-dev`.

- `server`: `ghcr.io/willitmod/axelive:v1.4.2-dev`.

Required functional acceptance:

- Authenticated page loads, app 1.4.2-dev and settings under /data persist
- Read-only discovery and miner telemetry with disposable/mock endpoints; cancel scan while an offline IP is slow
- Thermal/fan safety and Nano3/3S model exercise against simulator or dedicated miner; retain actual miner settings
- Restart/update preserves saved fleet, fan-learning and thermal governance state; offline devices report unavailable and return when reachable

### AxeMIG (willitmod-dev-axemig)

Package `0.1.21-dev`; locally observed display `0.1.21-dev`.

- `server`: `ghcr.io/willitmod/axemig:0.1.21-dev`.

Required functional acceptance:

- Authenticated page plus JSON /api/health; unknown API returns JSON 404 rather than HTML success
- Docker socket read access and discovered source/target effective bind mounts including node image family recognition
- Disposable source/target chain directories: supported simulation, copy/move, streamed progress/report and Undo retain prior target bytes; verify intended stop/restart choices
- Wallet/config/cookie/secrets are excluded; selected running projects stop before migration and restart according to UI choices; Undo restores target bytes and leaves target stopped; exact helper image matches app 0.1.21-dev
- USB/helper discovery fails with clear reason when unmounted/unavailable; no existing node-data migration for acceptance

App-specific limits: Migration functional tests must use disposable dirs and stop affected test containers; never move existing chain data.

### AxeBC2 (willitmod-dev-bc2)

Package `0.1.22-dev`; display version pending actual runtime observation.

- `init`: `alpine:3.22.1@sha256:4bcff63911fcb4448bd4fdacec207030997caf25e9bea4045fa6c8c44de311d1`.
- `btc2d`: `ghcr.io/willitmod/bitcoinii-core:31.1.0-rc.cdf44542dde2@sha256:8875917ece57668fe9925d40a256ce8d429a3071511bb555d4ace1fa4370afc6`.
- `ckpool`: `ghcr.io/willitmod/docker-ckpool-solo:590fb2a@sha256:8a9a7f10c8138d0f55533132ee7710a06715a42a49f75efb39be3350ada4fa6e`.
- `app`: `ghcr.io/willitmod/axebc2-app-umbrel-dev:0.1.22@sha256:bfb899d13f063b46d95e6aa70ea5edb8596b61a8e3d2967b0dad2499627cbdb0`.

Required functional acceptance:

- Umbrel renders template/hooks without /etc/5tratumos/build.json; native recipe checks actual OS >=0.7.12 before persistent writes
- Core 31.1 RPC, canonical checkpoint and chainwork; mandatory migration markers and full reindex safeguards retained
- CKPool stratum subscribe/authorize/notify/accepted-share submit on 2345, matched worker and correct payout
- Stop/start/reboot and update preserve exact local bind volume paths, wallet/config bytes and completed migration record
- Read-only pool config and file configs reject writes and missing sources; no rollback below persistent Core 31 policy; direct/MUX stats, best share and block proof

App-specific limits: Separate native Compose and generated Umbrel template/hooks. Inspect both; passing native Compose alone does not qualify Umbrel. Native OS build-file config is required; Umbrel template deliberately omits it.

### AxeBCH (willitmod-dev-bch)

Package `0.9.26-dev`; display version pending actual runtime observation.

- `init`: `alpine:3.22.1`.
- `bchn`: `ghcr.io/willitmod/bitcoin-cash-node:v29.0.0-wm3`.
- `ckpool`: `ghcr.io/willitmod/wim-solo-ckpool:0.8.3-rc1-590fb2a`.
- `app`: `ghcr.io/willitmod/axebch-app-umbrel-dev:0.9.26@sha256:394297a80226096657253df460c69f5945c270a56c01aa39f57c98dde3ef3824`.

Required functional acceptance:

- BCHN v29 RPC getblockchaininfo/getblocktemplate, correct BCH network and configured payout address validation
- CKPool stratum subscribe/authorize/notify/accepted-share submit on 4567, pool API and matching worker UI
- Preserve legacy or CashAddr payout and current miner difficulty, Bitcoin.conf, chain and wallets through update/restart
- Exact active BCH block hash and payout proof; direct/MUX mixed identity, best-share and browser block-alert retraction on unavailable proof
- Local regression of best-share tracker startup and ownership-safe settings save

### AxeBTC (willitmod-dev-btc)

Package `0.7.82.17-dev`; display version pending actual runtime observation.

- `init`: `alpine:3.22.1`.
- `bitcoind`: `ghcr.io/willitmod/axebtc-bitcoind-switch:0.7.44`.
- `ckpool`: `ghcr.io/willitmod/docker-ckpool-solo:590fb2a`.
- `app`: `ghcr.io/willitmod/axebtc-app-umbrel-dev:0.7.82.17@sha256:21334b67d803987a3ae4e79242ba2d74da0415d22e786783c73723a460d9c174`.

Required functional acceptance:

- RPC getblockchaininfo/getnetworkinfo and correct selected Core or Knots binary; verify no accidental backend switch on upgrade
- Synchronized node getblocktemplate, CKPool stratum subscribe/authorize/notify/submit with accepted share on 7890, matched worker shown in UI
- Existing payout, pool difficulty, Bitcoin config, chain and wallets survive app restart and update
- Direct versus MUX worker identity, accepted-share estimates and stale telemetry labels; best-share exact records and active-chain coinbase proof
- Pool log retention capability must report supported state or a precise unavailable reason on each OS; browser block acknowledgement independent of MUX/OS

### AxeDGB (willitmod-dev-dgb)

Package `0.9.189-dev`; display version pending actual runtime observation.

- `init_permissions`: `alpine:3.22.1`.
- `perm_watchdog`: `alpine:3.22.1`.
- `init`: `ghcr.io/willitmod/axedgb-init:0.9.181-dev`.
- `dgbd`: `ghcr.io/willitmod/axedgb-core:9.26.6-dev.2@sha256:fb46ff018e701accf6630b65c4b33a7d9d24b5fa248c31122d2daa2503677039`.
- `postgres`: `postgres:16-alpine`.
- `miningcore`: `ghcr.io/willitmod/axedgb-miningcore:axedgb-0.8.10-r26`.
- `app`: `ghcr.io/willitmod/axedgb-app:0.9.189-dev@sha256:7ccaced7437bcb50b245a4cc65e3a3a22f7570c00e0a267d22e14e789e2e4416`.

Required functional acceptance:

- Core 9.26.6-dev.2 getblockchaininfo/getnetworkinfo/getblocktemplate with expected DigiByte chain and SHA256/Scrypt algorithms
- Postgres schema and Miningcore API accessible; accepted shares separately on SHA256 port 5678 and Scrypt5679 with correct worker and payout records
- Preserve miningcore.json/coins.json algorithm parameters, Postgres share history, node config/wallet/chain and permission model
- Restart node/pool/host and distinguish IBD or waiting state from mining-ready state
- DGB route-status labels reflect actual matched active routes, direct versus MUX identity, best shares and full active-chain block payout evidence

App-specific limits: Permission watchdog runs continually; test startup with existing restrictive tree without unwanted config changes. Miningcore and Postgres readiness is not the same as service-started.

### FracAttack (willitmod-dev-fracattack)

Package `0.1.11`; display version pending actual runtime observation.

- `init`: `alpine:3.22.1`.
- `fractald`: `ghcr.io/willitmod/fracattack-fractald:0.4.0`.
- `ckpool`: `ghcr.io/willitmod/docker-ckpool-solo:590fb2a`.
- `app`: `ghcr.io/willitmod/fracattack-app-umbrel-dev:0.1.11@sha256:fffd78f12ca68f6f5a2565e6c4ca3f2657c7b916b0cbdffa60261c64d85b6830`.

Required functional acceptance:

- Fractal0.4.0 RPC with expected chain and consensus-fixed binary, synchronized getblocktemplate path
- CKPool accepted share on 7891 with correct configured payout and miner identity
- App dashboard21225 assigned only by Umbrel proxy or native renderer, no duplicate app bind
- Existing payout override preserved rather than replaced by package default; chain/wallet/node selector/config persistent through restart/update
- Direct/MUX share estimates, partial sharelog/best-share state, verified block proof and retention reporting

### Fumbrel (willitmod-dev-fumbrel)

Package `0.1.0-dev`; display version pending actual runtime observation.

- `server`: `ghcr.io/willitmod/fumbrel:0.1.0-dev@sha256:a2f6f66a6227264ff88bd2053b36ea09ea55193b01730d467dfefd005165968b`.

Required functional acceptance:

- Umbrel authentication rejects logged-out access; separate Fumbrel session and origin/custom header guards
- Verify hostSSH public key, fixed hostdestination and bounded login/rate-limit/sessionexpiry without logging secrets
- Allowlisted disposable app scan; Repair preserves image/runtime contract and fixes only known packaging; unrecognized custom exports blocked
- Repair/update backs up recipe metadata modes/ownership, retains appID/data/.env/settings; higher installed versions cannot downgrade
- Serialize operations, retain checkpoint for partial failure and start only when opted in; stopped app restore backup is recoverable
- Compare bundled catalog snapshots to current versions and show exact installed/target; this0.1.0 release intentionally does not fetch latest packages
- Native 5tratumOS is outside Fumbrel function: exclude from native catalogue rather than bypass Umbrel guards

App-specific limits: Fumbrel is Umbrel-only by user scope; native exclusion DEV draft PR #48 is tested locally and not deployed/released.

### PowPow (willitmod-dev-powpow)

Package `0.2.37-dev`; display version pending actual runtime observation.

- `init_permissions`: `alpine:3.22.1`.
- `app`: `ghcr.io/willitmod/powpow-app:0.2.37-mux.88f8fc0af57e@sha256:59994fb26f1b9b1daf2bf25bf528d190d3beda89acd65d80bd674b49696bed8d`.
- `litecoin`: `ghcr.io/willitmod/powpow-litecoin:0.2.32-dev`.
- `dogecoin`: `ghcr.io/willitmod/powpow-dogecoin:0.2.26-dev`.
- `pool`: `ghcr.io/willitmod/powpow-pool:0.2.37-mux.88f8fc0af57e@sha256:fdedad44cc7c7700eb3043884979785a02d9915bf5a70c5b50d2f52f6ba758d8`.
- `postgres`: `postgres:16-alpine`.

Required functional acceptance:

- Litecoin and Dogecoin processes run as UID 1000 with writable preserved configs, expected chain identities and full-sync readiness
- Postgres merged mining schema, pool API 8001, LTC job plus Dogecoin auxiliary job path and accepted Scrypt share on 9555
- Actual merged mining block/auxpow proof where suitable testnet/regtest environment exists, otherwise record mainnet block find uncertainty
- Both chain trees/wallets/payouts/difficulty/allocation and share DB persist across restart/update; explicit wait-for-full-sync remains enforced
- Native OS extension sets proper node stop policy; direct/MUX identity and independently labelled LTC/DOGE block evidence

### AxePPC (willitmod-dev-ppc)

Package `0.2.37-dev`; display version pending actual runtime observation.

- `init`: `alpine:3.22.1`.
- `ppcd`: local Peercoin `0.15.1ppc`, archive `1af7509666a7`; target build pending.
- `redis`: `redis:7-alpine`.
- `pool`: `ghcr.io/willitmod/axeppc-pool:0.2.30`.
- `app`: `ghcr.io/willitmod/axeppc-app-umbrel-dev:0.2.37-mux.d59c9d2e2501@sha256:2b48e067bb72a243f5f12b8ff4fc1ba9bb2a8e84949d569fc71c92b00f853a0f`.

Required functional acceptance:

- Fresh actual host build resolves Peercoin0.15.1ppc build 1af7509666a7 for target amd64/arm64; archive download and executable startup succeed
- Peercoin RPC mainnet getblockchaininfo/getblocktemplate and correct POW-only payout; invalid dual network flags repaired without changing ordinary config
- CPS pool plus Redis startup and subscribe/authorize/notify/accepted-share submit on 8765; stats API and matching worker UI
- Repeated init preserves valid ckpool config bytes; legacy/invalid config backups keep exact bytes and saved payout wins
- Current CPS configs, Peercoin chain/wallet and UI state survive update; determine and record Redis volatile-stat semantics after restart

App-specific limits: Node service has build rather than image. Installation depends on host Docker builder and outbound GitHub/Debian networks. Redis has no persistent mount; restart loses its local writable-layer statistics on recreation. Determine impact on CPS accounting.

### AxeXEC (willitmod-dev-xec)

Package `0.1.24-dev`; display version pending actual runtime observation.

- `init`: `alpine:3.22.1`.
- `xecd`: `ghcr.io/willitmod/xecd-abc:0.33.4-nojemalloc-r1`.
- `ckpool`: `ghcr.io/willitmod/ecash-ckpool-solo:18b38ad`.
- `app`: `ghcr.io/willitmod/axexec-app-umbrel-dev:0.1.24@sha256:ae783ceb68f7768314b0eb8864ce1b22b188eb29e706d32e6f87575df9b58b7f`.

Required functional acceptance:

- Bitcoin ABC0.33.4 mainnet RPC and getblocktemplate at28337; existing bitcoin.conf remains usable
- eCash CKPool subscribe/authorize/notify/accepted-share submit on 4321 with supported legacy/CashAddr payout validation
- Restart cleans stale CKPool PID files and preserves current payout/difficulties, wallet, chain and existing config
- Direct/MUX identity, best-share retention and exact active XEC block/payout proof; browser alert retraction when proof unavailable

App-specific limits: Confirmed published eCash CKPool binary selects AVX2 SHA256 unconditionally. It cannot safely execute that path on the VM CPU without AVX/AVX2; exact replacement candidate and actual OS/share qualification remain pending.

## Native diagnostics appendix

5tratDiag `0.1.8` has a global manifest and is native-only. It is not a fifteenth Umbrel catalogue app. Native amd64/arm64 checks are pending; Umbrel targets are N/A. Its app image is `ghcr.io/willitmod/5tratumos-diagnostics:0.1.8` and support relay is `0.1.5-relay`, with immutable index and platform digests in the JSON. No private logs, identity keys or diagnostic payloads are included here.

- 5tratumOS portal authenticated proxy 21227 and paid annual/lifetime MUX entitlement; trial or unlicensed routes show appropriate welcome
- Support relay socket, licence/device public receipt and host diagnostic mounts exist with least privileges
- Bounded read-only redacted export excludes wallets/keys/passwords/config/process environments; mux snapshot fresh/stale status honest
- Review archive locally; submission requires explicit test authorization and dedicated support identity, expiry/lifecycle verified against staging
- Restart/update retains app exports/receipt state and uses unchanged device key on host; missing host logs or capture yields explicit warning

## Reproduce checks and qualify a candidate

With PyYAML installed, run static checks and regressions from this repository. The tests also use Node.js for the retained official parser fixture:

```sh
python3 scripts/umbrel_catalogue_contract.py --probe-exports
python3 -m unittest discover -s tests -p test_umbrel_catalogue_contract.py -v
```

After collecting actual OS observations, validate schema 2 receipts and independent immutable qualification locks. These example filenames describe the required captured artifacts; no actual OS pass receipts are supplied by this audit.

```sh
python3 scripts/umbrel_catalogue_contract.py \
  --receipts ./qualification/receipts.json \
  --qualifications ./qualification/locks.json \
  --evidence-root ./qualification \
  --target umbrel:1.7.4:amd64 --target umbrel:1.7.4:arm64 \
  --target umbrel:2.0.0:amd64 --target umbrel:2.0.0:arm64
```

Run each native architecture separately with its matching captured release and host root:

```sh
python3 scripts/umbrel_catalogue_contract.py \
  --receipts ./qualification/receipts.json \
  --qualifications ./qualification/locks.json \
  --evidence-root ./qualification \
  --native-root ./qualification/native-amd64 \
  --target 5tratumos:0.8.31:amd64

python3 scripts/umbrel_catalogue_contract.py \
  --receipts ./qualification/receipts.json \
  --qualifications ./qualification/locks.json \
  --evidence-root ./qualification \
  --native-root ./qualification/native-arm64 \
  --target 5tratumos:0.8.31:arm64
```

The native snapshot contains captured `apps/<native_id>/docker-compose.yml`, `bin/5tratumos`, `daemon/5tratumosd.py`, unchanged release `build.json` and observed `host.json`. Source-only recipes cannot qualify a materialized native deployment. The module docstring specifies the schemas.

The validator binds the exact candidate and OS/version/architecture, raw OCI index/platform/config ancestry, actual image/container inspect artifacts and hash-linked observed evidence. Local builds require the complete actual context, source archive, pinned base and resulting image identity. Historical smoke, stale files, missing evidence, untracked source, mutable recipe image tags and mutable build bases block qualification. This audit does not change recipes or image pins. Fumbrel native targets are N/A; a supplied native Fumbrel pass receipt is rejected.

These checks validate evidence coverage and metadata consistency. A reviewer must still verify the observations and every app-specific functional checklist item. The generic DGB accepted-share field alone does not establish both SHA256 and Scrypt acceptance.

Consider MAIN only after the exact candidate qualifies on all applicable platforms and DEV changes are reviewed. Current full OS readiness is zero and no MAIN promotion is recorded. Standalone 5tratMux packaging remains separate.
