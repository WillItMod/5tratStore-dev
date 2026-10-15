"""Reverse only reviewed completion-access/pool-idle fields before old contracts."""
import copy,hashlib,json,subprocess,unittest
from pathlib import Path
import yaml
from app_version_normalization import previous_app_version_model, package_version as normalized_package_version
ROOT=Path(__file__).resolve().parents[1]
APP='willitmod-dev-axebch2'
RECORD=json.loads((ROOT/'BCH2-RESTART-COMPLETION-2026-10-14.json').read_text())
BASELINE='7387a836279563571a2f27ad064b3f7a8d102aac74efa9463d964f20af27e9d5'
OLD_POOL='ghcr.io/willitmod/axebch2-ckpool:0.1.34-dev@sha256:4d2cc3813cd48211ce685e51afeaa62c3a606282bb8e6c8fa8ccc4e43ec75ec3'
def digest(model):return hashlib.sha256(json.dumps(model,sort_keys=True,separators=(',',':')).encode()).hexdigest()
def package_version(app_id,historical):return normalized_package_version(app_id,RECORD['packageVersion'])if app_id==APP else historical

def previous_bch2_completion_model(app_id,current):
 if app_id!=APP:return copy.deepcopy(current)
 assert RECORD['beforeModelSHA256']==BASELINE
 # The preceding immutable node adapter can also receive its exact old input.
 if digest(current)==BASELINE:return copy.deepcopy(current)
 current=previous_app_version_model(app_id,current)
 assert digest(current)==RECORD['afterModelSHA256']
 expected={('services','app','group_add'):(False,None,['${AXEBCH2_DOCKER_GID:-1000}']),('services','ckpool','image'):(True,OLD_POOL,RECORD['poolImageRef']),('services','app','environment','CKPOOL_IMAGE'):(True,OLD_POOL,RECORD['poolImageRef']),('services','app','environment','APP_VERSION'):(True,'0.2.0.12-dev.1',RECORD['packageVersion'])}
 assert len(RECORD['changes'])==len(expected)and{tuple(r['path'])for r in RECORD['changes']}==set(expected)
 result=copy.deepcopy(current)
 for r in RECORD['changes']:
  target=result
  for key in r['path'][:-1]:target=target[key]
  key=r['path'][-1]
  assert (r['beforeExists'],r['before'],r['after'])==expected[tuple(r['path'])]
  assert target[key]==r['after']
  if r['beforeExists']:target[key]=r['before']
  else:del target[key]
 assert digest(result)==BASELINE
 return result

class Bch2RestartCompletionReleaseTests(unittest.TestCase):
 def test_whole_model_only_four_fields_and_prior_node_guard_preserved(self):
  model=yaml.safe_load((ROOT/APP/'docker-compose.yml').read_text());before=yaml.safe_load(subprocess.check_output(['git','show',RECORD['baselineCommit']+':'+APP+'/docker-compose.yml'],cwd=ROOT,text=True))
  self.assertEqual(previous_bch2_completion_model(APP,model),before)
  self.assertEqual(model['services']['app']['image'],RECORD['applicationImageUnchanged']);self.assertEqual(model['services']['app']['user'],'1000:1000')
  self.assertEqual(model['services']['bch2'],before['services']['bch2']);self.assertEqual(model['services']['init_permissions'],before['services']['init_permissions'])
  from test_bch2_node_entrypoint_release import previous_bch2_node_model
  previous_bch2_node_model(APP,model)
 def test_wrong_capability_images_mounts_policy_and_groups_are_refused(self):
  model=yaml.safe_load((ROOT/APP/'docker-compose.yml').read_text())
  for service,key,value in [('app','group_add',['0']),('app','group_add',['${AXEBCH2_DOCKER_GID:-0}']),('app','user','0'),('app','volumes',[]),('app','image','different-app'),('ckpool','image','moving:latest'),('ckpool','command',[]),('bch2','environment',{}),('bch2','stop_grace_period','10s'),('init_permissions','command',[])]:
   changed=copy.deepcopy(model);changed['services'][service][key]=value
   with self.subTest(service=service,key=key),self.assertRaises(AssertionError):previous_bch2_completion_model(APP,changed)
 def test_manifests_only_version_and_prepended_note(self):
  for name in ['global-app.yml','umbrel-app.yml']:
   now=yaml.safe_load((ROOT/APP/name).read_text());old=yaml.safe_load(subprocess.check_output(['git','show',RECORD['baselineCommit']+':'+APP+'/'+name],cwd=ROOT,text=True));self.assertEqual(now.pop('version'),package_version(APP,RECORD['packageVersion']));self.assertEqual(old.pop('version'),'0.2.0.12-dev.1');notes,prior=now.pop('releaseNotes'),old.pop('releaseNotes');self.assertTrue(notes.endswith('\n'+prior));self.assertIn('existing Docker socket group',notes);self.assertIn('waiting for a payout address',notes);self.assertEqual(now,old)
 def test_exact_exports_and_all_other_package_bytes_retained(self):
  exports=ROOT/APP/'exports.sh';self.assertEqual(hashlib.sha256(exports.read_bytes()).hexdigest(),RECORD['exportsSHA256']);self.assertEqual(oct(exports.stat().st_mode&0o777),RECORD['exportsMode'])
  names=subprocess.check_output(['git','ls-tree','-r','--name-only',RECORD['baselineCommit'],'--',APP],cwd=ROOT,text=True).splitlines();self.assertEqual({str(p.relative_to(ROOT))for p in(ROOT/APP).rglob('*')if p.is_file()},set(names)|{APP+'/exports.sh'})
  for name in names:
   if Path(name).name in {'docker-compose.yml','global-app.yml','umbrel-app.yml'}:continue
   with self.subTest(path=name):self.assertEqual((ROOT/name).read_bytes(),subprocess.check_output(['git','show',RECORD['baselineCommit']+':'+name],cwd=ROOT))
 def test_pool_source_both_native_images_and_unchanged_app_are_bound(self):
  self.assertEqual(RECORD['poolSourceRevision'],'d1a7e6d362feda8485018082cda9ada353986917');self.assertEqual(RECORD['poolSourceTree'],'5a358c47c98c67e612e72c9a2464f4f4b0a2feb7');self.assertEqual(RECORD['poolPublicationRun'],38648447565);self.assertEqual(RECORD['poolEntrypointSHA256'],'d730058daf999f6735fa943f711616ec9d5dc19d8a2d9f7369d719a12d360589')
  self.assertTrue(RECORD['poolImageRef'].endswith('@sha256:de3dca9f94f73aa9fb46812aa8ef65556e3ffa14b25ef3273bf4523753ea555c'));self.assertEqual(set(RECORD['poolImages']),{'amd64','arm64'});self.assertEqual(RECORD['applicationSourceRevisionUnchanged'],'5531b5e6e2e4c55353454665af9fc1950f9f0844')
  for arch,row in RECORD['poolImages'].items():self.assertRegex(row['configDigest'],r'^sha256:[a-f0-9]{64}$');self.assertEqual((row['binary']['mode'],row['binary']['uid'],row['binary']['gid']),(493,0,0))
  self.assertFalse(RECORD['validationScope']['normalAppManagerUpdateQualified']);self.assertFalse(RECORD['validationScope']['miningProtocolQualified'])
 def test_other_adapters_and_models_remain_disjoint(self):
  from test_ppc_immutable_release import APP as PPC,previous_ppc_model
  ppc=yaml.safe_load((ROOT/PPC/'docker-compose.yml').read_text());self.assertEqual(previous_bch2_completion_model(PPC,ppc),ppc);previous_ppc_model(PPC,ppc)
  self.assertEqual(package_version(PPC,'retained'),'retained')
if __name__=='__main__':unittest.main()
