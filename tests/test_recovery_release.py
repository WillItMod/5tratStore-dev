"""Current Dev recovery release, undone exactly before historical contracts."""
import copy
import hashlib
import json
from pathlib import Path
import re
import unittest
import yaml

ROOT = Path(__file__).resolve().parents[1]
RELEASE = json.loads((ROOT / 'RECOVERY-2026-10-02.json').read_text())
APPS = RELEASE['apps']
SMACK = 'willitmod-dev-5tratsmack'
DIAG = 'willitmod-dev-5tratumos-diagnostics'
EVIDENCE_MOUNT = '/var/lib/5tratumos/diagnostics/mux:/host/mux-evidence:ro'
BASELINES = {
    SMACK: '59f74e5fbfae0ef867586138973498828112e348308e6535ef89c5baad4ac41d',
    DIAG: '849c279816c5a9342a19dc43902fc4575bfe528da83d01853cbc1d1f77af4099',
}
IDENTITIES = {
    SMACK: ('0.11.20', '25cb1e900fc22fa6123d0916e7610bd4e4d56f2f',
            'ghcr.io/willitmod/5tratsmack-app:0.11.20@sha256:a5e66106dbc48d9c70e869ec8baed190913e26075de2b331da8316d3695bc5ae'),
    DIAG: ('0.1.8', '1331bfc6d6968ec251e82412c25c2d0c1143d175',
           'ghcr.io/willitmod/5tratumos-diagnostics:0.1.8@sha256:2d1d1bd59a7706257ac13dd6c3733aac8ef3cd798fa18ce8f1b44fdc2245e48f'),
}

def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':')).encode()).hexdigest()

def previous_recovery_model(app_id, current, filename='docker-compose.yml'):
    if app_id not in APPS:
        return copy.deepcopy(current)
    record = APPS[app_id]
    assert (record['version'], record['sourceRevision'], record['imageRef']) == IDENTITIES[app_id]
    contract = RELEASE['runtimeContracts'][app_id][filename]
    assert contract['beforeModelSHA256'] == BASELINES[app_id]
    assert digest(current) == contract['afterModelSHA256']
    expected = {('services', 'app', 'image')}
    keys = ('APP_VERSION', 'APP_REVISION', 'APP_IMAGE', 'FIVETRAT_RELEASE_TAG') if app_id == SMACK else ('APP_VERSION', 'APP_REVISION')
    expected.update(('services', 'app', 'environment', k) for k in keys)
    if app_id == DIAG:
        expected.add(('services', 'app', 'volumes'))
    assert len(contract['changes']) == len(expected)
    assert {tuple(row['path']) for row in contract['changes']} == expected
    values = {'image': record['imageRef'], 'APP_IMAGE': record['imageRef'],
              'APP_VERSION': record['version'], 'FIVETRAT_RELEASE_TAG': record['version'],
              'APP_REVISION': record['sourceRevision']}
    restored = copy.deepcopy(current)
    for row in contract['changes']:
        node = restored
        for key in row['path'][:-1]:
            node = node[key]
        key = row['path'][-1]
        assert node[key] == row['after']
        if key == 'volumes':
            assert row['existed'] is True and EVIDENCE_MOUNT not in row['before']
            assert row['after'].count(EVIDENCE_MOUNT) == 1
            assert [v for v in row['after'] if v != EVIDENCE_MOUNT] == row['before']
        else:
            assert row['after'] == values[key]
        if row['existed']:
            node[key] = row['before']
        else:
            del node[key]
    assert digest(restored) == BASELINES[app_id], 'unapproved runtime change'
    return restored

class RecoveryReleaseTests(unittest.TestCase):
    def test_current_recipes_restore_exact_baselines(self):
        self.assertEqual(RELEASE['baselineCommit'], '8ab5aeae19b5148f27ed561b62d43aa2569afabf')
        self.assertEqual(RELEASE['channel'], 'DEV')
        self.assertEqual(set(APPS), {SMACK, DIAG})
        self.assertEqual(set(RELEASE['runtimeContracts']), set(APPS))
        for aid, record in APPS.items():
            current = yaml.safe_load((ROOT / aid / 'docker-compose.yml').read_text())
            previous_recovery_model(aid, current)
            for filename in record['manifests']:
                self.assertEqual(yaml.safe_load((ROOT / aid / filename).read_text())['version'], record['version'])

    def test_diag_other_runtime_and_privilege_changes_are_rejected(self):
        current = yaml.safe_load((ROOT / DIAG / 'docker-compose.yml').read_text())
        for service, field, value in [
            ('support-relay', 'image', 'changed-relay'),
            ('support-relay', 'volumes', ['/secret:/secret:ro']),
            ('app', 'volumes', current['services']['app']['volumes'] + ['/var/run/docker.sock:/var/run/docker.sock']),
            ('app', 'volumes', [v.replace('/host/mux-evidence:ro', '/host/mux-evidence:rw') for v in current['services']['app']['volumes']]),
            ('app', 'environment', {'APP_VERSION': '0.1.8', 'CONTROLLER_TOKEN': 'secret'}),
            ('app', 'read_only', False), ('app', 'ports', ['9999:3000']),
        ]:
            with self.subTest(service=service, field=field):
                changed = copy.deepcopy(current)
                changed['services'][service][field] = value
                with self.assertRaises(AssertionError):
                    previous_recovery_model(DIAG, changed)

    def test_public_record_is_only_public_identity_and_bounded_delta(self):
        self.assertEqual(set(RELEASE), {'schemaVersion', 'channel', 'baselineCommit', 'apps', 'runtimeContracts'})
        self.assertEqual(RELEASE['schemaVersion'], 1)
        text = (ROOT / 'RECOVERY-2026-10-02.json').read_text()
        self.assertLess(len(text.encode()), 16384)
        for private in ('/Users/', '/home/forge', '10.10.10.', 'PAYOUT_ADDRESS', 'APP_PASSWORD', 'controller.key'):
            self.assertNotIn(private, text)
        for record in APPS.values():
            self.assertEqual(set(record), {'version', 'baseVersion', 'sourceRevision', 'imageRef', 'images', 'manifests'})
            self.assertEqual(record['version'], record['baseVersion'])
            self.assertEqual(set(record['images']), {'amd64', 'arm64'})
            for image in record['images'].values():
                self.assertEqual(set(image), {'configDigest', 'manifestDigest'})
                for value in image.values():
                    self.assertRegex(value, r'^sha256:[0-9a-f]{64}$')

if __name__ == '__main__':
    unittest.main()
