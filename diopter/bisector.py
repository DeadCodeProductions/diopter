import logging
import os

from typing import Optional

import ccbuilder
import subprocess
from diopter.utils import TempDirEnv, run_cmd_to_logfile, run_cmd
from ccbuilder import (
    PatchDB,
    BuilderWithCache,
    Repo,
    Compiler,
    BuildException,
    CompilerConfig,
)
from pathlib import Path


class BisectionException(Exception):
    pass


def find_cached_revisions(compiler: Compiler, cache_prefix: Path) -> list[str]:

    match compiler:
        case Compiler.GCC:
            compiler_name = "gcc"
        case Compiler.LLVM:
            compiler_name = "clang"

    if compiler_name == "llvm":
        compiler_name = "clang"
    compilers = []

    for entry in Path(cache_prefix).iterdir():
        if entry.is_symlink() or not entry.stem.startswith(compiler_name):
            continue
        if not (entry / "bin" / compiler_name).exists():
            continue
        rev = str(entry).split("-")[-1]
        compilers.append(rev)
    return compilers


class Bisector:
    def __init__(self, bldr: BuilderWithCache):
        self.bldr = bldr
        return

    def bisect(
        self,
        code: str,
        interestingness_test: str,
        compiler_project: ccbuilder.Compiler,
        good_compiler_rev: str,
        bad_compiler_rev: str,
        compiler_repo_path: Path,
        inverse_test_result: bool = False,
    ) -> Optional[str]:
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

        compiler_config = ccbuilder.get_compiler_config(
            compiler_project.to_string(), compiler_repo_path
        )

        repo = compiler_config.repo

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
                    compiler_project,
                    compiler_config,
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
        compiler: Compiler,
        compiler_config: CompilerConfig,
        good_rev: str,
        bad_rev: str,
        repo: Repo,
        inverse_test_result: bool,
    ) -> str:

        possible_revs = repo.direct_first_parent_path(good_rev, bad_rev)

        cached_revs = find_cached_revisions(compiler, self.bldr.cache_prefix)
        cached_revs = [r for r in cached_revs if r in possible_revs]

        # Create enumeration dict to sort cached_revs with
        sort_dict = dict((r, v) for v, r in enumerate(possible_revs))
        cached_revs = sorted(cached_revs, key=lambda x: sort_dict[x])

        # bisect in cache
        len_region = len(repo.direct_first_parent_path(good_rev, bad_rev))
        logging.info(f"Bisecting in cache...")
        midpoint = ""
        old_midpoint = ""
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

            midpoint_path = self.bldr.build_rev_with_config(compiler_config, midpoint)
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
                midpoint_path = self.bldr.build_rev_with_config(
                    compiler_config, midpoint
                )
                test = self._run_test(midpoint_path)
            except BuildException:
                logging.warning(f"Could not build {compiler.to_string()} {midpoint}!")
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
