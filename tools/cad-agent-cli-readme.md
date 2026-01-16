cad_agent_cli.py — Command Line Interface

DESCRIPTION
-----------
cad_agent_cli.py is a command-line client for interacting with the FreeCAD-AI API.
It allows you to:
- Check API and LLM health
- Create and manage sessions
- Send design or repair prompts
- Poll job status
- Retrieve job results and artifacts

The CLI communicates with the API over HTTP and does not talk directly to Redis,
the worker, or the LLM.

DEFAULTS
--------
Base URL:
  http://localhost:8080

The base URL can be overridden with:
  --base-url http://host:port

All commands assume the API service is running and reachable.


GLOBAL OPTIONS
--------------
--base-url URL
    Base URL of the FreeCAD-AI API
    Default: http://localhost:8080

--timeout SECONDS
    HTTP request timeout
    Default: 30


COMMANDS
========

health
------
Check overall API health.

Usage:
  cad_agent_cli.py health

Description:
  Calls GET /health
  Returns API status and dependency summary.


health llm
----------
Check whether the LLM backend is reachable and ready.

Usage:
  cad_agent_cli.py health llm

Description:
  Calls GET /health/llm
  Useful before enqueuing jobs.
  Returns non-200 if the LLM is unavailable or still loading.


session create
--------------
Create a new session.

Usage:
  cad_agent_cli.py session create --title TITLE [--project-id ID]

Options:
  --title TEXT        Session title (required)
  --project-id TEXT  Optional project identifier

Description:
  Calls POST /v1/sessions
  Returns a session_id.

Example:
  cad_agent_cli.py session create --title "Bracket prototype"


session list
------------
List existing sessions.

Usage:
  cad_agent_cli.py session list

Description:
  Calls GET /v1/sessions
  Returns all sessions visible to the API.


session get
-----------
Fetch a single session.

Usage:
  cad_agent_cli.py session get SESSION_ID

Description:
  Calls GET /v1/sessions/{session_id}


session close
-------------
Close a session.

Usage:
  cad_agent_cli.py session close SESSION_ID

Description:
  Calls POST /v1/sessions/{session_id}/close
  Marks the session as closed; no further messages allowed.


message send
------------
Send a design or repair prompt to a session (enqueue a job).

Usage:
  cad_agent_cli.py message send SESSION_ID \
    --content TEXT \
    --mode design|repair \
    [--units mm|inch] \
    [--tolerance-mm FLOAT] \
    [--export-fcstd] \
    [--export-step] \
    [--export-stl]

Required options:
  --content TEXT
      Natural language instruction (e.g. "Create a box 10x20x5mm")

Optional options:
  --mode design|repair
      Default: design

  --units mm|inch
      Default: mm

  --tolerance-mm FLOAT
      Default: 0.1

  --export-fcstd
      Export FreeCAD .FCStd file

  --export-step
      Export STEP file

  --export-stl
      Export STL file

Description:
  Calls POST /v1/sessions/{session_id}/messages
  Enqueues a background job.
  Returns a job_id.

Notes:
  - The API will refuse this call if the LLM health check fails.
  - The job will enter the queued state immediately.


job status
----------
Check the status of a job.

Usage:
  cad_agent_cli.py job status JOB_ID

Description:
  Calls GET /v1/jobs/{job_id}

Possible job states:
  queued
  started
  finished
  failed


job wait
--------
Poll a job until it finishes or fails.

Usage:
  cad_agent_cli.py job wait JOB_ID [--interval SECONDS] [--timeout SECONDS]

Options:
  --interval SECONDS
      Polling interval
      Default: 2

  --timeout SECONDS
      Maximum wait time
      Default: 300

Description:
  Repeatedly polls GET /v1/jobs/{job_id}
  Exits when job reaches finished or failed.


job result
----------
Fetch job results and metadata.

Usage:
  cad_agent_cli.py job result JOB_ID

Description:
  Calls GET /v1/jobs/{job_id}
  Prints job metadata and artifact references.
  Artifacts are stored in S3/MinIO, not Redis.


job artifacts
-------------
List artifacts produced by a job.

Usage:
  cad_agent_cli.py job artifacts JOB_ID

Description:
  Calls GET /v1/jobs/{job_id}/artifacts
  Returns artifact names, types, and storage locations.


COMMON WORKFLOW
---------------
1. Start services
   docker compose up -d

2. Verify health
   cad_agent_cli.py health
   cad_agent_cli.py health llm

3. Create a session
   cad_agent_cli.py session create --title "Test session"

4. Send a design prompt
   cad_agent_cli.py message send <SESSION_ID> \
     --content "Create a simple box 10mm x 20mm x 5mm" \
     --export-fcstd --export-step

5. Wait for completion
   cad_agent_cli.py job wait <JOB_ID>

6. Retrieve results
   cad_agent_cli.py job result <JOB_ID>
   cad_agent_cli.py job artifacts <JOB_ID>


EXIT CODES
----------
0  Success
1  Invalid arguments
2  Network / connection error
3  API returned error response
4  Job failed or timed out


TROUBLESHOOTING
---------------
- If jobs stay in "queued" or "started":
  - Check `cad_agent_cli.py health llm`
  - Check docker compose logs llm
  - Ensure model file is mounted at /models/*.gguf

- If jobs disappear:
  - Job state and results are persisted in Postgres and S3;
    Redis TTLs should no longer affect visibility.

- If CLI cannot connect:
  - Verify API port mapping (8080)
  - Use --base-url explicitly if needed
