import argparse
import json
import os
import sys
from pathlib import Path

import httpx

from cybergym.server.pocdb import PoCRecord, Session, init_engine

API_KEY = os.getenv("CYBERGYM_API_KEY")
API_KEY_NAME = "X-API-Key"


def _configure_utf8_output() -> None:
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            reconfigure(encoding="utf-8", errors="backslashreplace")


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


def query_remote_results(agent_id: str, server: str) -> int:
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
                return 0
            records = response.json()
            if isinstance(records, dict):
                records = [records]
            for record in records:
                print(json.dumps(record, ensure_ascii=False, default=str), flush=True)
            print(f"verification_records={len(records)} source=remote", flush=True)
            return len(records)
        except Exception as exc:
            print(f"verification_query_error error={exc}", flush=True)
            return 0


def load_results(pocdb_path: Path, agent_id: str) -> int:
    engine = init_engine(pocdb_path)
    with Session(engine) as session:
        pocs = session.query(PoCRecord).filter(PoCRecord.agent_id == agent_id).all()
        for poc in pocs:
            print(json.dumps(poc.to_dict(), ensure_ascii=False, default=str), flush=True)
        print(f"verification_records={len(pocs)}", flush=True)
        return len(pocs)


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

    if not run_verify(args.agent_id, args.server):
        raise SystemExit(1)
    if query_remote_results(args.agent_id, args.server) > 0:
        raise SystemExit(0)
    if load_results(args.pocdb_path, args.agent_id) == 0:
        print(
            f"verification_error agent_id={args.agent_id} "
            f"no_local_poc_record db={args.pocdb_path}",
            file=sys.stderr,
            flush=True,
        )
        raise SystemExit(1)
