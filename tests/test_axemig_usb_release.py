"""Bind both Docker-socket helper and UI to the reviewed USB source fix."""
import copy
import hashlib
import json
from pathlib import Path
import unittest
import yaml
from test_axemig_stop_release import APP, previous_mig_stop_model, previous_mig_stop_manifest

ROOT = Path(__file__).resolve().parents[1]
RECORD = json.loads((ROOT / 'AXEMIG-USB-2026-10-14.json').read_text())
LATEST_PATH = ROOT / 'AXEMIG-CHAIN-DISCOVERY-2026-10-14.json'
LATEST = json.loads(LATEST_PATH.read_text()) if LATEST_PATH.exists() else None


def digest(model):
    return hashlib.sha256(json.dumps(model, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def historical_usb_model():
    model = previous_mig_stop_model(APP,yaml.safe_load((ROOT / 'willitmod-dev-axemig/docker-compose.yml').read_text()))
    if LATEST:
        assert digest(model) == LATEST['afterModelSHA256']
        assert {tuple(row['path']) for row in LATEST['changes']} == {
            ('services', 'server', 'image'),
            ('services', 'server', 'environment', 'APP_VERSION'),
            ('services', 'server', 'environment', 'AXEMIG_HELPER_IMAGE')}
        assert len(LATEST['changes']) == 3
        for row in LATEST['changes']:
            node = model
            for key in row['path'][:-1]:
                node = node[key]
            assert node[row['path'][-1]] == row['after']
            node[row['path'][-1]] = row['before']
        assert digest(model) == LATEST['beforeModelSHA256'] == RECORD['afterModelSHA256']
    return model


class AxemigUsbReleaseTests(unittest.TestCase):
    def test_only_three_runtime_fields_changed_and_helpers_are_identical(self):
        current = historical_usb_model()
        self.assertEqual(digest(current), RECORD['afterModelSHA256'])
        expected = {('services', 'server', 'image'), ('services', 'server', 'environment', 'APP_VERSION'),
                    ('services', 'server', 'environment', 'AXEMIG_HELPER_IMAGE')}
        self.assertEqual({tuple(row['path']) for row in RECORD['changes']}, expected)
        self.assertEqual(len(RECORD['changes']), 3)
        old = copy.deepcopy(current)
        for row in RECORD['changes']:
            node = old
            for key in row['path'][:-1]:
                node = node[key]
            key = row['path'][-1]
            self.assertEqual(node[key], row['after'])
            node[key] = row['before']
        self.assertEqual(digest(old), RECORD['beforeModelSHA256'])
        image = current['services']['server']['image']
        self.assertEqual(current['services']['server']['environment']['AXEMIG_HELPER_IMAGE'], image)
        self.assertEqual(image, 'ghcr.io/willitmod/axemig:0.1.22-dev@' + RECORD['digest'])

    def test_recipe_revision_blocks_older_recovery_bundle(self):
        manifest = previous_mig_stop_manifest(yaml.safe_load((ROOT / 'willitmod-dev-axemig/umbrel-app.yml').read_text()))
        self.assertEqual(manifest['version'], (LATEST or RECORD)['packageVersion'])
        self.assertEqual(RECORD['packageVersion'], '0.1.22-dev')
        self.assertIn('host paths', manifest['releaseNotes'])

    def test_actual_source_labels_are_bound_on_both_architectures(self):
        self.assertEqual(RECORD['source'], 'b140dd20e4e179ddd91b7fe60a404170b4288f1b')
        self.assertEqual(set(RECORD['platforms']), {'amd64', 'arm64'})
        self.assertEqual(len({r['source_tree'] for r in RECORD['platforms'].values()}), 1)
        self.assertFalse(RECORD['fullAppQualified'])
