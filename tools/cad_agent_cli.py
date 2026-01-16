#!/usr/bin/env python3
"""CAD Agent CLI

A lightweight CLI for the CAD Agent API.
Usage examples:
  python tools/cad_agent_cli.py session create --title demo
  python tools/cad_agent_cli.py prompt send --session <SID> --text "Make a bracket" --wait
  python tools/cad_agent_cli.py job status --job <JOB_ID> --watch
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from typing import Any

import httpx

DEFAULT_BASE_URL = os.environ.get("CAD_AGENT_BASE_URL", "http://localhost:8080")


def _llm_ready(base_url: str) -> bool:
    with _client() as c:
        r = c.get(f"{base_url}/health/llm")
        if r.status_code != 200:
            return False
        try:
            data = r.json()
        except Exception:
            return False
        return bool(data.get("ok"))


def health_llm(args):
    with _client() as c:
        r = c.get(f"{args.base_url}/health/llm")
        print(r.status_code)
        try:
            _pp(r.json())
        except Exception:
            print(r.text)

def _client():
    return httpx.Client(timeout=60.0)

def _pp(obj: Any):
    print(json.dumps(obj, indent=2))

def session_create(args):
    payload = {"title": args.title, "project_id": args.project_id}
    with _client() as c:
        r = c.post(f"{args.base_url}/v1/sessions", json=payload)
        r.raise_for_status()
        _pp(r.json())

def session_end(args):
    with _client() as c:
        r = c.post(f"{args.base_url}/v1/sessions/{args.session_id}/end")
        r.raise_for_status()
        _pp(r.json())

def session_fork(args):
    with _client() as c:
        r = c.post(f"{args.base_url}/v1/sessions/{args.session_id}/fork")
        r.raise_for_status()
        _pp(r.json())

def prompt_send(args):
    if args.llm_check:
        if not _llm_ready(args.base_url):
            print("LLM health check failed; refusing to enqueue.", file=sys.stderr)
            sys.exit(2)
    payload = {
        "content": args.text,
        "mode": args.mode,
        "export": {"fcstd": args.fcstd, "step": args.step, "stl": args.stl},
        "units": args.units,
        "tolerance_mm": args.tolerance_mm,
    }
    with _client() as c:
        r = c.post(f"{args.base_url}/v1/sessions/{args.session_id}/messages", json=payload)
        r.raise_for_status()
        resp = r.json()
        _pp(resp)

    if args.wait:
        job_id = resp["job_id"]
        _watch_job(args.base_url, job_id, once=args.once)

def job_status(args):
    _watch_job(args.base_url, args.job_id, once=not args.watch)

def _watch_job(base_url: str, job_id: str, once: bool):
    with _client() as c:
        while True:
            r = c.get(f"{base_url}/v1/jobs/{job_id}")
            r.raise_for_status()
            data = r.json()
            _pp(data)
            st = data.get("status")
            if once or st in ("finished","failed"):
                return
            time.sleep(1.0)

def artifacts_list(args):
    with _client() as c:
        r = c.get(f"{args.base_url}/v1/sessions/{args.session_id}/artifacts")
        r.raise_for_status()
        _pp(r.json())

def logs_get(args):
    params = {}
    if args.since:
        params["since"] = args.since
    with _client() as c:
        r = c.get(f"{args.base_url}/v1/sessions/{args.session_id}/logs", params=params)
        r.raise_for_status()
        _pp(r.json())

def metrics_get(args):
    with _client() as c:
        r = c.get(f"{args.base_url}/v1/sessions/{args.session_id}/metrics")
        r.raise_for_status()
        _pp(r.json())

def rag_reconcile(args):
    with _client() as c:
        r = c.post(f"{args.base_url}/v1/rag/sources/reconcile")
        r.raise_for_status()
        _pp(r.json())

def rag_query(args):
    payload = {"query": args.query, "top_k": args.top_k, "max_trust_tier": args.max_trust_tier}
    with _client() as c:
        r = c.post(f"{args.base_url}/v1/rag/query", json=payload)
        r.raise_for_status()
        _pp(r.json())

def main():
    p = argparse.ArgumentParser(prog="cad-agent-cli")
    p.add_argument("--base-url", default=DEFAULT_BASE_URL, help="API base URL (or CAD_AGENT_BASE_URL env var)")
    sub = p.add_subparsers(dest="cmd", required=True)

    # health
    sp_health = sub.add_parser("health")
    health_sub = sp_health.add_subparsers(dest="sub", required=True)
    sp_h_llm = health_sub.add_parser("llm")
    sp_h_llm.set_defaults(func=health_llm)

    # session
    sp_sess = sub.add_parser("session")
    sess_sub = sp_sess.add_subparsers(dest="sub", required=True)

    sp_create = sess_sub.add_parser("create")
    sp_create.add_argument("--title", default="session")
    sp_create.add_argument("--project-id", default=None)
    sp_create.set_defaults(func=session_create)

    sp_end = sess_sub.add_parser("end")
    sp_end.add_argument("--session-id", required=True)
    sp_end.set_defaults(func=session_end)

    sp_fork = sess_sub.add_parser("fork")
    sp_fork.add_argument("--session-id", required=True)
    sp_fork.set_defaults(func=session_fork)

    # prompt
    sp_prompt = sub.add_parser("prompt")
    prompt_sub = sp_prompt.add_subparsers(dest="sub", required=True)
    sp_send = prompt_sub.add_parser("send")
    sp_send.add_argument("--session-id", required=True)
    sp_send.add_argument("--text", required=True)
    sp_send.add_argument("--mode", default="design", choices=["design","modify","explain","export"])
    sp_send.add_argument("--units", default="mm", choices=["mm","inch"])
    sp_send.add_argument("--tolerance-mm", type=float, default=0.1)
    sp_send.add_argument("--fcstd", action="store_true", default=True)
    sp_send.add_argument("--step", action="store_true", default=True)
    sp_send.add_argument("--stl", action="store_true", default=False)
    sp_send.add_argument("--wait", action="store_true", help="Poll until finished")
    sp_send.add_argument("--once", action="store_true", help="If --wait, print one poll only")
    sp_send.add_argument(
        "--no-llm-check",
        dest="llm_check",
        action="store_false",
        default=True,
        help="Skip calling /health/llm before enqueueing",
    )
    sp_send.set_defaults(func=prompt_send)

    # job
    sp_job = sub.add_parser("job")
    job_sub = sp_job.add_subparsers(dest="sub", required=True)
    sp_js = job_sub.add_parser("status")
    sp_js.add_argument("--job-id", required=True)
    sp_js.add_argument("--watch", action="store_true", help="Poll until finished/failed")
    sp_js.set_defaults(func=job_status)

    # artifacts
    sp_art = sub.add_parser("artifacts")
    art_sub = sp_art.add_subparsers(dest="sub", required=True)
    sp_al = art_sub.add_parser("list")
    sp_al.add_argument("--session-id", required=True)
    sp_al.set_defaults(func=artifacts_list)

    # logs
    sp_logs = sub.add_parser("logs")
    logs_sub = sp_logs.add_subparsers(dest="sub", required=True)
    sp_lg = logs_sub.add_parser("get")
    sp_lg.add_argument("--session-id", required=True)
    sp_lg.add_argument("--since", default=None, help="ISO datetime")
    sp_lg.set_defaults(func=logs_get)

    # metrics
    sp_met = sub.add_parser("metrics")
    met_sub = sp_met.add_subparsers(dest="sub", required=True)
    sp_mg = met_sub.add_parser("get")
    sp_mg.add_argument("--session-id", required=True)
    sp_mg.set_defaults(func=metrics_get)

    # rag
    sp_rag = sub.add_parser("rag")
    rag_sub = sp_rag.add_subparsers(dest="sub", required=True)
    sp_rr = rag_sub.add_parser("reconcile")
    sp_rr.set_defaults(func=rag_reconcile)
    sp_rq = rag_sub.add_parser("query")
    sp_rq.add_argument("--query", required=True)
    sp_rq.add_argument("--top-k", type=int, default=8)
    sp_rq.add_argument("--max-trust-tier", type=int, default=2)
    sp_rq.set_defaults(func=rag_query)

    args = p.parse_args()
    args.func(args)

if __name__ == "__main__":
    try:
        main()
    except httpx.HTTPStatusError as e:
        print(e.response.text, file=sys.stderr)
        raise
