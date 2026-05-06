"""Shared pytest fixtures for kaos-ui."""

from __future__ import annotations

from pathlib import Path

import pytest


@pytest.fixture
def tmp_project_root(tmp_path: Path) -> Path:
    """A clean temp directory suitable for scaffold tests."""
    project = tmp_path / "scaffold-target"
    project.mkdir()
    return project
