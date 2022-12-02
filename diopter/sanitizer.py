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

import os
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from diopter.compiler import (
    CComp,
    CompilationSetting,
    CompileError,
    CompilerExe,
    OptLevel,
    SourceProgram,
)
from diopter.utils import TempDirEnv, run_cmd


@dataclass(frozen=True, kw_only=True)
class SanitizationResult:
    """Why did the sanitizer fail on a program?"""

    check_warnings_failed: bool = False
    ub_address_sanitizer_failed: bool = False
    ccomp_failed: bool = False
    timeout: bool = False

    def __bool__(self) -> bool:
        """True indicates that sanitization was successful"""
        return not (
            self.check_warnings_failed
            or self.ub_address_sanitizer_failed
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


class Sanitizer:
    """A wrapper of various sanitization methods.

    Sanitizer tests an input program using  various checks
    to rule of obvious ways a program can be broken:
    - compiler warnings
    - address and undefined behavior sanitizers
    - CompCert

    Attributes:
        gcc (CompilerExe):
            gcc used for checking compiler warnings
        clang (CompilerExe):
            clang used for checking compiler warnings and ub/address sanitizers result
        ccomp (Optional[CComp]):
            CompCert used for validating the program
        checked_warnings (Optional[tuple[str,...]]):
            the warnings whose presence to check
        use_ub_address_sanitizer (bool):
            whether Sanitizer.sanitize should use clang's ub and address sanitizers
        check_warnings_and_sanitizer_opt_level (OptLevel):
            optimization level used when checking for warnings and running sanitizers
        compilation_timeout (int):
            seconds to wait before aborting when compiling the program
        execution_timeout (int):
            seconds to wait before aborting when executing the program (ub/asan)
        ccomp_timeout  (int):
            seconds to wait before aborting when interpreting the program with ccomp
    """

    default_warnings = (
        "cast to smaller integer type",
        "conversions than data arguments",
        "incompatible redeclaration",
        "ordered comparison between pointer",
        "eliding middle term",
        "end of non-void function",
        "invalid in C99",
        "specifies type",
        "should return a value",
        "uninitialized",
        "incompatible pointer to",
        "incompatible integer to",
        "comparison of distinct pointer types",
        "type specifier missing",
        "uninitialized",
        "Wimplicit-int",
        "division by zero",
        "without a cast",
        "control reaches end",
        "return type defaults",
        "cast from pointer to integer",
        "useless type name in empty declaration",
        "no semicolon at end",
        "type defaults to",
        "too few arguments for format",
        "incompatible pointer",
        "ordered comparison of pointer with integer",
        "declaration does not declare anything",
        "expects type",
        "comparison of distinct pointer types",
        "pointer from integer",
        "incompatible implicit",
        "excess elements in struct initializer",
        "comparison between pointer and integer",
        "return type of ‘main’ is not ‘int’",
        "past the end of the array",
        "no return statement in function returning non-void",
    )

    def __init__(
        self,
        *,
        check_warnings: bool = True,
        use_ub_address_sanitizer: bool = True,
        use_ccomp_if_available: bool = True,
        gcc: Optional[CompilerExe] = None,
        clang: Optional[CompilerExe] = None,
        ccomp: Optional[CComp] = None,
        check_warnings_and_sanitizer_opt_level: OptLevel = OptLevel.O3,
        checked_warnings: Optional[tuple[str, ...]] = None,
        compilation_timeout: int = 8,
        execution_timeout: int = 4,
        ccomp_timeout: int = 16,
    ):
        """
        Args:
            check_warnings (bool):
                if True gcc's and clang's outputs will be used to
                filter out cases with Sanitizer.default_warnings
            use_ub_address_sanitizer (bool):
                whether to use clang's undefined behavior and address sanitizers
            use_ccomp_if_available (Optional[bool]):
                if ccomp should be used, if ccomp is not None this argument is ignored
            gcc (Optional[CompilerExe]):
                the gcc executable to use, if not provided
                CompilerExe.get_system_gcc will be used
            clang (Optional[CompilerExe]):
                the clang executable to use, if not provided
                CompilerExe.get_system_clang will be used
            ccomp (Optional[CComp]:
                the ccomp executable to use, if not provided and use_ccomp
                is True CComp.get_system_ccomp will be used if available
            check_warnings_and_sanitizer_opt_level (OptLevel):
                which optimization level to use when checking for compiler
                warnings and ub/address sanitizer issues
            checked_warnings (Optional[tuple[str,...]]):
                if not None implies check_warnings = True and will
                be used instead of Sanitizer.default_warnings
            compilation_timeout (int):
                after how many seconds to abort a compilation and fail
            execution_timeout (int):
                after how many seconds to abort an execution and fail
                (relevant for use_ub_sanitizer)
            ccomp_timeout (int):
                after how many seconds to abort interpreting with ccomp and fail
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
        self.check_warnings_and_sanitizer_opt_level = (
            check_warnings_and_sanitizer_opt_level
        )
        self.compilation_timeout = compilation_timeout
        self.execution_timeout = execution_timeout
        self.ccomp_timeout = ccomp_timeout

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
                result = comp.compile_program_to_object(
                    program,
                    Path("/dev/null"),
                    (
                        "-Wall",
                        "-Wextra",
                        "-Wpedantic",
                        "-Wno-builtin-declaration-mismatch",
                    ),
                    timeout=self.compilation_timeout,
                )
            except subprocess.TimeoutExpired:
                return SanitizationResult(timeout=True)
            except CompileError:
                return SanitizationResult(check_warnings_failed=True)
            for line in result.stdout_stderr_output.splitlines():
                for checked_warning in self.checked_warnings:
                    if checked_warning in line:
                        return SanitizationResult(check_warnings_failed=True)
            return SanitizationResult()

        with TempDirEnv():
            if not (
                gcc_result := check_warnings_impl(
                    CompilationSetting(
                        compiler=self.gcc,
                        opt_level=self.check_warnings_and_sanitizer_opt_level,
                    )
                )
            ):
                return gcc_result
            if not (
                clang_result := check_warnings_impl(
                    CompilationSetting(
                        compiler=self.clang,
                        opt_level=self.check_warnings_and_sanitizer_opt_level,
                    )
                )
            ):
                return clang_result

        return SanitizationResult()

    def check_for_ub_and_address_sanitizer_errors(
        self,
        program: SourceProgram,
    ) -> SanitizationResult:
        """Checks the program for UB and address sanitizer errors.

        Compiles program with self.clang and -fsanitize=undefined,address, then
        it runs the checked program and reports whether it failed (or timed out).

        Args:
            program (SourceProgram):
                The program to check.

        Returns:
            SanitizationResult:
                whether the program failed sanitization or not.
        """

        with TempDirEnv():
            exe = tempfile.NamedTemporaryFile(suffix=".exe", delete=False)
            exe.close()
            os.chmod(exe.name, 0o777)
            # Compile program with -fsanitize=...
            try:
                CompilationSetting(
                    compiler=self.clang,
                    opt_level=self.check_warnings_and_sanitizer_opt_level,
                ).compile_program_to_executable(
                    program,
                    Path(exe.name),
                    (
                        "-Wall",
                        "-Wextra",
                        "-Wpedantic",
                        "-Wno-builtin-declaration-mismatch",
                        "-fsanitize=undefined,address",
                    ),
                    timeout=self.compilation_timeout,
                )
            except subprocess.TimeoutExpired:
                return SanitizationResult(timeout=True)
            except CompileError:
                return SanitizationResult(ub_address_sanitizer_failed=True)

            # Run the instrumented binary
            try:
                run_cmd(exe.name, timeout=self.execution_timeout)
            except subprocess.TimeoutExpired:
                return SanitizationResult(timeout=True)
            except subprocess.CalledProcessError:
                return SanitizationResult(ub_address_sanitizer_failed=True)
            return SanitizationResult()

    def check_for_ccomp_errors(
        self, program: SourceProgram
    ) -> Optional[SanitizationResult]:
        """Checks the program with self.ccomp if available.

        Interprets program with self.ccomp if available and reports whether
        it failed (or timed out).

        Args:
            program (SourceProgram):
                The program to check.

        Returns:
            Optional[SanitizationResult]:
                if self.ccomp is not None, whether the program
                failed sanitization or not.
        """
        if not self.ccomp:
            return None
        with TempDirEnv():
            try:
                if not self.ccomp.check_program(program, timeout=self.ccomp_timeout):
                    return SanitizationResult(ccomp_failed=True)
            except subprocess.TimeoutExpired:
                return SanitizationResult(timeout=True)

            return SanitizationResult()

    def sanitize(self, program: SourceProgram) -> SanitizationResult:
        """Runs all the enabled sanitization checks.

        Runs all available sanitization checks based on self.checked_warnings,
        self.use_ub_address_sanitizer, and self.ccomp. It reports if any of them
        failed or if some check timed out.

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
            sanitizer_result := self.check_for_ub_and_address_sanitizer_errors(program)
        ):
            return sanitizer_result

        if self.ccomp and not (ccomp_result := self.check_for_ccomp_errors(program)):
            assert ccomp_result is not None
            return ccomp_result

        return SanitizationResult()
