import copy
import logging
import os
import subprocess
import tempfile
from pathlib import Path
from types import TracebackType
from typing import IO, Any, Optional, TextIO, Union

import ccbuilder

import diopter


def run_cmd(
    cmd: Union[str, list[str]],
    working_dir: Optional[Path] = None,
    additional_env: dict[str, str] = {},
    **kwargs: Any,  # https://github.com/python/mypy/issues/8772
) -> str:

    if working_dir is None:
        working_dir = Path(os.getcwd())
    env = os.environ.copy()
    env.update(additional_env)

    if isinstance(cmd, str):
        cmd = cmd.strip().split(" ")
    output = subprocess.run(
        cmd, cwd=str(working_dir), check=True, env=env, capture_output=True, **kwargs
    )

    res: str = output.stdout.decode("utf-8").strip()
    return res


def run_cmd_to_logfile(
    cmd: Union[str, list[str]],
    log_file: Optional[TextIO] = None,
    working_dir: Optional[Path] = None,
    additional_env: dict[str, str] = {},
) -> None:

    if working_dir is None:
        working_dir = Path(os.getcwd())
    env = os.environ.copy()
    env.update(additional_env)

    if isinstance(cmd, str):
        cmd = cmd.strip().split(" ")

    subprocess.run(
        cmd,
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
        exc_type: Optional[type[BaseException]],
        exc_value: Optional[BaseException],
        exc_traceback: Optional[TracebackType],
    ) -> None:
        if self.chdir:
            os.chdir(self.old_dir)
        tempfile.tempdir = None


class CompileError(Exception):
    """Exception raised when the compiler fails to compile something.

    There are two common reasons for this to appear:
    - Easy: The code file has is not present/disappeard.
    - Hard: Internal compiler errors.
    """

    pass


class CompileContext:
    def __init__(self, code: str):
        self.code = code
        self.fd_code: Optional[int] = None
        self.fd_asm: Optional[int] = None
        self.code_file: Optional[str] = None
        self.asm_file: Optional[str] = None

    def __enter__(self) -> tuple[str, str]:
        self.fd_code, self.code_file = tempfile.mkstemp(suffix=".c")
        self.fd_asm, self.asm_file = tempfile.mkstemp(suffix=".s")

        with open(self.code_file, "w") as f:
            f.write(self.code)

        return (self.code_file, self.asm_file)

    def __exit__(
        self,
        exc_type: Optional[type[BaseException]],
        exc_value: Optional[BaseException],
        exc_traceback: Optional[TracebackType],
    ) -> None:
        if self.code_file and self.fd_code and self.asm_file and self.fd_asm:
            os.remove(self.code_file)
            os.close(self.fd_code)
            # In case of a CompileError,
            # the file itself might not exist.
            if Path(self.asm_file).exists():
                os.remove(self.asm_file)
            os.close(self.fd_asm)
        else:
            raise CompileError("Compiler context exited but was not entered")


def get_asm_str(code: str, compiler: str, flags: list[str]) -> Optional[str]:
    """Get assembly of `code` compiled by `compiler` using `flags`.

    Args:
        code:  Code to compile to assembly
        compiler: Compiler to use
        flags: list of flags to use

    Returns:
        str: Assembly of `code`

    Raises:
        CompileError: Is raised when compilation failes i.e. has a non-zero exit code.
    """

    with CompileContext(code) as context_res:
        code_file, asm_file = context_res

        cmd = f"{compiler} -S {code_file} -o{asm_file}".split(" ") + flags
        try:
            run_cmd(cmd)
        except subprocess.CalledProcessError:
            raise CompileError()

        with open(asm_file, "r") as f:
            return f.read()


def save_to_tmp_file(content: str, suffix: Optional[str] = None) -> IO[bytes]:
    ntf = tempfile.NamedTemporaryFile(suffix=suffix)
    with open(ntf.name, "w") as f:
        f.write(content)

    return ntf


def create_compiler_settings(
    project: ccbuilder.CompilerProject,
    revs: list[ccbuilder.Revision],
    opt_levels: list[str],
    additional_flags: list[diopter.database.HashableStringList],
    repo: ccbuilder.Repo,
) -> list[diopter.database.CompilerSetting]:

    res: list[diopter.database.CompilerSetting] = []
    for rev in revs:
        commit = repo.rev_to_commit(rev)
        for opt in opt_levels:
            for add_flag in additional_flags:
                cpy = copy.deepcopy(add_flag)
                t = diopter.database.CompilerSetting(
                    compiler_name=project.to_string(),
                    rev=commit,
                    opt_level=opt,
                    additional_flags=cpy,
                )
                res.append(t)
    return res
