# Testing

The project is designed to run tests inside Docker using the `test` profile. That profile starts the API, worker, fake LLM, Redis, Postgres, MinIO, and the dedicated `test-runner` container so the tests exercise the intended runtime wiring.

## Recommended commands

```bash
docker compose -f docker-compose.yml -f docker-compose.test-override.yml --profile test up -d --build
docker compose -f docker-compose.yml -f docker-compose.test-override.yml --profile test run --rm test-runner
docker compose -f docker-compose.yml -f docker-compose.test-override.yml --profile test down
```

## Why tests run in Docker

- the API and worker depend on service-to-service URLs
- object storage uses MinIO credentials wired through Compose
- the fake LLM gives deterministic behavior for test runs
- the stack mounts the same persistent LLM state directory used by the application

## Test inventory

The following modules are present under `tests/` in this branch.

### Repository-level tests

- `tests/test_pyzip.py` - covers pyzip.
- `tests/test_rag_sources_config.py` - covers rag sources config.
- `tests/test_retry_limit_config.py` - covers retry limit config.

### Integration tests

- `tests/integration/test_end_to_end.py` - covers end to end.

### Unit tests

- `tests/unit/test_api_dockerfile_install_progress.py` - covers api dockerfile install progress.
- `tests/unit/test_api_job_status_precedence.py` - covers api job status precedence.
- `tests/unit/test_api_max_tokens_wiring.py` - covers api max tokens wiring.
- `tests/unit/test_api_send_message_timeout_defaults.py` - covers api send message timeout defaults.
- `tests/unit/test_build_scripts_ignore_best_effort_down_failures.py` - covers build scripts ignore best effort down failures.
- `tests/unit/test_build_start_cpu_profile_script.py` - covers build start cpu profile script.
- `tests/unit/test_cad_agent_cli.py` - covers cad agent cli.
- `tests/unit/test_cad_agent_cli_diagnostics.py` - covers cad agent cli diagnostics.
- `tests/unit/test_cad_agent_cli_diagnostics_prompt.py` - covers cad agent cli diagnostics prompt.
- `tests/unit/test_dim_time_upsert.py` - covers dim time upsert.
- `tests/unit/test_docker_compose_api_build_context.py` - covers docker compose api build context.
- `tests/unit/test_docker_compose_llm_state_mount.py` - covers docker compose llm state mount.
- `tests/unit/test_dockerfile_pip_network_resilience.py` - covers dockerfile pip network resilience.
- `tests/unit/test_dual_max_tokens_contract.py` - covers dual max tokens contract.
- `tests/unit/test_freecad_worker_dockerfile_base_image.py` - covers freecad worker dockerfile base image.
- `tests/unit/test_inline_worker_import.py` - covers inline worker import.
- `tests/unit/test_internal_job_routes.py` - covers internal job routes.
- `tests/unit/test_llm_max_tokens_optional.py` - covers llm max tokens optional.
- `tests/unit/test_llm_prompt_compaction.py` - covers llm prompt compaction.
- `tests/unit/test_no_llm_token_controls.py` - covers no llm token controls.
- `tests/unit/test_session_close_endpoint.py` - covers session close endpoint.
- `tests/unit/test_session_failure_training.py` - covers session failure training.
- `tests/unit/test_settings_inline_jobs.py` - covers settings inline jobs.
- `tests/unit/test_test_profile_inline_jobs.py` - covers profile inline jobs.
- `tests/unit/test_test_profile_runtime_dependency_installs.py` - covers profile runtime dependency installs.
- `tests/unit/test_train_llm_state.py` - covers train llm state.
- `tests/unit/test_web_ui_defaults.py` - covers web ui defaults.
- `tests/unit/test_worker_diagnostics_compat.py` - covers worker diagnostics compat.
- `tests/unit/test_worker_export_doc_recovery.py` - covers worker export doc recovery.
- `tests/unit/test_worker_freecad_command.py` - covers worker freecad command.
- `tests/unit/test_worker_job_diagnostics.py` - covers worker job diagnostics.
- `tests/unit/test_worker_job_status_callbacks.py` - covers worker job status callbacks.
- `tests/unit/test_worker_llm_max_tokens_alias.py` - covers worker llm max tokens alias.
- `tests/unit/test_worker_llm_persisted_state.py` - covers worker llm persisted state.
- `tests/unit/test_worker_llm_response_parsing.py` - covers worker llm response parsing.
- `tests/unit/test_worker_macro_semantic_validation.py` - covers worker macro semantic validation.
- `tests/unit/test_worker_model_artifact_discovery.py` - covers worker model artifact discovery.
- `tests/unit/test_worker_model_artifacts.py` - covers worker model artifacts.
- `tests/unit/test_worker_model_state.py` - covers worker model state.
- `tests/unit/test_worker_prompt_budget_runtime.py` - covers worker prompt budget runtime.
- `tests/unit/test_worker_retry_training_persistence.py` - covers worker retry training persistence.
- `tests/unit/test_worker_runner_macro_ui_compat.py` - covers worker runner macro ui compat.
- `tests/unit/test_worker_runner_recovers_from_macro_export_api_errors.py` - covers worker runner recovers from macro export api errors.
- `tests/unit/test_worker_runner_script_compat.py` - covers worker runner script compat.
- `tests/unit/test_worker_runner_script_resilience.py` - covers worker runner script resilience.
- `tests/unit/test_worker_runner_status.py` - covers worker runner status.
- `tests/unit/test_worker_timeout_budget.py` - covers worker timeout budget.

## Additional files

- `tests/Dockerfile.test-runner` builds the pytest container used in the test profile.
- `tests/pytest.ini` configures pytest behavior and markers.
- `tests/requirements.txt` contains Python dependencies for the test-runner image.

## Notes

- The test profile uses `api-test`, `freecad-worker-test`, `web-ui-test`, and `llm-fake`.
- The test environment mounts the persistent LLM state directory so training-state behaviors can be exercised in tests.
- Use the override file to keep MinIO credentials aligned across services.
