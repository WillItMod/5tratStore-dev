"""Protect seeded SQL delivery; opt-in test runs the real native CLI and PostgreSQL."""
import copy
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import time
import unittest
import uuid

import yaml
from test_xec_portable_release import package_version as xec_package_version
from test_bc2_fresh_provenance import package_version as bc2_package_version
from test_bch2_node_entrypoint_release import package_version as bch2_package_version
from test_ppc_immutable_release import package_version as ppc_package_version

ROOT = Path(__file__).resolve().parents[1]
APP = 'willitmod-dev-powpow'
RECORD = json.loads((ROOT/'POWPOW-NATIVE-SEED-2026-10-14.json').read_text())

def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':')).encode()).hexdigest()

def previous_powpow_model(app_id, current):
    if app_id != APP:
        return copy.deepcopy(current)
    assert digest(current) == RECORD['afterModelSHA256']
    restored = copy.deepcopy(current)
    volumes = restored['services']['postgres']['volumes']
    assert volumes.count(RECORD['postgresInitMount']['after']) == 1
    volumes[volumes.index(RECORD['postgresInitMount']['after'])] = RECORD['postgresInitMount']['before']
    command = restored['services']['init_permissions']['command']
    assert command == RECORD['initPermissionsCommand']['after']
    restored['services']['init_permissions']['command'] = copy.deepcopy(RECORD['initPermissionsCommand']['before'])
    assert digest(restored) == RECORD['beforeModelSHA256']
    return restored

def package_version(app_id, historical):
    return RECORD['packageVersion'] if app_id == APP else ppc_package_version(app_id,bch2_package_version(app_id,bc2_package_version(app_id, xec_package_version(app_id, historical))))

class PowPowSqlSeedContractTests(unittest.TestCase):
    def test_seed_mount_is_deliverable_without_recipe_directory(self):
        model = yaml.safe_load((ROOT/APP/'docker-compose.yml').read_text())
        previous_powpow_model(APP, model)
        self.assertEqual({n:s['image'] for n,s in model['services'].items() if 'image' in s}, RECORD['imagesUnchanged'])
        self.assertEqual(model['services']['app']['environment']['APP_VERSION'], RECORD['applicationVersionUnchanged'])
        mount = next(v for v in model['services']['postgres']['volumes'] if v.endswith(':/docker-entrypoint-initdb.d:ro'))
        self.assertIsInstance(mount, str)  # Both Umbrel patchers consume short volume strings.
        source, target, mode = mount.rsplit(':', 2)
        self.assertEqual(target, '/docker-entrypoint-initdb.d')
        self.assertEqual(mode, 'ro')
        self.assertTrue(source.startswith('${APP_DATA_DIR}/data/'))
        seed = ROOT/APP/source.removeprefix('${APP_DATA_DIR}/')
        self.assertEqual({p.name for p in seed.iterdir()}, set(RECORD['sqlFiles']))
        for p in seed.iterdir():
            self.assertEqual(hashlib.sha256(p.read_bytes()).hexdigest(), RECORD['sqlFiles'][p.name]['sha256'])
            self.assertEqual(p.stat().st_mode & 0o777, 0o644)
        self.assertFalse((ROOT/APP/'postgres/init').exists())

    def test_recipe_revision_is_separate_from_unchanged_application(self):
        for name in ['umbrel-app.yml', 'global-app.yml']:
            manifest = yaml.safe_load((ROOT/APP/name).read_text())
            self.assertEqual(manifest['version'], RECORD['packageVersion'])
            self.assertIn('empty PostgreSQL', manifest['releaseNotes'])
            self.assertIn('images are unchanged', manifest['releaseNotes'])

@unittest.skipUnless(os.environ.get('POWPOW_NATIVE_RUNTIME') == '1', 'requires opt-in Linux native CLI and Docker')
class PowPowActualNativePostgresTests(unittest.TestCase):
    def test_actual_native_import_initializes_once_and_keeps_database_rows(self):
        cli = Path(os.environ.get('POWPOW_NATIVE_CLI', '/usr/local/bin/5tratumos'))
        daemon = Path(os.environ.get('POWPOW_NATIVE_DAEMON', '/opt/5tratumos/daemon'))
        self.assertEqual(os.geteuid(), 0)
        self.assertEqual(hashlib.sha256(cli.read_bytes()).hexdigest(), '1eba622ede45986e4e5ac966d0ed5da5343acc37d6da3db257cc7fb45daed340')
        project = 'codex-powpow-seed-regression-' + uuid.uuid4().hex[:10]
        with tempfile.TemporaryDirectory(prefix='codex-powpow-seed-') as temporary:
            root = Path(temporary)/'root'
            state = Path(temporary)/'state'
            root.mkdir();state.mkdir()
            shutil.copytree(daemon, root/'daemon')
            store = root/'store/dev'/APP
            shutil.copytree(ROOT/APP, store)
            (store/'umbrel-app.yml').replace(store/'global-app.yml')
            env = dict(os.environ, FIVETRATUMOS_ROOT=str(root), FIVETRATUMOS_STATE_DIR=str(state),
                       FIVETRATUMOS_STORAGE_CONFIG_FILE=str(Path(temporary)/'storage.json'))
            imported = subprocess.run([str(cli), 'app', 'install', 'axepowpow', '--channel', 'dev'], env=env, text=True, capture_output=True)
            self.assertEqual(imported.returncode, 0, imported.stderr)
            app = root/'apps/axepowpow'
            data = state/'apps/axepowpow/data'
            for name, record in RECORD['sqlFiles'].items():
                self.assertEqual(hashlib.sha256((data/'postgres-init'/name).read_bytes()).hexdigest(), record['sha256'])
            # This is the actual materialized model; no importer/seed implementation is copied here.
            compose = ['docker', 'compose', '--project-name', project, '--project-directory', str(app), '-f', str(app/'docker-compose.yml')]
            def run(args):
                p = subprocess.run(args, text=True, capture_output=True, timeout=180)
                self.assertEqual(p.returncode, 0, p.stderr)
                return p.stdout.strip()
            def query(sql):
                return run(compose + ['exec', '-T', 'postgres', 'psql', '-U', 'mergedmining', '-d', 'mergedmining', '-v', 'ON_ERROR_STOP=1', '-At', '-c', sql])
            def ready():
                end = time.monotonic()+75
                while time.monotonic()<end:
                    # The entrypoint temporarily starts a server during init.
                    # Wait for its final exec before accepting pg_isready.
                    server = subprocess.run(compose+['exec','-T','postgres','cat','/proc/1/comm'], capture_output=True, text=True)
                    p = subprocess.run(compose+['exec','-T','postgres','pg_isready','-U','mergedmining','-d','mergedmining'], capture_output=True)
                    if server.returncode == 0 and server.stdout.strip() == 'postgres' and p.returncode == 0:return
                    time.sleep(.5)
                self.fail('Owned PostgreSQL fixture did not become ready')
            try:
                # Starts only postgres and its permissions dependency; no node/pool/mining service.
                run(compose+['up','-d','postgres']);ready()
                tables=set(query("SELECT tablename FROM pg_tables WHERE schemaname='public'").splitlines())
                self.assertTrue({'shares','shares_testing','blocks','balances','balance_changes','miner_settings','payments','poolstats','minerstats'} <= tables)
                self.assertEqual(query("SELECT relkind FROM pg_class WHERE oid='shares'::regclass"), 'p')
                query('CREATE TABLE qa_seed_persistence(id integer PRIMARY KEY); INSERT INTO qa_seed_persistence VALUES (624)')
                before = query("SELECT pg_relation_filenode('shares_testing')")
                run(compose+['down']);run(compose+['up','-d','postgres']);ready()
                self.assertEqual(query('SELECT id FROM qa_seed_persistence'), '624')
                self.assertEqual(query("SELECT pg_relation_filenode('shares_testing')"), before)
                self.assertEqual(query("SELECT count(*) FROM pg_tables WHERE schemaname='public' AND tablename IN ('shares','shares_testing')"), '2')
            finally:
                subprocess.run(compose+['down','--remove-orphans'], capture_output=True, timeout=60)

if __name__ == '__main__':
    unittest.main()
