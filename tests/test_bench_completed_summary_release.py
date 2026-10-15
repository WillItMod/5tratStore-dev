"""One-image completed-card summary pin; frozen historical receipts stay exact."""
import copy
import hashlib
import json
from pathlib import Path
import subprocess
import unittest

import yaml

ROOT = Path(__file__).resolve().parents[1]
APP = 'willitmod-dev-axebench'
RECORD = json.loads((ROOT / 'BENCH-COMPLETED-SUMMARY-2026-10-15.json').read_text())


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def previous_bench_summary_model(current):
    assert digest(current) == RECORD['afterModelSHA256'], 'Unreviewed Bench summary runtime change'
    restored = copy.deepcopy(current)
    assert restored['services']['server']['image'] == RECORD['imageRef']
    restored['services']['server']['image'] = RECORD['previousImageRef']
    assert digest(restored) == RECORD['beforeModelSHA256']
    return restored


def previous_bench_summary_manifest(current):
    assert digest(current) == RECORD['afterManifestSHA256'], 'Unreviewed Bench summary manifest change'
    restored = copy.deepcopy(current)
    assert restored['version'] == RECORD['packageVersion']
    prefix = RECORD['releaseNote'] + '\n'
    assert restored['releaseNotes'].startswith(prefix)
    restored['version'] = RECORD['previousPackageVersion']
    restored['releaseNotes'] = restored['releaseNotes'][len(prefix):]
    assert digest(restored) == RECORD['beforeManifestSHA256']
    return restored


def original(path):
    return subprocess.check_output(['git', 'show', RECORD['baselineCommit'] + ':' + path], cwd=ROOT)


class BenchCompletedSummaryReleaseTests(unittest.TestCase):
    def test_only_server_image_changes_in_complete_runtime_model(self):
        current = yaml.safe_load((ROOT / APP / 'docker-compose.yml').read_text())
        before = previous_bench_summary_model(current)
        self.assertEqual(before, yaml.safe_load(original(APP + '/docker-compose.yml')))
        self.assertEqual(set(current), set(before))
        self.assertNotIn('networks', current)
        self.assertEqual(current['services']['server']['volumes'], ['${APP_DATA_DIR}/data:/data'])
        self.assertEqual(current['services']['server']['stop_grace_period'], '30s')

    def test_extra_image_control_mount_port_environment_or_network_delta_is_refused(self):
        current = yaml.safe_load((ROOT / APP / 'docker-compose.yml').read_text())
        for key, value in [('image', 'unreviewed:latest'), ('volumes', []), ('ports', ['5000:5000']),
                           ('environment', {}), ('stop_grace_period', '2s'), ('user', '0:0'), ('init', False)]:
            changed = copy.deepcopy(current); changed['services']['server'][key] = value
            with self.subTest(key=key), self.assertRaises(AssertionError):
                previous_bench_summary_model(changed)
        changed = copy.deepcopy(current); changed['networks'] = {'default': {'ipam': {}}}
        with self.assertRaises(AssertionError): previous_bench_summary_model(changed)

    def test_manifest_only_forwards_version_and_prepends_exact_release_note(self):
        current = yaml.safe_load((ROOT / APP / 'umbrel-app.yml').read_text())
        self.assertEqual(current['version'], '4.0.30-dev')
        self.assertEqual(previous_bench_summary_manifest(current), yaml.safe_load(original(APP + '/umbrel-app.yml')))
        for key, value in [('version', '4.0.29'), ('id', 'changed'), ('port', 9000),
                           ('releaseNotes', 'unreviewed note'), ('defaultPassword', 'unreviewed')]:
            changed = copy.deepcopy(current); changed[key] = value
            with self.subTest(key=key), self.assertRaises(AssertionError): previous_bench_summary_manifest(changed)

    def test_published_actual_native_payload_and_source_are_bound_without_guest_claim(self):
        self.assertEqual(RECORD['sourceRevision'], 'e2588087a489d83b903ba0f4b6a50a7a21928fe1')
        self.assertEqual(RECORD['sourceTree'], 'a4bd72d2a6b10c0a46c5f42a3c007757e0f11350')
        self.assertEqual(RECORD['publicationRun'], 38662526617)
        self.assertEqual(RECORD['imageRef'], 'ghcr.io/willitmod/axebench:v4.0.30-summary.e2588087a489@sha256:3d6a9bbaac5b3b70c6000c8bae174956b2c42d552c09f95aa1700b6c187a9b64')
        self.assertEqual(RECORD['changedRuntimeFiles'], ['/app/python/web_interface.py'])
        self.assertEqual(RECORD['nativeBakedTestsPerArchitecture'], 48)
        expected = {'amd64': 'sha256:ca5db7d880ebc10b57085b985dc801b95ddf97fe9fa32f7b878308fadff878bf',
                    'arm64': 'sha256:33df592a6c2f7b645a4f519428fffe58fad0a191f407162211d5431a65b69793'}
        self.assertEqual(set(RECORD['images']), set(expected))
        for arch, config in expected.items():
            row = RECORD['images'][arch]
            self.assertEqual(row['configDigest'], config)
            self.assertRegex(row['manifestDigest'], r'^sha256:[a-f0-9]{64}$')
            proof = RECORD['publishedNativePreservation'][arch]
            self.assertEqual(proof['candidate_config'], config)
            self.assertEqual(proof['source'], RECORD['sourceRevision'])
            self.assertEqual(proof['source_tree'], RECORD['sourceTree'])
            self.assertEqual(proof['only_rootfs_difference'], ['app/python/web_interface.py'])
            self.assertTrue(proof['all_other_files_modes_owners_links_exact'])
        self.assertTrue(RECORD['anonymousHashedSPDXSLSASubjectSourceAdmission'])
        self.assertFalse(RECORD['cryptographicSignerVerified'])
        self.assertFalse(RECORD['ordinaryGuestUpdateQualified'])
        self.assertFalse(RECORD['fullHardwareQualification'])
        self.assertTrue(RECORD['noNewHardwareBenchmark'])

    def test_every_other_package_file_and_uid_hook_mode_are_exact(self):
        rows = subprocess.check_output(['git', 'ls-tree', '-r', RECORD['baselineCommit'], '--', APP], cwd=ROOT, text=True).splitlines()
        for line in rows:
            header, name = line.split('\t', 1); mode = header.split()[0]
            if name in {APP + '/docker-compose.yml', APP + '/umbrel-app.yml'}: continue
            with self.subTest(path=name):
                self.assertEqual((ROOT / name).read_bytes(), original(name))
                self.assertEqual(bool((ROOT / name).stat().st_mode & 0o111), mode == '100755')
        self.assertTrue((ROOT / APP / 'hooks/pre-start').stat().st_mode & 0o111)

    def test_other_packages_and_all_frozen_bench_receipts_and_test_assertions_remain(self):
        rows = subprocess.check_output(['git', 'ls-tree', '-r', RECORD['baselineCommit']], cwd=ROOT, text=True).splitlines()
        for line in rows:
            header, name = line.split('\t', 1); mode, kind, blob = header.split()
            if not name.startswith('willitmod-') or name.startswith(APP + '/'): continue
            with self.subTest(path=name):
                actual = subprocess.check_output(['git', 'hash-object', '--path', name, name], cwd=ROOT, text=True).strip()
                self.assertEqual(actual, blob)
                if kind == 'blob': self.assertEqual(bool((ROOT / name).stat().st_mode & 0o111), mode == '100755')
        for name in ['BENCH-NETWORK-2026-10-14.json', 'BENCH-REPORTING-2026-10-14.json', 'tests/test_bench_network_release.py']:
            self.assertEqual((ROOT / name).read_bytes(), original(name))
        text = (ROOT / 'tests/test_bench_reporting_release.py').read_text()
        for addition in ['from test_bench_completed_summary_release import previous_bench_summary_model, previous_bench_summary_manifest\n',
                         '    current = previous_bench_summary_model(current)\n', '    current = previous_bench_summary_manifest(current)\n']:
            self.assertEqual(text.count(addition), 1); text = text.replace(addition, '', 1)
        self.assertEqual(text.encode(), original('tests/test_bench_reporting_release.py'))

    def test_umbrel174_normal_parser_retains_image_gateway_and_no_fixed_subnet(self):
        model = yaml.safe_load((ROOT / APP / 'docker-compose.yml').read_text())
        for _ in range(2):
            result = subprocess.run(['node', str(ROOT / 'tests/fixtures/umbrel_1_7_4_patch_compose.cjs')],
                                    input=json.dumps({'compose': model, 'id': APP}), text=True,
                                    capture_output=True, check=True)
            model = json.loads(result.stdout)
        self.assertEqual(model['services']['server']['image'], RECORD['imageRef'])
        self.assertEqual(model['services']['app_proxy']['environment']['APP_PORT'], 5000)
        self.assertNotIn('networks', model)


if __name__ == '__main__':
    unittest.main()
