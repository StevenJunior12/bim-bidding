"""Tests for prompt_merge semantic override merge."""
import unittest

from app.prompt_merge import merge_semantic_overrides
from app.semantic_slots import SEMANTIC_SLOT_KEYS, get_default_semantic_overrides


class TestMergeSemanticOverrides(unittest.TestCase):
    def test_none_returns_defaults(self):
        base = get_default_semantic_overrides()
        self.assertEqual(merge_semantic_overrides(None), base)
        self.assertEqual(merge_semantic_overrides({}), base)

    def test_partial_override(self):
        base = get_default_semantic_overrides()
        out = merge_semantic_overrides({"analyze_system": "仅覆盖分析 system"})
        self.assertEqual(out["analyze_system"], "仅覆盖分析 system")
        self.assertEqual(out["analyze_user"], base["analyze_user"])

    def test_drops_unknown_keys(self):
        out = merge_semantic_overrides({"evil_key": "inject", "analyze_system": "ok"})
        self.assertNotIn("evil_key", out)
        self.assertEqual(set(out.keys()), set(SEMANTIC_SLOT_KEYS))
        self.assertEqual(out["analyze_system"], "ok")

    def test_whitespace_only_ignored(self):
        base = get_default_semantic_overrides()
        out = merge_semantic_overrides({"analyze_system": "   \n"})
        self.assertEqual(out["analyze_system"], base["analyze_system"])


if __name__ == "__main__":
    unittest.main()
