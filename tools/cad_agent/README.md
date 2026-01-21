# CAD Agent CLI

`tools/cad_agent/cad_agent_cli.py` is a small command-line tool for calling the FreeCAD-AI API
(from your host machine) while the Docker **cpu** / **gpu** / **test** profile is running.

By default it targets:

- Base URL: `http://localhost:8080`
- Override with: `--base-url ...` or `CAD_AGENT_BASE_URL=...`

---

## Requirements

- Python 3.10+
- `requests` installed in your local `.venv`
- For example, you can run `pip install -r tools/cad_agent/requirements.txt`

---

## Quick start

```bash
# 1) Check overall API health (+ optional LLM check)
python tools/cad_agent/cad_agent_cli.py health --llm

# 2) Create a session
python tools/cad_agent/cad_agent_cli.py session create --title "itest"

# 3) Send a design prompt (enqueue a background job)
python tools/cad_agent/cad_agent_cli.py message send \
  --session <SESSION_ID> \
  --prompt "Create a simple box 10mm x 20mm x 5mm" \
  --export fcstd,step \
  --units mm \
  --tolerance-mm 0.1

# 4) Wait for the job to finish and print the final job record
python tools/cad_agent/cad_agent_cli.py job wait --job <JOB_ID> --timeout-seconds 300
```

---

## Global options

These apply to all commands:

- `--base-url URL`  
  API base URL (default: `http://localhost:8080`).  
  Env var alternative: `CAD_AGENT_BASE_URL`.

- `--timeout SECONDS`  
  HTTP request timeout (default: `30`).  
  Env var alternative: `CAD_AGENT_TIMEOUT_S`.

- `--debug`  
  Print request/response details to **stderr** (status code, latency, JSON bodies).

- `--debug-out DIR`  
  Write request/response JSON files into `DIR` (useful for bug reports).  
  Env var alternative: `CAD_AGENT_DEBUG_OUT`.

Example:

```bash
python tools/cad_agent/cad_agent_cli.py --debug --debug-out ./.cad_agent_debug health --llm
```

---

## Commands

### `health`

Checks API health.

```bash
python tools/cad_agent/cad_agent_cli.py health
python tools/cad_agent/cad_agent_cli.py health --llm
```

**What it calls**
- `GET /health`
- If `--llm` is provided: also `GET /health/llm`

**Output (stdout)**
JSON from the API. Typical fields vary by implementation, but you should expect a 200 on success.

**Exit code**
- `0` success
- `1` any non-200 response

---

### `session create`

Create a new session.

```bash
python tools/cad_agent/cad_agent_cli.py session create --title "my session"
python tools/cad_agent/cad_agent_cli.py session create --title "my session" --project-id demo
```

**What it calls**
- `POST /v1/sessions`

**Request fields**
- `title` *(string, required)*
- `project_id` *(string, optional)*

**Output (stdout)**
Session JSON, e.g.:

```json
{
  "session_id": "...",
  "title": "itest",
  "status": "active",
  "created_at": "...",
  "closed_at": null,
  "parent_session_id": null,
  "project_id": null
}
```

**Exit code**
- `0` if the API returns `201`
- `1` otherwise

---

### `session close`

Close an existing session.

```bash
python tools/cad_agent/cad_agent_cli.py session close <SESSION_ID>
```

**What it calls**
- `POST /v1/sessions/{session_id}/close`

**Exit code**
- `0` if HTTP 200 or 204
- `1` otherwise

---

### `message send`

Enqueue a design/repair request for a session (this creates a background job).

```bash
python tools/cad_agent/cad_agent_cli.py message send \
  --session <SESSION_ID> \
  --prompt "Create a simple box 10mm x 20mm x 5mm" \
  --mode design \
  --export fcstd,step \
  --units mm \
  --tolerance-mm 0.1
```

**What it calls**
- `POST /v1/sessions/{session_id}/messages`

#### Options

- `--session SESSION_ID` *(required)*  
  Which session to attach this message/job to.

- `--prompt TEXT` *(required)*  
  Your design request.

- `--mode design|repair` *(default: `design`)*  
  - `design`: generate a new macro from scratch  
  - `repair`: attempt to fix an existing macro based on validation issues (used internally during retries)

- `--units mm|in|...` *(default: `mm`)*  
  Units are passed through to the worker/LLM prompt and may affect validation rules.

- `--tolerance-mm FLOAT` *(default: `0.1`)*  
  Numeric tolerance in **millimeters** used by the worker/validator and included in the LLM prompt.
  It is intended to express acceptable deviation for dimensional checks and validation rules.

- `--export LIST` *(default: `fcstd,step`)*  
  Comma-separated list of export formats. Accepted values:
  - `fcstd` – FreeCAD document
  - `step` – STEP export
  - `stl` – STL export

  The CLI converts this list into an API payload like:
  ```json
  {"export": {"fcstd": true, "step": true, "stl": false}}
  ```
  Note: exports may be generated only if the worker successfully produces/validates geometry
  and the worker implementation supports the requested exports.

- `--timeout-seconds INT` *(optional)*  
  Job runtime timeout passed to the worker (separate from CLI HTTP timeout).

- `--max-repair-iterations INT` *(optional)*  
  Maximum number of repair attempts (generate → validate → repair loop) the worker should try.

#### Output (stdout)

On success (HTTP 202), you’ll typically receive:

```json
{
  "session_id": "...",
  "user_message_id": "...",
  "job_id": "...",
  "macro_artifact_id": "..."
}
```

Meanings:
- `job_id`: identifier you poll/wait on
- `user_message_id`: your message record in the session
- `macro_artifact_id`: artifact id placeholder for the generated macro (final artifacts are attached to the job record)

**Exit code**
- `0` if HTTP 202
- `1` otherwise

---

### `job get`

Fetch the current job record.

```bash
python tools/cad_agent/cad_agent_cli.py job get <JOB_ID>
```

**What it calls**
- `GET /v1/jobs/{job_id}`

**Output (stdout)**
Job JSON. Important fields include:
- `status`: `queued` | `started` | `finished` | `failed`
- `error`: error payload if failed
- `result`: final result object when finished (includes artifacts + validation)

**Exit code**
- `0` if HTTP 200
- `1` otherwise

---

### `job wait`

Poll until the job reaches a terminal state.

```bash
python tools/cad_agent/cad_agent_cli.py job wait --job <JOB_ID> --timeout-seconds 300 --poll-seconds 1
```

Accepted job id forms:
- `job wait <JOB_ID>`
- `job wait --job <JOB_ID>`

#### Options

- `--poll-s / --poll-seconds FLOAT` *(default: `1.0`)*
- `--max-wait-s / --timeout-seconds FLOAT` *(default: `300.0`)*

#### Output (stdout)

Final job record (same as `job get`).

If the job finishes successfully, you’ll see:

- `status: "finished"`
- `result.artifacts`: list of produced artifacts
- `result.passed`: whether validation passed

#### Exit codes

- `0` job finished
- `2` job failed
- `3` timed out waiting

---

## Artifacts: where they are stored and how to retrieve them

In job results, artifacts are shown like:

```json
{
  "kind": "freecad_macro_py",
  "object_key": "sessions/<session_id>/macros/<message_id>.gen0.py",
  "sha256": "...",
  "bytes": 1234
}
```

### Where the bytes actually live

Artifacts are stored in your configured object storage:
- In Docker/dev/test, this is typically **MinIO** (S3-compatible)
- In production, it can be real S3

The `object_key` is the key inside the bucket.

### How to list artifacts for a session

Call:

- `GET /v1/sessions/{session_id}/artifacts`

This returns artifact metadata + `artifact_id`.

### How to download an artifact (recommended)

Call:

- `GET /v1/artifacts/{artifact_id}`

The API returns:
- `download_url` (a presigned URL)
- `expires_at`

Then download with your browser or `curl`:

```bash
curl -L "<download_url>" -o out.fcstd
```

### Alternative: MinIO UI

If the `cpu` profile includes MinIO, you can also browse artifacts via MinIO Console
(typically exposed at `http://localhost:9001`) and download objects directly.
Credentials come from your project `.env`:
- `MINIO_ROOT_USER`
- `MINIO_ROOT_PASSWORD`

Bucket name is controlled by the API settings (commonly `cad-artifacts`).

---

## Understanding the `job wait` JSON result

Key parts of the returned JSON:

- `status`:
  - `queued`: waiting in Redis queue
  - `started`: worker has begun
  - `finished`: terminal success state (may still have `passed=false` if validation failed)
  - `failed`: terminal failure state

- `result.passed`:
  - `true`: validation passed and exports (if requested) are expected to be usable
  - `false`: validation did not pass; you may see repair artifacts + validation reports

- `result.iterations`:
  number of generate/repair cycles attempted

- `result.artifacts[]`:
  all artifacts produced during the run (macro versions, validation reports, exports if supported)

- `result.issues[]`:
  validator issues (if any). Empty with `passed=false` can happen if a validator step produced
  a report but did not populate issues (depends on validator implementation).

---

## Notes / common gotchas

- If `job wait` consistently times out:
  - check worker logs
  - check Redis queue connectivity
  - confirm the worker container is running and subscribed to the correct queue

- If `passed=false`:
  - download `validation_report_json` artifacts to see why
  - inspect the `freecad_macro_py` artifacts to see what was generated

---

## Debug bundle helper

The CLI also includes a helper to generate a debug bundle:

```bash
python tools/cad_agent/cad_agent_cli.py --debug --debug-out ./.cad_agent_debug debug bundle \
  --title "debug" \
  --prompt "Create a simple box 10mm x 20mm x 5mm" \
  --export fcstd,step \
  --units mm \
  --tolerance-mm 0.1
```

This will:
1) run health checks
2) create a session
3) send a message
4) wait for the job
…and write request/response JSON into the debug directory.
