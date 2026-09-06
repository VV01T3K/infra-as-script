"""Run installer preparation against synthetic mounted drives and a fake builder."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest


class UsbTests(unittest.TestCase):
    def test_checksum_and_build_failures_preserve_existing_iso(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            project = root/'repo/proxmox'
            ansible = project/'ansible'
            ansible.mkdir(parents=True)
            source = Path(__file__).resolve().parents[1]/'ansible/prepare-usb.yml'
            shutil.copyfile(source, ansible/source.name)
            (project/'usb/ventoy').mkdir(parents=True)
            (project/'usb/ventoy/ventoy.json').write_text('{}')
            iso = root/'proxmox-ve_9.2-1.iso'
            iso.write_bytes(b'synthetic ISO')
            checksum = project/'usb/SHA256SUMS'
            checksum.write_text('0'*64+'  '+iso.name)
            profile = root/'answer.toml'
            profile.write_text('synthetic profile')
            ventoy, answer = root/'ventoy', root/'answer'
            (ventoy/'ISO').mkdir(parents=True)
            answer.mkdir()
            published = ventoy/'ISO/proxmox-ve_9.2-1-auto.iso'
            published.write_bytes(b'existing ISO')
            binaries = root/'bin'
            binaries.mkdir()
            mock = """#!/usr/bin/env python3
import os, pathlib, sys
name = pathlib.Path(sys.argv[0]).name
args = sys.argv[1:]
if name == 'mountpoint': pass
elif name == 'findmnt': print('synthetic-wsl-drive')
elif args[0] == 'validate-answer': pass
elif args[0] == 'prepare-iso':
    pathlib.Path(args[args.index('--output')+1]).write_bytes(b'built ISO')
    if os.environ.get('FAIL_BUILD'): sys.exit(1)
else: sys.exit(8)
"""
            for name in ['mountpoint','findmnt','proxmox-auto-install-assistant']:
                tool = binaries/name
                tool.write_text(mock)
                tool.chmod(0o700)
            env = dict(os.environ, PATH=str(binaries)+':'+os.environ['PATH'])
            variables = dict(source_iso=str(iso), ventoy_mount=str(ventoy),
                             answer_mount=str(answer), answer_profile=str(profile))
            command = ['ansible-playbook',str(ansible/source.name),'-e',json.dumps(variables)]
            invalid = subprocess.run(command,env=env,capture_output=True,text=True)
            self.assertNotEqual(invalid.returncode,0)
            self.assertEqual(published.read_bytes(),b'existing ISO')
            self.assertFalse((answer/'answer.toml').exists())
            checksum.write_text(hashlib.sha256(iso.read_bytes()).hexdigest()+'  '+iso.name)
            failed = subprocess.run(command,env=dict(env,FAIL_BUILD='1'),capture_output=True,text=True)
            self.assertNotEqual(failed.returncode,0)
            self.assertEqual(published.read_bytes(),b'existing ISO')
            self.assertEqual(list((ventoy/'ISO').glob('.proxmox-build-*')),[])
            success = subprocess.run(command,env=env,capture_output=True,text=True)
            self.assertEqual(success.returncode,0,success.stdout+success.stderr)
            self.assertEqual(published.read_bytes(),b'built ISO')
            self.assertEqual((answer/'answer.toml').read_text(),'synthetic profile')
            self.assertEqual(list((ventoy/'ISO').glob('.proxmox-build-*')),[])


if __name__ == '__main__':
    unittest.main()
