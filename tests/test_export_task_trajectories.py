import json
import tempfile
import unittest
from pathlib import Path

from scripts.export_task_trajectories import (
    _swe_agent_message,
    _swe_agent_tools,
    _validate_tool_sequence,
    export_task_trajectories,
)


def write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")


class TaskTrajectoryExportTest(unittest.TestCase):
    def _capture(self, root: Path, capture_id: str, messages: list[dict], answer: str, when: str) -> Path:
        directory = root / "raw" / "completed" / capture_id
        directory.mkdir(parents=True)
        write_json(
            directory / "request.json",
            {
                "capture_id": capture_id,
                "captured_at": when,
                "body_json": {"model": "glm-5.3-flash", "messages": messages, "tools": []},
            },
        )
        write_json(
            directory / "response.json",
            {
                "status_code": 200,
                "finished_at": when,
                "body_json": {"id": "resp-" + capture_id, "choices": [{"message": {"role": "assistant", "content": answer}}]},
            },
        )
        write_json(directory / "state.json", {"state": "complete"})
        return directory

    def test_joins_request_history_into_one_task_sample(self):
        with tempfile.TemporaryDirectory() as temporary:
            run = Path(temporary) / "round1"
            task_dir = run / "node0" / "worker0" / "logs" / "arvo_1-agent1"
            capture_root = Path(temporary) / "captures"
            c1 = self._capture(
                capture_root,
                "cap_1",
                [{"role": "user", "content": "hello"}],
                "first",
                "2026-09-10T00:00:01Z",
            )
            c2 = self._capture(
                capture_root,
                "cap_2",
                [
                    {"role": "user", "content": "hello"},
                    {"role": "assistant", "content": "first"},
                    {"role": "user", "content": "continue"},
                ],
                "second",
                "2026-09-10T00:00:02Z",
            )
            manifest = task_dir / "capture_manifest.json"
            write_json(
                manifest,
                {
                    "task_id": "arvo:1",
                    "agent_id": "agent1",
                    "captures": [
                        {"capture_id": "cap_1", "capture_dir": str(c1)},
                        {"capture_id": "cap_2", "capture_dir": str(c2)},
                    ],
                },
            )
            write_json(
                task_dir / "result.json",
                {
                    "task": {"task_id": "arvo:1", "agent_id": "agent1"},
                    "agent": {"agent_kind": "main"},
                    "execution": {"status": "completed"},
                    "verification": {"status": "verified"},
                    "provenance": {"capture_manifest": str(manifest)},
                },
            )
            output = Path(temporary) / "train.jsonl"
            report = export_task_trajectories(run, output)
            self.assertEqual(report["exported_samples"], 1)
            sample = json.loads(output.read_text(encoding="utf-8"))
            self.assertEqual(
                [(item["role"], item.get("content")) for item in sample["messages"]],
                [("user", "hello"), ("assistant", "first"), ("user", "continue"), ("assistant", "second")],
            )
            self.assertEqual(sample["metadata"]["capture_count"], 2)

    def test_incomplete_capture_is_skipped_without_faking_training_data(self):
        with tempfile.TemporaryDirectory() as temporary:
            run = Path(temporary) / "round1"
            task_dir = run / "node0" / "worker0" / "logs" / "arvo_2-agent2"
            capture_root = Path(temporary) / "captures"
            capture = self._capture(
                capture_root,
                "cap_partial",
                [{"role": "user", "content": "hello"}],
                "partial",
                "2026-09-10T00:00:01Z",
            )
            write_json(capture / "state.json", {"state": "partial"})
            manifest = task_dir / "capture_manifest.json"
            write_json(manifest, {"captures": [{"capture_id": "cap_partial", "capture_dir": str(capture)}]})
            write_json(
                task_dir / "result.json",
                {
                    "task": {"task_id": "arvo:2", "agent_id": "agent2"},
                    "execution": {"status": "completed"},
                    "provenance": {"capture_manifest": str(manifest)},
                },
            )
            output = Path(temporary) / "train.jsonl"
            report = export_task_trajectories(run, output)
            self.assertEqual(report["exported_samples"], 0)
            self.assertEqual(output.read_text(encoding="utf-8"), "")
            self.assertIn("state='partial'", report["skipped"][0]["reason"])

    def test_terminal_sse_marker_allows_late_client_disconnect(self):
        with tempfile.TemporaryDirectory() as temporary:
            run = Path(temporary) / "round1"
            task_dir = run / "node0" / "worker0" / "logs" / "arvo_3-agent3"
            capture_root = Path(temporary) / "captures"
            capture = self._capture(
                capture_root,
                "cap_done",
                [{"role": "user", "content": "hello"}],
                "ignored",
                "2026-09-10T00:00:01Z",
            )
            write_json(
                capture / "response.json",
                {
                    "status_code": 200,
                    "stream": True,
                    "stream_complete": True,
                    "aggregation_complete": True,
                    "transport_error": "CancelledError: client disconnected",
                    "client_disconnected": True,
                },
            )
            (capture / "response.body").write_text(
                'data: {"choices":[{"delta":{"role":"assistant","content":"done"}}]}\n\n'
                "data: [DONE]\n\n",
                encoding="utf-8",
            )
            manifest = task_dir / "capture_manifest.json"
            write_json(manifest, {"captures": [{"capture_id": "cap_done", "capture_dir": str(capture)}]})
            write_json(
                task_dir / "result.json",
                {
                    "task": {"task_id": "arvo:3", "agent_id": "agent3"},
                    "execution": {"status": "completed"},
                    "provenance": {"capture_manifest": str(manifest)},
                },
            )
            output = Path(temporary) / "train.jsonl"
            report = export_task_trajectories(run, output)
            self.assertEqual(report["exported_samples"], 1)
            sample = json.loads(output.read_text(encoding="utf-8"))
            self.assertEqual(sample["messages"][-1]["content"], "done")

    def test_recover_mode_accepts_legacy_partial_with_clean_done_marker(self):
        with tempfile.TemporaryDirectory() as temporary:
            run = Path(temporary) / "round1"
            task_dir = run / "node0" / "worker0" / "logs" / "arvo_4-agent4"
            capture_root = Path(temporary) / "captures"
            capture = self._capture(
                capture_root,
                "cap_legacy",
                [{"role": "user", "content": "hello"}],
                "done",
                "2026-09-10T00:00:01Z",
            )
            write_json(capture / "state.json", {"state": "partial"})
            (capture / "response.body").write_text(
                'data: {"choices":[{"delta":{"role":"assistant","content":"done"}}]}\n\n'
                "data: [DONE]\n\n",
                encoding="utf-8",
            )
            manifest = task_dir / "capture_manifest.json"
            write_json(manifest, {"captures": [{"capture_id": "cap_legacy", "capture_dir": str(capture)}]})
            write_json(
                task_dir / "result.json",
                {
                    "task": {"task_id": "arvo:4", "agent_id": "agent4"},
                    "execution": {"status": "completed"},
                    "provenance": {"capture_manifest": str(manifest)},
                },
            )
            output = Path(temporary) / "train.jsonl"
            report = export_task_trajectories(
                run, output, recover_terminal_sse=True
            )
            self.assertEqual(report["exported_samples"], 1)


    def test_swe_agent_schema_matches_reference_trajectory(self):
        assistant = _swe_agent_message({
            "role": "assistant",
            "content": "run it",
            "reasoning_content": "inspect first",
            "tool_calls": [{
                "id": "call_1",
                "type": "function",
                "function": {
                    "name": "bash",
                    "arguments": "{\"command\":\"pwd\"}",
                },
            }],
        })
        tool = _swe_agent_message({
            "role": "tool",
            "tool_call_id": "call_1",
            "content": "/workspace",
        })
        definitions = _swe_agent_tools([{
            "name": "bash",
            "description": "run a command",
            "input_schema": {
                "type": "object",
                "properties": {"command": {"type": "string"}},
            },
        }])
        self.assertEqual(assistant["content"], "inspect first\nrun it")
        self.assertEqual(
            assistant["tool_calls"],
            [{"name": "bash", "arguments": {"command": "pwd"}}],
        )
        self.assertEqual(tool, {"role": "tool", "content": "OBSERVATION:\n/workspace"})
        self.assertEqual(definitions[0]["name"], "bash")
        self.assertIn("parameters", definitions[0])

    def test_tool_sequence_rejects_unresolved_call(self):
        errors = _validate_tool_sequence([{
            "role": "assistant",
            "content": "",
            "tool_calls": [{
                "id": "call_1",
                "type": "function",
                "function": {"name": "bash", "arguments": "{}"},
            }],
        }])
        self.assertEqual(errors, ["unresolved tool calls: call_1"])


if __name__ == "__main__":
    unittest.main()
