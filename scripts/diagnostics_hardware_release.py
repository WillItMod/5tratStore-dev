"""Admit only the published diagnostics hardware-evidence package."""
import copy
import hashlib
import json
from pathlib import Path
import stat
import subprocess

import yaml

ROOT = Path(__file__).resolve().parents[1]
APP = 'willitmod-dev-5tratumos-diagnostics'
BASELINE = '0b08fc0dae231ba9b02a0f418ad84b32e090d90c'
RECORD = 'DIAGNOSTICS-HARDWARE-2026-11-09.json'
RECORD_SHA256 = '4e4d786643dd7327add30926c5c735e4f4a2dbe1a7b3ab19ab946e50757b893c'
VERSION = '0.1.9'
SOURCE = 'b3e432b32771a06839a88af3d5e007cad94d29ae'
CHANGED = {APP + '/' + name for name in ('docker-compose.yml', 'global-app.yml')}


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def digest(model):
    return sha(json.dumps(model, sort_keys=True, separators=(',', ':')).encode())


def git(root, *args):
    return subprocess.check_output(['git', *args], cwd=root)


def baseline_bytes(root, name):
    return git(root, 'show', BASELINE + ':' + name)


def record(root=ROOT):
    raw = (root / RECORD).read_bytes()
    assert sha(raw) == RECORD_SHA256, 'Unreviewed diagnostics release record'
    row = json.loads(raw)
    assert (row['schemaVersion'], row['channel'], row['appId'], row['version'],
            row['previousVersion'], row['baselineCommit'], row['sourceRevision']) == (
                1, 'DEV', APP, VERSION, '0.1.8', BASELINE, SOURCE)
    assert set(row['changedFiles']) == CHANGED
    return row


def previous_file_bytes(raw, name, root=ROOT):
    row = record(root)
    expected = row['packageFiles'][name]
    before = baseline_bytes(root, name)
    assert sha(before) == expected['beforeSHA256'], 'Diagnostics predecessor differs'
    assert sha(raw) == expected['afterSHA256'], 'Unreviewed diagnostics package bytes'
    return before


def previous_model(app_id, current, root=ROOT, filename='docker-compose.yml'):
    if app_id != APP:
        return copy.deepcopy(current)
    row = record(root)
    before = yaml.safe_load(baseline_bytes(root, APP + '/' + filename))
    assert digest(before) == row['models'][filename]['beforeSHA256']
    if current == before:
        return copy.deepcopy(before)
    assert digest(current) == row['models'][filename]['afterSHA256'], 'Unreviewed diagnostics runtime or manifest'
    return before


def package_version(app_id, historical, root=ROOT):
    if app_id != APP:
        return historical
    record(root)
    assert historical in ('0.1.8', VERSION), 'Unexpected diagnostics predecessor version'
    return VERSION


def validate(root=ROOT):
    row = record(root)
    names = set(git(root, 'ls-tree', '-r', '--name-only', BASELINE, '--', APP).decode().splitlines())
    actual = {str(path.relative_to(root)): path for path in (root / APP).rglob('*')
              if path.is_file() or path.is_symlink()}
    assert set(actual) == names == set(row['packageFiles']), 'Diagnostics package inventory changed'
    changed = set()
    for name, path in actual.items():
        assert stat.S_ISREG(path.lstat().st_mode), 'Diagnostics package symlink forbidden'
        mode = stat.S_IMODE(path.stat().st_mode)
        assert oct(mode) == row['packageFiles'][name]['mode'], 'Diagnostics package mode changed'
        old_mode = git(root, 'ls-tree', BASELINE, '--', name).decode().split()[0]
        assert old_mode == ('100755' if mode & 0o111 else '100644')
        before = previous_file_bytes(path.read_bytes(), name, root)
        if path.read_bytes() != before:
            changed.add(name)
    assert changed == CHANGED, 'Unexpected diagnostics release file changes'
    for filename in ('docker-compose.yml', 'global-app.yml'):
        model = yaml.safe_load((root / APP / filename).read_text())
        assert digest(model) == row['models'][filename]['afterSHA256']
        previous_model(APP, model, root, filename)
    model = yaml.safe_load((root / APP / 'docker-compose.yml').read_text())
    assert model['services']['app']['image'] == row['appImage']
    assert model['services']['drive-probe']['image'] == row['probeImage']
    assert model['services']['app']['environment']['APP_REVISION'] == SOURCE
    return row


def historical_protected_paths(root, previous_commit, protected):
    """Keep all older guards, after proving this exact package successor."""
    validate(root)
    assert CHANGED <= set(protected), 'Historical diagnostics package inventory differs'
    for name in CHANGED:
        assert baseline_bytes(root, name) == git(root, 'show', previous_commit + ':' + name), 'Historical diagnostics predecessor bytes differ'
        mode = git(root, 'ls-tree', BASELINE, '--', name).decode().split()[0]
        historical = git(root, 'ls-tree', previous_commit, '--', name).decode().split()[0]
        assert mode == historical, 'Historical diagnostics predecessor mode differs'
    return [name for name in protected if name not in CHANGED]


if __name__ == '__main__':
    row = validate()
    print(json.dumps({'result': 'PASS', 'channel': row['channel'], 'version': row['version']}))
