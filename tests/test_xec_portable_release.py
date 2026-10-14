"""Keep the portable pool change separate from all prior XEC runtime contracts."""
import copy
import hashlib
import json
from pathlib import Path
import unittest
import yaml

ROOT = Path(__file__).resolve().parents[1]
APP = 'willitmod-dev-xec'
RECORD = json.loads((ROOT / 'XEC-PORTABLE-2026-10-14.json').read_text())


def digest(model):
    return hashlib.sha256(json.dumps(model, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def package_version(app_id, historical):
    return RECORD['packageVersion'] if app_id == APP else historical


def previous_xec_model(app_id, current):
    if app_id != APP:
        return copy.deepcopy(current)
    assert digest(current) == RECORD['afterModelSHA256']
    expected = {('services', 'ckpool', 'image'), ('services', 'app', 'environment', 'CKPOOL_IMAGE')}
    assert len(RECORD['changes']) == 2 and {tuple(row['path']) for row in RECORD['changes']} == expected
    restored = copy.deepcopy(current)
    for row in RECORD['changes']:
        node = restored
        for key in row['path'][:-1]:
            node = node[key]
        key = row['path'][-1]
        assert node[key] == row['after'] == RECORD['poolImageRef']
        assert row['before'] == 'ghcr.io/willitmod/ecash-ckpool-solo:18b38ad'
        node[key] = row['before']
    assert digest(restored) == RECORD['beforeModelSHA256']
    return restored


class XecPortableReleaseTests(unittest.TestCase):
    def test_only_pool_binary_references_change(self):
        current = yaml.safe_load((ROOT / APP / 'docker-compose.yml').read_text())
        previous_xec_model(APP, current)
        self.assertEqual(current['services']['app']['image'], RECORD['applicationImageUnchanged'])
        self.assertEqual(current['services']['xecd']['image'], RECORD['nodeImageUnchanged'])
        manifest = yaml.safe_load((ROOT / APP / 'umbrel-app.yml').read_text())
        self.assertEqual(manifest['version'], RECORD['packageVersion'])
        self.assertIn('portable SHA256', manifest['releaseNotes'])

    def test_unrelated_consensus_storage_and_pool_settings_are_rejected(self):
        current = yaml.safe_load((ROOT / APP / 'docker-compose.yml').read_text())
        for service, key, value in [('xecd', 'image', 'other-node'), ('ckpool', 'command', []),
                                    ('ckpool', 'volumes', []), ('app', 'environment', {})]:
            changed = copy.deepcopy(current)
            changed['services'][service][key] = value
            with self.subTest(service=service, field=key), self.assertRaises(AssertionError):
                previous_xec_model(APP, changed)

    def test_source_and_both_architectures_are_bound_without_full_runtime_claim(self):
        self.assertEqual(RECORD['upstreamSourceRevision'], '18b38ad886a4c7a323b5f9bdcf761704c669c223')
        self.assertEqual(RECORD['publicationRun'], 38626482142)
        self.assertEqual(set(RECORD['poolImages']), {'amd64', 'arm64'})
        for image in RECORD['poolImages'].values():
            for value in image.values():
                self.assertRegex(value, r'^sha256:[0-9a-f]{64}$')
        self.assertFalse(RECORD['validationScope']['fullAppManagerLifecycleQualified'])
        self.assertFalse(RECORD['validationScope']['miningProtocolQualified'])
