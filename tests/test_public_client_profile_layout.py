"""Launcher regression for managed suites nested beneath their profile."""
import argparse
import contextlib
import importlib.util
import io
import json
import unittest
from pathlib import Path
from unittest.mock import patch

CLIENT_PATH = Path(__file__).resolve().parents[1] / "src/scripts/paperspine_public_client.py"
spec = importlib.util.spec_from_file_location("profile_layout_client", CLIENT_PATH)
client = importlib.util.module_from_spec(spec)
spec.loader.exec_module(client)


class ProfileLayoutTests(unittest.TestCase):
    def check_layout(self, layout, accepted):
        with patch.object(Path, "is_file", return_value=True):
            base = Path.cwd().resolve() / "profile-layout-fixture"
            profile = base / "profile"
            root = {
                "managed": profile / ".paperspine5-lifecycle/installs/build/core",
                "separate": base / "product",
                "equal": profile,
                "inside_product": base,
            }[layout]
            binding = {key: str(base / key) for key in (
                "project_root", "user_data_root", "core_root",
                "domain_database", "contracts_root")}
            state = {"address": "http://127.0.0.1:12345", "binding": binding}
            args = argparse.Namespace(profile_root=str(profile), no_open=True, remember=False)
            with patch.object(client, "resolve_binding", return_value=binding) as resolver, \
                 patch.object(client, "_read_web_state", return_value=state), \
                 patch.object(client, "_web_ready", return_value=True), \
                 patch.object(client, "_runtime_code_status", return_value="current"), \
                 patch.object(client.subprocess, "Popen") as process, \
                 patch.object(client.webbrowser, "open") as browser, \
                 contextlib.redirect_stdout(io.StringIO()) as output:
                if accepted:
                    self.assertEqual(client.web_launch(args, root), 0)
                    reply = json.loads(output.getvalue())
                    self.assertEqual(reply["status"], "READY")
                    self.assertEqual(reply["profile_root"], str(profile))
                    self.assertTrue(reply["reused"])
                    resolver.assert_called_once()
                else:
                    with self.assertRaisesRegex(ValueError, "Keep the local profile separate"):
                        client.web_launch(args, root)
                    resolver.assert_not_called()
                process.assert_not_called()
                browser.assert_not_called()

    def test_official_managed_install_layout_reuses_service(self):
        self.check_layout("managed", True)

    def test_separate_profile_reuses_service(self):
        self.check_layout("separate", True)

    def test_profile_equal_to_product_is_rejected(self):
        self.check_layout("equal", False)

    def test_profile_inside_product_is_rejected(self):
        self.check_layout("inside_product", False)


if __name__ == "__main__":
    unittest.main()
