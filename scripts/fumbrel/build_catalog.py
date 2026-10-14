#!/usr/bin/env python3
"""Bundle recipe blobs from pinned Git commits, never host data or credentials.

The existing MAIN AxeSim entry is retained byte-for-byte from an explicit DEV
catalog commit. Refreshing DEV recovery recipes must not advance MAIN sources.
"""
import argparse
import base64
import copy
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
import subprocess

import yaml

ROOT = Path(__file__).resolve().parents[2]
DEV_COMMIT = '6f8ae3e7949433e64a144c9707432636bafb3e8a'
RETAINED_CATALOG_COMMIT = '6f8ae3e7949433e64a144c9707432636bafb3e8a'
MAIN_COMMIT = '5c68fc868c62eaeff2bb3f930cbf0193ac3931cb'
RELEASE = '0.1.1-dev'
CATALOG_PATH = 'willitmod-dev-fumbrel/app/catalog.json'
SELF = 'willitmod-dev-fumbrel'
LEGACY = [
    '723d296b8548d7d025303f81f811838842a742b7bd628d2e5d7e99d7d3952293',
    '2206ee3269f996409aee62da4dab552f853194a9e8b33505137dba223f6f108e',
]


def permitted(name):
    p = PurePosixPath(name)
    return (not p.is_absolute() and '..' not in p.parts and str(p) == name
            and (name in ('docker-compose.yml', 'umbrel-app.yml', 'exports.sh', 'torrc')
                 or (len(p.parts) == 1 and name.endswith('.template'))
                 or (len(p.parts) > 1 and p.parts[0] == 'hooks')))


def git(*args, repo=ROOT):
    return subprocess.check_output(['git', *args], cwd=repo)


def commit(value, repo):
    # Do not silently bind a release bundle to a moving branch or abbreviated SHA.
    if not re.fullmatch('[0-9a-f]{40}', value):
        raise ValueError('Catalog inputs must be full immutable Git commit IDs')
    if git('rev-parse', value + '^{commit}', repo=repo).decode().strip() != value:
        raise ValueError('Catalog input did not resolve to the exact commit')
    return value


def retained_main(catalog_ref, repo):
    previous = json.loads(git('show', catalog_ref + ':' + CATALOG_PATH, repo=repo))
    entry = previous['apps']['willitmod-axesim']
    if (entry['source_commit'] != MAIN_COMMIT or entry['source_id'] != 'willitmod-axesim'
            or entry['channel'] != 'MAIN (AxeSim)'):
        raise ValueError('The retained MAIN AxeSim source changed; review it separately')
    for name, record in entry['files'].items():
        body = base64.b64decode(record['body'], validate=True)
        if (not permitted(name) or hashlib.sha256(body).hexdigest() != record['sha256']
                or record['mode'] not in (0o644, 0o755)):
            raise ValueError('The retained MAIN AxeSim entry failed validation')
    return copy.deepcopy(entry)


def build(dev_ref=DEV_COMMIT, retained_catalog_ref=RETAINED_CATALOG_COMMIT,
          release=RELEASE, repo=ROOT):
    dev_ref = commit(dev_ref, repo)
    retained_catalog_ref = commit(retained_catalog_ref, repo)
    catalog = {'format': 1, 'release': release, 'legacy_exports': LEGACY, 'apps': {}}
    entries = []
    for line in git('ls-tree', '-r', dev_ref, repo=repo).decode().splitlines():
        metadata, path = line.split('\t', 1)
        mode, kind, _ = metadata.split()
        entries.append((path, mode, kind))
    folders = sorted({path.split('/')[0] for path, _, _ in entries
                      if path.startswith('willitmod-dev-') and path.endswith('/umbrel-app.yml')
                      and path.count('/') == 1 and path.split('/')[0] != SELF})
    for folder in folders:
        files = {}
        for path, mode, kind in entries:
            if not path.startswith(folder + '/') or not permitted(path[len(folder) + 1:]):
                continue
            if kind != 'blob' or mode not in ('100644', '100755'):
                raise ValueError('Recipe files must be regular Git blobs: ' + path)
            body = git('show', dev_ref + ':' + path, repo=repo)
            files[path[len(folder) + 1:]] = {
                'body': base64.b64encode(body).decode(),
                'sha256': hashlib.sha256(body).hexdigest(), 'mode': int(mode, 8) & 0o777}
        manifest = yaml.safe_load(base64.b64decode(files['umbrel-app.yml']['body']))
        if manifest['id'] != folder:
            raise ValueError('Recipe identity differs from its directory: ' + folder)
        aliases = [folder]
        if folder in ('willitmod-dev-btc', 'willitmod-dev-axebench', 'willitmod-dev-axelive', 'willitmod-dev-axemig'):
            aliases.append(folder.replace('willitmod-dev-', 'willitmod-'))
        entry = {'name': manifest['name'], 'version': str(manifest['version']), 'source_id': folder,
                 'source_commit': dev_ref, 'channel': 'DEV', 'files': files}
        for alias in aliases:
            catalog['apps'][alias] = entry
    catalog['apps']['willitmod-axesim'] = retained_main(retained_catalog_ref, repo)
    return catalog


def serialized(catalog):
    return json.dumps(catalog, indent=2, sort_keys=True) + '\n'


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--dev-ref', default=DEV_COMMIT)
    parser.add_argument('--retained-catalog-ref', default=RETAINED_CATALOG_COMMIT)
    parser.add_argument('--release', default=RELEASE)
    parser.add_argument('--output', type=Path, default=ROOT / CATALOG_PATH)
    parser.add_argument('--check', action='store_true', help='Compare without changing the bundled catalog')
    args = parser.parse_args()
    body = serialized(build(args.dev_ref, args.retained_catalog_ref, args.release))
    if args.check:
        if args.output.read_text() != body:
            raise SystemExit('Bundled catalog differs from its pinned Git inputs')
        print('Bundled catalog matches its pinned Git inputs')
    else:
        args.output.write_text(body)
        print(f'Bundled {len(json.loads(body)["apps"])} installed IDs')
