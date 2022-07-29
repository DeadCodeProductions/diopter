import logging
import subprocess
from abc import ABC, abstractmethod
from concurrent.futures import ProcessPoolExecutor, as_completed, Executor
from multiprocessing import cpu_count
from pathlib import Path
from random import randint
from tempfile import NamedTemporaryFile
from typing import Iterator, Optional

from diopter.sanitizer import sanitize_code as sanitize


class Generator:
    @abstractmethod
    def generate_raw_code(self) -> str:
        pass

    @abstractmethod
    def filter_code(self, code: str) -> bool:
        # TODO: the sanitizer should be configurable, e.g., only warnings + UB
        pass

    def generate_code(self) -> str:
        while True:
            code = self.generate_raw_code()
            if self.filter_code(code):
                return code
            logging.debug("Code didn't pass the filter")

    def generate_code_parallel(
        self, n: int, e: Optional[Executor] = None, jobs: Optional[int] = None
    ) -> Iterator[str]:
        """Args:
        n: how many cases to generate
        e: the executor used for running the code generation jobs
        jobs: the number of concurrent jobs, if none cpu_count() will be used (ignored if e is not None)
        """

        def make_futures(e: Executor) -> Iterator[str]:
            futures = (e.submit(self.generate_code) for _ in range(n))
            for future in as_completed(futures):
                yield future.result()

        if e:
            yield from make_futures(e)
        else:
            with ProcessPoolExecutor(jobs if jobs else cpu_count()) as p:
                yield from make_futures(p)


class CSmithGenerator(Generator):
    default_options_pool = [
        "arrays",
        "bitfields",
        "checksum",
        "comma-operators",
        "compound-assignment",
        "consts",
        "divs",
        "embedded-assigns",
        "jumps",
        "longlong",
        "force-non-uniform-arrays",
        "math64",
        "muls",
        "packed-struct",
        "paranoid",
        "pointers",
        "structs",
        "inline-function",
        "return-structs",
        "arg-structs",
        "dangling-global-pointers",
    ]
    fixed_options = [
        "--no-unions",
        "--safe-math",
        "--no-argc",
        "--no-volatiles",
        "--no-volatile-pointers",
    ]

    def __init__(
        self,
        csmith: Optional[str] = None,
        include_path: Optional[str] = None,
        options_pool: Optional[list[str]] = None,
        minimum_length: int = 10000,
        maximum_length: int = 50000,
        clang: str = "clang",
        gcc: str = "gcc",
        ccomp: str = "ccomp",
    ):
        """
        Args:
            self:
            csmith (Optional[str]): Path to executable or name in $PATH to csmith, if
            empty "csmith" will be used
            include_path (Optional[str]): The csmith include path, if empty
            "/usr/include/csmith-2.3.0" will be used
            options_pool (Optional[list[str]]): csmith options that will be randomly selected, if
            empty default_options_pool will be used
            minimum_length (int): The minimum length of a generated test case in characters.
            maximum_length (int): The maximum length of a generated test case in characters.
            clang (str): Path to executable or name in $PATH to clang. Default: "clang".
            gcc (str): Path to executable or name in $PATH to gcc. Default: "gcc".
            ccomp (str): Path to executable or name in $PATH to compcert. Default: "ccomp".
        """
        self.minimum_length = minimum_length
        self.maximum_length = maximum_length
        self.clang = clang
        self.gcc = gcc
        self.ccomp = ccomp
        self.csmith = csmith if csmith else "csmith"
        self.options = (
            options_pool if options_pool else CSmithGenerator.default_options_pool
        )
        self.include_path = (
            include_path if include_path else "/usr/include/csmith-2.3.0"
        )

    def generate_raw_code(self) -> str:
        """Generate random code with csmith.

        Returns:
            str: csmith generated program.
        """

        cmd = [self.csmith] + CSmithGenerator.fixed_options
        for option in self.options:
            if randint(0, 1):
                cmd.append(f"--{option}")
            else:
                cmd.append(f"--no-{option}")
        result = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        assert result.returncode == 0
        return result.stdout.decode("utf-8")

    def filter_code(self, code: str) -> bool:
        if len(code) < self.minimum_length or len(code) > self.maximum_length:
            return False
        return sanitize(
            self.gcc, self.clang, self.ccomp, code, f"-I {self.include_path}"
        )
