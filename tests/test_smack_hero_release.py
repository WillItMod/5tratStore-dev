"""Undo only the two reviewed APP references before frozen historical guards."""
import copy,hashlib,json,re,unittest
import importlib.util
from pathlib import Path
import yaml
ROOT=Path(__file__).resolve().parents[1];APP='willitmod-dev-5tratsmack'
SPEC=importlib.util.spec_from_file_location('smack_store_release',ROOT/'scripts/smack_store_release.py')
STORE=importlib.util.module_from_spec(SPEC);SPEC.loader.exec_module(STORE)
package_version=STORE.package_version
store_record=STORE.record
REF='ghcr.io/willitmod/5tratsmack-app:0.11.22-hero.6fc6597c3aba@sha256:304566aaf4374398d10e53612f1b1ccce89344e6fcf4a51293006d9c8f2111e9'
OLD='ghcr.io/willitmod/5tratsmack-app:0.11.21@sha256:09f3dc1eea85942781e4127b6d8836c32c7fa61a0a45cbffb99b40509c38e3bb'
def digest(v):return hashlib.sha256(json.dumps(v,sort_keys=True,separators=(',',':')).encode()).hexdigest()
def record():return json.loads((ROOT/'SMACK-HERO-2026-10-15.json').read_text())
def previous_hero_model(app_id,current):
    current=STORE.previous_store_model(app_id,current)
    restored=copy.deepcopy(current)
    if app_id!=APP:return restored
    r=record();c=r['runtimeContract'];assert digest(current)==c['afterModelSHA256']
    assert r['imageRef']==REF and {tuple(x['path']) for x in c['changes']}=={('services','app','image'),('services','app','environment','APP_IMAGE')} and len(c['changes'])==2
    for row in c['changes']:
        node=restored
        for k in row['path'][:-1]:node=node[k]
        k=row['path'][-1];assert node[k]==row['after']==REF and row['before']==OLD;node[k]=OLD
    assert digest(restored)==c['beforeModelSHA256']
    return restored
class SmackHeroTests(unittest.TestCase):
    def test_only_two_APP_references_change_in_the_complete_parsed_model(self):
        r=record();current=yaml.safe_load((ROOT/APP/'docker-compose.yml').read_text());old=previous_hero_model(APP,current)
        self.assertEqual(old['services']['app']['environment']['APP_VERSION'],'0.11.21');self.assertEqual(old['services']['app']['environment']['APP_REVISION'],'f41e154a74afbd54f67545d0b95d18506a336fa1')
    def test_unrelated_runtime_or_backend_identity_changes_fail_closed(self):
        m=yaml.safe_load((ROOT/APP/'docker-compose.yml').read_text())
        for service,key,value in [('node-a','image','changed'),('ckpool','image','changed'),('swap','image','changed'),('app','volumes',[]),('app','healthcheck',{}),('init_permissions','command',[])]:
            v=copy.deepcopy(m);v['services'][service][key]=value
            with self.assertRaises(AssertionError):previous_hero_model(APP,v)
        for key in ['APP_VERSION','APP_REVISION','FIVETRAT_RELEASE_TAG']:
            v=copy.deepcopy(m);v['services']['app']['environment'][key]='changed'
            with self.assertRaises(AssertionError):previous_hero_model(APP,v)
    def test_published_source_and_both_actual_native_configs_are_exact(self):
        r=record();self.assertEqual((r['version'],r['runtimeVersion']),('0.11.22-dev','0.11.21'));self.assertEqual(r['sourceRevision'],'6fc6597c3abaef0194a4d4bffbcd7b49e54e8758');self.assertEqual(r['imageRef'],REF);self.assertEqual(r['workflowRun'],38665179620)
        self.assertEqual(r['images']['amd64']['configDigest'],'sha256:9e2f8be750593b8bf7cd542a5457f03460260c740e693c72f16f8b39cb365781');self.assertEqual(r['images']['arm64']['configDigest'],'sha256:bb774a67011c696c2e55346f84191c89e1d14e5e2c23e48c74ebac10ddd3f921')
    def test_manifests_forward_package_and_preserve_every_previous_note(self):
        r=record();self.assertEqual((ROOT/APP/'umbrel-app.yml').read_bytes(),(ROOT/APP/'5tratstore-app.yml').read_bytes());m=yaml.safe_load((ROOT/APP/'umbrel-app.yml').read_text());self.assertEqual(m['version'],package_version(APP,r['version']));notes=m['releaseNotes'];self.assertIn('unchanged backend continues to report 0.11.21',notes)
        old=notes[-r['previousNotes']['characters']:];self.assertEqual(hashlib.sha256(old.encode()).hexdigest(),r['previousNotes']['sha256'])
    def test_one_HTML_overlay_and_no_other_component_or_attestation_claim(self):
        r=record();self.assertEqual(r['HTML']['afterSHA256'],'a8f11c10dfb56b70df8e17a9f331237e07072955aed14fd1009794e67231eab9');self.assertEqual(r['baseIndex'],'sha256:09f3dc1eea85942781e4127b6d8836c32c7fa61a0a45cbffb99b40509c38e3bb');self.assertIn('Not generated',r['validation']['OCIProvenanceOrSBOMAttestation'])
        text=(ROOT/'SMACK-HERO-2026-10-15.json').read_text()
        for private in ['/Users/','10.10.10.','PAYOUT_ADDRESS','APP_PASSWORD']:self.assertNotIn(private,text)
if __name__=='__main__':unittest.main()
