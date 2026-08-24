"""M1 scaffold regression guards (REG-1: SCAFF-1, SCAFF-2)."""

import tomllib
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]


def test_pyproject_toml_parses_and_declares_documented_deps():
    with open(ROOT / "ingest" / "pyproject.toml", "rb") as fh:
        pyproject = tomllib.load(fh)

    deps = pyproject["project"]["dependencies"]
    assert "chromadb>=0.5.0" in deps
    assert any(dep.startswith("openai") for dep in deps)
    assert any(dep.startswith("google-genai") for dep in deps)
    assert any(dep.startswith("python-dotenv") for dep in deps)
    assert any(
        dep.startswith("pytest")
        for dep in pyproject["project"]["optional-dependencies"]["dev"]
    )


def test_docker_compose_is_valid_yaml_with_db_service():
    with open(ROOT / "docker-compose.yml", encoding="utf-8") as fh:
        compose = yaml.safe_load(fh)

    db = compose["services"]["db"]
    assert db["image"] == "pgvector/pgvector:pg15"
    assert "5432:5432" in db["ports"]