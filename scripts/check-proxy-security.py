"""Exercise the real online CrowdSec snapshot with a database in WAL mode."""
import json
import os
from pathlib import Path
import runpy
import sqlite3
import subprocess
import sys
import tarfile
import tempfile
from unittest.mock import patch

script = Path(__file__).with_name('snapshot-crowdsec.py')
real_output = subprocess.check_output
with tempfile.TemporaryDirectory() as temporary:
    root = Path(temporary)
    config = root / 'config'
    data = root / 'data'
    backup = root / 'backup'
    for directory in (config, data, backup):
        directory.mkdir()
    (config / 'credentials.yaml').write_text('fixture credentials\n')
    (config / 'link.yaml').symlink_to('credentials.yaml')
    (data / 'parser-data.txt').write_text('fixture parser data\n')
    source = sqlite3.connect(data / 'crowdsec.db')
    source.execute('PRAGMA journal_mode=WAL')
    source.execute('CREATE TABLE fixture (value TEXT)')
    source.execute("INSERT INTO fixture VALUES ('committed WAL content')")
    source.commit()
    # Keep this connection open so the committed data remains in WAL.
    assert (data / 'crowdsec.db-wal').exists()

    def output(arguments):
        if arguments[:2] == ['lxc-info', '-n']:
            return str(os.getpid()).encode()
        if arguments[0] == sys.executable:
            # Namespace entry needs host-root privileges; the live command verifies
            # those calls. This fixture exercises the actual backup/serialization.
            program = arguments[2]
            for call in ("os.setns(namespace, 0)", "os.fchdir(root)", "os.chroot('.')", "os.chdir('/')"):
                assert call in program
                program = program.replace(call, 'pass')
            return real_output([arguments[0], '-c', program, *arguments[3:]])
        assert arguments[:4] == ['pct', 'exec', 'fixture', '--']
        command = arguments[4:]
        if command == ['docker', 'inspect', 'crowdsec']:
            return json.dumps([{'State': {'Running': True}, 'Mounts': [
                {'Destination': '/etc/crowdsec', 'Source': str(config)},
                {'Destination': '/var/lib/crowdsec/data', 'Source': str(data)},
            ]}]).encode()
        return real_output(command)

    with patch.dict(os.environ, {'GUEST': 'fixture', 'BACKUP': str(backup)}), patch('subprocess.check_output', output):
        runpy.run_path(str(script), run_name='__main__')
    with tarfile.open(backup / 'crowdsec_data.tar') as archive:
        names = archive.getnames()
        assert './crowdsec.db' in names
        assert not any(name.endswith(('-wal', '-shm', '-journal')) for name in names)
        restored = root / 'restored.db'
        restored.write_bytes(archive.extractfile('./crowdsec.db').read())
    with sqlite3.connect(restored) as database:
        assert database.execute('PRAGMA integrity_check').fetchone()[0] == 'ok'
        assert database.execute('SELECT value FROM fixture').fetchone()[0] == 'committed WAL content'
    assert json.loads((backup / 'crowdsec-snapshot.json').read_text())['table_counts']['fixture'] == 1
    with tarfile.open(backup / 'crowdsec_config.tar') as archive:
        assert archive.getmember('./link.yaml').issym()
        assert archive.extractfile('./credentials.yaml').read() == (config / 'credentials.yaml').read_bytes()
    source.close()
print('CrowdSec online backup includes committed WAL data and preserves configuration')
