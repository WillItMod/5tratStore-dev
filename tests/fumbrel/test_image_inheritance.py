"""Reject actual artifact contracts which broaden the two-file COPY change."""
import ast
import contextlib
import copy
import hashlib
import importlib.util
import io
from pathlib import Path
import tarfile
import unittest
from unittest import mock
import json
import sys
import tempfile

ROOT=Path(__file__).resolve().parents[2]
spec=importlib.util.spec_from_file_location('fumbrel_image_verify',ROOT/'scripts/fumbrel/verify_image.py')
verify=importlib.util.module_from_spec(spec);spec.loader.exec_module(verify)
COMMIT='a'*40


def layer(files,mode=0o644,kind=None):
    out=io.BytesIO()
    with tarfile.open(fileobj=out,mode='w') as tar:
        for name,body in files:
            entry=tarfile.TarInfo(name);entry.mode=mode;entry.size=len(body)
            if kind is not None:entry.type=kind
            tar.addfile(entry,io.BytesIO(body))
    return out.getvalue()


class ImageInheritanceTests(unittest.TestCase):
    def setUp(self):
        self.expected={'engine.py':b'reviewed engine','catalog.json':b'reviewed catalog'}
        self.files=[('app/'+name,body)for name,body in self.expected.items()]
        self.layer=layer(self.files)
        self.base={'architecture':'amd64','os':'linux','rootfs':{'diff_ids':['sha256:'+'b'*64]},
                   'config':{'User':'1000:1000','Env':['UNCHANGED=1'],'Cmd':['gunicorn'],
                             'Labels':{'retained':'value'}}}
        self.new=copy.deepcopy(self.base)
        self.new['rootfs']['diff_ids'].append(verify.digest(self.layer))
        self.new['config']['Labels'].update({'org.opencontainers.image.source':'https://github.com/WillItMod/5tratStore-dev',
            'org.opencontainers.image.revision':COMMIT,'org.opencontainers.image.version':verify.RELEASE,
            'org.opencontainers.image.base.digest':verify.BASE_DIGEST})

    def check(self,body=None):
        return verify.check_contract(self.base,self.new,self.layer if body is None else body,self.expected,COMMIT)

    def test_real_runtime_probe_respects_client_guard_before_missing_host_key(self):
        tree=ast.parse((ROOT/'scripts/fumbrel/verify_image.py').read_text())
        function=next(node for node in tree.body if isinstance(node,ast.FunctionDef) and node.name=='verify')
        code=next(node.value.value for node in function.body if isinstance(node,ast.Assign)
                  and any(isinstance(t,ast.Name) and t.id=='code' for t in node.targets))
        sys.path.insert(0,str(ROOT/'willitmod-dev-fumbrel/app'))
        import server
        # Actual Flask routes and guards; no host key, SSH, credentials or fake endpoint.
        body=io.StringIO()
        with tempfile.TemporaryDirectory() as folder, mock.patch.object(server,'KEY_FILE',Path(folder)/'absent-public-key'):
            with contextlib.redirect_stdout(body):
                # Use the genuine source app files in this local regression. The
                # native image proof executes the unchanged paths inside /app.
                exec(code.replace("'/app/static'",repr(str(server.BASE/'static')))
                         .replace("'/app'",repr(str(server.BASE))),{})
        result=json.loads(body.getvalue())
        self.assertEqual(result['health_status'],200)
        self.assertEqual(result['ui_status'],200)
        self.assertEqual(result['info_status_without_client_header'],403)
        self.assertEqual(result['info_status_without_host_key'],400)

    def test_only_exact_two_reviewed_files_and_retained_runtime_pass(self):
        self.assertEqual(set(self.check()),{'app/engine.py','app/catalog.json'})

    def test_unrelated_runtime_or_base_layer_change_refuses(self):
        for section,key,value in [('config','User','0:0'),('config','Cmd',['different']),('rootfs','diff_ids',['different',verify.digest(self.layer)])]:
            with self.subTest(key=key):
                original=copy.deepcopy(self.new[section][key]);self.new[section][key]=value
                with self.assertRaises(ValueError):self.check()
                self.new[section][key]=original

    def test_wrong_source_base_or_unrelated_label_refuses(self):
        for key,value in [('org.opencontainers.image.revision','c'*40),('org.opencontainers.image.base.digest','sha256:'+'d'*64),('retained','changed')]:
            with self.subTest(key=key):
                old=self.new['config']['Labels'][key];self.new['config']['Labels'][key]=value
                with self.assertRaises(ValueError):self.check()
                self.new['config']['Labels'][key]=old

    def test_extra_file_whiteout_path_link_and_duplicate_refuse(self):
        cases=[self.files+[('app/server.py',b'changed')],self.files+[('app/.wh.server.py',b'')],
               self.files+[('../escape',b'')],self.files+[self.files[0]]]
        for files in cases:
            with self.subTest(files=[n for n,_ in files]):
                body=layer(files);self.new['rootfs']['diff_ids'][-1]=verify.digest(body)
                with self.assertRaises(ValueError):self.check(body)
        body=layer(self.files,kind=tarfile.SYMTYPE);self.new['rootfs']['diff_ids'][-1]=verify.digest(body)
        with self.assertRaises(ValueError):self.check(body)

    def test_wrong_file_mode_bytes_or_actual_layer_digest_refuse(self):
        for body in [layer(self.files,mode=0o755),layer([('app/engine.py',b'wrong'),self.files[1]])]:
            self.new['rootfs']['diff_ids'][-1]=verify.digest(body)
            with self.assertRaises(ValueError):self.check(body)
        self.new['rootfs']['diff_ids'][-1]='sha256:'+'f'*64
        with self.assertRaises(ValueError):self.check()


if __name__=='__main__':unittest.main()
