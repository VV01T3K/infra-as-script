"""Create isolated repository fixtures for Ansible integration tests."""
import os
from pathlib import Path
import shutil
import yaml

REPOSITORY = Path(__file__).resolve().parents[2]


def copy_repository(destination):
    destination = Path(destination)
    for name in ['ansible', 'inventory', 'scripts']:
        shutil.copytree(REPOSITORY / name, destination / name)
    shutil.copytree(REPOSITORY / 'stages/02-post-install', destination / 'stages/02-post-install')
    shutil.copyfile(REPOSITORY / 'ansible.cfg', destination / 'ansible.cfg')
    (destination / 'stages/03-provision/proxmox').mkdir(parents=True)
    # All fixtures use local fake hosts; never fall back to the real homelab.
    (destination / 'inventory/hosts.yml').write_text(yaml.safe_dump({'all': {'hosts': {
        'pve': {'ansible_connection': 'local', 'ansible_host': '127.0.0.1'},
        'arcane': {'ansible_connection': 'local', 'ansible_host': '127.0.0.1'},
    }}}))
    return destination / 'ansible'


def environment(repository, **overrides):
    return dict(os.environ, ANSIBLE_CONFIG=str(Path(repository) / 'ansible.cfg'), **overrides)


def role_playbook(repository, role, task, name='fixture'):
    path = Path(repository) / 'ansible/playbooks' / (name + '.yml')
    path.write_text(yaml.safe_dump([{
        'name': 'Exercise ' + role + '/' + task,
        'hosts': 'localhost', 'connection': 'local', 'gather_facts': False,
        'tasks': [{'ansible.builtin.import_role': {'name': role, 'tasks_from': task}}],
    }], sort_keys=False))
    return path
