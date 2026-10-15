"""Remove only the exact reviewed initializer prefix before historical contracts."""
import base64
import copy
import hashlib
import json
from pathlib import Path
import unittest

import yaml
from app_version_normalization import previous_app_version_model

ROOT = Path(__file__).resolve().parents[1]
RECORD = json.loads((ROOT / 'POOL-SUPERVISOR-2026-10-14.json').read_text())
START = '# BEGIN REVIEWED POOL SUPERVISOR MIGRATION\n'
END = '# END REVIEWED POOL SUPERVISOR MIGRATION\n'


def digest(model):
    return hashlib.sha256(json.dumps(model, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def previous_supervisor_model(app_id, current):
    current = previous_app_version_model(app_id, current)
    if app_id not in RECORD['apps']:
        return copy.deepcopy(current)
    record = RECORD['apps'][app_id]
    assert digest(current) == record['afterModelSHA256']
    restored = copy.deepcopy(current)
    command = restored['services']['init']['command'][2]
    assert command.count(START) == command.count(END) == 1
    prefix, remainder = command.split(START, 1)
    body, suffix = remainder.split(END, 1)
    assert prefix == 'set -eu\n\n'
    assert hashlib.sha256((START + body + END).encode()).hexdigest() == record['guardComposeSourceSHA256']
    encoded = body.split("<<'REVIEWED_POOL_SUPERVISOR'\n", 1)[1].split('\nREVIEWED_POOL_SUPERVISOR', 1)[0]
    shipped = (ROOT / app_id / 'data/templates/ckpool-entrypoint.sh').read_bytes()
    assert base64.b64decode(encoded) == shipped
    assert hashlib.sha256(shipped).hexdigest() == record['afterEntrypointSHA256']
    restored['services']['init']['command'][2] = prefix + suffix.removeprefix('\n')
    assert digest(restored) == record['beforeModelSHA256']
    return restored


def package_version(app_id, historical):
    if app_id not in RECORD['apps']:
        return historical
    record = RECORD['apps'][app_id]
    assert historical == record['beforePackageVersion']
    return record['packageVersion']


class PoolSupervisorReleaseTests(unittest.TestCase):
    def test_exact_two_initializer_deltas_and_unchanged_images(self):
        self.assertEqual(set(RECORD['apps']), {'willitmod-dev-btc', 'willitmod-dev-fracattack'})
        for aid, record in RECORD['apps'].items():
            model = yaml.safe_load((ROOT / aid / 'docker-compose.yml').read_text())
            previous_supervisor_model(aid, model)
            normalized = previous_app_version_model(aid, model)
            self.assertEqual({n:s['image'] for n,s in normalized['services'].items() if 'image' in s}, record['imagesUnchanged'])
            self.assertEqual(normalized['services']['app']['environment'].get('APP_VERSION'), record['applicationVersionFieldUnchanged'])
            for mutate in ('mount', 'image', 'policy', 'guard', 'command'):
                changed = copy.deepcopy(model)
                if mutate == 'mount': changed['services']['ckpool']['volumes'].append('unreviewed:/other')
                elif mutate == 'image': changed['services']['ckpool']['image'] = 'unreviewed:latest'
                elif mutate == 'policy': changed['services']['ckpool']['stop_grace_period'] = '1s'
                elif mutate == 'guard': changed['services']['init']['command'][2] = changed['services']['init']['command'][2].replace('pool_migration_check', 'unreviewed_guard', 1)
                else: changed['services']['init']['command'][2] += '\necho unreviewed\n'
                with self.subTest(app=aid, mutation=mutate), self.assertRaises(AssertionError):
                    previous_supervisor_model(aid, changed)


if __name__ == '__main__':
    unittest.main()
