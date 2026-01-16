# CAD Agent CLI

`cad_agent_cli.py` is a small command-line tool for calling the FreeCAD-AI API.

It targets the API container (FastAPI) exposed on `http://localhost:8080` by default.

## Requirements

- Python 3.10+
- `requests` (already included in the API/worker images; install locally if running on the host)

## Quick start

```bash
# Check overall API health + downstream dependencies (LLM/Redis/DB/MinIO)
python tools/cad_agent/cad_agent_cli.py health

# Create a session
python tools/cad_agent/cad_agent_cli.py session create --title "itest"

# Send a design prompt (enqueue a job)
python tools/cad_agent/cad_agent_cli.py message send \
  --session <SESSION_ID> \
  --prompt "Create a simple box 10mm x 20mm x 5mm" \
  --export fcstd,step \
  --units mm \
  --tolerance-mm 0.1

# Follow the job until completion
python tools/cad_agent/cad_agent_cli.py job wait --job <JOB_ID> --timeout-seconds 300
```

## Commands

### `health`

Runs a health check against the API and prints a summary. Includes a separate LLM readiness check.

```bash
python tools/cad_agent/cad_agent_cli.py health
python tools/cad_agent/cad_agent_cli.py health --base-url http://localhost:8080
```

### `session create`

Create a new session.

```bash
python tools/cad_agent/cad_agent_cli.py session create --title "my session"
```

### `message send`

Enqueue a message (design request) for a given session.

```bash
python tools/cad_agent/cad_agent_cli.py message send --session <SESSION_ID> --prompt "..."

# Control exports (comma-separated list: fcstd,step,stl)
python tools/cad_agent/cad_agent_cli.py message send --session <SESSION_ID> --prompt "..." --export fcstd,step
```

Flags:
- `--mode` (`design` or `repair`) (default: `design`)
- `--units` (default: `mm`)
- `--tolerance-mm` (default: `0.1`)
- `--export` (default: `fcstd,step`)

### `job get`

Fetch the latest job record from the API.

```bash
python tools/cad_agent/cad_agent_cli.py job get --job <JOB_ID>
```

### `job wait`

Poll a job until it reaches a terminal state.

```bash
python tools/cad_agent/cad_agent_cli.py job wait --job <JOB_ID> --timeout-seconds 300 --poll-seconds 1
```

### Debugging: `--debug` / `--debug-dir`

Add `--debug` to print request/response details for each HTTP call.

Use `--debug-dir` to also write JSON snapshots to disk (one file per request).

```bash
python tools/cad_agent/cad_agent_cli.py --debug --debug-dir ./.cad_agent_debug health
python tools/cad_agent/cad_agent_cli.py --debug --debug-dir ./.cad_agent_debug message send --session <SID> --prompt "..."
```

The debug directory will contain:
- `NNN_request.json` (method/url/headers/payload)
- `NNN_response.json` (status/headers/body)
