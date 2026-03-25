let pollTimer = null;

function $(id) { return document.getElementById(id); }

function setOutput(obj) {
  $("output").textContent = typeof obj === "string" ? obj : JSON.stringify(obj, null, 2);
}

function setJobOutput(obj) {
  $("jobOutput").textContent = typeof obj === "string" ? obj : JSON.stringify(obj, null, 2);
}

function setLogsOutput(obj) {
  $("logsOutput").textContent = typeof obj === "string" ? obj : JSON.stringify(obj, null, 2);
}

function setActiveSession(id) {
  $("activeSession").textContent = id || "—";
  if (id) $("sessionId").value = id;
}

async function apiFetch(path, opts = {}) {
  const res = await fetch(`/api/${path.replace(/^\/+/, "")}`, {
    headers: { "Content-Type": "application/json", ...(opts.headers || {}) },
    ...opts,
  });
  const text = await res.text();
  let data = null;
  try { data = text ? JSON.parse(text) : null; } catch { data = text; }
  if (!res.ok) {
    throw new Error(`HTTP ${res.status}: ${typeof data === "string" ? data : JSON.stringify(data)}`);
  }
  return data;
}

async function createSession() {
  const title = $("sessionTitle").value.trim() || null;
  const data = await apiFetch("v1/sessions", {
    method: "POST",
    body: JSON.stringify({ title }),
  });
  setActiveSession(data.session_id);
  setOutput({ created_session: data });
}

async function forkSession() {
  const sid = $("sessionId").value.trim();
  if (!sid) throw new Error("Provide a session id to fork.");
  const data = await apiFetch(`v1/sessions/${sid}/fork`, { method: "POST" });
  setActiveSession(data.session_id);
  setOutput({ forked_session: data });
}

async function fetchLogs() {
  const sid = $("sessionId").value.trim();
  if (!sid) throw new Error("Provide a session id.");
  const tail = parseInt($("logsTail").value || "200", 10);
  const since = $("logsSince").value.trim();
  const qs = new URLSearchParams();
  if (since) qs.set("since", since);
  const data = await apiFetch(`v1/sessions/${sid}/logs${qs.toString() ? "?" + qs.toString() : ""}`);
  const events = (data.events || []).slice(-tail);
  setLogsOutput({ session_id: sid, tail, events });
}

async function fetchArtifacts() {
  const sid = $("sessionId").value.trim();
  if (!sid) throw new Error("Provide a session id.");
  const data = await apiFetch(`v1/sessions/${sid}/artifacts`);
  const list = data.artifacts || [];
  const root = $("artifactsOutput");
  root.innerHTML = "";
  if (!list.length) {
    root.textContent = "No artifacts yet.";
    return;
  }
  const table = document.createElement("table");
  table.style.width = "100%";
  table.style.borderCollapse = "collapse";
  table.innerHTML = `<thead>
    <tr>
      <th style="text-align:left;padding:6px;border-bottom:1px solid #243244;">kind</th>
      <th style="text-align:left;padding:6px;border-bottom:1px solid #243244;">object_key</th>
      <th style="text-align:left;padding:6px;border-bottom:1px solid #243244;">bytes</th>
      <th style="text-align:left;padding:6px;border-bottom:1px solid #243244;">download</th>
    </tr>
  </thead>`;
  const tbody = document.createElement("tbody");
  for (const a of list) {
    const tr = document.createElement("tr");
    tr.innerHTML = `
      <td style="padding:6px;border-bottom:1px solid #182235;">${a.kind}</td>
      <td style="padding:6px;border-bottom:1px solid #182235;">${a.object_key || ""}</td>
      <td style="padding:6px;border-bottom:1px solid #182235;">${a.bytes || ""}</td>
      <td style="padding:6px;border-bottom:1px solid #182235;"><button class="secondary" data-artifact="${a.artifact_id}">Get link</button></td>
    `;
    tbody.appendChild(tr);
  }
  table.appendChild(tbody);
  root.appendChild(table);

  root.querySelectorAll("button[data-artifact]").forEach(btn => {
    btn.addEventListener("click", async () => {
      const artifactId = btn.getAttribute("data-artifact");
      btn.disabled = true;
      try {
        const r = await apiFetch(`v1/artifacts/${artifactId}`);
        // API returns presigned_url
        const url = r.presigned_url || r.url || null;
        if (url) {
          window.open(url, "_blank");
        } else {
          alert("No presigned_url returned for artifact.");
        }
      } catch (e) {
        alert(e.message);
      } finally {
        btn.disabled = false;
      }
    });
  });
}

async function sendPrompt() {
  const sid = $("sessionId").value.trim();
  if (!sid) throw new Error("Create or provide a session id first.");

  const prompt = $("prompt").value.trim();
  if (!prompt) throw new Error("Prompt is empty.");

  const exportObj = {
    fcstd: $("expFcstd").checked,
    step: $("expStep").checked,
    stl: $("expStl").checked,
  };

  const payload = {
    content: prompt,
    export: exportObj,
    units: $("units").value,
    tolerance_mm: parseFloat($("tolerance").value || "0.1"),
    timeout_seconds: parseInt($("timeoutSeconds").value || "900", 10),
    max_tokens: parseInt($("maxTokens").value || "2400", 10),
  };

  const data = await apiFetch(`v1/sessions/${sid}/messages`, {
    method: "POST",
    body: JSON.stringify(payload),
  });

  $("jobId").value = data.job_id;
  setJobOutput({ enqueued: data });
  setOutput({ message_sent: data });

  // auto start polling
  await trackJob(true);
}

async function getJob(jobId) {
  return await apiFetch(`v1/jobs/${jobId}`);
}

async function trackJob(auto = false) {
  const jobId = $("jobId").value.trim();
  if (!jobId) throw new Error("Provide a job id to track.");

  if (pollTimer) clearInterval(pollTimer);

  let consecutiveFailures = 0;

  const poll = async () => {
    try {
      const data = await getJob(jobId);
      consecutiveFailures = 0;
      setJobOutput(data);

      // if finished/failed, stop
      if (data.status === "finished" || data.status === "failed") {
        clearInterval(pollTimer);
        pollTimer = null;
      }
    } catch (e) {
      consecutiveFailures += 1;
      setJobOutput({ error: e.message, consecutive_poll_failures: consecutiveFailures });
      if (consecutiveFailures >= 5) {
        clearInterval(pollTimer);
        pollTimer = null;
      }
    }
  };

  await poll();
  pollTimer = setInterval(poll, 1500);

  if (!auto) setOutput({ tracking_job: jobId });
}

function stopPolling() {
  if (pollTimer) clearInterval(pollTimer);
  pollTimer = null;
  setOutput("Stopped polling.");
}

async function loadSessionLogs() {
  // Just fetch logs to verify session exists & populate outputs
  await fetchLogs();
  setActiveSession($("sessionId").value.trim());
}

function wire() {
  $("btnCreate").addEventListener("click", () => createSession().catch(e => setOutput(e.message)));
  $("btnFork").addEventListener("click", () => forkSession().catch(e => setOutput(e.message)));
  $("btnLoad").addEventListener("click", () => loadSessionLogs().catch(e => setOutput(e.message)));

  $("btnSend").addEventListener("click", () => sendPrompt().catch(e => setOutput(e.message)));
  $("btnTrackJob").addEventListener("click", () => trackJob(false).catch(e => setOutput(e.message)));
  $("btnStopPolling").addEventListener("click", () => stopPolling());
  $("btnFetchLogs").addEventListener("click", () => fetchLogs().catch(e => setLogsOutput(e.message)));
  $("btnFetchArtifacts").addEventListener("click", () => fetchArtifacts().catch(e => setOutput(e.message)));
}

wire();
