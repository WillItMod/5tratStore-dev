"""The watchdog update changes only the paired app/Core image references."""
import copy
import hashlib
import json
from pathlib import Path
import unittest
import yaml
from test_dgb_route_release import previous_route_model, record as route_record
ROOT=Path(__file__).resolve().parents[1]
APP='willitmod-dev-dgb'
def digest(value):return hashlib.sha256(json.dumps(value,sort_keys=True,separators=(',',':')).encode()).hexdigest()
def record():return json.loads((ROOT/'DGB-WATCHDOG-2026-10-02.json').read_text())
def previous_watchdog_model(app_id,current):
    if app_id!=APP:return copy.deepcopy(current)
    current=previous_route_model(app_id,current)
    release=record();contract=release['runtimeContract'];restored=copy.deepcopy(current)
    expected={('services','app','image'),('services','dgbd','image'),('services','app','environment','DGB_IMAGE')}
    assert len(contract['changes'])==3 and {tuple(r['path']) for r in contract['changes']}==expected
    assert digest(current)==contract['afterModelSHA256']
    for row in contract['changes']:
        node=restored
        for key in row['path'][:-1]:node=node[key]
        target=release['imageRef'] if row['path']==['services','app','image'] else release['coreImageRef']
        assert node[row['path'][-1]]==row['after']==target
        node[row['path'][-1]]=row['before']
    # Exact accepted 0.9.187 Core update baseline, including shipped UI0.9.186.
    assert contract['beforeModelSHA256']=='d3c261ca3ba174f257119cdc830d3d92bd87650d93ec71fbdeebf23368303199'
    assert digest(restored)==contract['beforeModelSHA256']
    return restored
class WatchdogReleaseTests(unittest.TestCase):
    def test_exact_paired_images_and_unchanged_runtime(self):
        r=record();self.assertEqual(r['channel'],'DEV');self.assertEqual(r['version'],'0.9.188-dev')
        self.assertEqual(r['coreVersion'],'9.26.6');self.assertEqual(r['sourceRevision'],'de7a02cdc07ca43bc23eaa74f80f34535fd3c393')
        self.assertRegex(r['imageRef'],r'^ghcr.io/willitmod/axedgb-app:0\.9\.188-dev@sha256:[a-f0-9]{64}$')
        self.assertRegex(r['coreImageRef'],r'^ghcr.io/willitmod/axedgb-core:9\.26\.6-dev\.2@sha256:[a-f0-9]{64}$')
        current=yaml.safe_load((ROOT/APP/'docker-compose.yml').read_text());previous_watchdog_model(APP,current)
        manifest=yaml.safe_load((ROOT/APP/'umbrel-app.yml').read_text());self.assertEqual(manifest['version'],route_record()['version'])
        for text in ('defaults to Off','Turn off watchdog','9.26.6','24,490,000','23,627,520','Direct and mixed miners'):self.assertIn(text,manifest['releaseNotes'])
    def test_configuration_or_unpaired_changes_are_rejected(self):
        current=yaml.safe_load((ROOT/APP/'docker-compose.yml').read_text())
        for service,key,value in [('app','image','changed'),('init','image','changed'),('dgbd','volumes',[]),('dgbd','stop_grace_period','1s'),('miningcore','image','changed')]:
            changed=copy.deepcopy(current);changed['services'][service][key]=value
            with self.assertRaises(AssertionError):previous_watchdog_model(APP,changed)
        changed=copy.deepcopy(current);changed['services']['app']['environment']['DGB_IMAGE']='changed'
        with self.assertRaises(AssertionError):previous_watchdog_model(APP,changed)
    def test_public_evidence_contains_both_native_configs_without_host_data(self):
        raw=(ROOT/'DGB-WATCHDOG-2026-10-02.json').read_text()
        for private in ('/Users/','/home/forge','10.10.10.','PAYOUT_ADDRESS','APP_PASSWORD'):self.assertNotIn(private,raw)
        r=record()
        for name in ('appImages','coreImages'):
            self.assertEqual(set(r[name]),{'amd64','arm64'})
            for row in r[name].values():
                self.assertEqual(set(row),{'configDigest','manifestDigest'})
                for value in row.values():self.assertRegex(value,r'^sha256:[a-f0-9]{64}$')
if __name__=='__main__':unittest.main()
