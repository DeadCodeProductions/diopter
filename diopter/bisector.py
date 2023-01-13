from pathlib import Path
from subprocess import run, DEVNULL
from typing import TypeAlias
from tempfile import TemporaryDirectory


GitRevision: TypeAlias = str


class GitRepo:
    # XXX: add debug mode where everycommand prints something?
    def __init__(self, path: Path) -> None:
        result = run("git -C {path} status", stdout=DEVNULL, stderr=DEVNULL)
        if result.returncode != 0:
            raise ValueError(f"{path} is not a git repository")
        self.path = path

    def current_branch(self) -> GitRevision:
        return (
            run(
                f"git -C {self.path} branch --show-current",
                capture_output=True,
                check=True,
            )
            .stdout.decode("utf-8")
            .strip()
        )

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

        run(cmd, check=True, stdout=DEVNULL, stderr=DEVNULL)

    def remove_worktree(
        self,
        worktree_path: Path,
        force: bool = True,
    ) -> None:

        cmd = f"git -C {self.path} worktree remove {worktree_path}"
        if force:
            cmd += " --force"

        run(cmd, check=True, stdout=DEVNULL, stderr=DEVNULL)


def rev_parse(worktree_dir: Path, rev: str) -> GitRevision:
    return run(
        f"git -C {worktree_dir} rev-parse {rev}",
        check=True,
        capture_output=True,
    ).stdout.decode("utf-8")


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
    run(cmd, check=True)
    return parse_bisect_head(worktree_dir)


def bisect_skip(
    worktree_dir: Path,
) -> None:
    cmd = f"git -C {worktree_dir} bisect skip"
    run(cmd, check=True)


def bisect_good(
    worktree_dir: Path,
) -> None:
    cmd = f"git -C {worktree_dir} bisect good"
    run(cmd, check=True)


def bisect_bad(
    worktree_dir: Path,
) -> None:
    cmd = f"git -C {worktree_dir} bisect bad"
    run(cmd, check=True)


def currently_bisecting(worktree_dir: Path) -> bool:
    pass
    # count visualize lines?


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


import logging
import math
from abc import ABC, abstractmethod
from typing import Optional

from ccbuilder import Commit, CompilerProject, Repo, Revision, find_cached_revisions


class BisectionException(Exception):
    pass


def find_sorted_cached_commits_from_range(
    good_rev: Revision,
    bad_rev: Revision,
    project: CompilerProject,
    repo: Repo,
    cache_prefix: Path,
) -> list[Commit]:
    """Return all cached commits that are in the range R=[good_rev, bad_rev] such that
    R[i+1] is ancestor of R[i].

    Args:
        good_rev (Revision): good_rev
        bad_rev (Revision): bad_rev
        project (CompilerProject): project
        repo (Repo): Repository for `project`
        cache_prefix (Path): Path to the cache.

    Returns:
        list[Commit]:
            All cached commits in [good_rev, bad_rev] ordered via the ancestor relation.
    """
    possible_revs = repo.direct_first_parent_path(good_rev, bad_rev)

    cached_revs = find_cached_revisions(project, cache_prefix)
    cached_revs = [r for r in cached_revs if r in possible_revs]

    # Create enumeration dict to sort cached_revs with
    sort_dict = dict((r, v) for v, r in enumerate(possible_revs))
    cached_revs = sorted(cached_revs, key=lambda x: sort_dict[x])
    return cached_revs


def _get_midpoint_after_failure(
    bad_rev: Revision,
    good_rev: Revision,
    midpoint: Revision,
    failed_to_build_counter: int,
    repo: Repo,
    max_failed_builds: int = 3,
) -> Commit:
    if failed_to_build_counter >= max_failed_builds:
        raise BisectionException(
            "Failed too many times in a row while bisecting. Aborting bisection..."
        )
    if failed_to_build_counter % 2 == 0:
        # Get size of range
        range_size = len(repo.direct_first_parent_path(midpoint, bad_rev))

        # Move 10% towards the last bad
        step = max(int(0.9 * range_size), 1)
        midpoint = repo.rev_to_commit(f"{bad_rev}~{step}")
    else:
        # Symmetric to case above but jumping 10% into
        # the other direction i.e 20% from our position.
        range_size = len(repo.direct_first_parent_path(good_rev, midpoint))
        step = max(int(0.2 * range_size), 1)
        midpoint = repo.rev_to_commit(f"{midpoint}~{step}")
    return midpoint


def _terminate(guaranteed_termination_counter: int) -> bool:
    if guaranteed_termination_counter >= 20:
        logging.warning(
            "Failed too many times in a row while bisecting. Aborting bisection..."
        )
        return True
    return False



class Bisector:
    def __init__(self, build_cache_prefix: Path):
        self.build_cache_prefix = build_cache_prefix
        return

    def bisect(
        self,
        test: BisectionCallback,
        bad_rev: Revision,
        good_rev: Revision,
        project: CompilerProject,
        repo: Repo,
    ) -> Commit | None:
        """Bisect between `bad_rev` and `good_rev` based on the provided `test` callback
        `test(bad_rev)` must be True.
        `test(good_rev)` must be False.

        Args:
            test (BisectionCallback):
                Interestingness test.
            bad_rev (Revision):
                Revision that shows the initial unwanted behaviour, defined in `test`.
            good_rev (Revision):
                Revision that shows the initial correct behaviour.
            project (CompilerProject):
                Which project on bisect in.
            repo (Repo):
                Repository for the `project`.

        Returns:
            Commit | None: The bisection commit that introduced the behaviour
        """

        # sanitize revs
        good_commit = repo.rev_to_commit(good_rev)
        bad_commit = repo.rev_to_commit(bad_rev)

        # Make sure there is a direct path between the two
        # commits. If none is found or the good commit would
        # 'land on top', we abort.
        if not repo.is_ancestor(good_commit, bad_commit):
            bca = repo.get_best_common_ancestor(good_commit, bad_commit)
            test_res: bool | None = test.check(bca)
            match test_res:
                case False:
                    good_commit = bca
                case True:
                    logging.info("Best common ancestor is interesting. Can't bisect.")
                    return None
                case None:
                    logging.info("Test for best common ancestor failed. Can't bisect.")
                    return None

        try:
            good_commit, bad_commit = self._in_cache_path_bisection(
                test=test,
                bad_commit=bad_commit,
                good_commit=good_commit,
                project=project,
                repo=repo,
            )
            logging.info(f"{good_commit=} {bad_commit=}")
            if bisection_commit := self._normal_path_bisection(
                test=test,
                bad_commit=bad_commit,
                good_commit=good_commit,
                project=project,
                repo=repo,
            ):
                # Check if the result is correct
                pre_bisection_commit = repo.rev_to_commit(f"{bisection_commit}~")
                bisection_res = test.check(bisection_commit)
                pre_bisection_res = test.check(pre_bisection_commit)
                if bisection_res and not pre_bisection_res:
                    return bisection_commit
                logging.warning("Bisection check failed!")
                return None
            return None
        except BisectionException as e:
            logging.warning(e)
            return None

    def _in_cache_path_bisection(
        self,
        test: BisectionCallback,
        bad_commit: Commit,
        good_commit: Commit,
        project: CompilerProject,
        repo: Repo,
    ) -> tuple[Commit, Commit]:
        cached_commits = find_sorted_cached_commits_from_range(
            good_commit, bad_commit, project, repo, self.build_cache_prefix
        )

        logging.info("Bisecting in cache...")
        midpoint = ""
        old_midpoint = ""
        while True:
            logging.info(
                f"{len(cached_commits): 4}, bad: {bad_commit}, good: {good_commit}"
            )
            if len(cached_commits) == 0:
                break
            midpoint_idx = len(cached_commits) // 2
            old_midpoint = midpoint
            midpoint = cached_commits[midpoint_idx]
            if old_midpoint == midpoint:
                break

            test_res: bool | None = test.check(midpoint)

            match test_res:
                case True:
                    bad_commit = midpoint
                    cached_commits = cached_commits[midpoint_idx + 1 :]
                case False:
                    good_commit = midpoint
                    cached_commits = cached_commits[:midpoint_idx]
                case None:
                    # Test failed.
                    cached_commits.remove(midpoint)

        return good_commit, bad_commit

    def _normal_path_bisection(
        self,
        test: BisectionCallback,
        bad_commit: Commit,
        good_commit: Commit,
        project: CompilerProject,
        repo: Repo,
    ) -> Commit | None:
        logging.info("Starting normal bisection...")
        len_region = len(repo.direct_first_parent_path(good_commit, bad_commit))
        logging.info(f"Bisecting for approx. {math.ceil(math.log2(len_region))} steps")
        midpoint = ""
        old_midpoint = ""
        test_failed = False
        failed_to_build_counter = 0

        guaranteed_termination_counter = 0
        while True:
            if not test_failed:
                old_midpoint = midpoint
                midpoint = repo.next_bisection_commit(good_commit, bad_commit)
                failed_to_build_counter = 0
                guaranteed_termination_counter = 0
                if midpoint == "" or midpoint == old_midpoint:
                    break
            else:
                midpoint = _get_midpoint_after_failure(
                    bad_commit, good_commit, midpoint, failed_to_build_counter, repo
                )
                if _terminate(guaranteed_termination_counter):
                    return None
                guaranteed_termination_counter += 1
                failed_to_build_counter += 1
                test_failed = False

            logging.info(f"Midpoint: {midpoint}")

            match test.check(midpoint):
                case True:
                    bad_commit = midpoint
                case False:
                    good_commit = midpoint
                case None:
                    test_failed = True

        logging.info(f"Bisection result: {bad_commit}")
        return bad_commit
