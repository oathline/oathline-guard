"""The Guard's long values as Core 0.3.0 `carried: "block"` items (Claude 17:40 Wed answer 3): the Guard no longer re-hashes the
window's block itself; Core's show() does, from the shown text.

  K1  a long or multi-line argument is stored in Core as a block item: value = the argument = {sha256, chars}, carried "block",
      label = its key; the capability declares the key in block_keys
  K2  the Guard's own re-hash is gone (no "shown_body_differs" in the record module); a block changed by one character is refused
      by Core (carried_hash_mismatch) and nothing is SHOWN; the right text shows
  K3  (FABLE 19:06 Thu 12 Nov, must-fix, fixed in Core e8964db) a long value with Windows line ends ("\r\n", any file written on
      Windows, also one ending in "\r\n") is SHOWN by Core from the Guard's own window text (what `approve` does); the same window with the "\r" taken out
      is refused (carried_hash_mismatch); on Core c65e4e8 the CRLF body could never be shown
"""
import inspect
import os
import shutil
import tempfile
import unittest

from tests import _core  # noqa: F401
from oathline_guard import record as R


class K1_K2(unittest.TestCase):
    def setUp(self):
        self.home = tempfile.mkdtemp(prefix="guard-block-")
        self.addCleanup(shutil.rmtree, self.home, True)
        self.rec = R.Record(os.path.join(self.home, "db"), "db", human="dana")
        self.rec.declare_tools([{"name": "write_file", "inputSchema": {"type": "object", "properties": {"path": {}, "body": {}}}}],
                               {"write_file"})

    def test_k1_k2(self):
        body = "x" * 600 + "\nline two"
        out = self.rec.propose("write_file", {"path": "/tmp/a.txt", "body": body})
        self.assertTrue(out.get("ok"), out)
        tok, call = out["token"], out["call"]
        items = {it["key"]: it for it in self.rec.engine().tokens.get(tok)["items"]}
        self.assertEqual(items["body"].get("carried"), "block")
        self.assertEqual(items["body"]["value"], {"sha256": R._sha(body), "chars": len(body)})
        cap = self.rec.engine().registry.get(self.rec.engine().tokens.get(tok)["capability"])
        self.assertIn("body", cap.block_keys)
        self.assertNotIn("shown_body_differs", inspect.getsource(R))
        good = self.rec.text(call)
        bad = good.replace("| line two", "| line TWO")
        self.assertEqual(self.rec.show(call, bad).get("error"), "carried_hash_mismatch")
        self.assertTrue(self.rec.show(call, good).get("ok"))


class K3_WindowsLineEnds(unittest.TestCase):
    def setUp(self):
        self.home = tempfile.mkdtemp(prefix="guard-crlf-")
        self.addCleanup(shutil.rmtree, self.home, True)
        self.rec = R.Record(os.path.join(self.home, "db"), "db", human="dana")
        self.rec.declare_tools([{"name": "write_file", "inputSchema": {"type": "object", "properties": {"path": {}, "body": {}}}}],
                               {"write_file"})

    def shows(self, body):
        out = self.rec.propose("write_file", {"path": "/tmp/a.txt", "body": body})
        self.assertTrue(out.get("ok"), out)
        call = out["call"]
        return call, self.rec.show(call, self.rec.text(call))

    def test_k3_crlf_body_shows(self):
        call, out = self.shows("x" * 600 + "\r\nline two\r\nline three")
        self.assertTrue(out.get("ok"), out)

    def test_k3_body_ending_in_crlf_shows(self):
        call, out = self.shows("y" * 600 + "\r\nlast line\r\n")
        self.assertTrue(out.get("ok"), out)

    def test_k3_cr_taken_out_is_refused(self):
        body = "z" * 600 + "\r\nline two"
        out = self.rec.propose("write_file", {"path": "/tmp/a.txt", "body": body})
        call = out["call"]
        stripped = self.rec.text(call).replace(CR_LINE_END, LF_ONLY)
        self.assertEqual(self.rec.show(call, stripped).get("error"), "carried_hash_mismatch")


CR_LINE_END, LF_ONLY = chr(13) + chr(10), chr(10)


if __name__ == "__main__":
    unittest.main()
