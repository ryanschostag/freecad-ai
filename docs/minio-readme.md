# MinIO and Artifact Storage

FreeCAD AI uses MinIO as its local S3-compatible object store. The API and worker write artifacts to the `cad-artifacts` bucket, and the browser-facing MinIO Console can be used to inspect stored objects during development.

## Default local endpoints

- S3 API: `http://localhost:9000`
- MinIO Console: `http://localhost:9001`

## Credentials

Credentials come from `.env`:

```env
MINIO_ROOT_USER=minioadmin
MINIO_ROOT_PASSWORD=minioadmin
S3_ACCESS_KEY=minioadmin
S3_SECRET_KEY=minioadmin
```

The Compose stack passes the S3 credentials to the API, worker, and test-runner containers.

## What gets stored

Typical objects include:
- generated FreeCAD macros
- runner diagnostics and status payloads
- exported model files such as `.FCStd`, `.step`, and `.stl`
- job reports and training-related artifacts

## Bucket initialization

The `minio-init` container creates the `cad-artifacts` bucket at stack startup using the MinIO client image.

## How downloads work

Users normally do not access raw object keys directly. Instead:
1. the API lists artifacts for a session
2. the client asks the API for a specific artifact record
3. the API returns a presigned URL
4. the browser or CLI downloads the object using that presigned URL

## Troubleshooting

### `InvalidAccessKeyId`
Usually means the container environment is not using the same credentials as MinIO. Check `.env`, `docker-compose.test-override.yml`, and any host AWS-related environment variables.

### Artifacts are missing from the console
Confirm that the job finished, the worker uploaded the artifact, and the object key appears in the API artifact record.

### The console loads but login fails
Use `MINIO_ROOT_USER` and `MINIO_ROOT_PASSWORD`, not necessarily any cloud-provider credentials from your shell.
