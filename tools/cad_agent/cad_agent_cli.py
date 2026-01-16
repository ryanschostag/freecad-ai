#!/usr/bin/env python3
"""CAD Agent CLI

Interact with the local FreeCAD-AI API.

Default base URL: http://localhost:8080

Examples:
  python tools/cad_agent/cad_agent_cli.py health
  python tools/cad_agent/cad_agent_cli.py session create --title "itest"
  python tools/cad_agent/cad_agent_cli.py message send --session <SID> --prompt "Create a box 10mm x 20mm x 5mm" --mode design --export fcstd,step
  python tools/cad_agent/cad_agent_cli.py job wait --job <JOB_ID>

Use --debug to print request/response details and optionally write a debug bundle.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

import requests


def _json_dumps(obj: Any) -> str:
    return json.dumps(obj, indent=2, sort_keys=True, ensure_ascii=False)


@dataclass
class DebugConfig:
    enabled: bool
    out_dir: Optional[Path] = None


class ApiClient:
    def __init__(self, base_url: str, timeout_s: float = 30.0, debug: Optional[DebugConfig] = None):
        self.base_url = base_url.rstrip("/")
        self.timeout_s = timeout_s
        self.debug = debug or DebugConfig(enabled=False)

        if self.debug.enabled and self.debug.out_dir:
            self.debug.out_dir.mkdir(parents=True, exist_ok=True)

    def _dump(self, name: str, payload: Any) -> None:
        if not (self.debug.enabled and self.debug.out_dir):
            return
        p = self.debug.out_dir / name
        p.write_text(_json_dumps(payload) + "\n", encoding="utf-8")

    def request(self, method: str, path: str, *, json_body: Any = None, params: Dict[str, Any] | None = None) -> Tuple[int, Any]:
        url = f"{self.base_url}{path}"

        t0 = time.time()
        try:
            r = requests.request(method, url, json=json_body, params=params, timeout=self.timeout_s)
        except requests.RequestException as e:
            if self.debug.enabled:
                print(f"[debug] {method} {url} -> EXC {type(e).__name__}: {e}", file=sys.stderr)
            raise

        dt_ms = int((time.time() - t0) * 1000)

        # Try JSON first; fall back to text.
        body: Any
        try:
            body = r.json()
        except Exception:
            body = r.text

        if self.debug.enabled:
            print(f"[debug] {method} {url} -> {r.status_code} ({dt_ms}ms)", file=sys.stderr)
            if json_body is not None:
                print(f"[debug] request.json=\n{_json_dumps(json_body)}", file=sys.stderr)
            if params:
                print(f"[debug] request.params=\n{_json_dumps(params)}", file=sys.stderr)
            if isinstance(body, (dict, list)):
                print(f"[debug] response.json=\n{_json_dumps(body)}", file=sys.stderr)
            else:
                snippet = str(body)
                if len(snippet) > 2000:
                    snippet = snippet[:2000] + "..."
                print(f"[debug] response.text=\n{snippet}", file=sys.stderr)

        # Optional bundle
        stamp = time.strftime("%Y%m%dT%H%M%S")
        self._dump(f"{stamp}_{method}_{path.strip('/').replace('/', '_')}_request.json", {"method": method, "url": url, "json": json_body, "params": params})
        self._dump(f"{stamp}_{method}_{path.strip('/').replace('/', '_')}_response.json", {"status_code": r.status_code, "body": body})

        return r.status_code, body


def _print(obj: Any) -> None:
    if isinstance(obj, (dict, list)):
        print(_json_dumps(obj))
    else:
        print(obj)


def cmd_health(client: ApiClient, args: argparse.Namespace) -> int:
    code, body = client.request("GET", "/health")
    _print(body)
    if args.llm:
        code2, body2 = client.request("GET", "/health/llm")
        _print(body2)
        return 0 if (code == 200 and code2 == 200) else 1
    return 0 if code == 200 else 1


def cmd_session_create(client: ApiClient, args: argparse.Namespace) -> int:
    payload = {"title": args.title}
    if args.project_id:
        payload["project_id"] = args.project_id
    code, body = client.request("POST", "/v1/sessions", json_body=payload)
    _print(body)
    return 0 if code == 201 else 1


def cmd_session_close(client: ApiClient, args: argparse.Namespace) -> int:
    code, body = client.request("POST", f"/v1/sessions/{args.session_id}/close")
    _print(body)
    return 0 if code in (200, 204) else 1


def _parse_export(s: str) -> Dict[str, bool]:
    # Accept: fcstd,step,stl (comma-separated)
    enabled = {k.strip().lower() for k in s.split(",") if k.strip()}
    return {
        "fcstd": "fcstd" in enabled,
        "step": "step" in enabled,
        "stl": "stl" in enabled,
    }


def cmd_message_send(client: ApiClient, args: argparse.Namespace) -> int:
    payload = {
        "content": args.prompt,
        "mode": args.mode,
        "export": _parse_export(args.export),
        "units": args.units,
        "tolerance_mm": float(args.tolerance_mm),
    }
    if args.timeout_seconds is not None:
        payload["timeout_seconds"] = int(args.timeout_seconds)
    if args.max_repair_iterations is not None:
        payload["max_repair_iterations"] = int(args.max_repair_iterations)

    code, body = client.request("POST", f"/v1/sessions/{args.session_id}/messages", json_body=payload)
    _print(body)
    return 0 if code == 202 else 1


def cmd_job_get(client: ApiClient, args: argparse.Namespace) -> int:
    code, body = client.request("GET", f"/v1/jobs/{args.job_id}")
    _print(body)
    return 0 if code == 200 else 1


def cmd_job_wait(client: ApiClient, args: argparse.Namespace) -> int:
    deadline = time.time() + float(args.max_wait_s)
    last: Any = None
    while time.time() < deadline:
        code, body = client.request("GET", f"/v1/jobs/{args.job_id}")
        last = body
        if code != 200:
            _print(body)
            return 1
        status = body.get("status") if isinstance(body, dict) else None
        if status in ("finished", "failed"):
            _print(body)
            return 0 if status == "finished" else 2
        time.sleep(float(args.poll_s))

    # Timed out
    _print(last)
    return 3


def cmd_debug_bundle(client: ApiClient, args: argparse.Namespace) -> int:
    """Run a small end-to-end flow and write a debug bundle.

    This is meant for bug reports: it captures request/response JSON under --debug-out.
    """
    if not (client.debug.enabled and client.debug.out_dir):
        print("debug bundle requires --debug and --debug-out", file=sys.stderr)
        return 2

    # 1) health
    cmd_health(client, argparse.Namespace(llm=True))

    # 2) create session
    code, sess = client.request("POST", "/v1/sessions", json_body={"title": args.title})
    if code != 201 or not isinstance(sess, dict) or "session_id" not in sess:
        _print(sess)
        return 1
    sid = sess["session_id"]

    # 3) enqueue message
    payload = {
        "content": args.prompt,
        "mode": args.mode,
        "export": _parse_export(args.export),
        "units": args.units,
        "tolerance_mm": float(args.tolerance_mm),
    }
    code, msg = client.request("POST", f"/v1/sessions/{sid}/messages", json_body=payload)
    if code != 202 or not isinstance(msg, dict) or "job_id" not in msg:
        _print(msg)
        return 1

    job_id = msg["job_id"]

    # 4) wait
    rc = cmd_job_wait(client, argparse.Namespace(job_id=job_id, poll_s=args.poll_s, max_wait_s=args.max_wait_s))
    return rc


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="CAD Agent CLI")
    p.add_argument("--base-url", default=os.getenv("CAD_AGENT_BASE_URL", "http://localhost:8080"))
    p.add_argument("--timeout", type=float, default=float(os.getenv("CAD_AGENT_TIMEOUT_S", "30")))
    p.add_argument("--debug", action="store_true", help="print request/response details to stderr")
    p.add_argument("--debug-out", default=os.getenv("CAD_AGENT_DEBUG_OUT"), help="directory to write debug bundle JSON")

    sub = p.add_subparsers(dest="cmd", required=True)

    # health
    ph = sub.add_parser("health", help="check API health")
    ph.add_argument("--llm", action="store_true", help="also check /health/llm")
    ph.set_defaults(func=cmd_health)

    # session
    ps = sub.add_parser("session", help="session operations")
    ss = ps.add_subparsers(dest="session_cmd", required=True)

    sc = ss.add_parser("create", help="create a session")
    sc.add_argument("--title", required=True)
    sc.add_argument("--project-id")
    sc.set_defaults(func=cmd_session_create)

    sclose = ss.add_parser("close", help="close a session")
    sclose.add_argument("session_id")
    sclose.set_defaults(func=cmd_session_close)

    # message
    pm = sub.add_parser("message", help="message operations")
    ms = pm.add_subparsers(dest="message_cmd", required=True)

    send = ms.add_parser("send", help="enqueue a message for a session")
    send.add_argument("--session", dest="session_id", required=True)
    send.add_argument("--prompt", required=True)
    send.add_argument("--mode", default="design", choices=["design", "repair"])
    send.add_argument("--export", default="fcstd,step", help="comma-separated: fcstd,step,stl")
    send.add_argument("--units", default="mm")
    send.add_argument("--tolerance-mm", default="0.1")
    send.add_argument("--timeout-seconds", type=int)
    send.add_argument("--max-repair-iterations", type=int)
    send.set_defaults(func=cmd_message_send)

    # job
    pj = sub.add_parser("job", help="job operations")
    js = pj.add_subparsers(dest="job_cmd", required=True)

    jget = js.add_parser("get", help="get job status")
    jget.add_argument("job_id")
    jget.set_defaults(func=cmd_job_get)

    jwait = js.add_parser("wait", help="poll job until finished/failed")
    jwait.add_argument("job_id")
    jwait.add_argument("--poll-s", default=1.0, type=float)
    jwait.add_argument("--max-wait-s", default=300.0, type=float)
    jwait.set_defaults(func=cmd_job_wait)

    # debug
    pd = sub.add_parser("debug", help="debug helpers")
    ds = pd.add_subparsers(dest="debug_cmd", required=True)
    bundle = ds.add_parser("bundle", help="run a tiny e2e flow and write a debug bundle")
    bundle.add_argument("--title", default="debug")
    bundle.add_argument("--prompt", default="Create a simple box 10mm x 20mm x 5mm")
    bundle.add_argument("--mode", default="design", choices=["design", "repair"])
    bundle.add_argument("--export", default="fcstd,step")
    bundle.add_argument("--units", default="mm")
    bundle.add_argument("--tolerance-mm", default="0.1")
    bundle.add_argument("--poll-s", default=1.0, type=float)
    bundle.add_argument("--max-wait-s", default=300.0, type=float)
    bundle.set_defaults(func=cmd_debug_bundle)

    return p


def main(argv: Optional[list[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    dbg_out = Path(args.debug_out) if args.debug_out else None
    debug = DebugConfig(enabled=bool(args.debug), out_dir=dbg_out)
    client = ApiClient(args.base_url, timeout_s=args.timeout, debug=debug)

    return int(args.func(client, args))


if __name__ == "__main__":
    raise SystemExit(main())
