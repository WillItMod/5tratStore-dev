"""Exercise installed public-script migration; keep frozen recipe fields exact."""
import base64
import hashlib
import os
from pathlib import Path
import re
import subprocess
import unittest
import uuid

import yaml
from app_version_normalization import previous_app_version_model, package_version

ROOT = Path(__file__).resolve().parents[1]
BASELINE = 'd5dc75a03465bb8fc1a488bcf4375abb251ecf6c'
APPS = ('btc', 'fracattack')
START = '# BEGIN REVIEWED POOL SUPERVISOR MIGRATION\n'
END = '# END REVIEWED POOL SUPERVISOR MIGRATION\n'
IMAGE = 'alpine@sha256:4bcff63911fcb4448bd4fdacec207030997caf25e9bea4045fa6c8c44de311d1'
OWNER = 'codex-btc-frac-supervisor-delivery-20261014'


def source(app, name, baseline=False):
    path = f'willitmod-dev-{app}/{name}'
    if baseline:
        return subprocess.check_output(['git', '-C', str(ROOT), 'show', BASELINE + ':' + path])
    return (ROOT / path).read_bytes()


def compose(app, baseline=False):
    return yaml.safe_load(source(app, 'docker-compose.yml', baseline))


def guard(app):
    command = compose(app)['services']['init']['command'][2]
    return (START + command.split(START, 1)[1].split(END, 1)[0] + END).replace('$$', '$')


class SourceContracts(unittest.TestCase):
    def test_only_reviewed_initializer_prefix_changes_in_each_compose_model(self):
        for app in APPS:
            with self.subTest(app=app):
                candidate = previous_app_version_model('willitmod-dev-' + app, compose(app))
                command = candidate['services']['init']['command'][2]
                prefix, remainder = command.split(START, 1)
                _, suffix = remainder.split(END, 1)
                candidate['services']['init']['command'][2] = prefix + suffix.removeprefix('\n')
                self.assertEqual(candidate, compose(app, True))

    def test_embedded_payload_is_exact_shipped_script_with_known_old_and_new_hashes(self):
        for app in APPS:
            with self.subTest(app=app):
                shell = guard(app)
                encoded = shell.split("<<'REVIEWED_POOL_SUPERVISOR'\n", 1)[1].split('\nREVIEWED_POOL_SUPERVISOR', 1)[0]
                new = source(app, 'data/templates/ckpool-entrypoint.sh')
                old = source(app, 'data/templates/ckpool-entrypoint.sh', True)
                self.assertEqual(base64.b64decode(encoded, validate=False), new)
                self.assertIn(hashlib.sha256(old).hexdigest(), shell)
                self.assertIn(hashlib.sha256(new).hexdigest(), shell)
                self.assertNotIn('$(start_ckpool', new.decode())
                subprocess.run(['sh', '-n'], input=shell, text=True, check=True)
                subprocess.run(['sh', '-n'], input=new, check=True)

    def test_manifest_changes_only_package_version_and_release_notes(self):
        versions = {'btc': '0.7.82.17-dev.1', 'fracattack': '0.1.12-dev'}
        for app in APPS:
            for name in ('umbrel-app.yml', 'global-app.yml'):
                if not (ROOT / f'willitmod-dev-{app}' / name).is_file():
                    continue
                before = yaml.safe_load(source(app, name, True))
                after = yaml.safe_load(source(app, name))
                self.assertEqual(after['version'], package_version('willitmod-dev-' + app, versions[app]))
                after['version'] = before['version']
                after['releaseNotes'] = before['releaseNotes']
                self.assertEqual(after, before)

    def test_both_supervisors_have_identical_control_flow_except_existing_log_prefix(self):
        for baseline in (False, True):
            btc = source('btc', 'data/templates/ckpool-entrypoint.sh', baseline)
            frac = source('fracattack', 'data/templates/ckpool-entrypoint.sh', baseline)
            self.assertEqual(btc.replace(b'[axebtc]', b'[fracattack]'), frac)


@unittest.skipUnless(os.environ.get('POOL_SUPERVISOR_DOCKER') == '1', 'opt-in actual Linux initializer fixtures')
class ActualInitializerDelivery(unittest.TestCase):
    """Real shipped shell on owned ephemeral Linux files, no RPC/protocol server."""

    def run_case(self, app, case):
        # Only a new container writable layer is used; no app or host data mount.
        old = base64.b64encode(source(app, 'data/templates/ckpool-entrypoint.sh', True)).decode()
        new = base64.b64encode(source(app, 'data/templates/ckpool-entrypoint.sh')).decode()
        setup = f"""
set -eu
mkdir -p /data/templates /data/pool/config
printf '%s' '{old}' | base64 -d >/data/templates/ckpool-entrypoint.sh
printf 'owned config sentinel\\n' >/data/pool/config/.sentinel
chown 1000:1000 /data/templates/ckpool-entrypoint.sh /data/pool/config/.sentinel
chmod 0751 /data/templates/ckpool-entrypoint.sh
touch -d @1700000000 /data/templates/ckpool-entrypoint.sh
"""
        setup += {
            'old': '',
            'new': f"printf '%s' '{new}' | base64 -d >/data/templates/ckpool-entrypoint.sh\ntouch -d @1700000000 /data/templates/ckpool-entrypoint.sh\n",
            'custom': "printf '#!/bin/sh\\necho custom supervisor\\n' >/data/templates/ckpool-entrypoint.sh\n",
            'missing': 'rm /data/templates/ckpool-entrypoint.sh\n',
            'target-link': 'mv /data/templates/ckpool-entrypoint.sh /data/templates/original.sh\nln -s original.sh /data/templates/ckpool-entrypoint.sh\n',
            'hardlink': 'ln /data/templates/ckpool-entrypoint.sh /data/templates/second.sh\n',
            'parent-link': 'mv /data/templates /data/original-templates\nln -s original-templates /data/templates\n',
            'data-link': 'mv /data /owned-original-data\nln -s /owned-original-data /data\n',
            'oversized': 'dd if=/dev/zero of=/data/templates/ckpool-entrypoint.sh bs=16385 count=1 2>/dev/null\n',
        }[case]
        snapshot = """
find /data /owned-original-data -xdev -exec stat -c '%n|%F|%a|%u|%g|%i|%h|%s|%Y|%Z' {} + 2>/dev/null | sort
find /data /owned-original-data -xdev -type f -exec sha256sum {} + 2>/dev/null | sort
"""
        script = setup + "\nprintf 'BEFORE\\n'\n" + snapshot + "printf 'BEFORE_END\\n'\nset +e\n(\nset -eu\n" + guard(app) + "\n)\nresult=$?\nset -e\nprintf 'RESULT=%s\\n' \"$result\"\nprintf 'AFTER\\n'\n" + snapshot + "printf 'AFTER_END\\n'\n"
        result = subprocess.run(['docker', 'run', '--rm', '-i', '--name', OWNER + '-' + uuid.uuid4().hex[:10],
            '--label', 'dev.compat.owner=' + OWNER, '--network', 'none', '--cap-drop', 'ALL',
            '--cap-add', 'CHOWN', '--cap-add', 'FOWNER', '--cap-add', 'DAC_OVERRIDE',
            '--security-opt', 'no-new-privileges:true', '--memory', '96m', '--cpus', '1', '--pids-limit', '32',
            '--entrypoint', '/bin/sh', IMAGE, '-s'], input=script, text=True, capture_output=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stderr)
        before = result.stdout.split('BEFORE\n', 1)[1].split('BEFORE_END\n', 1)[0]
        after = result.stdout.split('AFTER\n', 1)[1].split('AFTER_END\n', 1)[0]
        status = int(re.search(r'^RESULT=(\d+)$', result.stdout, re.M)[1])
        return before, after, status

    def test_known_old_is_delivered_atomically_preserving_permissions_owner_and_mtime(self):
        for app in APPS:
            with self.subTest(app=app):
                before, after, status = self.run_case(app, 'old')
                self.assertEqual(status, 0)
                self.assertIn(hashlib.sha256(source(app, 'data/templates/ckpool-entrypoint.sh')).hexdigest(), after)
                target_before = next(line for line in before.splitlines() if line.startswith('/data/templates/ckpool-entrypoint.sh|')).split('|')
                target_after = next(line for line in after.splitlines() if line.startswith('/data/templates/ckpool-entrypoint.sh|')).split('|')
                self.assertEqual(target_before[2:5], target_after[2:5])
                self.assertEqual(target_before[8], target_after[8])
                self.assertNotEqual(target_before[5], target_after[5])
                sentinel_before = [line for line in before.splitlines() if '/data/pool/' in line]
                sentinel_after = [line for line in after.splitlines() if '/data/pool/' in line]
                self.assertEqual(sentinel_before, sentinel_after)
                self.assertNotIn('.ckpool-entrypoint.', after)

    def test_known_new_is_idempotent_without_inode_mode_owner_or_timestamp_changes(self):
        for app in APPS:
            with self.subTest(app=app):
                before, after, status = self.run_case(app, 'new')
                self.assertEqual(status, 0)
                self.assertEqual(before, after)

    def test_missing_custom_links_and_oversized_target_fail_before_any_change(self):
        for app in APPS:
            for case in ('missing', 'custom', 'target-link', 'parent-link', 'data-link', 'hardlink', 'oversized'):
                with self.subTest(app=app, case=case):
                    before, after, status = self.run_case(app, case)
                    self.assertNotEqual(status, 0)
                    self.assertEqual(before, after)


if __name__ == '__main__':
    unittest.main()
