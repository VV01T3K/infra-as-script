"""Run against the real Caddy image before a connector can receive traffic."""
import importlib.util
from pathlib import Path

spec = importlib.util.spec_from_file_location('migration', Path(__file__).with_name('migrate-cloudflared.py'))
migration = importlib.util.module_from_spec(spec)
spec.loader.exec_module(migration)



def verify():
    code = r'''
import hashlib,json,os,re,subprocess,time,uuid

def run(args,env=None):
 p=subprocess.run(args,text=True,capture_output=True,env=env)
 if p.returncode: raise RuntimeError('Candidate check failed: '+' '.join(args[:3]))
 return p.stdout

def inspect(name): return json.loads(run(['docker','inspect',name]))[0]
current=inspect('caddy')
production_baseline={c['Name']:[c['Id'],c['State']['StartedAt']] for c in json.loads(run(['docker','inspect']+run(['docker','ps','-q']).split()))}
image=current['Image']
name='caddy-tunnel-check-'+uuid.uuid4().hex[:8]
client=name+'-trusted';other=name+'-untrusted';banned=False
from pathlib import Path
root=Path('/root/cloudflared-cutover')
config=(root/'Caddyfile.next').read_text()+'\nimport /etc/caddy/tunnel.caddy\n'
(root/'Caddyfile.test').write_text(config)
env=dict(os.environ,**dict(v.split('=',1) for v in current['Config']['Env']))
args=['docker','create','--name',name,'--network','caddy',
      '-v',str(root/'Caddyfile.test')+':/etc/caddy/Caddyfile:ro',
      '-v',str(root/'deployment.caddy')+':/etc/caddy/tunnel.caddy:ro',
      '-v','/opt/caddy/backends:/etc/caddy/backends:ro',
      '-v','/var/run/docker.sock:/var/run/docker.sock:ro']
for value in current['Config']['Env']: args+=['-e',value.split('=',1)[0]]
try:
 run(args+[image],env)
 run(['docker','network','connect','caddy_security',name])
 run(['docker','network','connect','--ip','172.31.255.4','cloudflare_ingress',name])
 run(['docker','start',name])
 for i in range(20):
  check=subprocess.run(['docker','exec',name,'wget','-qO-','http://127.0.0.1:2019/config/'],text=True,capture_output=True)
  if check.returncode==0:
   cfg=json.loads(check.stdout)
   if 'komodo.wsiwiec.com' in check.stdout: break
  time.sleep(1)
 else: raise AssertionError('Candidate routes failed to load')
 for fixture,ip in [(client,'172.31.255.2'),(other,'172.31.255.5')]:
  run(['docker','run','--rm','-d','--name',fixture,'--network','cloudflare_ingress','--ip',ip,
       '--add-host','cruise.wsiwiec.com:172.31.255.4',
       '--add-host','komodo.wsiwiec.com:172.31.255.4',
       '--entrypoint','sh',image,'-c','sleep 240'])
  routes=(root/'deployment.caddy').read_text()
 sync=re.search(r'path (/api/\S+) ',routes).group(1)
 fake_ip='198.51.100.44'
 def status(fixture,host,path,post=False):
  args=['docker','exec',fixture,'wget','-S','-O','/dev/null',
        '--header','CF-Connecting-IP: '+fake_ip,'--header','X-Forwarded-For: 203.0.113.99',
        '--header','X-Cloudflare-Secret: candidate-secret-not-real',
        '--header','X-Api-Key: invalid-candidate-key']
  if post: args+=['--post-data','{}','--header','X-Api-Key: invalid-candidate-key']
  p=subprocess.run(args+['https://'+host+path],text=True,capture_output=True)
  codes=re.findall(r'HTTP/\S+\s+(\d{3})',p.stderr)
  assert codes,'No verified HTTPS response'
  return int(codes[-1])
 assert status(client,'cruise.wsiwiec.com','/api/health?cloudflared-check')==200
 assert status(client,'komodo.wsiwiec.com',sync,True)==401,'Arcane must reject a missing/invalid API key'
 assert status(client,'komodo.wsiwiec.com',sync)==404,'GET must not reach deployment'
 assert status(client,'komodo.wsiwiec.com','/')==404,'Dashboard must not be exposed'
 assert status(other,'komodo.wsiwiec.com',sync,True)==404,'Direct clients must not reach deployment'
 def records():
  p=subprocess.run(['docker','logs',name],text=True,capture_output=True)
  result=[]
  for line in (p.stdout+p.stderr).splitlines():
   try: d=json.loads(line)
   except ValueError: continue
   if d.get('request',{}).get('uri')=='/api/health?cloudflared-check': result.append(d['request'])
  return result
 raw_logs=subprocess.run(['docker','logs',name],text=True,capture_output=True)
 assert 'candidate-secret-not-real' not in raw_logs.stdout+raw_logs.stderr,'Cloudflare secret reached access logs'
 assert 'invalid-candidate-key' not in raw_logs.stdout+raw_logs.stderr,'API key reached access logs'
 assert any(r.get('client_ip')==fake_ip and r.get('remote_ip')=='172.31.255.2' for r in records()),'Trusted CF client IP missing'
 assert status(other,'cruise.wsiwiec.com','/api/health?cloudflared-check')==200
 assert any(r.get('client_ip')=='172.31.255.5' for r in records()),'Untrusted header was accepted'
 run(['docker','exec','crowdsec','cscli','decisions','add','--ip',fake_ip,'--duration','2m','--reason',name]);banned=True
 for i in range(15):
  if status(client,'cruise.wsiwiec.com','/api/health')==403: break
  time.sleep(2)
 else: raise AssertionError('Real client-IP ban failed')
 assert status(other,'cruise.wsiwiec.com','/api/health')==200,'Forged client-IP header affected untrusted traffic'
 for production,expected in production_baseline.items():
  actual=inspect(production)
  assert [actual['Id'],actual['State']['StartedAt']]==expected,'Production container changed during candidate checks'
 report={'origin_tls':'verified','health':200,'invalid_deploy_key':401,
                   'dashboard_and_wrong_method':404,'direct_deploy_access':404,
                   'trusted_client_ip':'verified','spoofed_client_ip':'ignored',
                   'real_client_ip_ban':403,'production_containers_restarted':False,'credential_headers_logged':False}
finally:
 try:
  if banned:
   run(['docker','exec','crowdsec','cscli','decisions','delete','--ip','198.51.100.44'])
   for i in range(15):
    if status(client,'cruise.wsiwiec.com','/api/health')==200: break
    time.sleep(2)
   else: raise AssertionError('Removing the test ban did not restore access')
 finally:
  for container in [client,other,name]: subprocess.run(['docker','rm','-f',container],capture_output=True)
report['image_id']=image
report['inputs_sha256']={name:hashlib.sha256((root/name).read_bytes()).hexdigest() for name in ['Caddyfile.next','caddy.compose.next.yaml','deployment.caddy','wanted-tunnel.json']}
(root/'candidate-verified.json').write_text(json.dumps(report))
print(json.dumps(report))
'''
    print(migration.guest(['python3', '-c', code]))


if __name__ == '__main__':
    verify()
