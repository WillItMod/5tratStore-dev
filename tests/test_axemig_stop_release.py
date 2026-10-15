"""Bind both MIG roles to one immutable no-force image; preserve every policy."""
import copy
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import unittest

import yaml
from test_powpow_umbrel_grace import previous_grace_workflow

ROOT=Path(__file__).resolve().parents[1]
APP='willitmod-dev-axemig'
RECORD=json.loads((ROOT/'AXEMIG-STOP-SAFETY-2026-10-15.json').read_text())
BASELINE='f1507c19b400d5a305242e495c5f14f4ba6f898a7c4b13590220d3181908d6d5'
OLD='ghcr.io/willitmod/axemig:0.1.23-dev@sha256:7d9b602b35a02e475055cd1a87d74de7dfc1c83f5af01bd909841d4943a098c0'
IMAGE='ghcr.io/willitmod/axemig:0.1.24-dev@sha256:e20d2d002567980e24000263464576d06a7afd0f35f477b7d77374f4ee2774f3'
WORKFLOW_FILTERS=('AXEMIG-STOP-SAFETY-2026-10-15.json','tests/test_axemig_stop_release.py',
                  'tests/test_axemig_chain_release.py','tests/test_axemig_usb_release.py')


def digest(model):
    return hashlib.sha256(json.dumps(model,sort_keys=True,separators=(',',':')).encode()).hexdigest()


def previous_mig_stop_model(app_id,current):
    if app_id!=APP:return copy.deepcopy(current)
    assert RECORD['beforeModelSHA256']==BASELINE
    assert digest(current)==RECORD['afterModelSHA256']
    expected={('services','server','image'):(OLD,IMAGE),
              ('services','server','environment','AXEMIG_HELPER_IMAGE'):(OLD,IMAGE),
              ('services','server','environment','APP_VERSION'):('0.1.23-dev','0.1.24-dev')}
    assert len(RECORD['changes'])==3
    assert {tuple(row['path'])for row in RECORD['changes']}==set(expected)
    old=copy.deepcopy(current)
    for row in RECORD['changes']:
        path=tuple(row['path']);assert(row['before'],row['after'])==expected[path]
        node=old
        for key in path[:-1]:node=node[key]
        assert node[path[-1]]==row['after'];node[path[-1]]=row['before']
    assert digest(old)==BASELINE
    return old


def previous_mig_stop_manifest(current):
    assert digest(current)==RECORD['afterManifestSHA256']
    old=copy.deepcopy(current)
    assert old['version']=='0.1.24-dev';old['version']='0.1.23-dev'
    prefix=RECORD['releaseNotesPrefix']+'\n'
    assert old['releaseNotes'].startswith(prefix)
    old['releaseNotes']=old['releaseNotes'][len(prefix):]
    assert digest(old)==RECORD['beforeManifestSHA256']
    return old


def previous_mig_stop_workflow(current):
    assert hashlib.sha256(current.encode()).hexdigest()==RECORD['afterWorkflowSHA256']
    for value in WORKFLOW_FILTERS:
        line='      - "'+value+'"\n'
        assert current.count(line)==2
        current=current.replace(line,'')
    assert hashlib.sha256(current.encode()).hexdigest()==RECORD['beforeWorkflowSHA256']
    return current


def baseline(name):
    return yaml.safe_load(subprocess.check_output(['git','show',RECORD['baselineCommit']+':'+APP+'/'+name],cwd=ROOT,text=True))


class AxemigStopReleaseTests(unittest.TestCase):
    def test_workflow_only_adds_exact_four_paths_to_both_filters(self):
        name='.github/workflows/validate-mux-app-packages.yml'
        current=previous_grace_workflow((ROOT/name).read_text())
        expected=subprocess.check_output(['git','show',RECORD['baselineCommit']+':'+name],cwd=ROOT,text=True)
        self.assertEqual(previous_mig_stop_workflow(current),expected)
        for altered in [current.replace('tests/test_axemig_stop_release.py','unreviewed.py',1),
                        current+'# unrelated change\n']:
            with self.assertRaises(AssertionError):previous_mig_stop_workflow(altered)

    def test_exact_three_fields_reverse_to_entire_previous_runtime_model(self):
        current=yaml.safe_load((ROOT/APP/'docker-compose.yml').read_text())
        self.assertEqual(previous_mig_stop_model(APP,current),baseline('docker-compose.yml'))
        server=current['services']['server']
        self.assertEqual(server['image'],IMAGE)
        self.assertEqual(server['environment']['AXEMIG_HELPER_IMAGE'],IMAGE)
        self.assertEqual(server['environment']['APP_VERSION'],'0.1.24-dev')
        self.assertEqual(server['volumes'],baseline('docker-compose.yml')['services']['server']['volumes'])

    def test_image_version_route_volume_permissions_and_policy_drift_refuses(self):
        model=yaml.safe_load((ROOT/APP/'docker-compose.yml').read_text())
        paths=[(['services','server','image'],'unreviewed:latest'),
               (['services','server','environment','AXEMIG_HELPER_IMAGE'],OLD),
               (['services','server','environment','APP_VERSION'],'0.1.23-dev'),
               (['services','server','environment','AXEMIG_HOME'],'/other'),
               (['services','server','volumes'],[]),(['services','server','stop_grace_period'],'10s'),
               (['services','server','user'],'1000:1000'),(['services','server','restart'],'always'),
               (['services','app_proxy','environment','APP_HOST'],'another-app')]
        for path,value in paths:
            candidate=copy.deepcopy(model);node=candidate
            for key in path[:-1]:node=node[key]
            node[path[-1]]=value
            with self.subTest(path=path),self.assertRaises(AssertionError):previous_mig_stop_model(APP,candidate)
        candidate=copy.deepcopy(model);candidate['networks']={'default':{}}
        with self.assertRaises(AssertionError):previous_mig_stop_model(APP,candidate)

    def test_manifest_only_advances_version_and_prepends_reviewed_note(self):
        current=yaml.safe_load((ROOT/APP/'umbrel-app.yml').read_text())
        self.assertEqual(previous_mig_stop_manifest(current),baseline('umbrel-app.yml'))
        self.assertEqual(current['version'],RECORD['packageVersion'])
        self.assertIn('verified graceful node shutdown',current['releaseNotes'])

    def test_published_native_and_anonymous_source_bindings_are_exact(self):
        self.assertEqual(RECORD['image'],IMAGE)
        self.assertEqual(RECORD['source'],'d61eb84aeca85a54635a5a20167882b8b41ef98f')
        self.assertEqual(RECORD['sourceTree'],'001caf2b8ff77b41469f9eccf79d033dcc7c5d53')
        self.assertEqual(RECORD['sourceMainMerge'],'9970b8c24dd240351d7bf67e92a36bd2d3249284')
        self.assertEqual(RECORD['workflow'],38660025499)
        self.assertEqual(RECORD['appSHA256'],'c035ac754ed9154450887caa97cd77728e005bb81b53a2e3125ab934175eab87')
        self.assertTrue(RECORD['anonymousAccess'])
        self.assertEqual({a:p['configDigest']for a,p in RECORD['platforms'].items()},
                         {'amd64':'sha256:a7e986be5eb39dd25ba47ab9f27c42b13356a60cb8848e4c9b8fd0d1dda20794',
                          'arm64':'sha256:8c6cae0ac76d4e57dfef4607fd09ff35142d694521188a6c4e97d23e897a37b7'})
        scope=RECORD['validationScope']
        self.assertEqual((scope['hostSourceTests'],scope['bakedRuntimeTestsPerArch'],scope['realOfflineCorePrimitiveCasesPerArch']),(53,52,3))
        self.assertTrue(scope['baseDiffIDsAndRuntimeConfigPreserved'])
        self.assertFalse(scope['fullAppQualified'])
        self.assertFalse(scope['allThreeOsNormalUpdateQualified'])
        self.assertFalse(scope['new48FunctionalChecksPerPlatformQualified'])
        self.assertFalse(scope['cryptographicSignerVerified'])

    def test_every_other_package_file_and_historical_contract_remains_unchanged(self):
        names=subprocess.check_output(['git','ls-tree','-r','--name-only',RECORD['baselineCommit'],'--',APP],cwd=ROOT,text=True).splitlines()
        for name in names:
            if Path(name).name in {'docker-compose.yml','umbrel-app.yml'}:continue
            self.assertEqual((ROOT/name).read_bytes(),subprocess.check_output(['git','show',RECORD['baselineCommit']+':'+name],cwd=ROOT))
        other={'services':{'app':{'image':'other-app'}}}
        self.assertEqual(previous_mig_stop_model('other-app',other),other)

    def test_umbrel174_normal_parser_keeps_both_immutable_roles(self):
        model=yaml.safe_load((ROOT/APP/'docker-compose.yml').read_text())
        fixture=ROOT/'tests/fixtures/umbrel_1_7_4_patch_compose.cjs'
        for _ in range(2):
            run=subprocess.run(['node',str(fixture)],input=json.dumps({'compose':model,'id':APP}),capture_output=True,text=True,check=True)
            model=json.loads(run.stdout)
        self.assertEqual(model['services']['server']['image'],IMAGE)
        self.assertEqual(model['services']['server']['environment']['AXEMIG_HELPER_IMAGE'],IMAGE)
        self.assertEqual(model['services']['server']['environment']['APP_VERSION'],'0.1.24-dev')

    def test_actual_installed_native_install_and_update_renderers_preserve_delta(self):
        path=os.environ.get('MIG_NATIVE_CLI')
        helper=os.environ.get('MIG_NATIVE_SOCKET_HELPER')
        if not path or not helper:
            self.skipTest('requires captured installed native CLI/helper; exact local renderer proof recorded separately')
        cli=Path(path);helper=Path(helper);proof=RECORD['nativeRenderer']
        self.assertEqual(hashlib.sha256(cli.read_bytes()).hexdigest(),proof['cliSHA256'])
        self.assertEqual(hashlib.sha256(helper.read_bytes()).hexdigest(),proof['socketAccessHelperSHA256'])
        blocks=[m.group(1)for m in re.finditer(r"python3 - <<'PY'[^\n]*\n(.*?)\nPY",cli.read_text(),re.S)
                if 'def find_ui_service'in m.group(1)and'services.pop("app_proxy", None)'in m.group(1)]
        self.assertEqual(len(blocks),2)
        current=yaml.safe_load((ROOT/APP/'docker-compose.yml').read_text())
        previous=previous_mig_stop_model(APP,current)
        receipts=[]
        for stage,body,row in zip(['install','update'],blocks,proof['rendererBlocks']):
            self.assertEqual(hashlib.sha256(body.encode()).hexdigest(),row['sha256'])
            with tempfile.TemporaryDirectory(prefix='mig-native-render-') as directory:
                models=[]
                for label,model in [('previous',previous),('current',current)]:
                    root=Path(directory)/label;source=root/'store'/APP;dest=root/'app';source.mkdir(parents=True);dest.mkdir()
                    (source/'docker-compose.yml').write_text(yaml.safe_dump(model,sort_keys=False))
                    env=dict(os.environ,STORE_CHANNEL='dev',STORE_ROOT=str(source.parent),STORE_DIR=APP,
                             STORE_PORT='12150',DEST=str(dest),APP_ID='axemig',OUT_FILE='docker-compose.yml.next',
                             SOCKET_ACCESS_CHECKER=str(helper),STOP_POLICY_CHECKER='/not-used-by-this-recipe')
                    subprocess.run([sys.executable,'-'],input=body,text=True,capture_output=True,env=env,check=True)
                    result=yaml.safe_load((dest/('docker-compose.yml'if stage=='install'else'docker-compose.yml.next')).read_text())
                    self.assertNotIn('app_proxy',result['services']);self.assertNotIn('version',result)
                    self.assertEqual(result['services']['server']['restart'],'unless-stopped')
                    self.assertIn('127.0.0.1:12150:12150',result['services']['server']['ports'])
                    models.append(result)
                restored=copy.deepcopy(models[1])
                for change in RECORD['changes']:
                    node=restored
                    for key in change['path'][:-1]:node=node[key]
                    self.assertEqual(node[change['path'][-1]],change['after']);node[change['path'][-1]]=change['before']
                self.assertEqual(restored,models[0])
                receipts.append({'stage':stage,'rendererSHA256':row['sha256'],
                                 'previousModelSHA256':digest(models[0]),'currentModelSHA256':digest(models[1]),
                                 'exactThreeFieldsOnly':True,'ports':models[1]['services']['server']['ports'],
                                 'serverImage':models[1]['services']['server']['image'],
                                 'helperImage':models[1]['services']['server']['environment']['AXEMIG_HELPER_IMAGE']})
        out=os.environ.get('MIG_NATIVE_RENDER_RECEIPT')
        if out:
            target=Path(out);self.assertFalse(target.exists())
            target.write_text(json.dumps({'cliSHA256':proof['cliSHA256'],
                                         'socketAccessHelperSHA256':proof['socketAccessHelperSHA256'],
                                         'actualInstalledConverterBlocks':receipts,'guestMutation':False},indent=2)+'\n')


if __name__=='__main__':unittest.main()
