"""Protect the narrowly scoped Bench subnet correction and its runtime models."""
import copy
import hashlib
import ipaddress
import json
from pathlib import Path
import subprocess
import unittest

import yaml
from test_bench_reporting_release import previous_bench_reporting_model, previous_bench_reporting_manifest

ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / 'willitmod-dev-axebench'
RECORD = json.loads((ROOT / 'BENCH-NETWORK-2026-10-14.json').read_text())


def digest(model):
    return hashlib.sha256(json.dumps(model, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def previous_compose(model):
    """Reverse only the exact, separately reviewed removal for historical checks."""
    result = copy.deepcopy(model)
    if 'networks' in result:
        raise AssertionError('Bench must use the ordinary per-project default network')
    result['networks'] = copy.deepcopy(RECORD['removedDefaultNetwork'])
    if digest(result) != RECORD['baselineComposeModelSHA256']:
        raise AssertionError('Unexpected Bench service, image, mount, port or runtime change')
    return result


class BenchNetworkReleaseTests(unittest.TestCase):
    def test_exact_whole_compose_delta_preserves_all_services_and_runtime_inputs(self):
        model = previous_bench_reporting_model(yaml.safe_load((APP / 'docker-compose.yml').read_text()))
        previous_compose(model)
        self.assertEqual(model['services']['server']['image'], RECORD['unchangedImage'])
        for service in model['services'].values():
            self.assertNotIn('networks', service)

    def test_guard_rejects_additional_service_or_network_changes(self):
        current = previous_bench_reporting_model(yaml.safe_load((APP / 'docker-compose.yml').read_text()))
        for mutate in [lambda m: m['services']['server'].update(image='unreviewed:latest'),
                       lambda m: m['services']['server'].update(volumes=[]),
                       lambda m: m.update(networks={'default': {}}),
                       lambda m: m['services']['server'].update(ports=['5000:5000'])]:
            candidate = copy.deepcopy(current)
            mutate(candidate)
            with self.subTest(mutation=mutate), self.assertRaises(AssertionError):
                previous_compose(candidate)

    def test_exact_manifest_delta_is_only_revision_and_new_release_note(self):
        manifest = previous_bench_reporting_manifest(yaml.safe_load((APP / 'umbrel-app.yml').read_text()))
        self.assertEqual(manifest['version'], RECORD['packageVersion'])
        baseline = yaml.safe_load(subprocess.check_output([
            'git', 'show', RECORD['baseStoreCommit'] + ':' + APP.name + '/umbrel-app.yml'], cwd=ROOT, text=True))
        self.assertEqual(digest(baseline), RECORD['baselineManifestModelSHA256'])
        self.assertEqual(manifest['releaseNotes'],
                         'v4.0.28-dev.2 (recipe revision): Let Docker allocate the app network subnet '
                         'to avoid overlap with other installed apps.\n' + baseline['releaseNotes'])
        manifest['version'] = baseline['version']
        manifest['releaseNotes'] = baseline['releaseNotes']
        self.assertEqual(manifest, baseline)

    def test_captured_real_overlap_is_removed_without_replacing_it_with_a_fixed_subnet(self):
        healthy = ipaddress.ip_network(RECORD['observedHealthyBCH2Subnet'])
        bench = ipaddress.ip_network(RECORD['observedConflictingBenchSubnet'])
        self.assertTrue(healthy.overlaps(bench))
        baseline = previous_compose(previous_bench_reporting_model(yaml.safe_load((APP / 'docker-compose.yml').read_text())))
        self.assertEqual(baseline['networks']['default']['ipam']['config'], [{'subnet': str(bench)}])
        self.assertNotIn('networks', previous_bench_reporting_model(yaml.safe_load((APP / 'docker-compose.yml').read_text())))

    def test_umbrel174_parser_accepts_install_and_repeated_start(self):
        fixture = ROOT / 'tests/fixtures/umbrel_1_7_4_patch_compose.cjs'
        model = previous_bench_reporting_model(yaml.safe_load((APP / 'docker-compose.yml').read_text()))
        for _ in range(2):
            p = subprocess.run(['node', str(fixture)], input=json.dumps({'compose': model, 'id': APP.name}),
                               text=True, capture_output=True, check=True)
            model = json.loads(p.stdout)
        self.assertNotIn('networks', model)
        self.assertEqual(model['services']['server']['image'], RECORD['unchangedImage'])

    def test_existing_ownership_hook_and_every_other_package_file_are_unchanged(self):
        names = subprocess.check_output(['git', 'ls-tree', '-r', '--name-only',
                                         RECORD['baseStoreCommit'], '--', APP.name], cwd=ROOT, text=True).splitlines()
        changed = {str(APP.relative_to(ROOT) / name) for name in ['docker-compose.yml', 'umbrel-app.yml']}
        for name in names:
            if name in changed:
                continue
            with self.subTest(file=name):
                old = subprocess.check_output(['git', 'show', RECORD['baseStoreCommit'] + ':' + name], cwd=ROOT)
                self.assertEqual((ROOT / name).read_bytes(), old)
        self.assertTrue((APP / 'hooks/pre-start').stat().st_mode & 0o111)


if __name__ == '__main__':
    unittest.main()
