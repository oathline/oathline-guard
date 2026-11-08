"""The public kit (Claude 09:40 Mon 9 Nov 2026, AGENT 1), red first: what the release says is what the code does.

  K1 pyproject: `oathline-guard` 0.1.0, Python >= 3.10, depends on `oathline>=0.2.0,<0.3` (Core from PyPI) and nothing else,
     the `oathline-guard` console script is `oathline_guard.__main__:main`, MIT with LICENSE as its licence file
  K2 one version everywhere: pyproject, `oathline_guard.__version__`, server.json and its PyPI package, CHANGELOG's top entry,
     RELEASE_NOTES_<version>.md
  K3 LICENSE is MIT with Core's holder
  K4 server.json for the official MCP Registry: the schema's required fields and limits (name pattern, description <= 100),
     the org namespace io.github.oathline/, one PyPI package `oathline-guard` over stdio, the repository URL
  K5 the README carries the Registry's ownership line `mcp-name: <server.json name>` with a boundary after it
  K6 the README's quickstart is real: its Claude Desktop config is valid JSON whose args `oathline-guard` accepts (run, a read
     list, a human, `--`, the demo server); its read-list file is the shape the Guard reads; every `oathline-guard <cmd>` it
     names is a command the CLI knows
  K7 the README's approve-window block is the window's own output: the lines of the example's real run, the code aside
  K8 the tests use the installed Core (PyPI 0.2.x), not a path: tests/_core.py no longer reads OATHLINE_CORE_PATH
  K9 the sdist leaves tests and examples out (MANIFEST.in prunes them) and ships the README, LICENSE and the package
"""
import json
import os
import re
import subprocess
import sys
import unittest

from tests import _core

ROOT = _core.ROOT


def read(name):
    with open(os.path.join(ROOT, name), encoding="utf-8") as fh:
        return fh.read()


def pyproject():
    try:
        import tomllib
    except ModuleNotFoundError:                       # Python 3.10
        import tomli as tomllib                       # noqa: F401  (only the test needs it there)
    with open(os.path.join(ROOT, "pyproject.toml"), "rb") as fh:
        return tomllib.load(fh)


def server_json():
    return json.loads(read("server.json"))


def readme_blocks(lang):
    return re.findall(r"```" + lang + r"\n(.*?)```", read("README.md"), re.S)


class K1_Pyproject(unittest.TestCase):
    def test_k1(self):
        p = pyproject()["project"]
        self.assertEqual(p["name"], "oathline-guard")
        self.assertEqual(p["requires-python"], ">=3.10")
        self.assertEqual(p["dependencies"], ["oathline>=0.2.0,<0.3"])
        self.assertEqual(p["scripts"], {"oathline-guard": "oathline_guard.__main__:main"})
        self.assertEqual(p["license"], "MIT")
        self.assertEqual(p["license-files"], ["LICENSE"])
        self.assertEqual(p["urls"]["Repository"], "https://github.com/oathline/oathline-guard")


class K2_OneVersion(unittest.TestCase):
    def test_k2(self):
        import oathline_guard
        v = pyproject()["project"]["version"]
        self.assertEqual(v, "0.1.0")
        self.assertEqual(oathline_guard.__version__, v)
        s = server_json()
        self.assertEqual(s["version"], v)
        self.assertEqual([p["version"] for p in s["packages"]], [v])
        self.assertTrue(read("CHANGELOG.md").split("\n## ", 1)[1].startswith(v), "CHANGELOG's top entry is the version")
        self.assertTrue(os.path.isfile(os.path.join(ROOT, f"RELEASE_NOTES_{v}.md")))


class K3_License(unittest.TestCase):
    def test_k3(self):
        text = read("LICENSE")
        self.assertTrue(text.startswith("MIT License"))
        self.assertIn("Copyright (c) 2026 Nexxt Nest Group Pty Ltd (ABN 52 689 862 922)", text)


class K4_ServerJson(unittest.TestCase):
    def test_k4(self):
        s = server_json()
        self.assertEqual(s["$schema"], "https://static.modelcontextprotocol.io/schemas/2025-12-11/server.schema.json")
        self.assertEqual(s["name"], "io.github.oathline/oathline-guard")
        self.assertRegex(s["name"], r"^[a-zA-Z0-9.-]+/[a-zA-Z0-9._-]+$")
        self.assertLessEqual(len(s["description"]), 100)
        self.assertLessEqual(len(s.get("title", "")), 100)
        self.assertEqual(s["repository"], {"url": "https://github.com/oathline/oathline-guard", "source": "github"})
        (pkg,) = s["packages"]
        self.assertEqual((pkg["registryType"], pkg["identifier"], pkg["transport"]), ("pypi", "oathline-guard", {"type": "stdio"}))
        self.assertEqual(pkg.get("runtimeHint"), "uvx")
        named = {a["name"] for a in pkg["packageArguments"] if a["type"] == "named"}
        self.assertTrue({"--server", "--reads", "--human"} <= named)


class K5_McpName(unittest.TestCase):
    def test_k5(self):
        name = server_json()["name"]
        self.assertRegex(read("README.md"), r"mcp-name: " + re.escape(name) + r"(\s|-->|<)")


class K6_QuickstartIsReal(unittest.TestCase):
    def test_k6_config(self):
        configs = [json.loads(b) for b in readme_blocks("json") if '"mcpServers"' in b]
        self.assertEqual(len(configs), 1, "one Claude Desktop config in the README")
        (entry,) = configs[0]["mcpServers"].values()
        self.assertEqual(entry["command"], "oathline-guard")
        args = entry["args"]
        self.assertEqual(args[0], "run")
        cut = args.index("--")
        flags = args[1:cut]
        for flag in ("--server", "--reads", "--human"):
            self.assertIn(flag, flags)
        self.assertEqual(args[cut + 1:cut + 4], ["python", "-m", "oathline_guard.demo.fake_db"])
        from oathline_guard.record import server_name_ok
        self.assertTrue(server_name_ok(flags[flags.index("--server") + 1]))

    def test_k6_reads_file(self):
        reads = [json.loads(b) for b in readme_blocks("json") if '"reads"' in b and '"mcpServers"' not in b]
        self.assertEqual(len(reads), 1)
        self.assertEqual(set(reads[0]), {"server", "reads"})
        from oathline_guard.demo import fake_db
        tools = {t["name"] for t in fake_db.TOOLS}
        self.assertTrue(set(reads[0]["reads"]) <= tools)
        self.assertNotIn("drop_database", reads[0]["reads"])

    def test_k6_commands(self):
        from oathline_guard.__main__ import main
        text = read("README.md")                      # the commands as a reader types them: a code line, or inline code
        code = "\n".join(re.findall(r"```\w*\n(.*?)```", text, re.S))
        named = set(re.findall(r"(?m)^oathline-guard (\w+)", code)) | set(re.findall(r"`oathline-guard (\w+)", text))
        self.assertTrue(named)
        for cmd in named:
            self.assertIn(cmd, ("run", "approve"), cmd)
        self.assertEqual(main(["--help"]), 0)


class K7_WindowBlockIsReal(unittest.TestCase):
    def test_k7(self):
        p = subprocess.run([sys.executable, os.path.join(ROOT, "examples", "stop_the_delete.py")], capture_output=True, text=True,
                           encoding="utf-8", cwd=ROOT, timeout=120, env={**os.environ, "PYTHONUTF8": "1"})
        self.assertEqual(p.returncode, 0, p.stderr)
        real = [ln.strip() for ln in p.stdout.splitlines()]
        blocks = [b for b in readme_blocks("text") if "db / drop_database" in b]
        self.assertEqual(len(blocks), 1, "one approve-window block in the README")
        mask = lambda ln: re.sub(r"code: [A-Z0-9]{4}", "code: ####", re.sub(r"c-[0-9a-f]{8}", "c-########", ln))  # noqa: E731
        real_masked = [mask(ln) for ln in real]
        for ln in blocks[0].splitlines():
            if ln.strip() and not ln.startswith("$") and not ln.startswith("Type the code"):
                self.assertIn(mask(ln.strip()), real_masked, ln)


class K8_CoreFromPyPI(unittest.TestCase):
    def test_k8(self):
        self.assertNotIn("OATHLINE_CORE_PATH", read(os.path.join("tests", "_core.py")))
        import oathline
        self.assertTrue(oathline.__version__.startswith("0.2."), oathline.__version__)
        self.assertIn("site-packages", oathline.__file__.replace("\\", "/"))


class K9_Manifest(unittest.TestCase):
    def test_k9(self):
        m = read("MANIFEST.in")
        for line in ("prune tests", "prune examples"):
            self.assertIn(line, m)
        pkgs = pyproject()["tool"]["setuptools"]["packages"]
        self.assertEqual(sorted(pkgs), ["oathline_guard", "oathline_guard.demo"])


if __name__ == "__main__":
    unittest.main()
