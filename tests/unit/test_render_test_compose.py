import importlib.util
from pathlib import Path


def _load_module():
    repo_root = Path(__file__).resolve().parents[2]
    module_path = repo_root / "tools" / "render_test_compose.py"
    spec = importlib.util.spec_from_file_location("render_test_compose", module_path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_strip_ports_for_test_services_but_keep_runtime_ports():
    module = _load_module()
    compose = """services:
  api-test:
    ports:
      - \"8081:8080\"
    environment:
      - A=1
  db:
    image: postgres:16
    ports:
      - \"5432:5432\"
  api:
    ports:
      - \"8080:8080\"
    environment:
      - B=2
  llm-fake:
    ports:
      - \"8001:8000\"
    image: fake
"""

    rendered = module.strip_ports_for_services(compose, module.SERVICES_WITHOUT_HOST_PORTS)

    assert '  api-test:\n    environment:\n      - A=1\n' in rendered
    assert '  db:\n    image: postgres:16\n' in rendered
    assert '  api:\n    ports:\n      - "8080:8080"\n' in rendered
    assert '  llm-fake:\n    image: fake\n' in rendered
    assert '"8081:8080"' not in rendered
    assert '"5432:5432"' not in rendered
    assert '"8001:8000"' not in rendered


def test_build_test_script_renders_generated_compose_without_test_ports():
    repo_root = Path(__file__).resolve().parents[2]
    script = (repo_root / "build-test.sh").read_text(encoding="utf-8")

    assert 'GENERATED_COMPOSE_FILE=.docker-compose.test.generated.yml' in script
    assert 'python3 tools/render_test_compose.py docker-compose.yml "$GENERATED_COMPOSE_FILE"' in script
    assert 'COMPOSE_FILES=(-f "$GENERATED_COMPOSE_FILE" -f docker-compose.test-override.yml)' in script
