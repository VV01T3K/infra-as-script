"""Run the real Ansible workflow with local substitutes for host operations."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
import yaml
from support import copy_repository, environment


ROLE_TASKS = {'verify-services': ('controller', 'health'), 'pause-gitops': ('arcane', 'pause'), 'backup': ('proxmox', 'backup_guest'), 'backup-host': ('proxmox', 'backup_host'), 'update-packages': ('maintenance', 'packages'), 'arcane': ('arcane', 'configure'), 'gitops': ('arcane', 'sync'), 'technitium-config': ('technitium', 'configure'), 'ready': ('proxmox', 'ready'), 'maintenance-backup': ('controller', 'backup'), 'bootstrap-gitops': ('arcane', 'github_key'), 'technitium': ('technitium', 'prepare')}


class UpdateTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.project = self.root / "repo"
        self.backups = self.root / "backups"
        self.backups.mkdir()
        self.bin = self.root / "bin"
        self.bin.mkdir()
        self.ansible = copy_repository(self.project)
        self.lock = self.project / "secrets/proxmox/maintenance.lock.d"
        self.events = self.root / "events"
        # Keep real orchestration, variable propagation, gating, locks, and manifests.
        # Substitute only operations that would contact hosts or external services.
        for name in ['verify-services', 'pause-gitops', 'backup', 'backup-host',
                     'update-packages', 'arcane', 'gitops', 'technitium-config', 'ready',
                     'maintenance-backup', 'bootstrap-gitops', 'technitium']:
            tasks = [
                {'name': 'Record operation', 'ansible.builtin.shell':
                    'printf "%s\\n" "$EVENT_NAME" >> "$EVENTS"; cat "$EVENTS"',
                 'environment': {'EVENT_NAME': name}, 'register': 'recorded_events', 'changed_when': False},
                {'name': 'Inject operation failure', 'ansible.builtin.fail': {'msg': 'Synthetic failure'},
                 'when': "lookup('env', 'FAIL_AT') == '" + name + "'"},
            ]
            if name == 'verify-services':
                tasks.append({'ansible.builtin.fail': {'msg': 'Synthetic final health failure'},
                    'when': "lookup('env', 'FAIL_FINAL_HEALTH') == '1' and "
                            "recorded_events.stdout_lines | select('equalto', 'verify-services') | list | length == 3"})
            if name == 'gitops':
                tasks.append({'ansible.builtin.assert': {'that': "expected_git_commit == '"+'a'*40+"'"},
                              'when': 'maintenance_target is defined'})
            play = {'name': name, 'hosts': 'pve' if name in ['backup', 'backup-host'] else 'localhost',
                    'connection': 'local', 'gather_facts': False, 'tasks': tasks}
            role, task = ROLE_TASKS[name]
            (self.ansible / 'roles' / role / 'tasks' / (task + '.yml')).write_text(yaml.safe_dump(tasks, sort_keys=False))
        for role, task in [('technitium', 'verify'), ('maintenance', 'recover_guest')]:
            (self.ansible / 'roles' / role / 'tasks' / (task + '.yml')).write_text('- ansible.builtin.command: "true"\n  changed_when: false\n')
        # Gathered host facts are part of the substituted remote operations.
        for path in (self.ansible / 'playbooks').glob('*.yml'):
            plays = yaml.safe_load(path.read_text())
            for play in plays:
                play['gather_facts'] = False
                play['tasks'] = [t for t in play.get('tasks', []) if 'ansible.builtin.setup' not in t]
            path.write_text(yaml.safe_dump(plays, sort_keys=False))
        mock = """#!/usr/bin/env python3
import json, os, pathlib, sys
args = sys.argv[1:]
if pathlib.Path(sys.argv[0]).name == 'tofu':
    print(json.dumps({'ip': '10.0.0.77', 'lxc_id': 207}))
elif '--show-toplevel' in args: print(os.environ['REPO'])
elif 'status' in args: print(os.environ.get('DIRTY', ''), end='')
elif 'ls-remote' in args: print(os.environ.get('REMOTE', 'a'*40) + '\\trefs/heads/main')
else: print('a'*40)
"""
        for name in ['git', 'tofu']:
            path = self.bin / name
            path.write_text(mock)
            path.chmod(0o700)
        self.env = environment(self.project, PATH=str(self.bin)+":"+os.environ['PATH'],
                        REPO=str(self.project), EVENTS=str(self.events), ANSIBLE_NOCOLOR='1')

    def run_update(self, target, **overrides):
        variables = {'maintenance_target': target, 'backup_storage': 'off-host',
                     'controller_backup_dir': str(self.backups), 'backup_passphrase': 'test-only'}
        name = 'pause' if target == 'pause-gitops' else 'update'
        result = subprocess.run(['ansible-playbook', '-i', str(self.project / 'inventory/hosts.yml'),
            str(self.ansible / 'playbooks' / (name+'.yml')), '-e', json.dumps(variables)],
            env=dict(self.env, **overrides), capture_output=True, text=True)
        return result, self.events.read_text().splitlines() if self.events.exists() else []

    def reset_run(self):
        self.events.unlink(missing_ok=True)
        if self.lock.exists(): shutil.rmtree(self.lock)

    def test_each_update_backs_up_before_mutation_and_checks_health_after(self):
        for target, operation in [('guest', 'update-packages'), ('host', 'update-packages'),
                                 ('arcane', 'arcane'), ('technitium', 'gitops')]:
            with self.subTest(target=target):
                self.reset_run()
                result, events = self.run_update(target)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                self.assertLess(events.index('maintenance-backup'), events.index('backup'))
                self.assertLess(events.index('pause-gitops'), events.index('backup'))
                self.assertLess(events.index('backup'), events.index(operation))
                self.assertEqual(events[-1], 'verify-services')
                if target == 'host': self.assertLess(events.index('backup-host'), events.index(operation))
                manifest = next(self.backups.glob(f'update-{target}-*/manifest.txt')).read_text()
                self.assertIn('verified=true', manifest)
                self.assertFalse(self.lock.exists())

    def test_failed_backup_blocks_update_across_host_boundaries(self):
        for failure in ['maintenance-backup', 'backup', 'backup-host']:
            with self.subTest(failure=failure):
                self.reset_run()
                result, events = self.run_update('host', FAIL_AT=failure)
                self.assertNotEqual(result.returncode, 0)
                self.assertNotIn('update-packages', events)
                self.assertTrue(self.lock.exists())

    def test_failed_update_is_not_reported_as_verified(self):
        result, events = self.run_update('guest', FAIL_AT='update-packages')
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(events[-1], 'update-packages')
        self.assertNotIn('verified=true', next(self.backups.glob('*/manifest.txt')).read_text())

    def test_unpublished_revision_blocks_technitium_update(self):
        result, events = self.run_update('technitium', REMOTE='b'*40)
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(events, [])

    def test_failed_final_health_check_is_not_marked_verified(self):
        result, events = self.run_update('guest', FAIL_FINAL_HEALTH='1')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('update-packages', events)
        self.assertEqual(events[-1], 'verify-services')
        self.assertNotIn('verified=true', next(self.backups.glob('*/manifest.txt')).read_text())

    def test_concurrent_maintenance_is_rejected(self):
        self.lock.mkdir(parents=True)
        result, events = self.run_update('pause-gitops')
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(events, [])

    def test_dirty_checkout_blocks_update(self):
        result, events = self.run_update('arcane', DIRTY=' M arcane.yml')
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(events, [])

    def test_deployment_uses_shared_lock_and_stops_on_failure(self):
        command = ['ansible-playbook', '-i', str(self.project / 'inventory/hosts.yml'),
                   str(self.ansible / 'playbooks/deploy.yml')]
        success = subprocess.run(command, env=self.env, capture_output=True, text=True)
        self.assertEqual(success.returncode, 0, success.stdout + success.stderr)
        self.assertEqual(self.events.read_text().splitlines(),
                         ['bootstrap-gitops', 'arcane', 'technitium', 'gitops',
                          'technitium-config', 'verify-services'])
        self.assertFalse(self.lock.exists())
        self.reset_run()
        failure = subprocess.run(command, env=dict(self.env, FAIL_AT='arcane'),
                                 capture_output=True, text=True)
        self.assertNotEqual(failure.returncode, 0)
        self.assertEqual(self.events.read_text().splitlines(), ['bootstrap-gitops', 'arcane'])
        self.assertTrue(self.lock.exists())
        blocked, events = self.run_update('pause-gitops')
        self.assertNotEqual(blocked.returncode, 0)
        self.assertEqual(events, ['bootstrap-gitops', 'arcane'])

    def test_pause_does_not_back_up_or_deploy(self):
        result, events = self.run_update('pause-gitops', DIRTY=' M arcane.yml')
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(events, ['pause-gitops'])


if __name__ == '__main__':
    unittest.main()
