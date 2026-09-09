import json
import tempfile
import unittest
from pathlib import Path

from harness.capture import write_capture_manifest
from scripts.export_training_data import export


class ExportTrainingDataTest(unittest.TestCase):
    def test_manifest_links_capture_and_harness_logs(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "capture"
            round_dir = root / "raw" / "completed" / "cap_1"
            round_dir.mkdir(parents=True)
            (round_dir / "request.json").write_text(
                json.dumps({"captured_at": "2026-09-09T01:00:00+00:00"}),
                encoding="utf-8",
            )
            (round_dir / "response.json").write_text(
                json.dumps({"finished_at": "2026-09-09T01:00:01+00:00"}),
                encoding="utf-8",
            )
            (round_dir / "response.body").write_text("{}", encoding="utf-8")
            (round_dir / "state.json").write_text(
                json.dumps({"state": "complete"}), encoding="utf-8"
            )
            log_dir = Path(directory) / "task-log"
            (log_dir / "logs").mkdir(parents=True)
            (log_dir / "console.log").write_text("event", encoding="utf-8")
            manifest = write_capture_manifest(
                root,
                log_dir,
                task_id="arvo:3569",
                agent_id="agent-1",
            )
            value = json.loads(manifest.read_text(encoding="utf-8"))
            self.assertEqual(value["capture_count"], 1)
            self.assertEqual(value["captures"][0]["capture_id"], "cap_1")
            self.assertEqual(value["task_id"], "arvo:3569")
            self.assertIn("console.log", value["harness_log_files"])
            self.assertEqual(value["captures"][0]["response_body"], str(round_dir / "response.body"))

    def test_openai_stream_keeps_tools_reasoning_and_tool_call(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "capture"
            round_dir = root / "raw" / "completed" / "cap_1"
            round_dir.mkdir(parents=True)
            request = {
                "body_json": {
                    "model": "glm-5.3-flash",
                    "system": "system instruction",
                    "messages": [{"role": "user", "content": "run it"}],
                    "tools": [{"type": "function", "function": {"name": "bash"}}],
                }
            }
            response = {"stream": True, "state": {"state": "complete"}}
            (round_dir / "request.json").write_text(json.dumps(request), encoding="utf-8")
            (round_dir / "response.json").write_text(json.dumps(response), encoding="utf-8")
            (round_dir / "response.body").write_text(
                'data: {"choices":[{"delta":{"role":"assistant","reasoning_content":"think"}}]}\n\n'
                'data: {"choices":[{"delta":{"tool_calls":[{"index":0,"id":"call_1","function":{"name":"bash","arguments":"{\\"cmd\\":\\"ls\\"}"}}]}}]}\n\n'
                "data: [DONE]\n\n",
                encoding="utf-8",
            )
            result = Path(directory) / "result.json"
            result.write_text(
                json.dumps(
                    {
                        "task": {"task_id": "arvo:3569", "agent_id": "agent"},
                        "agent": {"harness": "deepseek"},
                        "verification": {"vul_exit_code": 1, "fix_exit_code": 0},
                    }
                ),
                encoding="utf-8",
            )
            output = Path(directory) / "train.jsonl"
            self.assertEqual(export(root, output, {"task_id": "arvo:3569", "model": "glm-5.3-flash"}), 1)
            sample = json.loads(output.read_text(encoding="utf-8"))
            self.assertEqual(sample["id"], "arvo-glm-5.3-flash-main-cap_1")
            self.assertEqual(sample["messages"][0]["role"], "system")
            self.assertEqual(sample["messages"][-1]["reasoning_content"], "think")
            self.assertEqual(sample["messages"][-1]["tool_calls"][0]["id"], "call_1")
            self.assertEqual(sample["tools"][0]["function"]["name"], "bash")
            self.assertEqual(sample["metadata"]["agent_kind"], "main")

    def test_anthropic_stream_is_converted_to_openai_messages(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "capture"
            round_dir = root / "raw" / "completed" / "cap_2"
            round_dir.mkdir(parents=True)
            (round_dir / "request.json").write_text(
                json.dumps(
                    {
                        "body_json": {
                            "model": "glm-5.3-flash",
                            "system": [{"type": "text", "text": "system"}],
                            "messages": [{"role": "user", "content": [{"type": "text", "text": "run"}]}],
                        }
                    }
                ),
                encoding="utf-8",
            )
            (round_dir / "response.json").write_text(
                json.dumps({"stream": True, "state": {"state": "complete"}}), encoding="utf-8"
            )
            (round_dir / "state.json").write_text(
                json.dumps({"state": "complete"}), encoding="utf-8"
            )
            (round_dir / "response.body").write_text(
                "data: {\"type\":\"message_start\",\"message\":{\"role\":\"assistant\"}}\n\n"
                "data: {\"type\":\"content_block_start\",\"content_block\":{\"type\":\"thinking\"}}\n\n"
                "data: {\"type\":\"content_block_delta\",\"delta\":{\"type\":\"thinking_delta\",\"thinking\":\"reason\"}}\n\n"
                "data: {\"type\":\"content_block_start\",\"content_block\":{\"type\":\"tool_use\",\"id\":\"tool_1\",\"name\":\"bash\"}}\n\n"
                "data: {\"type\":\"content_block_delta\",\"delta\":{\"type\":\"input_json_delta\",\"partial_json\":\"{\\\"cmd\\\":\\\"ls\\\"}\"}}\n\n"
                "data: [DONE]\n\n",
                encoding="utf-8",
            )
            output = Path(directory) / "train.jsonl"
            self.assertEqual(
                export(
                    root,
                    output,
                    {"task_id": "arvo:3569", "model": "glm-5.3-flash"},
                    agent_kind="subagent",
                ),
                1,
            )
            sample = json.loads(output.read_text(encoding="utf-8"))
            self.assertEqual(sample["id"], "arvo-glm-5.3-flash-subagent-cap_2")
            self.assertEqual(sample["messages"][0]["role"], "system")
            assistant = sample["messages"][-1]
            self.assertEqual(assistant["reasoning_content"], "reason")
            self.assertEqual(assistant["tool_calls"][0]["function"]["name"], "bash")

    def test_partial_capture_is_not_exported(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "capture"
            round_dir = root / "raw" / "completed" / "cap_partial"
            round_dir.mkdir(parents=True)
            (round_dir / "request.json").write_text(
                json.dumps({"body_json": {"messages": [{"role": "user", "content": "hello"}]}}),
                encoding="utf-8",
            )
            (round_dir / "response.json").write_text(
                json.dumps({"stream": True}), encoding="utf-8"
            )
            (round_dir / "state.json").write_text(
                json.dumps({"state": "partial"}), encoding="utf-8"
            )
            (round_dir / "response.body").write_text(
                'data: {"choices":[{"delta":{"role":"assistant","content":"hello"}}]}\n\n',
                encoding="utf-8",
            )
            output = Path(directory) / "train.jsonl"
            self.assertEqual(
                export(root, output, {"task_id": "arvo:1", "model": "glm-5.3-flash"}),
                0,
            )
            self.assertEqual(output.read_text(encoding="utf-8"), "")


if __name__ == "__main__":
    unittest.main()
