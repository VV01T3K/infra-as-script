"""Verify real Caddy routes, certificate preservation and CrowdSec enforcement."""
import hashlib
import http.client
import json
from pathlib import Path
import re
import socket
import ssl
import subprocess
import sys
import time
import uuid


def run(arguments):
    result = subprocess.run(arguments, capture_output=True, text=True)
    if result.returncode:
        raise RuntimeError('Verification command failed: ' + ' '.join(arguments[:4]))
    return result.stdout


def container(name):
    return json.loads(run(['docker', 'inspect', name]))[0]


def probe(address, host, path='/'):
    with socket.create_connection((address, 443), timeout=10) as tcp:
        with ssl.create_default_context().wrap_socket(tcp, server_hostname=host) as connection:
            fingerprint = hashlib.sha256(connection.getpeercert(binary_form=True)).hexdigest()
            connection.sendall(('GET ' + path + ' HTTP/1.1\r\nHost: ' + host + '\r\nConnection: close\r\n\r\n').encode())
            response = http.client.HTTPResponse(connection)
            response.begin()
            return {'status': response.status, 'certificate_sha256': fingerprint}


def routes(domain, extra_host=None):
    result = {f'arcane.{domain}': '/', f'cliproxy.{domain}': '/management.html',
            f'pdm.{domain}': '/', f'omv.{domain}': '/'}
    if extra_host:
        result[extra_host] = '/api/version'
    return result


def baseline(domain, name='caddy', extra_host=None):
    address = container(name)['NetworkSettings']['Networks']['caddy']['IPAddress']
    return {host: probe(address, host, path) for host, path in routes(domain, extra_host).items()}


def handlers(route):
    result = []
    for handler in route.get('handle', []):
        result.append(handler.get('handler'))
        for nested in handler.get('routes', []):
            result.extend(handlers(nested))
    return result


def matched_routes(route):
    hosts = [host for match in route.get('match', []) for host in match.get('host', [])]
    if hosts:
        yield hosts, handlers(route)
    for handler in route.get('handle', []):
        for nested in handler.get('routes', []):
            yield from matched_routes(nested)


def verify(domain, name='caddy', expected=None, require_parsing=True, extra_host=None):
    caddy = container(name)
    assert caddy['State']['Running'] and caddy['RestartCount'] == 0
    config = json.loads(run(['docker', 'exec', name, 'wget', '-qO-', 'http://127.0.0.1:2019/config/']))
    assert config['storage']['module'] == 'redis' and str(config['storage']['db']) == '4'
    assert config['apps']['crowdsec']['enable_hard_fails']
    assert config['apps']['crowdsec']['api_url'] == 'http://crowdsec:8080/'
    secured = set()
    for server in config['apps']['http']['servers'].values():
        assert server.get('logs'), 'Access logging missing'
        for route in server.get('routes', []):
            for hosts, chain in matched_routes(route):
                for host in hosts:
                    if host in routes(domain, extra_host):
                        assert 'crowdsec' in chain and 'reverse_proxy' in chain, 'Handler missing: ' + host
                        assert chain.index('crowdsec') < chain.index('reverse_proxy'), 'Protection runs after proxy'
                        secured.add(host)
    assert secured == set(routes(domain, extra_host)), 'A retained route lacks protection'
    actual = baseline(domain, name, extra_host)
    assert all(200 <= entry['status'] < 500 for entry in actual.values()), 'An upstream failed'
    if expected:
        assert actual == expected, 'Route status or certificate changed'
    for service in ('valkey', 'crowdsec'):
        metadata = container(service)
        assert metadata['State']['Health']['Status'] == 'healthy'
        assert not any(metadata['NetworkSettings']['Ports'].values()), 'Published service port'
    memory = run(['docker', 'exec', 'valkey', 'sh', '-ec',
                  'export REDISCLI_AUTH="$VALKEY_PASSWORD"; valkey-cli --raw CONFIG GET maxmemory-policy'])
    assert memory.strip().splitlines()[-1] == 'noeviction'

    host = extra_host or 'arcane.' + domain
    address = caddy['NetworkSettings']['Networks']['caddy']['IPAddress']
    fixture = 'infra-proxy-check-' + uuid.uuid4().hex[:10]
    ip = None
    banned = False
    fixture_created = False
    parsed_lines = None
    try:
        run(['docker', 'run', '--rm', '-d', '--name', fixture, '--network', 'caddy',
             '--add-host', host + ':' + address, '--entrypoint', 'sh', caddy['Image'], '-c', 'sleep 180'])
        fixture_created = True
        ip = container(fixture)['NetworkSettings']['Networks']['caddy']['IPAddress']

        def status():
            result = subprocess.run(['docker', 'exec', fixture, 'wget', '-S', '-O', '/dev/null',
                                     'https://' + host + '/'], capture_output=True, text=True)
            codes = re.findall(r'HTTP/\S+\s+(\d{3})', result.stderr)
            assert codes, 'The test request did not reach HTTPS'
            return int(codes[-1])

        assert status() == actual[host]['status'], 'Disposable client is already blocked'
        run(['docker', 'exec', 'crowdsec', 'cscli', 'decisions', 'add', '--ip', ip,
             '--duration', '2m', '--reason', fixture])
        banned = True
        for attempt in range(12):
            if status() == 403:
                break
            time.sleep(2)
        else:
            raise AssertionError('CrowdSec decision did not block an actual request')
        # A parsed private test IP can be whitelisted by acquisition; manual bans
        # still exercise the real bouncer. Require parsing, not alert generation.
        if require_parsing:
            for attempt in range(10):
                metrics = json.loads(run(['docker', 'exec', 'crowdsec', 'cscli', 'metrics', 'show', 'acquisition', '-o', 'json']))
                source = metrics.get('acquisition', {}).get('docker:caddy', {})
                if source.get('parsed', 0) > 0:
                    parsed_lines = source['parsed']
                    break
                time.sleep(2)
            else:
                raise AssertionError('CrowdSec did not parse the new JSON access logs')
    finally:
        try:
            if banned:
                run(['docker', 'exec', 'crowdsec', 'cscli', 'decisions', 'delete', '--ip', ip])
                for attempt in range(12):
                    if status() == actual[host]['status']:
                        break
                    time.sleep(2)
                else:
                    raise AssertionError('Removing the test decision did not restore access')
        finally:
            if fixture_created:
                run(['docker', 'rm', '-f', fixture])
    print(json.dumps({'routes': actual, 'protected_hosts': sorted(secured),
                      'real_ban_status': 403, 'log_parsing': 'verified' if require_parsing else 'checked after listening proxy cutover',
                      'parsed_access_lines': parsed_lines, 'published_security_ports': False}, indent=2))


if __name__ == '__main__':
    expected_path = Path('/opt/caddy-security-candidate/baseline.json')
    expected = json.loads(expected_path.read_text()) if expected_path.exists() else None
    verify(sys.argv[1], sys.argv[2] if len(sys.argv) > 2 else 'caddy', expected,
           extra_host=sys.argv[3] if len(sys.argv) > 3 else None)
