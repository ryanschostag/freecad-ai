# Operational Runbook

## If jobs stuck in started:

1. Check worker logs
2. Verify Redis connectivity
3. Confirm LLM /health endpoint

## If API returns 500:

1. Inspect FastAPI logs
2. Check DB migrations
3. Validate environment variables

## If Job is stuck in queued:

### Checking Redis Connectivity From the Worker

Use these steps when jobs remain in `queued` status and are not being picked up by a worker.

#### Step 1: Verify Redis and Worker Containers Are Running

docker compose --profile cpu ps

Confirm that both containers are present and Up:
- redis
- worker (FreeCAD worker)

If Redis is not running, the worker cannot dequeue jobs.

---

#### Step 2: Inspect Worker Logs for Redis Connection Errors

docker compose --profile cpu logs -n 200 worker

Look for errors such as:
- redis.exceptions.ConnectionError
- Error connecting to Redis
- No route to host
- Name or service not known

A healthy worker log should show startup messages and no repeated reconnect attempts.

---

#### Step 3: Open a Shell Inside the Worker Container

docker compose --profile cpu exec worker /bin/sh

(Use /bin/bash if available.)

All following steps are executed inside the worker container.

---

#### Step 4: Verify Redis Environment Variables

env | grep -i redis

Expected example:
REDIS_URL=redis://redis:6379/0

Confirm:
- Hostname is redis (not localhost)
- Port is 6379
- Database index matches API configuration

---

#### Step 5: Ping Redis Using redis-cli (If Available)

redis-cli -h redis -p 6379 ping

Expected output:
PONG

If this fails, Docker networking or service naming is incorrect.

---

#### Step 6: Test Redis Connectivity via Python (Authoritative)

```bash
python - <<'EOF'
import os
import redis

url = os.environ.get("REDIS_URL")
print("REDIS_URL =", url)

r = redis.from_url(url)
print("PING:", r.ping())
EOF
```

Expected output:
PING: True

If this fails, the worker cannot dequeue jobs.

---

#### Step 7: Verify the Worker Is Listening on the Correct Queue

docker compose --profile cpu logs worker | grep -i queue

Expected example:
Listening on queues: default

Ensure the API enqueues jobs to the same queue name.

Queue mismatches will cause jobs to remain queued indefinitely.

---

#### Step 8: Inspect Redis Queue Depth Directly (Advanced)

docker compose --profile cpu exec redis redis-cli

Then run:
LLEN rq:queue:default

Interpretation:
- Value increasing → jobs enqueued, worker not consuming
- Value zero → jobs not enqueued or wrong Redis DB

---

### Common Root Causes

1. REDIS_URL uses localhost instead of redis
2. API and worker use different Redis DB indexes
3. Worker listens to a different queue than the API enqueues
4. Redis restarted but worker did not
5. Worker not attached to the correct Docker network

---

### Quick Diagnostic Table

Observation: job.enqueued but no job.started  
Meaning: Worker not consuming

Observation: Redis ping fails inside worker  
Meaning: Networking or environment issue

Observation: Redis ping works but jobs stuck  
Meaning: Queue mismatch

Observation: Redis queue depth increases  
Meaning: Worker down or misconfigured

Observation: Redis queue depth is zero  
Meaning: API enqueue issue


## Profile switching:

docker compose --profile test up -d
docker compose --profile cpu up -d
