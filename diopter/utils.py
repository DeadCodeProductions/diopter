from __future__ import annotations

import os
import shlex
import subprocess
import tempfile
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from shutil import copy
from types import TracebackType
from typing import IO, Any, Literal, TextIO, Union

import diopter.repository as repository


@dataclass(frozen=True, kw_only=True)
class CommandOutput:
    stdout: str
    stderr: str


def run_cmd(
    cmd: Union[str, list[str]],
    working_dir: Path | None = None,
    additional_env: dict[str, str] = {},
    **kwargs: Any,  # https://github.com/python/mypy/issues/8772
) -> CommandOutput:
    if working_dir is None:
        working_dir = Path(os.getcwd())
    env = os.environ.copy()
    env.update(additional_env)

    if isinstance(cmd, list):
        cmd = " ".join(cmd)
    output = subprocess.run(
        shlex.split(cmd.replace('"', '\\"')),
        cwd=str(working_dir),
        check=True,
        env=env,
        capture_output=True,
        **kwargs,
    )

    return CommandOutput(
        stdout=output.stdout.decode("utf-8").strip(),
        stderr=output.stderr.decode("utf-8").strip(),
    )


def run_cmd_async(
    cmd: Union[str, list[str]],
    working_dir: Path | None = None,
    additional_env: dict[str, str] = {},
    stdout: IO[str] | int | None = subprocess.PIPE,
    stderr: IO[str] | int | None = subprocess.PIPE,
    **kwargs: Any,
) -> subprocess.Popen[Any]:
    if working_dir is None:
        working_dir = Path(os.getcwd())
    env = os.environ.copy()
    env.update(additional_env)

    if isinstance(cmd, list):
        cmd = " ".join(cmd)

    return subprocess.Popen(
        shlex.split(cmd.replace('"', '\\"')),
        cwd=str(working_dir),
        env=env,
        stdout=stdout,
        stderr=stderr,
        **kwargs,
    )


def run_cmd_to_logfile(
    cmd: Union[str, list[str]],
    log_file: TextIO | None = None,
    working_dir: Path | None = None,
    additional_env: dict[str, str] = {},
) -> None:
    if working_dir is None:
        working_dir = Path(os.getcwd())
    env = os.environ.copy()
    env.update(additional_env)

    if isinstance(cmd, list):
        cmd = " ".join(cmd)

    subprocess.run(
        shlex.split(cmd),
        cwd=working_dir,
        check=True,
        stdout=log_file,
        stderr=subprocess.STDOUT,
        env=env,
        capture_output=False,
    )


class TempDirEnv:
    def __init__(self, change_dir: bool = False) -> None:
        self.td: tempfile.TemporaryDirectory[str]
        self.old_dir: Path

        self.chdir = change_dir

    def __enter__(self) -> Path:
        self.td = tempfile.TemporaryDirectory()
        tempfile.tempdir = self.td.name
        tmpdir_path = Path(self.td.name)
        if self.chdir:
            self.old_dir = Path(os.getcwd()).absolute()
            os.chdir(tmpdir_path)
        return tmpdir_path

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        exc_traceback: TracebackType | None,
    ) -> None:
        if self.chdir:
            os.chdir(self.old_dir)
        self.td.cleanup()
        tempfile.tempdir = None


def temporary_file(
    *, contents: str | None = None, suffix: str | None = None, delete: bool = True
) -> IO[bytes]:
    """Creates a named temporary file with extension
    `suffix` and writes `contents` into it.

    Args:
        contents (str):
            what to write in the temporary file
        suffix (str):
            the file's extension (e.g., ".c")
    Returns:
        tempfile.NamedTemporaryFile:
            a temporary file that is automatically deleted when the object is
            garbage collected
    """
    ntf = tempfile.NamedTemporaryFile(suffix=suffix, delete=delete)
    if contents:
        with open(ntf.name, "w") as f:
            f.write(contents)
    return ntf


class CompilerProject(Enum):
    GCC = 0
    LLVM = 1

    def to_string(self) -> str:
        return "gcc" if self == CompilerProject.GCC else "clang"


def get_compiler_info(
    project_name: Union[Literal["llvm"], Literal["gcc"], Literal["clang"]],
    repo_dir_prefix: Path,
) -> tuple[CompilerProject, repository.Repo]:
    match project_name:
        case "gcc":
            repo = repository.Repo(repo_dir_prefix / "gcc", "master")
            return CompilerProject.GCC, repo
        case "llvm" | "clang":
            repo = repository.Repo(repo_dir_prefix / "llvm-project", "main")
            return CompilerProject.LLVM, repo
        case _:
            raise Exception(f"Unknown compiler project {project_name}!")


def get_compiler_project(project_name: str) -> CompilerProject:
    """Get the `CompilerProject` from the project name.

    Args:
        project_name (str):

    Returns:
        CompilerProject: Project corresponding to `project_name`.
    """
    match project_name:
        case "gcc":
            return CompilerProject.GCC
        case "llvm" | "clang":
            return CompilerProject.LLVM
        case _:
            raise Exception(f"Unknown compiler project {project_name}!")


def find_cached_revisions(
    project: CompilerProject, cache_prefix: Path
) -> list[repository.Commit]:
    """Get all commits of `project` that have been built and cached in `cache_prefix`.

    Args:
        project (CompilerProject): Project to get commits for.
        cache_prefix (Path): Path to cache.

    Returns:
        list[repository.Commit]:
    """
    match project:
        case CompilerProject.GCC:
            compiler_name = "gcc"
        case CompilerProject.LLVM:
            compiler_name = "clang"

    compilers: list[str] = []

    for entry in Path(cache_prefix).iterdir():
        if entry.is_symlink() or not entry.stem.startswith(compiler_name):
            continue
        if not (entry / "bin" / compiler_name).exists():
            continue
        rev = str(entry).split("-")[-1]
        compilers.append(rev)
    return compilers


def initialize_repos(repos_dir: str) -> None:
    repos_path = Path(repos_dir)
    repos_path.mkdir(parents=True, exist_ok=True)
    llvm = repos_path / "llvm-project"
    if not llvm.exists():
        print("Cloning LLVM...")
        run_cmd(f"git clone https://github.com/llvm/llvm-project.git {llvm}")
    gcc = repos_path / "gcc"
    if not gcc.exists():
        print("Cloning GCC...")
        run_cmd(f"git clone git://gcc.gnu.org/git/gcc.git {gcc}")


def initialize_patches_dir(patches_dir: str) -> None:
    patches_path = Path(patches_dir)
    if not patches_path.exists():
        _ROOT = Path(__file__).parent.parent.absolute()
        patches_path.mkdir(parents=True, exist_ok=True)
        patches_source_dir = _ROOT / "data" / "patches"
        for entry in patches_source_dir.iterdir():
            copy(entry, patches_path / entry.name)
