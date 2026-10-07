#!/usr/bin/env python3
"""Exercise the actual cutover commands with SQL string literals through Ansible."""
from pathlib import Path
import shlex
import subprocess
import tempfile
import yaml

repo = Path(__file__).resolve().parent.parent
play = yaml.safe_load((repo / 'operations/migrate-research-cruise.yml').read_text())[0]
block = next(task['block'] for task in play['tasks'] if 'block' in task)
counts = [task.copy() for task in block if task['name'] in (
    'Capture final row counts from the frozen source',
    'Verify all table row counts before starting application writers',
)]
for task in counts:
    task['delegate_to'] = 'localhost'
prefix = '/usr/bin/python3 -c ' + shlex.quote('import json,sys; print(json.dumps(sys.argv[1:]))')
fixture = [{
    'name': 'Prove SQL literals survive the actual migration commands',
    'hosts': 'localhost', 'connection': 'local', 'gather_facts': False,
    'vars': {'cruise_counts': play['vars']['cruise_counts'],
             'cruise_sql_source': prefix, 'cruise_sql_target': prefix},
    'tasks': counts + [{
        'name': 'Require a single unchanged SQL argument including the dot string literal',
        'ansible.builtin.assert': {
            'that': ['cruise_source_counts.stdout | from_json == [cruise_counts]',
                     'cruise_target_counts.stdout | from_json == [cruise_counts]'],
            'quiet': True,
        },
    }],
}]
with tempfile.TemporaryDirectory() as directory:
    path = Path(directory) / 'fixture.yml'
    path.write_text(yaml.safe_dump(fixture, sort_keys=False))
    subprocess.run(['ansible-playbook', '-i', 'localhost,', str(path)], cwd=repo, check=True)
print('PASS: real source and target commands preserve the complete SQL argument.')
