"""Direct-miner fix must update every mining app, not unrelated runtime state."""
import copy
import hashlib
import json
from pathlib import Path
import unittest

import yaml

ROOT = Path(__file__).resolve().parents[1]


class DirectHashrateReleaseTests(unittest.TestCase):
    def test_all_ten_apps_have_versioned_fixes_and_explanatory_notes(self):
        release = json.loads((ROOT / 'DIRECT-HASHRATE-2026-09-30.json').read_text())
        previous = json.loads((ROOT / release['supersedes']).read_text())
        self.assertEqual(set(release['apps']), set(previous['apps']))
        self.assertEqual(release['validationHost'], '10.10.10.235')
        expected = set(release['apps']) | {'willitmod-dev-5tratsmack'}
        self.assertEqual(set(release['runtimeContracts']), expected)
        self.assertEqual(len(expected), 10)
        for app_id in expected:
            with self.subTest(app=app_id):
                manifest = yaml.safe_load((ROOT / app_id / 'umbrel-app.yml').read_text())
                notes = manifest['releaseNotes']
                self.assertIn('Direct and mixed miners', notes)
                self.assertIn('matched worker identities', notes)
                if app_id in release['apps']:
                    record = release['apps'][app_id]
                    self.assertNotEqual(record['version'], previous['apps'][app_id]['version'])
                    self.assertNotEqual(record['imageRef'], previous['apps'][app_id]['imageRef'])
                    for field in ('runtimeTestsPassed', 'provenanceVerified', 'sbomVerified'):
                        self.assertIs(record[field], True)

    def test_full_runtime_contract_changes_only_reviewed_image_and_version_fields(self):
        release = json.loads((ROOT / 'DIRECT-HASHRATE-2026-09-30.json').read_text())
        for app_id, contract in release['runtimeContracts'].items():
            with self.subTest(app=app_id):
                model = yaml.safe_load((ROOT / app_id / 'docker-compose.yml').read_text())
                restored = copy.deepcopy(model)
                allowed = {('services', 'app', 'image'),
                           ('services', 'app', 'environment', 'APP_VERSION')}
                if app_id == 'willitmod-dev-powpow':
                    allowed.add(('services', 'pool', 'image'))
                if app_id == 'willitmod-dev-5tratsmack':
                    allowed.add(('services', 'swap', 'image'))
                    allowed.update(('services', 'app', 'environment', key) for key in
                                   ('APP_IMAGE', 'APP_REVISION', 'FIVETRAT_RELEASE_TAG'))
                self.assertEqual(len({tuple(row['path']) for row in contract['changes']}), len(contract['changes']))
                for row in contract['changes']:
                    self.assertIn(tuple(row['path']), allowed)
                    target = restored
                    for key in row['path'][:-1]:
                        target = target[key]
                    self.assertEqual(target[row['path'][-1]], row['after'])
                    target[row['path'][-1]] = row['before']
                digest = hashlib.sha256(json.dumps(restored, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
                self.assertEqual(digest, contract['baselineComposeSha256'])


if __name__ == '__main__':
    unittest.main()
