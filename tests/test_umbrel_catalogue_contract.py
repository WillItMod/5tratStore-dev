"""Full-catalogue compatibility blockers and stale runtime evidence regressions."""

import copy
import contextlib
import importlib.util
import io
import json
from pathlib import Path
import subprocess
import tarfile
import tempfile
import unittest

import yaml

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location('umbrel_catalogue_contract',
                                             ROOT / 'scripts/umbrel_catalogue_contract.py')
contract = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(contract)
APP_IDS = frozenset('willitmod-dev-' + name for name in (
    '5tratsmack', 'axebch2', 'axebench', 'axelive', 'axemig', 'bc2', 'bch',
    'btc', 'dgb', 'fracattack', 'fumbrel', 'powpow', 'ppc', 'xec',
))


def compose(host='app'):
    return {'services': {'app_proxy': {'environment': {'APP_HOST': host, 'APP_PORT': 3000}},
                         'app': {'image': 'example/app:1@sha256:' + '1' * 64,
                                 'volumes': ['${APP_DATA_DIR}/data:/data']}}}


class CatalogueContractTests(unittest.TestCase):
    def test_every_authoritative_manifest_is_checked(self):
        self.assertEqual({path.name for path in contract.inventory(ROOT)}, APP_IDS)
        self.assertNotIn('willitmod-dev-5tratumos-diagnostics', APP_IDS)
        results = contract.catalogue_contract(ROOT)
        self.assertEqual({item['app_id'] for item in results}, APP_IDS)
        for item in results:
            with self.subTest(app=item['app_id']):
                self.assertEqual(item['static_contract_errors'], [])
                self.assertEqual(set(item['candidate']), {'app_id', 'package_version',
                                 'manifest_sha256', 'compose_sha256', 'tree_sha256', 'images'})

    def test_legacy_string_mount_blocker_in_every_service_including_proxy(self):
        for name in ('app', 'app_proxy'):
            with self.subTest(service=name):
                broken = compose()
                broken['services'][name]['volumes'] = [{'type': 'bind', 'source': '/data', 'target': '/data'}]
                self.assertTrue(any('requires string mount' in error for error in
                                    contract.compose_contract_errors(broken, 'sample')))

    def test_gateway_exact_service_hostname_container_and_generated_name(self):
        for host, service in (
            ('app', {}), ('my-app', {'hostname': 'my-app'}),
            ('custom-container', {'container_name': 'custom-container'}),
            ('sample_app_1', {}), ('${APP_ID}_app_1', {'container_name': '${APP_ID}_app_1'}),
        ):
            with self.subTest(host=host):
                value = compose(host)
                value['services']['app'].update(service)
                self.assertEqual(contract.compose_contract_errors(value, 'sample'), [])

    def test_gateway_network_alias_alone_does_not_match_service_discovery(self):
        value = compose('alias-only')
        value['services']['app']['networks'] = {'default': {'aliases': ['alias-only']}}
        self.assertTrue(any('found 0' in error for error in contract.compose_contract_errors(value, 'sample')))

    def test_gateway_never_matches_the_removed_proxy_and_ambiguous_matches_fail(self):
        for host in ('app_proxy', 'sample_app_proxy_1'):
            self.assertTrue(contract.compose_contract_errors(compose(host), 'sample'))
        value = compose()
        value['services']['other'] = {'hostname': 'app', 'image': 'example/other:1'}
        self.assertTrue(any('found 2' in error for error in contract.compose_contract_errors(value, 'sample')))

    def test_proxy_removal_detects_list_mapping_alias_link_and_network_dependencies(self):
        for field, value in (
            ('depends_on', ['app_proxy']),
            ('depends_on', {'app_proxy': {'condition': 'service_started'}}),
            ('links', ['app_proxy:old-proxy']), ('network_mode', 'service:app_proxy'),
            ('network_mode', 'container:${APP_ID}_app_proxy_1'),
        ):
            with self.subTest(field=field, value=value):
                broken = compose()
                broken['services']['app'][field] = value
                self.assertTrue(any('app_proxy is removed' in error for error in
                                    contract.compose_contract_errors(broken, 'sample')))

    def test_gateway_port_validation_and_native_apps(self):
        for port in (0, 65536, 'unknown', None):
            value = compose()
            value['services']['app_proxy']['environment']['APP_PORT'] = port
            self.assertTrue(any('APP_PORT' in error for error in contract.compose_contract_errors(value, 'sample')))
        value = compose()
        del value['services']['app_proxy']
        self.assertEqual(contract.compose_contract_errors(value, 'sample'), [])

    def test_all_catalogue_exports_survive_missing_auth_and_preserve_supplied_secret(self):
        for app_dir in contract.inventory(ROOT):
            with self.subTest(app=app_dir.name):
                self.assertEqual(contract.exports_contract_errors(app_dir), [])

    def test_cli_requires_13_native_and_all_14_umbrel_app_targets(self):
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            code = contract.main(['--root', str(ROOT), '--target', 'umbrel:2.0.0:amd64',
                                  '--target', '5tratumos:0.8.31:amd64'])
        self.assertEqual(code, 1)  # Current runtime receipts were not supplied.
        results = json.loads(output.getvalue())['apps']
        entries = [(app['app_id'], item) for app in results for item in app['runtime_readiness']]
        self.assertEqual(sum(item['applicable'] for _, item in entries if item['target']['os'] == 'umbrel'), 14)
        self.assertEqual(sum(item['applicable'] for _, item in entries if item['target']['os'] == '5tratumos'), 13)
        skipped = [(app_id, item) for app_id, item in entries if not item['applicable']]
        self.assertEqual(len(skipped), 1)
        app_id, item = skipped[0]
        self.assertEqual(app_id, 'willitmod-dev-fumbrel')
        self.assertEqual(item['status'], 'not_applicable')
        self.assertIn('Umbrel only', item['reason'])
        self.assertEqual(item['errors'], [])

    def test_unknown_os_and_undefined_native_app_scope_are_errors(self):
        for os_name in ('unknown', '5tratumOS', 'linux', ''):
            with self.subTest(os=os_name), self.assertRaises(ValueError):
                contract.target_applicability('willitmod-dev-btc', {'os': os_name})
        with self.assertRaises(ValueError):
            contract.target_applicability('willitmod-dev-new-app', {'os': '5tratumos'})

    def test_official_174_parser_accepts_every_base_and_start_template_repeatedly(self):
        fixture = ROOT / 'tests/fixtures/umbrel_1_7_4_patch_compose.cjs'
        for app_dir in contract.inventory(ROOT):
            for filename in ('docker-compose.yml', 'docker-compose.yml.template'):
                path = app_dir / filename
                if not path.exists():
                    continue
                with self.subTest(app=app_dir.name, recipe=filename):
                    model = contract.read_yaml(path)
                    for _ in range(2):
                        result = subprocess.run(['node', str(fixture)],
                                                input=json.dumps({'compose': model, 'id': app_dir.name}),
                                                text=True, capture_output=True, check=True, timeout=15)
                        model = json.loads(result.stdout)

    def test_gateway_uses_start_template_but_base_recipe_still_needs_legacy_mount_syntax(self):
        with tempfile.TemporaryDirectory() as temp:
            app_dir = Path(temp) / 'sample'
            app_dir.mkdir()
            (app_dir / 'docker-compose.yml').write_text(yaml.safe_dump(compose('native-only-alias')))
            (app_dir / 'docker-compose.yml.template').write_text(yaml.safe_dump(compose('app')))
            self.assertEqual(contract.app_contract_errors(app_dir), [])
            base = compose('native-only-alias')
            base['services']['app']['volumes'] = [{'source': '/data', 'target': '/data'}]
            (app_dir / 'docker-compose.yml').write_text(yaml.safe_dump(base))
            self.assertTrue(any('requires string mount' in error for error in contract.app_contract_errors(app_dir)))
            (app_dir / 'docker-compose.yml').write_text(yaml.safe_dump(compose('native-only-alias')))
            (app_dir / 'docker-compose.yml.template').write_text(yaml.safe_dump(compose('broken-upstream')))
            self.assertTrue(any('found 0' in error for error in contract.app_contract_errors(app_dir)))


class RuntimeReadinessTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.app = self.root / 'willitmod-dev-btc'
        self.app.mkdir()
        (self.app / 'umbrel-app.yml').write_text(yaml.safe_dump({'id': self.app.name, 'version': '1.2.3-dev'}))
        (self.app / 'docker-compose.yml').write_text(yaml.safe_dump(compose()))
        (self.app / 'hooks').mkdir()
        (self.app / 'hooks/install').write_text('#!/bin/sh\ntrue\n')
        self.evidence = self.root / 'evidence'
        self.evidence.mkdir()
        (self.evidence / 'fixture.log').write_text('Synthetic unit-test fixture only, no real runtime verification.\n')
        self.target = {'os': 'umbrel', 'version': '1.7.4', 'architecture': 'amd64'}
        self.native_root = None
        lock = self.fixture_lock('app', 'example/app:1')
        model = compose()
        model['services']['app']['image'] = lock['reference']
        (self.app / 'docker-compose.yml').write_text(yaml.safe_dump(model))
        self.receipt = {'schema_version': 2, 'app_id': self.app.name,
                        'candidate': contract.candidate_fingerprint(self.app),
                        'target': self.target.copy(), 'verification': 'runtime', 'historical': False,
                        'checks': {}, 'runtime_images': {'app': self.fixture_observation('app', lock)}}
        self.qualification = {'schema_version': 1, 'app_id': self.app.name,
                              'candidate': self.receipt['candidate'], 'target': self.target.copy(),
                              'deployment': contract.deployment_model(self.app, self.target)[1],
                              'images': {'app': lock}, 'builds': {}}
        self.refresh_qualification()
        for name in (*contract.REQUIRED_CHECKS, 'node_pool_accepted_share'):
            self.receipt['checks'][name] = {'status': 'pass', 'observation': 'Synthetic test-only observation',
                                          'artifacts': [{'path': 'fixture.log',
                                                        'sha256': contract.sha256(self.evidence / 'fixture.log')}]}

    def errors(self, receipt=None, target=None):
        return contract.readiness_errors(self.app, receipt if receipt is not None else self.receipt,
                                         target if target is not None else self.target, self.evidence,
                                         self.qualification, self.native_root)

    def json_artifact(self, name, value):
        path = self.evidence / (name + '.json')
        path.write_text(json.dumps(value, sort_keys=True, separators=(',', ':')))
        return {'path': path.name, 'sha256': contract.sha256(path)}

    def fixture_lock(self, name, repository, config_architecture='amd64'):
        config = self.json_artifact(name + '-config', {'_synthetic_fixture': True,
                                    'os': 'linux', 'architecture': config_architecture,
                                    'rootfs': {'type': 'layers', 'diff_ids': ['sha256:' + '1' * 64]}})
        config_digest = 'sha256:' + config['sha256']
        manifest = self.json_artifact(name + '-manifest', {'schemaVersion': 2,
                                      'config': {'digest': config_digest}})
        platform_digest = 'sha256:' + manifest['sha256']
        index = self.json_artifact(name + '-index', {'schemaVersion': 2,
                                   'manifests': [{'digest': platform_digest,
                                                'platform': {'os': 'linux', 'architecture': 'amd64'}}]})
        index_digest = 'sha256:' + index['sha256']
        return {'reference': repository + '@' + index_digest, 'platform': 'linux/amd64',
                'index_digest': index_digest, 'platform_digest': platform_digest,
                'config_digest': config_digest, 'index_artifact': index,
                'platform_artifact': manifest, 'config_artifact': config}

    def fixture_observation(self, name, lock, classic=False, local_build=False):
        config_digest = lock['config_digest']
        image_id = config_digest if classic or local_build else lock['index_digest']
        reference = 'synthetic-local-build' if local_build else lock['reference']
        image = {'Id': image_id, 'Os': 'linux', 'Architecture': 'amd64',
                 'RepoDigests': [] if local_build else [lock['reference']]}
        container_id = 'c' * 64
        container = {'Id': container_id, 'Image': config_digest,
                     'Config': {'Image': reference},
                     'State': {'Status': 'running', 'StartedAt': '2026-10-14T00:00:00Z', 'ExitCode': 0}}
        return {'reference': reference, 'platform': 'linux/amd64',
                'index_digest': None if local_build else lock['index_digest'],
                'platform_digest': None if local_build else lock['platform_digest'],
                'config_digest': config_digest, 'image_id': image_id,
                'container_image_id': config_digest, 'container_id': container_id, 'executed': True,
                'image_inspect_artifact': self.json_artifact(name + '-image-inspect', [image]),
                'container_inspect_artifact': self.json_artifact(name + '-container-inspect', [container])}

    def refresh_qualification(self):
        candidate = contract.candidate_fingerprint(self.app)
        self.qualification.update(candidate=candidate, target=self.target.copy(),
                                  deployment=contract.deployment_model(self.app, self.target, self.native_root)[1])
        self.receipt.update(candidate=candidate, target=self.target.copy(),
                            deployment=copy.deepcopy(self.qualification['deployment']),
                            qualification_sha256=contract.canonical_sha256(self.qualification))

    def git(self, *args):
        return subprocess.run(['git', '-C', str(self.root), *args],
                              capture_output=True, check=True, timeout=15).stdout

    def initialize_git(self):
        self.git('init', '-q')
        (self.root / '.gitignore').write_text('__pycache__/\n*.pyc\n')
        self.git('add', '.gitignore', self.app.name)
        self.git('-c', 'commit.gpgsign=false', '-c', 'user.name=Contract fixture',
                 '-c', 'user.email=fixture@example.invalid', 'commit', '-qm', 'Synthetic test fixture')
        self.receipt['candidate'] = contract.candidate_fingerprint(self.app)
        self.refresh_qualification()

    def test_complete_synthetic_schema_fixture_validates(self):
        self.assertEqual(self.errors(), [])

    def test_historical_smoke_and_static_inspection_cannot_claim_current_readiness(self):
        for verification, historical in (('static', False), ('runtime', True), ('smoke', False)):
            receipt = copy.deepcopy(self.receipt)
            receipt.update(verification=verification, historical=historical)
            self.assertTrue(any('runtime verification required' in error for error in self.errors(receipt)))

    def test_each_required_lifecycle_data_auth_network_functional_and_mining_check_is_gated(self):
        for name in (*contract.REQUIRED_CHECKS, 'node_pool_accepted_share'):
            for status in ('missing', 'blocked', 'fail', 'not_tested', 'static_pass'):
                with self.subTest(check=name, status=status):
                    receipt = copy.deepcopy(self.receipt)
                    if status == 'missing':
                        del receipt['checks'][name]
                    else:
                        receipt['checks'][name]['status'] = status
                    self.assertIn(f'{name}: runtime pass evidence required', self.errors(receipt))

    def test_exact_target_version_architecture_and_os_required(self):
        for field, changed in (('version', '2.0.0'), ('version', '1.7.3'),
                               ('architecture', 'arm64'), ('os', '5tratumos')):
            target = self.target.copy()
            target[field] = changed
            self.assertIn('target OS, exact version or architecture mismatch', self.errors(target=target))
        for version in ('1.7', '1.7.x', '2.0', 'latest', '>=1.7.4', ''):
            target = dict(self.target, version=version)
            self.assertTrue(any('version must be exact' in error for error in self.errors(target=target)))

    def test_manifest_compose_hooks_template_tree_and_modes_invalidate_old_evidence(self):
        original = contract.candidate_fingerprint(self.app)
        for filename in ('umbrel-app.yml', 'docker-compose.yml', 'hooks/install'):
            with self.subTest(file=filename):
                path = self.app / filename
                saved = path.read_bytes()
                path.write_bytes(saved + b'\n# changed candidate\n')
                self.assertIn('stale or incomplete candidate fingerprint', self.errors())
                path.write_bytes(saved)
        template = self.app / 'docker-compose.yml.template'
        template.write_text('changed deployment generator input\n')
        self.assertIn('stale or incomplete candidate fingerprint', self.errors())
        template.unlink()
        hook = self.app / 'hooks/install'
        hook.chmod(0o755)
        self.assertNotEqual(contract.candidate_fingerprint(self.app)['tree_sha256'], original['tree_sha256'])
        self.assertIn('stale or incomplete candidate fingerprint', self.errors())

    def test_symlink_target_changes_invalidate_tree_without_following_external_data(self):
        link = self.app / 'link'
        link.symlink_to('/nonexistent-first-target')
        original = contract.package_tree_hash(self.app)
        link.unlink()
        link.symlink_to('/nonexistent-second-target')
        self.assertNotEqual(contract.package_tree_hash(self.app), original)

    def test_git_clone_and_archive_fingerprints_match_despite_umask_permissions(self):
        (self.app / 'hooks/install').chmod(0o755)
        (self.app / 'script-link').symlink_to('hooks/install')
        self.initialize_git()
        expected = contract.candidate_fingerprint(self.app)
        archive_temp = tempfile.TemporaryDirectory()
        self.addCleanup(archive_temp.cleanup)
        archive = Path(archive_temp.name)
        with tarfile.open(fileobj=io.BytesIO(self.git('archive', '--format=tar', 'HEAD'))) as tar:
            tar.extractall(archive, filter='data')
        archive_app = archive / self.app.name
        (archive_app / 'umbrel-app.yml').chmod(0o600)
        (archive_app / 'docker-compose.yml').chmod(0o640)
        (archive_app / 'hooks/install').chmod(0o700)
        (archive_app / 'empty-directory').mkdir(mode=0o700)
        self.assertEqual(contract.package_git_state(archive_app)['source'], 'filesystem')
        self.assertEqual(contract.candidate_fingerprint(archive_app), expected)

    def test_ignored_generated_cache_and_nonexecutable_permission_changes_keep_receipt_valid(self):
        self.initialize_git()
        expected = self.receipt['candidate']
        cache = self.app / '__pycache__'
        cache.mkdir()
        (cache / 'generated.cpython-313.pyc').write_bytes(b'generated cache')
        (self.app / 'extra.pyc').write_bytes(b'generated cache')
        (self.app / 'umbrel-app.yml').chmod(0o600)
        (self.app / 'docker-compose.yml').chmod(0o640)
        self.assertEqual(contract.candidate_fingerprint(self.app), expected)
        self.assertEqual(contract.package_git_state(self.app)['untracked_source'], [])
        self.assertEqual(self.errors(), [])

    def test_fallback_cache_and_empty_directories_do_not_define_a_git_package(self):
        expected = contract.candidate_fingerprint(self.app)
        cache = self.app / '__pycache__'
        cache.mkdir()
        (cache / 'generated.pyc').write_bytes(b'cache')
        (self.app / 'empty-directory').mkdir()
        self.assertEqual(contract.candidate_fingerprint(self.app), expected)

    def test_untracked_source_is_reported_and_blocks_readiness_until_packaged(self):
        self.initialize_git()
        expected = self.receipt['candidate']
        new_source = self.app / 'new-function.py'
        new_source.write_text('new packaged functionality\n')
        self.assertEqual(contract.candidate_fingerprint(self.app), expected)
        state = contract.package_git_state(self.app)
        self.assertEqual(state['source'], 'git')
        self.assertEqual(len(state['head']), 40)
        self.assertEqual(len(state['head_app_tree']), 40)
        self.assertEqual(state['untracked_source'], [self.app.name + '/new-function.py'])
        self.assertIn('untracked package source is not part of the published Git candidate', self.errors())
        self.git('add', self.app.name + '/new-function.py')
        self.assertEqual(contract.package_git_state(self.app)['untracked_source'], [])
        self.assertIn('stale or incomplete candidate fingerprint', self.errors())

    def test_tracked_working_changes_deleted_files_and_executable_drift_are_bound(self):
        (self.app / 'docker-compose.yml.template').write_text(yaml.safe_dump(compose()))
        (self.app / 'script-link').symlink_to('hooks/install')
        self.initialize_git()
        expected = contract.package_tree_hash(self.app)
        for filename in ('umbrel-app.yml', 'docker-compose.yml', 'docker-compose.yml.template', 'hooks/install'):
            with self.subTest(file=filename):
                path = self.app / filename
                saved = path.read_bytes()
                path.write_bytes(saved + b'\n# modified working tree\n')
                self.assertNotEqual(contract.package_tree_hash(self.app), expected)
                self.assertIn(self.app.name + '/' + filename,
                              contract.package_git_state(self.app)['tracked_changes'])
                path.write_bytes(saved)
        hook = self.app / 'hooks/install'
        hook.chmod(0o755)
        self.assertNotEqual(contract.package_tree_hash(self.app), expected)
        hook.chmod(0o644)
        link = self.app / 'script-link'
        link.unlink()
        link.symlink_to('docker-compose.yml')
        self.assertNotEqual(contract.package_tree_hash(self.app), expected)
        link.unlink()
        link.symlink_to('hooks/install')
        hook.unlink()
        self.assertNotEqual(contract.package_tree_hash(self.app), expected)

    def test_receipt_images_and_package_version_are_bound_even_if_hashes_are_copied(self):
        for field, value in (('package_version', 'old'), ('images', {'app': 'old-image'}), ('manifest_sha256', '0' * 64)):
            receipt = copy.deepcopy(self.receipt)
            receipt['candidate'][field] = value
            self.assertIn('stale or incomplete candidate fingerprint', self.errors(receipt))

    def test_pass_labels_without_observation_and_artifact_do_not_count(self):
        for field, value in (('artifacts', []), ('observation', ''), ('observation', None)):
            receipt = copy.deepcopy(self.receipt)
            receipt['checks']['install'][field] = value
            self.assertTrue(any(error.startswith('install:') for error in self.errors(receipt)))

    def test_missing_tampered_and_escaping_artifacts_fail(self):
        for path in ('missing.log', '../outside.log', str(self.evidence / 'fixture.log')):
            receipt = copy.deepcopy(self.receipt)
            receipt['checks']['install']['artifacts'][0]['path'] = path
            self.assertTrue(any(error.startswith('install:') for error in self.errors(receipt)))
        (self.evidence / 'fixture.log').write_text('tampered\n')
        self.assertTrue(any('hash mismatch' in error for error in self.errors()))

    def test_current_static_blocker_cannot_be_overridden_by_complete_runtime_receipt(self):
        value = compose()
        value['services']['app']['depends_on'] = ['app_proxy']
        (self.app / 'docker-compose.yml').write_text(yaml.safe_dump(value))
        self.receipt['candidate'] = contract.candidate_fingerprint(self.app)
        self.assertTrue(any('static blocker:' in error for error in self.errors()))

    def test_native_fumbrel_pass_receipt_is_rejected_without_becoming_applicable(self):
        fumbrel = self.root / 'willitmod-dev-fumbrel'
        self.app.rename(fumbrel)
        self.app = fumbrel
        (fumbrel / 'umbrel-app.yml').write_text(yaml.safe_dump({'id': fumbrel.name, 'version': '1.2.3-dev'}))
        self.target = {'os': '5tratumos', 'version': '0.8.31', 'architecture': 'amd64'}
        self.receipt.update(app_id=fumbrel.name, candidate=contract.candidate_fingerprint(fumbrel),
                            target=self.target.copy())
        self.assertTrue(any('target is not applicable' in error for error in self.errors()))
        receipts = self.evidence / 'synthetic-receipts.json'
        receipts.write_text(json.dumps([self.receipt]))
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            code = contract.main(['--root', str(self.root), '--target', '5tratumos:0.8.31:amd64',
                                  '--receipts', str(receipts), '--evidence-root', str(self.evidence)])
        self.assertEqual(code, 1)
        item = json.loads(output.getvalue())['apps'][0]['runtime_readiness'][0]
        self.assertFalse(item['applicable'])
        self.assertEqual(item['status'], 'not_applicable')
        self.assertTrue(item['errors'])

    def bind_app_lock(self, lock):
        model = contract.read_yaml(self.app / 'docker-compose.yml')
        model['services']['app']['image'] = lock['reference']
        (self.app / 'docker-compose.yml').write_text(yaml.safe_dump(model))
        self.qualification['images']['app'] = lock
        self.receipt['runtime_images']['app'] = self.fixture_observation('bound-app', lock)
        self.refresh_qualification()

    def test_old_receipts_and_missing_independent_locks_cannot_qualify(self):
        self.receipt['schema_version'] = 1
        self.assertTrue(any('schema_version must be 2' in error for error in self.errors()))
        errors = contract.readiness_errors(self.app, self.receipt, self.target, self.evidence)
        self.assertIn('independent immutable qualification lock required', errors)

    def test_every_image_and_execution_observation_must_be_covered_exactly(self):
        for field in ('images', 'builds'):
            qualification = copy.deepcopy(self.qualification)
            qualification[field] = {}
            if field == 'builds':
                qualification[field]['unrelated'] = {}
            errors = contract.readiness_errors(self.app, self.receipt, self.target, self.evidence, qualification)
            self.assertTrue(any('must cover exactly' in error for error in errors))
        for value in ({}, {'app': self.receipt['runtime_images']['app'], 'extra': {}}):
            receipt = copy.deepcopy(self.receipt)
            receipt['runtime_images'] = value
            self.assertTrue(any('observations must cover exactly' in error for error in self.errors(receipt)))

    def test_mutable_recipe_tag_blocks_promotion_even_with_a_recorded_digest(self):
        model = contract.read_yaml(self.app / 'docker-compose.yml')
        model['services']['app']['image'] = 'example/app:1'
        (self.app / 'docker-compose.yml').write_text(yaml.safe_dump(model))
        self.refresh_qualification()
        self.assertTrue(any('mutable recipe image reference blocks promotion' in error for error in self.errors()))

    def test_raw_index_must_select_child_and_child_must_select_config(self):
        lock = copy.deepcopy(self.qualification['images']['app'])
        bad_index = self.json_artifact('unrelated-index', {'schemaVersion': 2, 'manifests': [
            {'digest': 'sha256:' + '0' * 64, 'platform': {'os': 'linux', 'architecture': 'amd64'}}]})
        lock.update(index_artifact=bad_index, index_digest='sha256:' + bad_index['sha256'])
        lock['reference'] = 'example/app:1@' + lock['index_digest']
        self.bind_app_lock(lock)
        self.assertTrue(any('index does not select locked target platform manifest' in error for error in self.errors()))
        lock = self.fixture_lock('wrong-config-link', 'example/app:1')
        other_config = self.json_artifact('unrelated-config', {'os': 'linux', 'architecture': 'amd64', 'different': True})
        lock.update(config_artifact=other_config, config_digest='sha256:' + other_config['sha256'])
        self.bind_app_lock(lock)
        self.assertTrue(any('manifest does not select locked config' in error for error in self.errors()))

    def test_config_architecture_and_artifact_bytes_cannot_be_substituted(self):
        lock = self.fixture_lock('wrong-architecture', 'example/app:1', config_architecture='arm64')
        self.bind_app_lock(lock)
        self.assertTrue(any('config OS/architecture mismatch' in error for error in self.errors()))
        lock = self.fixture_lock('tamper', 'example/app:1')
        self.bind_app_lock(lock)
        (self.evidence / lock['config_artifact']['path']).write_text('{}')
        self.assertTrue(any('artifact missing or hash mismatch' in error for error in self.errors()))

    def test_nonobject_oci_artifacts_fail_closed_even_when_their_hashes_match(self):
        for field, digest_field in (('index_artifact', 'index_digest'),
                                    ('platform_artifact', 'platform_digest'),
                                    ('config_artifact', 'config_digest')):
            for value in (None, [], 'scalar', 42, True):
                with self.subTest(artifact=field, value=value):
                    lock = self.fixture_lock('nonobject-' + field, 'example/app:1')
                    artifact = self.json_artifact('nonobject-' + field, value)
                    lock.update({field: artifact, digest_field: 'sha256:' + artifact['sha256']})
                    lock['reference'] = 'example/app:1@' + lock['index_digest']
                    errors = []
                    self.assertIsNone(contract.oci_lock_binding(lock, self.target, self.evidence, 'fixture', errors))
                    self.assertTrue(any('must be JSON objects' in error for error in errors))
                    self.bind_app_lock(lock)
                    self.assertTrue(any('must be JSON objects' in error for error in self.errors()))

    def test_docker_classic_and_containerd_identity_models_are_accepted_only_with_ancestry(self):
        lock = self.qualification['images']['app']
        for classic in (False, True):
            self.receipt['runtime_images']['app'] = self.fixture_observation('identity-' + str(classic), lock, classic=classic)
            self.assertEqual(self.errors(), [])
        observed = self.receipt['runtime_images']['app']
        artifact = observed['image_inspect_artifact']
        value = json.loads((self.evidence / artifact['path']).read_text())
        value[0]['Id'] = 'sha256:' + 'f' * 64
        observed['image_id'] = value[0]['Id']
        observed['image_inspect_artifact'] = self.json_artifact('foreign-image-inspect', value)
        self.assertTrue(any('image ID is not' in error for error in self.errors()))

    def test_claimed_execution_requires_inspect_reference_container_and_started_state(self):
        observed = self.receipt['runtime_images']['app']
        value = json.loads((self.evidence / observed['container_inspect_artifact']['path']).read_text())
        value[0]['State'].update(Status='created', StartedAt='0001-01-01T00:00:00Z')
        value[0]['Config']['Image'] = 'different:mutable'
        observed['container_inspect_artifact'] = self.json_artifact('never-executed-container', value)
        self.assertTrue(any('inspect does not show successful image execution' in error for error in self.errors()))
        self.assertTrue(any('container inspect reference mismatch' in error for error in self.errors()))

    def test_malformed_inspect_fields_and_missing_repository_digest_fail_closed(self):
        observed = self.receipt['runtime_images']['app']
        original = json.loads((self.evidence / observed['image_inspect_artifact']['path']).read_text())
        for field, value in (('Id', {}), ('Id', []), ('RepoDigests', None), ('RepoDigests', 7)):
            with self.subTest(field=field, value=value):
                inspect = copy.deepcopy(original)
                inspect[0][field] = value
                observed['image_inspect_artifact'] = self.json_artifact('malformed-inspect', inspect)
                self.assertTrue(self.errors())

    def install_fixture_build(self):
        context = self.app / 'data/peercoind'
        context.mkdir(parents=True)
        base = self.fixture_lock('base', 'example/debian:bookworm')
        dockerfile = context / 'Dockerfile'
        dockerfile.write_text('FROM ' + base['reference'] + '\nARG PEERCOIN_VERSION=0.15.1ppc\nARG PEERCOIN_LINUX_BUILD=1af7509666a7\n')
        (context / 'wrapper.sh').write_text('synthetic build input, no execution\n')
        archive_path = self.evidence / 'synthetic-archive.tar.gz'
        archive_path.write_bytes(b'Synthetic test archive bytes, not a downloaded Peercoin release.')
        archive = {'path': archive_path.name, 'sha256': contract.sha256(archive_path),
                   'url': 'https://github.com/peercoin/peercoin/releases/download/v0.15.1ppc/peercoin-1af7509666a7-x86_64-linux-gnu.tar.gz'}
        result_lock = self.fixture_lock('local-result', 'example/unused:1')
        result = {k: result_lock[k] for k in ('platform', 'config_digest', 'config_artifact')}
        result['image_id'] = result['config_digest']
        lock = {'context_sha256': contract.build_context_hash(context), 'dockerfile_sha256': contract.sha256(dockerfile),
                'archive': archive, 'base': base, 'result': result}
        self.qualification['builds']['node'] = lock
        model = contract.read_yaml(self.app / 'docker-compose.yml')
        model['services']['node'] = {'build': {'context': '${APP_DATA_DIR}/data/peercoind'}}
        (self.app / 'docker-compose.yml').write_text(yaml.safe_dump(model))
        observed = self.fixture_observation('local-build', result, local_build=True)
        observed['build_inputs_sha256'] = contract.canonical_sha256({k: lock[k] for k in
                                        ('context_sha256', 'dockerfile_sha256', 'archive', 'base')})
        observed['build_evidence_artifact'] = {'path': 'fixture.log', 'sha256': contract.sha256(self.evidence / 'fixture.log')}
        self.receipt['runtime_images']['node'] = observed
        self.refresh_qualification()
        return context, lock

    def test_local_build_cannot_be_omitted_and_exact_inputs_result_and_execution_are_bound(self):
        context, lock = self.install_fixture_build()
        self.assertEqual(self.errors(), [])
        saved = self.qualification['builds'].pop('node')
        self.assertTrue(any('build locks must cover exactly' in error for error in self.errors()))
        self.qualification['builds']['node'] = saved
        (context / 'wrapper.sh').write_text('changed build input')
        self.refresh_qualification()
        self.assertTrue(any('stale Dockerfile/build context inputs' in error for error in self.errors()))
        lock['context_sha256'] = contract.build_context_hash(context)
        self.refresh_qualification()
        self.assertTrue(any('not bound to exact build inputs' in error for error in self.errors()))
        lock['result']['image_id'] = 'sha256:' + '0' * 64
        self.refresh_qualification()
        self.assertTrue(any('local image ID must bind' in error for error in self.errors()))

    def test_local_build_requires_exact_archive_and_a_pinned_base(self):
        context, lock = self.install_fixture_build()
        (self.evidence / lock['archive']['path']).write_bytes(b'tampered archive')
        self.assertTrue(any('source archive: artifact missing or hash mismatch' in error for error in self.errors()))
        lock['archive']['url'] = 'https://example.invalid/different-release.tar.gz'
        self.assertTrue(any('source archive URL does not match' in error for error in self.errors()))
        dockerfile = context / 'Dockerfile'
        dockerfile.write_text(dockerfile.read_text().replace(lock['base']['reference'], 'debian:bookworm-slim'))
        lock.update(context_sha256=contract.build_context_hash(context), dockerfile_sha256=contract.sha256(dockerfile))
        self.refresh_qualification()
        self.assertTrue(any('mutable Dockerfile base reference blocks promotion' in error for error in self.errors()))

    def test_ignored_generated_build_inputs_are_bound_even_when_git_candidate_is_unchanged(self):
        context, _lock = self.install_fixture_build()
        self.initialize_git()
        before = contract.candidate_fingerprint(self.app)
        cache = context / '__pycache__'
        cache.mkdir()
        (cache / 'generated.pyc').write_bytes(b'ignored but actual Docker context input')
        self.assertEqual(contract.package_git_state(self.app)['untracked_source'], [])
        self.assertEqual(contract.candidate_fingerprint(self.app), before)
        self.assertTrue(any('stale Dockerfile/build context inputs' in error for error in self.errors()))

    def test_actual_build_context_binds_file_modes_empty_directories_and_symlinks(self):
        context, _lock = self.install_fixture_build()
        initial = contract.build_context_hash(context)
        path = context / 'wrapper.sh'
        original_mode = path.stat().st_mode & 0o777
        path.chmod(0o755)
        self.assertNotEqual(contract.build_context_hash(context), initial)
        path.chmod(original_mode)
        (context / 'empty-input-directory').mkdir()
        self.assertNotEqual(contract.build_context_hash(context), initial)
        (context / 'empty-input-directory').rmdir()
        (context / 'input-link').symlink_to('wrapper.sh')
        first_link = contract.build_context_hash(context)
        (context / 'input-link').unlink()
        (context / 'input-link').symlink_to('Dockerfile')
        self.assertNotEqual(contract.build_context_hash(context), first_link)

    def test_input_changing_compose_build_options_are_rejected_instead_of_using_defaults(self):
        self.install_fixture_build()
        original = contract.read_yaml(self.app / 'docker-compose.yml')
        for option, value in (('args', {'PEERCOIN_VERSION': '9.9.9'}),
                              ('args', ['TARGETARCH=arm64']), ('target', 'different-stage'),
                              ('additional_contexts', {'extra': '/other'}),
                              ('platforms', ['linux/arm64']), ('dockerfile_inline', 'FROM scratch'),
                              ('secrets', ['build-secret'])):
            with self.subTest(option=option, value=value):
                model = copy.deepcopy(original)
                model['services']['node']['build'][option] = value
                (self.app / 'docker-compose.yml').write_text(yaml.safe_dump(model))
                self.refresh_qualification()
                self.assertTrue(any('unsupported Compose build options' in error for error in self.errors()))

    def test_build_service_with_a_mutable_declared_image_cannot_qualify(self):
        self.install_fixture_build()
        model = contract.read_yaml(self.app / 'docker-compose.yml')
        model['services']['node']['image'] = 'example/peercoin:mutable'
        (self.app / 'docker-compose.yml').write_text(yaml.safe_dump(model))
        self.refresh_qualification()
        self.assertTrue(any('mutable recipe image reference blocks promotion' in error for error in self.errors()))

    def install_fixture_native(self):
        self.native_root = self.root / 'synthetic-native-release'
        recipe_dir = self.native_root / 'apps/axebtc'
        recipe_dir.mkdir(parents=True)
        (self.native_root / 'bin').mkdir()
        (self.native_root / 'daemon').mkdir()
        (self.native_root / 'bin/5tratumos').write_text('synthetic importer fixture\n')
        (self.native_root / 'daemon/5tratumosd.py').write_text('synthetic renderer fixture\n')
        (self.native_root / 'build.json').write_text(json.dumps({'channel': 'stable', 'repo': 'synthetic-fixture',
                                                               'tag': 'v0.8.31', 'built_at': '2026-10-14T00:00:00Z'}))
        (self.native_root / 'host.json').write_text(json.dumps({'os': '5tratumos', 'version': '0.8.31',
                                                              'architecture': 'amd64'}))
        lock = self.fixture_lock('native', 'example/native-app:2')
        (recipe_dir / 'docker-compose.yml').write_text(yaml.safe_dump({'services': {'native-web': {'image': lock['reference']}}}))
        self.target = {'os': '5tratumos', 'version': '0.8.31', 'architecture': 'amd64'}
        self.qualification['images'] = {'native-web': lock}
        self.receipt['runtime_images'] = {'native-web': self.fixture_observation('native', lock)}
        self.refresh_qualification()

    def test_native_receipt_requires_independent_materialized_recipe_importer_renderer_and_build(self):
        self.install_fixture_native()
        self.assertEqual(self.errors(), [])
        saved = self.native_root
        self.native_root = None
        self.assertTrue(any('--native-root' in error for error in self.errors()))
        self.native_root = saved
        for name in ('bin/5tratumos', 'daemon/5tratumosd.py', 'build.json', 'host.json', 'apps/axebtc/docker-compose.yml'):
            path = self.native_root / name
            original = path.read_bytes()
            if name in ('build.json', 'host.json'):
                path.write_text(json.dumps({**json.loads(original), 'changed_capture': True}))
            elif name.endswith('.yml'):
                path.write_bytes(original + b'\n# changed imported native recipe\n')
            else:
                path.write_bytes(original + b'changed\n')
            self.assertTrue(any('deployment recipe/importer/renderer/build hashes mismatch' in error for error in self.errors()), name)
            path.write_bytes(original)

    def test_native_umbrel_recipe_reuse_and_different_release_or_architecture_are_rejected(self):
        self.install_fixture_native()
        self.qualification['deployment']['recipe_sha256'] = contract.sha256(self.app / 'docker-compose.yml')
        self.receipt['deployment'] = self.qualification['deployment'].copy()
        self.receipt['qualification_sha256'] = contract.canonical_sha256(self.qualification)
        self.assertTrue(any('deployment recipe/importer/renderer/build hashes mismatch' in error for error in self.errors()))
        (self.native_root / 'build.json').write_text(json.dumps({'channel': 'stable', 'repo': 'synthetic-fixture',
                                                               'tag': 'v0.8.32-review3', 'built_at': '2026-10-14T00:00:00Z'}))
        self.assertTrue(any('native build tag does not match exact target release' in error for error in self.errors()))
        (self.native_root / 'build.json').write_text(json.dumps({'tag': 'v0.8.31'}))
        for field, value in (('version', '0.8.32-review3'), ('architecture', 'arm64'), ('os', 'umbrel')):
            host = {'os': '5tratumos', 'version': '0.8.31', 'architecture': 'amd64', field: value}
            (self.native_root / 'host.json').write_text(json.dumps(host))
            self.assertTrue(any('captured native host OS/version/architecture does not match' in error for error in self.errors()))

    def test_native_real_build_schema_requires_tag_and_a_separate_captured_host(self):
        self.install_fixture_native()
        self.assertEqual(self.errors(), [])
        (self.native_root / 'host.json').unlink()
        self.assertTrue(any('captured host.json' in error for error in self.errors()))
        (self.native_root / 'host.json').write_text(json.dumps(self.target))
        (self.native_root / 'build.json').write_text(json.dumps({'version': '0.8.31', 'architecture': 'amd64'}))
        self.assertTrue(any('native build tag does not match exact target release' in error for error in self.errors()))

    def test_empty_or_unexecutable_materialized_native_graph_cannot_qualify(self):
        self.install_fixture_native()
        for services in ({}, {'native-web': {}}, {'native-web': None}, {'app_proxy': {'environment': {}}}):
            with self.subTest(services=services):
                recipe = self.native_root / 'apps/axebtc/docker-compose.yml'
                recipe.write_text(yaml.safe_dump({'services': services}))
                self.qualification['images'] = {}
                self.qualification['builds'] = {}
                self.receipt['runtime_images'] = {}
                self.refresh_qualification()
                self.assertTrue(any('nonempty valid mapping' in error or 'no explicit runtime image/build' in error
                                    for error in self.errors()))

    def test_malformed_targets_return_errors_without_attempting_deployment_resolution(self):
        for target in ({'os': 'umbrel'}, dict(self.target, version=None),
                       dict(self.target, architecture=[]), dict(self.target, version='invalid')):
            with self.subTest(target=target):
                self.assertTrue(self.errors(target=target))


if __name__ == '__main__':
    unittest.main()
