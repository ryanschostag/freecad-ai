
LLM Timeout:
- Cause: model overload or long context
- Effect: job marked failed
- Mitigation: increase timeout or reduce ctx-size

Worker Crash:
- Cause: FreeCAD segfault or memory
- Effect: job stuck in started
- Mitigation: worker restart + job requeue

Redis Eviction:
- Cause: TTL expiry
- Effect: job metadata lost
- Mitigation: DB persistence
