# Web UI

The Web UI is the browser front end for FreeCAD AI. It is served by the `services/web-ui` container and reverse-proxies API traffic to the backend service so you can work from a browser without dealing with CORS setup.

## Default URLs

CPU or GPU profile:
- Web UI: `http://localhost:3000`
- API docs: `http://localhost:8080/docs`
- MinIO Console: `http://localhost:9001`

Test profile:
- Web UI: `http://localhost:3001`
- API docs: `http://localhost:8081/docs`

## What the UI can do

- create a new session
- continue an existing session by session id
- fork a session
- send a prompt to create a background design job
- choose export formats (`fcstd`, `step`, `stl`)
- track a job id until it reaches `finished` or `failed`
- fetch session logs
- list session artifacts
- request a presigned artifact download link

## UI workflow

### Create a session
1. Open the application in a browser.
2. Click **Create new session**.
3. The returned session id becomes the active session.

### Continue an existing session
1. Paste a session id into **Session ID**.
2. Click **Load session logs**.
3. The page validates the session by fetching logs and reuses that session as the active one.

### Fork a session
1. Enter or load an existing session id.
2. Click **Fork session**.
3. A child session is created and becomes the active session in the page.

### Send a prompt
1. Enter the prompt text.
2. Select units, tolerance, timeout, and export formats.
3. Click **Send prompt**.
4. The UI stores the returned job id and automatically begins polling.

### Track a job
The **Job Tracker** panel polls the API about every 1.5 seconds and stops automatically when the job reaches `finished` or `failed`.

### Fetch logs and artifacts
- **Fetch logs** reads `/v1/sessions/{session_id}/logs`
- **List artifacts** reads `/v1/sessions/{session_id}/artifacts`
- **Get link** requests a presigned URL for a downloadable artifact

## Implementation notes

- Static files live under `services/web-ui/static/`.
- The FastAPI app in `services/web-ui/app/main.py` proxies browser requests under `/api/*` to the API container.
- The container uses `API_BASE_URL` and `WEBUI_API_TIMEOUT_S` to control proxy behavior.

## When to use the Web UI vs the CLI

Use the Web UI when you want:
- a visual session-oriented workflow
- quick access to logs and artifacts
- easy job tracking without copying command output around

Use the CLI when you want:
- automation from shell scripts
- easier debug-output capture
- command chaining in development or CI
