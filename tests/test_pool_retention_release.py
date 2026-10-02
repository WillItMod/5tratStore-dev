"""Exact app-only pool retention release delta, before historical contracts."""
import copy
import hashlib
import json
from pathlib import Path
import re
import unittest
import yaml
from test_recovery_release import APPS as RECOVERY_APPS, previous_recovery_model

ROOT=Path(__file__).resolve().parents[1]
RELEASE=json.loads((ROOT/'POOL-RETENTION-2026-10-01.json').read_text())
APPS=RELEASE['apps']

def digest(value):return hashlib.sha256(json.dumps(value,sort_keys=True,separators=(',',':')).encode()).hexdigest()

def previous_model(app_id,current,filename='docker-compose.yml'):
    current=previous_recovery_model(app_id,current,filename)
    if app_id not in APPS:return copy.deepcopy(current)
    record=APPS[app_id];contract=RELEASE['runtimeContracts'][app_id][filename]
    assert digest(current)==contract['afterModelSHA256']
    expected={('services','app','image'),('services','app','environment','APP_REVISION')}
    expected.update(('services','app','environment',k) for k in ('APP_VERSION','APP_IMAGE','FIVETRAT_RELEASE_TAG') if k in current['services']['app']['environment'])
    assert {tuple(r['path']) for r in contract['changes']}==expected
    assert len(contract['changes'])==len(expected)
    values={'image':record['imageRef'],'APP_REVISION':record['sourceRevision'],'APP_VERSION':record['version'],
            'APP_IMAGE':record['imageRef'],'FIVETRAT_RELEASE_TAG':record['baseVersion']}
    restored=copy.deepcopy(current)
    for row in contract['changes']:
        node=restored
        for key in row['path'][:-1]:node=node[key]
        key=row['path'][-1];assert node[key]==row['after']==values[key]
        if row['existed']:node[key]=row['before']
        else:del node[key]
    assert digest(restored)==contract['beforeModelSHA256']
    return restored

class PoolRetentionReleaseTests(unittest.TestCase):
    def test_exact_seven_current_recipes_and_unchanged_runtime(self):
        assert RELEASE['schemaVersion']==1 and RELEASE['channel']=='DEV'
        assert RELEASE['baselineCommit']=='26bba898734b7bfac05b136a60055cfdda8deb45'
        assert set(APPS)=={'willitmod-dev-'+x for x in ('bch','btc','bc2','axebch2','xec','fracattack','5tratsmack')}
        assert set(RELEASE['runtimeContracts'])==set(APPS)
        for aid,record in APPS.items():
            assert re.fullmatch('[0-9a-f]{40}',record['sourceRevision'])
            assert re.fullmatch('ghcr.io/willitmod/[^:]+:'+re.escape(record['baseVersion'])+'@sha256:[0-9a-f]{64}',record['imageRef'])
            assert set(record['images'])=={'amd64','arm64'}
            for image in record['images'].values():
                for key in ('configDigest','manifestDigest'):assert re.fullmatch('sha256:[0-9a-f]{64}',image[key])
            for filename in RELEASE['runtimeContracts'][aid]:
                current=yaml.safe_load((ROOT/aid/filename).read_text());previous_model(aid,current,filename)
                current['services']['app']['volumes']=['unreviewed:/data']
                with self.assertRaises(AssertionError):previous_model(aid,current,filename)
            for filename in record['manifests']:
                manifest=yaml.safe_load((ROOT/aid/filename).read_text())
                assert manifest['version']==RECOVERY_APPS.get(aid,record)['version'] and 'Complete block and pool accounting records' in manifest['releaseNotes']

    def test_public_identity_record_has_no_private_host_material(self):
        data=(ROOT/'POOL-RETENTION-2026-10-01.json').read_text()
        for private in ('/Users/','/home/forge','10.10.10.','PAYOUT_ADDRESS','APP_PASSWORD'):
            self.assertNotIn(private,data)

if __name__=='__main__':unittest.main()
