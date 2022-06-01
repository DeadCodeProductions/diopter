import pickle
import inspect
import os
import subprocess
import logging
import shutil
from pathlib import Path
from sys import stderr
from typing import Callable, TextIO, Optional
from multiprocessing import cpu_count

from diopter.utils import run_cmd_to_logfile, TempDirEnv


class Reducer:
    """
    Reducer is a wrapper around CReduce
    """

    def __init__(self, creduce: Optional[str] = None):
        """
        Args:
            creduce: path to the creduce binary, if empty "creduce" will be
            used
        """
        self.creduce = creduce if creduce else "creduce"

    def reduce(
        self,
        code: str,
        interestingness_test: str,
        jobs: Optional[int] = None,
        log_file: Optional[TextIO] = None,
    ) -> Optional[str]:
        """
        Reduce given code

        Args:
            code: the code to reduce
            interestingness_test: the interestingness test script (can be generated with make_interestingness_check)
            jobs: The number of Creduce jobs, if empty cpu_count() will be
            log_file: Where to log Creduce's output, if empty stderr will be used

        Returns:
            Reduced code, if successful.
        """
        creduce_jobs = jobs if jobs else cpu_count()

        # creduce likes to kill unfinished processes with SIGKILL
        # so they can't clean up after themselves.
        # Setting a temporary temporary directory for creduce to be able to clean
        # up everything
        with TempDirEnv() as tmpdir:

            code_file = tmpdir / "code.c"
            with open(code_file, "w") as f:
                f.write(code)

            script_path = tmpdir / "check.py"
            with open(script_path, "w") as f:
                print(interestingness_test, file=f)
            os.chmod(script_path, 0o777)
            # run creduce
            creduce_cmd = [
                self.creduce,
                "--n",
                f"{creduce_jobs}",
                str(script_path.name),
                str(code_file.name),
            ]
            print(tmpdir)
            while True:
                pass

            try:
                run_cmd_to_logfile(
                    creduce_cmd,
                    log_file=log_file if log_file else stderr,
                    working_dir=Path(tmpdir),
                )
            except subprocess.CalledProcessError as e:
                logging.info(f"Failed to reduce code. Exception: {e}")
                return None

            with open(code_file, "r") as f:
                reduced_code = f.read()

            return reduced_code
