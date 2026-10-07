#!/usr/bin/env python3
"""Check the real Ansible precedence and preflight ordering behind Frog cutover."""
from pathlib import Path
import subprocess
import tempfile

import yaml

repo = Path(__file__).resolve().parent.parent
play = yaml.safe_load((repo / 'operations/migrate-frog.yml').read_text())[0]
tasks = play['tasks']
flag = next(task for task in tasks if task.get('ansible.builtin.set_fact', {}).get('gitops_sync_now') is True)
sync = next(task for task in tasks if task['name'] == 'Sync only Frog and inject its preserved settings')
build = next(task for task in tasks if task['name'] == 'Build the replacement image')
cutover = next(task for task in tasks if 'block' in task)
assert tasks.index(flag) < tasks.index(sync) < tasks.index(build) < tasks.index(cutover)

check = [{
    'name': 'Check required Frog sync against Ansible variable precedence',
    'hosts': 'localhost',
    'connection': 'local',
    'gather_facts': False,
    'vars': play['vars'],
    'vars_files': [str(repo / 'stages/5-services/gitops-config.yml')],
    'tasks': [
        {'name': 'Confirm the config disables sync by default',
         'ansible.builtin.assert': {'that': 'not gitops_sync_now | bool', 'quiet': True}},
        flag,
        {'name': 'Require the actual migration task to override that default',
         'ansible.builtin.assert': {'that': 'gitops_sync_now | bool', 'quiet': True}},
    ],
}]
with tempfile.TemporaryDirectory() as directory:
    path = Path(directory) / 'check.yml'
    path.write_text(yaml.safe_dump(check, sort_keys=False))
    subprocess.run(['ansible-playbook', '-i', 'localhost,', str(path)], cwd=repo, check=True)
print('PASS: required sync overrides the config; sync and build precede source downtime.')
