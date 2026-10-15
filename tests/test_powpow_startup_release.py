"""Bind the COPY-only pool overlay; reverse exactly one image before old contracts."""
import copy
import hashlib
import json
from pathlib import Path
import subprocess
import unittest

import yaml
from test_axemig_stop_release import previous_mig_stop_workflow
from test_powpow_umbrel_grace import previous_grace_model, previous_grace_workflow, package_version as grace_package_version

ROOT = Path(__file__).resolve().parents[1]
APP = 'willitmod-dev-powpow'
RECORD = json.loads((ROOT / 'POWPOW-STARTUP-SHUTDOWN-2026-10-15.json').read_text())
BASELINE = '733f1fc1c8f6ea1fe538f4b29cd1db38d9a6c68adff555f342b77f0f8f7fdaab'
OLD = 'ghcr.io/willitmod/powpow-pool:0.2.37-mux.88f8fc0af57e@sha256:fdedad44cc7c7700eb3043884979785a02d9915bf5a70c5b50d2f52f6ba758d8'
NEW = 'ghcr.io/willitmod/powpow-pool:0.2.37-pool-startup.a443d6f3e552@sha256:b89d5e8c8e078fb200690b1b7ce941c2c995b18ba9cfa699ccac08ff6ddebea8'


def digest(model):
    return hashlib.sha256(json.dumps(model, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def package_version(app_id, historical):
    if app_id != APP:
        return historical
    assert historical == RECORD['previousPackageVersion'] == '0.2.37-dev.2'
    assert RECORD['packageVersion'] == '0.2.37-dev.3'
    return grace_package_version(app_id, RECORD['packageVersion'])


def previous_startup_model(app_id, current):
    if app_id != APP:
        return copy.deepcopy(current)
    current = previous_grace_model(app_id, current)
    assert RECORD['beforeModelSHA256'] == BASELINE
    assert RECORD['previousPoolImageRef'] == OLD
    assert RECORD['poolImageRef'] == NEW
    assert RECORD['changes'] == [{'path': ['services', 'pool', 'image'], 'before': OLD, 'after': NEW}]
    assert digest(current) == RECORD['afterModelSHA256']
    restored = copy.deepcopy(current)
    assert restored['services']['pool']['image'] == NEW
    restored['services']['pool']['image'] = OLD
    assert digest(restored) == BASELINE
    return restored


class PowPowStartupReleaseTests(unittest.TestCase):
    def test_whole_runtime_reversal_changes_only_pool_image(self):
        model = yaml.safe_load((ROOT / APP / 'docker-compose.yml').read_text())
        before = yaml.safe_load(subprocess.check_output(['git', 'show', RECORD['baselineCommit'] + ':' + APP + '/docker-compose.yml'], cwd=ROOT))
        self.assertEqual(previous_startup_model(APP, model), before)
        normalized = previous_grace_model(APP, model)
        for service in model['services']:
            if service != 'pool':
                self.assertEqual(normalized['services'][service], before['services'][service])
        self.assertEqual({n: s['image'] for n, s in model['services'].items() if 'image' in s and n != 'pool'}, RECORD['imagesUnchanged'])
        self.assertEqual(model['services']['app']['environment']['APP_VERSION'], RECORD['applicationVersionUnchanged'])
        self.assertEqual(model['services']['app']['environment']['APP_CHANNEL'], RECORD['applicationChannelUnchanged'])

    def test_unreviewed_images_config_seeds_mounts_wait_policy_or_shutdown_are_refused(self):
        model = yaml.safe_load((ROOT / APP / 'docker-compose.yml').read_text())
        mutations = [('pool', 'image', 'moving:latest'), ('pool', 'environment', {'WAIT_FOR_FULL_SYNC': '0'}),
                     ('pool', 'volumes', []), ('pool', 'stop_grace_period', '1s'),
                     ('app', 'image', 'changed-ui:latest'), ('litecoin', 'image', 'changed-node:latest'),
                     ('postgres', 'volumes', []), ('init_permissions', 'command', ['true'])]
        for service, key, value in mutations:
            changed = copy.deepcopy(model)
            changed['services'][service][key] = value
            with self.subTest(service=service, key=key), self.assertRaises(AssertionError):
                previous_startup_model(APP, changed)

    def test_both_manifests_advance_only_recipe_version_and_prepend_notes(self):
        for name in ['global-app.yml', 'umbrel-app.yml']:
            current = yaml.safe_load((ROOT / APP / name).read_text())
            before = yaml.safe_load(subprocess.check_output(['git', 'show', RECORD['baselineCommit'] + ':' + APP + '/' + name], cwd=ROOT))
            self.assertEqual(current.pop('version'), package_version(APP, before.pop('version')))
            notes, old_notes = current.pop('releaseNotes'), before.pop('releaseNotes')
            self.assertTrue(notes.endswith('\n' + old_notes))
            self.assertIn('bounded RPC attempts', notes)
            self.assertIn('full-sync requirements are retained', notes)
            self.assertEqual(current, before)
        self.assertEqual((ROOT / APP / 'global-app.yml').read_bytes(), (ROOT / APP / 'umbrel-app.yml').read_bytes())

    def test_other_package_files_and_modes_stay_exact(self):
        entries = subprocess.check_output(['git', 'ls-tree', '-r', RECORD['baselineCommit'], '--', APP], cwd=ROOT, text=True).splitlines()
        expected = []
        for row in entries:
            metadata, name = row.split('\t')
            mode = metadata.split()[0]
            expected.append(name)
            p = ROOT / name
            if p.name not in {'docker-compose.yml', 'global-app.yml', 'umbrel-app.yml'}:
                self.assertEqual(p.read_bytes(), subprocess.check_output(['git', 'show', RECORD['baselineCommit'] + ':' + name], cwd=ROOT))
            self.assertEqual(bool(p.stat().st_mode & 0o111), mode == '100755', name)
        self.assertEqual(sorted(str(p.relative_to(ROOT)) for p in (ROOT / APP).rglob('*') if p.is_file()), sorted(expected))

    def test_exact_published_source_platforms_and_limited_qualification(self):
        self.assertEqual(RECORD['sourceRevision'], 'a443d6f3e5528a5689cf8bd8d40aa6620317d20d')
        self.assertEqual(RECORD['retainedSourceRevision'], '88f8fc0af57e4731533c79f7d8f8f4936d629f6b')
        self.assertEqual(RECORD['publicationRun'], 38655938879)
        self.assertEqual(RECORD['entrypointSHA256'], '4b61f39da8ee3e36f68b2c95039244497ad7e9635b6130e240e7133140e7063e')
        self.assertEqual(RECORD['nativeImages']['amd64']['configDigest'], 'sha256:440f0498d037b595f9981968ef2b72d4077aa939a91723b6ae18c2ae5f563470')
        self.assertEqual(RECORD['nativeImages']['arm64']['configDigest'], 'sha256:424e1308cfee07d0c670515c4d3fbddf9bf13e1c0f17547f290cf5913ae2829d')
        self.assertFalse(RECORD['provenance']['cryptographicSignerVerificationClaimed'])
        for key in ['actualFullChainIBDStopQualified', 'actualAppLifecycleQualified', 'miningProtocolQualified']:
            self.assertFalse(RECORD['validationScope'][key])

    def test_workflow_only_adds_record_and_test_to_both_filters(self):
        name = '.github/workflows/validate-mux-app-packages.yml'
        current = (ROOT / name).read_text()
        current = previous_mig_stop_workflow(previous_grace_workflow(current))
        for value in ['POWPOW-STARTUP-SHUTDOWN-2026-10-15.json', 'tests/test_powpow_startup_release.py']:
            line = '      - "' + value + '"\n'
            self.assertEqual(current.count(line), 2)
            current = current.replace(line, '')
        self.assertEqual(current, subprocess.check_output(['git', 'show', RECORD['baselineCommit'] + ':' + name], cwd=ROOT, text=True))

    def test_historical_seed_and_other_app_adapters_stay_strict_and_disjoint(self):
        from test_powpow_sql_seed import previous_powpow_model, RECORD as SEED
        model = yaml.safe_load((ROOT / APP / 'docker-compose.yml').read_text())
        self.assertEqual(digest(previous_powpow_model(APP, model)), SEED['beforeModelSHA256'])
        other = {'services': {'app': {'image': 'retained'}}}
        self.assertEqual(previous_startup_model('willitmod-dev-ppc', other), other)
        self.assertEqual(package_version('willitmod-dev-ppc', 'retained'), 'retained')
        for version in ['0.2.37-dev', 'unreviewed']:
            with self.assertRaises(AssertionError):
                package_version(APP, version)


if __name__ == '__main__':
    unittest.main()
