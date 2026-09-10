"""
Unit tests for .agent/skills/tool-provisioning/toolkit.py.
Standard-library unittest + unittest.mock only -- run with:
  python3 -m unittest discover -s tests -v
"""

import json
import os
import sys
import tempfile
import unittest
from unittest.mock import patch, MagicMock

HERE = os.path.dirname(os.path.abspath(__file__))
SKILL_DIR = os.path.join(HERE, "..", ".agent", "skills", "tool-provisioning")
sys.path.insert(0, os.path.abspath(SKILL_DIR))

import toolkit as tk  # noqa: E402


class TempRoot(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = self._tmp.name
        os.makedirs(os.path.join(self.root, ".git"))

    def tearDown(self):
        self._tmp.cleanup()

    def write_json(self, rel_path, data):
        full = os.path.join(self.root, rel_path)
        os.makedirs(os.path.dirname(full), exist_ok=True)
        with open(full, "w", encoding="utf-8") as fh:
            json.dump(data, fh)


SAMPLE_ENTRIES = [
    {"name": "alpha", "kind": "pip", "match": ["alpha thing"],
     "check": {"type": "python_import", "module": "alpha_mod"},
     "install_cmd": ["pip", "install", "--user", "alpha"],
     "uninstall_cmd": ["pip", "uninstall", "-y", "alpha"], "risk": "r-alpha"},
    {"name": "beta", "kind": "pip", "match": ["beta thing"],
     "check": {"type": "python_import", "module": "beta_mod"},
     "install_cmd": ["pip", "install", "--user", "beta"],
     "uninstall_cmd": ["pip", "uninstall", "-y", "beta"], "risk": "r-beta"},
]


class TestRegistryLoading(TempRoot):
    def test_load_registry_includes_shipped_entries(self):
        registry = tk.load_registry(self.root)
        names = {e["name"] for e in registry}
        self.assertIn("pdf-text", names)
        self.assertIn("csv", names)

    def test_local_overlay_overrides_by_name(self):
        self.write_json(tk.LOCAL_REGISTRY_SUBPATH, [
            {"name": "pdf-text", "kind": "pip", "match": [], "risk": "overridden",
             "check": {"type": "python_import", "module": "pypdf"},
             "install_cmd": ["pip", "install", "--user", "pypdf"],
             "uninstall_cmd": ["pip", "uninstall", "-y", "pypdf"]},
            {"name": "brand-new-tool", "kind": "manual", "match": [], "risk": "custom",
             "check": {}, "install_cmd": None, "uninstall_cmd": None},
        ])
        registry = tk.load_registry(self.root)
        by_name = {e["name"]: e for e in registry}
        self.assertEqual(by_name["pdf-text"]["risk"], "overridden")
        self.assertIn("brand-new-tool", by_name)


class TestFindAndSearch(unittest.TestCase):
    def test_find_entry_exact(self):
        e = tk.find_entry(SAMPLE_ENTRIES, "alpha")
        self.assertEqual(e["name"], "alpha")

    def test_find_entry_unique_fuzzy(self):
        e = tk.find_entry(SAMPLE_ENTRIES, "alp")
        self.assertEqual(e["name"], "alpha")

    def test_find_entry_no_match(self):
        self.assertIsNone(tk.find_entry(SAMPLE_ENTRIES, "gamma"))

    def test_search_ranks_by_keyword_hits(self):
        hits = tk.search(SAMPLE_ENTRIES, "beta thing")
        self.assertEqual(hits[0]["name"], "beta")

    def test_search_no_match_returns_empty(self):
        self.assertEqual(tk.search(SAMPLE_ENTRIES, "nonexistent query xyz"), [])


class TestOrgPolicy(unittest.TestCase):
    def test_advisory_mode_keeps_everything(self):
        policy = {"mode": "advisory", "allow": [], "deny": [], "overrides": []}
        visible, denied = tk.apply_org_policy(SAMPLE_ENTRIES, policy)
        self.assertEqual({e["name"] for e in visible}, {"alpha", "beta"})
        self.assertEqual(denied, {})

    def test_denylist_blocks_named_entry(self):
        policy = {"mode": "denylist", "allow": [], "deny": ["beta"], "overrides": []}
        visible, denied = tk.apply_org_policy(SAMPLE_ENTRIES, policy)
        self.assertEqual({e["name"] for e in visible}, {"alpha"})
        self.assertIn("beta", denied)

    def test_allowlist_mode_only_keeps_allowed(self):
        policy = {"mode": "allowlist", "allow": ["alpha"], "deny": [], "overrides": []}
        visible, denied = tk.apply_org_policy(SAMPLE_ENTRIES, policy)
        self.assertEqual({e["name"] for e in visible}, {"alpha"})
        self.assertIn("beta", denied)

    def test_override_replaces_fields(self):
        policy = {"mode": "advisory", "allow": [], "deny": [],
                  "overrides": [{"name": "alpha", "risk": "corp-approved"}]}
        visible, _ = tk.apply_org_policy(SAMPLE_ENTRIES, policy)
        alpha = next(e for e in visible if e["name"] == "alpha")
        self.assertEqual(alpha["risk"], "corp-approved")
        self.assertEqual(alpha["install_cmd"], ["pip", "install", "--user", "alpha"])  # untouched

    def test_pip_index_url_injected_when_absent(self):
        policy = {"mode": "advisory", "allow": [], "deny": [], "overrides": [],
                  "pip_index_url": "https://mirror.corp.example/simple"}
        visible, _ = tk.apply_org_policy(SAMPLE_ENTRIES, policy)
        alpha = next(e for e in visible if e["name"] == "alpha")
        self.assertIn("--index-url", alpha["install_cmd"])
        self.assertIn("https://mirror.corp.example/simple", alpha["install_cmd"])

    def test_pip_index_url_not_duplicated_if_already_present(self):
        entries = [{"name": "alpha", "kind": "pip",
                    "install_cmd": ["pip", "install", "--index-url", "https://existing", "alpha"]}]
        policy = {"mode": "advisory", "allow": [], "deny": [], "overrides": [],
                  "pip_index_url": "https://mirror.corp.example/simple"}
        visible, _ = tk.apply_org_policy(entries, policy)
        self.assertEqual(visible[0]["install_cmd"].count("--index-url"), 1)

    def test_local_registry_cannot_resurrect_org_denied_name(self):
        # apply_org_policy runs on whatever load_registry() already merged in
        # (shipped + registry.local.json) -- deny/allow always wins regardless
        # of which layer defined the entry.
        policy = {"mode": "denylist", "allow": [], "deny": ["alpha"], "overrides": []}
        visible, denied = tk.apply_org_policy(SAMPLE_ENTRIES, policy)
        self.assertNotIn("alpha", {e["name"] for e in visible})
        self.assertIn("alpha", denied)


class TestOrgPolicyPath(TempRoot):
    def test_default_path_inside_repo(self):
        self.assertTrue(tk.org_policy_path(self.root).endswith(tk.ORG_POLICY_SUBPATH))

    def test_env_var_overrides_path(self):
        with patch.dict(os.environ, {tk.ORG_POLICY_ENV: "/some/absolute/path.json"}):
            self.assertEqual(tk.org_policy_path(self.root), "/some/absolute/path.json")

    def test_missing_policy_file_yields_advisory_defaults(self):
        policy = tk.load_org_policy(self.root)
        self.assertEqual(policy["mode"], "advisory")
        self.assertEqual(policy["allow"], [])


class TestCheckInstalled(unittest.TestCase):
    def test_python_import_success(self):
        entry = {"check": {"type": "python_import", "module": "os"}}
        self.assertTrue(tk.check_installed(entry))

    def test_python_import_failure(self):
        entry = {"check": {"type": "python_import", "module": "definitely_not_a_real_module_xyz"}}
        self.assertFalse(tk.check_installed(entry))

    @patch("toolkit.subprocess.run")
    def test_subprocess_check_success(self, mock_run):
        mock_run.return_value = MagicMock(returncode=0)
        entry = {"check": {"type": "subprocess", "cmd": ["some-tool", "--version"]}}
        self.assertTrue(tk.check_installed(entry))

    @patch("toolkit.subprocess.run")
    def test_mcp_check_parses_list_output(self, mock_run):
        mock_run.return_value = MagicMock(returncode=0, stdout="memory\nfilesystem\n")
        entry = {"check": {"type": "mcp", "name": "memory"}}
        self.assertTrue(tk.check_installed(entry))

    @patch("toolkit.subprocess.run")
    def test_mcp_check_claude_cli_missing_is_unknown(self, mock_run):
        mock_run.return_value = MagicMock(returncode=1, stdout="")
        entry = {"check": {"type": "mcp", "name": "memory"}}
        self.assertIsNone(tk.check_installed(entry))

    def test_unknown_check_type_is_unknown(self):
        self.assertIsNone(tk.check_installed({"check": {"type": "something-else"}}))

    @patch("toolkit.subprocess.run", side_effect=Exception("boom"))
    def test_check_never_raises(self, mock_run):
        entry = {"check": {"type": "subprocess", "cmd": ["x"]}}
        self.assertIsNone(tk.check_installed(entry))


class TestPipShowInfo(unittest.TestCase):
    @patch("toolkit.subprocess.run")
    def test_parses_pip_show_output(self, mock_run):
        mock_run.return_value = MagicMock(
            returncode=0,
            stdout="Name: pypdf\nVersion: 3.1.0\nLicense: BSD\nHome-page: https://example.com\n")
        info = tk.pip_show_info("pypdf")
        self.assertEqual(info["name"], "pypdf")
        self.assertEqual(info["version"], "3.1.0")
        self.assertEqual(info["license"], "BSD")

    @patch("toolkit.subprocess.run")
    def test_returns_none_on_failure(self, mock_run):
        mock_run.return_value = MagicMock(returncode=1, stdout="")
        self.assertIsNone(tk.pip_show_info("nonexistent"))


class TestLedger(TempRoot):
    def test_open_installs_tracks_install_without_uninstall(self):
        tk.ledger_append(self.root, {"event": "install", "name": "pdf-text"})
        open_map = tk.open_installs(self.root)
        self.assertIn("pdf-text", open_map)

    def test_uninstall_event_closes_it(self):
        tk.ledger_append(self.root, {"event": "install", "name": "pdf-text"})
        tk.ledger_append(self.root, {"event": "uninstall", "name": "pdf-text"})
        self.assertEqual(tk.open_installs(self.root), {})

    def test_reinstall_after_uninstall_reopens(self):
        tk.ledger_append(self.root, {"event": "install", "name": "x", "ts": "1"})
        tk.ledger_append(self.root, {"event": "uninstall", "name": "x", "ts": "2"})
        tk.ledger_append(self.root, {"event": "install", "name": "x", "ts": "3"})
        open_map = tk.open_installs(self.root)
        self.assertIn("x", open_map)
        self.assertEqual(open_map["x"]["ts"], "3")

    def test_uninstall_never_invented_for_untouched_name(self):
        # No ledger at all -> nothing "open", and nothing to refuse-uninstall
        # incorrectly either. Guards the "never touch what we didn't install" rule.
        self.assertEqual(tk.open_installs(self.root, name="never-installed"), {})

    def test_corrupt_ledger_lines_are_skipped(self):
        path = tk.ledger_path(self.root)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as fh:
            fh.write('{"event": "install", "name": "ok"}\n')
            fh.write("not json at all\n")
        self.assertIn("ok", tk.open_installs(self.root))


if __name__ == "__main__":
    unittest.main()
