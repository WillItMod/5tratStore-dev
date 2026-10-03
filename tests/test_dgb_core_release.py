"""The current Core release changes exactly two recipe references."""
import copy
import hashlib
import json
from pathlib import Path
import unittest
import yaml
from test_dgb_watchdog_release import previous_watchdog_model, record as watchdog_record, route_record
ROOT=Path(__file__).resolve().parents[1]
APP='willitmod-dev-dgb'
def digest(value):return hashlib.sha256(json.dumps(value,sort_keys=True,separators=(',',':')).encode()).hexdigest()
def record():return json.loads((ROOT/'DGB-CORE-2026-10-02.json').read_text())
def previous_dgb_model(app_id,current):
    if app_id!=APP:return copy.deepcopy(current)
    current=previous_watchdog_model(app_id,current)
    release=record();contract=release['runtimeContract'];restored=copy.deepcopy(current)
    expected={('services','dgbd','image'),('services','app','environment','DGB_IMAGE')}
    assert len(contract['changes'])==2 and {tuple(r['path']) for r in contract['changes']}==expected
    assert digest(current)==contract['afterModelSHA256']
    for row in contract['changes']:
        node=restored
        for key in row['path'][:-1]:node=node[key]
        assert node[row['path'][-1]]==row['after']==release['coreImageRef']
        assert row['before']=='ghcr.io/willitmod/axedgb-core:0.9.181-dev'
        node[row['path'][-1]]=row['before']
    assert contract['beforeModelSHA256']=='e682e8e9f0f19fc8b4027ca18b5b35910aa624b568e7dfd6b4aebfb97b1a2b23'
    assert digest(restored)==contract['beforeModelSHA256']
    return restored
class DigiByteCoreReleaseTests(unittest.TestCase):
    def test_current_core_and_exact_prior_runtime(self):
        r=record();self.assertEqual(r['channel'],'DEV');self.assertEqual(r['version'],'0.9.187-dev')
        self.assertEqual(r['coreVersion'],'9.26.6');self.assertEqual(r['upstreamRevision'],'92330d952625e20aef2ee40671a179ef03872ac1')
        self.assertRegex(r['coreImageRef'],r'^ghcr.io/willitmod/axedgb-core:9\.26\.6-dev\.1@sha256:[a-f0-9]{64}$')
        current=yaml.safe_load((ROOT/APP/'docker-compose.yml').read_text());previous_dgb_model(APP,current)
        manifest=yaml.safe_load((ROOT/APP/'umbrel-app.yml').read_text());self.assertEqual(manifest['version'],route_record()['version'])
        for value in ('9.26.6','24,490,000','23,627,520','Direct and mixed miners'):self.assertIn(value,manifest['releaseNotes'])
        old=json.loads((ROOT/'DIRECT-HASHRATE-2026-09-30.json').read_text())['apps'][APP]
        self.assertEqual(previous_watchdog_model(APP,current)['services']['app']['image'],old['imageRef'])
    def test_unrelated_runtime_and_configuration_changes_fail(self):
        current=yaml.safe_load((ROOT/APP/'docker-compose.yml').read_text())
        for service,key,value in [('app','image','changed'),('init','image','changed'),('dgbd','volumes',[]),('dgbd','stop_grace_period','1s'),('miningcore','image','changed')]:
            changed=copy.deepcopy(current);changed['services'][service][key]=value
            with self.assertRaises(AssertionError):previous_dgb_model(APP,changed)
    def test_public_record_contains_no_host_evidence(self):
        raw=(ROOT/'DGB-CORE-2026-10-02.json').read_text()
        for private in ('/Users/','/home/forge','10.10.10.','PAYOUT_ADDRESS','APP_PASSWORD'):self.assertNotIn(private,raw)
        r=record();self.assertEqual(set(r['images']),{'amd64','arm64'})
        for row in r['images'].values():
            self.assertEqual(set(row),{'configDigest','manifestDigest'})
            for value in row.values():self.assertRegex(value,r'^sha256:[a-f0-9]{64}$')
if __name__=='__main__':unittest.main()
