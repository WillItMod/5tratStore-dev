#!/usr/bin/env bash
set -Eeuo pipefail

app_root="/home/umbrel/umbrel/app-data/willitmod-dev-5tratsmack"
if sudo grep -Fq 'ghcr.io/willitmod/5tratsmack-app:0.11.1' "${app_root}/docker-compose.yml" 2>/dev/null; then
  printf '5tratSmack 0.11.1 is already installed. No recovery was needed.\n'
  exit 0
fi

commit="e6f8ffd02d917af96e099016615437cc692ae945"
base="https://raw.githubusercontent.com/WillItMod/umbrel-dev-community-store/${commit}/willitmod-dev-5tratsmack"
work="$(mktemp -d /tmp/5tratsmack-one-shot.XXXXXX)"
trap 'rm -rf "${work}"' EXIT

curl -fsSL "${base}/recover-0.11.0.sh" -o "${work}/first.sh"
curl -fsSL "${base}/recover-after-prepatch.sh" -o "${work}/second.sh"
printf '%s  %s\n' \
  '7611ba85ca7d4433f20dc8c5c674dd3455521cc10e11735acc1c6994f2896b7f' \
  "${work}/first.sh" \
  | sha256sum --check --status
printf '%s  %s\n' \
  'abee6c78cec5b1faa04f86f794ea1d65ae19160f9cd9d94ba77708fc242f7828' \
  "${work}/second.sh" \
  | sha256sum --check --status

if ! bash "${work}/first.sh"; then
  printf '\nUmbrel pre-patch failed; continuing with the verified direct recovery.\n'
  bash "${work}/second.sh"
fi
