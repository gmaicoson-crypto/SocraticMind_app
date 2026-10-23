import unittest
from types import SimpleNamespace
from unittest.mock import patch

from ai.agent import chat_stream


def completed_chunk(content=None):
    return SimpleNamespace(
        choices=[SimpleNamespace(delta=SimpleNamespace(content=content), finish_reason="stop")]
    )


class ChatStreamTests(unittest.TestCase):
    def test_ignores_metadata_chunks_without_choices(self):
        chunks = [
            SimpleNamespace(choices=[SimpleNamespace(delta=SimpleNamespace(content="first"))]),
            SimpleNamespace(choices=[]),
            SimpleNamespace(choices=[SimpleNamespace(delta=SimpleNamespace(content=None))]),
            SimpleNamespace(choices=[SimpleNamespace(delta=SimpleNamespace(content="second"))]),
            completed_chunk(),
        ]
        completions = SimpleNamespace(create=lambda **_: iter(chunks))
        client = SimpleNamespace(chat=SimpleNamespace(completions=completions))

        with patch("ai.agent.get_ai_client", return_value=client):
            result = list(
                chat_stream(
                    messages=[],
                    node_label="test node",
                    node_sub="",
                    user_input="test question",
                )
            )

        self.assertEqual(result, ["first", "second"])

    def test_adds_memory_context_without_text_control_protocols(self):
        captured = {}

        def create(**kwargs):
            captured.update(kwargs)
            return iter([completed_chunk("reply")])

        completions = SimpleNamespace(create=create)
        client = SimpleNamespace(chat=SimpleNamespace(completions=completions))

        with patch("ai.agent.get_ai_client", return_value=client):
            list(
                chat_stream(
                    messages=[],
                    node_label="test node",
                    node_sub="",
                    user_input="test question",
                    memories=[{"kind": "preference", "content": "Use examples"}],
                )
            )

        system_prompt = captured["messages"][0]["content"]
        self.assertIn("Use examples", system_prompt)
        self.assertNotIn("[MASTERED]", system_prompt)
        self.assertNotIn("[CHOICES]", system_prompt)

    def test_socratic_styles_include_shared_explanation_guidance(self):
        captured = []

        def create(**kwargs):
            captured.append(kwargs["messages"][0]["content"])
            return iter([completed_chunk("reply")])

        completions = SimpleNamespace(create=create)
        client = SimpleNamespace(chat=SimpleNamespace(completions=completions))

        with patch("ai.agent.get_ai_client", return_value=client):
            for style in ("温和", "标准", "严格"):
                list(
                    chat_stream(
                        messages=[],
                        node_label="递归",
                        node_sub="Recursion",
                        user_input="我不太懂递归是什么",
                        ai_style=style,
                    )
                )

        for system_prompt, style in zip(captured, ("温和", "标准", "严格")):
            with self.subTest(style=style):
                self.assertIn("先讲清这个问题在解决什么", system_prompt)
                self.assertIn("明确回答原问题", system_prompt)
                self.assertIn("只有在追问确实能帮助学生继续思考时", system_prompt)
                self.assertIn(f"## {style}风格", system_prompt)
                self.assertNotIn("绝不直接给出答案", system_prompt)


if __name__ == "__main__":
    unittest.main()
