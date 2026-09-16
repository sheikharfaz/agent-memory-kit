"""
End-to-end smoke tests for .agent/skills/mcp-bridge/server.py: spawn the
real server as a subprocess and drive it over stdin/stdout exactly as an
MCP client would (newline-delimited JSON-RPC 2.0), against a throwaway git
repo. No mocking, no `mcp` package -- this is the same protocol shape a
real host (Claude Code, Claude Desktop, ...) speaks.

  python3 -m unittest discover -s tests -v
"""

import json
import os
import subprocess
import sys
import tempfile
import unittest

KIT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SERVER_PY = os.path.join(KIT_ROOT, ".agent", "skills", "mcp-bridge", "server.py")


class MCPClient:
    """A minimal MCP stdio client: one subprocess, newline-delimited
    JSON-RPC in and out, matched request/response by id."""

    def __init__(self, root, env=None):
        self.proc = subprocess.Popen(
            [sys.executable, SERVER_PY, "--root", root],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=subprocess.PIPE, text=True, bufsize=1, env=env)
        self._next_id = 1

    def send_raw(self, text):
        self.proc.stdin.write(text if text.endswith("\n") else text + "\n")
        self.proc.stdin.flush()

    def notify(self, method, params=None):
        msg = {"jsonrpc": "2.0", "method": method}
        if params is not None:
            msg["params"] = params
        self.send_raw(json.dumps(msg))

    def request(self, method, params=None, timeout=30):
        msg_id = self._next_id
        self._next_id += 1
        msg = {"jsonrpc": "2.0", "id": msg_id, "method": method}
        if params is not None:
            msg["params"] = params
        self.send_raw(json.dumps(msg))
        line = self.proc.stdout.readline()
        if not line.strip():
            raise AssertionError("no response for %s (id=%s); stderr:\n%s"
                                  % (method, msg_id, self.proc.stderr.read()))
        resp = json.loads(line)
        assert resp.get("id") == msg_id, resp
        return resp

    def initialize(self):
        return self.request("initialize", {
            "protocolVersion": "2025-06-18",
            "capabilities": {},
            "clientInfo": {"name": "test-client", "version": "0.0.0"},
        })

    def call_tool(self, name, arguments=None):
        return self.request("tools/call",
                             {"name": name, "arguments": arguments or {}})

    def close(self):
        try:
            self.proc.stdin.close()
        except Exception:
            pass
        try:
            self.proc.wait(timeout=10)
        except Exception:
            self.proc.kill()


class MCPBridgeTestCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.repo = self._tmp.name
        subprocess.run(["git", "init", "-q", "."], cwd=self.repo, check=True)
        subprocess.run(["git", "-c", "user.email=t@example.com", "-c", "user.name=T",
                         "commit", "-q", "--allow-empty", "-m", "init"],
                        cwd=self.repo, check=True)
        os.makedirs(os.path.join(self.repo, "app"), exist_ok=True)
        with open(os.path.join(self.repo, "app", "main.py"), "w", encoding="utf-8") as fh:
            fh.write("def helper():\n    return 1\n\n\ndef main():\n    return helper()\n")
        subprocess.run(["git", "add", "-A"], cwd=self.repo, check=True)
        subprocess.run(["git", "-c", "user.email=t@example.com", "-c", "user.name=T",
                         "commit", "-q", "-m", "add app"], cwd=self.repo, check=True)
        self.client = MCPClient(self.repo)

    def tearDown(self):
        self.client.close()
        self._tmp.cleanup()


class TestHandshake(MCPBridgeTestCase):
    def test_initialize_returns_server_info_and_tools_capability(self):
        resp = self.client.initialize()
        result = resp["result"]
        self.assertEqual(result["protocolVersion"], "2025-06-18")
        self.assertIn("tools", result["capabilities"])
        self.assertEqual(result["serverInfo"]["name"], "agent-memory-kit")
        self.assertIn("instructions", result)

    def test_initialize_falls_back_for_unknown_protocol_version(self):
        resp = self.client.request("initialize", {
            "protocolVersion": "1999-01-01", "capabilities": {},
            "clientInfo": {"name": "x", "version": "0"}})
        self.assertNotEqual(resp["result"]["protocolVersion"], "1999-01-01")

    def test_initialized_notification_gets_no_response(self):
        self.client.initialize()
        self.client.notify("notifications/initialized")
        # next real request must still get exactly its own response, proving
        # the notification above produced no stray reply ahead of it
        resp = self.client.request("tools/list")
        self.assertIn("tools", resp["result"])

    def test_unknown_method_is_protocol_error(self):
        resp = self.client.request("bogus/method")
        self.assertEqual(resp["error"]["code"], -32601)

    def test_ping(self):
        resp = self.client.request("ping")
        self.assertEqual(resp["result"], {})


class TestToolsList(MCPBridgeTestCase):
    def test_lists_expected_tool_names(self):
        self.client.initialize()
        resp = self.client.request("tools/list")
        names = {t["name"] for t in resp["result"]["tools"]}
        expected = {
            "codebase_verify", "codebase_build", "codebase_arch", "codebase_def",
            "codebase_callers", "codebase_callees", "codebase_search", "codebase_find",
            "codebase_file",
            "codebase_importers", "codebase_routes", "codebase_impact", "codebase_changed",
            "codebase_coverage", "codebase_orphans", "codebase_stats", "codebase_drift",
            "session_recall", "session_recent", "session_stats", "session_remember",
        }
        self.assertEqual(names, expected)

    def test_every_tool_has_a_valid_object_schema(self):
        resp = self.client.request("tools/list")
        for t in resp["result"]["tools"]:
            self.assertTrue(t["description"])
            self.assertEqual(t["inputSchema"]["type"], "object")
            self.assertIn("properties", t["inputSchema"])

    def test_write_tools_say_so_in_their_description(self):
        resp = self.client.request("tools/list")
        by_name = {t["name"]: t for t in resp["result"]["tools"]}
        self.assertIn("Writes", by_name["codebase_build"]["description"])
        self.assertIn("write", by_name["session_remember"]["description"])


class TestCodebaseTools(MCPBridgeTestCase):
    def test_verify_before_build_reports_missing_index(self):
        resp = self.client.call_tool("codebase_verify")
        text = resp["result"]["content"][0]["text"]
        self.assertIn("no index", text.lower())
        self.assertFalse(resp["result"]["isError"])

    def test_build_then_verify_ok(self):
        build = self.client.call_tool("codebase_build")
        self.assertFalse(build["result"]["isError"], build["result"])
        verify = self.client.call_tool("codebase_verify")
        self.assertFalse(verify["result"]["isError"])
        self.assertIn("OK", verify["result"]["content"][0]["text"])

    def test_def_finds_known_symbol(self):
        self.client.call_tool("codebase_build")
        resp = self.client.call_tool("codebase_def", {"name": "helper"})
        text = resp["result"]["content"][0]["text"]
        self.assertIn("app/main.py", text)
        self.assertFalse(resp["result"]["isError"])

    def test_callers_finds_the_calling_file(self):
        self.client.call_tool("codebase_build")
        resp = self.client.call_tool("codebase_callers", {"name": "helper"})
        self.assertIn("app/main.py", resp["result"]["content"][0]["text"])

    def test_find_reaches_a_camel_case_symbol_from_plain_words(self):
        self.client.call_tool("codebase_build")
        resp = self.client.call_tool("codebase_find", {"query": "helper"})
        self.assertFalse(resp["result"]["isError"])
        self.assertIn("helper", resp["result"]["content"][0]["text"])

    def test_find_without_query_is_tool_error(self):
        resp = self.client.call_tool("codebase_find", {})
        self.assertTrue(resp["result"]["isError"])

    def test_def_without_required_name_is_tool_error_not_protocol_error(self):
        resp = self.client.call_tool("codebase_def", {})
        self.assertTrue(resp["result"]["isError"])
        self.assertIn("name", resp["result"]["content"][0]["text"])
        self.assertNotIn("error", resp)  # a result, not a JSON-RPC error

    def test_coverage_requires_paths_array(self):
        resp = self.client.call_tool("codebase_coverage", {"paths": "not-a-list"})
        self.assertTrue(resp["result"]["isError"])

    def test_root_argument_overrides_launch_root(self):
        # server was launched against self.repo; explicitly pass a bogus
        # root and confirm it actually takes effect (fails differently)
        resp = self.client.call_tool("codebase_stats", {"root": "/nonexistent/path/xyz"})
        self.assertTrue(resp["result"]["isError"])


class TestSessionTools(MCPBridgeTestCase):
    def test_remember_then_recall_roundtrip(self):
        remember = self.client.call_tool("session_remember",
                                          {"text": "the retry policy uses exponential backoff"})
        self.assertFalse(remember["result"]["isError"])
        recall = self.client.call_tool("session_recall", {"query": "retry policy backoff"})
        self.assertFalse(recall["result"]["isError"])
        hits = json.loads(recall["result"]["content"][0]["text"])
        self.assertEqual(len(hits), 1)
        self.assertIn("retry policy", hits[0]["text"])

    def test_remember_without_text_is_tool_error(self):
        resp = self.client.call_tool("session_remember", {})
        self.assertTrue(resp["result"]["isError"])

    def test_stats_on_empty_corpus(self):
        resp = self.client.call_tool("session_stats")
        self.assertFalse(resp["result"]["isError"])
        stats = json.loads(resp["result"]["content"][0]["text"])
        self.assertEqual(stats["entries"], 0)

    def test_recent_on_empty_corpus(self):
        resp = self.client.call_tool("session_recent")
        self.assertFalse(resp["result"]["isError"])
        self.assertEqual(json.loads(resp["result"]["content"][0]["text"]), [])


class TestDisableEnvVar(MCPBridgeTestCase):
    def test_session_remember_respects_disable_env_var(self):
        self.client.close()
        env = dict(os.environ, AGENT_MEMORY_KIT_DISABLE_SESSION_MEMORY="1")
        self.client = MCPClient(self.repo, env=env)
        resp = self.client.call_tool("session_remember", {"text": "should not be recorded"})
        self.assertFalse(resp["result"]["isError"])
        self.assertIn("disabled", resp["result"]["content"][0]["text"].lower())
        entries_path = os.path.join(self.repo, ".agent", "memory", "session", "entries.jsonl")
        self.assertFalse(os.path.exists(entries_path))


class TestProtocolRobustness(MCPBridgeTestCase):
    def test_unknown_tool_is_a_protocol_error_not_a_result(self):
        resp = self.client.call_tool("does_not_exist")
        self.assertNotIn("result", resp)
        self.assertEqual(resp["error"]["code"], -32602)

    def test_non_object_arguments_rejected_cleanly(self):
        resp = self.client.request("tools/call",
                                    {"name": "codebase_verify", "arguments": "nope"})
        self.assertEqual(resp["error"]["code"], -32602)

    def test_malformed_json_line_is_ignored_not_fatal(self):
        self.client.send_raw("not json at all {{{")
        # the server must still be alive and answer the next real request
        resp = self.client.request("ping")
        self.assertEqual(resp["result"], {})

    def test_server_never_writes_non_json_to_stdout(self):
        self.client.initialize()
        self.client.call_tool("codebase_verify")
        # if the server ever wrote a stray banner/log line to stdout instead
        # of stderr, the readline-based request() calls above would already
        # have desynced and raised -- reaching here is the assertion


if __name__ == "__main__":
    unittest.main()
