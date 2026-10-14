"""Permission watchdog supervision only, with real owned Linux filesystem cases."""
import copy
import hashlib
import json
import os
from pathlib import Path
import subprocess
import time
import unittest
import uuid

import yaml

ROOT = Path(__file__).resolve().parents[1]
APP = 'willitmod-dev-dgb'
RECORD = json.loads((ROOT / 'DGB-PERMISSION-SHUTDOWN-2026-10-14.json').read_text())
IMAGE = 'alpine@sha256:4bcff63911fcb4448bd4fdacec207030997caf25e9bea4045fa6c8c44de311d1'
OWNER = 'codex-dgb-permission-shutdown-20261014'
RECEIPTS = []


def digest(model):
    return hashlib.sha256(json.dumps(model, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def previous_permission_model(app_id, current):
    if app_id != APP:
        return copy.deepcopy(current)
    assert digest(current) == RECORD['afterModelSHA256']
    restored = copy.deepcopy(current)
    command = restored['services']['perm_watchdog']['command']
    assert hashlib.sha256(command[2].encode()).hexdigest() == RECORD['afterCommandSHA256']
    command[2] = RECORD['beforeCommand']
    assert digest(restored) == RECORD['beforeModelSHA256']
    return restored


def package_version(app_id, historical):
    if app_id != APP:
        return historical
    assert historical == RECORD['beforePackageVersion']
    return RECORD['packageVersion']


def current_command():
    return yaml.safe_load((ROOT / APP / 'docker-compose.yml').read_text())['services']['perm_watchdog']['command'][2]


class PermissionShutdownContract(unittest.TestCase):
    def test_exactly_one_watchdog_command_and_package_version_change(self):
        model = yaml.safe_load((ROOT / APP / 'docker-compose.yml').read_text())
        restored = previous_permission_model(APP, model)
        self.assertEqual({n:s['image'] for n,s in model['services'].items() if 'image' in s}, RECORD['imagesUnchanged'])
        self.assertEqual(model['services']['app']['environment'].get('APP_VERSION'), RECORD['applicationVersionFieldUnchanged'])
        self.assertEqual(RECORD['runtimeFieldChanged'], ['services', 'perm_watchdog', 'command', 2])
        self.assertEqual(model['services']['perm_watchdog']['command'][:2], ['/bin/sh', '-ec'])
        # Every existing repair statement remains literally the same, with only
        # the tracked-child runner prepended to its execution.
        after = current_command()
        for line in RECORD['beforeCommand'].splitlines():
            if line.lstrip().startswith(('chown ', 'chmod ', 'sleep 5')):
                self.assertIn(line.lstrip().replace('chown ', 'run_watchdog_child chown ', 1)
                    .replace('chmod ', 'run_watchdog_child chmod ', 1).replace('sleep 5', 'run_watchdog_child sleep 5'), after)
        self.assertEqual(digest(restored), RECORD['beforeModelSHA256'])
        subprocess.run(['sh', '-n'], input=after.replace('$$', '$'), text=True, check=True)
        manifest = yaml.safe_load((ROOT / APP / 'umbrel-app.yml').read_text())
        self.assertEqual(manifest['version'], RECORD['packageVersion'])

    def test_image_mode_role_interval_and_unrelated_command_changes_are_rejected(self):
        model = yaml.safe_load((ROOT / APP / 'docker-compose.yml').read_text())
        for kind in ('image', 'mode', 'role', 'interval', 'other-service'):
            changed = copy.deepcopy(model)
            if kind == 'image': changed['services']['perm_watchdog']['image'] = 'unreviewed:latest'
            elif kind == 'other-service': changed['services']['init_permissions']['command'][2] += '\necho unreviewed\n'
            else:
                before, after = {'mode':('chmod 700','chmod 777'), 'role':('70:70','1000:1000'), 'interval':('sleep 5','sleep 1')}[kind]
                changed['services']['perm_watchdog']['command'][2] = changed['services']['perm_watchdog']['command'][2].replace(before, after)
            with self.subTest(kind=kind), self.assertRaises(AssertionError):
                previous_permission_model(APP, changed)


def run(argv, timeout=90):
    return subprocess.check_output(argv, text=True, stderr=subprocess.PIPE, timeout=timeout).strip()


def inspect(cid):
    return json.loads(run(['docker', 'inspect', cid]))[0]


def helper(volume, script):
    return run(['docker', 'run', '--rm', '--label', 'dev.compat.owner=' + OWNER, '--network', 'none',
        '--read-only', '--mount', 'type=volume,src=' + volume + ',dst=/data', '--entrypoint', '/bin/sh', IMAGE, '-ec', script])


def new_tree(files=0):
    name = OWNER + '-' + uuid.uuid4().hex[:12]
    assert subprocess.run(['docker', 'volume', 'inspect', name], capture_output=True).returncode != 0
    assert run(['docker', 'volume', 'create', '--label', 'dev.compat.owner=' + OWNER, name]) == name
    helper(name, 'mkdir -p /data/pool/postgres /data/node/chain /data/pool/config /data/ui/state /data/templates; '
        'for dir in pool/postgres node/chain pool/config ui/state templates; do printf "owned permission sentinel\\n" >"/data/$dir/.sentinel"; done; '
        'chown 333:444 /data/node/chain /data/node/chain/.sentinel; chmod 0640 /data/pool/postgres/.sentinel; '
        'i=0; while [ "$i" -lt ' + str(files) + ' ]; do : >"/data/pool/postgres/file.$i"; i=$((i+1)); done')
    return name


def remove_volume(volume):
    item = json.loads(run(['docker', 'volume', 'inspect', volume]))[0]
    assert item['Labels']['dev.compat.owner'] == OWNER
    run(['docker', 'volume', 'rm', volume])


def start(volume, baseline=False, cpus='1'):
    body = (RECORD['beforeCommand'] if baseline else current_command()).replace('$$', '$')
    return run(['docker', 'run', '-d', '--name', OWNER + '-' + uuid.uuid4().hex[:12],
        '--label', 'dev.compat.owner=' + OWNER, '--network', 'none', '--read-only', '--cap-drop', 'ALL',
        '--cap-add', 'CHOWN', '--cap-add', 'FOWNER', '--cap-add', 'DAC_OVERRIDE', '--security-opt', 'no-new-privileges:true',
        '--memory', '128m', '--cpus', cpus, '--pids-limit', '64', '--mount', 'type=volume,src=' + volume + ',dst=/data',
        '--entrypoint', '/bin/sh', IMAGE, '-ec', body])


def stop(cid, signal, expected=0):
    before = inspect(cid)
    assert before['Config']['Labels']['dev.compat.owner'] == OWNER
    started = time.monotonic()
    if signal == 'TERM': run(['docker', 'stop', '--timeout', '5', cid], timeout=15)
    else:
        assert signal == 'INT'; run(['docker', 'kill', '--signal', 'INT', cid]); run(['docker', 'wait', cid], timeout=10)
    after = inspect(cid); elapsed = time.monotonic() - started
    assert not after['State']['Running'] and after['State']['Pid'] == 0 and not after['State']['OOMKilled']
    assert after['State']['ExitCode'] == expected
    assert expected == 137 or elapsed < 4
    RECEIPTS.append({'signal':signal,'exit_code':expected,'elapsed_s':round(elapsed,3),'container_pid_after':0,
        'oom_killed':False,'normal_docker_stop_used':signal=='TERM','owned_container':cid})


def cleanup(cid):
    state = inspect(cid)
    assert state['Config']['Labels']['dev.compat.owner'] == OWNER
    if state['State']['Running']: stop(cid, 'TERM')
    run(['docker', 'rm', '-v', cid])


def wait_repaired(volume, files=0):
    deadline = time.monotonic() + 30
    while True:
        summary = helper(volume, 'stat -c "%u:%g:%a" /data/pool/postgres; find /data/pool/postgres -type f ! -user 70 | wc -l')
        if summary.splitlines() == ['70:70:700', '0']: break
        assert time.monotonic() < deadline, 'Owned tree repair did not complete'
        time.sleep(.1)
    assert helper(volume, 'find /data/pool/postgres -type f -size 0c | wc -l') == str(files)


@unittest.skipUnless(os.environ.get('DGB_PERMISSION_DOCKER') == '1', 'opt-in actual owned Linux filesystem fixtures')
class ActualPermissionShutdown(unittest.TestCase):
    def test_idle_baseline_137_candidate_term_int_and_exact_repair_rules(self):
        volume = new_tree(); cid = None
        before_hashes = helper(volume, 'find /data -type f -exec sha256sum {} + | sort')
        try:
            for baseline, signal in [(True,'TERM'),(False,'TERM'),(False,'INT')]:
                cid = start(volume, baseline); wait_repaired(volume)
                stop(cid, signal, 137 if baseline else 0); cleanup(cid); cid = None
            self.assertEqual(helper(volume, 'find /data -type f -exec sha256sum {} + | sort'), before_hashes)
            self.assertEqual(helper(volume, 'stat -c "%u:%g" /data/node /data/pool/config /data/ui/state /data/templates'), '\n'.join(['1000:1000']*4))
            self.assertEqual(helper(volume, 'stat -c "%u:%g" /data/node/chain /data/node/chain/.sentinel'), '333:444\n333:444')
            self.assertEqual(helper(volume, 'stat -c "%a" /data/pool/postgres/.sentinel'), '640')
            # Existing policy deliberately does not repair child owners/mode if
            # the watched directory's UID/GID is already correct.
            helper(volume, 'chown 0:0 /data/pool/postgres/.sentinel; chmod 755 /data/pool/postgres')
            cid = start(volume); time.sleep(.2); stop(cid, 'TERM'); cleanup(cid); cid = None
            self.assertEqual(helper(volume, 'stat -c "%u:%g:%a" /data/pool/postgres /data/pool/postgres/.sentinel'), '70:70:755\n0:0:640')
            version=run(['docker','run','--rm','--label','dev.compat.owner='+OWNER,'--network','none','--read-only','--entrypoint','/bin/busybox',IMAGE]).splitlines()[0]
            self.assertIn('BusyBox v1.37.0',version)
            image=json.loads(run(['docker','image','inspect',IMAGE]))[0]
            RECEIPTS.append({'repair_rules_and_conditional_modes_exact':True,'node_children_untouched':True,'all_sentinel_bytes_unchanged':True,
                'immutable_fixture_image':IMAGE,'fixture_architecture':image['Architecture'],'actual_busybox_version':version})
        finally:
            if cid: cleanup(cid)
            remove_volume(volume)

    def test_real_recursive_chown_interrupt_has_no_orphan_and_normal_restart_finishes(self):
        for signal in ('TERM','INT'):
            volume = new_tree(32768); cid = None
            try:
                cid = start(volume, cpus='0.1'); deadline = time.monotonic() + 20
                while True:
                    rows = run(['docker','top',cid,'-eo','pid,ppid,comm']).splitlines()
                    active = [row for row in rows[1:] if row.split()[-1] == 'chown']
                    if active: break
                    assert time.monotonic() < deadline, 'Actual recursive chown was not observed'
                    time.sleep(.02)
                stop(cid,signal); cleanup(cid); cid = None
                snapshot = helper(volume, 'stat -c "%u:%g" /data/pool/postgres; find /data/pool/postgres -type f -user 70 | wc -l')
                time.sleep(.2)
                self.assertEqual(helper(volume, 'stat -c "%u:%g" /data/pool/postgres; find /data/pool/postgres -type f -user 70 | wc -l'), snapshot)
                owner, repaired = snapshot.splitlines(); self.assertLess(int(repaired),32769)
                self.assertEqual(owner,'0:0')  # Real BusyBox depth-first retry condition retained.
                cid = start(volume); wait_repaired(volume,32768); stop(cid,'TERM'); cleanup(cid); cid = None
                RECEIPTS.append({'interrupted_signal':signal,'actual_chown_processes_before':active,'files_repaired_before_stop':int(repaired),
                    'top_owner_after_partial':owner,'no_orphan_writes_after_stop':True,'normal_restart_completed_all_recursive_repair':True,
                    'markers_or_permission_policy_changes':False})
            finally:
                if cid: cleanup(cid)
                remove_volume(volume)

    @classmethod
    def tearDownClass(cls):
        if os.environ.get('DGB_PERMISSION_RECEIPT'):
            Path(os.environ['DGB_PERMISSION_RECEIPT']).write_text(json.dumps(RECEIPTS,indent=2)+'\n')


if __name__ == '__main__': unittest.main()
