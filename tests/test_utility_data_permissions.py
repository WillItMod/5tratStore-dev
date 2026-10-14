"""Exercise privileged pre-start hooks in disposable Linux filesystems."""
import pathlib
import shutil
import subprocess
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
IMAGE = 'alpine:3.22.1@sha256:4bcff63911fcb4448bd4fdacec207030997caf25e9bea4045fa6c8c44de311d1'
APPS = ['willitmod-dev-axebench', 'willitmod-dev-axelive']


class UtilityDataPermissions(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not shutil.which('docker'):
            raise unittest.SkipTest('Docker is required for real Linux ownership checks')
        result = subprocess.run(['docker', 'info', '--format', '{{.ServerVersion}}'],
                                capture_output=True, text=True, timeout=20)
        if result.returncode:
            raise unittest.SkipTest('Docker daemon is unavailable')

    def exercise(self, app, body):
        hook = ROOT / app / 'hooks/pre-start'
        self.assertTrue(hook.stat().st_mode & 0o111, 'Umbrel must be able to execute the hook')
        result = subprocess.run([
            'docker', 'run', '--rm', '--network', 'none', '--read-only',
            '--label', 'codex.owner=umbrel-utility-hook-regression',
            '--tmpfs', '/tmp:rw,nosuid,nodev,mode=1777',
            '--mount', 'type=bind,src=' + str(hook) + ',dst=/hook,readonly',
            '--entrypoint', '/bin/sh', IMAGE, '-eu', '-c', body,
        ], capture_output=True, text=True, timeout=120)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_absent_mount_created_and_owned(self):
        for app in APPS:
            with self.subTest(app=app):
                self.exercise(app, '''
mkdir /tmp/app
APP_DATA_DIR=/tmp/app /hook
test "$(stat -c '%u:%g' /tmp/app/data)" = 1000:1000
APP_DATA_DIR=/tmp/app /hook
test "$(stat -c '%u:%g' /tmp/app/data)" = 1000:1000
''')

    def test_existing_mount_repaired_without_changing_user_files(self):
        for app in APPS:
            with self.subTest(app=app):
                self.exercise(app, '''
mkdir -p /tmp/app/data/child
printf preserved >/tmp/app/data/child/state
chmod 0640 /tmp/app/data/child/state
APP_DATA_DIR=/tmp/app /hook
test "$(stat -c '%u:%g' /tmp/app/data)" = 1000:1000
test "$(stat -c '%u:%g:%a' /tmp/app/data/child/state)" = 0:0:640
test "$(stat -c '%u:%g' /tmp/app/data/child)" = 0:0
test "$(cat /tmp/app/data/child/state)" = preserved
''')

    def test_symlinks_missing_roots_and_file_mounts_refused(self):
        for app in APPS:
            with self.subTest(app=app):
                self.exercise(app, '''
mkdir -p /tmp/outside /tmp/app
ln -s /tmp/outside /tmp/app/data
if APP_DATA_DIR=/tmp/app /hook; then exit 1; fi
test "$(stat -c '%u:%g' /tmp/outside)" = 0:0
rm /tmp/app/data
ln -s /tmp/outside /tmp/app-link
if APP_DATA_DIR=/tmp/app-link /hook; then exit 1; fi
test ! -e /tmp/outside/data
if APP_DATA_DIR=/tmp/missing /hook; then exit 1; fi
test ! -e /tmp/missing
touch /tmp/app/data
if APP_DATA_DIR=/tmp/app /hook; then exit 1; fi
test -f /tmp/app/data
if /hook; then exit 1; fi
''')


if __name__ == '__main__':
    unittest.main()
