from abc import ABC, abstractmethod
from pathlib import Path
from subprocess import DEVNULL
from tempfile import TemporaryDirectory
from typing import Optional, TypeAlias

from diopter.utils import run_cmd

GitRevision: TypeAlias = str


class GitRepo:
    # XXX: add debug mode where everycommand prints something?
    def __init__(self, path: Path) -> None:
        try:
            run_cmd("git -C {path} status")
        except Exception:
            raise ValueError(f"{path} is not a git repository")
        self.path = path

    def current_branch(self) -> GitRevision:
        return run_cmd(
            f"git -C {self.path} branch --show-current",
            capture_output=True,
            check=True,
        ).stdout

    def add_worktree(
        self,
        target_path: Path,
        branch: GitRevision,
        force: bool = True,
        no_checkout: bool = True,
    ) -> None:
        # XXX: this requires manual cleanup
        # TODO: make this a context manager

        cmd = f"git -C {self.path} worktree add {target_path} {branch}"
        if force:
            cmd += " --force"
        if no_checkout:
            cmd += " --no-checkout"

        run_cmd(cmd, check=True, stdout=DEVNULL, stderr=DEVNULL)

    def remove_worktree(
        self,
        worktree_path: Path,
        force: bool = True,
    ) -> None:
        cmd = f"git -C {self.path} worktree remove {worktree_path}"
        if force:
            cmd += " --force"

        run_cmd(cmd, check=True, stdout=DEVNULL, stderr=DEVNULL)


def rev_parse(worktree_dir: Path, rev: str) -> GitRevision:
    return run_cmd(
        f"git -C {worktree_dir} rev-parse {rev}",
        check=True,
        capture_output=True,
    ).stdout


def parse_bisect_head(worktree_dir: Path) -> GitRevision:
    return rev_parse(worktree_dir, "BISECT_HEAD")


def bisect_start(
    worktree_dir: Path,
    bad: GitRevision,
    good: GitRevision,
    no_checkout: bool = True,
) -> GitRevision:
    # TODO: make this a context manager?
    cmd = (
        f"git -C {worktree_dir} bisect start" + " --no-checkout"
        if no_checkout
        else "" + f" {bad} {good}"
    )
    run_cmd(cmd, check=True)
    return parse_bisect_head(worktree_dir)


def bisect_skip(
    worktree_dir: Path,
) -> None:
    cmd = f"git -C {worktree_dir} bisect skip"
    run_cmd(cmd, check=True)


def bisect_good(
    worktree_dir: Path,
) -> None:
    cmd = f"git -C {worktree_dir} bisect good"
    run_cmd(cmd, check=True)


def bisect_bad(
    worktree_dir: Path,
) -> None:
    cmd = f"git -C {worktree_dir} bisect bad"
    run_cmd(cmd, check=True)


def currently_bisecting(worktree_dir: Path) -> bool:
    try:
        run_cmd(
            f"git -C {worktree_dir} bisect log",
            check=False,
            capture_output=True,
        )
    except Exception:
        return False
    return True


class BisectionCallback(ABC):
    @abstractmethod
    def check(self, commit: GitRevision) -> Optional[bool]:
        pass


def bisect(
    repo: GitRepo, good: GitRevision, bad: GitRevision, callback: BisectionCallback
) -> GitRevision | None:
    with TemporaryDirectory() as tempdir:
        worktree_dir = Path(tempdir)
        # The context manager should be the worktree
        repo.add_worktree(worktree_dir, repo.current_branch())
        while currently_bisecting(worktree_dir):
            commit = parse_bisect_head(worktree_dir)
            test = callback.check(commit)
            if test is None:
                bisect_skip(worktree_dir)
                continue
            if test:
                bisect_good(worktree_dir)
            else:
                bisect_bad(worktree_dir)
        # TODO: check bisection was successful?
        bisection_success = True
        if not bisection_success:
            return None
        commit = rev_parse(worktree_dir, "bisect/bad")
        repo.remove_worktree(worktree_dir)

    return commit
