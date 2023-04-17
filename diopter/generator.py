from __future__ import annotations

import subprocess
from abc import ABC, abstractmethod
from concurrent.futures import Executor
from itertools import repeat
from pathlib import Path
from random import randint
from shutil import which
from typing import Iterator

from diopter.compiler import Language, SourceProgram
from diopter.sanitizer import Sanitizer


def dummy_func(generator: Generator) -> SourceProgram:
    return generator.generate_program()


class Generator(ABC):
    def __init__(self, sanitizer: Sanitizer):
        self.sanitizer = sanitizer

    @abstractmethod
    def generate_program_impl(self) -> SourceProgram:
        """Concrete subclasses must implement this

        Returns:
            SourceProgram: generated program
        """
        pass

    @abstractmethod
    def filter_program(self, program: SourceProgram) -> bool:
        """Concrete subclasses must implement this to check if the generated
           program should be discared
        Args:
            program (SourceProgram): the program to check
        Returns:
            bool: if the program is good(sanitized)
        """
        pass

    def generate_program(self) -> SourceProgram:
        while True:
            program = self.generate_program_impl()
            if self.filter_program(program):
                return program

    def generate_programs_parallel(
        self, n: int, executor: Executor, chunksize: int = 10
    ) -> Iterator[SourceProgram]:
        """
        Generate programs in parallel. Yield futures wrapping the generation
        jobs.

        Example:
        with ProcessPoolExecutor(16) as executor:
            for fut in generator.generate_programs_parallel(100, executor):
                program = fut.result()

        Args:
            n (int):
                how many cases to generate
            executor (Executor):
                executor used for running the code generation jobs
        Returns:
            Iterator[SourceProgram]: the generated programs
        """
        return executor.map(dummy_func, repeat(self, n), chunksize=chunksize)


def find_csmith_include_path() -> str:
    """Find csmith include path.

    Returns:
        str: csmith include path
    """
    if Path("/usr/include/csmith-2.3.0").exists():
        return "/usr/include/csmith-2.3.0"

    if Path("/usr/include/csmith").exists():
        return "/usr/include/csmith"

    raise RuntimeError("Could not find csmith include path")


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
        sanitizer: Sanitizer,
        csmith: str | None = None,
        include_path: str | None = None,
        options_pool: list[str] | None = None,
        minimum_length: int = 10000,
        maximum_length: int = 50000,
        amount_statements: int | tuple[int, int] | None = None,
    ):
        """
        Args:
            sanitizer (Sanitizer):
                used to sanitize and discard generated code
            csmith (str | None):
                Path to csmith executable, if empty "csmith" will be used
            include_path (str | None):
                csmith include path, if empty "/usr/include/csmith-2.3.0" or
                "/usr/include/csmith" will be used, depending on which one exists
            options_pool (list[str] | None):
                csmith options that will be randomly selected,
                if empty default_options_pool will be used
            minimum_length (int):
                The minimum length of a generated test case in characters.
            maximum_length (int):
                The maximum length of a generated test case in characters.
            amount_statements (int | tuple[int, int] | None):
                Uses the `--stop-by-stmt` option of csmith to generate a program with
                approximately the given amount of statements. If None, the constraints
                from `minimum_length` and `maximum_length` are used.
                If `amount_statements` is set, `minimum_length` and `maximum_length` are
                ignored.
                If `amount_statements` is a tuple (a,b), a random amount of statements
                is chosen in the interval [a,b].
        """
        super().__init__(sanitizer)
        self.minimum_length = minimum_length
        self.maximum_length = maximum_length
        self.amount_statements = amount_statements
        self.csmith = csmith if csmith else "csmith"
        self.options = (
            options_pool if options_pool else CSmithGenerator.default_options_pool
        )
        self.include_path = include_path if include_path else find_csmith_include_path()

        if not Path(self.include_path).exists():
            raise ValueError(f"Invalid csmith include path: {self.include_path}")

        if not which(self.csmith):
            raise ValueError(f"Invalid csmith executable: {self.csmith}")

    def generate_program_impl(self) -> SourceProgram:
        """Generate random code with csmith.

        Returns:
            SourceProgram: csmith generated program.
        """

        cmd = [self.csmith] + CSmithGenerator.fixed_options
        if self.amount_statements:
            if isinstance(self.amount_statements, tuple):
                amount = randint(*self.amount_statements)
            else:
                amount = self.amount_statements
            cmd.append(f"--stop-by-stmt {amount}")

        for option in self.options:
            if randint(0, 1):
                cmd.append(f"--{option}")
            else:
                cmd.append(f"--no-{option}")
        result = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        assert result.returncode == 0
        return SourceProgram(
            code=result.stdout.decode("utf-8"),
            language=Language.C,
            defined_macros=(),
            include_paths=(),
            system_include_paths=(self.include_path,),
            flags=(),
        )

    def filter_program(self, program: SourceProgram) -> bool:
        if not self.amount_statements and (
            len(program.code) < self.minimum_length
            or len(program.code) > self.maximum_length
        ):
            return False
        return bool(self.sanitizer.sanitize(program))
