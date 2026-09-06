"""Exercise the state-to-inventory boundary without touching infrastructure."""
from contextlib import redirect_stdout, redirect_stderr
import importlib.util
import io
import json
from pathlib import Path
import subprocess
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location(
    "inventory", Path(__file__).resolve().parents[1] / "ansible/tofu-inventory.py"
)
inventory = importlib.util.module_from_spec(spec)
spec.loader.exec_module(inventory)


class InventoryTests(unittest.TestCase):
    def run_inventory(self, result=None, error=None):
        output, errors = io.StringIO(), io.StringIO()
        with patch.object(inventory.subprocess, "run", return_value=result,
                          side_effect=error), redirect_stdout(output), redirect_stderr(errors):
            status = inventory.main()
        return status, output.getvalue(), errors.getvalue()

    def test_uses_applied_address_and_guest_id(self):
        result = subprocess.CompletedProcess([], 0, stdout=json.dumps({
            "ip": "10.0.0.77", "lxc_id": 207,
        }))
        status, output, errors = self.run_inventory(result)
        self.assertEqual(status, 0, errors)
        host = json.loads(output)["all"]["hosts"]["arcane"]
        self.assertEqual(host["ansible_host"], "10.0.0.77")
        self.assertEqual(host["lxc_id"], 207)

    def test_invalid_or_missing_state_never_emits_inventory(self):
        for state in ["{}", "not JSON", '{"ip":"invalid","lxc_id":200}',
                      '{"ip":"10.0.0.60","lxc_id":1}']:
            with self.subTest(state=state):
                result = subprocess.CompletedProcess([], 0, stdout=state)
                status, output, errors = self.run_inventory(result)
                self.assertEqual(status, 1)
                self.assertEqual(output, "")
                self.assertIn("Run tofu apply", errors)

    def test_tofu_failure_is_not_silently_replaced_with_default_ip(self):
        status, output, errors = self.run_inventory(
            error=subprocess.CalledProcessError(1, "tofu", stderr="private diagnostic")
        )
        self.assertEqual(status, 1)
        self.assertEqual(output, "")
        self.assertNotIn("private diagnostic", errors)


if __name__ == "__main__":
    unittest.main()
