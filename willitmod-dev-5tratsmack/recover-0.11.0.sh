#!/usr/bin/env bash
set -Eeuo pipefail

app_id="willitmod-dev-5tratsmack"
app_root="/home/umbrel/umbrel/app-data/${app_id}"
app_compose="${app_root}/docker-compose.yml"
backup_stamp="$(date -u +%Y%m%dT%H%M%SZ)"
backup_file="/home/umbrel/5tratsmack-wallet-state-before-0.11.1-${backup_stamp}.tgz"
compose_backup="${app_compose}.before-0.11.1-${backup_stamp}"

fail() {
  printf 'ERROR: %s\n' "$*" >&2
  exit 1
}

command -v sudo >/dev/null 2>&1 || fail "sudo is required"
command -v docker >/dev/null 2>&1 || fail "Docker is required"
command -v umbreld >/dev/null 2>&1 || fail "This does not look like Umbrel 1.x"

sudo test -d "${app_root}/data" \
  || fail "5tratSmack data was not found at ${app_root}/data"
sudo test -f "${app_compose}" \
  || fail "The installed compose file was not found at ${app_compose}"

printf '5tratSmack Umbrel 0.11.0 recovery\n'
printf 'App data: %s\n' "${app_root}/data"
printf 'No app uninstall, volume removal, or app-data deletion will be used.\n'

mapfile -t app_containers < <(
  sudo docker ps -aq \
    --filter "label=com.docker.compose.project=${app_id}"
)

if ((${#app_containers[@]})); then
  printf '\nStopping these 5tratSmack containers:\n'
  sudo docker inspect \
    --format '{{.Name}}  {{.Config.Image}}' \
    "${app_containers[@]}"
  sudo docker update --restart=no "${app_containers[@]}" >/dev/null
  sudo docker stop -t 120 "${app_containers[@]}" >/dev/null
else
  printf '\nNo running or stopped 5tratSmack containers were found.\n'
fi

printf '\nCreating wallet and application-state backup...\n'
sudo tar -czf "${backup_file}" \
  -C "${app_root}" \
  --exclude='data/node/blocks' \
  --exclude='data/node/chainstate' \
  --exclude='data/node/indexes' \
  data
sudo test -s "${backup_file}" || fail "The backup file is empty"
sudo tar -tzf "${backup_file}" >/dev/null \
  || fail "The backup archive did not pass its integrity check"
printf 'Backup verified: %s\n' "${backup_file}"

sudo cp -a "${app_compose}" "${compose_backup}"
if sudo grep -Fq '0.0.0.0:21226:3000' "${app_compose}"; then
  sudo sed -i '/0\.0\.0\.0:21226:3000/d' "${app_compose}"
  printf 'Removed the conflicting direct port binding.\n'
else
  printf 'The conflicting direct port binding is already absent.\n'
fi

printf '\nRequesting the published 0.11.1 update from Umbrel...\n'
if ! umbreld client apps.update.mutate --appId "${app_id}"; then
  printf '\nUmbrel still has stale 0.11.0 containers. Removing containers only.\n'
  mapfile -t stale_containers < <(
    sudo docker ps -aq \
      --filter "label=com.docker.compose.project=${app_id}"
  )
  if ((${#stale_containers[@]})); then
    sudo docker rm -f "${stale_containers[@]}" >/dev/null
  fi
  umbreld client apps.update.mutate --appId "${app_id}"
fi

# Some Umbrel releases start the app as part of update; others require this
# separate mutation. A harmless "already running" response is printed.
umbreld client apps.start.mutate --appId "${app_id}" || true

printf '\nInstalled 5tratSmack containers:\n'
sudo docker ps -a \
  --filter "label=com.docker.compose.project=${app_id}" \
  --format '{{.Names}}  {{.Image}}  {{.Status}}'

if sudo grep -Fq '0.0.0.0:21226:3000' "${app_compose}"; then
  fail "The conflicting port unexpectedly remains in the installed recipe"
fi

printf '\nRecovery completed. Keep this backup until the wallet is checked:\n'
printf '%s\n' "${backup_file}"
