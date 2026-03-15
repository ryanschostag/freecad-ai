from pathlib import Path

import yaml


def test_llm_services_bind_mount_models_and_configure_slot_state_path():
    repo_root = Path(__file__).resolve().parents[2]
    compose = yaml.safe_load((repo_root / "docker-compose.yml").read_text(encoding="utf-8"))
    services = compose["services"]

    for service_name in ("llm", "llm-cuda"):
        service = services[service_name]
        assert './models:/models' in service['volumes']
        env = service['environment']
        assert 'LLM_MODEL_PATH=${LLM_MODEL_PATH:-/models/Qwen2.5-Coder-7B-Instruct-Q4_K_M.gguf}' in env
        command = service['command']
        assert 'MODEL_STATE_DIR_NAME="$${MODEL_FILE_NAME//./-}";' in command
        assert '--slot-save-path "/models/$${MODEL_STATE_DIR_NAME}/state"' in command


def test_docs_cover_llm_state_management_layout():
    repo_root = Path(__file__).resolve().parents[2]
    doc = (repo_root / 'docs' / 'llm-state-management.md').read_text(encoding='utf-8')

    assert '/models/Qwen2-5-Coder-7B-Instruct-Q4_K_M-gguf/state' in doc
    assert './models/Qwen2-5-Coder-7B-Instruct-Q4_K_M-gguf/state' in doc
    assert '--slot-save-path' in doc


def test_llm_services_escape_shell_variables_for_compose_interpolation():
    repo_root = Path(__file__).resolve().parents[2]
    compose_text = (repo_root / "docker-compose.yml").read_text(encoding="utf-8")

    assert "$$(basename \"$$LLM_MODEL_PATH\")" in compose_text
    assert "$${MODEL_STATE_DIR_NAME}" in compose_text
    assert "$$LLM_CHAT_TEMPLATE" in compose_text
    assert "$$LLM_THREADS" in compose_text
    assert "$$LLM_CTX_SIZE" in compose_text
