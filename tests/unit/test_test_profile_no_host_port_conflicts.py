from pathlib import Path


def _block(text: str, start: str, end: str | None = None) -> str:
    tail = text.split(start, 1)[1]
    return tail if end is None else tail.split(end, 1)[0]


def test_test_override_clears_host_ports_for_test_profile_services():
    repo_root = Path(__file__).resolve().parents[2]
    override = (repo_root / "docker-compose.test-override.yml").read_text(encoding="utf-8")

    api_block = _block(override, "  api-test:\n", "\n  web-ui-test:\n")
    assert "    ports: []\n" in api_block

    web_ui_block = _block(override, "  web-ui-test:\n", "\n  db:\n")
    assert "    ports: []\n" in web_ui_block

    db_block = _block(override, "  db:\n", "\n  redis:\n")
    assert "    ports: []\n" in db_block

    redis_block = _block(override, "  redis:\n", "\n  llm-fake:\n")
    assert "    ports: []\n" in redis_block

    llm_fake_block = _block(
        override,
        "  llm-fake:\n",
        "\n  # Force all clients to use the same credentials",
    )
    assert "    ports: []\n" in llm_fake_block

    minio_block = _block(
        override,
        "  minio:\n",
        "\n  # Test profile services communicate over the internal Compose network only.\n",
    )
    assert "    ports: []\n" in minio_block
