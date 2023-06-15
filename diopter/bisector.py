from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path
from subprocess import CalledProcessError
from tempfile import TemporaryDirectory

from diopter.repository import Commit, Repo, Revision
from diopter.utils import run_cmd


def rev_parse(worktree_dir: Path, rev: str) -> Commit:
    return Commit(run_cmd(f"git -C {worktree_dir} rev-parse {rev}").stdout)


def parse_bisect_head(worktree_dir: Path) -> Commit:
    return Commit(rev_parse(worktree_dir, "BISECT_HEAD"))


def get_current_bisection_commit(working_dir: Path, no_checkout: bool) -> Commit:
    if no_checkout:
        return parse_bisect_head(working_dir)
    else:
        return rev_parse(working_dir, "HEAD")


def bisect_start(
    worktree_dir: Path,
    bad: Revision | Commit,
    good: Revision | Commit,
    no_checkout: bool = True,
) -> Commit:
    # TODO: make this a context manager?
    cmd = (
        f"git -C {worktree_dir} bisect start --first-parent"
        + (" --no-checkout" if no_checkout else "")
        + f" {bad} {good}"
    )
    output = run_cmd(cmd)
    print(output.stdout)
    return get_current_bisection_commit(worktree_dir, no_checkout)


def bisect_skip(worktree_dir: Path, commit: Commit) -> None:
    cmd = f"git -C {worktree_dir} bisect skip"
    if commit is not None:
        cmd += f" {commit}"
    print(run_cmd(cmd).stdout)


def bisect_good(worktree_dir: Path, commit: Commit) -> None:
    cmd = f"git -C {worktree_dir} bisect good"
    if commit is not None:
        cmd += f" {commit}"
    print(run_cmd(cmd).stdout)


def bisect_bad(worktree_dir: Path, commit: Commit) -> None:
    cmd = f"git -C {worktree_dir} bisect bad"
    if commit is not None:
        cmd += f" {commit}"
    print(run_cmd(cmd).stdout)


def bisect_log(worktree_dir: Path) -> str:
    return run_cmd(
        f"git -C {worktree_dir} bisect log",
    ).stdout


def latest_good_commit(worktree_dir: Path) -> Commit:
    good_prefix = "# good: ["
    good_commits = []
    for line in bisect_log(worktree_dir).splitlines():
        if line.startswith(good_prefix):
            good_commits.append(line[len(good_prefix) :].split("]", 1)[0])

    assert len(good_commits) > 0
    return Commit(good_commits[-1])


def currently_bisecting(worktree_dir: Path) -> bool:
    return (
        not bisect_log(worktree_dir).splitlines()[-1].startswith("# first bad commit")
    )


def successful_bisection(worktree_dir: Path) -> bool:
    return bisect_log(worktree_dir).splitlines()[-1].startswith("# first bad commit")


@dataclass(frozen=True)
class BisectTestResult:
    commit: Commit
    is_good: bool | None


class BisectionCallback(ABC):
    def shift_tested_commit(
        self, commit: Commit, good_commit: Commit, bad_commit: Commit
    ) -> Commit:
        """Shifts the commit to be tested.
        This can be used to steer the bisection
        """
        return commit

    @abstractmethod
    def check_impl(self, commit: Commit, repo_dir: Path) -> bool | None:
        """Checks if the commit is good or bad or broken.

        Subclasses should implement this method.
        """
        pass

    def check(
        self, commit: Commit, good_commit: Commit, bad_commit: Commit, repo_dir: Path
    ) -> BisectTestResult:
        """Checks if the commit is good or bad or broken."""
        commit = self.shift_tested_commit(commit, good_commit, bad_commit)
        result = self.check_impl(commit, repo_dir)
        if result is None:
            return BisectTestResult(commit, None)
        return BisectTestResult(commit, result is False)


def bisect(
    repo: Repo,
    callback: BisectionCallback,
    no_checkout: bool = True,
    *,
    good: Revision | Commit,
    bad: Revision | Commit,
) -> Commit | None:
    # TODO: add support for specifying which paths in the repo to look at
    with TemporaryDirectory() as tempdir:
        worktree_dir = Path(tempdir)
        # The context manager should be the worktree
        repo.add_worktree(worktree_dir, repo.current_branch(), no_checkout=no_checkout)
        bisect_start(worktree_dir, bad, good, no_checkout=no_checkout)
        while currently_bisecting(worktree_dir):
            commit = get_current_bisection_commit(worktree_dir, no_checkout)
            test_result = callback.check(
                commit,
                latest_good_commit(worktree_dir),
                rev_parse(worktree_dir, "bisect/bad"),
                worktree_dir,
            )
            print("Testing:", commit)
            if test_result.commit != commit:
                print(f"Bisection commit shifted: {commit} -> {test_result.commit}")
            try:
                if test_result.is_good is None:
                    print(f"Skipping {commit}")
                    bisect_skip(worktree_dir, test_result.commit)
                    continue
                if test_result.is_good:
                    print(f"Good {commit}")
                    bisect_good(worktree_dir, test_result.commit)
                else:
                    print(f"Bad {commit}")
                    bisect_bad(worktree_dir, test_result.commit)

            except CalledProcessError as e:
                print(e.stdout.decode("utf-8"))
                return None
        if not successful_bisection(worktree_dir):
            return None
        commit = rev_parse(worktree_dir, "bisect/bad")
        repo.remove_worktree(worktree_dir)

    return commit
