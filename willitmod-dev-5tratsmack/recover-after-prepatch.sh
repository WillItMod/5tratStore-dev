#!/usr/bin/env bash
set -Eeuo pipefail

app_id="willitmod-dev-5tratsmack"
app_root="/home/umbrel/umbrel/app-data/${app_id}"
app_compose="${app_root}/docker-compose.yml"
app_manifest="${app_root}/umbrel-app.yml"
release_commit="d2b2e451bfefab6ab9b234d7cf00ccfd6080e29c"
release_base="https://raw.githubusercontent.com/WillItMod/umbrel-dev-community-store/${release_commit}/${app_id}"
work_dir="$(mktemp -d /tmp/5tratsmack-0.11.1-prepatch-recovery.XXXXXX)"
new_compose="${work_dir}/docker-compose.yml"
new_manifest="${work_dir}/umbrel-app.yml"
stamp="$(date -u +%Y%m%dT%H%M%SZ)"
trap 'rm -rf "${work_dir}"' EXIT

fail() {
  printf 'ERROR: %s\n' "$*" >&2
  exit 1
}

command -v sudo >/dev/null 2>&1 || fail "sudo is required"
command -v docker >/dev/null 2>&1 || fail "Docker is required"
command -v umbreld >/dev/null 2>&1 || fail "This does not look like Umbrel 1.x"
command -v curl >/dev/null 2>&1 || fail "curl is required"

sudo test -d "${app_root}/data" \
  || fail "5tratSmack data was not found at ${app_root}/data"
sudo test -f "${app_compose}" \
  || fail "The installed compose file was not found at ${app_compose}"
sudo test -f "${app_manifest}" \
  || fail "The installed manifest was not found at ${app_manifest}"

shopt -s nullglob
backup_files=(
  /home/umbrel/5tratsmack-wallet-state-before-0.11.1-*.tgz
)
shopt -u nullglob
((${#backup_files[@]})) \
  || fail "The verified wallet/state backup from the first recovery was not found"
backup_file="${backup_files[${#backup_files[@]} - 1]}"
sudo test -s "${backup_file}" || fail "The wallet/state backup is empty"
sudo tar -tzf "${backup_file}" >/dev/null \
  || fail "The wallet/state backup failed its integrity check"

printf 'Verified existing wallet/state backup: %s\n' "${backup_file}"
printf 'App data remains at: %s\n' "${app_root}/data"

curl -fsSL "${release_base}/docker-compose.yml" -o "${new_compose}"
curl -fsSL "${release_base}/umbrel-app.yml" -o "${new_manifest}"

printf '%s  %s\n' \
  "3078da58cefa69cbe00a81d152f5e46ce8113d41faf1c82421e7e2968f01800d" \
  "${new_compose}" \
  | sha256sum --check --status \
  || fail "The published 0.11.1 compose checksum did not match"
printf '%s  %s\n' \
  "ba5cf06dfd015522d9bcc1e01d8bc9e7bc29a45298acce42521fa28e6e491fc4" \
  "${new_manifest}" \
  | sha256sum --check --status \
  || fail "The published 0.11.1 manifest checksum did not match"

grep -Fq 'ghcr.io/willitmod/5tratsmack-app:0.11.1' "${new_compose}" \
  || fail "The downloaded recipe is not 5tratSmack 0.11.1"
if grep -Fq '0.0.0.0:21226:3000' "${new_compose}"; then
  fail "The downloaded recipe contains the conflicting direct port"
fi

sudo cp -a "${app_compose}" "${app_compose}.before-direct-0.11.1-${stamp}"
sudo cp -a "${app_manifest}" "${app_manifest}.before-direct-0.11.1-${stamp}"
sudo install -m 0644 "${new_compose}" "${app_compose}"
sudo install -m 0644 "${new_manifest}" "${app_manifest}"

printf 'Installed the checksum-verified 0.11.1 recipe. Starting through Umbrel...\n'
umbreld client apps.start.mutate --appId "${app_id}"

printf '\n5tratSmack container state:\n'
sudo docker ps -a \
  --filter "label=com.docker.compose.project=${app_id}" \
  --format '{{.Names}}  {{.Image}}  {{.Status}}'

if ! sudo docker ps -a \
  --filter "label=com.docker.compose.project=${app_id}" \
  --format '{{.Image}}' \
  | grep -Fq 'ghcr.io/willitmod/5tratsmack-app:0.11.1'; then
  fail "Umbrel did not create the 0.11.1 application container"
fi

printf '\nDirect recovery completed without uninstalling the app or replacing app data.\n'
printf 'Keep this backup until the wallet is checked: %s\n' "${backup_file}"
