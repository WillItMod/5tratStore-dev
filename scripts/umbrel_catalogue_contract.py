#!/usr/bin/env python3
"""Static DEV catalogue contracts and fail-closed runtime evidence validation.

Static contracts follow the verified getumbrel/umbrel 1.7.0-1.7.4 app.ts
volume migration, and 2.0.0 legacy-compat/app-script and lan-ingress.ts.
They are not runtime installation, authentication, or mining verification.

A schema_version=2 readiness receipt has app_id, candidate (the exact result
of candidate_fingerprint), target {os, version, architecture}, verification
"runtime", historical false, and checks. Each required check must contain
status "pass", a nonempty observation, and artifacts [{path, sha256}].
Artifact paths are relative to the supplied evidence root. This script checks
the receipt's coverage and provenance binding, not the truth of its observations.
Only a test runner or reviewer with actual runtime evidence may create receipts.
Target OS names are exactly "umbrel" and "5tratumos". Fumbrel is Umbrel-only;
its native 5tratumOS target is not applicable and cannot accept a pass receipt.

Promotion also requires an independently supplied schema_version=1 qualification
lock with app_id, candidate, target, deployment, images and builds. The receipt
must echo deployment, bind qualification_sha256 to canonical JSON of that lock,
and supply runtime_images for exactly every explicit runtime image/build service.
Each images[service] lock has a digest-pinned reference, platform, index_digest,
platform_digest, config_digest and index/platform/config_artifact {path, sha256}.
Raw OCI ancestry and config architecture are verified offline. Mutable recipe
references block promotion even if a receipt claims their current digest.

Each runtime_images[service] observation has reference, platform, index_digest,
platform_digest, config_digest, image_id, container_image_id, container_id,
executed=true, and image/container_inspect_artifact {path, sha256}. Inspect JSON
must agree with these fields and the lock; Docker's config/index ID models are
accepted only when they belong to the proved immutable OCI ancestry. This checks
metadata consistency, not whether an observation or artifact was honestly made.

Local builds require builds[service] context_sha256, dockerfile_sha256, archive
{url,path,sha256}, a pinned base OCI lock and result. A local result may have
only a config_digest/config_artifact and immutable image_id equal to that config
digest; registry/index results require the full OCI lock. All actual build inputs
are recomputed. Context hashing conservatively includes all actual files, modes,
directories and symlinks, even ignored/generated files; it does not consult Git
or filter .dockerignore. Only context/dockerfile Compose build options are
supported. Other input-changing build options fail closed instead of silently
using Dockerfile defaults. Current PPC's unpinned Debian base remains a blocker.
Their runtime observation also binds build_inputs_sha256 to canonical JSON of
the context/Dockerfile/archive/base input fields and a build_evidence_artifact.

Native targets require --native-root containing the actual materialized imported
apps/<native_id>/docker-compose.yml, bin/5tratumos, daemon/5tratumosd.py and
the unchanged real build.json {channel,repo,tag,built_at}, plus captured host.json
{os,version,architecture} using OCI architecture names. The recipe is an actual
materialized deployment export, not repository defaults. The exact release is
parsed from build.json tag (e.g. v0.8.31), and host.json independently records the
reported OS/version/platform. Every snapshot hash is recomputed; no real release
metadata is rewritten to add fields. Umbrel targets use the current start template.
"""

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import subprocess
import sys

import yaml


MINING_APP_IDS = frozenset('willitmod-dev-' + name for name in (
    'btc', 'bch', 'axebch2', 'bc2', 'dgb', 'xec', 'ppc', 'powpow',
    'fracattack', '5tratsmack',
))
REQUIRED_CHECKS = (
    'install', 'update', 'start', 'restart', 'persistent_data',
    'ui_authentication', 'network_dependencies', 'app_functional',
)
ARCHITECTURES = frozenset(('amd64', 'arm64', 'arm/v7'))
TARGET_OSES = frozenset(('umbrel', '5tratumos'))
NATIVE_APP_IDS = MINING_APP_IDS | frozenset('willitmod-dev-' + name for name in (
    'axebench', 'axelive', 'axemig',
))
NATIVE_IDS = dict(zip(('willitmod-dev-' + name for name in (
    'btc', 'bch', 'axebch2', 'bc2', 'dgb', 'xec', 'ppc', 'powpow', 'fracattack',
    '5tratsmack', 'axebench', 'axelive', 'axemig')),
    ('axebtc', 'axebch', 'axebch2', 'axebc2', 'axedgb', 'axexec', 'axeppc',
     'axepowpow', 'axefracattack', '5tratsmack', 'axebench', 'axelive', 'axemig')))
DIGEST = re.compile(r'^sha256:[0-9a-f]{64}$')
PINNED_REFERENCE = re.compile(r'^([^\s@]+)@(sha256:[0-9a-f]{64})$')


def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def canonical_sha256(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True,
                                    separators=(',', ':')).encode()).hexdigest()


def read_yaml(path):
    value = yaml.safe_load(Path(path).read_text())
    if not isinstance(value, dict):
        raise ValueError(f'{Path(path).name}: expected a YAML mapping')
    return value


def inventory(root):
    """Match Umbrel's app-repository.ts one-directory manifest discovery."""
    return [path.parent for path in sorted(Path(root).glob('*/umbrel-app.yml'))]


def target_applicability(app_id, target):
    """Explicit scope, not a claim of compatibility or runtime readiness."""
    if not isinstance(target, dict) or not isinstance(target.get('os'), str) or target['os'] not in TARGET_OSES:
        raise ValueError('target OS must be exactly umbrel or 5tratumos')
    if target['os'] == '5tratumos':
        if app_id == 'willitmod-dev-fumbrel':
            return {'applicable': False, 'status': 'not_applicable',
                    'reason': 'Fumbrel is scoped to Umbrel only; no native 5tratumOS package is required'}
        if app_id not in NATIVE_APP_IDS:
            raise ValueError(f'Native target applicability is not defined for {app_id}')
    return {'applicable': True}


def git_package_context(app_dir):
    """Locate the package's Git root without changing its repository."""
    app_dir = Path(app_dir).resolve()
    result = subprocess.run(['git', '-C', str(app_dir), 'rev-parse', '--show-toplevel'],
                            capture_output=True, text=True, timeout=15)
    if result.returncode != 0:
        return None
    root = Path(result.stdout.strip()).resolve()
    return root, app_dir.relative_to(root).as_posix()


def git_output(root, *args):
    return subprocess.run(['git', '-C', str(root), *args], capture_output=True,
                          check=True, timeout=15).stdout


def generated_cache(path):
    return '__pycache__' in path.parts or path.suffix in ('.pyc', '.pyo')


def package_git_state(app_dir):
    """Report publication provenance separately from portable package identity.

    Untracked source is not in a Git archive. It must be added to the candidate
    before runtime evidence can count. Tracked working changes remain hash-bound.
    HEAD and dirty state are diagnostic metadata, not part of a portable archive
    fingerprint, since archives and deployed copies have no Git database.
    """
    context = git_package_context(app_dir)
    if context is None:
        return {'source': 'filesystem', 'head': None, 'head_app_tree': None,
                'tracked_changes': [], 'untracked_source': []}
    root, app_relative = context
    head_result = subprocess.run(['git', '-C', str(root), 'rev-parse', '--verify', 'HEAD'],
                                 capture_output=True, text=True, timeout=15)
    head = head_result.stdout.strip() if head_result.returncode == 0 else None
    tree_result = subprocess.run(['git', '-C', str(root), 'rev-parse', '--verify',
                                 f'HEAD:{app_relative}'], capture_output=True, text=True, timeout=15)
    untracked = git_output(root, 'ls-files', '--others', '--exclude-standard', '-z', '--', app_relative)
    changes = git_output(root, 'diff', '--name-only', '-z', 'HEAD', '--', app_relative) if head else b''
    return {'source': 'git', 'head': head,
            'head_app_tree': tree_result.stdout.strip() if tree_result.returncode == 0 else None,
            'tracked_changes': [os.fsdecode(name) for name in changes.split(b'\0') if name],
            'untracked_source': [os.fsdecode(name) for name in untracked.split(b'\0')
                                 if name and not generated_cache(Path(os.fsdecode(name)))]}


def package_tree_hash(app_dir):
    """Bind portable Git package entries using their actual working bytes.

    Git archives contain tracked files and symlinks, not empty directories or
    ignored generated caches. Only executable bits are portable Git permissions;
    owner/group/read/write bits vary with umask and do not define the package.
    Track executable drift from the index as well as content/target changes.
    For archive/fixture directories without Git, hash regular files and symlinks
    with canonical Git modes, excluding generated Python caches. Never follow
    symlinks. Git publication metadata is reported by package_git_state.
    """
    app_dir = Path(app_dir).resolve()
    context = git_package_context(app_dir)
    paths = []
    if context is not None:
        root, app_relative = context
        index = git_output(root, 'ls-files', '--stage', '-z', '--', app_relative)
        for record in index.split(b'\0'):
            if not record:
                continue
            metadata, relative_name = record.split(b'\t', 1)
            mode, _blob, stage = metadata.decode().split()
            if stage != '0':
                raise ValueError('Unmerged package index entry')
            paths.append((root / os.fsdecode(relative_name), mode))
    else:
        paths = [(path, None) for path in app_dir.rglob('*')
                 if not generated_cache(path.relative_to(app_dir)) and
                 (path.is_symlink() or not path.is_dir())]
    entries = []
    for path, index_mode in sorted(paths, key=lambda item: item[0].relative_to(app_dir).as_posix()):
        relative = path.relative_to(app_dir).as_posix()
        try:
            info = path.lstat()
        except FileNotFoundError:
            entries.append({'path': relative, 'mode': index_mode, 'type': 'missing'})
            continue
        executable = bool(info.st_mode & 0o111)
        actual_mode = '120000' if stat.S_ISLNK(info.st_mode) else '100755' if executable else '100644'
        entry = {'path': relative, 'mode': index_mode or actual_mode}
        if path.is_symlink():
            entry.update(type='symlink', target=os.readlink(path))
        elif path.is_file():
            entry.update(type='file', sha256=sha256(path))
            if index_mode in ('100644', '100755') and (index_mode == '100755') != executable:
                entry['executable_drift'] = True
        else:
            raise ValueError(f'Unsupported package entry: {entry["path"]}')
        entries.append(entry)
    return hashlib.sha256(json.dumps(entries, sort_keys=True,
                                    separators=(',', ':')).encode()).hexdigest()


def candidate_fingerprint(app_dir):
    app_dir = Path(app_dir)
    manifest = read_yaml(app_dir / 'umbrel-app.yml')
    compose = read_yaml(app_dir / 'docker-compose.yml')
    services = compose.get('services', {})
    return {
        'app_id': app_dir.name,
        'package_version': str(manifest['version']),
        'manifest_sha256': sha256(app_dir / 'umbrel-app.yml'),
        'compose_sha256': sha256(app_dir / 'docker-compose.yml'),
        'tree_sha256': package_tree_hash(app_dir),
        'images': {name: service['image'] for name, service in services.items()
                   if isinstance(service, dict) and service.get('image')},
    }


def build_context_hash(context):
    """Bind actual Docker context inputs, including ignored/generated entries.

    This deliberately includes .dockerignore-excluded entries too, so an extra
    file can invalidate evidence but can never be omitted from the lock by Git.
    Filesystem modes matter here because Docker COPY retains input permissions.
    No symlink target is followed, and unsupported special entries fail closed.
    """
    context = Path(context).resolve()
    entries = []
    for path in sorted(context.rglob('*'), key=lambda item: item.relative_to(context).as_posix()):
        info = path.lstat()
        entry = {'path': path.relative_to(context).as_posix(),
                 'mode': stat.S_IMODE(info.st_mode)}
        if stat.S_ISLNK(info.st_mode):
            entry.update(type='symlink', target=os.readlink(path))
        elif stat.S_ISREG(info.st_mode):
            entry.update(type='file', sha256=sha256(path))
        elif stat.S_ISDIR(info.st_mode):
            entry.update(type='directory')
        else:
            raise ValueError(f'Unsupported Docker build context entry: {entry["path"]}')
        entries.append(entry)
    return canonical_sha256(entries)


def environment_record(value):
    if isinstance(value, dict):
        return {name: str(item) for name, item in value.items() if item is not None}
    if isinstance(value, list):
        return dict(item.split('=', 1) for item in value
                    if isinstance(item, str) and '=' in item)
    return {}


def expand_app_id(value, app_id):
    return re.sub(r'\$\{APP_ID\}|\$APP_ID\b', lambda _match: app_id, value)


def compose_contract_errors(compose, app_id, validate_gateway=True):
    """Check known install/start blockers, without claiming full compatibility."""
    errors = []
    services = compose.get('services')
    if not isinstance(services, dict) or not services:
        return ['compose.services: missing nonempty service mapping']
    runtime_services = {name: service for name, service in services.items()
                        if name != 'app_proxy'}
    for name, service in services.items():
        if not isinstance(service, dict):
            errors.append(f'{name}: expected service mapping')
            continue
        volumes = service.get('volumes')
        if volumes is not None and not isinstance(volumes, list):
            errors.append(f'{name}.volumes: expected list')
        elif volumes:
            for index, volume in enumerate(volumes):
                # 1.7.x calls volume?.replace(), including on app_proxy volumes.
                # Long-form Compose mounts are valid Docker syntax but fail there.
                if not isinstance(volume, str):
                    errors.append(f'{name}.volumes[{index}]: Umbrel 1.7.x '
                                  'requires string mount syntax')
        if name == 'app_proxy':
            continue
        dependencies = service.get('depends_on', [])
        if isinstance(dependencies, (list, dict)) and 'app_proxy' in dependencies:
            errors.append(f'{name}.depends_on: app_proxy is removed on Umbrel 2.0')
        for link in service.get('links', []) or []:
            if isinstance(link, str) and link.split(':', 1)[0] == 'app_proxy':
                errors.append(f'{name}.links: app_proxy is removed on Umbrel 2.0')
        mode = service.get('network_mode', '')
        if isinstance(mode, str) and mode.startswith(('service:', 'container:')):
            target = expand_app_id(mode.split(':', 1)[1], app_id)
            if target in ('app_proxy', f'{app_id}_app_proxy_1'):
                errors.append(f'{name}.network_mode: app_proxy is removed on Umbrel 2.0')
    proxy = services.get('app_proxy')
    if not validate_gateway or not isinstance(proxy, dict):
        return errors  # Native apps may legitimately have no legacy gateway.
    env = environment_record(proxy.get('environment'))
    host = expand_app_id(env.get('APP_HOST', '').strip(), app_id)
    matches = []
    for name, service in runtime_services.items():
        if not isinstance(service, dict):
            continue
        # These are the exact matches used in 2.0 lan-ingress.resolveAppTarget.
        # Network aliases alone are not part of its service-discovery branch.
        identities = (name, service.get('hostname'), service.get('container_name'),
                      f'{app_id}_{name}_1')
        if host and any(isinstance(value, str) and
                        expand_app_id(value, app_id) == host for value in identities):
            matches.append(name)
    if len(matches) != 1:
        errors.append(f'app_proxy.APP_HOST: expected one exact runtime service, '
                      f'hostname or container match, found {len(matches)} for {host!r}')
    port = env.get('APP_PORT', '').strip()
    if not port.isdigit() or not 1 <= int(port) <= 65535:
        errors.append('app_proxy.APP_PORT: expected integer from 1 through 65535')
    return errors


def app_contract_errors(app_dir):
    """Validate both preflight recipes, and the template used at Umbrel start.

    Official 1.7/2.0 template_app copies *.template over its output before
    Compose up. The initial app.ts parser still sees the unrendered base recipe,
    so both recipes need string mounts, but gateway discovery uses the template.
    """
    app_dir = Path(app_dir)
    errors = []
    template_exists = (app_dir / 'docker-compose.yml.template').exists()
    for name in ('docker-compose.yml', 'docker-compose.yml.template'):
        path = app_dir / name
        if path.exists():
            validate_gateway = name.endswith('.template') or not template_exists
            try:
                errors.extend(f'{name}: {error}' for error in compose_contract_errors(
                    read_yaml(path), app_dir.name, validate_gateway=validate_gateway))
            except (OSError, ValueError, yaml.YAMLError) as error:
                errors.append(f'{name}: {error}')
    return errors


def catalogue_contract(root):
    results = []
    for app_dir in inventory(root):
        errors = []
        try:
            manifest = read_yaml(app_dir / 'umbrel-app.yml')
            if manifest.get('id') != app_dir.name:
                errors.append('manifest.id does not match the app directory')
            errors.extend(app_contract_errors(app_dir))
            candidate = candidate_fingerprint(app_dir)
        except (OSError, ValueError, KeyError, yaml.YAMLError) as error:
            errors.append(str(error))
            candidate = None
        results.append({'app_id': app_dir.name, 'candidate': candidate,
                        'git_state': package_git_state(app_dir),
                        'static_contract_errors': errors})
    return results


def exports_contract_errors(app_dir):
    """Exercise only exports.sh with a fake docker; never access a real daemon."""
    exports = Path(app_dir) / 'exports.sh'
    if not exports.exists():
        return []
    probe = r'''
set -euo pipefail
docker() {
  case "${PROBE_MODE}:${!#}" in
    legacy:umbrel-auth) printf '%s\n' 'JWT_SECRET=contract-legacy-secret';;
    *) return 1;;
  esac
}
before_flags="$-"
before_options="$(set +o)"
source "$1"
[[ "$before_flags" == "$-" ]]
[[ "$before_options" == "$(set +o)" ]]
printf '%s' "${JWT_SECRET-unset}"
'''
    errors = []
    for mode, supplied, expected in (
        ('missing', None, 'unset'), ('legacy', None, 'contract-legacy-secret'),
        ('missing', 'contract-supplied-secret', 'contract-supplied-secret'),
        ('legacy', 'contract-supplied-secret', 'contract-supplied-secret'),
    ):
        env = {'PATH': os.environ.get('PATH', '/usr/bin:/bin'), 'PROBE_MODE': mode,
               'APP_ID': Path(app_dir).name, 'APP_DATA_DIR': str(Path(app_dir).resolve())}
        if supplied is not None:
            env['JWT_SECRET'] = supplied
        result = subprocess.run(['bash', '-c', probe, 'exports-contract', str(exports.resolve())],
                                env=env, capture_output=True, text=True, timeout=15)
        if result.returncode != 0 or result.stdout != expected:
            errors.append(f'exports.sh: strict-shell auth probe {mode}/'
                          f'{"supplied" if supplied else "missing"} failed '
                          f'(exit {result.returncode})')
    return errors


def checked_artifact(root, artifact, label, errors):
    if not isinstance(artifact, dict) or not isinstance(artifact.get('path'), str) or not re.fullmatch(r'[0-9a-f]{64}', str(artifact.get('sha256', ''))):
        errors.append(f'{label}: hash-linked artifact required')
        return None
    relative = Path(artifact['path'])
    path = (root / relative).resolve()
    if relative.is_absolute() or not path.is_relative_to(root) or path == root:
        errors.append(f'{label}: artifact must remain inside evidence root')
        return None
    if not path.is_file() or sha256(path) != artifact['sha256']:
        errors.append(f'{label}: artifact missing or hash mismatch')
        return None
    return path


def artifact_json(root, artifact, label, errors, digest=None):
    path = checked_artifact(root, artifact, label, errors)
    if path is None:
        return None
    if digest and 'sha256:' + artifact['sha256'] != digest:
        errors.append(f'{label}: artifact does not hash to locked OCI digest')
        return None
    try:
        return json.loads(path.read_bytes())
    except (ValueError, OSError):
        errors.append(f'{label}: invalid JSON artifact')
        return None


def platform_matches(value, target):
    if not isinstance(value, dict) or value.get('os') != 'linux':
        return False
    architecture, _, variant = target['architecture'].partition('/')
    if value.get('architecture') != architecture:
        return False
    actual_variant = value.get('variant', '')
    return actual_variant == variant if variant else actual_variant in ('', 'v8') if architecture == 'arm64' else not actual_variant


def oci_lock_binding(lock, target, root, label, errors):
    """Prove reference -> index -> target manifest -> target config ancestry."""
    if not isinstance(lock, dict):
        errors.append(f'{label}: immutable OCI lock required')
        return None
    reference = lock.get('reference', '')
    match = PINNED_REFERENCE.fullmatch(reference) if isinstance(reference, str) else None
    if not match or match[2] != lock.get('index_digest'):
        errors.append(f'{label}: reference must pin the exact index digest')
        return None
    if lock.get('platform') != 'linux/' + target['architecture']:
        errors.append(f'{label}: locked platform mismatch')
        return None
    for field in ('index_digest', 'platform_digest', 'config_digest'):
        if not isinstance(lock.get(field), str) or not DIGEST.fullmatch(lock[field]):
            errors.append(f'{label}: invalid {field}')
            return None
    index = artifact_json(root, lock.get('index_artifact'), label + ' index', errors, lock['index_digest'])
    manifest = artifact_json(root, lock.get('platform_artifact'), label + ' manifest', errors, lock['platform_digest'])
    config = artifact_json(root, lock.get('config_artifact'), label + ' config', errors, lock['config_digest'])
    if not isinstance(index, dict) or not isinstance(manifest, dict) or not isinstance(config, dict):
        errors.append(f'{label}: OCI index/manifest/config artifacts must be JSON objects')
        return None
    if 'manifests' in index:
        selected = [item for item in index['manifests'] if isinstance(item, dict) and platform_matches(item.get('platform'), target)] if isinstance(index['manifests'], list) else []
        if len(selected) != 1 or selected[0].get('digest') != lock['platform_digest']:
            errors.append(f'{label}: index does not select locked target platform manifest')
    elif lock['index_digest'] != lock['platform_digest']:
        errors.append(f'{label}: single manifest reference must equal platform digest')
    if not isinstance(manifest.get('config'), dict) or manifest['config'].get('digest') != lock['config_digest']:
        errors.append(f'{label}: platform manifest does not select locked config')
    if not platform_matches(config, target):
        # OCI ARMv7 configs can omit variant; the index must still attest v7.
        base_config = dict(config, variant=target['architecture'].partition('/')[2])
        if '/' not in target['architecture'] or config.get('variant') or not platform_matches(base_config, target):
            errors.append(f'{label}: config OS/architecture mismatch')
    return {key: lock.get(key) for key in ('reference', 'platform', 'index_digest', 'platform_digest', 'config_digest')}


def deployment_model(app_dir, target, native_root=None):
    app_dir = Path(app_dir).resolve()
    if target['os'] == 'umbrel':
        template = app_dir / 'docker-compose.yml.template'
        path = template if template.exists() else app_dir / 'docker-compose.yml'
        compose = read_yaml(path)
        deployment = {'os': 'umbrel', 'recipe_sha256': sha256(path)}
        # The inherited OS sidecar is outside explicit app image coverage.
        if target['version'].startswith('2.'):
            compose = dict(compose, services={name: value for name, value in compose.get('services', {}).items() if name != 'app_proxy'})
        return compose, deployment, app_dir
    if native_root is None:
        raise ValueError('native qualification requires independent materialized --native-root deployment/release files')
    root = Path(native_root).resolve()
    native_id = NATIVE_IDS.get(app_dir.name)
    if native_id is None:
        raise ValueError('native application mapping unavailable')
    files = {'recipe_sha256': root / 'apps' / native_id / 'docker-compose.yml',
             'importer_sha256': root / 'bin/5tratumos',
             'renderer_sha256': root / 'daemon/5tratumosd.py',
             'build_sha256': root / 'build.json',
             'host_sha256': root / 'host.json'}
    if any(not path.is_file() for path in files.values()):
        raise ValueError('native qualification requires actual materialized recipe, importer, renderer, build.json and captured host.json')
    try:
        build = json.loads(files['build_sha256'].read_text())
        host = json.loads(files['host_sha256'].read_text())
    except ValueError as error:
        raise ValueError('native build.json or captured host.json is invalid') from error
    tag = build.get('tag') if isinstance(build, dict) else None
    release = re.fullmatch(r'v?(\d+\.\d+\.\d+(?:-[0-9A-Za-z.-]+)?(?:\+[0-9A-Za-z.-]+)?)', tag) if isinstance(tag, str) else None
    if not release or release[1] != target['version']:
        raise ValueError('native build tag does not match exact target release')
    if not isinstance(host, dict) or any(host.get(field) != target[field] for field in ('os', 'version', 'architecture')):
        raise ValueError('captured native host OS/version/architecture does not match exact target')
    deployment = {'os': '5tratumos', 'native_id': native_id,
                  **{name: sha256(path) for name, path in files.items()}}
    return read_yaml(files['recipe_sha256']), deployment, files['recipe_sha256'].parent


def docker_object(value, label, errors):
    if isinstance(value, list) and len(value) == 1:
        value = value[0]
    if not isinstance(value, dict):
        errors.append(f'{label}: one actual Docker inspect object required')
        return {}
    return value


def runtime_image_errors(observed, binding, root, label, errors, local_build=False):
    if not isinstance(observed, dict) or observed.get('executed') is not True:
        errors.append(f'{label}: observed executed runtime image required')
        return
    for field in ('platform', 'index_digest', 'platform_digest', 'config_digest'):
        if field not in observed or observed[field] != binding.get(field):
            errors.append(f'{label}: observed {field} differs from immutable lock')
    if not local_build and observed.get('reference') != binding['reference']:
        errors.append(f'{label}: observed reference differs from pinned recipe')
    image = docker_object(artifact_json(root, observed.get('image_inspect_artifact'), label + ' image inspect', errors), label, errors)
    container = docker_object(artifact_json(root, observed.get('container_inspect_artifact'), label + ' container inspect', errors), label, errors)
    immutable_ids = {binding.get(key) for key in ('index_digest', 'platform_digest', 'config_digest')} - {None}
    if not isinstance(image.get('Id'), str) or image['Id'] not in immutable_ids or observed.get('image_id') != image.get('Id'):
        errors.append(f'{label}: image ID is not the recorded immutable inspect identity')
    if not isinstance(container.get('Image'), str) or container['Image'] not in immutable_ids or observed.get('container_image_id') != container.get('Image'):
        errors.append(f'{label}: container image ID is outside locked OCI ancestry')
    if local_build and image.get('Id') != binding.get('image_id'):
        errors.append(f'{label}: local build result image ID mismatch')
    if local_build:
        if observed.get('build_inputs_sha256') != binding.get('build_inputs_sha256'):
            errors.append(f'{label}: executed local image is not bound to exact build inputs')
        checked_artifact(root, observed.get('build_evidence_artifact'), label + ' build execution', errors)
    if not platform_matches({'os': image.get('Os'), 'architecture': image.get('Architecture'), 'variant': image.get('Variant', '')}, target_from_platform(binding['platform'])):
        errors.append(f'{label}: inspected image OS/architecture mismatch')
    if observed.get('container_id') != container.get('Id') or not isinstance(container.get('Id'), str) or not re.fullmatch(r'[0-9a-f]{64}', container['Id']):
        errors.append(f'{label}: executed container ID mismatch')
    actual_reference = container.get('Config', {}).get('Image') if isinstance(container.get('Config'), dict) else None
    if not observed.get('reference') or observed.get('reference') != actual_reference:
        errors.append(f'{label}: container inspect reference mismatch')
    state = container.get('State', {})
    if (not isinstance(state, dict) or not isinstance(state.get('StartedAt'), str) or
            not state['StartedAt'] or state['StartedAt'].startswith('0001-') or
            state.get('Status') not in ('running', 'exited') or
            (state.get('Status') == 'exited' and state.get('ExitCode') != 0)):
        errors.append(f'{label}: inspect does not show successful image execution')
    repo_digests = image.get('RepoDigests')
    if not local_build and not any(isinstance(value, str) and value.endswith('@' + binding['index_digest'])
                                  for value in (repo_digests if isinstance(repo_digests, list) else [])):
        errors.append(f'{label}: inspect RepoDigests omits locked index')


def target_from_platform(platform):
    return {'architecture': platform.removeprefix('linux/')}


def build_binding(model, lock, target, root, package_dir, label, errors):
    if not isinstance(lock, dict):
        errors.append(f'{label}: immutable local build input/result lock required')
        return None
    build = model['build']
    build = build if isinstance(build, dict) else {'context': build}
    if set(build) - {'context', 'dockerfile'}:
        errors.append(f'{label}: unsupported Compose build options change effective inputs')
        return None
    context_value = build.get('context')
    if not isinstance(context_value, str):
        errors.append(f'{label}: local build context is unresolved')
        return None
    context = Path(context_value.replace('${APP_DATA_DIR}', str(package_dir)).replace('$APP_DATA_DIR', str(package_dir)))
    context = (package_dir / context).resolve() if not context.is_absolute() else context.resolve()
    if not context.is_relative_to(package_dir) or not context.is_dir():
        errors.append(f'{label}: build context must be independently available inside package')
        return None
    dockerfile_value = build.get('dockerfile', 'Dockerfile')
    if not isinstance(dockerfile_value, str):
        errors.append(f'{label}: Dockerfile path is unresolved')
        return None
    dockerfile = (context / dockerfile_value).resolve()
    if not dockerfile.is_relative_to(context) or not dockerfile.is_file():
        errors.append(f'{label}: Dockerfile unavailable in build context')
        return None
    try:
        context_digest = build_context_hash(context)
    except (OSError, ValueError) as error:
        errors.append(f'{label}: {error}')
        return None
    if lock.get('context_sha256') != context_digest or lock.get('dockerfile_sha256') != sha256(dockerfile):
        errors.append(f'{label}: stale Dockerfile/build context inputs')
    source = dockerfile.read_text()
    base_refs = re.findall(r'^FROM\s+([^\s]+)', source, re.M | re.I)
    base = lock.get('base')
    if len(base_refs) != 1 or not isinstance(base, dict) or base.get('reference') != base_refs[0]:
        errors.append(f'{label}: exact single pinned Dockerfile base lock required')
    if len(base_refs) != 1 or not PINNED_REFERENCE.fullmatch(base_refs[0]):
        errors.append(f'{label}: mutable Dockerfile base reference blocks promotion')
    oci_lock_binding(base, target, root, label + ' base', errors)
    archive = lock.get('archive')
    if not isinstance(archive, dict):
        errors.append(f'{label}: exact source archive lock required')
    else:
        checked_artifact(root, archive, label + ' source archive', errors)
        args = dict(re.findall(r'^ARG\s+(PEERCOIN_VERSION|PEERCOIN_LINUX_BUILD)=([^\s]+)', source, re.M))
        arch = {'amd64': 'x86_64-linux-gnu', 'arm64': 'aarch64-linux-gnu'}.get(target['architecture'])
        expected_url = f'https://github.com/peercoin/peercoin/releases/download/v{args.get("PEERCOIN_VERSION")}/peercoin-{args.get("PEERCOIN_LINUX_BUILD")}-{arch}.tar.gz'
        if set(args) != {'PEERCOIN_VERSION', 'PEERCOIN_LINUX_BUILD'} or not arch or archive.get('url') != expected_url:
            errors.append(f'{label}: source archive URL does not match exact Dockerfile version/build/architecture')
    result = lock.get('result')
    if not isinstance(result, dict):
        errors.append(f'{label}: immutable resulting build image required')
        return None
    input_digest = canonical_sha256({key: lock.get(key) for key in
                                    ('context_sha256', 'dockerfile_sha256', 'archive', 'base')})
    if result.get('index_digest'):
        binding = oci_lock_binding(result, target, root, label + ' result', errors)
        if binding:
            binding['image_id'] = result.get('image_id')
            binding['build_inputs_sha256'] = input_digest
        return binding
    config_digest = result.get('config_digest')
    if not isinstance(config_digest, str) or not DIGEST.fullmatch(config_digest) or result.get('image_id') != config_digest:
        errors.append(f'{label}: local image ID must bind its exact config digest')
        return None
    config = artifact_json(root, result.get('config_artifact'), label + ' result config', errors, config_digest)
    if not platform_matches(config, target) or result.get('platform') != 'linux/' + target['architecture']:
        errors.append(f'{label}: resulting local image platform mismatch')
    return {'reference': None, 'platform': 'linux/' + target['architecture'],
            'index_digest': None, 'platform_digest': None, 'config_digest': config_digest,
            'image_id': result['image_id'], 'build_inputs_sha256': input_digest}


def qualification_errors(app_dir, receipt, target, evidence_root, qualification, native_root=None):
    errors = []
    root = Path(evidence_root).resolve()
    try:
        compose, deployment, package_dir = deployment_model(app_dir, target, native_root)
    except (OSError, ValueError, yaml.YAMLError) as error:
        return [str(error)]
    if not isinstance(qualification, dict) or qualification.get('schema_version') != 1:
        return ['independent immutable qualification lock required']
    if qualification.get('app_id') != Path(app_dir).name or qualification.get('candidate') != candidate_fingerprint(app_dir) or qualification.get('target') != target:
        errors.append('qualification lock app/candidate/target mismatch')
    if qualification.get('deployment') != deployment or receipt.get('deployment') != deployment:
        errors.append('deployment recipe/importer/renderer/build hashes mismatch')
    if receipt.get('qualification_sha256') != canonical_sha256(qualification):
        errors.append('receipt is not bound to independent qualification lock')
    services = compose.get('services', {})
    if not isinstance(services, dict) or not services:
        return errors + ['actual deployment services must be a nonempty valid mapping']
    for name, model in services.items():
        inherited_proxy = target['os'] == 'umbrel' and name == 'app_proxy'
        if not isinstance(model, dict) or (not inherited_proxy and not model.get('image') and not model.get('build')):
            errors.append(f'{name}: deployment runtime service requires image or build')
    image_services = {name: model for name, model in services.items() if isinstance(model, dict) and model.get('image') and not model.get('build')}
    build_services = {name: model for name, model in services.items() if isinstance(model, dict) and model.get('build')}
    if not image_services and not build_services:
        errors.append('actual deployment has no explicit runtime image/build service')
    locks, builds, observed = qualification.get('images'), qualification.get('builds'), receipt.get('runtime_images')
    if not isinstance(locks, dict) or set(locks) != set(image_services):
        errors.append('immutable image locks must cover exactly every explicit deployment image service')
        locks = locks if isinstance(locks, dict) else {}
    if not isinstance(builds, dict) or set(builds) != set(build_services):
        errors.append('build locks must cover exactly every local build service')
        builds = builds if isinstance(builds, dict) else {}
    if not isinstance(observed, dict) or set(observed) != set(image_services) | set(build_services):
        errors.append('runtime image observations must cover exactly every deployment image/build service')
        observed = observed if isinstance(observed, dict) else {}
    for name, model in image_services.items():
        reference = model['image']
        if not isinstance(reference, str) or not PINNED_REFERENCE.fullmatch(reference):
            errors.append(f'{name}: mutable recipe image reference blocks promotion')
        lock = locks.get(name)
        if not isinstance(lock, dict) or lock.get('reference') != reference:
            errors.append(f'{name}: immutable lock reference differs from actual deployment recipe')
        binding = oci_lock_binding(lock, target, root, name, errors)
        if binding:
            runtime_image_errors(observed.get(name), binding, root, name, errors)
    for name, model in build_services.items():
        declared_image = model.get('image')
        if declared_image and (not isinstance(declared_image, str) or not PINNED_REFERENCE.fullmatch(declared_image)):
            errors.append(f'{name}: mutable recipe image reference blocks promotion')
        binding = build_binding(model, builds.get(name), target, root, package_dir, name, errors)
        if binding:
            if declared_image and declared_image != binding.get('reference'):
                errors.append(f'{name}: built result differs from pinned deployment image reference')
            runtime_image_errors(observed.get(name), binding, root, name, errors, local_build=True)
    return errors


def readiness_errors(app_dir, receipt, target, evidence_root, qualification=None, native_root=None):
    """Require current exact-candidate runtime coverage and hash-linked artifacts."""
    errors = []
    if not isinstance(receipt, dict):
        return ['missing runtime receipt']
    app_dir = Path(app_dir)
    try:
        scope = target_applicability(app_dir.name, target)
    except ValueError as error:
        return [str(error)]
    if not scope['applicable']:
        return ['target is not applicable: ' + scope['reason']]
    if package_git_state(app_dir)['untracked_source']:
        errors.append('untracked package source is not part of the published Git candidate')
    if receipt.get('schema_version') != 2:
        errors.append('receipt schema_version must be 2 with immutable deployment/image binding')
    if receipt.get('app_id') != app_dir.name:
        errors.append('receipt app_id mismatch')
    try:
        candidate = candidate_fingerprint(app_dir)
    except (OSError, ValueError, KeyError, yaml.YAMLError) as error:
        return [f'candidate cannot be fingerprinted: {error}']
    if receipt.get('candidate') != candidate:
        errors.append('stale or incomplete candidate fingerprint')
    if receipt.get('target') != target:
        errors.append('target OS, exact version or architecture mismatch')
    target_valid = True
    if not isinstance(target, dict) or set(target) != {'os', 'version', 'architecture'}:
        errors.append('target requires os, version and architecture')
        target_valid = False
    else:
        if not isinstance(target['architecture'], str) or target['architecture'] not in ARCHITECTURES:
            errors.append('target architecture must use OCI names')
            target_valid = False
        if not isinstance(target['os'], str) or not target['os'].strip():
            errors.append('target OS is missing')
            target_valid = False
        version = target['version']
        if (not isinstance(version, str) or not version.strip() or
                version in ('1.7', '2.0', 'latest') or re.search(r'[xX*<>=~^]|\s', version) or
                not re.fullmatch(r'\d+\.\d+\.\d+(?:-[0-9A-Za-z.-]+)?(?:\+[0-9A-Za-z.-]+)?', version)):
            errors.append('target version must be exact, not a release family or range')
            target_valid = False
    if receipt.get('verification') != 'runtime' or receipt.get('historical') is not False:
        errors.append('current runtime verification required; static/historical smoke is insufficient')
    checks = receipt.get('checks')
    if not isinstance(checks, dict):
        checks = {}
    required = list(REQUIRED_CHECKS)
    if app_dir.name in MINING_APP_IDS:
        required.append('node_pool_accepted_share')
    evidence_root = Path(evidence_root).resolve()
    for name in required:
        check = checks.get(name)
        if not isinstance(check, dict) or check.get('status') != 'pass':
            errors.append(f'{name}: runtime pass evidence required')
            continue
        if not isinstance(check.get('observation'), str) or not check['observation'].strip():
            errors.append(f'{name}: observed behavior is required')
        artifacts = check.get('artifacts')
        if not isinstance(artifacts, list) or not artifacts:
            errors.append(f'{name}: hash-linked evidence artifact required')
            continue
        for artifact in artifacts:
            if not isinstance(artifact, dict) or not isinstance(artifact.get('path'), str) or not isinstance(artifact.get('sha256'), str):
                errors.append(f'{name}: invalid evidence artifact')
                continue
            relative = Path(artifact['path'])
            path = (evidence_root / relative).resolve()
            if relative.is_absolute() or not path.is_relative_to(evidence_root) or path == evidence_root:
                errors.append(f'{name}: artifact must remain inside the evidence root')
            elif not path.is_file():
                errors.append(f'{name}: evidence artifact missing: {artifact["path"]}')
            elif sha256(path) != artifact['sha256']:
                errors.append(f'{name}: evidence artifact hash mismatch: {artifact["path"]}')
    errors.extend('static blocker: ' + error for error in app_contract_errors(app_dir))
    if target_valid:
        errors.extend(qualification_errors(app_dir, receipt, target, evidence_root, qualification, native_root))
    return errors


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--root', type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument('--probe-exports', action='store_true')
    parser.add_argument('--receipts', type=Path,
                        help='JSON array of runtime receipts; no receipts are generated')
    parser.add_argument('--evidence-root', type=Path)
    parser.add_argument('--qualifications', type=Path,
                        help='independent JSON array of immutable qualification locks')
    parser.add_argument('--native-root', type=Path,
                        help='independent materialized native deployment/release root')
    parser.add_argument('--target', action='append', default=[], metavar='OS:VERSION:ARCH',
                        help='exact target required for every app; repeat for each target')
    args = parser.parse_args(argv)
    results = catalogue_contract(args.root)
    targets = []
    for target in args.target:
        parts = target.split(':')
        if len(parts) != 3:
            parser.error('--target must have OS:VERSION:ARCH')
        if parts[0] not in TARGET_OSES:
            parser.error('--target OS must be exactly umbrel or 5tratumos')
        targets.append(dict(zip(('os', 'version', 'architecture'), parts)))
    if args.receipts and (not targets or not args.evidence_root):
        parser.error('--receipts requires --target and --evidence-root')
    receipts = json.loads(args.receipts.read_text()) if args.receipts else []
    if not isinstance(receipts, list):
        parser.error('--receipts must contain a JSON array')
    qualifications = json.loads(args.qualifications.read_text()) if args.qualifications else []
    if not isinstance(qualifications, list):
        parser.error('--qualifications must contain an independent JSON array')
    failed = not results
    for result in results:
        app_dir = args.root / result['app_id']
        if args.probe_exports:
            result['exports_contract_errors'] = exports_contract_errors(app_dir)
        result['runtime_readiness'] = []
        for target in targets:
            matching = [receipt for receipt in receipts if isinstance(receipt, dict) and
                        receipt.get('app_id') == result['app_id'] and receipt.get('target') == target]
            try:
                scope = target_applicability(result['app_id'], target)
            except ValueError as error:
                result['runtime_readiness'].append({'target': target, 'applicable': False,
                                                    'status': 'unsupported_target', 'errors': [str(error)]})
                continue
            if not scope['applicable']:
                # N/A is an explicit scope decision, never a runtime pass. A
                # claimed native Fumbrel receipt is a wrong-platform input.
                errors = ['runtime receipts cannot qualify for a not-applicable target'] if matching else []
                result['runtime_readiness'].append({'target': target, **scope, 'errors': errors})
                continue
            qualified = [lock for lock in qualifications if isinstance(lock, dict) and
                         lock.get('app_id') == result['app_id'] and lock.get('target') == target]
            errors = ['exactly one current receipt required for this app/target'] if len(matching) != 1 else readiness_errors(
                app_dir, matching[0], target, args.evidence_root,
                qualified[0] if len(qualified) == 1 else None, args.native_root)
            result['runtime_readiness'].append({'target': target, 'applicable': True,
                                                'status': 'blocked' if errors else 'evidence_complete',
                                                'errors': errors})
        failed |= bool(result['static_contract_errors'] or result.get('exports_contract_errors') or
                       any(item['errors'] for item in result['runtime_readiness']))
    print(json.dumps({'verification': 'static_contracts_only', 'apps': results}, indent=2))
    return int(failed)


if __name__ == '__main__':
    sys.exit(main())
