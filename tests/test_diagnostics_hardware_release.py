"""Hardware release admission rejects changes outside the reviewed package."""
import copy
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

import yaml

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location('diagnostics_hardware_release', ROOT / 'scripts/diagnostics_hardware_release.py')
release = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(release)


class DiagnosticsHardwareReleaseTests(unittest.TestCase):
    def test_published_package_and_full_predecessor_are_exact(self):
        row = release.validate()
        self.assertEqual(row['validation']['compiledArchitectures'], ['amd64', 'arm64'])
        for name in ('docker-compose.yml', 'global-app.yml'):
            current = yaml.safe_load((ROOT / release.APP / name).read_text())
            self.assertEqual(release.previous_model(release.APP, current, filename=name),
                             yaml.safe_load(release.baseline_bytes(ROOT, release.APP + '/' + name)))

    def test_privileges_devices_images_and_support_changes_are_rejected(self):
        current = yaml.safe_load((ROOT / release.APP / 'docker-compose.yml').read_text())
        for service, field, value in (
            ('drive-probe', 'network_mode', 'host'),
            ('drive-probe', 'cap_add', ['ALL']),
            ('drive-probe', 'volumes', ['/dev:/host/dev']),
            ('drive-probe', 'command', ['smartctl', '--test=long', '/dev/sda']),
            ('app', 'image', 'unreviewed:latest'),
            ('app', 'volumes', current['services']['app']['volumes'] + ['/var/run/docker.sock:/var/run/docker.sock']),
            ('support-relay', 'image', 'changed:latest'),
        ):
            with self.subTest(service=service, field=field), self.assertRaises(AssertionError):
                changed = copy.deepcopy(current)
                changed['services'][service][field] = value
                release.previous_model(release.APP, changed)

    def test_manifest_port_version_and_notes_changes_are_rejected(self):
        current = yaml.safe_load((ROOT / release.APP / 'global-app.yml').read_text())
        for field, value in (('port', 9999), ('version', '0.2.0'), ('releaseNotes', 'replacement')):
            with self.subTest(field=field), self.assertRaises(AssertionError):
                changed = copy.deepcopy(current)
                changed[field] = value
                release.previous_model(release.APP, changed, filename='global-app.yml')

    def test_editable_record_cannot_authorize_new_package(self):
        row = release.record()
        row['packageFiles'][release.APP + '/docker-compose.yml']['afterSHA256'] = '0' * 64
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / release.RECORD).write_text(json.dumps(row))
            with self.assertRaises(AssertionError):
                release.record(root)

    def test_historical_adapter_keeps_unrelated_protected_paths(self):
        protected = sorted(release.CHANGED) + ['willitmod-dev-btc/docker-compose.yml']
        self.assertEqual(release.historical_protected_paths(ROOT, release.BASELINE, protected),
                         ['willitmod-dev-btc/docker-compose.yml'])
        with self.assertRaises(AssertionError):
            release.historical_protected_paths(ROOT, release.BASELINE, protected[1:])

    def test_public_record_excludes_private_test_host_and_configuration(self):
        text = (ROOT / release.RECORD).read_text()
        for private in ('/Users/', '/home/forge', '10.10.10.', 'APP_PASSWORD', 'controller.key'):
            self.assertNotIn(private, text)


if __name__ == '__main__':
    unittest.main()
