import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "skills/amazon-listing-images-skill/scripts"))
import api_runtime  # noqa: E402


class ApiRuntimeTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.base = Path(self.temp.name)
        self.root = self.base / "workspace"
        api_runtime.initialise(self.root)

    def tearDown(self):
        self.temp.cleanup()

    def test_defaults_match_tokease_gemini_and_gpt_image(self):
        with patch.dict(os.environ, {"TOKEASE_API_KEY": "secret-key"}, clear=False):
            cfg = api_runtime.endpoint("vision", self.root)
        self.assertEqual(cfg["base_url"], "https://tokease.com/v1")
        self.assertEqual(cfg["model"], "gemini-3.5-flash")
        with patch.dict(os.environ, {"TOKEASE_API_KEY": "secret-key"}, clear=False):
            self.assertEqual(api_runtime.endpoint("image", self.root)["model"], "gpt-image-2")

    def test_user_config_then_workspace_override(self):
        user = self.base / "user-config"
        user.mkdir()
        (user / ".env").write_text("USER_KEY=user-secret\n")
        (user / "config.json").write_text('{"vision":{"base_url":"https://user.example/v1","model":"v1","api_key_env":"USER_KEY"}}')
        with patch.dict(os.environ, {"AMAZON_GALLERY_CONFIG_DIR": str(user)}, clear=False):
            self.assertEqual(api_runtime.endpoint("vision", self.root)["base_url"], "https://user.example/v1")
            (self.root / api_runtime.CONFIG_NAME).write_text(
                '{"vision":{"base_url":"https://workspace.example/v1","model":"v2","api_key_env":"USER_KEY"}}')
            cfg = api_runtime.endpoint("vision", self.root)
            self.assertEqual(cfg["base_url"], "https://workspace.example/v1")
            self.assertEqual(cfg["model"], "v2")

    def test_legacy_user_config_is_read_when_new_is_absent(self):
        xdg = self.base / "xdg"
        legacy = xdg / "amazon-gallery-studio"
        legacy.mkdir(parents=True)
        (legacy / ".env").write_text("LEGACY_KEY=legacy-secret\n")
        (legacy / "config.json").write_text(
            '{"vision":{"base_url":"https://legacy.example/v1","model":"legacy-model","api_key_env":"LEGACY_KEY"}}')
        with patch.dict(os.environ, {"XDG_CONFIG_HOME": str(xdg)}, clear=False):
            cfg = api_runtime.endpoint("vision", self.root)
        self.assertEqual(cfg["base_url"], "https://legacy.example/v1")
        self.assertEqual(cfg["model"], "legacy-model")
        self.assertEqual(cfg["key"], "legacy-secret")

    def test_new_user_config_overrides_legacy(self):
        xdg = self.base / "xdg"
        for name, key, model in (("amazon-gallery-studio", "LEGACY_KEY", "legacy-model"),
                                 ("amazon-listing-images-skill", "NEW_KEY", "new-model")):
            directory = xdg / name
            directory.mkdir(parents=True)
            (directory / ".env").write_text("%s=%s-secret\n" % (key, name))
            (directory / "config.json").write_text(
                '{"vision":{"base_url":"https://%s.example/v1","model":"%s","api_key_env":"%s"}}' % (name, model, key))
        with patch.dict(os.environ, {"XDG_CONFIG_HOME": str(xdg)}, clear=False):
            cfg = api_runtime.endpoint("vision", self.root)
        self.assertEqual(cfg["base_url"], "https://amazon-listing-images-skill.example/v1")
        self.assertEqual(cfg["model"], "new-model")
        self.assertEqual(cfg["key"], "amazon-listing-images-skill-secret")

    def test_legacy_workspace_config_is_read_and_new_overrides_it(self):
        (self.root / ".env").write_text("K=value123\n")
        legacy = self.root / api_runtime.LEGACY_CONFIG_NAME
        legacy.write_text('{"vision":{"base_url":"https://legacy.example/v1","model":"legacy","api_key_env":"K"}}')
        self.assertEqual(api_runtime.endpoint("vision", self.root)["base_url"], "https://legacy.example/v1")
        (self.root / api_runtime.CONFIG_NAME).write_text(
            '{"vision":{"base_url":"https://new.example/v1","model":"new","api_key_env":"K"}}')
        self.assertEqual(api_runtime.endpoint("vision", self.root)["base_url"], "https://new.example/v1")

    def test_process_environment_beats_files(self):
        (self.root / ".env").write_text("TOKEASE_API_KEY=file-secret\n")
        with patch.dict(os.environ, {"TOKEASE_API_KEY": "env-secret"}, clear=False):
            self.assertEqual(api_runtime.endpoint("image", self.root)["key"], "env-secret")

    def test_missing_key_message_is_actionable(self):
        with patch.dict(os.environ, {"AMAZON_GALLERY_CONFIG_DIR": str(self.base / "empty"), "TOKEASE_API_KEY": ""}, clear=False):
            with self.assertRaises(ValueError) as caught:
                api_runtime.endpoint("vision", self.root)
        message = str(caught.exception)
        self.assertIn("TOKEASE_API_KEY", message)
        self.assertIn("用户级", message)

    def test_remote_http_is_rejected_and_localhost_allowed(self):
        (self.root / ".env").write_text("K=value123\n")
        (self.root / api_runtime.CONFIG_NAME).write_text('{"vision":{"base_url":"http://example.com/v1","model":"m","api_key_env":"K"}}')
        with self.assertRaisesRegex(ValueError, "HTTPS"):
            api_runtime.endpoint("vision", self.root)
        (self.root / api_runtime.CONFIG_NAME).write_text('{"vision":{"base_url":"http://localhost:1234/v1","model":"m","api_key_env":"K"}}')
        self.assertEqual(api_runtime.endpoint("vision", self.root)["base_url"], "http://localhost:1234/v1")

    def test_skill_directory_is_not_a_workspace(self):
        with self.assertRaisesRegex(ValueError, "安装目录"):
            api_runtime.workspace(api_runtime.SKILL_DIR)

    def test_external_directory_needs_marker(self):
        external = self.base / "素材目录"
        external.mkdir()
        with self.assertRaisesRegex(ValueError, "外部素材目录"):
            api_runtime.workspace(external)

    def test_redaction_hides_secret(self):
        with patch.dict(os.environ, {"TOKEASE_API_KEY": "super-secret-value"}, clear=False):
            text = api_runtime.redact("Authorization: Bearer super-secret-value")
        self.assertNotIn("super-secret-value", text)
        self.assertIn("<REDACTED>", text)


if __name__ == "__main__":
    unittest.main()
