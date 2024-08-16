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
from diopter.utils import TempDirEnv


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

    if Path("/usr/include/csmith.h").exists():
        return "/usr/include/"

    raise RuntimeError("Could not find csmith include path")


class CSmithGenerator(Generator):
    default_options_pool = [
        "arrays",
        "bitfields",
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
    ):
        """
        Args:
            sanitizer (Sanitizer):
                used to sanitize and discard generated code
            csmith (str | None):
                Path to csmith executable, if empty "csmith" will be used
            include_path (str | None):
                csmith include path, if empty "/usr/include/csmith-2.3.0" will be used
            options_pool (list[str] | None):
                csmith options that will be randomly selected,
                if empty default_options_pool will be used
            minimum_length (int):
                The minimum length of a generated test case in characters.
            maximum_length (int):
                The maximum length of a generated test case in characters.
        """
        super().__init__(sanitizer)
        self.minimum_length = minimum_length
        self.maximum_length = maximum_length
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
        if (
            len(program.code) < self.minimum_length
            or len(program.code) > self.maximum_length
        ):
            return False
        return bool(self.sanitizer.sanitize(program))


class YarpGen(Generator):
    def __init__(
        self,
        sanitizer: Sanitizer,
        yarpgen: str | None = None,
        language: Language = Language.C,
        additional_flags: tuple[str, ...] = (),
        minimum_length: int = 10000,
        maximum_length: int = 50000,
    ):
        """
        Args:
            sanitizer (Sanitizer):
                used to sanitize and discard generated code
            yarpgen (str | None):
                Path to yarpgen executable, if empty "csmith" will be used
            language (Language):
                The language of the generated code (--std flag).
            additional_flags (tuple[str, ...]):
                Additional flags to pass to yarpgen.
            minimum_length (int):
                The minimum length of a generated test case in characters.
            maximum_length (int):
                The maximum length of a generated test case in characters.
        """
        super().__init__(sanitizer)
        self.minimum_length = minimum_length
        self.maximum_length = maximum_length
        self.yarpgen = yarpgen if yarpgen else "yarpgen"
        self.language = language
        self.additional_flags = additional_flags

        if not which(self.yarpgen):
            raise ValueError(f"Invalid yarpgen executable: {self.yarpgen}")

    def generate_program_impl(self) -> SourceProgram:
        """Generate random code with yarpgen.

        Returns:
            SourceProgram: yarpgen generated program.
        """

        lang_flag = {
            Language.C: "--std=c",
            Language.CPP: "--std=c++",
        }[self.language]
        with TempDirEnv() as temp_dir:
            cmd = [self.yarpgen, lang_flag, "-o", str(temp_dir.resolve())] + list(
                self.additional_flags
            )
            for _ in range(100):
                result = subprocess.run(
                    cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT
                )
                if result.returncode == 0:
                    break
            assert result.returncode == 0, result.stdout.decode("utf-8")
            driver_str = (temp_dir / ("driver" + self.language.to_suffix())).read_text()
            func_str = (
                (temp_dir / ("func" + self.language.to_suffix()))
                .read_text()
                .replace('#include "init.h"', "")
            )

            return SourceProgram(
                code=driver_str + "\n" + func_str,
                language=self.language,
                defined_macros=(),
                include_paths=(),
                system_include_paths=(),
                flags=(),
            )

    def filter_program(self, program: SourceProgram) -> bool:
        if (
            len(program.code) < self.minimum_length
            or len(program.code) > self.maximum_length
        ):
            return False
        return bool(self.sanitizer.sanitize(program))
