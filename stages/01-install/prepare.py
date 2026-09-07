"""Prepare reusable installer credentials and an answer file; never contact a host."""
import argparse
import os
from pathlib import Path
import re
import secrets
import subprocess
import tempfile
import tomllib


def prepare(profile, destination, regenerate=False):
    template = profile.read_text()
    tomllib.loads(template)
    destination.mkdir(parents=True, exist_ok=True, mode=0o700)
    answer = destination / 'answer.toml'
    if answer.exists() and not regenerate:
        return answer
    # Keep previous generations so older USB media can still be used for reinstall.
    with tempfile.TemporaryDirectory(dir=destination) as temporary:
        staging = Path(temporary)
        key = staging / 'bootstrap'
        subprocess.run(['ssh-keygen', '-q', '-t', 'ed25519', '-N', '',
                        '-C', 'installer', '-f', str(key)], check=True)
        password = secrets.token_urlsafe(36)
        hashed = subprocess.run(['openssl', 'passwd', '-6', '-stdin'],
                                input=password + '\n', text=True,
                                capture_output=True, check=True).stdout.strip()
        rendered = template.replace('REPLACE_WITH_SHA512_CRYPT_HASH', hashed).replace(
            'REPLACE_WITH_BOOTSTRAP_SSH_PUBLIC_KEY', key.with_suffix('.pub').read_text().strip())
        parsed = tomllib.loads(rendered)
        if parsed['global']['root-password-hashed'] != hashed:
            raise ValueError('Profile must use the example credential placeholders')
        (staging / 'root-password').write_text(password + '\n')
        (staging / 'answer.toml').write_text(rendered)
        for name in ['bootstrap', 'bootstrap.pub', 'root-password', 'answer.toml']:
            target = destination / name
            if target.exists():
                history = destination / 'history'
                history.mkdir(exist_ok=True, mode=0o700)
                target.rename(history / (name + '.' + secrets.token_hex(8)))
            os.replace(staging / name, target)
            target.chmod(0o600)
    return answer


def main():
    root = Path(__file__).resolve().parents[2]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--server', default='pve')
    parser.add_argument('--profile', type=Path, default=Path(__file__).parent / 'profiles/old-laptop.example.toml')
    parser.add_argument('--regenerate', action='store_true')
    args = parser.parse_args()
    if not re.fullmatch(r'[a-zA-Z0-9][a-zA-Z0-9_-]*', args.server):
        parser.error('server must be a simple directory name')
    answer = prepare(args.profile, root / 'secrets/installer' / args.server, args.regenerate)
    print(f'Installer answer: {answer}')
    print('Validate the answer and rebuild the USB ISO after regeneration.')


if __name__ == '__main__':
    main()
