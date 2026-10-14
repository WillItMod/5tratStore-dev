"""Bind the reporting-only image pin without weakening historical network checks."""
import copy
import hashlib
import json
from pathlib import Path
import subprocess
import unittest

import yaml

ROOT = Path(__file__).resolve().parents[1]
APP = 'willitmod-dev-axebench'
RECORD = json.loads((ROOT / 'BENCH-REPORTING-2026-10-14.json').read_text())


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def previous_bench_reporting_model(current):
    assert digest(current) == RECORD['afterModelSHA256'], 'Unreviewed Bench runtime change'
    restored = copy.deepcopy(current)
    assert restored['services']['server']['image'] == RECORD['imageRef']
    restored['services']['server']['image'] = 'ghcr.io/willitmod/axebench:v4.0.28-dev'
    assert digest(restored) == RECORD['beforeModelSHA256']
    return restored


def previous_bench_reporting_manifest(current):
    restored = copy.deepcopy(current)
    assert restored['version'] == RECORD['packageVersion']
    assert restored['releaseNotes'].startswith(RECORD['releaseNote'] + '\n')
    restored['version'] = '4.0.28-dev.2'
    restored['releaseNotes'] = restored['releaseNotes'][len(RECORD['releaseNote']) + 1:]
    assert digest(restored) == RECORD['beforeManifestSHA256']
    return restored


class BenchReportingReleaseTests(unittest.TestCase):
    def test_only_the_image_changes_in_the_entire_runtime_model(self):
        current = yaml.safe_load((ROOT / APP / 'docker-compose.yml').read_text())
        previous = previous_bench_reporting_model(current)
        baseline = yaml.safe_load(subprocess.check_output(['git', 'show', RECORD['baselineCommit'] + ':' + APP + '/docker-compose.yml'], cwd=ROOT))
        self.assertEqual(previous, baseline)
        self.assertNotIn('networks', current)

    def test_runtime_or_image_drift_is_refused(self):
        current = yaml.safe_load((ROOT / APP / 'docker-compose.yml').read_text())
        for service, key, value in [('server', 'image', 'changed:latest'), ('server', 'volumes', []),
                                    ('server', 'stop_grace_period', '5s'), ('server', 'environment', {}),
                                    ('app_proxy', 'environment', {'APP_HOST': 'changed'})]:
            changed = copy.deepcopy(current)
            changed['services'][service][key] = value
            with self.subTest(service=service, key=key), self.assertRaises(AssertionError):
                previous_bench_reporting_model(changed)
        changed = copy.deepcopy(current)
        changed['networks'] = {'default': {'ipam': {'config': [{'subnet': '172.31.51.0/24'}]}}}
        with self.assertRaises(AssertionError):
            previous_bench_reporting_model(changed)

    def test_manifest_only_changes_revision_and_prepends_the_reporting_note(self):
        current = yaml.safe_load((ROOT / APP / 'umbrel-app.yml').read_text())
        before = previous_bench_reporting_manifest(current)
        baseline = yaml.safe_load(subprocess.check_output(['git', 'show', RECORD['baselineCommit'] + ':' + APP + '/umbrel-app.yml'], cwd=ROOT))
        self.assertEqual(before, baseline)
        for key, value in [('id', 'different-id'), ('port', 9999), ('version', '4.0.29')]:
            changed = copy.deepcopy(current)
            changed[key] = value
            with self.subTest(key=key), self.assertRaises(AssertionError):
                previous_bench_reporting_manifest(changed)

    def test_published_both_native_platforms_are_bound_without_hardware_pass_claim(self):
        self.assertEqual(RECORD['sourceRevision'], '97091de5e5cc45ad91b61aca23bdde67b5067135')
        self.assertEqual(RECORD['publicationRun'], 38645247620)
        self.assertEqual(RECORD['baseIndex'], 'sha256:e96077e2a1e260bb84258d7629910cc26ec26823148120016e02a6e098769844')
        self.assertEqual(RECORD['packageVersion'], '4.0.28-dev.3')
        self.assertEqual(set(RECORD['images']), {'amd64', 'arm64'})
        for row in RECORD['images'].values():
            for value in row.values():
                self.assertRegex(value, r'^sha256:[a-f0-9]{64}$')
        self.assertFalse(RECORD['fullHardwareQualification'])
        self.assertEqual(set(RECORD['changedRuntimeFiles']), {'/app/python/web_interface.py', '/app/python/benchmark_engine.py'})
        self.assertEqual(RECORD['nativeBakedTestsPerArchitecture'], 41)

    def test_all_other_package_files_remain_byte_identical(self):
        names = subprocess.check_output(['git', 'ls-tree', '-r', '--name-only', RECORD['baselineCommit'], '--', APP], cwd=ROOT, text=True).splitlines()
        for name in names:
            if Path(name).name in {'docker-compose.yml', 'umbrel-app.yml'}:
                continue
            with self.subTest(path=name):
                self.assertEqual((ROOT / name).read_bytes(), subprocess.check_output(['git', 'show', RECORD['baselineCommit'] + ':' + name], cwd=ROOT))


if __name__ == '__main__':
    unittest.main()
