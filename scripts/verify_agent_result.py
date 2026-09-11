import argparse
import json
import os
import sys
import tempfile
from pathlib import Path
from typing import Any

import httpx

from cybergym.server.pocdb import PoCRecord, Session, init_engine

API_KEY = os.getenv("CYBERGYM_API_KEY")
API_KEY_NAME = "X-API-Key"


def _configure_utf8_output() -> None:
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            reconfigure(encoding="utf-8", errors="backslashreplace")


def _write_verification_result(
    agent_id: str,
    status: str,
    records: list[dict[str, Any]],
    details: list[str],
) -> Path:
    """Write one structured result without changing the existing CLI."""
    configured = os.getenv("CYBERGYM_VERIFICATION_RESULT_PATH")
    output = Path(configured) if configured else Path.cwd() / "verification_result.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "agent_id": agent_id,
        "status": status,
        "verified": status == "verified",
        "records": records,
        "details": details,
    }
    # Atomic replacement prevents readers from observing a half-written JSON.
    with tempfile.NamedTemporaryFile(
        "w",
        encoding="utf-8",
        dir=str(output.parent),
        prefix=f".{output.name}.",
        suffix=".tmp",
        delete=False,
    ) as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2, default=str)
        handle.write("\n")
        temporary = Path(handle.name)
    os.replace(temporary, output)
    return output


def run_verify(agent_id: str, server: str) -> bool:
    with httpx.Client(base_url=server, timeout=1200, trust_env=False) as client:
        headers = {API_KEY_NAME: API_KEY} if API_KEY else {}
        try:
            response = client.post(
                "/verify-agent-pocs",
                json={"agent_id": agent_id},
                headers=headers,
            )
            print(
                f"verification_response agent_id={agent_id} "
                f"status={response.status_code} body={response.text}",
                flush=True,
            )
            return response.is_success
        except httpx.ReadTimeout:
            print(f"verification_error agent_id={agent_id} error=read_timeout", flush=True)
            return False
        except Exception as exc:
            print(
                f"verification_error agent_id={agent_id} error={exc}",
                flush=True,
            )
            return False


def query_remote_results(agent_id: str, server: str) -> list[dict[str, Any]]:
    """Return the remote verification records instead of only their count."""
    with httpx.Client(base_url=server, timeout=1200, trust_env=False) as client:
        headers = {API_KEY_NAME: API_KEY} if API_KEY else {}
        try:
            response = client.post(
                "/query-poc",
                json={"agent_id": agent_id},
                headers=headers,
            )
            if not response.is_success:
                print(
                    f"verification_query status={response.status_code} "
                    f"body={response.text}",
                    flush=True,
                )
                return []
            value = response.json()
            if isinstance(value, dict):
                value = [value]
            if not isinstance(value, list):
                print("verification_query_error error=response is not a list", flush=True)
                return []
            records = [item for item in value if isinstance(item, dict)]
            for record in records:
                print(json.dumps(record, ensure_ascii=False, default=str), flush=True)
            print(f"verification_records={len(records)} source=remote", flush=True)
            return records
        except Exception as exc:
            print(f"verification_query_error error={exc}", flush=True)
            return []


def load_results(pocdb_path: Path, agent_id: str) -> list[dict[str, Any]]:
    """Return local PoC records for the fallback verification path."""
    try:
        engine = init_engine(pocdb_path)
        with Session(engine) as session:
            pocs = session.query(PoCRecord).filter(PoCRecord.agent_id == agent_id).all()
            records: list[dict[str, Any]] = []
            for poc in pocs:
                record = poc.to_dict()
                record = record if isinstance(record, dict) else {"value": record}
                records.append(record)
                print(json.dumps(record, ensure_ascii=False, default=str), flush=True)
            print(f"verification_records={len(records)} source=local", flush=True)
            return records
    except Exception as exc:
        print(
            f"verification_query_error source=local agent_id={agent_id} error={exc}",
            flush=True,
        )
        return []


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--server",
        type=str,
        required=True,
        help="The server to send the verification request to.",
    )
    parser.add_argument(
        "--agent_id",
        type=str,
        required=True,
        help="The agent ID to verify.",
    )
    parser.add_argument(
        "--pocdb_path",
        type=Path,
        required=True,
        help="The path to the PoC database.",
    )

    args = parser.parse_args()
    _configure_utf8_output()

    details: list[str] = []
    remote_records: list[dict[str, Any]] = []
    local_records: list[dict[str, Any]] = []

    remote_verify_ok = run_verify(args.agent_id, args.server)
    details.append(f"remote_verify_ok={remote_verify_ok}")

    # Query remote records after a successful verification request. A local
    # record remains a valid fallback even if the remote request/query fails.
    if remote_verify_ok:
        remote_records = query_remote_results(args.agent_id, args.server)
        details.append(f"remote_records={len(remote_records)}")
    else:
        details.append("remote_query_skipped=verify_request_failed")

    if remote_records:
        records = remote_records
        verified = True
        details.append("verified_by=remote")
    else:
        local_records = load_results(args.pocdb_path, args.agent_id)
        details.append(f"local_records={len(local_records)}")
        records = local_records
        verified = bool(local_records)
        if verified:
            details.append("verified_by=local")

    status = "verified" if verified else "failed"
    result_path = _write_verification_result(
        args.agent_id,
        status,
        records,
        details,
    )
    print(f"verification_result={result_path}", flush=True)

    # Preserve the historical exit-code contract: success means at least one
    # verified remote or local record was found.
    raise SystemExit(0 if verified else 1)
