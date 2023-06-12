from __future__ import annotations

import os
import subprocess
from functools import cache
from pathlib import Path
from typing import NewType

from diopter.compiler import CompilerProject
from diopter.utils import run_cmd

DEFAULT_REPOS_DIR = Path.home() / ".cache" / "diopter-compiler-repos"


class RepositoryException(Exception):
    pass


Revision = NewType("Revision", str)
Commit = NewType("Commit", str)


class Repo:
    def __init__(self, path: Path, main_branch: Revision):
        self.path = os.path.abspath(path)
        try:
            run_cmd(f"git -C {self.path} status")
        except Exception:
            raise ValueError(f"{path} is not a git repository")
        self.main_branch = main_branch

    def current_branch(self) -> Revision:
        return Revision(run_cmd(f"git -C {self.path} branch --show-current").stdout)

    @cache
    def get_best_common_ancestor(self, rev_a: Revision, rev_b: Revision) -> Commit:
        a = self.rev_to_commit(rev_a)
        b = self.rev_to_commit(rev_b)
        return Commit(run_cmd(f"git -C {self.path} merge-base {a} {b}").stdout)

    @cache
    def rev_to_commit(self, rev: Revision) -> Commit:
        """Convert any revision (commits, tags etc.) into their
        SHA1 hash via git rev-parse.

        Args:
            rev (str): Revision to convert.

        Returns:
            str: Hash of `rev` in this repo.
        """
        # Could support list of revs...
        try:
            if rev == "trunk" or rev == "master" or rev == "main":
                rev = self.main_branch
            return Commit(run_cmd(f"git -C {self.path} rev-parse {rev}").stdout)
        except subprocess.CalledProcessError as e:
            raise RepositoryException(e)

    def rev_to_range_needing_patch(
        self, introducer: Commit, fixer: Commit
    ) -> list[Commit]:  # noqa: W605
        """
        This function's aim is best described with a picture # noqa: W605
           O---------P
          /   G---H   \      I---J       L--M
         /   /     \   \    /     \     /
        A---B---Z---C---N---D-------E---F---K
             \     /
              Q---R
        call rev_to_range_needing_patch(G, K) gives
        (K, F, 'I, J, D, E', C, H, G)
        in particular it doesn't include Z, P, O, Q and R
        Range G~..K would include these

        Args:
            introducer (Commit): introducer commit
            fixer (Commit): fixer commit

        Returns:
            list[Commit]: List of revision hashes needing the patch.
        """
        #

        # Get all commits with at least 2 parents
        try:
            merges_after_introducer = run_cmd(
                f"git -C {self.path} rev-list --merges {introducer}~..{fixer}",
            ).stdout
        except subprocess.CalledProcessError as e:
            raise RepositoryException(e)

        if len(merges_after_introducer) > 0:
            # Get all parent commits of these (so for C it would be H, Z and R)
            cmd = f"git -C {self.path} rev-parse " + "^@ ".join(merges_after_introducer)
            try:
                merger_parents = set(run_cmd(cmd).stdout.split("\n"))
            except subprocess.CalledProcessError as e:
                raise RepositoryException(e)

            # Remove all parents which are child of the requested commit
            unwanted_merger_parents = [
                parent
                for parent in merger_parents
                if not self.is_ancestor(Revision(introducer), Revision(parent))
            ]
        else:
            unwanted_merger_parents = []
        cmd = f"git -C {self.path} rev-list {fixer} ^{introducer} " + " ^".join(
            unwanted_merger_parents
        )
        try:
            res = [
                Commit(commit)
                for commit in run_cmd(cmd).stdout.split("\n")
                if commit != ""
            ] + [introducer]
            return res
        except subprocess.CalledProcessError as e:
            raise RepositoryException(e)

    def direct_first_parent_path(self, older: Commit, younger: Commit) -> list[Commit]:
        """Get interval of commits [younger, older] always following the
        first parent.

        Args:
            self:
            older (Commit): Older commit
            younger (Commit): Younger commit

        Returns:
            list[Commit]: Commits [younger, older] following the first parent.
        """
        cmd = f"git -C {self.path} rev-list --first-parent {younger} ^{older}"
        try:
            res = [
                Commit(commit)
                for commit in run_cmd(cmd).stdout.split("\n")
                if commit != ""
            ] + [older]
            return res
        except subprocess.CalledProcessError as e:
            raise RepositoryException(e)

    def rev_to_commit_list(self, rev: Revision) -> list[Commit]:
        try:
            return [
                Commit(commit)
                for commit in run_cmd(
                    f"git -C {self.path} log --format=%H {rev}"
                ).stdout.split("\n")
            ]

        except subprocess.CalledProcessError as e:
            raise RepositoryException(e)

    def is_ancestor(
        self, rev_old: Revision | Commit, rev_young: Revision | Commit
    ) -> bool:
        commit_old = self.rev_to_commit(rev_old)
        commit_young = self.rev_to_commit(rev_young)

        process = subprocess.run(
            f"git -C {self.path} merge-base --is-ancestor "
            f"{commit_old} {commit_young}".split(" "),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        return process.returncode == 0

    def is_branch_point_ancestor_wrt_master(
        self, rev_old: Revision, rev_young: Revision
    ) -> bool:
        """
        In the following example, Young is not ancestor of Old but
        their respective best common ancestors wrt to main (i.e. the commit
        where they branched away from Main) are ancestors.

        Main
         | Young
         |/
         | Old
         |/

        Args:
            self:
            rev_old (Revision): rev_old
            rev_young (Revision): rev_young

        Returns:
            bool: True if their best common ancestors with main are ancestors.
        """
        commit_old = self.rev_to_commit(rev_old)
        commit_young = self.rev_to_commit(rev_young)
        commit_master = self.rev_to_commit("master")
        ca_young = self.get_best_common_ancestor(commit_master, commit_young)
        ca_old = self.get_best_common_ancestor(commit_master, commit_old)

        return self.is_ancestor(ca_old, ca_young)

    def on_same_branch_wrt_master(self, rev_a: Revision, rev_b: Revision) -> bool:
        commit_a = self.rev_to_commit(rev_a)
        commit_b = self.rev_to_commit(rev_b)
        commit_master = self.rev_to_commit("master")

        ca_a = self.get_best_common_ancestor(commit_a, commit_master)
        ca_b = self.get_best_common_ancestor(commit_b, commit_master)

        return ca_b == ca_a

    def get_unix_timestamp(self, rev: Revision) -> int:
        commit = self.rev_to_commit(rev)
        try:
            return int(
                run_cmd(
                    f"git -C {self.path} log -1 --format=%at {commit}",
                ).stdout
            )
        except subprocess.CalledProcessError as e:
            raise RepositoryException(e)

    def apply(self, patches: list[Path], check: bool = False) -> bool:
        patches = [patch.absolute() for patch in patches]
        git_patches = [
            str(patch) for patch in patches if not str(patch).endswith(".sh")
        ]
        sh_patches = [f"sh {patch}" for patch in patches if str(patch).endswith(".sh")]
        if check:
            git_cmd = f"git -C {self.path} apply --check".split(" ") + git_patches
            sh_patches = [patch_cmd + " --check" for patch_cmd in sh_patches]
        else:
            git_cmd = f"git -C {self.path} apply".split(" ") + git_patches

        returncode = 0
        for patch_cmd in [patch_cmd.split(" ") for patch_cmd in sh_patches]:
            returncode += subprocess.run(
                patch_cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
            ).returncode

        if len(git_patches) > 0:
            returncode += subprocess.run(
                git_cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
            ).returncode

        return returncode == 0

    def next_bisection_commit(
        self, good: Revision | Commit, bad: Revision | Commit
    ) -> Commit:
        request_str = (
            f"git -C {self.path} rev-list --bisect --first-parent {bad} ^{good}"
        )
        try:
            return Commit(run_cmd(request_str).stdout)
        except subprocess.CalledProcessError as e:
            raise RepositoryException(e)

    def pull(self) -> None:
        """Pulls from the main branch of the repository.
        It will switch the repository to the main branch.
        It will also invalidate the caches of `rev_to_commit`
        , `get_best_common_ancestor` and `rev_to_tag`.

        Args:
            self:

        Returns:
            None:
        """
        self.rev_to_commit.cache_clear()
        self.get_best_common_ancestor.cache_clear()
        self.rev_to_tag.cache_clear()
        # Just in case...
        cmd0 = f"git -C {self.path} switch {self.main_branch}"
        cmd1 = f"git -C {self.path} pull"
        try:
            run_cmd(cmd0)
            run_cmd(cmd1)
        except subprocess.CalledProcessError as e:
            raise RepositoryException(e)

    @cache
    def rev_to_tag(self, rev: Revision) -> Commit | None:
        request_str = f"git -C {self.path} describe --exact-match {rev}"
        output = subprocess.run(
            request_str.split(),
            capture_output=True,
        )
        stdout = output.stdout.decode("utf-8").strip()
        stderr = output.stderr.decode("utf-8").strip()
        if stderr.startswith("fatal:"):
            return None
        return Commit(stdout)

    @cache
    def parent(self, rev: Revision) -> Commit:
        request_str = f"git -C {self.path} rev-parse {rev}^@"
        try:
            res = run_cmd(request_str).stdout
        except subprocess.SubprocessError as e:
            raise RepositoryException(e)

        assert len(res.split("\n")) == 1
        return Commit(res)

    def prune_worktree(self) -> None:
        prune_str = f"git -C {self.path} worktree prune"
        try:
            run_cmd(prune_str)
        except subprocess.SubprocessError as e:
            raise RepositoryException(e)

    def tags(self) -> list[Revision]:
        print_cmd = f"git -C {self.path} tag -l"
        try:
            res = run_cmd(print_cmd).stdout
        except subprocess.SubprocessError as e:
            raise RepositoryException(e)
        return [Revision(rev) for rev in res.splitlines()]

    def add_worktree(
        self,
        target_path: Path,
        branch: Revision,
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


def get_llvm_repo(path_to_repo: Path | None = None) -> Repo:
    if path_to_repo:
        return Repo(path_to_repo, Revision("main"))
    return Repo(DEFAULT_REPOS_DIR / "llvm-project", Revision("main"))


def get_gcc_repo(path_to_repo: Path | None = None) -> Repo:
    if path_to_repo:
        return Repo(path_to_repo, Revision("master"))
    return Repo(DEFAULT_REPOS_DIR / "gcc", Revision("master"))


def get_gcc_releases(repo: Repo) -> list[Revision]:
    releases = []
    for r in repo.tags():
        if not r.startswith("releases/gcc-"):
            continue
        # We filter out older releases that we can't build
        should_skip = False
        for v in ("2", "3", "4", "5", "6"):
            if r.startswith(f"releases/gcc-{v}."):
                should_skip = True
                break
        if should_skip:
            continue
        releases.append(r)

    return sorted(
        releases, reverse=True, key=lambda x: int(x.split("-")[-1].replace(".", ""))
    )


def get_llvm_releases(repo: Repo) -> list[Revision]:
    releases = []
    for r in repo.tags():
        if not r.startswith("llvmorg-"):
            continue
        if "-rc" in r or "init" in r:
            continue
        # We filter out older releases that we can't build
        should_skip = False
        for v in ("1", "2", "3", "4"):
            if r.startswith(f"llvmorg-{v}."):
                should_skip = True
                break
        if should_skip:
            continue
        releases.append(r)

    return sorted(
        releases, reverse=True, key=lambda x: int(x.split("-")[-1].replace(".", ""))
    )


def get_releases(project: CompilerProject, repo: Repo) -> list[Revision]:
    match project:
        case CompilerProject.GCC:
            return get_gcc_releases(repo)
        case CompilerProject.LLVM:
            return get_llvm_releases(repo)
