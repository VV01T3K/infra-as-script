"""Prepare a stopped connector; activate only after the dashboard rules match."""
import argparse
import base64
import ipaddress
import json
import os
from pathlib import Path
import re
import shlex
import subprocess
import time
import urllib.parse
import urllib.request

import jinja2
import yaml

REPO = Path(__file__).resolve().parents[1]
SOURCE_REPO = Path(os.environ.get('TUNNEL_CREDENTIAL_REPO', REPO))
NETWORK = 'cloudflare_ingress'
SUBNET = ipaddress.ip_network('172.31.255.0/29')
RECOVERY = '/root/cloudflared-cutover'


def local(args, data=None):
    result = subprocess.run(args, input=data if data is not None else "", text=True, capture_output=True)
    if result.returncode:
        message = re.findall(r'(?:AssertionError|RuntimeError): ([^\n]+)', result.stderr)
        raise RuntimeError('Command failed: ' + ' '.join(args[:3]) + ('; ' + message[-1] if message else ''))
    return result.stdout


inventory = yaml.safe_load((REPO / 'inventory/hosts.yml').read_text())['all']
hosts = inventory['children']
source = hosts['proxmox']['hosts']['torus']['address']
target_guest = hosts['guests']['hosts']['zoltan']
target = hosts['proxmox']['hosts'][target_guest['node']]['address']


def remote(host, args, data=None):
    return local(['ssh', '-o', 'BatchMode=yes', '-o', 'IdentitiesOnly=yes',
                  '-i', str(SOURCE_REPO / 'keys/fleet.pub'), '-o',
                  'UserKnownHostsFile=' + str(SOURCE_REPO / 'secrets/known_hosts'),
                  'root@' + host, shlex.join(args)], data)


def guest(args, data=None):
    return remote(target, ['pct', 'exec', str(target_guest['vmid']), '--', *args], data)


def original(args):
    listing = remote(source, ['pct', 'list'])
    ids = [line.split()[0] for line in listing.splitlines()[1:]
           if line.split()[-1] == 'externum' and line.split()[1] == 'running']
    assert len(ids) == 1, 'Exactly one running externum is required'
    return remote(source, ['pct', 'exec', ids[0], '--', *args])


def metadata(name):
    return json.loads(guest(['docker', 'inspect', name]))[0]


def write_files(files):
    # Credentials travel only through encrypted SSH stdin and root-only files.
    code = '''import json,pathlib,sys
for name,content in json.load(sys.stdin).items():
 p=pathlib.Path(name);p.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
 p.touch(mode=0o600,exist_ok=True);p.chmod(0o600);p.write_text(content)
'''
    guest(['python3', '-c', code], json.dumps(files))


def render(name, secrets):
    env = jinja2.Environment(loader=jinja2.FileSystemLoader(REPO / 'stages/5-services/templates'),
                             undefined=jinja2.StrictUndefined, keep_trailing_newline=True)
    env.filters['to_json'] = json.dumps
    from ansible.module_utils.parsing.convert_bool import boolean
    env.filters['bool'] = boolean
    versions = yaml.safe_load((REPO / 'stages/5-services/versions.yml').read_text())
    variables = dict(inventory['vars'], **versions, service_secrets=secrets,
                     caddy_security_enabled=True, caddy_tunnel_enabled=True,
                     arcane_host='arcane.lab.wsiwiec.com', cliproxy_host='cliproxy.lab.wsiwiec.com')
    variables['domain'] = inventory['vars']['domain']
    variables['caddy_wildcard_domains'] = [variables['domain'], 'wsiwiec.com']
    return env.get_template(name).render(**variables)


def configuration():
    # docker logs may write its informational lines to stderr; collect remotely.
    logs = original(['sh', '-c', 'docker logs cloudflared 2>&1'])
    result = None
    for line in logs.splitlines():
        match = re.search(r'config=("(?:[^"\\]|\\.)*")', line)
        if match:
            result = json.loads(json.loads(match[1]))
    assert result, 'No remote tunnel configuration found'
    return result


def api(secrets, path):
    code = '''import json,sys,urllib.request
request=json.load(sys.stdin)
r=urllib.request.urlopen(urllib.request.Request('http://127.0.0.1:3552/api/'+request['path'],headers={'X-Api-Key':request['key']}))
print(json.dumps(json.load(r)))
'''
    return json.loads(guest(['python3', '-c', code], json.dumps({'path': path, 'key': secrets['arcane_api_key']})))


def prepare():
    secrets = json.loads(os.environ['SERVICE_SECRETS'])
    current = json.loads(original(['docker', 'inspect', 'cloudflared']))[0]
    environment = dict(value.split('=', 1) for value in current['Config']['Env'])
    token = environment.get('TUNNEL_TOKEN')
    if not token:
        command = current['Config']['Cmd']
        token = command[command.index('--token') + 1]
    identity = json.loads(base64.b64decode(token))
    image = json.loads(original(['docker', 'image', 'inspect', current['Image']]))[0]
    digests = [value for value in image['RepoDigests'] if value.startswith('cloudflare/cloudflared@sha256:')]
    assert len(digests) == 1
    secrets.update(cloudflared_token=token, cloudflared_image=digests[0])
    mapping = [item for item in api(secrets, 'environments/0/gitops-syncs?limit=1000')['data']
               if item['name'] == 'research-cruise']
    assert len(mapping) == 1 and mapping[0]['projectId']
    sync_path = '/api/environments/0/gitops-syncs/' + mapping[0]['id'] + '/sync'
    deploy_path = '/api/environments/0/projects/' + mapping[0]['projectId'] + '/up'
    routes = f'''# Only the two Arcane staging endpoints are exposed.
komodo.wsiwiec.com {{
    import protected
    @deploy {{
        method POST
        remote_ip 172.31.255.2/32
        path {sync_path} {deploy_path}
    }}
    handle @deploy {{
        reverse_proxy arcane:3552
    }}
    handle {{
        respond 404
    }}
}}
'''
    wanted = {'ingress': [
        {'hostname': 'cruise.wsiwiec.com', 'service': 'https://caddy',
         'originRequest': {'originServerName': 'cruise.wsiwiec.com'}},
        {'hostname': 'komodo_wb.wojtecs.com',
         'path': '^/(listener/github/.*|api/environments/0/.*)$',
         'service': 'https://caddy', 'originRequest': {
             'httpHostHeader': 'komodo.wsiwiec.com', 'originServerName': 'komodo.wsiwiec.com'}},
        {'service': 'http_status:404'}], 'warp-routing': {'enabled': False}}
    networks = json.loads(guest(['sh', '-c', 'docker network inspect $(docker network ls -q)']))
    assert not any(SUBNET.overlaps(ipaddress.ip_network(block['Subnet']))
                   for network in networks for block in network['IPAM'].get('Config') or []), 'Tunnel subnet overlaps an existing network'
    assert guest(['sh', '-c', 'test ! -e ' + RECOVERY + ' && echo ready']).strip() == 'ready', 'Existing cutover files require inspection'
    baseline_code = 'import json,subprocess; print(json.dumps({c["Name"]:[c["Id"],c["State"]["StartedAt"]] for c in json.loads(subprocess.check_output(["docker","inspect"]+subprocess.check_output(["docker","ps","-q"],text=True).split()))}))'
    baseline = guest(['python3', '-c', baseline_code])
    old_config = configuration()
    files = {RECOVERY + '/baseline.json': baseline,
                 RECOVERY + '/old-tunnel.json': json.dumps(old_config, indent=2),
                 RECOVERY + '/wanted-tunnel.json': json.dumps(wanted, indent=2),
                 RECOVERY + '/deployment.caddy': routes,
                 RECOVERY + '/Caddyfile.next': render('Caddyfile.j2', secrets),
                 RECOVERY + '/caddy.compose.next.yaml': render('caddy.compose.yaml.j2', secrets),
                 '/opt/cloudflared/compose.yaml': render('cloudflared.compose.yaml.j2', secrets)}
    guest(['mkdir', '-m', '700', RECOVERY])
    guest(['cp', '-p', '/opt/caddy/Caddyfile', RECOVERY + '/Caddyfile'])
    guest(['cp', '-p', '/opt/caddy/compose.yaml', RECOVERY + '/caddy.compose.yaml'])
    write_files(files)
    encrypted = local(['sops', 'encrypt', '--input-type', 'json', '--output-type', 'yaml',
                       '--filename-override', str(REPO / 'secrets/services.sops.yaml'), '/dev/stdin'], json.dumps(secrets))
    (REPO / 'secrets/services.sops.yaml').write_text(encrypted)
    (REPO / 'secrets/services.sops.yaml').chmod(0o600)
    guest(['docker', 'network', 'create', '--internal', '--subnet', str(SUBNET), NETWORK])
    guest(['docker', 'compose', '-f', '/opt/cloudflared/compose.yaml', 'create'])
    assert not metadata('cloudflared')['State']['Running']
    print(json.dumps({'prepared': True, 'connector_running': False, 'tunnel_id': identity['t'],
                      'required_dashboard_config': wanted,
                      'staging_sync_url': 'https://komodo_wb.wojtecs.com' + sync_path,
                      'staging_deploy_url': 'https://komodo_wb.wojtecs.com' + deploy_path}, indent=2))


def activate():
    code = r'''
import hashlib,json,pathlib,re,subprocess,time
root=pathlib.Path('/root/cloudflared-cutover')
def run(args):
 p=subprocess.run(args,text=True,capture_output=True)
 if p.returncode: raise RuntimeError('Activation failed: '+' '.join(args[:3]))
 return p.stdout
def inspect(name): return json.loads(run(['docker','inspect',name]))[0]
proof=json.loads((root/'candidate-verified.json').read_text())
assert proof['image_id']==inspect('caddy')['Image'],'Caddy image changed after verification'
assert all(hashlib.sha256((root/name).read_bytes()).hexdigest()==sha for name,sha in proof['inputs_sha256'].items()),'Prepared inputs changed after verification'
assert not inspect('cloudflared')['State']['Running'],'Unexpected running connector'
assert not pathlib.Path('/opt/caddy/backends/staging-deploy.caddy').exists(),'Existing deployment route requires inspection'
try:
 for src,dst in [('Caddyfile.next','/opt/caddy/Caddyfile'),('caddy.compose.next.yaml','/opt/caddy/compose.yaml'),('deployment.caddy','/opt/caddy/backends/staging-deploy.caddy')]:
  path=pathlib.Path(dst);path.touch(mode=0o600,exist_ok=True);path.chmod(0o600);path.write_bytes((root/src).read_bytes())
 run(['docker','compose','-f','/opt/caddy/compose.yaml','up','--detach','--wait','caddy'])
 run(['docker','compose','-f','/opt/cloudflared/compose.yaml','up','--detach','--wait'])
 for i in range(30):
  status=subprocess.run(['docker','exec','caddy','wget','-qO-','http://cloudflared:2000/ready'],capture_output=True)
  if status.returncode==0: break
  time.sleep(2)
 else: raise AssertionError('Connector did not establish a Cloudflare connection')
 wanted=json.loads((root/'wanted-tunnel.json').read_text())
 received=None
 for i in range(15):
  logs=subprocess.run(['docker','logs','cloudflared'],text=True,capture_output=True)
  for line in (logs.stdout+logs.stderr).splitlines():
   match=re.search(r'config=("(?:[^"\\]|\\.)*")',line)
   if match: received=json.loads(json.loads(match.group(1)))
  if received: break
  time.sleep(1)
 assert received,'No configuration received by the replacement connector'
 def rules(config):
  result=[]
  for rule in config['ingress']:
   origin={key:rule.get('originRequest',{}).get(key,'') for key in ['httpHostHeader','originServerName']}
   # The retained signed certificate has this exact wildcard SAN.
   if origin['originServerName']=='*.wsiwiec.com':
    origin['originServerName']='cruise.wsiwiec.com' if rule['hostname']=='cruise.wsiwiec.com' else 'komodo.wsiwiec.com'
   result.append({key:rule.get(key) for key in ['hostname','service','path']} | {'origin':origin})
  return result
 assert rules(received)==rules(wanted),'Dashboard rules do not match the prepared cutover'
 assert not received.get('warp-routing',{}).get('enabled'),'Unexpected private-network routing'
 assert not any(rule.get('originRequest',{}).get('noTLSVerify',False) for rule in received['ingress']),'Origin TLS verification must remain enabled'
 (root/'received-tunnel.json').write_text(json.dumps(received,indent=2))
 for production,expected in json.loads((root/'baseline.json').read_text()).items():
  if production=='/caddy': continue
  actual=inspect(production)
  assert [actual['Id'],actual['State']['StartedAt']]==expected,'An application container changed'
 pathlib.Path('/opt/caddy/tunnel-enabled').write_text('Verified private origin; connector ready.\n')
except BaseException:
 subprocess.run(['docker','stop','cloudflared'],capture_output=True)
 for src,dst in [('Caddyfile','/opt/caddy/Caddyfile'),('caddy.compose.yaml','/opt/caddy/compose.yaml')]: pathlib.Path(dst).write_bytes((root/src).read_bytes())
 pathlib.Path('/opt/caddy/backends/staging-deploy.caddy').unlink(missing_ok=True)
 run(['docker','compose','-f','/opt/caddy/compose.yaml','up','--detach','--wait','caddy'])
 raise
print('New connector ready. Original connector remains running until public verification passes.')
'''
    print(guest(['python3', '-c', code]))


def finish():
    assert metadata('cloudflared')['State']['Running'], 'Replacement connector is not running'
    guest(['docker', 'exec', 'caddy', 'wget', '-qO-', 'http://cloudflared:2000/ready'])
    host = 'cruise.wsiwiec.com'
    query = urllib.parse.urlencode({'name': host, 'type': 'A'})
    request = urllib.request.Request('https://cloudflare-dns.com/dns-query?' + query,
                                     headers={'Accept': 'application/dns-json'})
    with urllib.request.urlopen(request, timeout=15) as response:
        dns = json.load(response)
    addresses = [item['data'] for item in dns.get('Answer', []) if item['type'] == 1]
    assert addresses, 'No public origin address'
    was_running = json.loads(original(['docker', 'inspect', 'cloudflared']))[0]['State']['Running']
    original(['docker', 'stop', 'cloudflared'])
    try:
        results = {}
        for attempt in range(5):
            time.sleep(2)
            for path in ['/api/health', '/api/version', '/api/v2/users/me']:
                results[path] = local(['curl', '--silent', '--show-error', '--connect-timeout', '5',
                                      '--max-time', '12', '--resolve', host + ':443:' + addresses[0],
                                      '--output', '/dev/null', '--write-out', '%{http_code}',
                                      'https://' + host + path])
            if results == {'/api/health': '200', '/api/version': '200', '/api/v2/users/me': '401'}:
                break
        else:
            raise AssertionError('Public checks failed on the replacement connector')
    except BaseException:
        if was_running:
            original(['docker', 'start', 'cloudflared'])
        raise
    print(json.dumps({'public_checks': results, 'original_connector': 'stopped'}))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('step', choices=['prepare', 'activate', 'finish'])
    args = parser.parse_args()
    {'prepare': prepare, 'activate': activate, 'finish': finish}[args.step]()
