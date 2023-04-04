from __future__ import annotations

from pathlib import Path


class GitRepository:
    def __init__(self, path: Path) -> None:
        raise NotImplementedError

    def get_workspace(self, revision: GitRevision) -> GitWorkspace:
        raise NotImplementedError

    def get_revision(self, revision: str) -> GitRevision:
        raise NotImplementedError


class GitWorkspace:
    def path(self) -> Path:
        raise NotImplementedError


class GitRevision:
    def __str__(self) -> str:
        raise NotImplementedError
