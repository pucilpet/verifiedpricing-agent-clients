import contextlib
import importlib.util
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch


class InstallScaffoldTests(unittest.TestCase):
    def test_default_plan_does_not_install_or_start_subprocesses(self):
        script = Path(__file__).resolve().parents[1] / "scripts/clean_install_smoke.py"
        spec = importlib.util.spec_from_file_location("vp_install_scaffold", script)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        with tempfile.TemporaryDirectory() as temporary:
            wheel = Path(temporary) / "synthetic-not-an-installable-wheel.whl"
            wheel.write_bytes(b"synthetic artifact for plan test only")
            output = io.StringIO()
            with patch.object(module.subprocess, "run") as execute:
                with contextlib.redirect_stdout(output):
                    self.assertEqual(module.main([str(wheel)]), 0)
            execute.assert_not_called()
            receipt = json.loads(output.getvalue())
            self.assertFalse(receipt["executed"])
            self.assertEqual(len(receipt["artifact_sha256"]), 64)
            self.assertNotIn("passed", receipt)


if __name__ == "__main__":
    unittest.main()
