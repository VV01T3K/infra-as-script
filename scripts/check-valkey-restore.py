"""Opt-in real Valkey RDB-to-AOF restore check using isolated Podman containers."""
import subprocess
import time
import uuid

image = 'docker.io/valkey/valkey:9.1.2-alpine@sha256:48332870af354a799964c0012ae1194a0bf2bf894eb508f945810596dc2d8d11'
name = 'infra-valkey-test-' + uuid.uuid4().hex[:10]
volume = name + '-data'


def run(*arguments):
    return subprocess.check_output(['podman', *arguments], text=True, stderr=subprocess.PIPE).strip()


def start(appendonly):
    run('run', '--rm', '-d', '--name', name, '--network', 'none', '-v', volume + ':/data',
        image, 'valkey-server', '--appendonly', appendonly, '--port', '0',
        '--unixsocket', '/tmp/test.sock', '--unixsocketperm', '600')
    for attempt in range(30):
        try:
            if cli('PING') == 'PONG':
                return
        except subprocess.CalledProcessError:
            pass
        time.sleep(0.2)
    raise AssertionError('Valkey did not start')


def cli(*arguments):
    return run('exec', name, 'valkey-cli', '-s', '/tmp/test.sock', '-n', '4', '--raw', *arguments)


run('volume', 'create', volume)
try:
    start('no')
    assert cli('SET', 'certificate', 'preserved-fixture') == 'OK'
    assert cli('SAVE') == 'OK'
    run('rm', '-f', name)
    start('no')
    assert cli('GET', 'certificate') == 'preserved-fixture'
    assert cli('CONFIG', 'SET', 'appendonly', 'yes') == 'OK'
    for attempt in range(50):
        info = dict(line.split(':', 1) for line in cli('INFO', 'persistence').splitlines() if ':' in line)
        if info['aof_rewrite_in_progress'] == '0' and int(info['aof_rewrites']) > 0:
            assert info['aof_last_bgrewrite_status'] == 'ok'
            break
        time.sleep(0.2)
    else:
        raise AssertionError('Initial AOF rewrite did not finish')
    run('rm', '-f', name)
    start('yes')
    assert cli('GET', 'certificate') == 'preserved-fixture'
    assert cli('DBSIZE') == '1'
    print('Real Valkey preserved the restored certificate key after RDB-to-AOF conversion and restart')
finally:
    subprocess.run(['podman', 'rm', '-f', name], capture_output=True, check=False)
    run('volume', 'rm', volume)
