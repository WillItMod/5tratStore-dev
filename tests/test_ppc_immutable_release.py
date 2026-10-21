"""Bind the paired PPC release; reverse only its exact seven runtime fields."""
import copy
import hashlib
import json
from pathlib import Path
import subprocess
import unittest

import yaml
import importlib.util

_SUCCESSOR_SPEC = importlib.util.spec_from_file_location("ppc_payout_status_successor", Path(__file__).resolve().parents[1] / "scripts/ppc_payout_status_release.py")
successor = importlib.util.module_from_spec(_SUCCESSOR_SPEC)
_SUCCESSOR_SPEC.loader.exec_module(successor)

ROOT = Path(__file__).resolve().parents[1]
APP = 'willitmod-dev-ppc'
RECORD = json.loads((ROOT / 'PPC-IMMUTABLE-NODE-2026-10-14.json').read_text())
BASELINE = 'aa972f0c38e18eaf2f4ca1b89ad3479600a66d27bd37e22a91f9f1765e1b58fa'
OLD_APP = 'ghcr.io/willitmod/axeppc-app-umbrel-dev:0.2.37-mux.d59c9d2e2501@sha256:2b48e067bb72a243f5f12b8ff4fc1ba9bb2a8e84949d569fc71c92b00f853a0f'


def digest(model):
    return hashlib.sha256(json.dumps(model, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def package_version(app_id, historical):
    return successor.package_version(app_id, RECORD['packageVersion']) if app_id == APP else historical


def previous_ppc_model(app_id, current):
    current = successor.previous_model(app_id, current)
    if app_id != APP:
        return copy.deepcopy(current)
    assert RECORD['beforeModelSHA256'] == BASELINE
    assert digest(current) == RECORD['afterModelSHA256']
    expected = {
        ('services', 'ppcd', 'build'): (True, {'context': '${APP_DATA_DIR}/data/peercoind'}, False, None),
        ('services', 'ppcd', 'image'): (False, None, True, RECORD['nodeImageRef']),
        ('services', 'ppcd', 'stop_signal'): (False, None, True, 'SIGTERM'),
        ('services', 'ppcd', 'stop_grace_period'): (False, None, True, '2m'),
        ('services', 'app', 'image'): (True, OLD_APP, True, RECORD['imageRef']),
        ('services', 'app', 'environment', 'PPCD_IMAGE'): (True, '', True, RECORD['nodeImageRef']),
        ('services', 'app', 'environment', 'APP_VERSION_SUFFIX'): (True, '-dev', True, '-dev.1'),
    }
    assert len(RECORD['changes']) == len(expected)
    assert {tuple(r['path']) for r in RECORD['changes']} == set(expected)
    restored = copy.deepcopy(current)
    for row in RECORD['changes']:
        target = restored
        for key in row['path'][:-1]:
            target = target[key]
        key = row['path'][-1]
        assert (row['beforeExists'], row.get('before'), row['afterExists'], row.get('after')) == expected[tuple(row['path'])]
        assert (key in target) == row['afterExists']
        if row['afterExists']:
            assert target[key] == row['after']
        if row['beforeExists']:
            target[key] = copy.deepcopy(row['before'])
        else:
            del target[key]
    assert digest(restored) == BASELINE
    return restored


class PpcImmutableReleaseTests(unittest.TestCase):
    def test_exact_full_runtime_reversal_retains_every_other_field(self):
        current = yaml.safe_load((ROOT / APP / 'docker-compose.yml').read_text())
        previous = previous_ppc_model(APP, current)
        baseline = yaml.safe_load(subprocess.check_output(['git', 'show', RECORD['baselineCommit'] + ':' + APP + '/docker-compose.yml'], cwd=ROOT, text=True))
        self.assertEqual(previous, baseline)
        self.assertEqual(current['services']['pool'], baseline['services']['pool'])
        self.assertEqual(current['services']['init'], baseline['services']['init'])
        self.assertEqual(current['services']['redis'], baseline['services']['redis'])
        self.assertEqual(current['services']['ppcd']['user'], '1000:1000')
        self.assertEqual(current['services']['ppcd']['volumes'], baseline['services']['ppcd']['volumes'])

    def test_wrong_shutdown_image_configuration_mount_or_pool_change_is_refused(self):
        model = yaml.safe_load((ROOT / APP / 'docker-compose.yml').read_text())
        for service, key, value in [('ppcd', 'stop_signal', 'SIGKILL'), ('ppcd', 'stop_grace_period', '10s'),
                                    ('ppcd', 'volumes', []), ('ppcd', 'environment', {'DB_CACHE': '2048'}),
                                    ('ppcd', 'build', {'context': 'unreviewed'}), ('ppcd', 'image', 'moving:latest'),
                                    ('pool', 'image', 'changed-pool'), ('init', 'command', []),
                                    ('app', 'stop_signal', 'SIGTERM'), ('app', 'networks', {})]:
            changed = copy.deepcopy(model)
            changed['services'][service][key] = value
            with self.subTest(service=service, key=key), self.assertRaises(AssertionError):
                previous_ppc_model(APP, changed)

    def test_manifest_only_advances_recipe_version_and_prepends_release_note(self):
        current = successor.previous_manifest(APP, yaml.safe_load((ROOT / APP / 'umbrel-app.yml').read_text()))
        before = yaml.safe_load(subprocess.check_output(['git', 'show', RECORD['baselineCommit'] + ':' + APP + '/umbrel-app.yml'], cwd=ROOT, text=True))
        self.assertEqual(current.pop('version'), '0.2.37-dev.1')
        self.assertEqual(before.pop('version'), '0.2.37-dev')
        notes, old_notes = current.pop('releaseNotes'), before.pop('releaseNotes')
        self.assertTrue(notes.endswith('\n' + old_notes))
        self.assertIn('same official Peercoin 0.15.1ppc binaries', notes)
        self.assertIn('two minutes', notes)
        self.assertEqual(current, before)

    def test_published_source_and_native_binary_bindings_are_immutable(self):
        self.assertEqual(RECORD['sourceRevision'], '5b0aac96a4757f3d2039560b8a006dc23ba0d5b2')
        self.assertEqual(RECORD['nodeSourceRevision'], '602518e559dfc7ebeb9a14a3abcf15879fd5e8d7')
        self.assertEqual(RECORD['nodePublicationRun'], 38643836636)
        self.assertTrue(RECORD['imageRef'].endswith('@sha256:df22d1f1ba4f607d7422945cbdb0ec4ad348b9ce7ddd578d8179849db45d536d'))
        self.assertTrue(RECORD['nodeImageRef'].endswith('@sha256:41bebfa7003bfc3073cae18345abd55da8831288277b1c4185114e91ef437e75'))
        self.assertEqual(set(RECORD['nodeImages']), {'amd64', 'arm64'})
        for arch, row in RECORD['nodeBinaryWrapperTiniBindings'].items():
            self.assertEqual(set(row['files']), {'peercoind', 'peercoin-cli', 'peercoin-tx', 'peercoind-wrapper.sh', 'tini'})
            for binding in row['files'].values():
                self.assertRegex(binding['sha256'], r'^[a-f0-9]{64}$')
                self.assertEqual((binding['mode'], binding['uid'], binding['gid']), ('0o755', 0, 0))
                self.assertGreater(binding['bytes'], 0)
        self.assertFalse(RECORD['validationScope']['actualFullMainnetGracefulStopQualified'])
        self.assertFalse(RECORD['validationScope']['miningProtocolQualified'])

    def test_all_non_runtime_package_files_are_unchanged(self):
        names = subprocess.check_output(['git', 'ls-tree', '-r', '--name-only', RECORD['baselineCommit'], '--', APP], cwd=ROOT, text=True).splitlines()
        for name in names:
            if Path(name).name in {'docker-compose.yml', 'umbrel-app.yml'}:
                continue
            with self.subTest(path=name):
                self.assertEqual((ROOT / name).read_bytes(), subprocess.check_output(['git', 'show', RECORD['baselineCommit'] + ':' + name], cwd=ROOT))

    def test_other_adapters_and_models_remain_disjoint(self):
        from test_bch2_node_entrypoint_release import APP as BCH2, previous_bch2_node_model
        model = yaml.safe_load((ROOT / BCH2 / 'docker-compose.yml').read_text())
        self.assertEqual(previous_ppc_model(BCH2, model), model)
        previous_bch2_node_model(BCH2, previous_ppc_model(BCH2, model))
        ppc = yaml.safe_load((ROOT / APP / 'docker-compose.yml').read_text())
        self.assertEqual(previous_bch2_node_model(APP, ppc), ppc)
        self.assertEqual(package_version(BCH2, 'retained-version'), 'retained-version')


if __name__ == '__main__':
    unittest.main()
