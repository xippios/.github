"""Make scripts/ importable and isolate git from the user's configuration."""

import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


@pytest.fixture(autouse=True)
def isolated_git(monkeypatch: pytest.MonkeyPatch) -> None:
    """Every git call in a test ignores the user's git setup."""
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", os.devnull)
    monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "1")
    # git's default excludes file lives under XDG_CONFIG_HOME; a user's could hide test files.
    monkeypatch.setenv("XDG_CONFIG_HOME", os.devnull)
    monkeypatch.setenv("GIT_AUTHOR_NAME", "test")
    monkeypatch.setenv("GIT_AUTHOR_EMAIL", "test@example.invalid")
    monkeypatch.setenv("GIT_COMMITTER_NAME", "test")
    monkeypatch.setenv("GIT_COMMITTER_EMAIL", "test@example.invalid")
    monkeypatch.delenv("GITHUB_OUTPUT", raising=False)
    monkeypatch.delenv("GITHUB_STEP_SUMMARY", raising=False)
    # The caller's read token (.github#62): a test that wants one sets it.
    monkeypatch.delenv("DOCUMENTS_READ_TOKEN", raising=False)


@pytest.fixture(autouse=True)
def waits(monkeypatch: pytest.MonkeyPatch) -> list[int]:
    """The seconds the review waits before it tries a request again (.github#158), recorded in
    place of the sleep, so no test sleeps; a test that reads them asks for this fixture."""
    import conventions

    seen: list[int] = []
    monkeypatch.setattr(conventions, "wait", seen.append, raising=False)
    return seen
