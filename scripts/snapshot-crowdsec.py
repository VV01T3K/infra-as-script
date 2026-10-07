import json, pathlib, sqlite3, subprocess, tarfile, tempfile, os
os.umask(0o077)
backup=pathlib.Path(os.environ['BACKUP'])
guest=os.environ['GUEST']
prefix=['pct','exec',guest,'--']
def run(args): return subprocess.check_output(args)
c=json.loads(run(prefix+['docker','inspect','crowdsec']))[0]
assert c['State']['Running']
mounts={m['Destination']:m['Source'] for m in c['Mounts']}
config=mounts['/etc/crowdsec']; data=mounts['/var/lib/crowdsec/data']
pid=run(['lxc-info','-n',guest,'-pH']).decode().strip()
db=pathlib.Path('/proc')/pid/'root'/data.lstrip('/')/'crowdsec.db'
# Linux advisory locks refer to the same inode through the guest's root.
# SQLite's backup API takes a consistent online snapshot, including any WAL.
with tempfile.TemporaryDirectory(dir=backup) as tmp:
    snapshot=pathlib.Path(tmp)/'crowdsec.db'
    with sqlite3.connect(db.as_uri()+'?mode=ro',uri=True,timeout=60) as source, sqlite3.connect(snapshot) as target:
        source.backup(target)
        assert target.execute('PRAGMA integrity_check').fetchone()[0]=='ok'
        tables=[r[0] for r in target.execute("SELECT name FROM sqlite_master WHERE type='table'")]
        counts={name:target.execute('SELECT COUNT(*) FROM "'+name.replace('"','""')+'"').fetchone()[0] for name in tables}
    (backup/'crowdsec_config.tar').write_bytes(run(prefix+['tar','-C',config,'-cf','-','.']))
    archive=backup/'crowdsec_data.tar'
    archive.write_bytes(run(prefix+['tar','--exclude=./crowdsec.db','--exclude=./crowdsec.db-*','-C',data,'-cf','-','.']))
    uid,gid,mode=run(prefix+['stat','-c','%u %g %a',data+'/crowdsec.db']).decode().split()
    with tarfile.open(archive,'a') as tar:
        info=tar.gettarinfo(str(snapshot),arcname='./crowdsec.db')
        info.uid=int(uid);info.gid=int(gid);info.mode=int(mode,8);info.uname='';info.gname=''
        with snapshot.open('rb') as stream:tar.addfile(info,stream)
    (backup/'crowdsec-snapshot.json').write_text(json.dumps({'integrity':'ok','table_counts':counts},indent=2)+'\n')
print('CrowdSec online snapshot integrity verified')
