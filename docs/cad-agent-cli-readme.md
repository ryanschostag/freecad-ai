# CAD Agent CLI

The CAD Agent CLI is the host-side command-line client for the FreeCAD AI API.

Source file:
- `tools/cad_agent/cad_agent_cli.py`

## What it is good for

Use the CLI when you want to:
- verify API and LLM health from a terminal
- create, close, or inspect sessions
- send prompts without opening the browser UI
- wait on jobs and print structured JSON results
- download artifacts locally
- capture debug request/response payloads for troubleshooting

## Requirements

- Python 3.10+
- `requests`

Install local CLI dependencies:

```bash
pip install -r tools/cad_agent/requirements.txt
```

## Defaults

- base URL: `http://localhost:8080`
- override with `--base-url` or `CAD_AGENT_BASE_URL`

## Quick start

```bash
python tools/cad_agent/cad_agent_cli.py health --llm
python tools/cad_agent/cad_agent_cli.py session create --title "demo"
python tools/cad_agent/cad_agent_cli.py message send   --session <SESSION_ID>   --prompt "Create a simple box 10mm x 20mm x 5mm"   --export fcstd,step   --units mm   --tolerance-mm 0.1
python tools/cad_agent/cad_agent_cli.py job wait --job <JOB_ID> --timeout-seconds 300
```

## Useful global options

- `--base-url URL`
- `--timeout SECONDS`
- `--debug`
- `--debug-out DIR`

## Main command groups

### `health`
Checks API health, and optionally LLM health.

### `session`
Creates sessions, closes sessions, and inspects logs or artifacts.

### `message send`
Sends a user prompt to the API and enqueues a new job.

### `job`
Fetches job details or waits until a job reaches a terminal state.

### `artifact`
Retrieves artifact metadata and downloads artifacts to the local machine.

## Debugging

Use `--debug` to print request/response details to stderr.
Use `--debug-out <DIR>` to save JSON payloads for later inspection.

## Relationship to the Web UI

The CLI and Web UI both talk to the same API. Use the CLI for automation and the Web UI for interactive browsing.
