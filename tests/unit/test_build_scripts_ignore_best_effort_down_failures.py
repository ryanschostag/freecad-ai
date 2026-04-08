from pathlib import Path


def test_build_test_script_treats_compose_down_as_best_effort():
    repo_root = Path(__file__).resolve().parents[2]
    script = (repo_root / "build-test.sh").read_text(encoding="utf-8")

    assert 'compose_down_best_effort()' in script
    assert 'set +e' in script
    assert 'PIPESTATUS[0]' in script
    assert 'docker compose "${COMPOSE_FILES[@]}" "${PROFILE[@]}" down 2>&1 | tee "$log_file"' in script
    assert 'Warning: docker compose down failed and will be ignored because cleanup is best-effort.' in script
    assert 'compose_down_best_effort "$down_file"' in script


def test_build_cpu_script_treats_compose_down_as_best_effort():
    repo_root = Path(__file__).resolve().parents[2]
    script = (repo_root / "build-cpu.sh").read_text(encoding="utf-8")

    assert 'compose_down_best_effort()' in script
    assert 'set +e' in script
    assert 'PIPESTATUS[0]' in script
    assert 'docker compose --profile cpu down 2>&1 | tee "$log_file"' in script
    assert 'Warning: docker compose down failed and will be ignored because cleanup is best-effort.' in script
    assert 'compose_down_best_effort "$down_file"' in script
