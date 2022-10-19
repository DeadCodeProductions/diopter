import os
import subprocess
import logging
import tempfile
from pathlib import Path
from typing import Union, Optional, Any, TextIO, IO
from types import TracebackType


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

    res: str = (
        output.stdout.decode("utf-8").strip()
        + "\n"
        + output.stderr.decode("utf-8").strip()
    ).strip()
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


def save_to_tmp_file(content: str, suffix: Optional[str] = None) -> IO[bytes]:
    ntf = tempfile.NamedTemporaryFile(suffix=suffix)
    with open(ntf.name, "w") as f:
        f.write(content)

    return ntf
