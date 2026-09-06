# Tests

`integration/` contains Python unittest tests that run real Ansible playbooks and
roles against temporary repository fixtures. SSH, GitHub, Proxmox, and application
endpoints are simulated; tests do not connect to the homelab. Backup tests use real
GPG with synthetic data.

Run from the repository root:

```bash
python3 -m unittest discover -s tests/integration -v
```

For OpenTofu checks, playbook syntax, and tests together:

```bash
ansible-playbook ansible/playbooks/validate.yml
```

Install the collection with `ansible-galaxy collection install -r ansible/requirements.yml`.
The test runner also needs Ansible, PyYAML, GPG, and OpenSSH tools on PATH.
`integration/support.py` creates isolated fixtures and role test entry points.
Python here is test infrastructure; deployment does not invoke custom Python code.
