from pathlib import Path


def test_build_cpu_detects_exited_llm_container_before_waiting_full_timeout():
    repo_root = Path(__file__).resolve().parents[2]
    script = (repo_root / "build-cpu.sh").read_text(encoding="utf-8")

    assert 'check_service_running() {' in script
    assert 'docker inspect -f {{.State.Status}}' in script
    assert 'Service $service is $state; aborting readiness wait early.' in script
    assert script.count('check_service_running llm || return 1') >= 2
