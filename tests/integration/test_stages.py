"""Exercise stage boundaries without contacting the real server."""
import shutil
from pathlib import Path
import subprocess
import tempfile
import tomllib
import unittest
import yaml
from support import REPOSITORY, copy_repository, environment


class StageTests(unittest.TestCase):
    def test_installer_reuses_credentials_and_regeneration_stays_in_its_folder(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            destination = root / 'secrets/installer/pve'
            shutil.copytree(REPOSITORY / 'stages/01-install', root / 'stages/01-install')
            command = ['bash', str(root / 'stages/01-install/prepare.sh')]
            answer = destination / 'answer.toml'
            subprocess.run(command, check=True, capture_output=True)
            original = answer.read_bytes()
            key = (destination / 'bootstrap').read_bytes()
            subprocess.run(command, check=True, capture_output=True)
            self.assertEqual(answer.read_bytes(), original)
            self.assertEqual((destination / 'bootstrap').read_bytes(), key)
            subprocess.run(command + ['--regenerate'], check=True, capture_output=True)
            self.assertNotEqual((destination / 'bootstrap').read_bytes(), key)
            parsed = tomllib.loads(answer.read_text())
            self.assertTrue(parsed['global']['root-password-hashed'].startswith('$6$'))
            self.assertEqual(parsed['global']['root-ssh-keys'], [(destination / 'bootstrap.pub').read_text().strip()])
            self.assertEqual([p.name for p in (root / 'secrets').iterdir()], ['installer'])
            self.assertTrue(any(p.read_bytes() == key for p in (destination / 'history').glob('*/bootstrap')))
            current = {p.name: p.read_bytes() for p in destination.iterdir() if p.is_file()}
            invalid = root / 'invalid.toml'
            invalid.write_text((root / 'stages/01-install/profiles/old-laptop.example.toml').read_text() + '\ninvalid = [\n')
            rejected = subprocess.run(command + ['--regenerate', '--profile', str(invalid)], capture_output=True)
            self.assertNotEqual(rejected.returncode, 0, rejected.stdout.decode() + rejected.stderr.decode())
            self.assertEqual({p.name: p.read_bytes() for p in destination.iterdir() if p.is_file()}, current)
            self.assertEqual(list(destination.glob('.prepare-*')), [])

    def test_post_install_preserves_order_and_stops_before_rotation_on_failure(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            copy_repository(root)
            key = root / 'secrets/proxmox/proxmox_bootstrap'
            key.parent.mkdir(parents=True)
            key.write_text('synthetic existing key')
            operations = [('proxmox', name) for name in ['ready', 'configure', 'access', 'template']]
            operations += [('credentials', name) for name in ['prepare', 'manage']]
            for role, name in operations:
                tasks = [
                    {'ansible.builtin.lineinfile': {'path': '{{ repo_root }}/events', 'line': name, 'create': True}},
                    {'ansible.builtin.fail': {'msg': 'Simulated host failure'},
                     'when': "lookup('env', 'FAIL_AT') == '" + name + "'"},
                ]
                (root / 'ansible/roles' / role / 'tasks' / (name + '.yml')).write_text(yaml.safe_dump(tasks))
            command = ['ansible-playbook', str(root / 'stages/02-post-install/main.yml')]
            result = subprocess.run(command, env=environment(root), capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertEqual((root / 'events').read_text().splitlines(), [name for _, name in operations])
            lock = root / 'secrets/proxmox/maintenance.lock.d'
            self.assertFalse(lock.exists())
            (root / 'events').unlink()
            failed = subprocess.run(command, env=environment(root, FAIL_AT='configure'), capture_output=True, text=True)
            self.assertNotEqual(failed.returncode, 0)
            self.assertEqual((root / 'events').read_text().splitlines(), ['ready', 'configure'])
            self.assertTrue(lock.exists())

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
