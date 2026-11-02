"""Exact store-version correction; runtime bytes and prior evidence stay fixed."""
import hashlib
import json
from pathlib import Path
import stat
import subprocess

ROOT = Path(__file__).resolve().parents[1]
APP = 'willitmod-dev-powpow'
BASELINE = 'e09578a28413350442af8aa0aff92c96c8acaa9e'
PREVIOUS_VERSION = '0.2.37-dev.6'
VERSION = '0.2.39'
MANIFESTS = ('umbrel-app.yml', 'global-app.yml')
RECORD_NAME = 'POWPOW-PACKAGE-VERSION-2026-11-02.json'
RECORD_SHA256 = "61a42acf75d4c9cb3f485179fa02675714e2ea28db016201bcdc7d491e4ecdc7"


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def git(root, *args):
    return subprocess.check_output(['git', *args], cwd=root)


def baseline_bytes(name, root=ROOT):
    return git(root, 'show', BASELINE + ':' + name)


def expected_bytes(name, root=ROOT):
    raw = baseline_bytes(name, root)
    if name in {APP + '/' + filename for filename in MANIFESTS}:
        old = ('version: "' + PREVIOUS_VERSION + '"\n').encode()
        assert raw.count(old) == 1
        return raw.replace(old, ('version: "' + VERSION + '"\n').encode(), 1)
    if name == 'README.md':
        old = ('- **PowPow** (`' + APP + '`) - `' + PREVIOUS_VERSION + '`').encode()
        assert raw.count(old) == 1
        return raw.replace(old, old.replace(PREVIOUS_VERSION.encode(), VERSION.encode()), 1)
    return raw


def previous_manifest_bytes(name, raw, root=ROOT):
    assert name in MANIFESTS, 'Only PowPow manifest versions may be normalized'
    path = APP + '/' + name
    previous = baseline_bytes(path, root)
    assert raw in (previous, expected_bytes(path, root)), 'Unreviewed PowPow successor bytes in package-version correction'
    return previous


def package_version(app_id, historical, root=ROOT):
    if app_id != APP:
        return historical
    assert historical in (PREVIOUS_VERSION, VERSION), 'Unreviewed package-version predecessor'
    return VERSION


def validate_files(root=ROOT):
    rows = git(root, 'ls-tree', '-r', BASELINE).decode().splitlines()
    entries = {row.split('\t', 1)[1]: row.split()[0] for row in rows}
    package = {name for name in entries if name.startswith(APP + '/')}
    actual = {str(path.relative_to(root)) for path in (root / APP).rglob('*')
              if not path.is_dir() or path.is_symlink()}
    assert actual == package, 'PowPow package inventory changed'
    preserved = {name for name in entries if ('/' not in name and name.endswith('.json'))
                 or name.startswith('powpow-release-records/')}
    for name in sorted(package | preserved | {'README.md'}):
        path = root / name
        info = path.lstat()
        assert stat.S_ISREG(info.st_mode), 'Correction file is not regular: ' + name
        assert stat.S_IMODE(info.st_mode) == int(entries[name], 8) & 0o777, 'Correction file mode changed: ' + name
        assert path.read_bytes() == expected_bytes(name, root), 'Unreviewed correction bytes: ' + name


def validate(root=ROOT):
    raw = (root / RECORD_NAME).read_bytes()
    assert RECORD_SHA256 is not None and sha(raw) == RECORD_SHA256, 'Unreviewed version-correction record'
    row = json.loads(raw)
    assert row == {'schemaVersion': 1, 'status': 'qualified-metadata-only', 'channel': 'DEV',
                   'appId': APP, 'baselineCommit': BASELINE, 'previousPackageVersion': PREVIOUS_VERSION,
                   'packageVersion': VERSION, 'changedPackageFiles': [APP + '/' + name for name in MANIFESTS],
                   'readmeCatalogueVersionUpdated': True, 'runtimeModelChanged': False,
                   'imagesChanged': False, 'priorReleaseRecordsAndProofsChanged': False}
    validate_files(root)
    return row


if __name__ == '__main__':
    print(json.dumps(validate(), indent=2))
