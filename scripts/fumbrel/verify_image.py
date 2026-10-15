#!/usr/bin/env python3
"""Verify the actual native COPY-only candidate preserves the tested base.

No SSH, guest/app mounts or recovery operation. A real container reads its own
files and checks health/UI through its Flask test client only.
"""
import argparse
import gzip
import hashlib
import io
import json
import os
from pathlib import Path, PurePosixPath
import re
import subprocess
import tarfile
import tempfile

ROOT = Path(__file__).resolve().parents[2]
BASE_DIGEST = 'sha256:290a91f5e8f42e51af4b9c715c449bda96071b98eb4c2de0ef97e52d9d4fba7a'
BASE = 'ghcr.io/willitmod/fumbrel:0.1.1-dev@' + BASE_DIGEST
RELEASE = '0.1.2-dev'
LABELS = {'org.opencontainers.image.source', 'org.opencontainers.image.revision',
          'org.opencontainers.image.version', 'org.opencontainers.image.base.digest'}
FILES = ('engine.py', 'catalog.json')


def digest(value):
    return 'sha256:' + hashlib.sha256(value).hexdigest()


def run(argv, timeout=60):
    result = subprocess.run(argv, text=True, capture_output=True, timeout=timeout)
    if result.returncode:
        raise RuntimeError('Image verification command failed: ' + argv[0])
    return result.stdout


def check_contract(base, candidate, layer, expected, source_commit):
    """Fail closed on unrelated layer files, runtime or provenance changes."""
    if not re.fullmatch('[0-9a-f]{40}', source_commit):
        raise ValueError('Expected an immutable source commit')
    if any(base.get(k) != candidate.get(k) for k in ('architecture', 'os')):
        raise ValueError('Platform changed')
    old_layers, new_layers = base['rootfs']['diff_ids'], candidate['rootfs']['diff_ids']
    if len(new_layers) != len(old_layers) + 1 or new_layers[:-1] != old_layers:
        raise ValueError('The actual tested base blobs were not retained exactly')
    if digest(layer) != new_layers[-1]:
        raise ValueError('Actual COPY layer bytes differ from the image configuration')
    old, new = base['config'], candidate['config']
    if {k: v for k, v in old.items() if k != 'Labels'} != {k: v for k, v in new.items() if k != 'Labels'}:
        raise ValueError('Inherited runtime settings changed')
    old_labels, new_labels = old.get('Labels') or {}, new.get('Labels') or {}
    if {k: v for k, v in old_labels.items() if k not in LABELS} != {k: v for k, v in new_labels.items() if k not in LABELS}:
        raise ValueError('Unrelated labels changed')
    required = {'org.opencontainers.image.source': 'https://github.com/WillItMod/5tratStore-dev',
                'org.opencontainers.image.revision': source_commit,
                'org.opencontainers.image.version': RELEASE,
                'org.opencontainers.image.base.digest': BASE_DIGEST}
    if any(new_labels.get(k) != v for k, v in required.items()):
        raise ValueError('Candidate provenance does not match its reviewed source/base')
    found, directories = {}, []
    with tarfile.open(fileobj=io.BytesIO(layer), mode='r:') as archive:
        for member in archive:
            name = member.name.removeprefix('./').rstrip('/')
            path = PurePosixPath(name)
            if path.is_absolute() or '..' in path.parts or str(path) != name:
                raise ValueError('Noncanonical layer path')
            if member.isdir():
                if name != 'app' or (member.mode, member.uid, member.gid) != (0o755, 0, 0):
                    raise ValueError('Unrelated directory metadata in COPY layer')
                directories.append(name)
                continue
            if not member.isfile() or name not in {'app/' + n for n in FILES} or name in found:
                raise ValueError('Unrelated file, link, duplicate or whiteout in COPY layer')
            body = archive.extractfile(member).read()
            if body != expected[name.removeprefix('app/')] or (member.mode, member.uid, member.gid) != (0o644, 0, 0):
                raise ValueError('Candidate file bytes/modes/owners do not match reviewed source')
            found[name] = {'sha256': digest(body), 'bytes': len(body), 'mode': '0644', 'uid': 0, 'gid': 0}
    if set(found) != {'app/' + n for n in FILES} or len(directories) != len(set(directories)):
        raise ValueError('COPY payload is incomplete or ambiguous')
    return found


def saved_image(image, destination):
    run(['docker', 'image', 'save', '-o', str(destination), image], timeout=180)
    with tarfile.open(destination) as archive:
        manifest = json.load(archive.extractfile('manifest.json'))
        if len(manifest) != 1:
            raise ValueError('Expected one selected native platform')
        entry = manifest[0]
        raw = archive.extractfile(entry['Config']).read()
        layer = archive.extractfile(entry['Layers'][-1]).read()
    if layer.startswith(b'\x1f\x8b'):
        layer = gzip.decompress(layer)
    return json.loads(raw), digest(raw), layer


def verify(image, arch, source_commit):
    if run(['git', 'rev-parse', 'HEAD']).strip() != source_commit:
        raise ValueError('Verifier checkout does not match candidate source')
    if run(['git', 'status', '--porcelain', '--untracked-files=all', '--', 'willitmod-dev-fumbrel/app']).strip():
        raise ValueError('Application build context must be committed and clean')
    actual_arch = run(['docker', 'info', '--format', '{{.Architecture}}']).strip()
    if {'x86_64': 'amd64', 'aarch64': 'arm64', 'arm64': 'arm64'}.get(actual_arch) != arch:
        raise ValueError('This proof requires the actual native platform')
    expected = {name: (ROOT / 'willitmod-dev-fumbrel/app' / name).read_bytes() for name in FILES}
    record = json.loads((ROOT / 'release-records/fumbrel-0.1.1-dev-image.json').read_text())
    if record['digest'] != BASE_DIGEST:
        raise ValueError('Historical tested base receipt changed')
    run(['docker', 'pull', BASE], timeout=180)
    with tempfile.TemporaryDirectory(prefix='fumbrel-image-proof-') as directory:
        base, base_config, _ = saved_image(BASE, Path(directory) / 'base.tar')
        candidate, candidate_config, layer = saved_image(image, Path(directory) / 'candidate.tar')
    if base_config != record['platforms'][arch]['config_digest']:
        raise ValueError('Selected base is not the actual tested platform configuration')
    if candidate['architecture'] != arch:
        raise ValueError('Candidate platform does not match the native worker')
    bindings = check_contract(base, candidate, layer, expected, source_commit)
    # No app path/host key/credential is supplied, and no SSH endpoint exists.
    code = """import hashlib,json,os,pathlib
from server import app,CATALOG
paths=['engine.py','catalog.json','server.py','requirements.txt']+['static/'+str(p.relative_to('/app/static')) for p in sorted(pathlib.Path('/app/static').rglob('*')) if p.is_file()]
out={}
for name in paths:
 p=pathlib.Path('/app')/name;s=p.stat();out[name]={'sha256':hashlib.sha256(p.read_bytes()).hexdigest(),'mode':oct(s.st_mode&0o777),'uid':s.st_uid,'gid':s.st_gid}
c=app.test_client();h=c.get('/health');u=c.get('/');i=c.get('/api/info');assert h.status_code==200 and u.status_code==200 and i.status_code==400
print(json.dumps({'files':out,'health_status':h.status_code,'ui_status':u.status_code,'info_status_without_host_key':i.status_code,'version':CATALOG['release'],'uid':os.getuid(),'gid':os.getgid()}))"""
    out = json.loads(run(['docker', 'run', '--rm', '--network', 'none', '--read-only',
                         '--cap-drop', 'ALL', '--security-opt', 'no-new-privileges',
                         '--user', '1000:1000', '--memory', '256m', '--memory-swap', '256m',
                         '--cpus', '1', '--pids-limit', '32', '--tmpfs', '/tmp:rw,nosuid,nodev,noexec,size=16m',
                         '--entrypoint', 'python', image, '-c', code]))
    if out['uid'] != 1000 or out['gid'] != 1000 or out.get('version') != RELEASE:
        raise ValueError('Runtime identity/release did not match candidate')
    for name, value in out['files'].items():
        if value['sha256'] != hashlib.sha256((ROOT / 'willitmod-dev-fumbrel/app' / name).read_bytes()).hexdigest():
            raise ValueError('Runtime application files differ from the source context')
    return {'source_commit': source_commit, 'release': RELEASE, 'architecture': arch,
            'base_index': BASE_DIGEST, 'base_config': base_config, 'candidate_config': candidate_config,
            'exact_base_diff_ids': base['rootfs']['diff_ids'], 'added_copy_diff_id': candidate['rootfs']['diff_ids'][-1],
            'only_added_files': bindings, 'runtime': out, 'native_platform': True,
            'inherited_runtime_UI_auth_dependencies_base_blobs_exact': True,
            'no_SSH_host_app_mount_or_recovery_operation': True,
            'scope': 'Native image inheritance and in-container health/UI and expected missing-host-key refusal; actual Umbrel update/recovery remains separate.'}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--image', required=True)
    parser.add_argument('--arch', required=True, choices=('amd64', 'arm64'))
    parser.add_argument('--source-commit', required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    result = verify(args.image, args.arch, args.source_commit)
    body = json.dumps(result, indent=2) + '\n'
    args.output.write_text(body)
    print(body, end='')
