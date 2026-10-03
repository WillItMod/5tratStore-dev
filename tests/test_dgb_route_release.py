"""The route-status release replaces only the application image."""
import copy,hashlib,json,unittest
from pathlib import Path
import yaml
ROOT=Path(__file__).resolve().parents[1]
APP='willitmod-dev-dgb'
def record():return json.loads((ROOT/'DGB-ROUTE-EVIDENCE-2026-10-03.json').read_text())
def digest(v):return hashlib.sha256(json.dumps(v,sort_keys=True,separators=(',',':')).encode()).hexdigest()
def previous_route_model(app_id,current):
    if app_id!=APP:return copy.deepcopy(current)
    r=record();c=r['runtimeContract'];restored=copy.deepcopy(current)
    assert len(c['changes'])==1 and c['changes'][0]['path']==['services','app','image']
    change=c['changes'][0];assert digest(current)==c['afterModelSHA256']
    assert current['services']['app']['image']==change['after']==r['imageRef']
    old=json.loads((ROOT/'DGB-WATCHDOG-2026-10-02.json').read_text())
    assert change['before']==old['imageRef'] and c['beforeModelSHA256']==old['runtimeContract']['afterModelSHA256']
    restored['services']['app']['image']=change['before'];assert digest(restored)==c['beforeModelSHA256']
    return restored
class DgbRouteReleaseTests(unittest.TestCase):
    def test_app_only_runtime_and_current_version(self):
        r=record();self.assertEqual(r['version'],'0.9.189-dev');self.assertEqual(r['channel'],'DEV')
        self.assertEqual(r['sourceRevision'],'4a050ea08c48dcf1200b573eb508aecac22cfa8f')
        self.assertEqual(r['sourceMerge'],'5f1a11ee7d15e6fcdcf9793bf39b1f2eb230f1be')
        self.assertRegex(r['imageRef'],r'^ghcr.io/willitmod/axedgb-app:0\.9\.189-dev@sha256:[a-f0-9]{64}$')
        current=yaml.safe_load((ROOT/APP/'docker-compose.yml').read_text());previous_route_model(APP,current)
        self.assertEqual(current['services']['dgbd']['image'],r['coreImageRef'])
        self.assertEqual(r['coreImageRef'],'ghcr.io/willitmod/axedgb-core:9.26.6-dev.2@sha256:fb46ff018e701accf6630b65c4b33a7d9d24b5fa248c31122d2daa2503677039')
        manifest=yaml.safe_load((ROOT/APP/'umbrel-app.yml').read_text());self.assertEqual(manifest['version'],r['version'])
        for text in ('route unconfirmed','Accepted pool estimates','9.26.6','Previous 0.9.188'):
            self.assertIn(text,manifest['releaseNotes'])
    def test_other_service_configuration_change_is_rejected(self):
        current=yaml.safe_load((ROOT/APP/'docker-compose.yml').read_text())
        for service,key,value in [('dgbd','image','wrong'),('app','volumes',[]),('init','command',[]),('miningcore','image','wrong')]:
            changed=copy.deepcopy(current);changed['services'][service][key]=value
            with self.assertRaises(AssertionError):previous_route_model(APP,changed)
    def test_public_record_has_both_configs_without_private_host_material(self):
        raw=(ROOT/'DGB-ROUTE-EVIDENCE-2026-10-03.json').read_text()
        for private in ('/Users/','/home/forge','10.10.10.','APP_PASSWORD'):self.assertNotIn(private,raw)
        r=record();self.assertEqual(set(r['appImages']),{'amd64','arm64'})
        for row in r['appImages'].values():
            self.assertEqual(set(row),{'configDigest','manifestDigest'})
            for value in row.values():self.assertRegex(value,r'^sha256:[a-f0-9]{64}$')
if __name__=='__main__':unittest.main()
