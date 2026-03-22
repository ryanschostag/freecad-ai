from pathlib import Path


def test_build_test_script_uses_dedicated_compose_project_name():
    repo_root = Path(__file__).resolve().parents[2]
    script = (repo_root / "build-test.sh").read_text(encoding="utf-8")

    assert 'PROJECT_NAME=${COMPOSE_PROJECT_NAME:-freecad-ai-test}' in script
    assert 'docker compose -p "$PROJECT_NAME" "${COMPOSE_FILES[@]}" "${PROFILE[@]}" down' in script
    assert 'docker compose -p "$PROJECT_NAME" "${COMPOSE_FILES[@]}" "${PROFILE[@]}" build --no-cache' in script
    assert 'docker compose -p "$PROJECT_NAME" "${COMPOSE_FILES[@]}" "${PROFILE[@]}" up -d' in script
    assert 'docker compose -p "$PROJECT_NAME" "${COMPOSE_FILES[@]}" "${PROFILE[@]}" run --rm test-runner' in script
