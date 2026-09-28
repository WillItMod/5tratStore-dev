"""Protect legacy auth, gateway discovery and the unchanged application contract."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import unittest

import yaml

ROOT = Path(__file__).resolve().parents[1]
CONTRACT = json.loads((ROOT / 'UMBREL-CONTRACTS-2026-09-28.json').read_text())
RELEASE = CONTRACT['apps']


class UmbrelCrossVersionTests(unittest.TestCase):
    def test_historical_live_acceptance_evidence_is_preserved(self):
        previous = ROOT / CONTRACT['historical_evidence']
        self.assertEqual(hashlib.sha256(previous.read_bytes()).hexdigest(),
                         CONTRACT['historical_evidence_sha256'])

    def test_python_stop_policy_is_app_only_and_retains_every_other_field(self):
        migration = CONTRACT['python_app_stop_policy']
        expected = {'willitmod-dev-' + name for name in
                    ('btc', 'bch', 'axebch2', 'dgb', 'xec', 'ppc', 'powpow', 'fracattack')}
        self.assertEqual(set(migration['baseline_compose_contract_sha256']), expected)
        self.assertEqual(migration['baseline_store_commit'],
                         'cf72507651d46b7f432d75d0e5626e792c40a723')
        self.assertEqual(migration['service'], 'app')
        self.assertEqual(migration['stop_signal'], 'SIGINT')
        for app_id in expected:
            with self.subTest(app=app_id):
                compose = yaml.safe_load((ROOT / app_id / 'docker-compose.yml').read_text())
                self.assertEqual(compose['services']['app'].pop('stop_signal'), 'SIGINT')
                # Comparing the entire preceding contract also protects every
                # Core/pool/Redis field, image, mount, secret interpolation and
                # existing grace period; no unrelated lifecycle change slips in.
                digest = hashlib.sha256(json.dumps(compose, sort_keys=True,
                                                   separators=(',', ':')).encode()).hexdigest()
                self.assertEqual(digest, migration['baseline_compose_contract_sha256'][app_id])
        # BC2 already installs its own TERM handler; retain its existing policy.
        for filename in ('docker-compose.yml', 'docker-compose.yml.template'):
            compose = yaml.safe_load((ROOT / 'willitmod-dev-bc2' / filename).read_text())
            self.assertNotIn('stop_signal', compose['services']['app'])

    def test_only_reviewed_changes_reach_the_current_compose_contract(self):
        for app_id, release in RELEASE.items():
            with self.subTest(app=app_id):
                compose = yaml.safe_load((ROOT / app_id / 'docker-compose.yml').read_text())
                host = compose['services']['app_proxy']['environment']['APP_HOST']
                if app_id == 'willitmod-dev-bc2':
                    for network in ('default', 'umbrel_main_network'):
                        self.assertIn(host, compose['services']['app']['networks'][network]['aliases'])
                else:
                    self.assertEqual(compose['services']['app']['hostname'], host)
                if app_id == 'willitmod-dev-fracattack':
                    self.assertNotIn('ports', compose['services']['app'])
                if app_id == 'willitmod-dev-powpow':
                    for node in ['litecoin', 'dogecoin']:
                        self.assertEqual(compose['services'][node]['user'], '1000:1000')
                digest = hashlib.sha256(json.dumps(compose, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
                self.assertEqual(digest, release['compose_contract_sha256'])
                self.assertEqual(yaml.safe_load((ROOT / app_id / 'umbrel-app.yml').read_text())['version'], release['package_version'])

    def test_umbrel_174_parser_accepts_install_and_repeated_start(self):
        fixture = ROOT / 'tests/fixtures/umbrel_1_7_4_patch_compose.cjs'
        for app_id in RELEASE:
            with self.subTest(app=app_id):
                compose = yaml.safe_load((ROOT / app_id / 'docker-compose.yml').read_text())
                for _ in range(2):
                    result = subprocess.run(['node', str(fixture)], input=json.dumps({'compose': compose, 'id': app_id}), text=True, capture_output=True, check=True)
                    compose = json.loads(result.stdout)

    def test_every_catalog_gateway_has_an_explicit_service_match(self):
        for manifest in ROOT.glob('*/umbrel-app.yml'):
            with self.subTest(app=manifest.parent.name):
                recipe = manifest.parent / 'docker-compose.yml.template'
                if not recipe.exists():
                    recipe = manifest.parent / 'docker-compose.yml'
                compose = yaml.safe_load(recipe.read_text())
                host = compose['services']['app_proxy']['environment']['APP_HOST']
                self.assertTrue(any(host in [name, service.get('hostname'), service.get('container_name'), manifest.parent.name + '_' + name + '_1'] for name, service in compose['services'].items()))

    def test_exports_tolerate_missing_auth_and_preserve_real_legacy_secret(self):
        script = '''
set -euo pipefail
docker() {
    case "${FAKE_MODE}:${!#}" in
      later:umbrel-auth) printf '%s\\n' 'JWT_SECRET=real-test-secret';;
      *) return 1;;
    esac
}
before="$-"
source "$1"
[[ "$before" == "$-" ]]
[[ "$(set -o | awk '$1 == "pipefail" {print $2}')" == on ]]
printf '%s' "${JWT_SECRET-unset}"
'''
        for app_id in RELEASE:
            exports = ROOT / app_id / 'exports.sh'
            if not exports.exists():
                continue
            for mode, supplied, expected in [('missing', None, 'unset'), ('later', None, 'real-test-secret'), ('missing', 'supplied-test-secret', 'supplied-test-secret')]:
                with self.subTest(app=app_id, mode=mode, supplied=bool(supplied)):
                    env = dict(os.environ, FAKE_MODE=mode)
                    env.pop('JWT_SECRET', None)
                    if supplied:
                        env['JWT_SECRET'] = supplied
                    result = subprocess.run(['bash', '-c', script, 'probe', str(exports)], env=env, text=True, capture_output=True)
                    self.assertEqual(result.returncode, 0, result.stderr)
                    self.assertEqual(result.stdout, expected)


if __name__ == '__main__':
    unittest.main()
