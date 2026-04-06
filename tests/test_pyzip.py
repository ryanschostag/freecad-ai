import importlib.util
from pathlib import Path
from zipfile import ZipFile


REPO_ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = REPO_ROOT / 'tools' / 'collect_logs.py'
SPEC = importlib.util.spec_from_file_location('collect_logs_tool', MODULE_PATH)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC is not None and SPEC.loader is not None
SPEC.loader.exec_module(MODULE)


def test_create_log_archive_uses_python_zip_and_removes_logs(tmp_path: Path):
    first_log = tmp_path / 'build.log'
    second_log = tmp_path / 'run.log'
    first_log.write_text('build output', encoding='utf-8')
    second_log.write_text('run output', encoding='utf-8')

    archive_path = MODULE.create_log_archive(tmp_path)

    assert archive_path == tmp_path / 'build.zip'
    assert archive_path.exists()
    assert not first_log.exists()
    assert not second_log.exists()

    with ZipFile(archive_path) as archive:
        assert sorted(archive.namelist()) == ['build.log', 'run.log']
        assert archive.read('build.log').decode('utf-8') == 'build output'
        assert archive.read('run.log').decode('utf-8') == 'run output'


def test_collect_logs_shell_script_delegates_to_python_tool():
    script = (REPO_ROOT / 'collect-logs.sh').read_text(encoding='utf-8')

    assert 'zip -v9 build.zip *.log' not in script
    assert 'python tools/collect_logs.py' in script
