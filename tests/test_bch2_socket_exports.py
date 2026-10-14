"""Regression for the actual non-root Unix socket capability and caller context."""
from pathlib import Path
import os,socket,subprocess,tempfile,textwrap,unittest
ROOT=Path(__file__).resolve().parents[1]
SOURCE=ROOT/'willitmod-dev-axebch2/exports.sh'
class Bch2SocketExportsTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory(prefix='bch2-socket-');self.root=Path(self.tmp.name);self.path=self.root/'docker.sock';self.sock=socket.socket(socket.AF_UNIX,socket.SOCK_STREAM);self.sock.bind(str(self.path));os.chmod(self.path,0o660)
  self.export=self.root/'exports.sh';s=SOURCE.read_text();assert s.count('/var/run/docker.sock')==2;self.export.write_text(s.replace('/var/run/docker.sock',str(self.path)))
  self.bin=self.root/'bin';self.bin.mkdir();p=self.bin/'stat';p.write_text('#!/usr/bin/env python3\nimport os,sys\np=sys.argv[-1]\ns=os.stat(p)\nprint(os.environ.get("TEST_STAT",format(s.st_mode & 0o7777,"o")+":"+str(s.st_gid)))\n');p.chmod(0o755)
 def tearDown(self):self.sock.close();self.tmp.cleanup()
 def run_source(self,metadata=None,strict=True):
  env=dict(os.environ,PATH=str(self.bin)+':'+os.environ['PATH'],AXEBCH2_DOCKER_GID='0')
  if metadata is not None:env['TEST_STAT']=metadata
  script=('set -euo pipefail'if strict else'set +e; set +u; set +o pipefail')+'\nbefore="$-"; pf="$(set -o | awk \'$1=="pipefail"{print $2}\')"\nsource "$1"\n[[ "$before" == "$-" ]] || exit 91\n[[ "$pf" == "$(set -o | awk \'$1=="pipefail"{print $2}\')" ]] || exit 92\n! declare -F _axebch2_export_socket_group >/dev/null || exit 93\nprintf "%s\\n" "${AXEBCH2_DOCKER_GID:-1000}"\n'
  return subprocess.run(['bash','-c',script,'bch2-export-test',str(self.export)],env=env,text=True,capture_output=True)
 def test_actual_existing_socket_group_and_caller_flags(self):
  for strict in [True,False]:
   r=self.run_source(strict=strict);self.assertEqual(r.returncode,0,r.stderr);self.assertEqual(r.stdout.strip(),str(self.path.stat().st_gid))
 def test_umbrel_174_and_200_numeric_groups_are_not_hardcoded(self):
  for gid in ['987','999','104','0','65534']:
   r=self.run_source('660:'+gid);self.assertEqual(r.returncode,0,r.stderr);self.assertEqual(r.stdout.strip(),gid)
 def test_absent_socket_and_regular_file_clear_stale_access(self):
  self.path.unlink()
  for regular in [False,True]:
   if regular:self.path.write_text('not a socket')
   r=self.run_source();self.assertEqual(r.returncode,0,r.stderr);self.assertEqual(r.stdout.strip(),'1000')
 def test_invalid_or_non_group_writable_metadata_never_exports_access(self):
  for raw in ['660:root','660:0\n987','660:-1','660:$(id)','600:987','8888:987','invalid','660:']:
   with self.subTest(raw=raw):
    r=self.run_source(raw);self.assertEqual(r.returncode,0,r.stderr);self.assertEqual(r.stdout.strip(),'1000')
if __name__=='__main__':unittest.main()
