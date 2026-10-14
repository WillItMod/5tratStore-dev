import base64
import copy
import hashlib
import json
import os
from pathlib import Path
import shutil
import stat
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

import yaml

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'willitmod-dev-fumbrel/app'))
import engine
import server

CATALOG = json.loads((ROOT / 'willitmod-dev-fumbrel/app/catalog.json').read_text())
BTC = 'willitmod-dev-btc'


class Host(engine.Engine):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.live = {}
        self.calls = []
        self.fail = None

    def running(self, app_id):
        return self.live.get(app_id, [])

    def lifecycle(self, app_id, action):
        self.calls.append((app_id, action))
        if self.fail == action:
            raise engine.RecoveryError('Simulated lifecycle failure')
        self.live[app_id] = [{'id': 'container', 'service': 'node'}] if action == 'start' else []


class VersionTests(unittest.TestCase):
    def test_prerelease_precedence_numeric_revisions_and_historical_versions(self):
        pairs = [
            ('4.0.28-dev.1', '4.0.28-dev'),
            ('1.4.2-dev.10', '1.4.2-dev.2'),
            ('0.1.21-dev.1', '0.1.21-dev'),
            ('0.2.37-dev.1', '0.2.37-dev'),
            ('1.0.0-alpha.1', '1.0.0-alpha'),
            ('1.0.0-beta', '1.0.0-alpha.9'),
            ('1.0.0-beta.11', '1.0.0-beta.2'),
            ('1.0.0-dev.1', '1.0.0-beta.11'),
            ('1.0.0', '1.0.0-dev.99'),
            ('0.7.82.17-dev.1', '0.7.82.17-dev'),
            ('0.7.82.18-alpha', '0.7.82.17'),
            ('0.7.83-dev', '0.7.82.99'),
            ('1.0.0-alpha.beta', '1.0.0-alpha.1'),
        ]
        for newer, older in pairs:
            with self.subTest(newer=newer, older=older):
                self.assertTrue(engine.is_newer(newer, older))
                self.assertFalse(engine.is_newer(older, newer))

    def test_build_metadata_and_zero_padding_have_no_precedence(self):
        for a, b in [('v1.2.3', '1.2.3.0'), ('1.2.3-dev.1+build.7', '1.2.3-dev.1+other'),
                     ('1.2.3+build.4', '1.2.3'), ('0.7.82.17-dev', '0.7.82.17-dev')]:
            with self.subTest(a=a, b=b):
                self.assertFalse(engine.is_newer(a, b))
                self.assertFalse(engine.is_newer(b, a))

    def test_unknown_or_ambiguous_versions_fail_closed(self):
        for value in ('latest', '', '1.2.3-', '1.2.3+', '1.2.3-dev..1', '1.2.3-dev.01',
                      '1.2.3_dev', '1.2.3+meta..1', '1.2.3\n', ' 1.2.3', '1.2.3-dev/1'):
            with self.subTest(version=value), self.assertRaises(engine.RecoveryError):
                engine.is_newer(value, '1.2.3')


class RecoveryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name).resolve()
        self.home = self.root / 'app-data' / engine.SELF
        self.home.mkdir(parents=True)
        (self.root / 'umbrel.yaml').write_text('apps: []\n')
        self.yaml = patch.object(engine, 'yaml_load', lambda body: yaml.safe_load(body))
        self.yaml.start()
        self.addCleanup(self.yaml.stop)
        self.addCleanup(self.temp.cleanup)
        self.catalog = copy.deepcopy(CATALOG)
        self.host = Host(str(self.home), self.catalog)

    def install(self, app_id=BTC):
        registry = self.root / 'umbrel.yaml'
        installed = yaml.safe_load(registry.read_text())['apps'] if registry.exists() else []
        registry.write_text(yaml.safe_dump({'apps': installed + [app_id]}))
        folder = self.root / 'app-data' / app_id
        folder.mkdir()
        for name, item in self.catalog['apps'][app_id]['files'].items():
            path = folder / name
            path.parent.mkdir(exist_ok=True, parents=True)
            path.write_bytes(base64.b64decode(item['body']))
            path.chmod(item['mode'])
        (folder / 'data').mkdir()
        (folder / 'data/wallet.dat').write_bytes(b'precious-wallet-sentinel')
        (folder / '.env').write_text('RPC_PASSWORD=must-stay-private\n')
        (folder / 'settings.yml').write_text('autoStart: false\ncustomEnvironment: []\n')
        return folder

    def seed_powpow(self, folder):
        entry = self.catalog['apps']['willitmod-dev-powpow']
        for name in engine.POWPOW_SEEDS:
            path = folder / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(subprocess.check_output(['git', 'show', entry['source_commit'] + ':' + entry['source_id'] + '/' + name], cwd=ROOT))

    def test_repair_preserves_images_identity_and_persistent_state(self):
        folder = self.install()
        compose = yaml.safe_load((folder / 'docker-compose.yml').read_text())
        del compose['services']['app']['hostname']
        (folder / 'docker-compose.yml').write_text(yaml.safe_dump(compose))
        before = {name: (folder / name).read_bytes() for name in ['data/wallet.dat', '.env', 'settings.yml', 'umbrel-app.yml']}
        result = self.host.recover(BTC, 'repair', False)
        actual = yaml.safe_load((folder / 'docker-compose.yml').read_bytes())
        self.assertEqual(actual['services']['app']['hostname'], 'axebtc-app')
        del actual['services']['app']['hostname']
        self.assertEqual(actual, compose)
        self.assertEqual({name: (folder / name).read_bytes() for name in before}, before)
        self.assertEqual(result['state'], 'stopped')
        self.assertEqual(self.host.calls, [(BTC, 'stop')])

    def test_metadata_only_repair_preserves_restricted_modes_and_ownership(self):
        folder = self.install()
        compose_path = folder / 'docker-compose.yml'
        compose = yaml.safe_load(compose_path.read_text())
        del compose['services']['app']['hostname']
        # Custom recipe values may contain credentials. A narrow repair must
        # not make their file readable by accounts that could not read it before.
        compose['services']['app'].setdefault('environment', {})['PRIVATE_SETTING'] = 'must-stay-restricted'
        compose_path.write_text(yaml.safe_dump(compose))
        compose_path.chmod(0o600)
        before_owner = (compose_path.stat().st_uid, compose_path.stat().st_gid)
        untouched = {name: (folder / name).read_bytes() for name in ('data/wallet.dat', '.env', 'settings.yml', 'umbrel-app.yml')}
        self.host.recover(BTC, 'repair', False)
        actual = yaml.safe_load(compose_path.read_text())
        self.assertEqual(actual['services']['app'].pop('hostname'), 'axebtc-app')
        self.assertEqual(actual, compose)
        self.assertEqual(stat.S_IMODE(compose_path.stat().st_mode), 0o600)
        self.assertEqual((compose_path.stat().st_uid, compose_path.stat().st_gid), before_owner)
        self.assertEqual({name: (folder / name).read_bytes() for name in untouched}, untouched)

    def test_legacy_exports_bootstrap_precedes_stop(self):
        folder = self.install()
        legacy = b'set -euo pipefail\nfalse\n'
        self.catalog['legacy_exports'].append(engine.digest(legacy))
        (folder / 'exports.sh').write_bytes(legacy)
        normal = self.host.lifecycle
        def lifecycle(app_id, action):
            self.assertNotEqual((folder / 'exports.sh').read_bytes(), legacy)
            normal(app_id, action)
        self.host.lifecycle = lifecycle
        result = self.host.recover(BTC, 'repair', False)
        original = json.loads((self.host.backups / result['backup'] / 'index.json').read_text())
        self.assertEqual(base64.b64decode(original['files']['exports.sh']['body']), legacy)

    def test_unknown_exports_repair_blocks_but_explicit_update_replaces(self):
        folder = self.install()
        (folder / 'exports.sh').write_text('echo customized\n')
        with self.assertRaisesRegex(engine.RecoveryError, 'Unrecognized exports'):
            self.host.recover(BTC, 'repair', False)
        self.assertEqual(self.host.calls, [])
        self.host.recover(BTC, 'update', False)
        expected = base64.b64decode(self.catalog['apps'][BTC]['files']['exports.sh']['body'])
        self.assertEqual((folder / 'exports.sh').read_bytes(), expected)

    def test_main_identity_update_and_conventional_proxy_names(self):
        for app_id in ['willitmod-btc', 'willitmod-axebench', 'willitmod-axelive', 'willitmod-axemig']:
            with self.subTest(app=app_id):
                folder = self.install(app_id)
                self.host.recover(app_id, 'update', False)
                manifest = yaml.safe_load((folder / 'umbrel-app.yml').read_text())
                self.assertEqual(manifest['id'], app_id)
                self.assertEqual((folder / 'data/wallet.dat').read_bytes(), b'precious-wallet-sentinel')
                compose = yaml.safe_load((folder / 'docker-compose.yml').read_text())
                self.assertNotIn(self.catalog['apps'][app_id]['source_id'], json.dumps(compose))
                if app_id in ('willitmod-axebench', 'willitmod-axelive'):
                    self.assertEqual(compose['services']['server']['hostname'], app_id + '_server_1')

    def test_downgrade_blocked_before_backup_or_stop(self):
        folder = self.install()
        manifest = yaml.safe_load((folder / 'umbrel-app.yml').read_text())
        manifest['version'] = '99.0.0-dev'
        (folder / 'umbrel-app.yml').write_text(yaml.safe_dump(manifest))
        with self.assertRaisesRegex(engine.RecoveryError, 'Downgrades'):
            self.host.recover(BTC, 'update', False)
        self.assertEqual(self.host.calls, [])
        self.assertFalse(self.host.backups.exists())

    def test_old_bundle_cannot_remove_newer_utility_hooks_or_revisions(self):
        for app_id, installed in [('willitmod-dev-axebench', '4.0.28-dev.1'),
                                  ('willitmod-dev-axelive', '1.4.2-dev.1'),
                                  ('willitmod-dev-axemig', '0.1.21-dev.1'),
                                  ('willitmod-dev-powpow', '0.2.37-dev.1')]:
            with self.subTest(app=app_id):
                folder = self.install(app_id)
                manifest = yaml.safe_load((folder / 'umbrel-app.yml').read_text())
                manifest['version'] = installed
                (folder / 'umbrel-app.yml').write_text(yaml.safe_dump(manifest))
                self.catalog['apps'][app_id]['version'] = installed.rsplit('.', 1)[0]
                self.catalog['apps'][app_id]['files'].pop('hooks/pre-start', None)
                before = {p.relative_to(self.root): (p.read_bytes(), stat.S_IMODE(p.stat().st_mode), p.stat().st_mtime_ns)
                          for p in self.root.rglob('*') if p.is_file()}
                with patch.object(self.host, 'backup', side_effect=AssertionError('Backup attempted before downgrade rejection')) as backup, \
                        patch.object(self.host, 'stop') as stop, \
                        patch.object(self.host, 'write_changes') as write, \
                        self.assertRaisesRegex(engine.RecoveryError, 'Downgrades'):
                    self.host.recover(app_id, 'update', True)
                backup.assert_not_called()
                stop.assert_not_called()
                write.assert_not_called()
                self.assertEqual(self.host.calls, [])
                self.assertFalse(self.host.backups.exists())
                row = next(row for row in self.host.scan()['apps'] if row['id'] == app_id)
                self.assertFalse(row['can_update'])
                after = {p.relative_to(self.root): (p.read_bytes(), stat.S_IMODE(p.stat().st_mode), p.stat().st_mtime_ns)
                         for p in self.root.rglob('*') if p.is_file()}
                self.assertEqual(after, before)

    def test_update_installs_and_repairs_executable_ownership_hook_modes(self):
        for app_id in ('willitmod-dev-axebench', 'willitmod-dev-axelive'):
            with self.subTest(app=app_id):
                folder = self.install(app_id)
                hook = folder / 'hooks/pre-start'
                hook.unlink()
                self.host.recover(app_id, 'update', False)
                self.assertEqual(stat.S_IMODE(hook.stat().st_mode), 0o755)
                owner = (hook.stat().st_uid, hook.stat().st_gid)
                hook.chmod(0o644)
                self.host.recover(app_id, 'update', False)
                self.assertEqual(stat.S_IMODE(hook.stat().st_mode), 0o755)
                self.assertEqual((hook.stat().st_uid, hook.stat().st_gid), owner)
                self.assertEqual(hook.read_bytes(), base64.b64decode(self.catalog['apps'][app_id]['files']['hooks/pre-start']['body']))
                self.assertEqual((folder / 'data/wallet.dat').read_bytes(), b'precious-wallet-sentinel')
                self.assertEqual((folder / '.env').read_text(), 'RPC_PASSWORD=must-stay-private\n')

    def test_powpow_seed_prerequisites_block_before_backup_stop_or_writes(self):
        app_id = 'willitmod-dev-powpow'
        for condition in ('missing', 'stale', 'symlink-file', 'symlink-directory', 'hardlink', 'fifo'):
            with self.subTest(condition=condition):
                # A failed assertion in one subcase must not contaminate the next.
                previous = self.root / 'app-data' / app_id
                if previous.exists():
                    shutil.rmtree(previous)
                (self.root / 'umbrel.yaml').write_text('apps: []\n')
                folder = self.install(app_id)
                self.seed_powpow(folder)
                seed = folder / engine.POWPOW_SEEDS[0]
                outside = self.root / 'untouched-outside.sql'
                outside.write_bytes(b'outside-private-sentinel')
                if condition == 'missing':
                    seed.unlink()
                elif condition == 'stale':
                    seed.write_bytes(b'changed-static-seed')
                elif condition == 'symlink-file':
                    seed.unlink()
                    seed.symlink_to(outside)
                elif condition == 'symlink-directory':
                    old = seed.parent
                    preserved = folder / 'seed-directory-before-test'
                    old.rename(preserved)
                    old.symlink_to(preserved, target_is_directory=True)
                elif condition == 'hardlink':
                    seed.unlink()
                    os.link(outside, seed)
                elif condition == 'fifo':
                    seed.unlink()
                    os.mkfifo(seed)
                data_before = {name: (folder / name).read_bytes() for name in ('data/wallet.dat', '.env', 'settings.yml', 'umbrel-app.yml', 'docker-compose.yml')}
                with patch.object(self.host, 'backup', side_effect=AssertionError('Backup attempted before seed prerequisite rejection')) as backup, \
                        patch.object(self.host, 'stop') as stop, patch.object(self.host, 'write_changes') as write, \
                        self.assertRaisesRegex(engine.RecoveryError, 'normal Umbrel store update'):
                    self.host.recover(app_id, 'update', True)
                backup.assert_not_called()
                stop.assert_not_called()
                write.assert_not_called()
                self.assertEqual(self.host.calls, [])
                self.assertFalse(self.host.backups.exists())
                self.assertEqual({name: (folder / name).read_bytes() for name in data_before}, data_before)
                self.assertEqual(outside.read_bytes(), b'outside-private-sentinel')
                row = next(row for row in self.host.scan()['apps'] if row['id'] == app_id)
                self.assertFalse(row['can_update'])
                self.assertTrue(row['can_repair'])
                self.assertTrue(any('normal Umbrel store update' in issue for issue in row['issues']))
                # Keep each subcase in its own installed-app directory.
                shutil.rmtree(folder)
                (self.root / 'umbrel.yaml').write_text('apps: []\n')
                outside.unlink()

    def test_powpow_exact_existing_seeds_enable_update_without_data_writes(self):
        app_id = 'willitmod-dev-powpow'
        folder = self.install(app_id)
        self.seed_powpow(folder)
        before = {p.relative_to(folder): (p.read_bytes(), stat.S_IMODE(p.stat().st_mode), p.stat().st_mtime_ns)
                  for p in (folder / 'data').rglob('*') if p.is_file()}
        private = {name: (folder / name).read_bytes() for name in ('.env', 'settings.yml')}
        row = next(row for row in self.host.scan()['apps'] if row['id'] == app_id)
        self.assertTrue(row['can_update'])
        result = self.host.recover(app_id, 'update', False)
        self.assertEqual(result['state'], 'stopped')
        self.assertEqual(self.host.calls, [(app_id, 'stop')])
        self.assertEqual({p.relative_to(folder): (p.read_bytes(), stat.S_IMODE(p.stat().st_mode), p.stat().st_mtime_ns)
                          for p in (folder / 'data').rglob('*') if p.is_file()}, before)
        self.assertEqual({name: (folder / name).read_bytes() for name in private}, private)
        compose = yaml.safe_load((folder / 'docker-compose.yml').read_text())
        self.assertIn('${APP_DATA_DIR}/data/postgres-init:/docker-entrypoint-initdb.d:ro', compose['services']['postgres']['volumes'])

    def test_powpow_metadata_repair_does_not_require_sql_seeds(self):
        app_id = 'willitmod-dev-powpow'
        folder = self.install(app_id)
        compose = yaml.safe_load((folder / 'docker-compose.yml').read_text())
        compose['services']['litecoin']['user'] = 'root'
        (folder / 'docker-compose.yml').write_text(yaml.safe_dump(compose))
        self.host.recover(app_id, 'repair', False)
        self.assertFalse((folder / 'data/postgres-init').exists())
        self.assertEqual((folder / 'data/wallet.dat').read_bytes(), b'precious-wallet-sentinel')
        self.assertEqual(self.host.calls, [(app_id, 'stop')])

    def test_powpow_seed_metadata_cannot_expand_into_other_app_data(self):
        app_id = 'willitmod-dev-powpow'
        folder = self.install(app_id)
        for requirements in ({}, {'data/wallet.dat': {'sha256': '0' * 64}},
                             {name: {'sha256': 'invalid'} for name in engine.POWPOW_SEEDS}):
            with self.subTest(requirements=requirements):
                self.catalog['apps'][app_id]['required_existing_files'] = requirements
                with patch.object(self.host, 'backup') as backup, self.assertRaisesRegex(engine.RecoveryError, 'prerequisite metadata is invalid'):
                    self.host.recover(app_id, 'update', False)
                backup.assert_not_called()
                self.assertEqual(self.host.calls, [])
                self.assertEqual((folder / 'data/wallet.dat').read_bytes(), b'precious-wallet-sentinel')

    def test_same_version_reapply_and_idempotent_repair(self):
        self.install()
        self.host.recover(BTC, 'update', False)
        self.assertEqual(self.host.repair_plan(BTC), ({}, []))

    def test_stop_failure_keeps_recipe_and_backup_without_replacing_node(self):
        folder = self.install()
        original = (folder / 'docker-compose.yml').read_bytes()
        self.host.fail = 'stop'
        with self.assertRaises(engine.RecoveryError):
            self.host.recover(BTC, 'update', True)
        self.assertEqual((folder / 'docker-compose.yml').read_bytes(), original)
        self.assertEqual(self.host.list_backups()[0]['phase'], 'needs-review-bootstrapping-stop')
        self.assertEqual(self.host.calls, [(BTC, 'stop')])

    def test_failed_start_does_not_automatically_downgrade_or_restore_data(self):
        folder = self.install()
        self.host.fail = 'start'
        with self.assertRaises(engine.RecoveryError):
            self.host.recover(BTC, 'update', True)
        self.assertEqual(self.host.list_backups()[0]['phase'], 'needs-review-starting')
        self.assertEqual((folder / 'data/wallet.dat').read_bytes(), b'precious-wallet-sentinel')

    def test_backup_restore_exact_files_modes_and_new_file_removal(self):
        folder = self.install()
        (folder / 'hooks').mkdir(exist_ok=True)
        (folder / 'hooks/old-hook').write_text('#!/bin/sh\ntrue\n')
        (folder / 'hooks/old-hook').chmod(0o750)
        (folder / 'exports.sh').unlink()
        names = self.host.metadata_names(folder)
        originals = {name: ((folder / name).read_bytes(), stat.S_IMODE((folder / name).stat().st_mode)) for name in names}
        result = self.host.recover(BTC, 'update', False)
        self.assertFalse((folder / 'hooks/old-hook').exists())
        self.assertTrue((folder / 'exports.sh').exists())
        restored = self.host.restore(result['backup'])
        self.assertEqual(restored['state'], 'stopped')
        self.assertFalse((folder / 'exports.sh').exists())
        self.assertEqual({name: ((folder / name).read_bytes(), stat.S_IMODE((folder / name).stat().st_mode)) for name in names}, originals)
        self.assertEqual((folder / '.env').read_text(), 'RPC_PASSWORD=must-stay-private\n')
        self.assertEqual(stat.S_IMODE((self.host.backups / result['backup'] / 'index.json').stat().st_mode), 0o600)

    def test_restore_running_app_is_rejected(self):
        self.install()
        result = self.host.recover(BTC, 'update', True)
        with self.assertRaisesRegex(engine.RecoveryError, 'Stop the app'):
            self.host.restore(result['backup'])

    def test_reject_symlink_hardlink_and_traversal(self):
        folder = self.install()
        for name in ['../umbrel.yaml', '/etc/passwd', 'data/wallet.dat', 'settings.yml', '.env', 'hooks/../exports.sh']:
            with self.subTest(name=name), self.assertRaises(engine.RecoveryError):
                engine.safe_path(folder, name)
        path = folder / 'exports.sh'
        path.unlink(); path.symlink_to(folder / 'data/wallet.dat')
        with self.assertRaises(engine.RecoveryError):
            self.host.recover(BTC, 'update', False)
        path.unlink(); os.link(folder / 'data/wallet.dat', path)
        with self.assertRaises(engine.RecoveryError):
            self.host.recover(BTC, 'update', False)
        self.assertEqual(self.host.calls, [])

    def test_catalog_integrity_and_umbrel_bc2_definition(self):
        self.install()
        for app_id in self.catalog['apps']:
            with self.subTest(app=app_id):
                files = self.host.target(app_id)
                self.assertIn('docker-compose.yml', files)
                self.assertTrue(all(engine.allowed(name) for name in files))
        target = self.host.target('willitmod-dev-bc2')
        self.assertEqual(target['docker-compose.yml'], target['docker-compose.yml.template'])
        self.assertNotIn(b'/etc/5tratumos/build.json', target['docker-compose.yml'])
        self.catalog['apps'][BTC]['files']['exports.sh']['sha256'] = '0' * 64
        with self.assertRaisesRegex(engine.RecoveryError, 'integrity'):
            self.host.target(BTC)

    def test_only_installed_allowlist_not_arbitrary_apps(self):
        self.install()
        for app_id in ['bitcoin', engine.SELF, '../../etc', 'willitmod-dev-dgb']:
            with self.subTest(app=app_id), self.assertRaises(engine.RecoveryError):
                self.host.recover(app_id, 'update', False)

    def test_frac_port_and_pow_uid_changes_are_narrow(self):
        value = {'services': {'app': {'ports': ['21225:3000/tcp', '7891:3333']}}}
        actual, _ = engine.fix_compose(value, 'willitmod-dev-fracattack')
        self.assertEqual(actual['services']['app']['ports'], ['7891:3333'])
        value = {'services': {'litecoin': {'image': 'original'}, 'dogecoin': {'image': 'original'}}}
        actual, _ = engine.fix_compose(value, 'willitmod-dev-powpow')
        self.assertTrue(all(service == {'image': 'original', 'user': '1000:1000'} for service in actual['services'].values()))


class APITests(unittest.TestCase):
    def setUp(self):
        self.client = server.app.test_client()
        server.sessions.clear(); server.jobs.clear(); server.failed_logins.clear()
        self.headers = {'X-Fumbrel-Client': '1', 'Origin': 'http://localhost'}
        self.scan = {'apps': [], 'backups': [], 'release': 'test'}

    def login(self):
        with patch.object(server, 'remote', return_value=self.scan):
            response = self.client.post('/api/login', json={'username': 'umbrel', 'password': 'test-private'}, headers=self.headers)
        self.assertEqual(response.status_code, 200)
        self.headers['X-Fumbrel-Session'] = response.json['token']
        return response

    def test_direct_container_access_requires_session(self):
        self.assertEqual(self.client.get('/api/scan', headers=self.headers).status_code, 401)
        self.assertEqual(self.client.post('/api/jobs', json={}, headers=self.headers).status_code, 401)

    def test_cross_origin_and_simple_form_requests_rejected_before_ssh(self):
        with patch.object(server, 'remote') as remote:
            response = self.client.post('/api/login', json={}, headers={**self.headers, 'Origin': 'http://evil.example'})
            self.assertEqual(response.status_code, 403)
            self.assertEqual(self.client.post('/api/login', data={'password': 'x'}).status_code, 403)
            remote.assert_not_called()

    def test_session_expiry_and_logout_remove_credentials(self):
        response = self.login()
        session = server.sessions[response.json['token']]
        session['last'] = time.monotonic() - server.SESSION_TTL - 1
        server.expire_sessions()
        self.assertEqual(session['credentials'], {})
        self.assertEqual(self.client.get('/api/scan', headers=self.headers).status_code, 401)
        response = self.login(); session = server.sessions[response.json['token']]
        self.assertEqual(self.client.post('/api/logout', json={}, headers=self.headers).status_code, 200)
        self.assertEqual(session['credentials'], {})

    def test_arbitrary_host_command_and_app_rejected(self):
        with patch.object(server, 'remote') as remote:
            self.assertEqual(self.client.post('/api/login', json={'host': 'evil'}, headers=self.headers).status_code, 400)
            remote.assert_not_called()
        self.login()
        for payload in [{'action': 'shell', 'command': 'id'}, {'action': 'recover', 'apps': ['bitcoin'], 'mode': 'update'}, {'action': 'restore', 'backup': '../secret'}]:
            self.assertEqual(self.client.post('/api/jobs', json=payload, headers=self.headers).status_code, 400)

    def test_failed_login_rate_limit(self):
        with patch.object(server, 'remote', side_effect=server.AccessError('Rejected')) as remote:
            for _ in range(5):
                self.assertEqual(self.client.post('/api/login', json={'password': 'wrong'}, headers=self.headers).status_code, 400)
            self.assertEqual(self.client.post('/api/login', json={'password': 'wrong'}, headers=self.headers).status_code, 429)
            self.assertEqual(remote.call_count, 5)

    def test_passwords_not_in_response_report_or_cookies(self):
        response = self.login()
        self.assertNotIn('test-private', response.get_data(as_text=True))
        self.assertNotIn('Set-Cookie', response.headers)
        self.assertIn("frame-ancestors 'none'", response.headers['Content-Security-Policy'])

    def test_ssh_key_mismatch_does_not_execute_engine(self):
        key = server.paramiko.RSAKey.generate(1024)
        with patch.object(server, 'host_key', return_value=key), patch.object(server.paramiko, 'SSHClient') as client:
            client.return_value.connect.side_effect = server.paramiko.BadHostKeyException('host.docker.internal', key, key)
            with self.assertRaisesRegex(server.AccessError, 'host key mismatch'):
                server.remote({'username': 'umbrel', 'password': 'private', 'sudo_password': 'private'}, 'scan')
            client.return_value.exec_command.assert_not_called()
            policy = client.return_value.set_missing_host_key_policy.call_args.args[0]
            self.assertIsInstance(policy, server.paramiko.RejectPolicy)


if __name__ == '__main__':
    unittest.main()
