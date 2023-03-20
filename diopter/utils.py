import os
import shlex
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from types import TracebackType
from typing import IO, Any, TextIO, Union


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
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
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
