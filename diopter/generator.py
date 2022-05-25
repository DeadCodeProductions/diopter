import subprocess
import logging
from random import randint
from tempfile import NamedTemporaryFile
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Optional, Iterator
from concurrent.futures import ProcessPoolExecutor, as_completed
from multiprocessing import cpu_count

from diopter.sanitizer import sanitize_code as sanitize


class Generator:
    def __init__(self, minimum_length: int):
        self.minimum_length = minimum_length

    @abstractmethod
    def generate_file_impl(self) -> str:
        pass

    @abstractmethod
    def sanitize_code(self, code: str) -> bool:
        # TODO: the sanitizer should be configurable, e.g., only warnings + UB
        pass

    def generate_case(self) -> str:
        while True:
            code = self.generate_file_impl()
            if self.minimum_length and len(code) < self.minimum_length:
                continue
            if self.sanitize_code(code):
                return code
            logging.debug("Code not sanitizable")


class ParallelGenerator:
    def __init__(self, generator: Generator):
        """Args:
        generator: which Generator to use? E.g., CSmithGenerator
        """
        self.generator = generator

    def generate_cases(self, n: int, jobs: Optional[int] = None) -> Iterator[str]:
        """Args:
        n: how many cases to generate
        jobs: the number of concurrent jobs, if none cpu_count() will be used
        """
        with ProcessPoolExecutor(jobs if jobs else cpu_count()) as p:
            futures = (p.submit(self.generator.generate_case) for _ in range(n))
            for future in as_completed(futures):
                yield future.result()


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
    ):
        """Args:
        csmith (str): Path to executable or name in $PATH to csmith, if
        empty "csmith" will be used
        include_path (str): The csmith include path, if empty
        "/usr/include/csmith-2.3.0" will be used
        options_pool: csmith options that will be randomly selected, if
        empty default_options_pool will be used
        minimum_length: the minium length (characters) of a generated test
        case, smaller ones will be discarded
        """
        super().__init__(minimum_length)
        self.csmith = csmith if csmith else "csmith"
        self.options = (
            options_pool if options_pool else CSmithGenerator.default_options_pool
        )
        self.include_path = (
            include_path if include_path else "/usr/include/csmith-2.3.0"
        )

    def generate_file_impl(self) -> str:
        """Generate random code with csmith.

        Args:
            csmith (str): Path to executable or name in $PATH to csmith.

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

    def sanitize_code(self, code: str) -> bool:
        # TODO: don't hand-code the binary names
        return sanitize("gcc", "clang", "ccomp", code, f"-I {self.include_path}")
