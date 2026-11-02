"""Version correction changes store metadata while retaining deployed fixes."""
import importlib.util
import json
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import patch

import yaml

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location('version_correction_tests', ROOT / 'scripts/powpow_package_version_correction.py')
correction = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(correction)


class PowPowPackageVersionCorrectionTests(unittest.TestCase):
    def fixture(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name)
        shutil.copytree(ROOT / correction.APP, root / correction.APP)
        shutil.copytree(ROOT / 'powpow-release-records', root / 'powpow-release-records')
        for path in ROOT.glob('*.json'):
            shutil.copy2(path, root / path.name)
        shutil.copy2(ROOT / 'README.md', root / 'README.md')
        original = correction.git
        patcher = patch.object(correction, 'git', side_effect=lambda _root, *args: original(ROOT, *args))
        patcher.start()
        self.addCleanup(patcher.stop)
        return root

    def test_exact_store_version_preserves_notes_runtime_images_and_prior_evidence(self):
        self.assertEqual(correction.validate()['packageVersion'], '0.2.39')
        for name in correction.MANIFESTS:
            path = correction.APP + '/' + name
            before = yaml.safe_load(correction.baseline_bytes(path))
            current = yaml.safe_load((ROOT / path).read_text())
            self.assertEqual(current.pop('version'), '0.2.39')
            self.assertEqual(before.pop('version'), '0.2.37-dev.6')
            self.assertEqual(current, before)
        compose = correction.APP + '/docker-compose.yml'
        self.assertEqual((ROOT / compose).read_bytes(), correction.baseline_bytes(compose))

    def test_only_the_exact_manifest_version_can_be_normalized(self):
        for name in correction.MANIFESTS:
            previous = correction.baseline_bytes(correction.APP + '/' + name)
            current = correction.expected_bytes(correction.APP + '/' + name)
            self.assertEqual(correction.previous_manifest_bytes(name, previous), previous)
            self.assertEqual(correction.previous_manifest_bytes(name, current), previous)
            for altered in (current + b'# changed notes\n', current.replace(b'0.2.39', b'0.2.39-dev', 1)):
                with self.assertRaises(AssertionError):
                    correction.previous_manifest_bytes(name, altered)
        with self.assertRaises(AssertionError):
            correction.previous_manifest_bytes('docker-compose.yml', b'anything')
        self.assertEqual(correction.package_version(correction.APP, '0.2.37-dev.6'), '0.2.39')
        with self.assertRaises(AssertionError):
            correction.package_version(correction.APP, '0.2.39-dev')

    def test_runtime_prior_record_proof_extra_file_and_mode_drift_are_rejected(self):
        root = self.fixture()
        correction.validate(root)
        for name in [correction.APP + '/docker-compose.yml', correction.APP + '/umbrel-app.yml',
                     'POWPOW-SHARE-PARTITION-2026-11-02.json',
                     'powpow-release-records/share-partition-20261102-publication.json', 'README.md']:
            path = root / name
            before = path.read_bytes()
            path.write_bytes(before + b'\n# unreviewed\n')
            try:
                with self.subTest(name=name), self.assertRaises(AssertionError):
                    correction.validate(root)
            finally:
                path.write_bytes(before)
        extra = root / correction.APP / 'unreviewed.yml'
        extra.write_text('extra')
        with self.assertRaisesRegex(AssertionError, 'inventory'):
            correction.validate(root)
        extra.unlink()
        manifest = root / correction.APP / 'umbrel-app.yml'
        manifest.chmod(0o600)
        with self.assertRaisesRegex(AssertionError, 'mode'):
            correction.validate(root)

    def test_an_editable_correction_record_cannot_authorize_a_different_version(self):
        root = self.fixture()
        path = root / correction.RECORD_NAME
        row = json.loads(path.read_text())
        row['packageVersion'] = '0.2.39-dev'
        path.write_text(json.dumps(row))
        with self.assertRaisesRegex(AssertionError, 'record'):
            correction.validate(root)


if __name__ == '__main__':
    unittest.main()
