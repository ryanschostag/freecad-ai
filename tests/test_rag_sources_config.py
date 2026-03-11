import yaml
from pathlib import Path


CONFIG_FILE = Path("rag_sources.yaml")


def load_config():
    with open(CONFIG_FILE, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def test_policy_keys_preserved():
    cfg = load_config()

    policy = cfg["policy"]

    assert "default_trust_tier" in policy
    assert "require_https" in policy
    assert "allow_domains" in policy
    assert "deny_domains" in policy


def test_freecad_source_not_removed():
    cfg = load_config()

    ids = {s["source_id"] for s in cfg["sources"]}

    assert "freecad-wiki" in ids


def test_patterns_not_removed():
    cfg = load_config()

    freecad = next(s for s in cfg["sources"] if s["source_id"] == "freecad-wiki")

    assert "include_patterns" in freecad
    assert "exclude_patterns" in freecad


def test_new_sources_present():
    cfg = load_config()

    ids = {s["source_id"] for s in cfg["sources"]}

    expected = {
        "freecad-api-docs",
        "openscad-docs",
        "mcmaster-mechanical-components",
        "misumi-configurable-components",
        "digikey-electromechanical-components",
        "keystone-battery-holders",
    }

    missing = expected - ids

    assert not missing, f"Missing sources: {missing}"


def test_https_entrypoints():
    cfg = load_config()

    for source in cfg["sources"]:
        for url in source["entrypoints"]:
            assert url.startswith("https://")

