"""Prove recovery metadata came from the pinned Git recipes, not the worktree."""
import base64
import hashlib
import importlib.util
import json
from pathlib import Path
import subprocess
import unittest

import yaml

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location('fumbrel_build_catalog', ROOT / 'scripts/fumbrel/build_catalog.py')
builder = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(builder)
CATALOG = json.loads((ROOT / builder.CATALOG_PATH).read_text())


class CatalogTests(unittest.TestCase):
    def test_bundle_reproduces_from_exact_git_inputs(self):
        self.assertEqual(builder.serialized(builder.build()), (ROOT / builder.CATALOG_PATH).read_text())
        for entry in CATALOG['apps'].values():
            if entry['channel'] != 'DEV':
                continue
            self.assertEqual(entry['source_commit'], builder.DEV_COMMIT)
            for name, record in entry['files'].items():
                with self.subTest(app=entry['source_id'], file=name):
                    body = subprocess.check_output(['git', 'show', builder.DEV_COMMIT + ':' + entry['source_id'] + '/' + name], cwd=ROOT)
                    self.assertEqual(base64.b64decode(record['body']), body)
                    self.assertEqual(record['sha256'], hashlib.sha256(body).hexdigest())

    def test_ownership_hooks_are_bundled_with_executable_git_modes(self):
        for app_id in ('willitmod-dev-axebench', 'willitmod-dev-axelive'):
            with self.subTest(app=app_id):
                entry = CATALOG['apps'][app_id]
                hook = entry['files']['hooks/pre-start']
                self.assertEqual(hook['mode'], 0o755)
                self.assertIn(b'chown -h 1000:1000', base64.b64decode(hook['body']))
                self.assertTrue(entry['version'].endswith('-dev.1'))
        self.assertEqual(CATALOG['apps']['willitmod-dev-axemig']['version'], '0.1.21-dev.1')
        compose = base64.b64decode(CATALOG['apps']['willitmod-dev-axemig']['files']['docker-compose.yml']['body'])
        self.assertEqual(yaml.safe_load(compose)['services']['app_proxy']['environment']['APP_HOST'],
                         'willitmod-dev-axemig_server_1')
        self.assertEqual(CATALOG['apps']['willitmod-dev-powpow']['version'], '0.2.37-dev.2')
        self.assertEqual(CATALOG['apps']['willitmod-dev-axebch2']['version'], '0.2.0.12-dev')

    def test_main_axesim_entry_is_retained_exactly(self):
        previous = json.loads(builder.git('show', builder.RETAINED_CATALOG_COMMIT + ':' + builder.CATALOG_PATH))
        self.assertEqual(CATALOG['apps']['willitmod-axesim'], previous['apps']['willitmod-axesim'])
        self.assertEqual(CATALOG['apps']['willitmod-axesim']['source_commit'], builder.MAIN_COMMIT)
        self.assertEqual(len(CATALOG['apps']), 18)
        self.assertNotIn(builder.SELF, CATALOG['apps'])

    def test_powpow_static_seed_prerequisites_are_hashes_only(self):
        entry = CATALOG['apps']['willitmod-dev-powpow']
        self.assertEqual(entry['files']['hooks/pre-start']['mode'], 0o755)
        for template in ('powpow-2-schema.sql.template', 'powpow-3-multi-pool-partition.sql.template'):
            self.assertIn(template, entry['files'])
        self.assertEqual(set(entry['required_existing_files']), set(builder.POWPOW_SEEDS))
        for name, requirement in entry['required_existing_files'].items():
            with self.subTest(seed=name):
                self.assertEqual(set(requirement), {'sha256'})
                body = builder.git('show', builder.DEV_COMMIT + ':' + entry['source_id'] + '/' + name)
                self.assertEqual(requirement['sha256'], hashlib.sha256(body).hexdigest())
                self.assertNotIn(name, entry['files'])
        for other in CATALOG['apps'].values():
            if other['source_id'] != entry['source_id']:
                self.assertNotIn('required_existing_files', other)

    def test_mutable_or_abbreviated_refs_are_rejected(self):
        for ref in ('HEAD', 'main', builder.DEV_COMMIT[:8], '--help', builder.DEV_COMMIT.upper()):
            with self.subTest(ref=ref), self.assertRaises(ValueError):
                builder.build(dev_ref=ref)
        with self.assertRaises(ValueError):
            builder.build(retained_catalog_ref='main')

    def test_release_and_workflow_match_unpublished_candidate(self):
        manifest = yaml.safe_load((ROOT / 'willitmod-dev-fumbrel/umbrel-app.yml').read_text())
        compose = yaml.safe_load((ROOT / 'willitmod-dev-fumbrel/docker-compose.yml').read_text())
        self.assertEqual(CATALOG['release'], manifest['version'])
        self.assertEqual(CATALOG['release'], builder.RELEASE)
        self.assertEqual(compose['services']['server']['image'].split('@')[0], 'ghcr.io/willitmod/fumbrel:' + builder.RELEASE)
        workflow = yaml.load((ROOT / '.github/workflows/fumbrel-image.yml').read_text(), Loader=yaml.BaseLoader)
        self.assertIn('pull_request', workflow['on'])
        self.assertEqual(workflow['permissions'], {'contents': 'read'})
        verify = workflow['jobs']['verify']
        self.assertFalse(any('login-action' in step.get('uses', '') for step in verify['steps']))
        self.assertEqual([step['with']['push'] for step in verify['steps'] if 'build-push-action' in step.get('uses', '')], ['false'])
        publish = workflow['jobs']['publish']
        for required in ("github.event_name == 'workflow_dispatch'", 'inputs.publish', "github.ref == 'refs/heads/main'"):
            self.assertIn(required, publish['if'])
        self.assertEqual(publish['needs'], 'verify')
        self.assertEqual(publish['permissions']['packages'], 'write')
        self.assertEqual(publish['concurrency'], {'group': 'fumbrel-publish-' + builder.RELEASE, 'cancel-in-progress': 'false'})
        checks = [i for i, step in enumerate(publish['steps']) if 'check_publish_tag.py' in step.get('run', '')]
        pushes = [i for i, step in enumerate(publish['steps']) if step.get('with', {}).get('push') == 'true']
        self.assertEqual(len(checks), 1)
        self.assertEqual(len(pushes), 1)
        self.assertLess(checks[0], pushes[0])
        check = publish['steps'][checks[0]]
        self.assertEqual(check['env']['GHCR_PASSWORD'], '${{ secrets.GITHUB_TOKEN }}')
        self.assertNotIn('GITHUB_TOKEN', check['run'])


if __name__ == '__main__':
    unittest.main()
