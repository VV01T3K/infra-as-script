"""Exercise deploy-key creation and conflict handling with real SSH keys."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from support import copy_repository, environment, role_playbook


class BootstrapTests(unittest.TestCase):
    def test_key_is_reused_and_conflicting_or_write_keys_are_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            repository = root / 'repo'
            copy_repository(repository)
            playbook = role_playbook(repository, 'arcane', 'github_key')
            binaries = root / 'bin'
            binaries.mkdir()
            gh = binaries / 'gh'
            gh.write_text("""#!/usr/bin/env python3
import json, os, pathlib, sys
args = sys.argv[1:]
state = pathlib.Path(os.environ['KEY_STATE'])
if args[:2] == ['auth', 'status']: pass
elif args[:2] == ['repo', 'view']: print(json.dumps({'isPrivate': True}))
elif args[0] == 'api':
    keys = json.loads(state.read_text()) if state.exists() else []
    if keys and os.environ.get('CONFLICT'): keys[0]['key'] = 'different'
    if keys and os.environ.get('WRITE_KEY'): keys[0]['read_only'] = False
    print(json.dumps([keys]))
elif args[:3] == ['repo', 'deploy-key', 'add']:
    if state.exists(): sys.exit(9)
    state.write_text(json.dumps([{'title': 'arcane-gitops',
        'key': ' '.join(pathlib.Path(args[3]).read_text().split()[:2]), 'read_only': True}]))
else: sys.exit(8)
""")
            gh.chmod(0o700)
            env = environment(repository, PATH=str(binaries)+':'+os.environ['PATH'], KEY_STATE=str(root/'keys'))
            command = ['ansible-playbook', str(playbook)]
            first = subprocess.run(command, env=env, capture_output=True, text=True)
            self.assertEqual(first.returncode, 0, first.stdout+first.stderr)
            key = root / 'repo/secrets/arcane/arcane-gitops'
            original = key.read_bytes()
            second = subprocess.run(command, env=env, capture_output=True, text=True)
            self.assertEqual(second.returncode, 0, second.stdout+second.stderr)
            self.assertEqual(key.read_bytes(), original)
            for override in ['CONFLICT', 'WRITE_KEY']:
                rejected = subprocess.run(command, env=dict(env, **{override:'1'}), capture_output=True, text=True)
                self.assertNotEqual(rejected.returncode, 0)
                self.assertEqual(key.read_bytes(), original)


if __name__ == '__main__':
    unittest.main()
