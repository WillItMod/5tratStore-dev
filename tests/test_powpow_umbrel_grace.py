"""Mirror the existing native flush policy in standard Umbrel Compose fields."""
import copy
import hashlib
import json
from pathlib import Path
import subprocess
import unittest

import yaml

ROOT = Path(__file__).resolve().parents[1]
APP = 'willitmod-dev-powpow'
RECORD = json.loads((ROOT / 'POWPOW-UMBREL-GRACE-2026-10-15.json').read_text())
BEFORE = 'b8261ee23b102026559c7ca52c3f0a19cb907c097f3c987ba72a9fef23878b28'
AFTER = 'a168daf8222ae4f7ada91e27f4e3799075f82a390b981df7f8ab1a1860f5a836'


def digest(model):
    return hashlib.sha256(json.dumps(model, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def package_version(app_id, historical):
    if app_id != APP:
        return historical
    assert historical == RECORD['previousPackageVersion'] == '0.2.37-dev.3'
    assert RECORD['packageVersion'] == '0.2.37-dev.4'
    return RECORD['packageVersion']


def previous_grace_model(app_id, model):
    restored = copy.deepcopy(model)
    if app_id != APP:
        return restored
    assert RECORD['beforeModelSHA256'] == BEFORE
    assert digest(restored) == RECORD['afterModelSHA256'] == AFTER
    expected = []
    for name in ['litecoin', 'dogecoin']:
        policy = restored['x-5tratumos-stop-policy']['services'][name]
        assert policy == {'stop_signal': 'SIGTERM', 'stop_grace_period': '15m30s', 'user': '1000:1000'}
        for field in ['stop_signal', 'stop_grace_period']:
            assert restored['services'][name].pop(field) == policy[field]
            expected.append({'path': ['services', name, field], 'beforePresent': False, 'after': policy[field]})
    assert RECORD['changes'] == expected
    assert digest(restored) == BEFORE
    return restored


def previous_grace_workflow(current):
    assert hashlib.sha256(current.encode()).hexdigest() == RECORD['afterWorkflowSHA256']
    for value in ['POWPOW-UMBREL-GRACE-2026-10-15.json', 'tests/test_powpow_umbrel_grace.py']:
        line = '      - "' + value + '"\n'
        assert current.count(line) == 2
        current = current.replace(line, '')
    assert hashlib.sha256(current.encode()).hexdigest() == RECORD['beforeWorkflowSHA256']
    return current


class PowPowUmbrelGraceTests(unittest.TestCase):
    def model(self):
        return yaml.safe_load((ROOT / APP / 'docker-compose.yml').read_text())

    def historical(self, name):
        return subprocess.check_output(['git', 'show', RECORD['baselineCommit'] + ':' + name], cwd=ROOT)

    def test_exact_four_fields_match_native_and_reverse_to_published_dev3(self):
        model = self.model()
        old = yaml.safe_load(self.historical(APP + '/docker-compose.yml'))
        self.assertEqual(previous_grace_model(APP, model), old)
        self.assertEqual(model['x-5tratumos-stop-policy'], old['x-5tratumos-stop-policy'])
        self.assertEqual({n: s['image'] for n, s in model['services'].items() if 'image' in s}, RECORD['imagesUnchanged'])
        self.assertEqual({n: s for n, s in model['services'].items() if n not in {'litecoin', 'dogecoin'}},
                         {n: s for n, s in old['services'].items() if n not in {'litecoin', 'dogecoin'}})

    def test_signal_deadline_and_unrelated_model_drift_are_rejected(self):
        for name, field, value in [('litecoin', 'stop_signal', 'SIGKILL'), ('dogecoin', 'stop_grace_period', '10s'),
                                   ('pool', 'environment', {'WAIT_FOR_FULL_SYNC': '0'}),
                                   ('app', 'image', 'changed:latest'), ('postgres', 'volumes', [])]:
            altered = self.model()
            altered['services'][name][field] = value
            with self.subTest(name=name, field=field), self.assertRaises(AssertionError):
                previous_grace_model(APP, altered)
        altered = self.model()
        altered['x-5tratumos-stop-policy']['services']['litecoin']['stop_grace_period'] = '10s'
        with self.assertRaises(AssertionError):
            previous_grace_model(APP, altered)

    def test_ci_workflow_reverses_only_four_exact_filter_lines(self):
        name = '.github/workflows/validate-mux-app-packages.yml'
        current = (ROOT / name).read_text()
        before = subprocess.check_output(['git', 'show', RECORD['workflowBaselineCommit'] + ':' + name], cwd=ROOT, text=True)
        self.assertEqual(previous_grace_workflow(current), before)
        for altered in [current + '# unrelated change\n', current.replace('tests/test_powpow_umbrel_grace.py', 'unreviewed.py', 1)]:
            with self.assertRaises(AssertionError):
                previous_grace_workflow(altered)

    def test_manifests_advance_recipe_only_and_keep_all_previous_notes(self):
        for name in ['global-app.yml', 'umbrel-app.yml']:
            current = yaml.safe_load((ROOT / APP / name).read_text())
            before = yaml.safe_load(self.historical(APP + '/' + name))
            self.assertEqual(current.pop('version'), package_version(APP, before.pop('version')))
            notes, old_notes = current.pop('releaseNotes'), before.pop('releaseNotes')
            self.assertTrue(notes.endswith('\n' + old_notes))
            self.assertIn('Umbrel as well as 5tratumOS', notes)
            self.assertEqual(current, before)
        self.assertEqual((ROOT / APP / 'global-app.yml').read_bytes(), (ROOT / APP / 'umbrel-app.yml').read_bytes())

    def test_all_other_package_bytes_modes_and_membership_remain_exact(self):
        entries = subprocess.check_output(['git', 'ls-tree', '-r', RECORD['baselineCommit'], '--', APP], cwd=ROOT, text=True).splitlines()
        names = []
        for entry in entries:
            metadata, name = entry.split('\t')
            names.append(name)
            path = ROOT / name
            if path.name not in {'docker-compose.yml', 'global-app.yml', 'umbrel-app.yml'}:
                self.assertEqual(path.read_bytes(), self.historical(name), name)
            self.assertEqual(bool(path.stat().st_mode & 0o111), metadata.split()[0] == '100755', name)
        self.assertEqual(sorted(str(p.relative_to(ROOT)) for p in (ROOT / APP).rglob('*') if p.is_file()), sorted(names))

    def test_real_runtime_and_mining_qualification_are_not_claimed_by_source(self):
        self.assertEqual(RECORD['qualification'], {'sourceOnly': True, 'actualInstalledCandidatePolicyVerified': False,
                                                 'actualNodeStopRetentionVerified': False, 'miningProtocolQualified': False})
        unrelated = {'services': {'app': {'image': 'unchanged'}}}
        self.assertEqual(previous_grace_model('willitmod-dev-ppc', unrelated), unrelated)
        self.assertEqual(package_version('willitmod-dev-ppc', 'unchanged'), 'unchanged')
        for invalid in ['0.2.37-dev.2', 'unknown']:
            with self.assertRaises(AssertionError):
                package_version(APP, invalid)


if __name__ == '__main__':
    unittest.main()
