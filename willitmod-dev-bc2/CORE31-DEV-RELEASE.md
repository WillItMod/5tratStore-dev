# AxeBC2 0.1.11 / Core 31 DEV release gates

The DEV recipe maps store ID `willitmod-dev-bc2` to canonical 5tratumOS app ID
`axebc2`. Its preserved data path is `/var/lib/5tratumos/apps/axebc2`, matching
the `app_id` in `.5tratumos-rollback-policy.json`. The protected consensus
rollback floor remains `0.1.10`; this application-only maintenance release must
not change that floor or repeat the completed Core 31 reindex.

Every host bind uses `create_host_path: false`. The recipe contains the empty
runtime directories that 5tratumOS stages before Compose validation, so Docker
must not silently create a misspelled or missing source path.

The digest-pinned generic Alpine init container installs `jq` and
`gettext-envsubst` from Alpine 3.22 repositories at startup. This remains a
network-availability dependency, but an install failure occurs before any
persistent app-data or node-data mutation and prevents Core from starting. A
future dedicated, independently built and digest-pinned init image could remove
that availability dependency; it is not introduced in this release.

## Immutable release inputs

The application is pinned to
`ghcr.io/willitmod/axebc2-app-umbrel-dev:0.1.11-candidate.ecf6e2c8cfd0@sha256:23a7962e223da5549eba52697c6f4cfa16ab74cba935c68c48148a4c515302b4`,
built from source revision `ecf6e2c8cfd0e42ea53d3cc146b18cd6d4c4b563` by
candidate workflow run `33895447789`.

The already accepted BitcoinII Core 31 image is unchanged and remains pinned
twice to
`ghcr.io/willitmod/bitcoinii-core:31.1.0-rc.cdf44542dde2@sha256:8875917ece57668fe9925d40a256ce8d429a3071511bb555d4ace1fa4370afc6`.
Its source revision is `cdf44542dde255648008249d187fafc15f3a2f09`, built by
candidate workflow run `33675068951`. Both the DEV finalizer and validator must
reject any change to that tag, digest, source revision, or the two-reference
invariant.

`scripts/finalize-axebc2-0.1.11-dev.sh` accepts the exact application index
digest once the candidate is available. Before editing Compose, it anonymously
verifies the application and retained Core tag resolutions, amd64 and arm64
manifests, and digest pulls. It atomically replaces only the application
sentinel and emits an evidence template bound to both exact source revisions.
CI accepts either the complete one-sentinel prefinalization state or the complete
immutable finalization state; partial or mixed states fail.

The test platform remains fixed to the published DEV-only
[`v0.7.12-dev`](https://github.com/WillItMod/5tratum/releases/tag/v0.7.12-dev)
bundle with SHA-256
`11a35e68ab169eb0446485992a57b33fae018a92020b7d86bbf9a005571377af`.
The finalizer writes that exact value into the acceptance template; it is not a
free-form observation. MAIN promotion rejects evidence from a different OS
bundle even when the displayed version string is the same.

The store validator exercises a pinned copy of the relevant 5tratumOS
materialization contract from platform commit
`4f979cb9541622c1fdccdf43b8a885bbf845ba38`: it consumes `app_proxy`, publishes
the manifest port on the resolved app service, removes the legacy shared
network, and normalizes restart policies. Final DEV acceptance must use the real
platform materializer and validate its generated Compose file before containers
are started.

## Retained Core 31 acceptance

The unchanged Core image completed its mandatory full reindex and protected
migration-marker checks on `10.10.10.235` using the pinned 5tratumOS bundle on
2026-09-04. A subsequent full app restart did not repeat the reindex. Core
reported version `310100`, passed level-4 `verifychain`, matched the official
BitcoinII explorer, maintained at least three outbound Core 31 peers, and had no
competing valid tip at or beyond ShockWave checkpoint height `57,752`.

That evidence remains valid for the unchanged Core image, but it does not replace
live acceptance of the new application candidate.

## Required 0.1.11 live DEV acceptance

Exercise installation and update on DEV. Confirm that the existing node chain,
migration markers, pool configuration, payout address, and rollback policy are
preserved; no blockchain reindex is started; sync, Explorer, private UI data,
and the non-submitting Stratum probe work; and telemetry, P2P port, and NAT-PMP
controls remain unchanged.

Specifically verify the payout fix with Core-accepted mainnet `1...`, `3...`, and
`bc1...` address families. An invalid or wrong-network address and an RPC-not-ready
condition must both leave the saved pool configuration and payout history
unchanged. Any legacy pending-validation record must be rechecked at the bounded
interval and resolve to either validated or a definitive warning. Confirm that a
MAIN/stable channel value no longer displays the misleading payout warning, and
that the one-time conditional CKPool `/www` ownership repair makes existing
sharelog paths writable by uid/gid 1000 without rewriting a current pool config.
Complete `DEV-ACCEPTANCE-EVIDENCE.json` only after those live checks pass.
