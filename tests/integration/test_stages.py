"""Exercise stage boundaries without contacting the real server."""
import importlib.util
from pathlib import Path
import subprocess
import tempfile
import tomllib
import unittest
import yaml
from support import REPOSITORY, copy_repository, environment


class StageTests(unittest.TestCase):
    def test_installer_reuses_credentials_and_regeneration_stays_in_its_folder(self):
        spec = importlib.util.spec_from_file_location('installer', REPOSITORY / 'stages/01-install/prepare.py')
        installer = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(installer)
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            destination = root / 'secrets/installer/pve'
            profile = REPOSITORY / 'stages/01-install/profiles/old-laptop.example.toml'
            answer = installer.prepare(profile, destination)
            original = answer.read_bytes()
            key = (destination / 'bootstrap').read_bytes()
            installer.prepare(profile, destination)
            self.assertEqual(answer.read_bytes(), original)
            self.assertEqual((destination / 'bootstrap').read_bytes(), key)
            installer.prepare(profile, destination, regenerate=True)
            self.assertNotEqual((destination / 'bootstrap').read_bytes(), key)
            parsed = tomllib.loads(answer.read_text())
            self.assertTrue(parsed['global']['root-password-hashed'].startswith('$6$'))
            self.assertEqual(parsed['global']['root-ssh-keys'], [(destination / 'bootstrap.pub').read_text().strip()])
            self.assertEqual([p.name for p in (root / 'secrets').iterdir()], ['installer'])
            self.assertTrue(any(p.read_bytes() == key for p in (destination / 'history').iterdir()))

    def test_system_update_needs_no_guest_state_and_requires_a_target(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            copy_repository(root)
            (root / 'jobs').mkdir()
            plays = yaml.safe_load((REPOSITORY / 'jobs/update-system.yml').read_text())
            plays[1]['gather_facts'] = False
            plays[1]['become'] = False
            (root / 'jobs/update-system.yml').write_text(yaml.safe_dump(plays))
            (root / 'ansible/roles/maintenance/tasks/packages.yml').write_text(
                '- ansible.builtin.copy:\n    dest: "{{ repo_root }}/updated"\n    content: done\n')
            command = ['ansible-playbook', str(root / 'jobs/update-system.yml')]
            rejected = subprocess.run(command, env=environment(root), capture_output=True, text=True)
            self.assertNotEqual(rejected.returncode, 0)
            self.assertFalse((root / 'updated').exists())
            result = subprocess.run(command + ['-e', 'system_update_hosts=pve'],
                                    env=environment(root), capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertTrue((root / 'updated').exists())
            self.assertFalse((root / 'secrets/proxmox/maintenance.lock.d').exists())
