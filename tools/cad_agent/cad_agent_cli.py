#!/usr/bin/env python3
"""CAD Agent CLI.

Interact with the local FreeCAD-AI API.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Optional, Tuple
from urllib.parse import urlparse, urlunparse

import requests


def _json_dumps(obj: Any) -> str:
    return json.dumps(obj, indent=2, sort_keys=True, ensure_ascii=False)


def _safe_name(value: str) -> str:
    keep = []
    for ch in value:
        if ch.isalnum() or ch in {"-", "_", "."}:
            keep.append(ch)
        else:
            keep.append("_")
    out = "".join(keep).strip("._")
    return out or "artifact"


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

        try:
            body: Any = r.json()
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

        stamp = time.strftime("%Y%m%dT%H%M%S")
        stem = path.strip("/").replace("/", "_") or "root"
        self._dump(f"{stamp}_{method}_{stem}_request.json", {"method": method, "url": url, "json": json_body, "params": params})
        self._dump(f"{stamp}_{method}_{stem}_response.json", {"status_code": r.status_code, "body": body})

        return r.status_code, body

    def download_to(self, url: str, out_path: Path) -> None:
        out_path.parent.mkdir(parents=True, exist_ok=True)
        with requests.get(url, stream=True, timeout=self.timeout_s) as resp:
            resp.raise_for_status()
            with out_path.open("wb") as f:
                for chunk in resp.iter_content(chunk_size=1024 * 128):
                    if chunk:
                        f.write(chunk)


def _candidate_download_urls(base_url: str, download_url: str) -> list[str]:
    parsed = urlparse(download_url)
    if not parsed.scheme or not parsed.netloc:
        return [download_url]

    candidates: list[str] = [download_url]
    hostname = (parsed.hostname or "").lower()
    known_internal = {"minio", "api", "db", "redis", "llm", "llm-fake", "freecad-worker", "api-test"}
    if hostname not in known_internal:
        return candidates

    public_base = os.getenv("CAD_AGENT_ARTIFACT_BASE_URL") or os.getenv("MINIO_PUBLIC_BASE_URL")
    if public_base:
        pub = urlparse(public_base.rstrip("/"))
        if pub.scheme and pub.netloc:
            replacement = parsed._replace(scheme=pub.scheme, netloc=pub.netloc)
            candidates.append(urlunparse(replacement))

    api_host = (urlparse(base_url).hostname or "").lower()
    for host in [api_host, "localhost", "127.0.0.1", "host.docker.internal"]:
        if not host or host == hostname:
            continue
        if host in known_internal:
            continue
        netloc = f"{host}:{parsed.port}" if parsed.port else host
        replacement = parsed._replace(netloc=netloc)
        alt = urlunparse(replacement)
        if alt not in candidates:
            candidates.append(alt)
    return candidates


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


def cmd_session_logs(client: ApiClient, args: argparse.Namespace) -> int:
    params: Dict[str, Any] = {}
    if args.since:
        params["since"] = args.since
    code, body = client.request("GET", f"/v1/sessions/{args.session_id}/logs", params=params)
    if code == 200 and isinstance(body, dict) and args.tail and isinstance(body.get("events"), list):
        body = dict(body)
        body["events"] = body["events"][-args.tail :]
    _print(body)
    return 0 if code == 200 else 1


def _download_session_artifacts(client: ApiClient, session_id: str, out_dir: Path) -> dict[str, Any]:
    code, body = client.request("GET", f"/v1/sessions/{session_id}/artifacts")
    if code != 200 or not isinstance(body, dict):
        raise RuntimeError(f"failed to list artifacts for session {session_id}: {body}")

    artifacts = body.get("artifacts") or []
    out_dir.mkdir(parents=True, exist_ok=True)
    manifest: dict[str, Any] = {"session_id": session_id, "downloaded": []}

    for idx, art in enumerate(artifacts, start=1):
        artifact_id = art.get("artifact_id")
        if not artifact_id:
            continue
        info_code, info = client.request("GET", f"/v1/artifacts/{artifact_id}")
        if info_code != 200 or not isinstance(info, dict):
            manifest["downloaded"].append({"artifact_id": artifact_id, "status": "metadata_failed", "detail": info})
            continue

        url = info.get("download_url")
        proxy_download_url = info.get("proxy_download_url")
        if not url and not proxy_download_url:
            manifest["downloaded"].append({"artifact_id": artifact_id, "status": "missing_download_url"})
            continue

        parsed = urlparse(url or proxy_download_url)
        suffix = Path(parsed.path).suffix
        fname = f"{idx:03d}_{_safe_name(str(info.get('kind') or 'artifact'))}_{_safe_name(str(artifact_id))}{suffix}"
        dest = out_dir / fname

        candidates = _candidate_download_urls(client.base_url, url) if url else []
        if proxy_download_url:
            if proxy_download_url.startswith("http://") or proxy_download_url.startswith("https://"):
                proxy_candidate = proxy_download_url
            else:
                proxy_candidate = f"{client.base_url.rstrip('/')}/{proxy_download_url.lstrip('/')}"
            if proxy_candidate not in candidates:
                candidates.append(proxy_candidate)

        last_error: str | None = None
        for candidate in candidates:
            try:
                client.download_to(candidate, dest)
                manifest["downloaded"].append({
                    "artifact_id": artifact_id,
                    "kind": info.get("kind"),
                    "object_key": info.get("object_key"),
                    "path": str(dest),
                    "download_url": candidate,
                    "source_download_url": url,
                    "proxy_download_url": proxy_download_url,
                })
                break
            except requests.RequestException as exc:
                last_error = f"{type(exc).__name__}: {exc}"
                if dest.exists():
                    dest.unlink()
        else:
            manifest["downloaded"].append({
                "artifact_id": artifact_id,
                "kind": info.get("kind"),
                "object_key": info.get("object_key"),
                "status": "download_failed",
                "source_download_url": url,
                "proxy_download_url": proxy_download_url,
                "tried_urls": candidates,
                "error": last_error,
            })

    (out_dir / "manifest.json").write_text(_json_dumps(manifest) + "\n", encoding="utf-8")
    return manifest


def cmd_session_artifacts(client: ApiClient, args: argparse.Namespace) -> int:
    code, body = client.request("GET", f"/v1/sessions/{args.session_id}/artifacts")
    if code != 200:
        _print(body)
        return 1
    if args.download_dir:
        manifest = _download_session_artifacts(client, args.session_id, Path(args.download_dir))
        _print({"artifacts": body.get("artifacts") if isinstance(body, dict) else body, "download_manifest": manifest})
        return 0
    _print(body)
    return 0


def _parse_export(s: str) -> Dict[str, bool]:
    enabled = {k.strip().lower() for k in s.split(",") if k.strip()}
    return {"fcstd": "fcstd" in enabled, "step": "step" in enabled, "stl": "stl" in enabled}


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
    job_id = getattr(args, "job", None) or getattr(args, "job_id", None)
    if not job_id:
        raise SystemExit("job wait: missing job id (use positional JOB_ID or --job JOB_ID)")

    deadline = time.time() + float(args.max_wait_s)
    last: Any = None
    while time.time() < deadline:
        code, body = client.request("GET", f"/v1/jobs/{job_id}")
        last = body
        if code != 200:
            _print(body)
            return 1
        status = body.get("status") if isinstance(body, dict) else None
        if status in ("finished", "failed"):
            _print(body)
            return 0 if status == "finished" else 2
        time.sleep(float(args.poll_s))

    _print(last)
    return 3


def _sanitize_env_text(text: str) -> str:
    out = []
    sensitive_tokens = ("PASSWORD", "SECRET", "TOKEN", "KEY")
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in line:
            out.append(line)
            continue
        key, _, value = line.partition("=")
        if any(token in key.upper() for token in sensitive_tokens):
            out.append(f"{key}=<redacted>")
        else:
            out.append(f"{key}={value}")
    return "\n".join(out) + ("\n" if text.endswith("\n") else "")


def _copy_sanitized_configs(bundle_dir: Path) -> list[str]:
    repo_root = Path.cwd()
    copied: list[str] = []
    candidates = [
        repo_root / "docker-compose.yml",
        repo_root / "docker-compose.gpu.override.yml",
        repo_root / "docker-compose.test-override.yml",
        repo_root / "build-start-cpu-profile.sh",
        repo_root / "build-start-test-profile.sh",
        repo_root / ".env",
        repo_root / ".env.sample",
        repo_root / "rag_sources.yaml",
        repo_root / "services" / "api" / "app" / "settings.py",
        repo_root / "services" / "freecad-worker" / "worker" / "settings.py",
    ]
    cfg_dir = bundle_dir / "config"
    cfg_dir.mkdir(parents=True, exist_ok=True)
    for src in candidates:
        if not src.exists() or not src.is_file():
            continue
        rel = src.relative_to(repo_root)
        dst = cfg_dir / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        if src.name.startswith(".env"):
            dst.write_text(_sanitize_env_text(src.read_text(encoding="utf-8")), encoding="utf-8")
        else:
            shutil.copy2(src, dst)
        copied.append(str(rel))
    return copied


def _collect_docker_logs(bundle_dir: Path) -> list[str]:
    logs_dir = bundle_dir / "docker_logs"
    logs_dir.mkdir(parents=True, exist_ok=True)
    compose_cmd = ["docker", "compose"]
    ps = subprocess.run(compose_cmd + ["ps", "--services"], capture_output=True, text=True)
    if ps.returncode != 0:
        (logs_dir / "docker-compose-ps.error.txt").write_text((ps.stderr or ps.stdout or "docker compose ps failed") + "\n", encoding="utf-8")
        return []

    services = [line.strip() for line in ps.stdout.splitlines() if line.strip()]
    collected: list[str] = []
    for service in services:
        proc = subprocess.run(compose_cmd + ["logs", "--no-color", service], capture_output=True, text=True)
        text = proc.stdout if proc.returncode == 0 else (proc.stdout or "") + ("\n" if proc.stdout and proc.stderr else "") + (proc.stderr or "")
        (logs_dir / f"{_safe_name(service)}.log").write_text(text, encoding="utf-8")
        collected.append(service)
    return collected


def _zip_tree(src_dir: Path, out_file: Path) -> None:
    out_file.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(out_file, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for path in sorted(src_dir.rglob("*")):
            if path.is_file():
                zf.write(path, path.relative_to(src_dir))




def _extract_prompt_and_config_from_logs(logs: dict[str, Any]) -> tuple[str | None, dict[str, Any] | None]:
    events = logs.get("events") if isinstance(logs, dict) else None
    if not isinstance(events, list):
        return None, None
    for event in reversed(events):
        if not isinstance(event, dict):
            continue
        if event.get("type") != "message.user":
            continue
        payload = event.get("payload") or {}
        if not isinstance(payload, dict):
            continue
        prompt = payload.get("prompt")
        cfg = {k: payload.get(k) for k in ("mode", "export", "units", "tolerance_mm", "timeout_seconds") if k in payload}
        return (str(prompt) if prompt is not None else None), cfg
    return None, None

def cmd_job_diagnose(client: ApiClient, args: argparse.Namespace) -> int:
    out_zip = Path(args.out)
    with tempfile.TemporaryDirectory(prefix="cad-agent-diagnose-") as tmp:
        root = Path(tmp)

        status_code, job = client.request("GET", f"/v1/jobs/{args.job_id}")
        if status_code != 200 or not isinstance(job, dict):
            _print(job)
            return 1
        (root / "job.json").write_text(_json_dumps(job) + "\n", encoding="utf-8")

        session_id = job.get("session_id") or args.session_id
        if not session_id:
            raise SystemExit("job diagnose: no session_id in job response; pass --session-id SESSION_ID")

        logs_code, logs = client.request("GET", f"/v1/sessions/{session_id}/logs")
        (root / "session_logs.json").write_text(_json_dumps(logs) + "\n", encoding="utf-8")
        if logs_code != 200:
            return 1
        prompt_text, request_config = _extract_prompt_and_config_from_logs(logs if isinstance(logs, dict) else {})
        if prompt_text is not None:
            (root / "prompt.txt").write_text(prompt_text + ("\n" if not prompt_text.endswith("\n") else ""), encoding="utf-8")
        if request_config is not None:
            (root / "request_config.json").write_text(_json_dumps(request_config) + "\n", encoding="utf-8")

        arts_manifest = _download_session_artifacts(client, session_id, root / "artifacts")
        (root / "artifacts_manifest.json").write_text(_json_dumps(arts_manifest) + "\n", encoding="utf-8")

        copied_cfgs = _copy_sanitized_configs(root)
        docker_services = _collect_docker_logs(root)

        downloaded = arts_manifest.get("downloaded", [])
        summary = {
            "has_prompt_file": (root / "prompt.txt").exists(),
            "has_request_config_file": (root / "request_config.json").exists(),
            "job_id": args.job_id,
            "session_id": session_id,
            "artifact_count": len(downloaded),
            "artifact_download_failures": [item for item in downloaded if item.get("status") == "download_failed"],
            "config_files": copied_cfgs,
            "docker_services": docker_services,
            "notes": [
                "Structured session log events come from /v1/sessions/{session_id}/logs.",
                "Container stdout/stderr logs come from docker compose logs and are stored under docker_logs/.",
                "Sensitive values from .env files are redacted in config/.",
                "Artifact download URLs from internal Docker hostnames are rewritten to host-reachable URLs when needed.",
            ],
        }
        (root / "summary.json").write_text(_json_dumps(summary) + "\n", encoding="utf-8")
        _zip_tree(root, out_zip)

    print(str(out_zip))
    return 0


def cmd_debug_bundle(client: ApiClient, args: argparse.Namespace) -> int:
    if not (client.debug.enabled and client.debug.out_dir):
        print("debug bundle requires --debug and --debug-out", file=sys.stderr)
        return 2

    cmd_health(client, argparse.Namespace(llm=True))

    code, sess = client.request("POST", "/v1/sessions", json_body={"title": args.title})
    if code != 201 or not isinstance(sess, dict) or "session_id" not in sess:
        _print(sess)
        return 1
    sid = sess["session_id"]

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

    return cmd_job_wait(client, argparse.Namespace(job_id=msg["job_id"], poll_s=args.poll_s, max_wait_s=args.max_wait_s))


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="CAD Agent CLI")
    p.add_argument("--base-url", default=os.getenv("CAD_AGENT_BASE_URL", "http://localhost:8080"))
    p.add_argument("--timeout", type=float, default=float(os.getenv("CAD_AGENT_TIMEOUT_S", "30")))
    p.add_argument("--debug", action="store_true", help="print request/response details to stderr")
    p.add_argument("--debug-out", default=os.getenv("CAD_AGENT_DEBUG_OUT"), help="directory to write debug bundle JSON")

    sub = p.add_subparsers(dest="cmd", required=True)

    ph = sub.add_parser("health", help="check API health")
    ph.add_argument("--llm", action="store_true", help="also check /health/llm")
    ph.set_defaults(func=cmd_health)

    ps = sub.add_parser("session", help="session operations")
    ss = ps.add_subparsers(dest="session_cmd", required=True)

    sc = ss.add_parser("create", help="create a session")
    sc.add_argument("--title", required=True)
    sc.add_argument("--project-id")
    sc.set_defaults(func=cmd_session_create)

    sclose = ss.add_parser("close", help="close a session")
    sclose.add_argument("session_id")
    sclose.set_defaults(func=cmd_session_close)

    slogs = ss.add_parser("logs", help="fetch session log events")
    slogs.add_argument("session_id")
    slogs.add_argument("--since", help="ISO timestamp; only return events at/after this time (e.g. 2026-01-21T20:00:00Z)")
    slogs.add_argument("--tail", type=int, default=0, help="Only print the last N events (client-side). 0 means all events returned by the API.")
    slogs.set_defaults(func=cmd_session_logs)

    sarts = ss.add_parser("artifacts", help="list or download all artifacts for a session")
    sarts.add_argument("session_id")
    sarts.add_argument("--download-dir", help="download all session artifacts into this directory")
    sarts.set_defaults(func=cmd_session_artifacts)

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

    pj = sub.add_parser("job", help="job operations")
    js = pj.add_subparsers(dest="job_cmd", required=True)

    jget = js.add_parser("get", help="get job status")
    jget.add_argument("job_id")
    jget.set_defaults(func=cmd_job_get)

    jwait = js.add_parser("wait", help="poll job until finished/failed")
    jwait.add_argument("job_id", nargs="?", help="Job id")
    jwait.add_argument("--job", dest="job", help="Job id (alias for positional JOB_ID)")
    jwait.add_argument("--poll-s", "--interval-s", "--poll-seconds", dest="poll_s", default=1.0, type=float)
    jwait.add_argument("--max-wait-s", "--timeout-seconds", "--max-wait-seconds", dest="max_wait_s", default=300.0, type=float)
    jwait.set_defaults(func=cmd_job_wait)

    jdiag = js.add_parser("diagnose", help="collect job, session artifacts, logs, and sanitized config into a zip file")
    jdiag.add_argument("--job-id", dest="job_id", required=True)
    jdiag.add_argument("--session-id", dest="session_id")
    jdiag.add_argument("--out", required=True, help="output zip file")
    jdiag.set_defaults(func=cmd_job_diagnose)

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
    client = ApiClient(args.base_url, timeout_s=args.timeout, debug=DebugConfig(enabled=bool(args.debug), out_dir=dbg_out))
    return int(args.func(client, args))


if __name__ == "__main__":
    raise SystemExit(main())
