import subprocess
from abc import ABC, abstractmethod
from concurrent.futures import Executor, Future, wait
from random import randint
from typing import Iterator

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
        self, n: int, executor: Executor, max_parallel_jobs: int = 1024
    ) -> Iterator[Future[SourceProgram]]:
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
            max_parallel_jobs (int):
                Maximum number of jobs to be submitted concurrently. This
                is a workaround for deadlocking issues with ProcessPoolExecutor.
                If n > max_parallel_jobs then jobs will be submitted in chunks
                of max_parallel_jobs.
        Returns:
            Iterator[Future[SourceProgram]]: the generated program futures
        """
        remaining = n
        while True:
            futures = []
            for _ in range(min(max_parallel_jobs, remaining)):
                futures.append(executor.submit(self.generate_program))
                yield futures[-1]
            remaining -= len(futures)
            if not remaining:
                return
            wait(futures)


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
