"""Bind the discovery fix to identical server/helper images and exact recipe scope."""
import copy
import hashlib
import json
from pathlib import Path
import unittest
import yaml
from test_axemig_stop_release import APP, previous_mig_stop_model, previous_mig_stop_manifest

ROOT = Path(__file__).resolve().parents[1]
RECORD = json.loads((ROOT / 'AXEMIG-CHAIN-DISCOVERY-2026-10-14.json').read_text())

def digest(model):
    return hashlib.sha256(json.dumps(model, sort_keys=True, separators=(',', ':')).encode()).hexdigest()

class AxemigChainReleaseTests(unittest.TestCase):
    def test_only_server_helper_and_version_change(self):
        current=previous_mig_stop_model(APP,yaml.safe_load((ROOT/'willitmod-dev-axemig/docker-compose.yml').read_text()))
        self.assertEqual(digest(current),RECORD['afterModelSHA256'])
        self.assertEqual({tuple(r['path']) for r in RECORD['changes']},{
            ('services','server','image'),('services','server','environment','AXEMIG_HELPER_IMAGE'),
            ('services','server','environment','APP_VERSION')})
        self.assertEqual(len(RECORD['changes']),3)
        old=copy.deepcopy(current)
        for r in RECORD['changes']:
            node=old
            for key in r['path'][:-1]:node=node[key]
            self.assertEqual(node[r['path'][-1]],r['after']);node[r['path'][-1]]=r['before']
        self.assertEqual(digest(old),RECORD['beforeModelSHA256'])
        self.assertEqual(current['services']['server']['image'],RECORD['image'])
        self.assertEqual(current['services']['server']['environment']['AXEMIG_HELPER_IMAGE'],RECORD['image'])
        self.assertEqual(RECORD['image'],'ghcr.io/willitmod/axemig:0.1.23-dev@'+RECORD['digest'])
        self.assertEqual(current['services']['server']['environment']['APP_VERSION'],'0.1.23-dev')

    def test_visible_recipe_and_published_source_binding(self):
        manifest=previous_mig_stop_manifest(yaml.safe_load((ROOT/'willitmod-dev-axemig/umbrel-app.yml').read_text()))
        self.assertEqual(manifest['version'],RECORD['packageVersion'])
        self.assertEqual(manifest['version'],'0.1.23-dev')
        self.assertIn('independent BC2',manifest['releaseNotes'])
        self.assertEqual(RECORD['source'],'2e7509b73d54068d1d77b5409b8fbe3ec25887a8')
        self.assertEqual(set(RECORD['platforms']),{'amd64','arm64'})
        self.assertEqual(len({p['source_tree'] for p in RECORD['platforms'].values()}),1)
        self.assertTrue(RECORD['anonymous_access'])

    def test_source_checks_do_not_claim_new_runtime_qualification(self):
        self.assertEqual(RECORD['sourceTests'],24)
        self.assertFalse(RECORD['actualNewClassificationRuntimeQualified'])
        self.assertFalse(RECORD['fullAppQualified'])
        self.assertEqual(RECORD['preservedCoreRuntimeEvidence']['checksPerPlatform'],48)

if __name__=='__main__':unittest.main()
