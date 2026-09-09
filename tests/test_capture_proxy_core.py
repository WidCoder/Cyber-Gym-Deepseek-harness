import json
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "capture_proxy"))

from capture_core import OpenAIChatAggregator, RequestCapture, SSEDecoder  # noqa: E402


class CaptureProxyCoreTest(unittest.TestCase):
    def test_openai_done_marker_completes_capture(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            capture = RequestCapture(root)
            capture.start_request(
                method="POST",
                path="/v1/chat/completions",
                query="",
                url="http://proxy/v1/chat/completions",
                headers=[("content-type", "application/json")],
                raw_body=json.dumps(
                    {
                        "model": "glm-5.3-flash",
                        "messages": [{"role": "user", "content": "hello"}],
                        "stream": True,
                    }
                ).encode(),
                upstream_url="http://glm:31542/v1/chat/completions",
                client_host="127.0.0.1",
                client_port=1234,
            )
            capture.start_response(
                status_code=200,
                headers=[("content-type", "text/event-stream")],
                is_sse=True,
            )
            decoder = SSEDecoder(OpenAIChatAggregator())
            body = (
                b'data: {"id":"chatcmpl-1","choices":[{"delta":{"role":"assistant","content":"OK"}}]}\n\n'
                b'data: {"choices":[{"delta":{},"finish_reason":"stop"}]}\n\n'
                b"data: [DONE]\n\n"
            )
            for chunk in (body[:17], body[17:63], body[63:]):
                capture.append_response(chunk)
                decoder.feed(chunk)
            capture.finalize()

            directory_path = next((root / "completed").iterdir())
            state = json.loads((directory_path / "state.json").read_text())
            response = json.loads((directory_path / "response.json").read_text())
            self.assertEqual(state["state"], "complete")
            self.assertTrue(response["stream_complete"])
            self.assertTrue(response["aggregation_complete"])
            self.assertEqual(response["protocol"], "openai-chat-completions")
            self.assertEqual(response["message"]["content"], "OK")

    def test_missing_openai_done_marker_is_partial(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            capture = RequestCapture(root)
            capture.start_request(
                method="POST",
                path="/v1/chat/completions",
                query="",
                url="http://proxy/v1/chat/completions",
                headers=[],
                raw_body=b'{"messages":[]}',
                upstream_url="http://glm:31542/v1/chat/completions",
                client_host=None,
                client_port=None,
            )
            capture.start_response(
                status_code=200,
                headers=[("content-type", "text/event-stream")],
                is_sse=True,
            )
            capture.append_response(
                b'data: {"choices":[{"delta":{"content":"partial"}}]}\n\n'
            )
            capture.finalize()

            directory_path = next((root / "completed").iterdir())
            state = json.loads((directory_path / "state.json").read_text())
            self.assertEqual(state["state"], "partial")


if __name__ == "__main__":
    unittest.main()
