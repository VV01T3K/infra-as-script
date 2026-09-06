"""Run credential workflows against local files and simulated service APIs."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlsplit
import unittest
import yaml


class SecretTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.repo = self.root / 'repo'
        self.ansible = self.repo / 'proxmox/ansible'
        shutil.copytree(Path(__file__).resolve().parents[1] / 'ansible', self.ansible)
        (self.repo / 'installer/profiles').mkdir(parents=True)
        self.secrets = self.repo / 'secrets'
        self.bin = self.root / 'bin'
        self.bin.mkdir()
        self.env = dict(os.environ, PATH=str(self.bin)+':'+os.environ['PATH'],
                        TEST_ROOT=str(self.root), ANSIBLE_NOCOLOR='1')
        hosts = {}
        for host in ['pve', 'arcane']:
            hosts[host] = dict(ansible_host='127.0.0.1', ansible_connection='local',
                               rotation_authorized_keys=str(self.root / (host+'-authorized')))
        (self.ansible/'inventory.yml').write_text(yaml.safe_dump({'all':{'hosts':hosts}}))
        self.tool('tofu', "print('{\"ip\":\"127.0.0.1\",\"lxc_id\":207}')")
        # Never mutate the test runner's actual root password or service manager.
        (self.ansible/'tasks/secrets/root.yml').write_text('- ansible.builtin.command: "true"\n  changed_when: false\n')
        p=self.ansible/'tasks/secrets/arcane-api.yml'
        tasks=yaml.safe_load(p.read_text())
        def replace_service(items):
            for t in items:
                if t.get('register') == 'new_arcane_auth':
                    t['retries']=1
                    t['delay']=0
                if 'ansible.builtin.systemd_service' in t:
                    del t['ansible.builtin.systemd_service']
                    t['ansible.builtin.command']='true'
                for key in ['block','rescue','always']:
                    replace_service(t.get(key,[]))
        replace_service(tasks)
        p.write_text(yaml.safe_dump(tasks,sort_keys=False))
        self.state = {'password':'old-password', 'fail_verify':False, 'changed':False,
                      'events':[], 'sessions':[]}
        state=self.state
        class Handler(BaseHTTPRequestHandler):
            def log_message(self,*args): pass
            def do_GET(self): self.respond()
            def do_POST(self): self.respond()
            def do_PUT(self): self.respond()
            def respond(self):
                route=urlsplit(self.path).path
                body=self.rfile.read(int(self.headers.get('Content-Length',0))).decode()
                data={k:v[0] for k,v in parse_qs(body).items()}
                status=200
                result={'status':'ok'}
                if route.endswith('/user/login'):
                    if data.get('pass') != state['password'] or (state['changed'] and state['fail_verify']):
                        result={'status':'error'}
                    else:
                        token='session-'+str(len(state['sessions']))
                        state['sessions'].append(token)
                        result={'status':'ok','token':token}
                elif route.endswith('/user/changePassword'):
                    if data.get('pass')!=state['password'] or not data.get('newPass'):
                        result={'status':'error'}
                    else:
                        state['password']=data['newPass'];state['changed']=True
                        state['events'].append('password-changed')
                elif route.endswith('/user/profile/get'):
                    current=self.headers['Authorization'].split()[1]
                    result={'status':'ok','response':{'sessions':[
                        {'partialToken':t,'isCurrentSession':t==current} for t in state['sessions']]}}
                elif route.endswith('/user/session/delete'):
                    state['sessions'].remove(data['partialToken'])
                elif route.endswith('/nodes'):
                    if state['fail_verify']: status=403
                    if 'token_file' in state:
                        header=self.headers.get('Authorization','')
                        identities=json.loads(Path(state['token_file']).read_text())
                        if not any(header=='PVEAPIToken=automation@pve!'+n+'=synthetic-issued-secret' for n in identities):
                            status=401
                    result={'data':[]} 
                elif '/customize/git-repositories' in route:
                    if 'arcane_env' in state:
                        active=[l.split('=',1)[1] for l in Path(state['arcane_env']).read_text().splitlines()
                                if l.startswith('ADMIN_STATIC_API_KEY=')][0]
                        if self.headers.get('X-Api-Key')!=active or state['fail_verify']: status=401
                    result={'success':True,'data':[]}
                    if 'github_state' in state:
                        result={'success':True,'data':[{'id':'repo1','name':'infra-as-script',
                                  'url':'git@github.com:VV01T3K/infra-as-script.git'}]}
                        if self.command=='PUT':
                            state['repo_private']=json.loads(body)['sshKey']
                        if route.endswith('/test'):
                            if state.get('fail_git_test'): status=400
                            elif state.get('repo_private')!=Path(state['candidate_path']).read_text().strip(): status=400
                self.send_response(status)
                self.send_header('Content-Type','application/json')
                self.end_headers()
                self.wfile.write(json.dumps(result).encode())
        self.server=ThreadingHTTPServer(('127.0.0.1',0),Handler)
        thread=threading.Thread(target=self.server.serve_forever,daemon=True)
        thread.start()
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.server.shutdown)
        self.api='http://127.0.0.1:'+str(self.server.server_port)

    def tool(self,name,body):
        path=self.bin/name
        path.write_text('#!/usr/bin/env python3\nimport json,os,pathlib,sys\n'+body+'\n')
        path.chmod(0o700)

    def put(self,name,value):
        path=self.secrets/name
        path.parent.mkdir(parents=True,exist_ok=True)
        path.write_text(value)
        path.chmod(0o600)
        return path

    def run_secrets(self,operation='rotate',only='all',**variables):
        args=dict(secrets_action=operation,secrets_only=only,
                  technitium_api=self.api,proxmox_api_url=self.api,arcane_api=self.api,
                  technitium_password_path=str(self.root/'runtime-password'))
        args.update(variables)
        result=subprocess.run(['ansible-playbook','-i',str(self.ansible/'inventory.yml'),
            str(self.ansible/'secrets.yml'),'-e',json.dumps(args)],env=self.env,
            capture_output=True,text=True)
        return result

    def unlock(self):
        shutil.rmtree(self.secrets/'proxmox/maintenance.lock.d')

    def test_generation_is_repeatable_and_never_overwrites_credentials(self):
        first=self.run_secrets('generate')
        self.assertEqual(first.returncode,0,first.stdout+first.stderr)
        names=['proxmox/proxmox_bootstrap','arcane/arcane-api-key',
               'arcane/arcane-gitops','technitium/technitium-admin-password']
        originals={name:(self.secrets/name).read_bytes() for name in names}
        second=self.run_secrets('generate')
        self.assertEqual(second.returncode,0,second.stdout+second.stderr)
        for name,value in originals.items():
            self.assertEqual((self.secrets/name).read_bytes(),value)
            self.assertNotIn(value.decode().strip(),first.stdout)
        self.assertFalse((self.secrets/'proxmox/proxmox.env').exists())

    def test_ssh_failure_preserves_access_and_retry_reuses_candidate(self):
        key=self.secrets/'proxmox/proxmox_bootstrap'
        key.parent.mkdir(parents=True)
        subprocess.run(['ssh-keygen','-q','-t','ed25519','-N','','-f',str(key)],check=True)
        original=key.read_bytes()
        public=Path(str(key)+'.pub').read_text().strip()
        for host in ['pve','arcane']:(self.root/(host+'-authorized')).write_text(public+'\n')
        self.tool('ssh', r"""root=pathlib.Path(os.environ['TEST_ROOT'])
if (root/'fail-ssh').exists(): sys.exit(1)
args=sys.argv[1:]
assert 'IdentitiesOnly=yes' in args and 'ControlPath=none' in args and 'IdentityAgent=none' in args
key=pathlib.Path(args[args.index('-i')+1]+'.pub').read_text().strip()
assert all(key in (root/(h+'-authorized')).read_text() for h in ['pve','arcane'])
""")
        (self.root/'fail-ssh').touch()
        failed=self.run_secrets(only='ssh')
        self.assertNotEqual(failed.returncode,0)
        self.assertEqual(key.read_bytes(),original)
        candidate=(self.secrets/'.pending/ssh/new').read_bytes()
        self.assertIn(public,(self.root/'pve-authorized').read_text())
        self.unlock();(self.root/'fail-ssh').unlink()
        retried=self.run_secrets(only='ssh')
        self.assertEqual(retried.returncode,0,retried.stdout+retried.stderr)
        self.assertEqual(key.read_bytes(),candidate)
        for host in ['pve','arcane']:self.assertNotIn(public,(self.root/(host+'-authorized')).read_text())

    def test_technitium_resumes_after_server_password_changed(self):
        current=self.put('technitium/technitium-admin-password','old-password\n')
        self.state['fail_verify']=True
        failed=self.run_secrets(only='technitium')
        self.assertNotEqual(failed.returncode,0)
        self.assertEqual(current.read_text(),'old-password\n')
        candidate=(self.secrets/'.pending/technitium/new').read_text()
        self.assertEqual(self.state['password'],candidate.strip())
        self.unlock();self.state['fail_verify']=False
        retried=self.run_secrets(only='technitium')
        self.assertEqual(retried.returncode,0,retried.stdout+retried.stderr)
        self.assertEqual(current.read_text(),candidate)
        self.assertEqual(self.state['events'],['password-changed'])
        self.assertEqual((self.root/'runtime-password').read_text(),candidate)

    def test_proxmox_verifies_before_revoking_and_resumes(self):
        current=self.put('proxmox/proxmox.env',"export PROXMOX_VE_API_TOKEN_ID='automation@pve!iac'\n")
        tokens=self.root/'tokens.json';tokens.write_text(json.dumps(['iac']))
        self.state['token_file']=str(tokens)
        self.tool('pveum', r"""p=pathlib.Path(os.environ['TEST_ROOT'])/'tokens.json'
names=json.loads(p.read_text());args=sys.argv[1:];op=args[2]
if op=='list': print(json.dumps([{'tokenid':n} for n in names]))
elif op=='add':
    name=args[4];names.append(name);p.write_text(json.dumps(names))
    print(json.dumps({'full-tokenid':'automation@pve!'+name,'value':'synthetic-issued-secret'}))
elif op=='remove': names.remove(args[4]);p.write_text(json.dumps(names))
else: sys.exit(9)
""")
        self.state['fail_verify']=True
        failed=self.run_secrets(only='proxmox-api')
        self.assertNotEqual(failed.returncode,0)
        self.assertIn('iac',json.loads(tokens.read_text()))
        candidate=(self.secrets/'.pending/proxmox-api/new').read_text()
        self.unlock();self.state['fail_verify']=False
        retried=self.run_secrets(only='proxmox-api')
        self.assertEqual(retried.returncode,0,retried.stdout+retried.stderr)
        self.assertEqual(current.read_text(),candidate)
        self.assertNotIn('iac',json.loads(tokens.read_text()))
        self.assertEqual(len(json.loads(tokens.read_text())),1)

    def test_arcane_keeps_encryption_key_and_retires_old_api_key(self):
        current=self.put('arcane/arcane-api-key','old-api-key\n')
        env=self.root/'arcane.env'
        env.write_text('ENCRYPTION_KEY=keep-this-encryption-key\nADMIN_STATIC_API_KEY=old-api-key\n')
        self.state['arcane_env']=str(env)
        self.state['fail_verify']=True
        failed=self.run_secrets(only='arcane-api',arcane_env_file=str(env))
        self.assertNotEqual(failed.returncode,0)
        self.assertEqual(current.read_text(),'old-api-key\n')
        self.assertIn('ADMIN_STATIC_API_KEY=old-api-key',env.read_text())
        self.unlock();self.state['fail_verify']=False
        result=self.run_secrets(only='arcane-api',arcane_env_file=str(env))
        self.assertEqual(result.returncode,0,result.stdout+result.stderr)
        self.assertIn('ENCRYPTION_KEY=keep-this-encryption-key',env.read_text())
        self.assertIn('ADMIN_STATIC_API_KEY='+current.read_text().strip(),env.read_text())
        self.assertNotEqual(current.read_text().strip(),'old-api-key')

    def test_gitops_retires_old_key_only_after_arcane_verifies_candidate(self):
        key=self.secrets/'arcane/arcane-gitops'
        key.parent.mkdir(parents=True)
        subprocess.run(['ssh-keygen','-q','-t','ed25519','-N','','-f',str(key)],check=True)
        original=key.read_bytes()
        public=' '.join(Path(str(key)+'.pub').read_text().split()[:2])
        self.put('arcane/arcane-api-key','test-static-key')
        keys=self.root/'github-keys.json'
        keys.write_text(json.dumps([dict(id=1,key=public,title='arcane-gitops',read_only=True)]))
        self.state.update(github_state=str(keys),candidate_path=str(self.secrets/'.pending/gitops/new'),fail_git_test=True)
        self.tool('gh', r"""p=pathlib.Path(os.environ['TEST_ROOT'])/'github-keys.json'
keys=json.loads(p.read_text());args=sys.argv[1:]
if args[:2]==['auth','status']: pass
elif args[0]=='api' and 'DELETE' not in args: print(json.dumps([keys]))
elif args[:3]==['repo','deploy-key','add']:
    public=' '.join(pathlib.Path(args[3]).read_text().split()[:2])
    assert public not in [k['key'] for k in keys]
    keys.append(dict(id=2,key=public,title='arcane-gitops',read_only=True));p.write_text(json.dumps(keys))
elif 'DELETE' in args:
    key_id=int(args[-1].split('/')[-1]);keys=[k for k in keys if k['id']!=key_id];p.write_text(json.dumps(keys))
else: sys.exit(9)
""")
        failed=self.run_secrets(only='gitops')
        self.assertNotEqual(failed.returncode,0)
        self.assertEqual(key.read_bytes(),original)
        self.assertEqual(len(json.loads(keys.read_text())),2)
        candidate=(self.secrets/'.pending/gitops/new').read_bytes()
        self.unlock();self.state['fail_git_test']=False
        retried=self.run_secrets(only='gitops')
        self.assertEqual(retried.returncode,0,retried.stdout+retried.stderr)
        self.assertEqual(key.read_bytes(),candidate)
        self.assertEqual([k['id'] for k in json.loads(keys.read_text())],[2])

    def test_post_install_runs_once_and_retires_profile_keys(self):
        key=self.secrets/'proxmox/proxmox_bootstrap';key.parent.mkdir(parents=True)
        subprocess.run(['ssh-keygen','-q','-t','ed25519','-N','','-f',str(key)],check=True)
        public=Path(str(key)+'.pub').read_text().strip()
        (self.root/'pve-authorized').write_text(public+'\n')
        (self.repo/'installer/profiles/old-laptop.toml').write_text(
            '[global]\nroot-ssh-keys = '+json.dumps([public])+'\n')
        self.tool('ssh','pass')
        first=self.run_secrets('post-install')
        self.assertEqual(first.returncode,0,first.stdout+first.stderr)
        rotated=key.read_bytes()
        self.assertNotIn(public,(self.root/'pve-authorized').read_text())
        second=self.run_secrets('post-install')
        self.assertEqual(second.returncode,0,second.stdout+second.stderr)
        self.assertEqual(key.read_bytes(),rotated)
        self.assertTrue((self.secrets/'proxmox/installed-machine-id').exists())


if __name__=='__main__': unittest.main()
