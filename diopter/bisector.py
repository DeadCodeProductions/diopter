import logging
import os
import subprocess
from pathlib import Path
from typing import Callable, Optional, TypeVar

from ccbuilder import (
    Builder,
    BuildException,
    Commit,
    CompilerProject,
    Repo,
    Revision,
    find_cached_revisions,
    get_repo,
)

from diopter.utils import TempDirEnv, run_cmd

C = TypeVar("C")


class BisectionException(Exception):
    pass


class Bisector:
    def __init__(self, bldr: Builder):
        self.bldr = bldr
        return

    def bisect_higherorder(
        self,
        cse: C,
        test: Callable[[Commit, C, Builder], Optional[bool]],
        bad_commit: Commit,
        good_commit: Commit,
        project: CompilerProject,
        repo: Repo,
    ) -> Optional[Commit]:
        print("LETS GOO")
        possible_commits = repo.direct_first_parent_path(good_commit, bad_commit)

        cached_commits = find_cached_revisions(project, self.bldr.cache_prefix)
        cached_commits = [r for r in cached_commits if r in possible_commits]

        # Create enumeration dict to sort cached_commits with
        sort_dict = dict((r, v) for v, r in enumerate(possible_commits))
        cached_commits = sorted(cached_commits, key=lambda x: sort_dict[x])

        # bisect in cache
        len_region = len(possible_commits)
        logging.info(f"Bisecting in cache...")
        midpoint: Commit = ""
        old_midpoint: Commit = ""
        test_failed = False
        while True:
            if test_failed:
                # TODO: Introduce failure management option
                test_failed = False
                cached_commits.remove(midpoint)

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

            test_res: Optional[bool] = test(midpoint, cse, self.bldr)

            match test_res:
                case True:
                    good_commit = midpoint
                    cached_commits = cached_commits[:midpoint_idx]
                case False:
                    bad_commit = midpoint
                    cached_commits = cached_commits[midpoint_idx + 1 :]
                case None:
                    test_failed = True

        tmp_len_region = len(repo.direct_first_parent_path(good_commit, bad_commit))
        logging.info(f"Cache bisection: range size {len_region} -> {tmp_len_region}")
        len_region = tmp_len_region

        midpoint = ""
        old_midpoint = ""
        failed_any_step = False
        failed_any_step_counter = 0

        guaranteed_termination_counter = 0
        while True:
            if not failed_any_step:
                old_midpoint = midpoint
                midpoint = repo.next_bisection_commit(good_commit, bad_commit)
                failed_any_step_counter = 0
                if midpoint == "" or midpoint == old_midpoint:
                    break
            else:
                if failed_any_step_counter >= 3:  # TODO: make parameter for this
                    raise BisectionException(
                        "Failed too many times in a row while bisecting. Aborting bisection..."
                    )
                if failed_any_step_counter % 2 == 0:
                    # Get size of range
                    range_size = len(
                        repo.direct_first_parent_path(midpoint, bad_commit)
                    )

                    # Move 10% towards the last bad
                    step = max(int(0.9 * range_size), 1)
                    midpoint = repo.rev_to_commit(f"{bad_commit}~{step}")
                else:
                    # Symmetric to case above but jumping 10% into the other directory i.e 20% from our position.
                    range_size = len(
                        repo.direct_first_parent_path(good_commit, midpoint)
                    )
                    step = max(int(0.2 * range_size), 1)
                    midpoint = repo.rev_to_commit(f"{midpoint}~{step}")

                failed_any_step_counter += 1
                failed_any_step = False

                if guaranteed_termination_counter >= 20:
                    raise BisectionException(
                        "Failed too many times in a row while bisecting. Aborting bisection..."
                    )
                guaranteed_termination_counter += 1

            logging.info(f"Midpoint: {midpoint}")

            try:
                self.bldr.build(project, midpoint)
            except BuildException:
                logging.warning(f"Could not build {project.to_string()} {midpoint}!")
                failed_any_step = True
                continue

            test_res = test(midpoint, cse, self.bldr)

            match test_res:
                case True:
                    good_commit = midpoint
                case False:
                    bad_commit = midpoint
                case None:
                    test_failed = True
        return bad_commit

    def bisect(
        self,
        code: str,
        interestingness_test: str,
        project: CompilerProject,
        good_compiler_rev: Revision,
        bad_compiler_rev: Revision,
        compiler_repo_path: Path,
        inverse_test_result: bool = False,
    ) -> Optional[Commit]:
        # TODO Update docs
        """bisect.

        Args:
            self:
            code (str): code
            interestingness_test (str): interestingness_test
            compiler_project (ccbuilder.Compiler): compiler_project
            good_compiler_rev (str): good_compiler_rev
            bad_compiler_rev (str): bad_compiler_rev
            compiler_repo_path (Path): compiler_repo_path
            inverse_test_result (bool): inverse_test_result

        Returns:
            Optional[str]:
        """

        repo = get_repo(project, compiler_repo_path)

        # sanitize revs
        good_rev = repo.rev_to_commit(good_compiler_rev)
        bad_rev = repo.rev_to_commit(bad_compiler_rev)

        # Write test script
        with TempDirEnv(change_dir=True) as tmpdir:
            code_file = tmpdir / "code.c"
            with open(code_file, "w") as f:
                f.write(code)

            script_path = tmpdir / "check.py"
            with open(script_path, "w") as f:
                print(interestingness_test, file=f)
            os.chmod(script_path, 0o770)

            try:
                return self._bisection(
                    project,
                    good_rev,
                    bad_rev,
                    repo,
                    inverse_test_result,
                )
            except BisectionException as e:
                logging.warning(e)
                return None

    def _run_test(self, midpoint_compiler_path: Path) -> bool:
        cmd = ["check.py", str(midpoint_compiler_path)]
        try:
            run_cmd(cmd)
            return True
        except subprocess.CalledProcessError:
            return False

    def _bisection(
        self,
        project: CompilerProject,
        good_rev: str,
        bad_rev: str,
        repo: Repo,
        inverse_test_result: bool,
    ) -> Commit:

        possible_revs = repo.direct_first_parent_path(good_rev, bad_rev)

        cached_revs = find_cached_revisions(project, self.bldr.cache_prefix)
        cached_revs = [r for r in cached_revs if r in possible_revs]

        # Create enumeration dict to sort cached_revs with
        sort_dict = dict((r, v) for v, r in enumerate(possible_revs))
        cached_revs = sorted(cached_revs, key=lambda x: sort_dict[x])

        # bisect in cache
        len_region = len(repo.direct_first_parent_path(good_rev, bad_rev))
        logging.info(f"Bisecting in cache...")
        midpoint: Commit = ""
        old_midpoint: Commit = ""
        failed_to_compile = False
        while True:
            if failed_to_compile:
                failed_to_compile = False
                cached_revs.remove(midpoint)

            logging.info(f"{len(cached_revs): 4}, bad: {bad_rev}, good: {good_rev}")
            if len(cached_revs) == 0:
                break
            midpoint_idx = len(cached_revs) // 2
            old_midpoint = midpoint
            midpoint = cached_revs[midpoint_idx]
            if old_midpoint == midpoint:
                break

            midpoint_path = self.bldr.build(project, midpoint)
            test: bool = self._run_test(midpoint_path)

            if test:
                # bad is always "on top" in the history tree
                # git rev-list returns commits in order of the parent relation
                # cached_revs is also sorted in that order
                # Thus when finding something bad i.e interesting, we have to cut the head
                # and when finding something good, we have to cut the tail
                if inverse_test_result:
                    bad_rev = midpoint
                    cached_revs = cached_revs[midpoint_idx + 1 :]
                else:
                    good_rev = midpoint
                    cached_revs = cached_revs[:midpoint_idx]
            else:
                if inverse_test_result:
                    good_rev = midpoint
                    cached_revs = cached_revs[:midpoint_idx]
                else:
                    bad_rev = midpoint
                    cached_revs = cached_revs[midpoint_idx + 1 :]

        tmp_len_region = len(repo.direct_first_parent_path(good_rev, bad_rev))
        logging.info(f"Cache bisection: range size {len_region} -> {tmp_len_region}")
        len_region = tmp_len_region

        midpoint = ""
        old_midpoint = ""
        failed_to_build_or_compile = False
        failed_to_build_counter = 0

        guaranteed_termination_counter = 0
        while True:
            if not failed_to_build_or_compile:
                old_midpoint = midpoint
                midpoint = repo.next_bisection_commit(good_rev, bad_rev)
                failed_to_build_counter = 0
                if midpoint == "" or midpoint == old_midpoint:
                    break
            else:
                if failed_to_build_counter >= 3:  # TODO: make parameter for this
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
                    # Symmetric to case above but jumping 10% into the other directory i.e 20% from our position.
                    range_size = len(repo.direct_first_parent_path(good_rev, midpoint))
                    step = max(int(0.2 * range_size), 1)
                    midpoint = repo.rev_to_commit(f"{midpoint}~{step}")

                failed_to_build_counter += 1
                failed_to_build_or_compile = False

                if guaranteed_termination_counter >= 20:
                    raise BisectionException(
                        "Failed too many times in a row while bisecting. Aborting bisection..."
                    )
                guaranteed_termination_counter += 1

            logging.info(f"Midpoint: {midpoint}")

            try:
                midpoint_path = self.bldr.build(project, midpoint)
                test = self._run_test(midpoint_path)
            except BuildException:
                logging.warning(f"Could not build {project.to_string()} {midpoint}!")
                failed_to_build_or_compile = True
                continue

            if test:
                if inverse_test_result:
                    bad_rev = midpoint
                else:
                    good_rev = midpoint
            else:
                if inverse_test_result:
                    good_rev = midpoint
                else:
                    bad_rev = midpoint

        return bad_rev
