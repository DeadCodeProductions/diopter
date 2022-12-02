import subprocess
from abc import ABC, abstractmethod
from concurrent.futures import Executor, ProcessPoolExecutor, as_completed
from multiprocessing import cpu_count
from random import randint
from typing import Iterator, Optional

from diopter.compiler import Language, SourceProgram
from diopter.sanitizer import Sanitizer


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
        self, n: int, e: Optional[Executor] = None, jobs: Optional[int] = None
    ) -> Iterator[SourceProgram]:
        """
        Args:
            n (int): how many cases to generate
            e (Optional[Executor]): executor used for running the code generation jobs
            jobs (Optional[int]):
                number of jobs, if None cpu_count() is used (ignored if e is not None)
        Returns:
            Iterator[SourceProgram]: the generated programs
        """

        def make_futures(e: Executor) -> Iterator[SourceProgram]:
            futures = (e.submit(self.generate_program) for _ in range(n))
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
        sanitizer: Sanitizer,
        csmith: Optional[str] = None,
        include_path: Optional[str] = None,
        options_pool: Optional[list[str]] = None,
        minimum_length: int = 10000,
        maximum_length: int = 50000,
    ):
        """
        Args:
            sanitizer (Sanitizer):
                used to sanitize and discard generated code
            csmith (Optional[str]):
                Path to csmith executable, if empty "csmith" will be used
            include_path (Optional[str]):
                csmith include path, if empty "/usr/include/csmith-2.3.0" will be used
            options_pool (Optional[list[str]]):
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
        # XXX: don't hardcode the path here
        self.include_path = (
            include_path if include_path else "/usr/include/csmith-2.3.0"
        )

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
            available_macros=(),
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
