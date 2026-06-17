#!/usr/bin/env python3
"""Behavior checks for reconcile_server.py."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import reconcile_server as r


class ReconcileServerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def write(self, name: str, content: bytes, *, is_dest: bool = False) -> r.Candidate:
        path = self.root / name
        path.write_bytes(content)
        return r.Candidate(path=path, size=path.stat().st_size, is_dest=is_dest)

    def test_binary_identical_and_conflict(self) -> None:
        a = self.write("a.BIN", b"abc\x00def")
        b = self.write("b.BIN", b"abc\x00def")
        dest = self.write("dest.BIN", b"abc\x00def", is_dest=True)
        different = self.write("different.BIN", b"abc\x00XYZ")

        self.assertEqual(r.resolve_group("thing.BIN", [a, b]).action, "copied_identical")
        self.assertEqual(r.resolve_group("thing.BIN", [a, b, dest]).action, "already_current")
        self.assertEqual(r.resolve_group("thing.BIN", [a, different]).action, "conflicts")

    def test_out_blocks_merge_deduplicate_and_stay_idempotent(self) -> None:
        block_2018 = b"***20180628-07h46mn41: sending cmd from a.cmd\nTx one\n\n"
        block_2026 = b"***20260522-06h10mn00: sending cmd from a.cmd\nTx two\n\n"
        a = self.write("a.out", block_2018)
        b = self.write("b.out", block_2026)
        superset = self.write("superset.out", block_2018 + block_2026)
        dest = self.write("dest.out", block_2018 + block_2026, is_dest=True)

        disjoint = r.resolve_group("thing.out", [a, b])
        self.assertEqual(disjoint.action, "merged_out_blocks")
        self.assertEqual(disjoint.merged_content, block_2018 + block_2026)

        deduped = r.resolve_group("thing.out", [a, superset])
        self.assertEqual(deduped.action, "merged_out_blocks")
        self.assertEqual(deduped.merged_content, block_2018 + block_2026)

        self.assertEqual(r.resolve_group("thing.out", [a, b, dest]).action, "already_current")

    def test_out_preamble_conflicts(self) -> None:
        good = self.write("good.out", b"***20180628-07h46mn41: sending cmd\nTx\n")
        bad = self.write("bad.out", b"not assignable\n***20180628-07h46mn41: sending cmd\n")

        result = r.resolve_group("thing.out", [bad, good])
        self.assertEqual(result.action, "conflicts")
        self.assertIsNotNone(result.conflict)

    def test_vit_record_merge_and_request_conflict(self) -> None:
        a = self.write("a.vit", b"alpha\n")
        b = self.write("b.vit", b"beta\n")
        merged = r.resolve_group("thing.vit", [a, b])
        self.assertEqual(merged.action, "merged_disjoint")
        self.assertEqual(merged.merged_content, b"alpha\nbeta\n")

        req_a = self.write("req_a.vit", b"mermaid REQUEST:2024-01-01T00_00_00,1200,5\n")
        req_b = self.write("req_b.vit", b"mermaid REQUEST:2024-01-01T00_00_00,1800,5\n")
        self.assertEqual(r.resolve_group("thing.vit", [req_a, req_b]).action, "conflicts")


if __name__ == "__main__":
    unittest.main()
