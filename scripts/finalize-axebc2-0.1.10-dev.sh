#!/usr/bin/env bash
set -Eeuo pipefail

if [[ "$#" -lt 3 || "$#" -gt 4 ]]; then
  echo "usage: $0 APP_INDEX_DIGEST CORE_CANDIDATE_TAG CORE_INDEX_DIGEST [EVIDENCE_OUTPUT]" >&2
  exit 64
fi
app_digest="$1"; core_candidate_tag="$2"; core_digest="$3"
repo_root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
compose="$repo_root/willitmod-dev-bc2/docker-compose.yml"
evidence_output="${4:-$repo_root/willitmod-dev-bc2/DEV-ACCEPTANCE-EVIDENCE.json}"
docker_bin="${DOCKER_BIN:-docker}"
curl_bin="${CURL_BIN:-curl}"
jq_bin="${JQ_BIN:-jq}"
app_tag="ghcr.io/willitmod/axebc2-app-umbrel-dev:0.1.10-candidate.6e4ef58218e8"
app_revision="6e4ef58218e8cd5a4d1113196f9872a7f501f52e"
core_revision="cdf44542dde255648008249d187fafc15f3a2f09"
core_tag="ghcr.io/willitmod/bitcoinii-core:$core_candidate_tag"
fail() { echo "ERROR: $*" >&2; exit 1; }
[[ "$app_digest" =~ ^sha256:[0-9a-f]{64}$ ]] || fail "app digest is not an exact sha256 digest"
[[ "$core_digest" =~ ^sha256:[0-9a-f]{64}$ ]] || fail "Core digest is not an exact sha256 digest"
[[ "$core_candidate_tag" == "31.1.0-rc.cdf44542dde2" ]] || fail "Core tag must be 31.1.0-rc.cdf44542dde2"
command -v "$docker_bin" >/dev/null 2>&1 || fail "Docker is required for registry verification"
command -v "$curl_bin" >/dev/null 2>&1 || fail "curl is required for anonymous registry verification"
command -v "$jq_bin" >/dev/null 2>&1 || fail "jq is required for anonymous registry verification"
docker_host="${DOCKER_HOST:-}"
if [[ -z "$docker_host" ]]; then
  active_context="$("$docker_bin" context show)" || fail "cannot determine active Docker context"
  [[ -n "$active_context" ]] || fail "active Docker context is empty"
  docker_host="$("$docker_bin" context inspect "$active_context" --format '{{.Endpoints.docker.Host}}')" || fail "cannot resolve active Docker daemon endpoint"
fi
[[ "$docker_host" =~ ^(unix|tcp|ssh|npipe)://[^[:space:]]+$ ]] || fail "Docker daemon endpoint is missing or malformed"

anon_config="$(mktemp -d "${TMPDIR:-/tmp}/axebc2-anonymous-docker.XXXXXX")"
cleanup() { rm -rf -- "$anon_config"; }
trap cleanup EXIT
printf '{"auths":{}}\n' >"$anon_config/config.json"

resolve_tag() {
  local ref="$1" expected="$2" path repository tag token headers resolved
  [[ "$ref" == "$app_tag" || "$ref" == "$core_tag" ]] || fail "not an approved candidate tag: $ref"
  path="${ref#ghcr.io/}"; repository="${path%:*}"; tag="${path##*:}"
  token="$("$curl_bin" -fsSL "https://ghcr.io/token?service=ghcr.io&scope=repository:${repository}:pull" | "$jq_bin" -er '.token')" || fail "anonymous token request failed: $ref"
  headers="$("$curl_bin" -fsSI -H "Authorization: Bearer $token" \
    -H 'Accept: application/vnd.oci.image.index.v1+json, application/vnd.docker.distribution.manifest.list.v2+json' \
    "https://ghcr.io/v2/${repository}/manifests/${tag}")" || fail "anonymous manifest HEAD failed: $ref"
  resolved="$(printf '%s\n' "$headers" | awk 'tolower($0) ~ /^docker-content-digest:/ {sub(/^[^:]*:[[:space:]]*/, ""); sub(/\r$/, ""); print}' | tail -n 1)"
  [[ "$resolved" =~ ^sha256:[0-9a-f]{64}$ ]] || fail "$ref returned a missing or malformed Docker-Content-Digest"
  [[ "$resolved" == "$expected" ]] || fail "$ref resolves to ${resolved:-nothing}, expected $expected"
}
verify_index() {
  local ref="$1" digest="$2" manifest
  manifest="$("$docker_bin" --host "$docker_host" --config "$anon_config" manifest inspect "$ref@$digest")" || fail "anonymous inspection failed: $ref@$digest"
  python3 -c '
import json,sys
d=json.load(sys.stdin); p={(m.get("platform",{}).get("os"),m.get("platform",{}).get("architecture")) for m in d.get("manifests",[])}
missing={("linux","amd64"),("linux","arm64")}-p
if missing: raise SystemExit("missing required platforms: "+str(sorted(missing)))
' <<<"$manifest" || fail "$ref@$digest is not an amd64+arm64 index"
  "$docker_bin" --host "$docker_host" --config "$anon_config" pull --platform linux/amd64 "$ref@$digest" >/dev/null || fail "anonymous amd64 pull failed"
  "$docker_bin" --host "$docker_host" --config "$anon_config" pull --platform linux/arm64 "$ref@$digest" >/dev/null || fail "anonymous arm64 pull failed"
}
resolve_tag "$app_tag" "$app_digest"; resolve_tag "$core_tag" "$core_digest"
verify_index "$app_tag" "$app_digest"; verify_index "$core_tag" "$core_digest"

[[ "$(grep -oF APP_CANDIDATE_DIGEST_REQUIRED "$compose" | wc -l | tr -d ' ')" == 1 ]] || fail "expected one app sentinel"
[[ "$(grep -oF CORE31_CANDIDATE_DIGEST_REQUIRED "$compose" | wc -l | tr -d ' ')" == 2 ]] || fail "expected two Core sentinels"
tmp="$(mktemp "${compose}.finalize.XXXXXX")"
sed -e "s/APP_CANDIDATE_DIGEST_REQUIRED/${app_digest#sha256:}/g" \
    -e "s|$core_tag@sha256:CORE31_CANDIDATE_DIGEST_REQUIRED|$core_tag@$core_digest|g" "$compose" >"$tmp"
chmod 0644 "$tmp"
grep -F _DIGEST_REQUIRED "$tmp" >/dev/null && fail "unresolved digest sentinel remains"
[[ "$(grep -oF "$core_tag@$core_digest" "$tmp" | wc -l | tr -d ' ')" == 2 ]] || fail "Core references differ"
grep -Fx "    image: $app_tag@$app_digest" "$tmp" >/dev/null || fail "app reference is incorrect"
grep -Fx "    image: $core_tag@$core_digest" "$tmp" >/dev/null || fail "Core service reference is incorrect"
grep -Fx "      BTC2D_IMAGE: \"$core_tag@$core_digest\"" "$tmp" >/dev/null || fail "BTC2D_IMAGE is incorrect"

evidence_tmp="$(mktemp "${evidence_output}.finalize.XXXXXX")"
python3 - "$evidence_tmp" "$app_tag" "$app_digest" "$app_revision" "$core_tag" "$core_digest" "$core_revision" <<'PY'
import json,sys
path,app_image,app_digest,revision,core_image,core_digest,core_revision=sys.argv[1:]
with open(path,"w",encoding="utf-8") as h:
 json.dump({"schema":1,"result":"RECORD_passed_AFTER_LIVE_DEV_ACCEPTANCE","app_image":app_image,"app_digest":app_digest,"core_image":core_image,"core_digest":core_digest,"app_version":"0.1.10-dev","source_revision":revision,"core_source_revision":core_revision,"core_candidate_run":33675068951,"tested_os_version":"v0.7.12-dev","tested_os_bundle_sha256":"RECORD_64_HEX_OS_BUNDLE_SHA256","tested_on":"RECORD_TEST_NODE","tested_at":"RECORD_ISO_8601_TIMESTAMP","acceptance":{"observed_at":"RECORD_ISO_8601_TIMESTAMP","chain":"main","core_version":"RECORD_INTEGER_VERSION","migration_required_marker_absent":"RECORD_BOOLEAN","migration_started_marker_valid":"RECORD_BOOLEAN","migration_complete_marker_valid":"RECORD_BOOLEAN","checkpoint_height":57752,"checkpoint_hash":"000000000000000013ceffe797280c57f75a5b9f1d9e70c3503584058c322576","chainwork":"RECORD_64_HEX_CHAINWORK","ibd":False,"verification_progress":"RECORD_NUMBER","blocks":"RECORD_INTEGER","headers":"RECORD_SAME_INTEGER","best_block_hash":"RECORD_64_HEX_HASH","explorer_common_height":"RECORD_SAME_INTEGER","explorer_common_hash":"RECORD_SAME_64_HEX_HASH","outbound_core31_peers":"RECORD_INTEGER_AT_LEAST_3","competing_valid_tips":0,"verifychain_level":4,"verifychain_passed":"RECORD_BOOLEAN","payout_configured":"RECORD_BOOLEAN","payout_preserved":"RECORD_BOOLEAN","pool_stratum_result":"RECORD_passed","app_ui_privacy_passed":"RECORD_BOOLEAN","telemetry_disabled":"RECORD_BOOLEAN","p2p_port_unpublished":"RECORD_BOOLEAN","natpmp_disabled":"RECORD_BOOLEAN","post_completion_restart_passed":"RECORD_BOOLEAN","reindex_not_repeated":"RECORD_BOOLEAN","app_rollback_rejected":"RECORD_BOOLEAN","os_rollback_rejected":"RECORD_BOOLEAN"}},h,indent=2); h.write("\n")
PY
chmod 0644 "$evidence_tmp"
mv -f "$tmp" "$compose"; mv -f "$evidence_tmp" "$evidence_output"
printf 'Prepared AxeBC2 0.1.10 DEV\napp=%s\ncore=%s\nevidence template=%s\n' "$app_digest" "$core_digest" "$evidence_output"
