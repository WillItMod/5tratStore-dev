"""Execute both shipped initializers against preserved app-data lifecycle fixtures.

These checks exercise initializer admission, not live chain/mining qualification.
The chain fixture represents data retained after a Core31 first boot; no RPC or
Stratum server is mocked and no validation-completion marker is invented.
"""
import hashlib
import json
import os
from pathlib import Path
import shutil
import stat
import subprocess
import tempfile
import unittest

import yaml

ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / 'willitmod-dev-bc2'
RECORD = json.loads((ROOT / 'BC2-FRESH-PROVENANCE-2026-10-14.json').read_text())
FRESH = '.core31-fresh-provenance.json'
REQUIRED = '.core31-full-reindex-required.json'
COMPLETE = '.core31-full-reindex-complete.json'


def package_version(app_id, historical):
    return RECORD['packageVersion'] if app_id == 'willitmod-dev-bc2' else historical


class FreshCore31ProvenanceTests(unittest.TestCase):
    def context(self, script):
        temp = tempfile.TemporaryDirectory(prefix='bc2-fresh-provenance-')
        self.addCleanup(temp.cleanup)
        root = Path(temp.name)
        data, appdata = root / 'data', root / 'appdata'
        data.mkdir(); appdata.mkdir()
        build = root / 'build.json'
        build.write_text('{"tag":"0.8.32"}')
        env = dict(os.environ, AXEBC2_DATA_DIR=str(data), AXEBC2_APPDATA_DIR=str(appdata),
                   AXEBC2_BUILD_FILE=str(build), AXEBC2_TEMPLATES_DIR=str(APP / 'data/templates'),
                   AXEBC2_TEST_SKIP_CHOWN='true', AXEBC2_PLATFORM='umbrel',
                   APPS_SUBNET='10.0.0.0/16', RPC_USER='btc2', RPC_PASSWORD='test-only',
                   BTC2_RPC_PORT='8337', BTC2_P2P_PORT='8338', BTC2_ZMQ_HASHBLOCK_PORT='28336',
                   PAYOUT_ADDRESS='CHANGEME_BTC2_PAYOUT_ADDRESS')
        env.pop('JWT_SECRET', None)
        def run(expected=0):
            p = subprocess.run(['sh', str(script)], env=env, capture_output=True, text=True, timeout=30)
            self.assertEqual(p.returncode, expected, p.stderr)
            return p
        return data, appdata, run

    def scripts(self):
        return [APP / 'data/init/init.sh', APP / 'hooks/umbrel-init']

    def chain_fixture(self, data):
        node = data / 'node'
        (node / 'blocks').mkdir(parents=True, exist_ok=True)
        (node / 'chainstate').mkdir(exist_ok=True)
        block = node / 'blocks/blk00000.dat'
        block.write_bytes(b'retained Core31 chain fixture\x00\xff')
        chainstate = node / 'chainstate/retained-state'
        chainstate.write_bytes(b'retained chainstate fixture')
        return {p: hashlib.sha256(p.read_bytes()).hexdigest() for p in [block, chainstate]}

    def test_fresh_first_boot_then_persisted_chain_restart_never_queues_migration(self):
        for script in self.scripts():
            with self.subTest(script=script.name):
                data, appdata, run = self.context(script)
                run()
                marker = data / 'node' / FRESH
                first = marker.read_bytes()
                record = json.loads(first)
                self.assertEqual(record['node_image'], RECORD['nodeImageUnchanged'])
                self.assertEqual(record['source_revision'], RECORD['nodeSourceRevision'])
                self.assertTrue(record['empty_chain_at_creation'])
                self.assertEqual(stat.S_IMODE(marker.stat().st_mode), 0o600)
                self.assertNotIn('validated_height', record)
                self.assertNotIn('checkpoint_hash', record)
                retained = self.chain_fixture(data)
                run(); run()
                self.assertEqual(marker.read_bytes(), first)
                self.assertFalse((data / 'node' / REQUIRED).exists())
                self.assertFalse((data / 'node' / COMPLETE).exists())
                for path, digest in retained.items():
                    self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(), digest)

    def test_historical_chain_without_provenance_keeps_existing_migration_and_bytes(self):
        for script in self.scripts():
            with self.subTest(script=script.name):
                data, appdata, run = self.context(script)
                retained = self.chain_fixture(data)
                run()
                self.assertFalse((data / 'node' / FRESH).exists())
                self.assertEqual(json.loads((data / 'node' / REQUIRED).read_text())['minimum_core_major'], 31)
                for path, digest in retained.items():
                    self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(), digest)

    def test_explicit_required_marker_and_reindex_config_cannot_be_superseded(self):
        payload = '{"schema":1,"migration":"bitcoinii-shockwave-core31-full-reindex","minimum_core_major":31,"activation_height":57750}\n'
        for script in self.scripts():
            with self.subTest(script=script.name):
                data, appdata, run = self.context(script)
                run(); self.chain_fixture(data)
                marker = data / 'node' / REQUIRED
                marker.write_text(payload)
                conf = data / 'node/bitcoinII.conf'
                conf.write_text(conf.read_text() + 'reindex=1\nreindex-chainstate=1\n')
                run()
                self.assertEqual(marker.read_text(), payload)
                self.assertFalse((data / 'node' / COMPLETE).exists())
                self.assertIn('reindex=1\n', conf.read_text())
                self.assertIn('reindex-chainstate=1\n', conf.read_text())

    def test_malformed_source_image_and_completion_like_provenance_fail_before_writes(self):
        mutations = [lambda r: r.update(schema=2), lambda r: r.update(source_revision='a'*40),
                     lambda r: r.update(node_image='other-core-image'),
                     lambda r: r.update(empty_chain_at_creation=False),
                     lambda r: r.update(validated_height=61525), lambda r: r.update(core_major=30)]
        for script in self.scripts():
            for mutate in mutations:
                with self.subTest(script=script.name, mutation=mutate):
                    data, appdata, run = self.context(script)
                    (data / 'node').mkdir()
                    record = {'schema':1, 'purpose':'bitcoinii-core31-fresh-chain', 'core_major':31,
                              'empty_chain_at_creation':True, 'source_revision':RECORD['nodeSourceRevision'],
                              'node_image':RECORD['nodeImageUnchanged']}
                    mutate(record)
                    marker = data / 'node' / FRESH
                    marker.write_text(json.dumps(record))
                    before = marker.read_bytes()
                    run(78)
                    self.assertEqual(marker.read_bytes(), before)
                    self.assertFalse((data / '.5tratumos-rollback-policy.json').exists())
                    self.assertFalse((data / 'node/bitcoinII.conf').exists())
                    self.assertEqual(list(appdata.iterdir()), [])

    def test_directory_and_dangling_link_are_not_provenance(self):
        for script in self.scripts():
            for kind in ['directory','dangling-link']:
                with self.subTest(script=script.name, kind=kind):
                    data, appdata, run = self.context(script)
                    (data / 'node').mkdir()
                    marker = data / 'node' / FRESH
                    marker.mkdir() if kind == 'directory' else marker.symlink_to('missing-provenance')
                    run(78)
                    self.assertFalse((data / '.5tratumos-rollback-policy.json').exists())
                    self.assertFalse((data / 'node' / REQUIRED).exists())

    def test_dangling_or_symlinked_migration_markers_cannot_create_fresh_provenance(self):
        for script in self.scripts():
            for name in [REQUIRED, COMPLETE]:
                with self.subTest(script=script.name, marker=name):
                    data, appdata, run = self.context(script)
                    (data / 'node').mkdir()
                    (data / 'node' / name).symlink_to('missing-migration-proof')
                    run(78)
                    self.assertFalse((data / 'node' / FRESH).exists())

    def test_provenance_binds_the_actual_recipe_and_generated_common_source(self):
        compose = yaml.safe_load((APP / 'docker-compose.yml').read_text())
        template = yaml.safe_load((APP / 'docker-compose.yml.template').read_text())
        self.assertEqual(compose['services']['btc2d']['image'], RECORD['nodeImageUnchanged'])
        self.assertEqual(template['services']['btc2d']['image'], RECORD['nodeImageUnchanged'])
        self.assertEqual(compose['services']['app']['image'], RECORD['appImageUnchanged'])
        manifest = yaml.safe_load((APP / 'umbrel-app.yml').read_text())
        self.assertEqual(manifest['version'], RECORD['packageVersion'])
        subprocess.run([os.sys.executable, str(ROOT / 'scripts/build-axebc2-umbrel.py'), '--check'], check=True)
        for script in self.scripts():
            text = script.read_text()
            self.assertIn('fresh_source="'+RECORD['nodeSourceRevision']+'"', text)
            self.assertIn('fresh_image="'+RECORD['nodeImageUnchanged']+'"', text)
            self.assertIn('validate_complete_marker', text)
            self.assertIn('000000000000000013ceffe797280c57f75a5b9f1d9e70c3503584058c322576', text)
