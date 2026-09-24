"""Fixed recovery program sent over verified SSH. Host dependency: Umbrel's yq.

Only recipe metadata is writable here. Application lifecycle, including its
normal data migrations, remains Umbrel's responsibility. No uninstall/purge.
"""
import base64
import copy
import fcntl
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import time
import uuid

SELF = 'willitmod-dev-fumbrel'
MAX_FILE = 2 * 1024 * 1024


class RecoveryError(Exception):
    pass


def digest(body):
    return hashlib.sha256(body).hexdigest()


def allowed(name):
    p = PurePosixPath(name)
    return (not p.is_absolute() and '..' not in p.parts and str(p) == name
            and (name in ('docker-compose.yml', 'umbrel-app.yml', 'exports.sh', 'torrc')
                 or (len(p.parts) == 1 and name.endswith('.template'))
                 or (len(p.parts) > 1 and p.parts[0] == 'hooks')))


def safe_path(root, name):
    if not allowed(name):
        raise RecoveryError('Unapproved recipe path. No changes made to that file.')
    p = root / name
    for component in [root, *p.relative_to(root).parents, p]:
        q = component if component.is_absolute() else root / component
        if q.is_symlink():
            raise RecoveryError('Recipe contains a symlink; manual review is required.')
    if p.exists():
        info = p.stat()
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or info.st_size > MAX_FILE:
            raise RecoveryError('Recipe is not a regular bounded file; manual review is required.')
    return p


def read_file(root, name):
    path = safe_path(root, name)
    return path.read_bytes() if path.exists() else None


def atom_write(path, body, mode=0o644, uid=0, gid=0):
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix='.fumbrel-', dir=path.parent)
    try:
        with os.fdopen(fd, 'wb') as stream:
            stream.write(body)
            stream.flush()
            os.fsync(stream.fileno())
            os.fchmod(stream.fileno(), mode & 0o777)
            if os.geteuid() == 0:
                os.fchown(stream.fileno(), uid, gid)
        os.replace(temporary, path)
        directory = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def command(argv, timeout=30, input_text=None):
    try:
        result = subprocess.run(argv, input=input_text, text=True, capture_output=True, timeout=timeout)
    except (OSError, subprocess.TimeoutExpired):
        raise RecoveryError('A host command timed out or is unavailable. Inspect Umbrel before retrying.') from None
    if result.returncode:
        # Never return subprocess output: Compose and Umbrel can include secrets.
        raise RecoveryError('Umbrel could not complete this step. The recipe backup is available; inspect Umbrel troubleshooting.')
    return result.stdout


def yaml_load(body):
    return json.loads(command(['yq', '-o=json', '.', '-'], input_text=body.decode('utf-8-sig')))


def yaml_dump(value):
    # JSON is YAML 1.2, including multiline strings and literal ${variables}.
    return (json.dumps(value, indent=2, ensure_ascii=False) + '\n').encode()


def version_tuple(value):
    match = re.fullmatch(r'v?(\d+(?:\.\d+)*)(?:[-+][A-Za-z0-9.+-]+)?', str(value))
    if not match:
        raise RecoveryError('Unrecognized version; automatic replacement is disabled.')
    return tuple(int(part) for part in match.group(1).split('.'))


def is_newer(installed, target):
    a, b = version_tuple(installed), version_tuple(target)
    count = max(len(a), len(b))
    return a + (0,) * (count - len(a)) > b + (0,) * (count - len(b))


def fix_compose(value, app_id):
    value = copy.deepcopy(value)
    issues = []
    services = value.get('services', {})
    proxy = services.get('app_proxy', {})
    env = proxy.get('environment', {})
    if isinstance(env, list):
        env = dict(item.split('=', 1) for item in env if '=' in item)
    host = env.get('APP_HOST')
    if host:
        candidates = []
        for name, service in services.items():
            if name == 'app_proxy':
                continue
            networks = service.get('networks', {})
            aliases = [alias for network in (networks.values() if isinstance(networks, dict) else [])
                       for alias in (network or {}).get('aliases', [])]
            if host in [name, service.get('hostname'), service.get('container_name'),
                        f'{app_id}_{name}_1', f'{app_id}-{name}-1', *aliases]:
                candidates.append(name)
        if len(candidates) != 1:
            raise RecoveryError('Cannot identify a unique dashboard service. Manual recipe review is required.')
        service = services[candidates[0]]
        if service.get('hostname') != host:
            service['hostname'] = host
            issues.append('Declare dashboard hostname for the Umbrel 2 gateway')
    if app_id == 'willitmod-dev-fracattack':
        service = services.get('app', {})
        old_ports = service.get('ports', [])
        ports = []
        for port in old_ports:
            duplicate = (isinstance(port, str) and re.fullmatch(r'(?:0\.0\.0\.0:)?21225:3000(?:/tcp)?', port))
            duplicate = duplicate or (isinstance(port, dict) and str(port.get('published')) == '21225' and str(port.get('target')) == '3000' and port.get('protocol', 'tcp') == 'tcp')
            if not duplicate:
                ports.append(port)
        if ports != old_ports:
            if ports:
                service['ports'] = ports
            else:
                service.pop('ports', None)
            issues.append('Remove the duplicate dashboard port binding')
    if app_id == 'willitmod-dev-powpow':
        for name in ('litecoin', 'dogecoin'):
            if name in services and services[name].get('user') != '1000:1000':
                if services[name].get('user') not in (None, 'root', '0', '0:0'):
                    raise RecoveryError('Custom PowPow node ownership requires manual review.')
                services[name]['user'] = '1000:1000'
                issues.append(f'Run {name} as the existing data owner')
    return value, issues


class Engine:
    def __init__(self, app_path, catalog, emit=lambda event: None):
        self.home = Path(app_path)
        if not self.home.is_absolute() or self.home.name != SELF or self.home.parent.name != 'app-data':
            raise RecoveryError('The installed Fumbrel path is invalid.')
        if self.home.resolve() != self.home or not self.home.is_dir():
            raise RecoveryError('Fumbrel must use its regular Umbrel app-data directory.')
        self.root = self.home.parent.parent
        if not (self.root / 'umbrel.yaml').is_file():
            raise RecoveryError('Umbrel configuration was not found at the expected location.')
        self.catalog = catalog
        self.emit = emit
        self.backups = self.home / 'data' / 'backups'
        self.cli = shutil.which('umbreld') or '/usr/local/bin/umbreld'

    def installed(self):
        config = yaml_load((self.root / 'umbrel.yaml').read_bytes())
        apps = config.get('apps', [])
        if not isinstance(apps, list) or not all(isinstance(x, str) for x in apps):
            raise RecoveryError('Umbrel installed-app registry is not recognized.')
        return apps

    def appdir(self, app_id):
        if app_id not in self.catalog['apps'] or app_id == SELF or app_id not in self.installed():
            raise RecoveryError('Only installed, supported WillItMod apps can be recovered.')
        folder = self.root / 'app-data' / app_id
        if folder.resolve() != folder or not folder.is_dir():
            raise RecoveryError('App definition path is not a regular directory.')
        return folder

    def target(self, app_id):
        entry = self.catalog['apps'][app_id]
        files = {}
        for name, record in entry['files'].items():
            if not allowed(name):
                raise RecoveryError('Bundled package includes an unapproved file.')
            body = base64.b64decode(record['body'], validate=True)
            if digest(body) != record['sha256'] or len(body) > MAX_FILE:
                raise RecoveryError('Bundled package failed its integrity check.')
            # Preserve MAIN identity where the DEV package uses a different ID.
            if app_id != entry['source_id']:
                body = body.replace(entry['source_id'].encode(), app_id.encode())
            files[name] = body
        manifest = yaml_load(files['umbrel-app.yml'])
        manifest['id'] = app_id
        files['umbrel-app.yml'] = yaml_dump(manifest)
        for name in ('docker-compose.yml', 'docker-compose.yml.template'):
            if name in files:
                fixed, _ = fix_compose(yaml_load(files[name]), app_id)
                files[name] = yaml_dump(fixed)
        # Umbrel templates render at start. Its pre-start patch must also see
        # the Umbrel definition (AxeBC2's base Compose targets another platform).
        if 'docker-compose.yml.template' in files:
            files['docker-compose.yml'] = files['docker-compose.yml.template']
        return files

    def repair_plan(self, app_id):
        folder = self.appdir(app_id)
        changes, issues = {}, []
        entry = self.catalog['apps'][app_id]
        exports = read_file(folder, 'exports.sh')
        target_exports = entry['files'].get('exports.sh')
        if exports is not None:
            known_good = target_exports and digest(exports) == target_exports['sha256']
            if digest(exports) in self.catalog['legacy_exports'] and target_exports:
                changes['exports.sh'] = base64.b64decode(target_exports['body'])
                issues.append('Repair legacy auth lookup that blocks start, stop and update')
            elif not known_good:
                raise RecoveryError('Unrecognized exports.sh. Repair & update can replace it with the bundled package.')
        for name in ('docker-compose.yml', 'docker-compose.yml.template'):
            body = read_file(folder, name)
            if body:
                fixed, found = fix_compose(yaml_load(body), app_id)
                if found:
                    changes[name] = yaml_dump(fixed)
                    issues.extend(found)
        return changes, list(dict.fromkeys(issues))

    def scan(self):
        rows = []
        for app_id in sorted(set(self.installed()) & self.catalog['apps'].keys()):
            entry = self.catalog['apps'][app_id]
            row = {'id': app_id, 'name': entry['name'], 'target': entry['version'], 'channel': entry['channel'],
                   'source_commit': entry['source_commit'], 'installed': 'unknown', 'issues': [], 'can_update': False}
            try:
                folder = self.appdir(app_id)
                manifest = yaml_load(read_file(folder, 'umbrel-app.yml'))
                row['installed'] = str(manifest['version'])
                row['can_update'] = not is_newer(row['installed'], entry['version'])
                row['main_identity'] = app_id != entry['source_id']
                try:
                    _, row['issues'] = self.repair_plan(app_id)
                    row['can_repair'] = True
                except RecoveryError as error:
                    row['issues'] = [str(error)]
                    row['can_repair'] = False
                if not row['can_update']:
                    row['issues'].append('Installed version is newer than this recovery package; downgrade blocked')
                row['running'] = bool(self.running(app_id))
            except (RecoveryError, KeyError, TypeError, ValueError):
                row.update(can_repair=False, can_update=False, issues=['Installed metadata needs manual review'])
            rows.append(row)
        return {'apps': rows, 'release': self.catalog['release'], 'backups': self.list_backups(),
                'scope': 'Installed WillItMod apps only. Unrecognized failures and CPU instruction crashes require separate diagnosis.'}

    def metadata_names(self, folder):
        names = set()
        for p in folder.iterdir():
            if p.name == 'hooks':
                if p.is_symlink():
                    raise RecoveryError('Hooks directory is a symlink; manual review is required.')
                if p.exists():
                    for child in p.rglob('*'):
                        if child.is_symlink():
                            raise RecoveryError('Hooks contain a symlink; manual review is required.')
                        if child.is_file():
                            names.add(child.relative_to(folder).as_posix())
            elif allowed(p.name):
                names.add(p.name)
        for name in names:
            safe_path(folder, name)
        return names

    def backup(self, app_id, names):
        folder = self.appdir(app_id)
        # Backups live below Fumbrel only, not below the app being repaired.
        for p in (self.home / 'data', self.backups):
            if p.is_symlink():
                raise RecoveryError('Backup directory cannot be a symlink.')
            p.mkdir(mode=0o700, parents=True, exist_ok=True)
        os.chmod(self.backups, 0o700)
        backup_id = uuid.uuid4().hex
        destination = self.backups / backup_id
        destination.mkdir(mode=0o700)
        records = {}
        for name in sorted(names):
            path = safe_path(folder, name)
            if path.exists():
                body, info = path.read_bytes(), path.stat()
                records[name] = {'body': base64.b64encode(body).decode(), 'sha256': digest(body),
                                 'mode': stat.S_IMODE(info.st_mode), 'uid': info.st_uid, 'gid': info.st_gid}
            else:
                records[name] = None
        record = {'id': backup_id, 'app': app_id, 'created': int(time.time()), 'phase': 'backup-complete', 'files': records}
        self.save_backup(record)
        return record

    def save_backup(self, record):
        atom_write(self.backups / record['id'] / 'index.json', yaml_dump(record), 0o600)

    def list_backups(self):
        if self.backups.is_symlink():
            raise RecoveryError('Backup directory cannot be a symlink.')
        rows = []
        if self.backups.exists():
            for p in self.backups.iterdir():
                if p.is_symlink() or not re.fullmatch(r'[a-f0-9]{32}', p.name):
                    continue
                index = p / 'index.json'
                if index.is_symlink() or not index.is_file() or index.stat().st_size > 16 * MAX_FILE:
                    continue
                record = json.loads(index.read_text())
                rows.append({k: record[k] for k in ('id', 'app', 'created', 'phase')})
        return sorted(rows, key=lambda row: row['created'], reverse=True)

    def step(self, app_id, message):
        self.emit({'type': 'step', 'app': app_id, 'message': message})

    def running(self, app_id):
        ids = command(['docker', 'ps', '-q', '--filter', 'label=com.docker.compose.project=' + app_id]).split()
        if not ids:
            return []
        details = json.loads(command(['docker', 'inspect', *ids]))
        return [{'id': d['Id'], 'service': d['Config']['Labels'].get('com.docker.compose.service')}
                for d in details if d['State']['Running'] or d['State'].get('Paused')]

    def lifecycle(self, app_id, action):
        if action not in ('start', 'stop'):
            raise RecoveryError('Unsupported lifecycle action.')
        command([self.cli, 'client', 'apps.' + action + '.mutate', '--appId', app_id], timeout=1800)

    def stop(self, app_id):
        self.step(app_id, 'Stopping through Umbrel')
        # A failed normal stop is not permission to replace a live node recipe.
        self.lifecycle(app_id, 'stop')
        remaining = self.running(app_id)
        for container in remaining:
            if container['service'] == 'app_proxy':
                self.step(app_id, 'Removing the obsolete legacy dashboard proxy')
                command(['docker', 'stop', '--time', '20', container['id']], timeout=40)
                command(['docker', 'rm', container['id']])
        if self.running(app_id):
            raise RecoveryError('App containers are still running. No package replacement was performed.')

    def write_changes(self, folder, changes, entry=None):
        for name, body in changes.items():
            path = safe_path(folder, name)
            previous = path.stat() if path.exists() else None
            mode = previous.st_mode & 0o777 if previous else (entry or {}).get('files', {}).get(name, {}).get('mode', 0o644)
            if body is None:
                if path.exists():
                    path.unlink()
            else:
                atom_write(path, body, mode, previous.st_uid if previous else 0, previous.st_gid if previous else 0)

    def recover(self, app_id, mode, start):
        if mode not in ('repair', 'update') or not isinstance(start, bool):
            raise RecoveryError('Invalid recovery options.')
        folder = self.appdir(app_id)
        entry = self.catalog['apps'][app_id]
        installed = str(yaml_load(read_file(folder, 'umbrel-app.yml'))['version'])
        if mode == 'update' and is_newer(installed, entry['version']):
            raise RecoveryError('Downgrades are blocked. Install a newer Fumbrel release first.')
        if mode == 'update':
            target = self.target(app_id)
            # Only exports is replaced before stop; all other metadata waits
            # until normal Umbrel stop has completed and no nodes are running.
            bootstrap = {}
            if 'exports.sh' in target and read_file(folder, 'exports.sh') != target['exports.sh']:
                bootstrap['exports.sh'] = target['exports.sh']
            names = self.metadata_names(folder) | set(target)
            changes = {name: target.get(name) for name in names}
        else:
            changes, _ = self.repair_plan(app_id)
            bootstrap = {name: body for name, body in changes.items() if name == 'exports.sh'}
            names = self.metadata_names(folder) | set(changes)
        record = self.backup(app_id, names)
        self.emit({'type': 'backup', 'app': app_id, 'backup': record['id']})
        try:
            record['phase'] = 'bootstrapping-stop'
            self.save_backup(record)
            self.write_changes(folder, bootstrap)
            self.stop(app_id)
            record['phase'] = 'applying-recipe'
            self.save_backup(record)
            self.step(app_id, 'Applying verified package' if mode == 'update' else 'Applying compatibility repairs')
            self.write_changes(folder, changes, entry)
            record['phase'] = 'recipe-applied'
            self.save_backup(record)
            if start:
                record['phase'] = 'starting'
                self.save_backup(record)
                self.step(app_id, 'Starting through Umbrel; normal app migrations may run')
                self.lifecycle(app_id, 'start')
                if not self.running(app_id):
                    raise RecoveryError('Umbrel returned from start but no app containers are running.')
            record['phase'] = 'complete-started' if start else 'complete-stopped'
            self.save_backup(record)
            return {'app': app_id, 'ok': True, 'backup': record['id'], 'state': 'started' if start else 'stopped',
                    'version': entry['version'] if mode == 'update' else installed}
        except Exception:
            # Deliberately retain the checkpoint. Never auto-restore an old
            # binary after a new binary could have migrated persistent data.
            record['phase'] = 'needs-review-' + record['phase']
            self.save_backup(record)
            raise

    def restore(self, backup_id):
        if not re.fullmatch(r'[a-f0-9]{32}', backup_id):
            raise RecoveryError('Invalid backup identifier.')
        candidates = {row['id']: row for row in self.list_backups()}
        if backup_id not in candidates:
            raise RecoveryError('Backup not found.')
        record = json.loads((self.backups / backup_id / 'index.json').read_text())
        app_id = record['app']
        folder = self.appdir(app_id)
        if self.running(app_id):
            raise RecoveryError('Stop the app in Umbrel before restoring a recipe backup.')
        files = record['files']
        for name, item in files.items():
            safe_path(folder, name)
            if item:
                body = base64.b64decode(item['body'], validate=True)
                if digest(body) != item['sha256'] or len(body) > MAX_FILE:
                    raise RecoveryError('Backup integrity check failed.')
        current = self.backup(app_id, set(files) | self.metadata_names(folder))
        for name, item in files.items():
            path = safe_path(folder, name)
            if item:
                atom_write(path, base64.b64decode(item['body']), item['mode'], item['uid'], item['gid'])
            elif path.exists():
                path.unlink()
        record['phase'] = 'restored-stopped'
        self.save_backup(record)
        return {'app': app_id, 'ok': True, 'state': 'stopped', 'backup': current['id'],
                'message': 'Recipe restored. App data was not rolled back. Review compatibility before starting.'}


def main():
    def emit(event):
        print(json.dumps(event), flush=True)
    try:
        # With passwordless sudo, the password line remains unread on stdin.
        prefix = 'FUMBREL_REQUEST_V1:'
        line = sys.stdin.readline()
        if not line.startswith(prefix):
            line = sys.stdin.readline()
        if not line.startswith(prefix):
            raise RecoveryError('Invalid recovery request framing.')
        request = json.loads(line[len(prefix):])
        if os.geteuid() != 0:
            raise RecoveryError('Administrator access through sudo is required.')
        engine = Engine(request['app_path'], request['catalog'], emit)
        lock_path = engine.home / '.fumbrel-recovery.lock'
        if lock_path.is_symlink():
            raise RecoveryError('Recovery lock cannot be a symlink.')
        fd = os.open(lock_path, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
        with os.fdopen(fd, 'w') as lock:
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                raise RecoveryError('Another Fumbrel recovery is running. Wait for it to finish.') from None
            action = request['action']
            if action == 'scan':
                result = engine.scan()
            elif action == 'recover':
                result = engine.recover(request['app'], request['mode'], request['start'])
            elif action == 'restore':
                result = engine.restore(request['backup'])
            else:
                raise RecoveryError('Unsupported recovery action.')
            emit({'type': 'result', 'result': result})
    except RecoveryError as error:
        emit({'type': 'error', 'message': str(error)})
        return 1
    except Exception:
        emit({'type': 'error', 'message': 'Recovery stopped on an unexpected host condition. Existing recipe backups are retained.'})
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
