"""Reverse only the published node pin and package metadata before old contracts."""
import copy
import hashlib
import json
from pathlib import Path
import subprocess
import unittest

import yaml
from test_bch2_restart_completion_release import previous_bch2_completion_model, package_version as completion_package_version

ROOT=Path(__file__).resolve().parents[1]
APP='willitmod-dev-axebch2'
RECORD=json.loads((ROOT/'BCH2-NODE-ENTRYPOINT-2026-10-14.json').read_text())
BASELINE='ab8b00ca99666ca6eed7df62eb4d6d0d3d6956f02a2dc7ad942cf41faeed50f6'
OLD_NODE='ghcr.io/willitmod/axebch2-node:0.1.33-dev'

def digest(model):return hashlib.sha256(json.dumps(model,sort_keys=True,separators=(',',':')).encode()).hexdigest()

def package_version(app_id,historical):return completion_package_version(app_id,RECORD['packageVersion'] if app_id==APP else historical)

def previous_bch2_node_model(app_id,current):
    current=previous_bch2_completion_model(app_id,current)
    if app_id!=APP:return copy.deepcopy(current)
    assert RECORD['beforeModelSHA256']==BASELINE
    assert digest(current)==RECORD['afterModelSHA256']
    expected={('services','bch2','image'):(OLD_NODE,RECORD['nodeImageRef']),
        ('services','app','environment','BCH2_NODE_IMAGE'):(OLD_NODE,RECORD['nodeImageRef']),
        ('services','app','environment','APP_VERSION'):('0.2.0.12-dev',RECORD['packageVersion'])}
    assert len(RECORD['changes'])==len(expected) and {tuple(row['path']) for row in RECORD['changes']}==set(expected)
    restored=copy.deepcopy(current)
    for row in RECORD['changes']:
        target=restored
        for key in row['path'][:-1]:target=target[key]
        key=row['path'][-1]
        assert (row['before'],row['after'])==expected[tuple(row['path'])] and target[key]==row['after']
        target[key]=row['before']
    assert digest(restored)==BASELINE
    return restored

class Bch2NodeEntrypointReleaseTests(unittest.TestCase):
    def test_only_node_service_helper_and_package_version_change(self):
        current=yaml.safe_load((ROOT/APP/'docker-compose.yml').read_text())
        restored=previous_bch2_node_model(APP,current)
        current=previous_bch2_completion_model(APP,current)
        baseline=yaml.safe_load(subprocess.check_output(['git','show',RECORD['baselineCommit']+':'+APP+'/docker-compose.yml'],cwd=ROOT,text=True))
        self.assertEqual(restored,baseline)
        self.assertEqual(current['services']['app']['image'],RECORD['applicationImageUnchanged'])
        self.assertEqual(current['services']['app']['environment']['APP_REVISION'],RECORD['applicationSourceRevisionUnchanged'])
        self.assertEqual(current['services']['ckpool']['image'],RECORD['poolImageUnchanged'])
        self.assertEqual(current['services']['app']['environment']['CKPOOL_IMAGE'],RECORD['poolImageUnchanged'])

    def test_unrelated_node_pool_config_policy_mount_and_initialization_changes_are_refused(self):
        original=yaml.safe_load((ROOT/APP/'docker-compose.yml').read_text())
        cases=[('bch2','environment',{}),('bch2','volumes',[]),('bch2','stop_grace_period','5s'),
            ('app','image','different-app'),('app','stop_signal','SIGTERM'),('app','ports',['3000:3000']),
            ('ckpool','image','different-pool'),('ckpool','environment',{}),('init_permissions','command',[])]
        for service,key,value in cases:
            changed=copy.deepcopy(original);changed['services'][service][key]=value
            with self.subTest(service=service,key=key),self.assertRaises(AssertionError):previous_bch2_node_model(APP,changed)

    def test_missing_helper_or_node_pin_different_from_helper_is_refused(self):
        original=yaml.safe_load((ROOT/APP/'docker-compose.yml').read_text())
        for key in ['BCH2_NODE_IMAGE','APP_VERSION']:
            changed=copy.deepcopy(original);del changed['services']['app']['environment'][key]
            with self.subTest(key=key),self.assertRaises(AssertionError):previous_bch2_node_model(APP,changed)
        changed=copy.deepcopy(original);changed['services']['bch2']['image']=OLD_NODE
        with self.assertRaises(AssertionError):previous_bch2_node_model(APP,changed)

    def test_manifests_change_only_revision_and_prepended_release_note(self):
        self.assertEqual(RECORD['packageVersion'],'0.2.0.12-dev.1')
        for filename in ['global-app.yml','umbrel-app.yml']:
            current=yaml.safe_load((ROOT/APP/filename).read_text())
            before=yaml.safe_load(subprocess.check_output(['git','show',RECORD['baselineCommit']+':'+APP+'/'+filename],cwd=ROOT,text=True))
            self.assertEqual(current.pop('version'),package_version(APP,RECORD['packageVersion']));self.assertEqual(before.pop('version'),'0.2.0.12-dev')
            notes=current.pop('releaseNotes');old_notes=before.pop('releaseNotes')
            self.assertTrue(notes.endswith('\n'+old_notes));self.assertIn('entrypoint-only node image',notes)
            self.assertIn('Fresh installations using this node image',notes)
            self.assertIn('one-time resync/reindex policy remains active for unmarked legacy chain data',notes)
            self.assertEqual(current,before)

    def test_actual_published_source_and_both_platform_configs_are_immutable(self):
        self.assertEqual(RECORD['channel'],'DEV');self.assertEqual(RECORD['publicationRun'],38642035379)
        self.assertEqual(RECORD['nodeSourceRevision'],'f901ade0581e85770ad774dfb7366cc1347cfb42')
        self.assertEqual(RECORD['entrypointSHA256'],'fa54a53f5c415e836f4b505ec5af4fb78a6b4a277a0a81be0d59124c81216591')
        self.assertEqual(RECORD['testedBaseIndex'],'sha256:031df736b6de4607ab26fdd686d51231f1523a9230a04944d3f922dd88fdbfdc')
        self.assertEqual(RECORD['nodeImageRef'],'ghcr.io/willitmod/axebch2-node:0.1.34-fresh-entrypoint-dev-20261014@sha256:f90cbc4bc844a773b864c6f33300289a362b6ccd48aa014fd738578a608ca697')
        self.assertEqual(set(RECORD['nodeImages']),{'amd64','arm64'})
        for row in RECORD['nodeImages'].values():
            self.assertEqual(set(row),{'manifestDigest','configDigest'})
            for value in row.values():self.assertRegex(value,r'^sha256:[a-f0-9]{64}$')
        self.assertRegex(RECORD['publicationReceiptSHA256'],r'^[a-f0-9]{64}$')
        self.assertEqual(RECORD['nativeRendererProof']['cliSHA256'],'caa747717a3a5ba12dbc231ce79987179b3c37b8ca31d8f588baa1c30c715cfc')
        self.assertEqual(set(RECORD['nativeRendererProof']['generatorSHA256']),{'install','update'})
        self.assertEqual(set(RECORD['nativeRendererProof']['policyHelperSHA256']),{'docker_socket_access.py','app_stop_policy.py'})
        self.assertRegex(RECORD['nativeRendererProof']['receiptSHA256'],r'^[a-f0-9]{64}$')
        self.assertTrue(RECORD['validationScope']['actualInstalledNativeInstallAndUpdateRendererIdentity'])
        for key in ['normalAppManagerUpdateQualified','actualNonAVXAppRestartQualified','miningProtocolQualified']:
            self.assertFalse(RECORD['validationScope'][key])

    def test_other_app_models_and_package_versions_are_untouched(self):
        model={'services':{'app':{'image':'existing-image'}}}
        restored=previous_bch2_node_model('willitmod-dev-btc',model)
        self.assertEqual(restored,model);self.assertIsNot(restored,model)
        self.assertEqual(package_version('willitmod-dev-btc','existing-version'),'existing-version')

    def test_public_record_contains_no_private_host_or_wallet_material(self):
        raw=(ROOT/'BCH2-NODE-ENTRYPOINT-2026-10-14.json').read_text()
        for private in ['/Users/','/home/forge','10.10.10.','APP_PASSWORD','PAYOUT_ADDRESS']:
            self.assertNotIn(private,raw)

if __name__=='__main__':unittest.main()
