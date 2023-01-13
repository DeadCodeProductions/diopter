from abc import ABC, abstractmethod
from pathlib import Path
from subprocess import CalledProcessError
from tempfile import TemporaryDirectory
from typing import TypeAlias

from diopter.utils import run_cmd

GitRevision: TypeAlias = str


class GitRepo:
    # XXX: add debug mode where everycommand prints something?
    def __init__(self, path: Path) -> None:
        try:
            run_cmd(f"git -C {path} status")
        except Exception:
            raise ValueError(f"{path} is not a git repository")
        self.path = path

    def current_branch(self) -> GitRevision:
        return run_cmd(f"git -C {self.path} branch --show-current").stdout

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

        run_cmd(cmd)

    def remove_worktree(
        self,
        worktree_path: Path,
        force: bool = True,
    ) -> None:
        cmd = f"git -C {self.path} worktree remove {worktree_path}"
        if force:
            cmd += " --force"

        run_cmd(cmd)


def rev_parse(worktree_dir: Path, rev: str) -> GitRevision:
    return run_cmd(f"git -C {worktree_dir} rev-parse {rev}").stdout


def parse_bisect_head(worktree_dir: Path) -> GitRevision:
    return rev_parse(worktree_dir, "BISECT_HEAD")


def get_current_bisection_commit(working_dir: Path, no_checkout: bool) -> GitRevision:
    if no_checkout:
        return parse_bisect_head(working_dir)
    else:
        return rev_parse(working_dir, "HEAD")


def bisect_start(
    worktree_dir: Path,
    bad: GitRevision,
    good: GitRevision,
    no_checkout: bool = True,
) -> GitRevision:
    # TODO: make this a context manager?
    cmd = (
        f"git -C {worktree_dir} bisect start --first-parent"
        + (" --no-checkout" if no_checkout else "")
        + f" {bad} {good}"
    )
    output = run_cmd(cmd)
    print(output.stdout)
    return get_current_bisection_commit(worktree_dir, no_checkout)


def bisect_skip(
    worktree_dir: Path,
) -> None:
    cmd = f"git -C {worktree_dir} bisect skip"
    print(run_cmd(cmd).stdout)


def bisect_good(
    worktree_dir: Path,
) -> None:
    cmd = f"git -C {worktree_dir} bisect good"
    print(run_cmd(cmd).stdout)


def bisect_bad(
    worktree_dir: Path,
) -> None:
    cmd = f"git -C {worktree_dir} bisect bad"
    print(run_cmd(cmd).stdout)


def bisect_log(worktree_dir: Path) -> str:
    return run_cmd(
        f"git -C {worktree_dir} bisect log",
    ).stdout


def currently_bisecting(worktree_dir: Path) -> bool:
    return (
        not bisect_log(worktree_dir).splitlines()[-1].startswith("# first bad commit")
    )


def successful_bisection(worktree_dir: Path) -> bool:
    return bisect_log(worktree_dir).splitlines()[-1].startswith("# first bad commit")


class BisectionCallback(ABC):
    @abstractmethod
    def check(self, commit: GitRevision, repo_dir: Path) -> bool | None:
        pass


def bisect(
    repo: GitRepo,
    good: GitRevision,
    bad: GitRevision,
    callback: BisectionCallback,
    no_checkout: bool = True,
) -> GitRevision | None:
    with TemporaryDirectory() as tempdir:
        worktree_dir = Path(tempdir)
        # The context manager should be the worktree
        repo.add_worktree(worktree_dir, repo.current_branch(), no_checkout=no_checkout)
        bisect_start(worktree_dir, bad, good, no_checkout=no_checkout)
        while currently_bisecting(worktree_dir):
            commit = get_current_bisection_commit(worktree_dir, no_checkout)
            test = callback.check(commit, worktree_dir)
            print("Testing:", commit)
            try:
                if test is None:
                    print(f"Skipping {commit}")
                    bisect_skip(worktree_dir)
                    continue
                if test:
                    print(f"Good {commit}")
                    bisect_good(worktree_dir)
                else:
                    print(f"Bad {commit}")
                    bisect_bad(worktree_dir)

            except CalledProcessError as e:
                print(e.stdout.decode("utf-8"))
                return None
        if not successful_bisection(worktree_dir):
            return None
        commit = rev_parse(worktree_dir, "bisect/bad")
        repo.remove_worktree(worktree_dir)

    return commit
