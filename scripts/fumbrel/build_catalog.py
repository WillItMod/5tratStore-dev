#!/usr/bin/env python3
"""Bundle reviewed recipe metadata; never include application data or secrets."""
import argparse
import base64
import hashlib
import json
import subprocess
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
DEV_COMMIT = '8ce6fcc02b6c5d0cd4ee27f8803a6948e97c3f9e'
MAIN_COMMIT = '5c68fc868c62eaeff2bb3f930cbf0193ac3931cb'
LEGACY = [
    '723d296b8548d7d025303f81f811838842a742b7bd628d2e5d7e99d7d3952293',
    '2206ee3269f996409aee62da4dab552f853194a9e8b33505137dba223f6f108e',
]


def permitted(name):
    p = Path(name)
    return (name in ('docker-compose.yml', 'umbrel-app.yml', 'exports.sh', 'torrc')
            or (len(p.parts) == 1 and name.endswith('.template'))
            or (len(p.parts) > 1 and p.parts[0] == 'hooks'))


def build(main_path):
    catalog = {'format': 1, 'release': '0.1.0-dev', 'legacy_exports': LEGACY, 'apps': {}}
    entries = subprocess.check_output(['git', 'ls-tree', '-r', DEV_COMMIT], cwd=ROOT, text=True).splitlines()
    folders = sorted({line.split('\t', 1)[1].split('/')[0] for line in entries
                      if line.endswith('/umbrel-app.yml') and '\twillitmod-dev-' in line})
    for folder in folders + ['willitmod-axesim']:
        is_main = folder == 'willitmod-axesim'
        files = {}
        if is_main:
            sources = [(p.relative_to(main_path / folder).as_posix(), p.read_bytes(), 0o644)
                       for p in (main_path / folder).rglob('*') if p.is_file() and permitted(p.relative_to(main_path / folder).as_posix())]
        else:
            sources = []
            for line in entries:
                metadata, path = line.split('\t', 1)
                if path.startswith(folder + '/') and permitted(path[len(folder) + 1:]):
                    mode = int(metadata.split()[0], 8) & 0o777
                    body = subprocess.check_output(['git', 'show', DEV_COMMIT + ':' + path], cwd=ROOT)
                    sources.append((path[len(folder) + 1:], body, mode))
        for name, body, mode in sources:
            files[name] = {'body': base64.b64encode(body).decode(), 'sha256': hashlib.sha256(body).hexdigest(), 'mode': mode}
        manifest = yaml.safe_load(base64.b64decode(files['umbrel-app.yml']['body']))
        aliases = [folder]
        if folder in ('willitmod-dev-btc', 'willitmod-dev-axebench', 'willitmod-dev-axelive', 'willitmod-dev-axemig'):
            aliases.append(folder.replace('willitmod-dev-', 'willitmod-'))
        entry = {'name': manifest['name'], 'version': str(manifest['version']), 'source_id': folder,
                 'source_commit': MAIN_COMMIT if is_main else DEV_COMMIT,
                 'channel': 'MAIN (AxeSim)' if is_main else 'DEV', 'files': files}
        for alias in aliases:
            catalog['apps'][alias] = entry
    destination = ROOT / 'willitmod-dev-fumbrel/app/catalog.json'
    destination.write_text(json.dumps(catalog, indent=2, sort_keys=True) + '\n')
    print(f'Bundled {len(folders) + 1} packages / {len(catalog["apps"])} installed IDs')


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--main-snapshot', required=True, type=Path)
    build(parser.parse_args().main_snapshot)
