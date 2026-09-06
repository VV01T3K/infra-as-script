"""Exercise native Ansible inventory loading with synthetic OpenTofu output."""
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
import yaml
from support import copy_repository, environment, role_playbook


class InventoryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.repo = Path(self.temp.name) / 'repo'
        copy_repository(self.repo)
        self.playbook = role_playbook(self.repo, 'controller', 'inventory')
        plays = yaml.safe_load(self.playbook.read_text())
        self.output = Path(self.temp.name) / 'inventory.json'
        plays[0]['tasks'].append({'ansible.builtin.copy': {
            'dest': str(self.output),
            'content': '{{ {"ip": hostvars["arcane"].ansible_host, "lxc_id": hostvars["arcane"].lxc_id} | to_json }}',
        }})
        self.playbook.write_text(yaml.safe_dump(plays, sort_keys=False))
        binaries = Path(self.temp.name) / 'bin'
        binaries.mkdir()
        command = binaries / 'tofu'
        command.write_text('#!/usr/bin/env python3\nimport os,sys\n'
                           'if os.environ.get("TOFU_FAIL"):\n'
                           '    print("private diagnostic",file=sys.stderr);sys.exit(1)\n'
                           'print(os.environ["TOFU_OUTPUT"])\n')
        command.chmod(0o700)
        self.env = environment(self.repo, PATH=str(binaries)+':'+os.environ['PATH'])

    def run_inventory(self, state, **overrides):
        self.output.unlink(missing_ok=True)
        result = subprocess.run(['ansible-playbook', str(self.playbook)],
            env=dict(self.env, TOFU_OUTPUT=state, **overrides), capture_output=True, text=True)
        return result

    def test_uses_applied_address_and_guest_id(self):
        result = self.run_inventory('{"ip":"10.0.0.77","lxc_id":207}')
        self.assertEqual(result.returncode, 0, result.stdout+result.stderr)
        self.assertEqual(json.loads(self.output.read_text()), {'ip':'10.0.0.77','lxc_id':207})

    def test_invalid_or_missing_state_never_emits_inventory(self):
        for state in ['{}', 'not JSON', '{"ip":"invalid","lxc_id":200}',
                      '{"ip":"10.0.0.60","lxc_id":1}', '{"ip":"999.0.0.1","lxc_id":200}',
                      '{"ip":"010.0.0.1","lxc_id":200}', '{"ip":"10.0.0.1","lxc_id":true}']:
            with self.subTest(state=state):
                result = self.run_inventory(state)
                self.assertNotEqual(result.returncode, 0)
                self.assertFalse(self.output.exists())

    def test_tofu_failure_is_not_silently_replaced_with_default_ip(self):
        result = self.run_inventory('{}', TOFU_FAIL='1')
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(self.output.exists())
        self.assertNotIn('private diagnostic', result.stdout+result.stderr)


if __name__ == '__main__':
    unittest.main()
