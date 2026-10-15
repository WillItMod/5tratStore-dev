"""Stop/recovery safety control flow only; no synthetic network protocol or Docker run."""
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

POW = engine.POWPOW
IDS = {'litecoin': 'a' * 64, 'dogecoin': 'b' * 64}


class Host(engine.Engine):
    def __init__(self, *args):
        super().__init__(*args)
        self.lifecycle_calls = []
        self.live = True

    def lifecycle(self, app_id, action):
        self.lifecycle_calls.append((app_id, action))
        self.live = False

    def running(self, app_id):
        return [{'id': cid, 'service': service} for service, cid in IDS.items()] if self.live else []


class PowPowStopTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(); self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        home = self.root / 'app-data' / engine.SELF; home.mkdir(parents=True)
        (self.root / 'umbrel.yaml').write_text(json.dumps({'apps': [POW]}))
        self.folder = self.root / 'app-data' / POW; self.folder.mkdir()
        (self.folder / 'data').mkdir()
        for service in engine.POWPOW_NODES: (self.folder / 'data' / service).mkdir()
        (self.folder / 'data/wallet.dat').write_bytes(b'private-fixture-sentinel')
        (self.folder / 'data/wallet.dat').chmod(0o640)
        (self.folder / '.env').write_bytes(b'PRIVATE_FIXTURE=not-for-output\n')
        (self.folder / '.env').chmod(0o600)
        self.installed = {'services': {}}
        for service, known in engine.POWPOW_NODES.items():
            self.installed['services'][service] = {'image': known['image'], 'user': '1000:1000',
                'volumes': ['${APP_DATA_DIR}/data:/data']}
        self.write_installed()
        (self.folder / 'umbrel-app.yml').write_text(json.dumps({'id': POW, 'version': '0.2.37-dev.3'}))
        target = copy.deepcopy(self.installed)
        for node in target['services'].values():
            node.update(stop_signal='SIGTERM', stop_grace_period='15m30s')
        def record(value):
            body = json.dumps(value).encode()
            return {'body': base64.b64encode(body).decode(), 'sha256': hashlib.sha256(body).hexdigest(), 'mode': 0o644}
        self.entry = {'source_id': POW, 'version': '0.2.37-dev.4', 'files': {
            'docker-compose.yml': record(target),
            'umbrel-app.yml': record({'id': POW, 'version': '0.2.37-dev.4'})}}
        self.entry['required_existing_files'] = {}
        for name in engine.POWPOW_SEEDS:
            path = self.folder / name; path.parent.mkdir(exist_ok=True)
            body = ('-- owned read-only prerequisite ' + name + '\n').encode()
            path.write_bytes(body)
            self.entry['required_existing_files'][name] = {'sha256': engine.digest(body)}
        self.host = Host(str(home), {'apps': {POW: self.entry}, 'legacy_exports': []})
        self.before = {}
        self.images = {}
        for service, known in engine.POWPOW_NODES.items():
            config_id = known['configs']['amd64']
            self.images[service] = {'Id': config_id, 'Architecture': 'amd64'}
            self.before[service] = {'Id': IDS[service], 'Image': config_id,
                'Config': {'Image': known['image'], 'User': '1000:1000', 'StopSignal': None,
                    'StopTimeout': None, 'Entrypoint': ['/usr/local/bin/start-' + service], 'Cmd': None,
                    'Labels': {'com.docker.compose.project': POW, 'com.docker.compose.service': service}},
                'Mounts': [{'Type': 'bind', 'Source': str(self.folder / 'data'), 'Destination': '/data', 'RW': True}],
                'State': {'Running': True, 'Paused': False, 'Restarting': False, 'OOMKilled': False,
                    'ExitCode': 0, 'StartedAt': '2026-10-15T00:00:00Z', 'FinishedAt': '0001-01-01T00:00:00Z'}}
        self.after = copy.deepcopy(self.before)
        for row in self.after.values():
            row['State'].update(Running=False, FinishedAt='2026-10-15T00:00:31Z')
        self.ids = list(IDS.values()); self.ids_after = None
        self.did_stop = False; self.stopped_ids = []; self.stop_calls = []; self.command_calls = []; self.error = None
        self.inspect_calls = 0; self.change_before_signal = False
        self.unstopped_state_change = {}
        def command(argv, **kwargs):
            self.command_calls.append(argv)
            if argv[:2] == ['docker', 'ps']:
                return '\n'.join(self.ids_after if self.did_stop and self.ids_after is not None else self.ids)
            if argv[:3] == ['docker', 'image', 'inspect']:
                service = next(s for s, k in engine.POWPOW_NODES.items() if argv[3] in (k['image'], k['image'] + '@' + k['index']))
                return json.dumps([self.images[service]])
            self.assertEqual(argv[:2], ['docker', 'inspect'])
            self.inspect_calls += 1
            rows = []
            for cid in argv[2:]:
                service = next(s for s, value in IDS.items() if value == cid)
                rows.append(self.after[service] if self.did_stop and cid in self.stopped_ids else self.before[service])
            if self.change_before_signal and self.inspect_calls == 2:
                rows = copy.deepcopy(rows); rows[1]['State']['StartedAt'] = '2026-10-15T00:00:02Z'
            return json.dumps(rows)
        def stop(argv, **kwargs):
            self.stop_calls.append((argv, kwargs))
            if isinstance(self.error, Exception):
                raise self.error
            if self.error:
                return subprocess.CompletedProcess(argv, self.error)
            self.stopped_ids = argv[4:]; self.did_stop = True
            self.before['dogecoin']['State'].update(self.unstopped_state_change)
            return subprocess.CompletedProcess(argv, 0)
        for name, value in [('yaml_load', lambda body: yaml.safe_load(body)), ('command', command)]:
            p = patch.object(engine, name, value); p.start(); self.addCleanup(p.stop)
        p = patch.object(engine.subprocess, 'run', stop); p.start(); self.addCleanup(p.stop)

    def write_installed(self):
        path = self.folder / 'docker-compose.yml'
        path.write_text(json.dumps(self.installed)); path.chmod(0o600)

    def private_snapshot(self):
        return {name: ((self.folder / name).read_bytes(), stat.S_IMODE((self.folder / name).stat().st_mode))
                for name in ['.env', 'data/wallet.dat', *engine.POWPOW_SEEDS]}

    def assert_no_stop(self):
        self.assertEqual(self.stop_calls, [])
        self.assertEqual(self.host.lifecycle_calls, [])

    def test_both_known_legacy_nodes_clean_before_one_normal_stop(self):
        self.host.stop(POW)
        self.assertEqual(self.stop_calls[0][0], ['docker', 'stop', '--time', '-1', *IDS.values()])
        self.assertEqual(self.stop_calls[0][1]['timeout'], 960)
        self.assertEqual(len(self.stop_calls), 1)
        self.assertEqual(self.host.lifecycle_calls, [(POW, 'stop')])

    def test_unknown_second_node_prevents_signal_to_already_admitted_first_node(self):
        self.before['dogecoin']['Config']['Image'] = 'unreviewed-node'
        with self.assertRaises(engine.RecoveryError): self.host.stop(POW)
        self.assert_no_stop()

    def test_exact_immutable_refs_and_arm64_configs_are_admitted(self):
        for service, known in engine.POWPOW_NODES.items():
            ref = known['image'] + '@' + known['index']
            self.installed['services'][service]['image'] = ref
            self.images[service] = {'Id': known['configs']['arm64'], 'Architecture': 'arm64'}
            for rows in [self.before, self.after]:
                rows[service]['Image'] = known['configs']['arm64']; rows[service]['Config']['Image'] = ref
        self.write_installed()
        self.host.stop(POW)
        self.assertEqual(self.stop_calls[0][0], ['docker', 'stop', '--time', '-1', *IDS.values()])

    def index_image_identity(self, service, arch='arm64'):
        known = engine.POWPOW_NODES[service]
        self.images[service] = {'Id': known['index'], 'Architecture': arch,
            'RootFS': {'Type': 'layers', 'Layers': engine.POWPOW_INDEX_ROOTFS[service][arch]}}
        self.before[service]['Image'] = self.after[service]['Image'] = known['index']

    def test_exact_docker29_index_identity_requires_selected_platform_rootfs(self):
        for service in engine.POWPOW_NODES: self.index_image_identity(service)
        self.host.stop(POW)
        self.assertEqual(self.stop_calls[0][0], ['docker', 'stop', '--time', '-1', *IDS.values()])

    def test_known_index_wrong_architecture_or_rootfs_refused_before_signal(self):
        self.index_image_identity('dogecoin')
        valid = copy.deepcopy(self.images['dogecoin'])
        variants = [dict(valid, Architecture='unknown'),
            dict(valid, Architecture='amd64'), dict(valid, RootFS={'Type': 'layers', 'Layers': ['sha256:' + 'e' * 64]}),
            dict(valid, RootFS={'Type': 'layers', 'Layers': valid['RootFS']['Layers'][::-1]}),
            dict(valid, RootFS={'Type': 'unknown', 'Layers': valid['RootFS']['Layers']})]
        for variant in variants:
            with self.subTest(variant=variant):
                self.images['dogecoin'] = variant
                with self.assertRaises(engine.RecoveryError): self.host.stop(POW)
        self.assert_no_stop()

    def test_current_930_and_infinite_grace_are_no_preparatory_stop(self):
        for grace in [930, -1]:
            with self.subTest(grace=grace):
                for row in self.before.values(): row['Config'].update(StopSignal='SIGTERM', StopTimeout=grace)
                result = self.host.stop_legacy_powpow(POW)
                self.assertEqual(result, {'stopped': [], 'adequate_or_cleanly_stopped': True})
        self.assert_no_stop()

    def test_mixed_current_and_legacy_policy_only_signals_legacy_cid(self):
        self.before['dogecoin']['Config']['StopTimeout'] = 930
        self.host.stop(POW)
        self.assertEqual(self.stop_calls[0][0], ['docker', 'stop', '--time', '-1', IDS['litecoin']])
        self.assertEqual(self.host.lifecycle_calls, [(POW, 'stop')])

    def created_node(self, service):
        self.before[service]['State'] = {'Status': 'created', 'Running': False, 'Paused': False,
            'Restarting': False, 'OOMKilled': False, 'Dead': False, 'Pid': 0, 'ExitCode': 0,
            'Error': '', 'StartedAt': '0001-01-01T00:00:00Z', 'FinishedAt': '0001-01-01T00:00:00Z'}

    def test_created_node_and_adequate_node_need_no_preparatory_stop_or_clean_claim(self):
        self.created_node('dogecoin')
        (self.folder / 'data/dogecoin').rmdir()
        self.before['litecoin']['Config']['StopTimeout'] = 930
        self.assertEqual(self.host.stop_legacy_powpow(POW), {'stopped': [],
            'no_preparatory_stop_required': True, 'never_started': [IDS['dogecoin']]})
        self.assert_no_stop()

    def test_created_node_and_short_grace_node_only_stop_started_node(self):
        self.created_node('dogecoin')
        self.assertEqual(self.host.stop_legacy_powpow(POW), {'stopped': [IDS['litecoin']],
            'exit': 0, 'never_started': [IDS['dogecoin']]})
        self.assertEqual(self.stop_calls[0][0], ['docker', 'stop', '--time', '-1', IDS['litecoin']])

    def test_malformed_or_dirty_created_state_blocks_every_signal(self):
        self.created_node('dogecoin')
        original = copy.deepcopy(self.before['dogecoin']['State'])
        for key, value in [('Status', 'exited'), ('Pid', 1), ('Pid', False), ('ExitCode', 137),
                           ('Dead', True), ('Error', 'start failed'), ('StartedAt', 'invalid'),
                           ('FinishedAt', '2026-10-15T00:00:20Z')]:
            with self.subTest(key=key):
                self.before['dogecoin']['State'] = copy.deepcopy(original)
                self.before['dogecoin']['State'][key] = value
                with self.assertRaises(engine.RecoveryError): self.host.stop(POW)
        self.assert_no_stop()

    def test_adequate_node_health_refresh_does_not_change_lifecycle_identity(self):
        self.before['dogecoin']['Config']['StopTimeout'] = 930
        self.before['dogecoin']['State']['Health'] = {'Status': 'starting', 'Log': []}
        self.unstopped_state_change = {'Health': {'Status': 'healthy', 'Log': [{'ExitCode': 0}]}}
        self.host.stop(POW)
        self.assertEqual(self.host.lifecycle_calls, [(POW, 'stop')])

    def test_adequate_node_lifecycle_change_still_blocks_normal_stop(self):
        self.before['dogecoin']['Config']['StopTimeout'] = 930
        self.unstopped_state_change = {'Pid': 999}
        with self.assertRaises(engine.RecoveryError): self.host.stop(POW)
        self.assertEqual(self.host.lifecycle_calls, [])

    def test_empty_project_is_only_an_explicit_no_running_result_not_clean_exit_proof(self):
        self.ids = []
        self.assertEqual(self.host.stop_legacy_powpow(POW), {'stopped': [], 'no_running_project': True})
        self.assert_no_stop()

    def test_missing_duplicate_or_short_nodes_are_refused_when_project_running(self):
        for ids in [[IDS['litecoin']], [IDS['litecoin'], IDS['litecoin']], ['a' * 12]]:
            with self.subTest(ids=ids):
                self.ids = ids
                with self.assertRaises(engine.RecoveryError): self.host.stop(POW)
        self.assert_no_stop()

    def test_duplicate_service_label_refused(self):
        self.before['dogecoin']['Config']['Labels']['com.docker.compose.service'] = 'litecoin'
        with self.assertRaises(engine.RecoveryError): self.host.stop(POW)
        self.assert_no_stop()

    def test_changed_generation_rechecked_before_any_signal(self):
        self.change_before_signal = True
        with self.assertRaises(engine.RecoveryError): self.host.stop(POW)
        self.assert_no_stop()

    def test_redirected_core_data_is_refused_before_any_signal(self):
        p = self.folder / 'data/dogecoin'; p.rmdir(); p.symlink_to(self.folder / 'data/litecoin', target_is_directory=True)
        with self.assertRaises(engine.RecoveryError): self.host.stop(POW)
        self.assert_no_stop()

    def test_unknown_installed_image_command_mount_user_and_policy_refused(self):
        base = copy.deepcopy(self.installed)
        for key, value in [('image', 'ghcr.io/willitmod/powpow-litecoin:other'), ('build', {'context': '.'}),
                           ('command', ['different-daemon']), ('entrypoint', ['/custom']), ('user', '0'),
                           ('volumes', ['/unrelated:/data']), ('stop_signal', 'SIGINT'), ('stop_grace_period', '30s')]:
            with self.subTest(key=key):
                self.installed = copy.deepcopy(base); self.installed['services']['litecoin'][key] = value; self.write_installed()
                with self.assertRaises(engine.RecoveryError): self.host.stop(POW)
        self.assert_no_stop()

    def test_retagged_or_wrong_architecture_configs_refused(self):
        for field, value in [('Id', 'sha256:' + 'f' * 64), ('Architecture', 'unknown')]:
            with self.subTest(field=field):
                old = self.images['dogecoin'][field]; self.images['dogecoin'][field] = value
                with self.assertRaises(engine.RecoveryError): self.host.stop(POW)
                self.images['dogecoin'][field] = old
        self.assert_no_stop()

    def test_unknown_actual_signal_grace_user_command_and_mount_refused(self):
        base = copy.deepcopy(self.before)
        for key, value in [('StopSignal', 'SIGKILL'), ('StopSignal', 'SIGINT'), ('StopTimeout', 0),
                           ('StopTimeout', 120), ('StopTimeout', 900), ('StopTimeout', 10.0), ('StopTimeout', True),
                           ('StopTimeout', '10'), ('User', '0'), ('Entrypoint', ['/custom']), ('Cmd', ['override'])]:
            with self.subTest(key=key, value=value):
                self.before = copy.deepcopy(base); self.before['dogecoin']['Config'][key] = value
                with self.assertRaises(engine.RecoveryError): self.host.stop(POW)
        self.before = copy.deepcopy(base); self.before['dogecoin']['Mounts'][0]['Source'] = '/unrelated'
        with self.assertRaises(engine.RecoveryError): self.host.stop(POW)
        self.assert_no_stop()

    def test_paused_restarting_oom_or_wrong_project_refused(self):
        for key in ['Paused', 'Restarting', 'OOMKilled']:
            self.before['dogecoin']['State'][key] = True
            with self.assertRaises(engine.RecoveryError): self.host.stop(POW)
            self.before['dogecoin']['State'][key] = False
        self.before['dogecoin']['Config']['Labels']['com.docker.compose.project'] = 'unrelated'
        with self.assertRaises(engine.RecoveryError): self.host.stop(POW)
        self.assert_no_stop()

    def test_dirty_stopped_node_blocks_signal_to_other_node(self):
        self.before['dogecoin']['State'].update(Running=False, ExitCode=137, FinishedAt='2026-10-15T00:00:20Z')
        with self.assertRaises(engine.RecoveryError): self.host.stop(POW)
        self.assert_no_stop()

    def test_replaced_generation_nonzero_oom_or_mount_change_never_reaches_normal_stop(self):
        base = copy.deepcopy(self.after)
        for section, key, value in [('State', 'StartedAt', '2026-10-15T00:00:01Z'), ('State', 'ExitCode', 137),
                                   ('State', 'OOMKilled', True), ('State', 'Running', True),
                                   ('State', 'FinishedAt', '0001-01-01T00:00:00Z'), ('Config', 'User', '0')]:
            with self.subTest(key=key):
                self.did_stop = False; self.after = copy.deepcopy(base); self.after['dogecoin'][section][key] = value
                with self.assertRaises(engine.RecoveryError): self.host.stop(POW)
        self.assertEqual(self.host.lifecycle_calls, [])

    def test_new_project_generation_never_reaches_normal_stop(self):
        self.ids_after = list(IDS.values()) + ['c' * 64]
        with self.assertRaises(engine.RecoveryError): self.host.stop(POW)
        self.assertEqual(self.host.lifecycle_calls, [])

    def test_timeout_retains_backup_and_every_private_byte_mode_without_normal_stop(self):
        before = self.private_snapshot()
        self.error = subprocess.TimeoutExpired(['docker', 'stop'], 960)
        with self.assertRaisesRegex(engine.RecoveryError, 'still pending'): self.host.recover(POW, 'update', False)
        self.assertEqual(self.private_snapshot(), before)
        self.assertEqual(self.host.lifecycle_calls, [])
        self.assertEqual(len(self.stop_calls), 1)
        self.assertEqual(self.host.list_backups()[0]['phase'], 'needs-review-bootstrapping-stop')

    def test_cli_failure_or_unavailability_never_reaches_normal_stop(self):
        for error in [1, OSError()]:
            with self.subTest(error=type(error).__name__):
                self.error = error
                with self.assertRaises(engine.RecoveryError): self.host.stop(POW)
        self.assertEqual(self.host.lifecycle_calls, [])

    def test_outdated_bundle_refused_before_backup_stop_and_private_writes(self):
        body = json.dumps(self.installed).encode()
        self.entry['files']['docker-compose.yml'].update(body=base64.b64encode(body).decode(), sha256=engine.digest(body))
        before = self.private_snapshot()
        with self.assertRaisesRegex(engine.RecoveryError, 'outdated'): self.host.recover(POW, 'update', False)
        self.assertFalse(self.host.backups.exists())
        self.assertEqual(self.private_snapshot(), before)
        self.assertEqual(self.command_calls, [])
        self.assert_no_stop()

    def test_corrupt_bundle_identity_or_unknown_target_shape_refused_before_backup(self):
        self.entry['files']['docker-compose.yml']['sha256'] = '0' * 64
        with self.assertRaises(engine.RecoveryError): self.host.recover(POW, 'update', False)
        self.assertFalse(self.host.backups.exists()); self.assert_no_stop()

    def test_successful_update_preserves_private_data_and_installs_930_policy(self):
        before = self.private_snapshot()
        result = self.host.recover(POW, 'update', False)
        self.assertEqual(result['state'], 'stopped')
        self.assertEqual(self.private_snapshot(), before)
        model = yaml.safe_load((self.folder / 'docker-compose.yml').read_bytes())
        for node in model['services'].values():
            self.assertEqual(node['stop_grace_period'], '15m30s')
            self.assertEqual(node['stop_signal'], 'SIGTERM')
        self.assertEqual(self.host.lifecycle_calls, [(POW, 'stop')])

    def test_other_apps_do_not_enter_powpow_guard(self):
        for app_id in ['willitmod-dev-ppc', 'willitmod-dev-btc', 'willitmod-powpow']:
            self.host.stop_legacy_powpow(app_id)
        self.assertEqual(self.command_calls, []); self.assert_no_stop()


if __name__ == '__main__':
    unittest.main()
