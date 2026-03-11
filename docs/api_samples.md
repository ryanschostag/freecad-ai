
POST /v1/sessions
Request:
{
  "title": "Example Session"
}

Response:
{
  "session_id": "uuid",
  "status": "active"
}

POST /v1/sessions/{id}/messages
Request:
{
  "content": "Create a 10x20x5 box",
  "mode": "design"
}

Response:
{
  "job_id": "uuid"
}

GET /v1/jobs/{job_id}
Response:
{
  "status": "finished",
  "artifacts": ["model.fcstd", "model.step"]
}
