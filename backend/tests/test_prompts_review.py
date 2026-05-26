"""Tests for review prompts: build_review_messages and parse_review_output."""
import unittest

from app.prompts import (
    REVIEW_OUTPUT_FORMAT_SPEC,
    REVIEW_SYSTEM,
    build_review_messages,
    parse_review_output,
)


class TestBuildReviewMessages(unittest.TestCase):
    def test_placeholders_replaced(self):
        """User message must not contain any placeholder and must contain the given content."""
        chapter_full_name = "第1章 项目理解与分析"
        chapter_content = "本章为示例正文。"
        analyze_text = "招标要求摘要。"
        params_review_context = "废标点：xxx；响应要点：yyy"
        kb_context = "知识库片段。"
        messages = build_review_messages(
            chapter_full_name,
            chapter_content,
            analyze_text,
            params_review_context,
            kb_context,
        )
        self.assertEqual(len(messages), 2)
        user_content = messages[1]["content"]
        self.assertNotIn("{{#", user_content)
        self.assertIn(chapter_full_name, user_content)
        self.assertIn(chapter_content, user_content)
        self.assertIn(analyze_text, user_content)
        self.assertIn(params_review_context, user_content)
        self.assertIn(kb_context, user_content)

    def test_structure(self):
        """Return two messages: system and user, both with non-empty content."""
        messages = build_review_messages(
            "第1章 标题",
            "正文",
            "分析",
            "参数",
            "知识库",
        )
        self.assertEqual(len(messages), 2)
        self.assertEqual(messages[0]["role"], "system")
        self.assertTrue(messages[0]["content"])
        self.assertEqual(messages[1]["role"], "user")
        self.assertTrue(messages[1]["content"])

    def test_default_system_matches_review_system_constant(self):
        messages = build_review_messages("章", "正文", "分析", "参数", "知识库")
        self.assertEqual(messages[0]["content"], REVIEW_SYSTEM)

    def test_custom_review_system_appends_output_format_spec(self):
        custom = "自定义校审人设"
        merged = {"review_system": custom}
        messages = build_review_messages(
            "章", "正文", "分析", "参数", "知识库", semantic_overrides=merged
        )
        sys_c = messages[0]["content"]
        self.assertTrue(sys_c.startswith(custom))
        self.assertIn(REVIEW_OUTPUT_FORMAT_SPEC, sys_c)
        self.assertIn(custom + "\n\n" + REVIEW_OUTPUT_FORMAT_SPEC, sys_c)


class TestParseReviewOutput(unittest.TestCase):
    def test_valid_json(self):
        """Valid JSON array with type, description, quote returns expected list."""
        raw = '[{"type":"废标项","description":"缺少必须承诺","quote":"原文"}]'
        out = parse_review_output(raw)
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0]["type"], "废标项")
        self.assertEqual(out[0]["description"], "缺少必须承诺")
        self.assertEqual(out[0]["quote"], "原文")

        raw2 = '[{"type":"幻觉","description":"无依据"}]'
        out2 = parse_review_output(raw2)
        self.assertEqual(len(out2), 1)
        self.assertEqual(out2[0]["type"], "幻觉")
        self.assertEqual(out2[0]["description"], "无依据")
        self.assertEqual(out2[0]["quote"], "")

        raw3 = '[{"type":"套路","description":"空话"},{"type":"建议","description":"可补充"}]'
        out3 = parse_review_output(raw3)
        self.assertEqual(len(out3), 2)
        self.assertEqual(out3[0]["type"], "套路")
        self.assertEqual(out3[1]["type"], "建议")

    def test_empty(self):
        """Empty or empty-array input returns []."""
        self.assertEqual(parse_review_output(""), [])
        self.assertEqual(parse_review_output("   "), [])
        self.assertEqual(parse_review_output("[]"), [])
        self.assertEqual(parse_review_output("  []  "), [])

    def test_malformed(self):
        """Non-JSON or invalid structure returns [] without raising."""
        self.assertEqual(parse_review_output("not json"), [])
        self.assertEqual(parse_review_output("{}"), [])
        self.assertEqual(parse_review_output('{"a":1}'), [])
        self.assertEqual(parse_review_output('[1,2,3]'), [])
        self.assertEqual(parse_review_output('[{}]'), [])
        self.assertEqual(parse_review_output('[{"description":"no type"}]'), [])

    def test_markdown_wrapper(self):
        """JSON wrapped in markdown code block is parsed correctly."""
        raw = '```json\n[{"type":"废标项","description":"x","quote":""}]\n```'
        out = parse_review_output(raw)
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0]["type"], "废标项")
        self.assertEqual(out[0]["description"], "x")

    def test_invalid_type_normalized(self):
        """Invalid type is normalized to 建议."""
        raw = '[{"type":"其他","description":"某条"}]'
        out = parse_review_output(raw)
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0]["type"], "建议")
        self.assertEqual(out[0]["description"], "某条")


if __name__ == "__main__":
    unittest.main()
