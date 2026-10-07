"""Run the complete candidate privately before moving the listening proxy."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import uuid

candidate = Path(sys.argv[1])
sys.path.insert(0, str(candidate))
from verify_proxy_security import baseline, run, verify

image = sys.argv[2]
domain = sys.argv[3]
name = 'infra-caddy-candidate-' + uuid.uuid4().hex[:10]
config = json.loads(run(['docker', 'compose', '-p', 'caddy', '-f', str(candidate / 'compose.yaml'),
                         'config', '--format', 'json']))['services']['caddy']
environment = config['environment']
expected = baseline(domain)
(candidate / 'baseline.json').write_text(json.dumps(expected, indent=2) + '\n')
arguments = ['docker', 'create', '--rm', '--name', name, '--network', 'caddy_security',
             '-v', str(candidate / 'Caddyfile') + ':/etc/caddy/Caddyfile:ro',
             '-v', str(candidate / 'backends') + ':/etc/caddy/backends:ro',
             '-v', '/var/run/docker.sock:/var/run/docker.sock:ro']
for key in environment:
    arguments.extend(['-e', key])
arguments.append(image)
created = False
try:
    result = subprocess.run(arguments, capture_output=True, text=True,
                            env={**os.environ, **{key: str(value) for key, value in environment.items()}})
    assert result.returncode == 0, 'Candidate container creation failed'
    created = True
    run(['docker', 'network', 'connect', 'caddy', name])
    run(['docker', 'start', name])
    for attempt in range(30):
        result = subprocess.run(['docker', 'exec', name, 'wget', '-qO-', 'http://127.0.0.1:2019/config/'],
                                capture_output=True, text=True)
        if result.returncode == 0:
            break
        time.sleep(2)
    else:
        raise AssertionError('Candidate never loaded its configuration')
    verify(domain, name, expected, require_parsing=False)
finally:
    if created:
        run(['docker', 'rm', '-f', name])
files = [candidate / name for name in ('compose.yaml', 'Caddyfile', 'Dockerfile', 'baseline.json')]
files.extend(sorted((candidate / 'backends').iterdir()))
proof = {'files': {str(path.relative_to(candidate)): hashlib.sha256(path.read_bytes()).hexdigest() for path in files},
         'image': json.loads(run(['docker', 'image', 'inspect', image]))[0]['Id'], 'domain': domain}
(candidate / 'validated.json').write_text(json.dumps(proof, indent=2) + '\n')
print('Private candidate passed; the listening proxy has not changed')
