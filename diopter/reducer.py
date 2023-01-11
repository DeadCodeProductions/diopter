import inspect
import logging
import os
import pickle
import subprocess
import sys
from abc import ABC, abstractmethod
from dataclasses import replace
from multiprocessing import cpu_count
from pathlib import Path
from shutil import which
from sys import stderr
from typing import Optional, TextIO

from diopter.compiler import SourceProgram
from diopter.utils import TempDirEnv, run_cmd_to_logfile


class ReductionCallback(ABC):
    @abstractmethod
    def test(self, program: SourceProgram) -> bool:
        pass


def emit_module_imports(reduction_callback: ReductionCallback) -> str:
    """Generates all the necessary imports for the reduction script.

    Other than some stantand imports (e.g., pickle) it imports all the
    modules necessary to deserialize and run the `reduction_callback`
    """

    # Figure out the callback import:
    # from callback_module import callback_name
    callback_name = type(reduction_callback).__name__
    callback_module_path = inspect.getsourcefile(type(reduction_callback))
    assert callback_module_path
    callback_module = inspect.getmodulename(callback_module_path)

    # Also import all visible modules, this ensures that the callback
    # can be properly deserialized (pickle.load'ed) and run
    sys_path_append = "".join(f'\nsys.path.append("{p}")' for p in sys.path)

    return f"""import importlib
import pickle
import sys
from pathlib import Path
from dataclasses import replace
sys.path.insert(0, "{str(Path(callback_module_path).parent)}")
{sys_path_append}

from {callback_module} import {callback_name}
"""


def emit_call(
    reduction_callback: ReductionCallback, program: SourceProgram, code_filename: str
) -> str:
    """
    Emits the call in the reduction script.

    Serializes both the original program and the reduction call back in hex strings.
    These strings are embedded in the reduction script which pickle.load's them.

    Returns code that loads the callback and the program, reads the new code,
    and runs the callback on loaded program with the code replaced.
    """
    callback_in_hex = pickle.dumps(reduction_callback).hex()
    program_in_hex = pickle.dumps(program).hex()

    callback_load = f'callback = pickle.loads(bytes.fromhex("{callback_in_hex}"))'
    program_load = f'program = pickle.loads(bytes.fromhex("{program_in_hex}"))'

    call = "exit(not callback.test(program))"

    return f"""with open(\"{code_filename}\", \"r\") as f:
    code = f.read()
{program_load}
program = replace(program, code=code)
{callback_load}
{call}
    """


def make_interestingness_script(
    reduction_callback: ReductionCallback, program: SourceProgram, code_filename: str
) -> str:
    """
    Helper function to create a script useful for use with diopter.Reducer.
    It serializes the reduction callback into a script that checks if the code in
    code_filename is still interesting

    Args:
        reduction_callback:
            callback that will be serialized stored as a runnable script
        program:
            the original program
        code_filename:
            file that the generated script will check everytime it is run

    Returns:
        The python3 script (str)
    """
    prologue = f"#!{sys.executable}"
    return "\n".join(
        (
            prologue,
            emit_module_imports(reduction_callback),
            emit_call(reduction_callback, program, code_filename),
        )
    )


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
        assert which(self.creduce), f"{self.creduce} is not executable"

    def reduce(
        self,
        program: SourceProgram,
        interestingness_test: ReductionCallback,
        jobs: Optional[int] = None,
        log_file: Optional[TextIO] = None,
        debug: bool = False,
    ) -> Optional[SourceProgram]:
        """
        Reduce given code

        Args:
            program:
                the program to reduce
            interestingness_test:
                a concrete ReductionCallback that implementes the interestingness
                (can be generated with make_interestingness_check).
            jobs:
                The number of Creduce jobs, if empty cpu_count() will be
            log_file:
                Where to log Creduce's output, if empty stderr will be used
            debug:
                Whether to pass the debug flag to creduce

        Returns:
            Reduced program, if successful.
        """
        creduce_jobs = jobs if jobs else cpu_count()

        code_filename = "code" + program.language.to_suffix()

        interestingness_script = make_interestingness_script(
            interestingness_test, program, code_filename
        )

        # creduce likes to kill unfinished processes with SIGKILL
        # so they can't clean up after themselves.
        # Setting a temporary temporary directory for creduce to be able to clean
        # up everything
        with TempDirEnv() as tmpdir:

            code_file = tmpdir / code_filename
            with open(code_file, "w") as f:
                f.write(program.code)

            script_path = tmpdir / "check.py"
            with open(script_path, "w") as f:
                print(interestingness_script, file=f)
            os.chmod(script_path, 0o770)
            # run creduce
            creduce_cmd = [
                self.creduce,
                "--n",
                f"{creduce_jobs}",
                str(script_path.name),
                str(code_file.name),
            ]
            if debug:
                creduce_cmd.append("--debug")

            try:
                run_cmd_to_logfile(
                    creduce_cmd,
                    log_file=log_file if log_file else stderr,
                    working_dir=Path(tmpdir),
                    additional_env={"TMPDIR": str(tmpdir.absolute())},
                )
            except subprocess.CalledProcessError as e:
                logging.info(f"Failed to reduce code. Exception: {e}")
                return None

            with open(code_file, "r") as f:
                reduced_code = f.read()

            return replace(program, code=reduced_code)
