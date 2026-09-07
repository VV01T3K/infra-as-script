"""Exercise the real Ansible backup tasks with synthetic secrets and real GPG."""
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import tarfile
import tempfile
import unittest
from support import copy_repository, environment, role_playbook


class BackupTests(unittest.TestCase):
    def test_encrypted_archive_restores_inputs_and_refuses_overwrite(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            project = root / "repo"
            copy_repository(project)
            inputs = {"stages/01-install/profiles/old-laptop.toml": "synthetic installer profile",
                      "secrets/technitium/admin-password": "synthetic secret",
                      "secrets/proxmox/proxmox_bootstrap": "synthetic private key"}
            for name, value in inputs.items():
                path = project / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(value)
            (project / "stages/03-provision/proxmox/terraform.tfstate").write_text('{"serial": 7}')
            gnupg = root / "gnupg"
            gnupg.mkdir(mode=0o700)
            env = environment(project, GNUPGHOME=str(gnupg), ANSIBLE_NOCOLOR="1")
            archive = root / "controller.gpg"
            variables = root / "vars.json"
            variables.write_text(json.dumps({"backup_passphrase": "test-only",
                                             "controller_backup_path": str(archive)}))
            command = ["ansible-playbook", str(role_playbook(project, "controller", "backup")),
                       "-e", "@" + str(variables)]
            first = subprocess.run(command, env=env, capture_output=True, text=True)
            self.assertEqual(first.returncode, 0, first.stdout + first.stderr)
            encrypted = archive.read_bytes()
            self.assertNotIn(b"synthetic secret", encrypted)
            restored = subprocess.run(["gpg", "--batch", "--pinentry-mode", "loopback",
                "--passphrase", "test-only", "--decrypt", str(archive)], env=env,
                check=True, capture_output=True)
            with tarfile.open(fileobj=io.BytesIO(restored.stdout), mode="r:gz") as backup:
                for name, expected in inputs.items():
                    self.assertEqual(backup.extractfile(name).read().decode(), expected)
                self.assertEqual(backup.extractfile("terraform.tfstate").read(), b'{"serial": 7}')
            again = subprocess.run(command, env=env, capture_output=True, text=True)
            self.assertNotEqual(again.returncode, 0)
            self.assertEqual(archive.read_bytes(), encrypted)
            self.assertEqual(list(root.glob(".controller-encrypted-*")), [])
            # Encryption failure must neither publish a backup nor leave staging files.
            archive.unlink()
            binaries = root / "bin"
            binaries.mkdir()
            fake_gpg = binaries / "gpg"
            fake_gpg.write_text("#!/bin/sh\nexit 1\n")
            fake_gpg.chmod(0o700)
            failed = subprocess.run(command, env=dict(env, PATH=str(binaries)+":"+env["PATH"]),
                                    capture_output=True, text=True)
            self.assertNotEqual(failed.returncode, 0)
            self.assertFalse(archive.exists())
            self.assertEqual(list(root.glob(".controller-encrypted-*")), [])


if __name__ == "__main__":
    unittest.main()
