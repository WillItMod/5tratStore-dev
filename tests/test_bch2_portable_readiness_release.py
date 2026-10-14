"""Undo exactly five BCH2 release fields before all historical whole-model tests."""
import copy
import hashlib
import json
from pathlib import Path
import unittest
import yaml
from test_bch2_node_entrypoint_release import previous_bch2_node_model, package_version

ROOT = Path(__file__).resolve().parents[1]
APP = 'willitmod-dev-axebch2'
RECORD = ROOT/'BCH2-PORTABLE-READINESS-2026-10-14.json'
BASELINE = '648999be23804b9dc285f305af3a8f72fb0d00d5eb5129dc902577d09eac0d93'


def record():
    return json.loads(RECORD.read_text())


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def previous_bch2_model(app_id, current):
    current=previous_bch2_node_model(app_id,current)
    if app_id != APP:
        return copy.deepcopy(current)
    r = record();c = r['runtimeContract']
    expected = {
        ('services', 'app', 'image'): r['imageRef'],
        ('services', 'app', 'environment', 'APP_REVISION'): r['sourceRevision'],
        ('services', 'app', 'environment', 'APP_VERSION'): r['version'],
        ('services', 'app', 'environment', 'CKPOOL_IMAGE'): r['poolImageRef'],
        ('services', 'ckpool', 'image'): r['poolImageRef'],
    }
    assert c['beforeModelSHA256'] == BASELINE
    assert digest(current) == c['afterModelSHA256']
    assert len(c['changes']) == len(expected) and {tuple(x['path']) for x in c['changes']} == set(expected)
    restored = copy.deepcopy(current)
    for row in c['changes']:
        node = restored
        for key in row['path'][:-1]:
            node = node[key]
        key = row['path'][-1]
        assert node[key] == row['after'] == expected[tuple(row['path'])]
        node[key] = row['before']
    assert digest(restored) == BASELINE
    return restored


class Bch2PortableReadinessTests(unittest.TestCase):
    def test_exact_release_and_original_runtime(self):
        r = record()
        self.assertEqual(r['version'], '0.2.0.12-dev')
        self.assertEqual(r['channel'], 'DEV')
        self.assertEqual(r['sourceRevision'], '5531b5e6e2e4c55353454665af9fc1950f9f0844')
        self.assertEqual(r['poolBuildSourceRevision'], 'c0f61fcf52bd8be6782fc1a8f81ad6ebb681e6a5')
        self.assertEqual(r['poolBuildInputEquivalence']['fileCount'], 101)
        self.assertEqual(r['includedSourcePullRequests'], [7, 8])
        current = yaml.safe_load((ROOT/APP/'docker-compose.yml').read_text())
        previous_bch2_model(APP, current)
        self.assertEqual(previous_bch2_node_model(APP,current)['services']['bch2']['image'], r['coreImageRef'])
        self.assertEqual(r['coreImageRef'], 'ghcr.io/willitmod/axebch2-node:0.1.33-dev')
        self.assertEqual(current['services']['app']['stop_signal'], 'SIGINT')
        for name in ('umbrel-app.yml', 'global-app.yml'):
            manifest = yaml.safe_load((ROOT/APP/name).read_text())
            self.assertEqual(manifest['version'], package_version(APP,r['version']))
            for text in ('fresh readiness evidence', 'portable SHA256',
                         'Complete block and pool accounting records', 'Block alerts in this browser'):
                self.assertIn(text, manifest['releaseNotes'])

    def test_node_config_mount_stop_and_pool_policy_changes_are_rejected(self):
        original = yaml.safe_load((ROOT/APP/'docker-compose.yml').read_text())
        cases = [('bch2', 'image', 'different-node'), ('bch2', 'environment', {}),
                 ('app', 'volumes', []), ('app', 'stop_signal', 'SIGTERM'),
                 ('ckpool', 'command', []), ('ckpool', 'environment', {}),
                 ('init_permissions', 'command', [])]
        for service, key, value in cases:
            with self.subTest(service=service, field=key):
                changed = copy.deepcopy(original);changed['services'][service][key] = value
                with self.assertRaises(AssertionError):
                    previous_bch2_model(APP, changed)

    def test_public_identity_and_qualification_boundaries(self):
        raw = RECORD.read_text();r = record()
        for private in ('/Users/', '/home/forge', '10.10.10.', 'APP_PASSWORD', 'PAYOUT_ADDRESS'):
            self.assertNotIn(private, raw)
        for key in ('appImages', 'poolImages'):
            self.assertEqual(set(r[key]), {'amd64', 'arm64'})
            for row in r[key].values():
                self.assertEqual(set(row), {'configDigest', 'manifestDigest'})
                for value in row.values():
                    self.assertRegex(value, r'^sha256:[a-f0-9]{64}$')
        self.assertRegex(r['imageRef'], r'^ghcr.io/willitmod/axebch2-app:0\.2\.0\.12-dev@sha256:[a-f0-9]{64}$')
        self.assertRegex(r['poolImageRef'], r'^ghcr.io/willitmod/axebch2-ckpool:0\.1\.34-dev@sha256:[a-f0-9]{64}$')
        self.assertRegex(r['publicationReceiptSHA256'], r'^[a-f0-9]{64}$')
        scope = r['validationScope']
        self.assertFalse(scope['fullAppManagerLifecycleQualified'])
        self.assertFalse(scope['nonAvxRuntimeQualified'])
        self.assertFalse(scope['miningProtocolQualified'])


if __name__ == '__main__':
    unittest.main()
