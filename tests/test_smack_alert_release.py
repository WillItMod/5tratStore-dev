"""The rich-alert release changes only Smack's app image and release metadata."""
import copy
import hashlib
import json
from pathlib import Path
import unittest
import yaml
ROOT=Path(__file__).resolve().parents[1]
APP='willitmod-dev-5tratsmack'
BASELINE='7970c78f53291907c95151dcc024e47eda0709d91d3ff6bfc899bde97f00ea2c'
def digest(value):return hashlib.sha256(json.dumps(value,sort_keys=True,separators=(',',':')).encode()).hexdigest()
def record():return json.loads((ROOT/'SMACK-ALERTS-2026-10-02.json').read_text())
def previous_alert_model(app_id,current):
    if app_id!=APP:return copy.deepcopy(current)
    release=record();contract=release['runtimeContract'];restored=copy.deepcopy(current)
    expected={('services','app','image')}
    expected.update(('services','app','environment',key) for key in ('APP_VERSION','APP_REVISION','APP_IMAGE','FIVETRAT_RELEASE_TAG'))
    assert len(contract['changes'])==5 and {tuple(r['path']) for r in contract['changes']}==expected
    assert digest(current)==contract['afterModelSHA256']
    values={'image':release['imageRef'],'APP_IMAGE':release['imageRef'],'APP_VERSION':release['version'],
            'FIVETRAT_RELEASE_TAG':release['version'],'APP_REVISION':release['sourceRevision']}
    for row in contract['changes']:
        node=restored
        for key in row['path'][:-1]:node=node[key]
        key=row['path'][-1];assert node[key]==row['after']==values[key]
        node[key]=row['before']
    assert contract['beforeModelSHA256']==BASELINE and digest(restored)==BASELINE
    return restored
class SmackAlertReleaseTests(unittest.TestCase):
    def test_exact_app_only_update_and_preserved_release_notes(self):
        r=record();self.assertEqual(r['channel'],'DEV');self.assertEqual(r['version'],'0.11.21')
        self.assertEqual(r['sourceRevision'],'f41e154a74afbd54f67545d0b95d18506a336fa1')
        self.assertEqual(r['baselineCommit'],'15ad08a65e4f85c2d558c4dce096b14a446ecd18')
        self.assertRegex(r['imageRef'],r'^ghcr.io/willitmod/5tratsmack-app:0\.11\.21@sha256:[a-f0-9]{64}$')
        previous_alert_model(APP,yaml.safe_load((ROOT/APP/'docker-compose.yml').read_text()))
        for filename in ('umbrel-app.yml','5tratstore-app.yml'):
            manifest=yaml.safe_load((ROOT/APP/filename).read_text());self.assertEqual(manifest['version'],r['version'])
            for text in ('detailed block-found celebration','fresh active-chain','hardware telemetry separately','Complete block and pool accounting records','OS and MUX notification acknowledgements remain separate'):self.assertIn(text,manifest['releaseNotes'])
    def test_unrelated_runtime_or_proof_metadata_changes_rejected(self):
        current=yaml.safe_load((ROOT/APP/'docker-compose.yml').read_text())
        for service,key,value in [('node-a','image','changed'),('ckpool','image','changed'),('swap','image','changed'),('app','volumes',[]),('app','healthcheck',{}),('init_permissions','command',[])]:
            changed=copy.deepcopy(current);changed['services'][service][key]=value
            with self.assertRaises(AssertionError):previous_alert_model(APP,changed)
        changed=copy.deepcopy(current);changed['services']['app']['environment']['APP_REVISION']='0'*40
        with self.assertRaises(AssertionError):previous_alert_model(APP,changed)
    def test_public_native_provenance_has_no_private_configuration(self):
        text=(ROOT/'SMACK-ALERTS-2026-10-02.json').read_text()
        for private in ('/Users/','/home/forge','10.10.10.','PAYOUT_ADDRESS','APP_PASSWORD'):self.assertNotIn(private,text)
        r=record();self.assertEqual(set(r['images']),{'amd64','arm64'})
        for row in r['images'].values():
            self.assertEqual(set(row),{'configDigest','manifestDigest'})
            for value in row.values():self.assertRegex(value,r'^sha256:[a-f0-9]{64}$')
if __name__=='__main__':unittest.main()
