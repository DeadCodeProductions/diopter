""" A sanitizer used to check programs for potential correctness issues

The following checks are currently supported: checking for compiler warnings,
checking a program with clang's undefined behaviour and address sanitizers,
checking a program with CompCert (ccomp).

Example:

program : SourceProgram = ...
sanitizer = Sanitizer()
if not sanitizer.sanitize(program):
    # the program is broken
"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path

from diopter.compiler import (
    CComp,
    CompilationSetting,
    CompileError,
    CompilerExe,
    ExeCompilationOutput,
    Language,
    ObjectCompilationOutput,
    OptLevel,
    SourceProgram,
)
from diopter.utils import TempDirEnv, run_cmd


@dataclass(frozen=True, kw_only=True)
class SanitizationResult:
    """Why did the sanitizer fail on a program?"""

    check_warnings_failed: bool = False
    sanitizer_failed: bool = False
    ccomp_failed: bool = False
    timeout: bool = False

    def __bool__(self) -> bool:
        """True indicates that sanitization was successful"""
        return not (
            self.check_warnings_failed
            or self.sanitizer_failed
            or self.ccomp_failed
            or self.timeout
        )

    def __eq__(self, other: object) -> bool:
        if isinstance(other, bool):
            return self.__bool__() == other
        if not isinstance(other, SanitizationResult):
            return NotImplemented
        return self == other

    def __ne__(self, other: object) -> bool:
        return not self.__eq__(other)


def supports_gnu2x(compiler: CompilerExe) -> bool:
    try:
        CompilationSetting(compiler=compiler, opt_level=OptLevel.O0).compile_program(
            SourceProgram(language=Language.C, code=""),
            ObjectCompilationOutput(Path("/dev/null")),
            additional_flags=("--std=gnu2x",),
        )
        return True
    except CompileError:
        return False


class Sanitizer:
    """A wrapper of various sanitization methods.

    Sanitizer tests an input program using  various checks
    to rule of obvious ways a program can be broken:
    - compiler warnings
    - address and undefined behavior sanitizers
    - memory sanitizer
    - CompCert

    Attributes:
        gcc (CompilerExe):
            gcc used for checking compiler warnings
        clang (CompilerExe):
            clang used for checking compiler warnings and ub/address sanitizers result
        ccomp (CComp | None):
            CompCert used for validating the program
        checked_warnings (tuple[str,...] | None):
            the warnings whose presence to check
        use_ub_address_sanitizer (bool):
            whether Sanitizer.sanitize should use clang's ub and address sanitizers
        use_memory_sanitizer (bool):
            whether Sanitizer.sanitize should use clang's memory sanitizer
        check_warnings_opt_level (OptLevel):
            optimization level used when checking for warnings
        sanitizer_opt_level (OptLevel):
            optimization level used when running sanitizers
        sanitizer_env_variables (dict[str, str]):
            environment variables for sanitizers
        use_gnu2x (bool):
            if True then gnu2x will be used when checking for compiler warnings
        compilation_timeout (int):
            seconds to wait before aborting when compiling the program
        execution_timeout (int):
            seconds to wait before aborting when executing the program (ub/asan)
        ccomp_timeout  (int):
            seconds to wait before aborting when interpreting the program with ccomp
        debug (bool):
            if True then additional info is printed when sanitizing programs
    """

    default_warnings = (
        "cast from pointer to integer",
        "cast to smaller integer type",
        "comparison between pointer and integer",
        # "comparison of distinct pointer types",
        "control reaches end",
        "conversions than data arguments",
        "declaration does not declare anything",
        "division by zero",
        "eliding middle term",
        "end of non-void function",
        "excess elements in struct initializer",
        "expects type",
        "incompatible implicit",
        "incompatible integer to",
        "incompatible pointer",
        "incompatible pointer to",
        "incompatible redeclaration",
        "invalid in C99",
        "no return statement in function returning non-void",
        "no semicolon at end",
        "ordered comparison between pointer",
        "ordered comparison of pointer with integer",
        "past the end of the array",
        "pointer from integer",
        "return type defaults",
        "return type of 'main' is not 'int'",
        "return type of ‘main’ is not ‘int’",
        "should return a value",
        "specifies type",
        "too few arguments for format",
        "type defaults to",
        "type specifier missing",
        "undefined behavior",
        "uninitialized",
        "useless type name in empty declaration",
        "Wimplicit-int",
        "without a cast",
    )

    def __init__(
        self,
        *,
        check_warnings: bool = True,
        use_ub_address_sanitizer: bool = True,
        use_memory_sanitizer: bool = False,
        use_ccomp_if_available: bool = True,
        gcc: CompilerExe | None = None,
        clang: CompilerExe | None = None,
        ccomp: CComp | None = None,
        check_warnings_opt_level: OptLevel = OptLevel.O3,
        sanitizer_opt_level: OptLevel = OptLevel.O0,
        sanitizer_env_variables: dict[str, str] = {
            "ASAN_OPTIONS": "detect_stack_use_after_return=1"
        },
        checked_warnings: tuple[str, ...] | None = None,
        use_gnu2x_if_available: bool = True,
        compilation_timeout: int = 8,
        execution_timeout: int = 4,
        ccomp_timeout: int = 16,
        debug: bool = False,
    ):
        """
        Args:
            check_warnings (bool):
                if True gcc's and clang's outputs will be used to
                filter out cases with Sanitizer.default_warnings
            use_ub_address_sanitizer (bool):
                whether to use clang's undefined behavior and address sanitizers
            use_memory_sanitizer (bool):
                whether to use clang's memory sanitizer
            use_ccomp_if_available (bool | None):
                if ccomp should be used, if ccomp is not None this argument is ignored
            gcc (CompilerExe | None):
                the gcc executable to use, if not provided
                CompilerExe.get_system_gcc will be used
            clang (CompilerExe | None):
                the clang executable to use, if not provided
                CompilerExe.get_system_clang will be used
            ccomp (CComp | None):
                the ccomp executable to use, if not provided and use_ccomp
                is True CComp.get_system_ccomp will be used if available
            check_warnings_opt_level (OptLevel):
                which optimization level to use when checking
                for compiler warnings
            sanitizer_opt_level (OptLevel):
                which optimization level to use when checking
                for ub/address sanitizer issues
            sanitizer_env_variables (dict[str,str]):
                environment variables to use when running sanitizers
            checked_warnings (tuple[str,...] | None):
                if not None implies check_warnings = True and will
                be used instead of Sanitizer.default_warnings
            use_gnu2x_if_available (bool):
                if True then gnu2x will be used if available
                when checking for compiler warnings
            compilation_timeout (int):
                after how many seconds to abort a compilation and fail
            execution_timeout (int):
                after how many seconds to abort an execution and fail
                (relevant for use_ub_sanitizer)
            ccomp_timeout (int):
                after how many seconds to abort interpreting with ccomp and fail
            debug (bool):
                if True then additional info is printed when sanitizing programs
        """
        self.gcc = gcc if gcc else CompilerExe.get_system_gcc()
        self.clang = clang if clang else CompilerExe.get_system_clang()
        self.ccomp = ccomp
        if use_ccomp_if_available and not self.ccomp:
            self.ccomp = CComp.get_system_ccomp()
        if checked_warnings:
            self.checked_warnings = checked_warnings
        elif check_warnings:
            self.checked_warnings = Sanitizer.default_warnings
        self.use_ub_address_sanitizer = use_ub_address_sanitizer
        self.use_memory_sanitizer = use_memory_sanitizer
        self.check_warnings_opt_level = check_warnings_opt_level
        self.sanitizer_opt_level = sanitizer_opt_level
        self.sanitizer_env_variables = sanitizer_env_variables
        self.compilation_timeout = compilation_timeout
        self.execution_timeout = execution_timeout
        self.ccomp_timeout = ccomp_timeout
        self.debug = debug
        self.use_gnu2x = (
            use_gnu2x_if_available
            and supports_gnu2x(self.clang)
            and supports_gnu2x(self.gcc)
        )

    def check_for_compiler_warnings(self, program: SourceProgram) -> SanitizationResult:
        """Checks the program for compiler warnings.

        Compiles program with self.gcc and self.clang and reports
        if any of self.checked_warnings is present in their outputs
        (or if the compilation timed out).

        Args:
            program (SourceProgram):
                The program to check.

        Returns:
            SanitizationResult:
                whether the program failed sanitization or not.
        """

        def check_warnings_impl(comp: CompilationSetting) -> SanitizationResult:
            try:
                result = comp.compile_program(
                    program,
                    ObjectCompilationOutput(Path("/dev/null")),
                    (
                        "-Wall",
                        "-Wextra",
                        "-Wpedantic",
                        "-Wno-builtin-declaration-mismatch",
                    )
                    + (
                        ("--std=gnu2x",)
                        if self.use_gnu2x and program.language == Language.C
                        else ()
                    ),
                    timeout=self.compilation_timeout,
                )
            except subprocess.TimeoutExpired:
                return SanitizationResult(timeout=True)
            except CompileError as e:
                if self.debug:
                    print(e)
                return SanitizationResult(check_warnings_failed=True)
            warnings: set[str] = set()
            for line in result.stdout_stderr_output.splitlines():
                for checked_warning in self.checked_warnings:
                    if checked_warning in line:
                        if self.debug:
                            warnings.add(checked_warning)
                        else:
                            return SanitizationResult(check_warnings_failed=True)
            if self.debug and warnings:
                print("Warnings found:", "|".join(warnings))
                return SanitizationResult(check_warnings_failed=True)
            return SanitizationResult()

        with TempDirEnv():
            if not (
                gcc_result := check_warnings_impl(
                    CompilationSetting(
                        compiler=self.gcc,
                        opt_level=self.check_warnings_opt_level,
                    )
                )
            ):
                return gcc_result
            if not (
                clang_result := check_warnings_impl(
                    CompilationSetting(
                        compiler=self.clang,
                        opt_level=self.check_warnings_opt_level,
                    )
                )
            ):
                return clang_result

        return SanitizationResult()

    def check_for_sanitizer_errors(
        self, program: SourceProgram, sanitizer_flag: str
    ) -> SanitizationResult:
        """Checks the program for UB, address, or memory sanitizer errors.

        Compiles program with self.clang and -fsanitize=undefined,address or
        -fsanitize=memory, then it runs the checked program and reports
        whether it failed (or timed out).

        Args:
            program (SourceProgram):
                The program to check.
            sanitizer_flag (str):
                the flag to pass to clang to enable the sanitizer
        Returns:
            SanitizationResult:
                whether the program failed sanitization or not.
        """

        with TempDirEnv():
            # Compile program with -fsanitize=...
            try:
                result = CompilationSetting(
                    compiler=self.clang,
                    opt_level=self.sanitizer_opt_level,
                ).compile_program(
                    program,
                    ExeCompilationOutput(None),
                    (
                        "-Wall",
                        "-Wextra",
                        "-Wpedantic",
                        "-Wno-builtin-declaration-mismatch",
                        "-fsanitize=" + sanitizer_flag,
                        "-fno-sanitize-recover=all",
                    ),
                    timeout=self.compilation_timeout,
                )
            except subprocess.TimeoutExpired:
                if self.debug:
                    print("Compilation timed out")
                return SanitizationResult(timeout=True)
            except CompileError as e:
                if self.debug:
                    print(e)
                return SanitizationResult(sanitizer_failed=True)

            # Run the instrumented binary
            try:
                run_cmd(
                    str(result.output.filename),
                    timeout=self.execution_timeout,
                    additional_env=self.sanitizer_env_variables,
                )
            except subprocess.TimeoutExpired:
                if self.debug:
                    print("Compilation timed out")
                return SanitizationResult(timeout=True)
            except subprocess.CalledProcessError as e:
                if self.debug:
                    print(e.stdout)
                    print(e.stderr)
                return SanitizationResult(sanitizer_failed=True)
            if self.debug:
                print("Sanitizer checks passed")
            return SanitizationResult()

    def check_for_ccomp_errors(
        self, program: SourceProgram
    ) -> SanitizationResult | None:
        """Checks the program with self.ccomp if available.

        Interprets program with self.ccomp if available and reports whether
        it failed (or timed out).

        Args:
            program (SourceProgram):
                The program to check.

        Returns:
            SanitizationResult | None:
                if self.ccomp is not None, whether the program
                failed sanitization or not.
        """
        if not self.ccomp:
            if self.debug:
                print("CComp not available, skipping")
            return None
        with TempDirEnv():
            try:
                if not self.ccomp.check_program(program, timeout=self.ccomp_timeout):
                    if self.debug:
                        print("CComp failed")
                    return SanitizationResult(ccomp_failed=True)
            except subprocess.TimeoutExpired:
                if self.debug:
                    print("CComp timed out")
                return SanitizationResult(timeout=True)

            return SanitizationResult()

    def sanitize(self, program: SourceProgram) -> SanitizationResult:
        """Runs all the enabled sanitization checks.

        Runs all available sanitization checks based on self.checked_warnings,
        self.use_ub_address_sanitizer, self.use_memory_sanitizer and self.ccomp.
        It reports if any of them failed or if some check timed out.

        Args:
            program (SourceProgram):
                The program to check.

        Returns:
            SanitizationResult:
                Whether the program failed sanitization or not.
        """

        if self.checked_warnings and not (
            check_warnings_result := self.check_for_compiler_warnings(program)
        ):
            return check_warnings_result

        if self.use_ub_address_sanitizer and not (
            sanitizer_result := self.check_for_sanitizer_errors(
                program, sanitizer_flag="undefined,address"
            )
        ):
            return sanitizer_result

        if self.use_memory_sanitizer and not (
            sanitizer_result := self.check_for_sanitizer_errors(
                program, sanitizer_flag="memory"
            )
        ):
            return sanitizer_result

        if self.ccomp and not (ccomp_result := self.check_for_ccomp_errors(program)):
            assert ccomp_result is not None
            return ccomp_result

        return SanitizationResult()
