"""Semantic slots and PromptProfile model (Phase A)."""
import unittest

import app.prompts as prompts
from app.models.task import Base
from app.semantic_slots import (
    CONTRACT_PROMPT_ATTRS,
    SEMANTIC_SLOT_KEYS,
    SEMANTIC_SLOTS,
    assert_semantic_catalog_matches_slots,
    catalog_id_for_slot,
    get_default_semantic_overrides,
)


class TestSemanticSlots(unittest.TestCase):
    def test_slot_count(self):
        self.assertEqual(len(SEMANTIC_SLOTS), 10)
        self.assertEqual(len(SEMANTIC_SLOT_KEYS), 10)

    def test_source_attrs_are_str_on_prompts(self):
        for slot in SEMANTIC_SLOTS:
            self.assertTrue(hasattr(prompts, slot.source_attr), slot.source_attr)
            val = getattr(prompts, slot.source_attr)
            self.assertIsInstance(val, str, slot.source_attr)
            self.assertGreater(len(val.strip()), 0, slot.source_attr)

    def test_default_overrides_keys(self):
        d = get_default_semantic_overrides()
        self.assertEqual(set(d.keys()), set(SEMANTIC_SLOT_KEYS))
        for k, v in d.items():
            self.assertIsInstance(v, str)
            self.assertGreater(len(v.strip()), 0, k)

    def test_contract_attrs_disjoint_from_slot_sources(self):
        slot_attrs = {s.source_attr for s in SEMANTIC_SLOTS}
        overlap = CONTRACT_PROMPT_ATTRS & slot_attrs
        self.assertEqual(
            overlap,
            set(),
            f"Contract set must not include semantic slot sources: {overlap}",
        )

    def test_catalog_alignment(self):
        assert_semantic_catalog_matches_slots()

    def test_catalog_id_roundtrip(self):
        for slot in SEMANTIC_SLOTS:
            self.assertEqual(catalog_id_for_slot(slot.slot_key), f"semantic.{slot.slot_key}")


class TestPromptProfileModel(unittest.TestCase):
    def test_table_registered(self):
        self.assertIn("prompt_profiles", Base.metadata.tables)


if __name__ == "__main__":
    unittest.main()
