import json
import tempfile
import unittest
from pathlib import Path

from scripts.update_task_result import main


class UpdateTaskResultTest(unittest.TestCase):
    def test_any_nonzero_vulnerability_exit_code_is_verified(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            result = root / "result.json"
            log = root / "verification.log"
            result.write_text(
                json.dumps({"verification": {"status": "pending"}}),
                encoding="utf-8",
            )
            log.write_text(
                '{"vul_exit_code": 77, "fix_exit_code": 0}\n',
                encoding="utf-8",
            )

            self.assertEqual(
                main(["--result", str(result), "--verification-log", str(log)]),
                0,
            )
            updated = json.loads(result.read_text(encoding="utf-8"))
            self.assertEqual(updated["verification"]["vul_exit_code"], 77)
            self.assertEqual(updated["verification"]["fix_exit_code"], 0)
            self.assertEqual(updated["verification"]["status"], "verified")


if __name__ == "__main__":
    unittest.main()
