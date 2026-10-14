"""Run the actual update hook and startup precondition in owned Linux tmpfs."""
import hashlib
import json
from pathlib import Path
import shutil
import shlex
import subprocess
import unittest

import yaml

ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / 'willitmod-dev-powpow'
RECORD = json.loads((ROOT / 'POWPOW-NATIVE-SEED-2026-10-14.json').read_text())
PYTHON_IMAGE = 'python:3.13.16-alpine3.24@sha256:2d9aefe2fef018a7eb2c13064c89c71929800fd2e5dccdbf52ea5da5bb8d929a'
ALPINE_IMAGE = 'alpine:3.22.1@sha256:4bcff63911fcb4448bd4fdacec207030997caf25e9bea4045fa6c8c44de311d1'

PREPARE = '''
mkdir -p /tmp/app/data/postgres /tmp/app/postgres/init
cp /recipe/data/postgres-init/*.sql /tmp/app/postgres/init/
printf preserved-db >/tmp/app/data/postgres/PG_VERSION
chmod 0600 /tmp/app/data/postgres/PG_VERSION
chown 70:70 /tmp/app/data/postgres/PG_VERSION
printf private-config >/tmp/app/.env
chmod 0600 /tmp/app/.env
cp /recipe/powpow-*.template /tmp/app/
cp -R /recipe/hooks /tmp/app/
'''


class PowPowDeliveryContractTests(unittest.TestCase):
    def test_templates_match_unchanged_reviewed_sql_and_update_whitelist(self):
        self.assertEqual(RECORD['packageVersion'], '0.2.37-dev.2')
        for name, record in RECORD['sqlFiles'].items():
            template = APP / RECORD['ordinaryUmbrelDelivery']['sourceTemplates'][name]
            self.assertEqual(template.parent, APP)
            self.assertEqual(template.suffix, '.template')
            self.assertEqual(template.read_bytes(), (APP / 'data/postgres-init' / name).read_bytes())
            self.assertEqual(hashlib.sha256(template.read_bytes()).hexdigest(), record['sha256'])
        self.assertTrue((APP / 'hooks/pre-start').stat().st_mode & 0o111)
        model = yaml.safe_load((APP / 'docker-compose.yml').read_text())
        # The native importer omits root templates/hooks. It needs only data seeds.
        mounts = model['services']['init_permissions']['volumes'] + model['services']['postgres']['volumes']
        self.assertFalse(any('.template' in mount or '/hooks' in mount for mount in mounts))


class PowPowActualLinuxDeliveryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not shutil.which('docker'):
            raise unittest.SkipTest('Docker is required for Linux fd/ownership checks')
        info = subprocess.run(['docker', 'info', '--format', '{{.ServerVersion}}'], capture_output=True, timeout=20)
        if info.returncode:
            raise unittest.SkipTest('Docker daemon is unavailable')
        for image in [PYTHON_IMAGE, ALPINE_IMAGE]:
            present = subprocess.run(['docker', 'image', 'inspect', image], capture_output=True, timeout=20)
            if present.returncode:
                subprocess.run(['docker', 'pull', image], check=True, capture_output=True, timeout=180)

    def exercise(self, body, image=PYTHON_IMAGE):
        result = subprocess.run([
            'docker', 'run', '--rm', '--pull', 'never', '--network', 'none', '--read-only',
            '--label', 'codex.owner=powpow-seed-delivery-regression',
            '--tmpfs', '/tmp:rw,exec,nosuid,nodev,mode=1777', '--tmpfs', '/data:rw,nosuid,nodev,mode=0755',
            '--mount', 'type=bind,src=' + str(APP) + ',dst=/recipe,readonly',
            '--entrypoint', '/bin/sh', image, '-eu', '-c', body,
        ], capture_output=True, text=True, timeout=120)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_historical_recipe_updates_copy_only_whitelisted_metadata_then_seed(self):
        self.exercise(PREPARE + '''
test ! -e /tmp/app/data/postgres-init
APP_DATA_DIR=/tmp/app /tmp/app/hooks/pre-start
test "$(cat /tmp/app/data/postgres/PG_VERSION)" = preserved-db
test "$(stat -c '%u:%g:%a' /tmp/app/data/postgres/PG_VERSION)" = 70:70:600
test "$(cat /tmp/app/.env)" = private-config
test "$(stat -c %a /tmp/app/.env)" = 600
test "$(stat -c '%u:%g:%a' /tmp/app/data/postgres-init)" = 1000:1000:755
for name in 2-schema.sql 3-multi-pool-partition.sql; do
  cmp /tmp/app/data/postgres-init/$name /recipe/data/postgres-init/$name
  test "$(stat -c '%u:%g:%a' /tmp/app/data/postgres-init/$name)" = 1000:1000:644
done
''')

    def test_matching_files_keep_inode_owner_mode_and_mtime_on_repeated_start(self):
        self.exercise(PREPARE + '''
mkdir /tmp/app/data/postgres-init
cp /recipe/data/postgres-init/2-schema.sql /tmp/app/data/postgres-init/
chown 70:70 /tmp/app/data/postgres-init/2-schema.sql
chmod 0600 /tmp/app/data/postgres-init/2-schema.sql
before="$(stat -c '%d:%i:%u:%g:%a:%Y' /tmp/app/data/postgres-init/2-schema.sql)"
APP_DATA_DIR=/tmp/app /tmp/app/hooks/pre-start
test "$(stat -c '%d:%i:%u:%g:%a:%Y' /tmp/app/data/postgres-init/2-schema.sql)" = "$before"
second="$(stat -c '%d:%i:%u:%g:%a:%Y' /tmp/app/data/postgres-init/3-multi-pool-partition.sql)"
APP_DATA_DIR=/tmp/app /tmp/app/hooks/pre-start
test "$(stat -c '%d:%i:%u:%g:%a:%Y' /tmp/app/data/postgres-init/2-schema.sql)" = "$before"
test "$(stat -c '%d:%i:%u:%g:%a:%Y' /tmp/app/data/postgres-init/3-multi-pool-partition.sql)" = "$second"
''')

    def test_both_sources_are_verified_before_creating_data(self):
        self.exercise('''
mkdir /tmp/app
cp /recipe/powpow-*.template /tmp/app/
cp -R /recipe/hooks /tmp/app/
printf altered >>/tmp/app/powpow-3-multi-pool-partition.sql.template
if APP_DATA_DIR=/tmp/app /tmp/app/hooks/pre-start >/tmp/hook-result 2>&1; then exit 1; fi
grep -q 'PowPow SQL seed delivery refused' /tmp/hook-result
test ! -e /tmp/app/data
''')

    def test_unsafe_source_or_destination_never_replaced_or_followed(self):
        self.exercise('''
for condition in source-symlink source-hardlink data-symlink seed-directory-symlink seed-symlink seed-hardlink seed-fifo seed-stale; do
  mkdir -p /tmp/app/data /tmp/outside
  cp /recipe/powpow-*.template /tmp/app/
  cp -R /recipe/hooks /tmp/app/
  cp /recipe/data/postgres-init/2-schema.sql /tmp/outside/exact.sql
  printf outside-private >/tmp/outside/private
  case "$condition" in
    source-symlink) rm /tmp/app/powpow-2-schema.sql.template; ln -s /tmp/outside/exact.sql /tmp/app/powpow-2-schema.sql.template ;;
    source-hardlink) rm /tmp/app/powpow-2-schema.sql.template; ln /tmp/outside/exact.sql /tmp/app/powpow-2-schema.sql.template ;;
    data-symlink) rmdir /tmp/app/data; ln -s /tmp/outside /tmp/app/data ;;
    seed-directory-symlink) ln -s /tmp/outside /tmp/app/data/postgres-init ;;
    seed-symlink) mkdir /tmp/app/data/postgres-init; ln -s /tmp/outside/exact.sql /tmp/app/data/postgres-init/2-schema.sql ;;
    seed-hardlink) mkdir /tmp/app/data/postgres-init; ln /tmp/outside/exact.sql /tmp/app/data/postgres-init/2-schema.sql ;;
    seed-fifo) mkdir /tmp/app/data/postgres-init; mkfifo /tmp/app/data/postgres-init/2-schema.sql ;;
    seed-stale) mkdir /tmp/app/data/postgres-init; printf custom-sql >/tmp/app/data/postgres-init/3-multi-pool-partition.sql ;;
  esac
  if APP_DATA_DIR=/tmp/app /tmp/app/hooks/pre-start >/tmp/hook-result 2>&1; then exit 1; fi
  grep -q 'PowPow SQL seed delivery refused' /tmp/hook-result
  test "$(cat /tmp/outside/private)" = outside-private
  cmp /tmp/outside/exact.sql /recipe/data/postgres-init/2-schema.sql
  test ! -e /tmp/outside/3-multi-pool-partition.sql
  if [ "$condition" = seed-stale ]; then
    test "$(cat /tmp/app/data/postgres-init/3-multi-pool-partition.sql)" = custom-sql
    test ! -e /tmp/app/data/postgres-init/2-schema.sql
  fi
  rm -rf /tmp/app /tmp/outside
done
''')

    def test_init_precondition_stops_before_filesystem_setup(self):
        command = RECORD['initPermissionsCommand']['after'][2].replace('$$', '$')
        # Execute the real complete Alpine command in its own shell. Any missing
        # or changed seed must return before mkdir/chown can change the sentinel.
        for state in ['missing', 'changed', 'symlink', 'hardlink', 'fifo']:
            prepare = 'mkdir -p /data/postgres-init /data/postgres\nprintf database-sentinel >/data/postgres/PG_VERSION\nchmod 0640 /data/postgres/PG_VERSION\n'
            prepare += 'cp /recipe/data/postgres-init/*.sql /data/postgres-init/\n'
            target = '/data/postgres-init/2-schema.sql'
            if state == 'missing':
                prepare += 'rm ' + target + '\n'
            elif state == 'changed':
                prepare += 'printf changed >' + target + '\n'
            elif state in ['symlink', 'hardlink']:
                source = '/data/source.sql' if state == 'hardlink' else '/tmp/source.sql'
                prepare += 'cp ' + target + ' ' + source + '\nrm ' + target + '\nln ' + ('-s ' if state == 'symlink' else '') + source + ' ' + target + '\n'
            else:
                prepare += 'rm ' + target + '\nmkfifo ' + target + '\n'
            body = prepare + 'if /bin/sh -ec ' + shlex.quote(command) + '; then exit 1; fi\n'
            body += '''
test ! -e /data/ui
test ! -e /data/litecoin
test ! -e /data/dogecoin
test ! -e /data/pool
test "$(cat /data/postgres/PG_VERSION)" = database-sentinel
test "$(stat -c '%u:%g:%a' /data/postgres/PG_VERSION)" = 0:0:640
'''
            with self.subTest(seed_state=state):
                self.exercise(body, ALPINE_IMAGE)

    def test_init_precondition_accepts_exact_native_seeds_without_root_templates(self):
        command = RECORD['initPermissionsCommand']['after'][2].replace('$$', '$')
        self.exercise('mkdir -p /data/postgres-init\ncp /recipe/data/postgres-init/*.sql /data/postgres-init/\n'
                      + '/bin/sh -ec ' + shlex.quote(command) + '\n'
                      + 'test -d /data/ui/state\ntest -d /data/postgres\n', ALPINE_IMAGE)


if __name__ == '__main__':
    unittest.main()
