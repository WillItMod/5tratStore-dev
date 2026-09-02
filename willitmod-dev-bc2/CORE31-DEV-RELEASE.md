# AxeBC2 Core 31 DEV release gates

The DEV recipe maps store ID `willitmod-dev-bc2` to canonical 5tratumOS app ID
`axebc2`. Its preserved data path is `/var/lib/5tratumos/apps/axebc2`, matching
the `app_id` in `.5tratumos-rollback-policy.json`.

Every host bind uses `create_host_path: false`. The recipe contains the empty
runtime directories that 5tratumOS stages before Compose validation, so Docker
must not silently create a misspelled or missing source path.

The digest-pinned generic Alpine init container installs `jq` and
`gettext-envsubst` from Alpine 3.22 repositories at startup. This remains a
network-availability dependency, but an install failure occurs before any
persistent app-data or node-data mutation and prevents Core from starting. A
future dedicated, independently built and digest-pinned init image could remove
that availability dependency; it is not introduced in this consensus release.

The committed Compose file deliberately retains these non-runnable sentinels:

- `CORE31_CANDIDATE_DIGEST_REQUIRED`
- `APP_CANDIDATE_DIGEST_REQUIRED`

CI treats this as the strict `prefinalization` phase. It accepts exactly all
three expected sentinel occurrences. Once finalization is committed, CI
switches to `finalized` and requires one immutable application sha256 pin and
two identical immutable Core sha256 pins. A partial or mixed state is rejected.

They must be replaced with the exact verified multi-architecture candidate
digests. After substitution, the merged platform Compose must pass validation,
all images must pull anonymously by digest, init must complete successfully on
5tratumOS 0.7.11+, and the resulting installation must be tested on DEV before
any production promotion.

Run `scripts/finalize-axebc2-0.1.10-dev.sh` with the exact application index
digest, exact Core candidate tag and exact Core index digest. The application
candidate is fixed to `0.1.10-candidate.6e4ef58218e8` from source revision
`6e4ef58218e8cd5a4d1113196f9872a7f501f52e`. The Core candidate is fixed to
`31.1.0-rc.cdf44542dde2` from source revision
`cdf44542dde255648008249d187fafc15f3a2f09`, candidate workflow run
`33675068951`. Before editing Compose, the
finalizer anonymously verifies candidate resolution, amd64 and arm64 manifests
and pulls. It atomically replaces every sentinel and emits both exact source
revisions in the evidence JSON template, which must be completed only after
live DEV acceptance.

The store validator exercises a pinned copy of the relevant 5tratumOS
materialization contract from platform commit `4f979cb9541622c1fdccdf43b8a885bbf845ba38`:
it consumes `app_proxy`, publishes the manifest port on the resolved app
service, removes the legacy shared network, and normalizes restart policies.
The platform currently exposes this logic only inside its mutating install and
update commands, so invoking the live implementation from isolated store CI
would require performing a stateful platform transaction. Final DEV acceptance
therefore still runs the real platform materializer and validates its generated
Compose file before containers are started.
