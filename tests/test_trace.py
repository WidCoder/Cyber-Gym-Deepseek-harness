import json
import tempfile
import unittest
from pathlib import Path

from harness.trace import _normalize, normalize_session


class TraceNormalizationTest(unittest.TestCase):
    def test_real_payload_wins_over_dsh_event_label(self):
        event = _normalize(
            {
                "type": "assistant/chunk",
                "message": {"role": "assistant", "content": "assistant/chunk"},
                "data": {"text": "真实的模型回复"},
            },
            1,
        )
        self.assertEqual(event["message"]["content"], "真实的模型回复")

    def test_nested_data_payload_is_extracted_and_preserved(self):
        event = _normalize(
            {
                "type": "agent/inbox/spliced",
                "data": {
                    "items": [
                        {
                            "type": "assistant/chunk",
                            "message": {"role": "assistant", "content": "嵌套的真实内容"},
                        }
                    ]
                },
            },
            1,
        )
        self.assertEqual(event["message"]["content"], "嵌套的真实内容")
        self.assertEqual(event["data"]["items"][0]["message"]["content"], "嵌套的真实内容")

    def test_json_encoded_data_payload_is_extracted(self):
        event = _normalize(
            {
                "type": "assistant/chunk",
                "data": json.dumps(
                    {"message": {"role": "assistant", "content": "JSON中的真实内容"}},
                    ensure_ascii=False,
                ),
            },
            1,
        )
        self.assertEqual(event["message"]["content"], "JSON中的真实内容")

    def test_session_joins_payload_text_not_labels(self):
        with tempfile.TemporaryDirectory() as directory:
            session = Path(directory) / "session.jsonl"
            session.write_text(
                "\n".join(
                    [
                        json.dumps(
                            {
                                "type": "assistant/chunk",
                                "message": {"content": "assistant/chunk"},
                                "data": {"text": "第一段"},
                            }
                        ),
                        json.dumps(
                            {
                                "type": "assistant/chunk",
                                "message": {"content": "assistant/chunk"},
                                "delta": {"text": "第二段"},
                            }
                        ),
                    ]
                )
                + "\n",
                encoding="utf-8",
            )
            output = Path(directory) / "trajectory.jsonl"
            stats = normalize_session(session, output)
            self.assertEqual(stats["text"], 1)
            records = [json.loads(line) for line in output.read_text(encoding="utf-8").splitlines()]
            self.assertEqual(records[0]["message"]["content"], "第一段第二段")
            self.assertNotIn("assistant/chunk", records[0]["message"]["content"])


if __name__ == "__main__":
    unittest.main()
