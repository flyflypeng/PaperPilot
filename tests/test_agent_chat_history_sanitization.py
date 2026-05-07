import unittest

from paperpilot.routes.agent_routes.agent_chat_route import (
    ThinkTagStreamFilter,
    normalize_chat_messages,
    strip_think_blocks,
)


class TestAgentChatHistorySanitization(unittest.TestCase):
    def test_stream_filter_removes_think_tags_split_across_chunks(self):
        chunks = [
            "Answer starts <thi",
            "nk>private reasoning",
            "</think> visible",
            "\n<think>drop me</think> done",
        ]
        stream_filter = ThinkTagStreamFilter()

        visible = "".join(stream_filter.feed(chunk) for chunk in chunks)
        visible += stream_filter.flush()

        self.assertEqual(visible, "Answer starts  visible\n done")

    def test_strip_think_blocks_removes_complete_and_unclosed_blocks(self):
        cleaned = strip_think_blocks(
            "before <think>hidden</think> middle <think>unfinished"
        )

        self.assertEqual(cleaned, "before  middle ")

    def test_normalize_chat_messages_tolerates_legacy_or_malformed_items(self):
        messages = [
            None,
            "plain assistant text",
            {"role": "assistant", "content": "<think>secret</think>answer"},
            {"role": "invalid", "content": {"answer": 42}},
            {"role": "user", "content": ["hello"]},
            {"role": "system", "content": "system prompt"},
        ]

        normalized = normalize_chat_messages(messages)

        self.assertEqual(
            [message["role"] for message in normalized],
            ["assistant", "assistant", "assistant", "assistant", "user", "system"],
        )
        self.assertEqual(normalized[0]["content"], "")
        self.assertEqual(normalized[1]["content"], "plain assistant text")
        self.assertEqual(normalized[2]["content"], "answer")
        self.assertIn('"answer": 42', normalized[3]["content"])
        self.assertEqual(normalized[4]["content"], '[\n  "hello"\n]')
        self.assertEqual(normalized[5]["content"], "system prompt")


if __name__ == "__main__":
    unittest.main()
