from pathlib import Path


def test_cpu_profile_script_uses_cpu_down_and_checks_model_file_and_state_dir():
    repo_root = Path(__file__).resolve().parents[2]
    script = (repo_root / "build-cpu.sh").read_text(encoding="utf-8")

    assert 'model_file="./models/Qwen2.5-Coder-7B-Instruct-Q4_K_M.gguf"' in script
    assert 'state_dir_name="${model_filename//./-}"' in script
    assert 'state_dir="./models/${state_dir_name}/state"' in script
    assert 'mkdir -p "$state_dir"' in script
    assert 'if [[ ! -f "$model_file" ]]; then' in script
    assert 'docker compose --profile cpu down' in script
    assert 'docker compose --profile test down' not in script
    assert 'docker compose --profile cpu up -d' in script
