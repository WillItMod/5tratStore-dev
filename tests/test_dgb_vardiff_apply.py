"""Bind the initializer delta and exercise its real jq/BusyBox JSON transforms."""
import base64
import copy
import hashlib
import json
import os
from pathlib import Path
import subprocess
import unittest
import uuid

import yaml

ROOT = Path(__file__).resolve().parents[1]
APP = 'willitmod-dev-dgb'
RECORD = json.loads((ROOT / 'DGB-VARDIFF-APPLY-2026-10-14.json').read_text())
OWNER = 'codex-dgb-vardiff-json-20261014'
RECEIPTS = []


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def previous_vardiff_model(app_id, current):
    if app_id != APP:
        return copy.deepcopy(current)
    assert digest(current) == RECORD['afterModelSHA256']
    restored = copy.deepcopy(current)
    command = restored['services']['init']['command']
    assert hashlib.sha256(command[2].encode()).hexdigest() == RECORD['afterCommandSHA256']
    for change in reversed(RECORD['commandReplacements']):
        assert command[2].count(change['after']) == change['count']
        command[2] = command[2].replace(change['after'], change['before'])
    assert hashlib.sha256(command[2].encode()).hexdigest() == RECORD['beforeCommandSHA256']
    assert digest(restored) == RECORD['beforeModelSHA256']
    return restored


def package_version(app_id, historical):
    if app_id != APP:
        return historical
    assert historical == RECORD['beforePackageVersion']
    return RECORD['packageVersion']


def current_model():
    return yaml.safe_load((ROOT / APP / 'docker-compose.yml').read_text())


def apply_section(command, phase):
    """Execute shipped read/validation/jq bytes, without unrelated init/SQL work."""
    command = command.replace('$$', '$')
    if phase == 'normal':
        start = command.index('settings="/data/ui/state/pool_settings.json"')
        end = command.index('\n    # Safety:', start)
    else:
        assert phase == 'post-repair'
        anchor = command.index('# After any regeneration/normalization, always attempt')
        start = command.index('  settings="/data/ui/state/pool_settings.json"', anchor)
        end = command.index('\n  # Safety:', start)
    return command[start:end]


class VarDiffSourceContract(unittest.TestCase):
    def test_exact_initializer_only_delta_and_package_revision(self):
        model = current_model()
        restored = previous_vardiff_model(APP, model)
        expected = copy.deepcopy(model)
        expected['services']['init']['command'] = restored['services']['init']['command']
        self.assertEqual(expected, restored)
        self.assertEqual(RECORD['runtimeFieldChanged'], ['services', 'init', 'command', 2])
        self.assertEqual({k:v['image'] for k,v in model['services'].items() if 'image' in v}, RECORD['imagesUnchanged'])
        self.assertEqual(model['services']['app']['environment'].get('APP_VERSION'), RECORD['applicationVersionFieldUnchanged'])
        manifest = yaml.safe_load((ROOT / APP / 'umbrel-app.yml').read_text())
        self.assertEqual(manifest['version'], RECORD['packageVersion'])
        self.assertTrue(manifest['releaseNotes'].startswith(RECORD['releaseNotesPrefix']))
        manifest['version'] = RECORD['beforePackageVersion']
        manifest['releaseNotes'] = manifest['releaseNotes'].removeprefix(RECORD['releaseNotesPrefix'])
        self.assertEqual(digest(manifest), RECORD['beforeManifestSHA256'])
        for phase in ('normal', 'post-repair'):
            subprocess.run(['sh', '-n'], input=apply_section(model['services']['init']['command'][2], phase), text=True, check=True)
        self.assertEqual(len(RECORD['commandReplacements']), 4)

    def test_other_image_scrypt_default_port_and_command_changes_are_rejected(self):
        for kind in ('image', 'scrypt-default', 'port', 'watchdog', 'sql'):
            model = current_model()
            if kind == 'image': model['services']['init']['image'] = 'unreviewed:latest'
            elif kind == 'scrypt-default': model['services']['init']['environment']['SCRYPT_STARTDIFF'] = '4096'
            elif kind == 'port': model['services']['miningcore']['ports'][0] = '1:2'
            elif kind == 'watchdog': model['services']['perm_watchdog']['command'][2] += '\necho changed\n'
            else: model['services']['init']['command'][2] = model['services']['init']['command'][2].replace('CREATE TABLE shares', 'CREATE TABLE changed', 1)
            with self.subTest(kind=kind), self.assertRaises(AssertionError):
                previous_vardiff_model(APP, model)


def run(argv):
    return subprocess.check_output(argv, text=True, stderr=subprocess.PIPE, timeout=30).strip()


def fixture_config():
    def pool(pool_id, port, diff, minimum, maximum):
        return {'id':pool_id, 'enabled':True, 'address':'previous-owned-fixture-address',
            'coin':'digibyte-sha256' if pool_id == 'dgb-sha256-1' else 'digibyte-scrypt',
            'ports':{port:{'listenAddress':'0.0.0.0', 'difficulty':diff,
                'varDiff':{'minDiff':minimum, 'maxDiff':maximum, 'targetTime':17, 'retargetTime':91, 'variancePercent':31},
                'tcpProxyProtocol':False}},
            'daemons':[{'host':'offline-fixture', 'port':14022, 'user':'public-test-user', 'password':'public-test-password'}],
            'paymentProcessing':{'enabled':False}, 'untouched':['nested', {'sentinel':42}]}
    result = {'api':{'enabled':True}, 'persistence':{'postgres':{'host':'offline-fixture','password':'public-json-sentinel'}},
        'pools':[pool('dgb-sha256-1','3333',99,88,777), pool('dgb-scrypt-1','3334',1.5,.25,128.5),
                 pool('unrelated-pool','9999',3,2,4)], 'unrelated':{'sentinel':['unchanged',42]}}
    result['pools'][0]['ports']['3335'] = copy.deepcopy(result['pools'][0]['ports']['3333'])
    result['pools'][1]['ports']['3336'] = copy.deepcopy(result['pools'][1]['ports']['3334'])
    return result


def docker_case(volume, phase, values, expected_values, baseline=False):
    config = fixture_config()
    settings = {'payoutAddress':'D' + '1' * 33, **dict(zip(('mindiff','startdiff','maxdiff'), values))}
    model = previous_vardiff_model(APP, current_model()) if baseline else current_model()
    command = apply_section(model['services']['init']['command'][2], phase)
    setup = 'set -eu\nmkdir -p /data/pool/config /data/ui/state\n'
    for filename, value in [('pool/config/miningcore.json',config), ('ui/state/pool_settings.json',settings)]:
        encoded = base64.b64encode(json.dumps(value, separators=(',', ':')).encode()).decode()
        setup += "printf '%s' '" + encoded + "' | base64 -d > /data/" + filename + '\n'
    setup += "printf 'owned JSON fixture sentinel\\n' > /data/.sentinel; chmod 640 /data/.sentinel\n"
    setup += 'before_settings="$(sha256sum /data/ui/state/pool_settings.json)"\n'
    setup += 'miningcore_conf=/data/pool/config/miningcore.json\napplied_settings=0\n' + command
    setup += '\n[ "$before_settings" = "$(sha256sum /data/ui/state/pool_settings.json)" ]\n'
    setup += "[ \"$(cat /data/.sentinel)\" = 'owned JSON fixture sentinel' ]; [ \"$(stat -c '%a' /data/.sentinel)\" = 640 ]\n"
    setup += "printf '__RESULT__'; jq -c . /data/pool/config/miningcore.json; printf '__JQ__'; jq --version\n"
    output = run(['docker','run','--rm','--label','dev.compat.owner='+OWNER,'--network','none','--read-only',
        '--cap-drop','ALL','--security-opt','no-new-privileges:true','--memory','128m','--cpus','1','--pids-limit','64',
        '--mount','type=volume,src='+volume+',dst=/data','--entrypoint','/bin/sh',RECORD['fixtureImage'],'-ec',setup])
    result = json.loads(next(line.removeprefix('__RESULT__') for line in output.splitlines() if line.startswith('__RESULT__')))
    expected = copy.deepcopy(config)
    for pool in expected['pools'][:2]:
        pool['address'] = settings['payoutAddress']
    for pool in expected['pools'][:2] if baseline else expected['pools'][:1]:
        for port in pool['ports'].values():
            minimum, start, maximum = expected_values
            if minimum > 0: port['varDiff']['minDiff'] = minimum
            if start > 0: port['difficulty'] = start
            port['varDiff']['maxDiff'] = maximum if maximum > 0 else None
    assert result == expected, 'Only payout and intended SHA256 varDiff semantic fields may change'
    # This whole-model equality also checks all daemon/DB credential sentinels,
    # unrelated pools and every Scrypt port, not only selected numeric values.
    protected = lambda value: {'db':value['persistence'], 'daemons':[p['daemons'] for p in value['pools']]}
    assert digest(protected(result)) == digest(protected(config))
    if not baseline: assert result['pools'][1]['ports'] == config['pools'][1]['ports']
    RECEIPTS.append({'phase':phase, 'baseline':baseline, 'inputNumbers':values,
        'expectedSha256Numbers':expected_values, 'wholeConfigMatchesExpectedDelta':True,
        'scryptPortsUnchanged':not baseline, 'rpcAndDbSentinelSHA256Unchanged':True,
        'settingsBytesAndSentinelModeUnchanged':True, 'jqVersion':next(x.removeprefix('__JQ__') for x in output.splitlines() if x.startswith('__JQ__'))})


@unittest.skipUnless(os.environ.get('DGB_VARDIFF_DOCKER') == '1', 'opt-in actual jq/BusyBox JSON-only fixtures')
class ActualVarDiffApply(unittest.TestCase):
    def test_both_shipped_passes_accept_floats_ints_zero_and_preserve_scrypt(self):
        volume = OWNER + '-' + uuid.uuid4().hex[:12]
        self.assertNotEqual(subprocess.run(['docker','volume','inspect',volume],capture_output=True).returncode,0)
        self.assertEqual(run(['docker','volume','create','--label','dev.compat.owner='+OWNER,volume]),volume)
        try:
            cases = [((1024.0,4096.0,131072.0),(1024,4096,131072)),
                ((1.25,2.5,128.75),(1.25,2.5,128.75)), ((2048,8192,262144),(2048,8192,262144)),
                ((1024.0,4096.0,0.0),(1024,4096,0)),
                (('NaN','4096x','1e5'),(0,0,0)), ((-1,-2,-3),(0,0,0)),
                ((True,False,None),(0,0,0)), (('2048.0','8192.0','262144.0'),(2048,8192,262144))]
            for phase in ('normal','post-repair'):
                docker_case(volume,phase,(1024.0,4096.0,131072.0),(0,0,0),baseline=True)
                docker_case(volume,phase,(2048,8192,262144),(2048,8192,262144),baseline=True)
                for values, expected in cases:
                    with self.subTest(phase=phase,values=values): docker_case(volume,phase,values,expected)
        finally:
            info=json.loads(run(['docker','volume','inspect',volume]))[0]
            self.assertEqual(info['Labels']['dev.compat.owner'],OWNER)
            run(['docker','volume','rm',volume])
            if os.environ.get('DGB_VARDIFF_RECEIPT'):
                image=json.loads(run(['docker','image','inspect',RECORD['fixtureImage']]))[0]
                for row in RECEIPTS:
                    row.update({'fixtureImage':RECORD['fixtureImage'],'fixtureLocalImageId':image['Id'],
                        'fixturePlatformConfig':RECORD['fixturePlatforms'][image['Architecture']]['configDigest'],
                        'architecture':image['Architecture']})
                Path(os.environ['DGB_VARDIFF_RECEIPT']).write_text(json.dumps(RECEIPTS,indent=2)+'\n')


if __name__ == '__main__':
    unittest.main()
