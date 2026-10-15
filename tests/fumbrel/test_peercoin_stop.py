"""Control-flow regressions only; no fake RPC, Stratum or real Docker execution."""
import base64
import copy
import hashlib
import json
from pathlib import Path
import stat
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

import yaml

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'willitmod-dev-fumbrel/app'))
import engine

PPC = 'willitmod-dev-ppc'
CID = 'a' * 64
IMAGE = 'ghcr.io/willitmod/axeppc-peercoind:legacy@sha256:' + 'b' * 64


class Host(engine.Engine):
    def __init__(self, *args):
        super().__init__(*args)
        self.lifecycle_calls = []
        self.live = True

    def lifecycle(self, app_id, action):
        self.lifecycle_calls.append((app_id, action))
        self.live = False

    def running(self, app_id):
        return [{'id': CID, 'service': 'ppcd'}] if self.live else []


class PeercoinStopTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory(); self.addCleanup(temp.cleanup)
        self.root = Path(temp.name).resolve()
        home = self.root / 'app-data' / engine.SELF; home.mkdir(parents=True)
        (self.root / 'umbrel.yaml').write_text(json.dumps({'apps': [PPC]}))
        self.folder = self.root / 'app-data' / PPC; self.folder.mkdir()
        installed = {'services': {'ppcd': {'image': IMAGE}}}
        (self.folder / 'docker-compose.yml').write_text(json.dumps(installed))
        (self.folder / 'docker-compose.yml').chmod(0o600)
        (self.folder / 'umbrel-app.yml').write_text(json.dumps({'id': PPC, 'version': '0.2.37-dev'}))
        (self.folder / 'data').mkdir()
        (self.folder / 'data/wallet.dat').write_bytes(b'private-wallet-sentinel')
        (self.folder / 'data/wallet.dat').chmod(0o640)
        (self.folder / '.env').write_text('PRIVATE_RPC_VALUE=not-for-output\n')
        (self.folder / '.env').chmod(0o600)
        target = {'services': {'ppcd': {'image': IMAGE, 'stop_signal': 'SIGTERM', 'stop_grace_period': '2m'}}}
        def record(body):
            body = json.dumps(body).encode()
            return {'body': base64.b64encode(body).decode(), 'sha256': hashlib.sha256(body).hexdigest(), 'mode': 0o644}
        self.entry = {'source_id': PPC, 'version': '0.2.37-dev.1', 'files': {
            'docker-compose.yml': record(target),
            'umbrel-app.yml': record({'id': PPC, 'version': '0.2.37-dev.1'})}}
        self.host = Host(str(home), {'apps': {PPC: self.entry}, 'legacy_exports': []})
        self.before = {'Id': CID, 'Image': 'sha256:' + 'd' * 64,
            'Config': {'Image': IMAGE, 'StopSignal': 'SIGTERM', 'StopTimeout': 10,
                       'Labels': {'com.docker.compose.project': PPC, 'com.docker.compose.service': 'ppcd'}},
            'State': {'Running': True, 'Paused': False, 'Restarting': False, 'OOMKilled': False,
                      'ExitCode': 0, 'StartedAt': '2026-10-15T00:00:00Z', 'FinishedAt': '0001-01-01T00:00:00Z'}}
        self.after = copy.deepcopy(self.before)
        self.after['State'].update(Running=False, FinishedAt='2026-10-15T00:00:31Z')
        self.resolved_image_id = self.before['Image']
        self.ids = [CID]; self.inspect_calls = 0; self.stop_calls = []; self.cli_error = None
        self.command_calls = []
        def command(argv, **kwargs):
            self.command_calls.append(argv)
            if argv[:2] == ['docker', 'ps']:
                return '\n'.join(self.ids)
            if argv[:3] == ['docker', 'image', 'inspect']:
                return json.dumps([{'Id': self.resolved_image_id}])
            self.assertEqual(argv, ['docker', 'inspect', CID])
            self.inspect_calls += 1
            return json.dumps([self.before if self.inspect_calls == 1 else self.after])
        def stop(argv, **kwargs):
            self.stop_calls.append((argv, kwargs))
            if isinstance(self.cli_error, Exception):
                raise self.cli_error
            return subprocess.CompletedProcess(argv, self.cli_error or 0, stdout=CID, stderr='')
        for target, value in [('yaml_load', lambda b: yaml.safe_load(b)), ('command', command)]:
            p = patch.object(engine, target, value); p.start(); self.addCleanup(p.stop)
        p = patch.object(engine.subprocess, 'run', stop); p.start(); self.addCleanup(p.stop)

    def assert_no_stop_or_lifecycle(self):
        self.assertEqual(self.stop_calls, [])
        self.assertEqual(self.host.lifecycle_calls, [])

    def test_legacy_short_grace_requires_verified_zero_exit_before_ordinary_stop(self):
        self.host.stop(PPC)
        self.assertEqual(self.stop_calls[0][0], ['docker', 'stop', '--time', '-1', CID])
        self.assertEqual(self.stop_calls[0][1]['timeout'], 150)
        self.assertEqual(len(self.stop_calls), 1)
        self.assertEqual(self.host.lifecycle_calls, [(PPC, 'stop')])
        self.assertEqual(self.inspect_calls, 2)

    def test_implicit_linux_ten_second_default_is_protected(self):
        self.before['Config'].pop('StopTimeout')
        self.host.stop(PPC)
        self.assertEqual(len(self.stop_calls), 1)

    def test_observed_build_only_legacy_recipe_and_generated_image_are_protected(self):
        path = self.folder / 'docker-compose.yml'
        path.write_text(json.dumps({'services': {'ppcd': {'build': {'context': '${APP_DATA_DIR}/data/peercoind'}}}}))
        self.before['Config']['Image'] = PPC + '-ppcd'
        self.after['Config']['Image'] = PPC + '-ppcd'
        self.host.stop(PPC)
        self.assertEqual(self.stop_calls[0][0], ['docker', 'stop', '--time', '-1', CID])
        self.assertEqual(self.host.lifecycle_calls, [(PPC, 'stop')])

    def test_custom_or_ambiguous_build_recipe_is_refused(self):
        path = self.folder / 'docker-compose.yml'
        for node in [{'build': {'context': '/different/path'}},
                     {'build': {'context': '${APP_DATA_DIR}/data/peercoind', 'dockerfile': 'custom'}},
                     {'image': IMAGE, 'build': {'context': '${APP_DATA_DIR}/data/peercoind'}}]:
            with self.subTest(node=node):
                path.write_text(json.dumps({'services': {'ppcd': node}})); self.inspect_calls = 0
                with self.assertRaises(engine.RecoveryError): self.host.stop(PPC)
        self.assert_no_stop_or_lifecycle()

    def test_zero_grace_is_protected(self):
        self.before['Config']['StopTimeout'] = 0
        self.host.stop(PPC)
        self.assertEqual(len(self.stop_calls), 1)

    def test_current_and_infinite_stop_grace_need_no_preparatory_signal(self):
        for grace in [120, 180, -1]:
            with self.subTest(grace=grace):
                self.before['Config']['StopTimeout'] = grace; self.inspect_calls = 0
                self.host.stop_legacy_peercoin(PPC)
        self.assert_no_stop_or_lifecycle()

    def test_other_apps_are_outside_guard_without_docker_queries(self):
        for app in ['willitmod-dev-btc', 'willitmod-ppc', 'other-project']:
            self.host.stop_legacy_peercoin(app)
        self.assertEqual(self.command_calls, [])
        self.assert_no_stop_or_lifecycle()

    def test_stopped_node_needs_no_preparatory_signal(self):
        self.ids = []
        self.host.stop_legacy_peercoin(PPC)
        self.assertEqual(self.inspect_calls, 0)
        self.assert_no_stop_or_lifecycle()

    def test_duplicate_or_short_container_id_is_refused(self):
        for ids in [[CID, 'e' * 64], [CID[:12]], [CID, CID]]:
            with self.subTest(ids=ids):
                self.ids = ids
                with self.assertRaises(engine.RecoveryError): self.host.stop(PPC)
        self.assert_no_stop_or_lifecycle()

    def test_wrong_project_service_or_installed_image_is_refused(self):
        changes = [('com.docker.compose.project', 'other-app'), ('com.docker.compose.service', 'redis')]
        for key, value in changes:
            with self.subTest(label=key):
                old = self.before['Config']['Labels'][key]
                self.before['Config']['Labels'][key] = value; self.inspect_calls = 0
                with self.assertRaises(engine.RecoveryError): self.host.stop(PPC)
                self.before['Config']['Labels'][key] = old
        self.before['Config']['Image'] = IMAGE + '-mismatch'; self.inspect_calls = 0
        with self.assertRaises(engine.RecoveryError): self.host.stop(PPC)
        self.assert_no_stop_or_lifecycle()

    def test_paused_restarting_wrong_signal_and_invalid_timeout_are_refused(self):
        for section, key, value in [('State', 'Paused', True), ('State', 'Restarting', True),
                                    ('Config', 'StopSignal', 'SIGKILL'), ('Config', 'StopSignal', 'SIGINT'),
                                    ('Config', 'StopTimeout', True), ('Config', 'StopTimeout', '10')]:
            with self.subTest(key=key, value=value):
                old = self.before[section][key]; self.before[section][key] = value; self.inspect_calls = 0
                with self.assertRaises(engine.RecoveryError): self.host.stop(PPC)
                self.before[section][key] = old
        self.assert_no_stop_or_lifecycle()

    def test_unverified_catalog_policy_or_integrity_is_refused(self):
        self.entry['files']['docker-compose.yml']['sha256'] = '0' * 64
        with self.assertRaises(engine.RecoveryError): self.host.stop(PPC)
        self.assert_no_stop_or_lifecycle()

    def test_retagged_installed_image_is_refused(self):
        self.resolved_image_id = 'sha256:' + 'f' * 64
        with self.assertRaises(engine.RecoveryError): self.host.stop(PPC)
        self.assert_no_stop_or_lifecycle()

    def test_catalog_shorter_or_different_signal_policy_is_refused(self):
        for grace, signal in [('30s', 'SIGTERM'), ('2m', 'SIGKILL'), ('3m', 'SIGTERM')]:
            with self.subTest(grace=grace, signal=signal):
                body = json.dumps({'services': {'ppcd': {'image': IMAGE, 'stop_grace_period': grace, 'stop_signal': signal}}}).encode()
                self.entry['files']['docker-compose.yml'].update(body=base64.b64encode(body).decode(), sha256=hashlib.sha256(body).hexdigest())
                with self.assertRaises(engine.RecoveryError): self.host.stop(PPC)
        self.assert_no_stop_or_lifecycle()

    def test_timeout_never_reaches_ordinary_stop_or_recipe_replacement(self):
        self.cli_error = subprocess.TimeoutExpired(['docker', 'stop'], 150)
        names = ['docker-compose.yml', 'umbrel-app.yml', 'data/wallet.dat', '.env']
        before = {name: ((self.folder / name).read_bytes(), stat.S_IMODE((self.folder / name).stat().st_mode)) for name in names}
        with self.assertRaisesRegex(engine.RecoveryError, 'still pending'):
            self.host.recover(PPC, 'update', False)
        self.assertEqual(len(self.stop_calls), 1)
        self.assertEqual(self.host.lifecycle_calls, [])
        self.assertEqual({name: ((self.folder / name).read_bytes(), stat.S_IMODE((self.folder / name).stat().st_mode)) for name in names}, before)
        backups = self.host.list_backups()
        self.assertEqual(len(backups), 1)
        self.assertEqual(backups[0]['phase'], 'needs-review-bootstrapping-stop')

    def test_unavailable_or_failed_stop_never_reaches_ordinary_stop(self):
        for error in [OSError(), 1]:
            with self.subTest(error=type(error).__name__):
                self.cli_error = error; self.inspect_calls = 0
                with self.assertRaises(engine.RecoveryError): self.host.stop(PPC)
        self.assertEqual(self.host.lifecycle_calls, [])

    def test_nonzero_oom_running_or_changed_generation_never_reaches_ordinary_stop(self):
        for key, value in [('ExitCode', 137), ('ExitCode', 1), ('OOMKilled', True),
                           ('Running', True), ('StartedAt', '2026-10-15T00:00:01Z'),
                           ('FinishedAt', '0001-01-01T00:00:00Z')]:
            with self.subTest(key=key):
                original = self.after['State'][key]; self.after['State'][key] = value; self.inspect_calls = 0
                with self.assertRaises(engine.RecoveryError): self.host.stop(PPC)
                self.after['State'][key] = original
        self.assertEqual(self.host.lifecycle_calls, [])


if __name__ == '__main__': unittest.main()
