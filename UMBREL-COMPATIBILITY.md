# Umbrel 1.x and 2.0 compatibility

The 24 September 2026 DEV update keeps one recipe for both Umbrel generations.
It updates packaging only: application images, node and pool images, persistent
paths, commands and network aliases are preserved. Public dashboard port numbers
stay the same.

## Recipe requirements

- Declare the dashboard service's `hostname` to match `app_proxy.environment.APP_HOST`.
  Umbrel 2.0's built-in gateway resolves service names, container names and
  hostnames, but does not resolve a target from Docker network aliases alone.
  Keep the alias for older proxy containers and retain the `app_proxy`
  declaration for both generations. Extra dashboard host-port mappings are not
  required.
- Treat legacy authentication discovery in `exports.sh` as optional. Umbrel
  sources this file with strict shell settings before rendering templates.
  A missing `auth` container must not abort installation. Preserve a supplied
  real JWT secret or discover the legacy secret with guarded probes. Do not
  change the caller's shell options or fabricate a fallback credential.
- Keep service volume mounts compatible with Umbrel 1.7.4's parser. It calls
  string methods on service mounts before template rendering; long-form mount
  objects caused the earlier AxeBC2 regression. No mount definitions change in
  this update.
- FracAttack must not publish dashboard port 21225 directly from its app
  container: the legacy Umbrel proxy already owns that port. The duplicate bind
  caused `port is already allocated` on 1.7.4. The gateway continues to expose
  the dashboard on 21225 on both versions.
- PowPow's Litecoin and Dogecoin containers run as `1000:1000`, matching its
  dashboard and existing initializer. Previously their default root user could
  create node configuration files that the dashboard could not write, causing
  a fresh-install restart loop. The initializer already repairs ownership on
  updates, and the explicit user prevents new root-owned files.

These requirements follow the earlier
[AxeBC2 repair](willitmod-dev-bc2/UMBREL-COMPATIBILITY.md) and Umbrel's released
[2.0 gateway resolver](https://github.com/getumbrel/umbrel/blob/2.0.0/packages/umbreld/source/modules/lan-ingress/lan-ingress.ts),
[gateway configuration](https://github.com/getumbrel/umbrel/blob/2.0.0/packages/umbreld/source/modules/app-gateway/app-gateway.ts), and
[app lifecycle script](https://github.com/getumbrel/umbrel/blob/2.0.0/packages/umbreld/source/modules/apps/legacy-compat/app-script).

## Package revisions

| App | Previous package | Compatibility package |
| --- | --- | --- |
| AxeBTC | 0.7.82.9-dev | 0.7.82.10-dev |
| AxeBCH | 0.9.18-dev | 0.9.19-dev |
| AxeBCH2 | 0.2.0.3-dev | 0.2.0.4-dev |
| AxeDGB | 0.9.181-dev | 0.9.182-dev |
| AxePPC | 0.2.31-dev | 0.2.32-dev |
| AxeXEC | 0.1.17-dev | 0.1.18-dev |
| FracAttack | 0.1.4-dev | 0.1.5-dev |
| PowPow | 0.2.32-dev | 0.2.33-dev |
| 5tratSmack | 0.11.13 | 0.11.14 |

The dashboard's application version may differ from the store package revision:
this update reuses the existing binaries. Image references and original Compose
contract hashes are recorded in
[the release record](UMBREL-COMPATIBILITY-2026-09-24.json).

## Verification scope

All nine updated apps and the unchanged AxeBench, AxeLive and AxeMIG passed
install/update, startup and authenticated dashboard checks on both final Umbrel
2.0.0 and Umbrel 1.7.4. The final 24 checks had no service restarts or failing
initializer exits. Each test app was stopped after checking. Existing AxeBC2
installations remained running and their authenticated dashboards were checked;
AxeBC2 was not reinstalled or updated.

AxeBCH and AxeBTC also passed baseline-to-candidate upgrades on 1.7.4.
FracAttack and PowPow were retested on 2.0 using candidate-to-candidate updates
after their additional startup fixes. The release record contains the final
per-app operations and outcomes. Automated validation ran 49 cases: 45 passed,
with four existing optional Docker/native-platform checks skipped.

Automated checks cover guarded auth discovery, preservation of shell options and
real secrets, explicit gateway target discovery across the Umbrel catalog,
repeated parsing with the Umbrel 1.7.4 parser fixture, and preservation of every
Compose setting except the added dashboard hostname, FracAttack's removed
duplicate port binding and PowPow's explicit node user.

Live checks use final Umbrel 2.0.0 and Umbrel 1.7.4 on x86-64. Each test app is
installed or updated through Umbrel, checked for authenticated dashboard access,
then stopped immediately to limit disk use. Chain synchronization, mining/share
submission, physical ARM hardware and low-instruction-set CPU compatibility are
outside this smoke test. In particular, this recipe update does not rebuild the
AxeBCH2 CKPool binary or resolve the separately reported N3450 illegal-instruction
failure.

Publication is DEV only. MAIN promotion requires a later release decision after
the DEV observation period.
