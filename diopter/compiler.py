""" Python wrapper for running a compiler

Important classes:
    - `SourceProgram`: represents a C or C++ program together with additional
      info (flags, macro definitions, includ paths) that can be compiled.
    - `CompilerExe`: a compiler executable (e.g., "gcc", "/usr/bin/clang-14", etc)
    - `CompilationOutput`: the output of a compiler invocation, e.g., an object file
    - `CompilationSetting`: a CompilerExe together with an optimization level and
      additional flags used to compile `SourceProgram`s. Can be parsed from a
      string, "gcc -O3 test.c -o test.o -MACRO1=foo -fomit-frame-pointer"  with
      `parse_compilation_setting_from_string`

Example:
from pathlib import Path
from diopter.compiler import (
    CompilationSetting,
    CompilerExe,
    CompilerProject,
    ExeCompilationOutput,
    Language,
    OptLevel,
    SourceProgram,
)
input_code = \"\"\"
             #include <stdio.h>
             void foo(int argc){
                 printf("%d \\n", argc);
             }
             int main(int argc, char* argv[]){
                 foo(argc);
             }
\"\"\"
# Create a program
program = SourceProgram(code=input_code, language=Language.C)
# Get the system gcc compiler
compiler = CompilerExe(CompilerProject.GCC, Path("gcc"), "")
# Create a compilation setting
cs = CompilationSetting(compiler=compiler, opt_level=OptLevel.O2)
# Compile the program to an executable
res = cs.compile_program( program, ExeCompilationOutput())
# Run the program
output = res.output.run()
# The output should be 1 (argc is 1 if no flags a passed)
assert output.stdout.strip() == "1"
# Run the program with one flag
output = res.output.run(("-flag",))
# The output should be 2
assert output.stdout.strip() == "2"
"""
from __future__ import annotations

import argparse
import os
import re
import subprocess
import tempfile
from abc import ABC, abstractmethod
from dataclasses import dataclass, replace
from enum import Enum
from itertools import chain
from pathlib import Path
from shutil import which
from subprocess import Popen
from typing import IO, Any, Generic, Sequence, TypeVar

from diopter.utils import CommandOutput, run_cmd, run_cmd_async, temporary_file


class Language(Enum):
    """An enum denoting the source language of a program.
    C and C++ are the two options.
    """

    C = 0
    CPP = 1

    def get_language_flag(self) -> str:
        """Returns the appriopriate flag to instruct the compiler driver
        (gcc/clang) to treat the input file's language correctly.

        Returns:
            str:
                -xc or -xc++
        """
        match self:
            case Language.C:
                return "-xc"
            case Language.CPP:
                return "-xc++"

    def get_linker_flag(self) -> str | None:
        """Returns the appriopriate linker flag if this is a c++
        language object such that the standard library is property linked.

        Returns:
            str | None:
                the flag or nothing
        """
        match self:
            case Language.C:
                return None
            case Language.CPP:
                return "-lstdc++"

    def to_suffix(self) -> str:
        """Returns a corresponding file suffix for the language.

        Returns:
            str:
                file suffix
        """
        match self:
            case Language.C:
                return ".c"
            case Language.CPP:
                return ".cpp"


@dataclass(frozen=True)
class SourcePath:
    filename: Path
    tempfile: IO[bytes] | None

    def __del__(self) -> None:
        """Delete the temporary file if it still exists"""
        if self.tempfile is None:
            return
        if Path(self.filename).exists():
            os.remove(self.filename)


@dataclass(frozen=True, kw_only=True)
class Source(ABC):
    """A C or C++ base class for source programs together
       with flags, includes and macro definitions.

    Attributes:
        code (str):
            the source code
        language (Language):
            the program's language
        defined_macros (tuple[str,...]):
            macros that will be defined when compiling this program
        include_paths (tuple[str,...]):
            include paths which will be passed to the compiler (with -I)
        system_include_paths (tuple[str,...]):
            system include paths which will be passed to the compiler (with -isystem)
        flags (tuple[str,...]):
            flags, prefixed with a dash ("-") that will be passed to the compiler
    """

    language: Language
    defined_macros: tuple[str, ...] = tuple()
    include_paths: tuple[str, ...] = tuple()
    system_include_paths: tuple[str, ...] = tuple()
    flags: tuple[str, ...] = tuple()

    def __post_init__(self) -> None:
        """Sanity checks"""

        for macro in self.defined_macros:
            assert not macro.strip().startswith("-D")

        # (system) include paths must actually by paths and not include a flag
        for path in self.include_paths:
            assert not path.strip().startswith("-I")
        for path in self.system_include_paths:
            assert not path.strip().startswith("-isystem")

        # XXX: can't check flags as the args and flags may be split

    def get_compilation_flags(self) -> tuple[str, ...]:
        """Returns flags based on the program's flags, include paths and macro defs.

        Returns:
            tuple[str, ...]:
                the flags
        """

        return tuple(
            chain(
                self.flags,
                (f"-D{m}" for m in self.defined_macros),
                (f"-I{i}" for i in self.include_paths),
                (f"-isystem{i}" for i in self.system_include_paths),
            )
        )

    def get_file_suffix(self) -> str:
        """Returns a corresponding file suffix for this program.

        Returns:
            str:
                file suffix
        """

        return self.language.to_suffix()

    @abstractmethod
    def get_filename(self) -> SourcePath:
        pass


ProgramType = TypeVar("ProgramType", bound="SourceProgram")


@dataclass(frozen=True, kw_only=True)
class SourceProgram(Source):
    """A C or C++ source program together with flags, includes and macro definitions.

    Attributes:
        code (str):
            the source code
        language (Language):
            the program's language
        defined_macros (tuple[str,...]):
            macros that will be defined when compiling this program
        include_paths (tuple[str,...]):
            include paths which will be passed to the compiler (with -I)
        system_include_paths (tuple[str,...]):
            system include paths which will be passed to the compiler (with -isystem)
        flags (tuple[str,...]):
            flags, prefixed with a dash ("-") that will be passed to the compiler
    """

    code: str

    def get_filename(self) -> SourcePath:
        tf = temporary_file(
            contents=self.get_modified_code(),
            suffix=self.get_file_suffix(),
            delete=False,
        )
        tf.close()
        return SourcePath(Path(tf.name), tf)

    def get_modified_code(self) -> str:
        """Returns `self.code` potentially modified to be used in `CompilationSetting`.

        Subclasses of `SourceProgram` can override this method.

        Returns:
            str:
                the (modified) `self.code`
        """
        return self.code

    def with_preprocessed_code(
        self: ProgramType, preprocessed_code: str
    ) -> ProgramType:
        """Returns a new program with its code replaced with `preprocessed_code`

        `CompilerSetting.preprocess_program` calls this. It can be overriden by
        subclasses.

        Returns:
            ProgramType:
                the new program
        """
        return replace(
            self,
            code=preprocessed_code,
            defined_macros=tuple(),
            include_paths=tuple(),
            system_include_paths=tuple(),
        )

    def with_code(self: ProgramType, new_code: str) -> ProgramType:
        """Returns a new program with its code replaced with new_code

        Returns:
            ProgramType:
                the new program
        """
        return replace(self, code=new_code)


@dataclass(frozen=True, kw_only=True)
class SourceFile(Source):
    """A C or C++ source file together with flags, includes and macro definitions.

    Attributes:
        path (str):
            the path to the source file (this or code must be set)
        language (Language):
            the program's language
        defined_macros (tuple[str,...]):
            macros that will be defined when compiling this program
        include_paths (tuple[str,...]):
            include paths which will be passed to the compiler (with -I)
        system_include_paths (tuple[str,...]):
            system include paths which will be passed to the compiler (with -isystem)
        flags (tuple[str,...]):
            flags, prefixed with a dash ("-") that will be passed to the compiler
    """

    filename: Path

    def __post_init__(self) -> None:
        super().__post_init__()
        # TODO: fix testing and re-enable the assertion
        # assert self.filename.is_file()

    def get_filename(self) -> SourcePath:
        return SourcePath(self.filename, None)


Revision = str


def parse_compiler(compiler_exe: Path) -> tuple[CompilerProject, Revision] | None:
    """Tries to find the compiler project parse the revision
    of the given executable (clang/gcc).

    Args:
        compiler_exe (Path): a path to the compiler executable

    Returns:
        (CompilerProject, Revision) | None :
            compiler project (LLVM or GCC)  and the parsed version, None if
            the parsing failed
    """
    info = run_cmd(f"{str(compiler_exe)} -v".split())
    for line in info.stderr.splitlines():
        if "clang version" in line:
            return CompilerProject.LLVM, line[len("clang version") :].strip()
        if "gcc version" in line:
            return CompilerProject.GCC, line[len("gcc version") :].strip().split()[0]
    return None


class CompilerProject(Enum):
    GCC = 0
    LLVM = 1

    def to_string(self) -> str:
        return "gcc" if self == CompilerProject.GCC else "clang"


@dataclass(frozen=True)
class CompilerExe:
    """A compiler executable (gcc/clang).

    Attributes:
        project (CompilerProject): is this GCC or LLVM?
        exe (Path): the path to the executable
        revision (Revision): the compiler revision/version
    """

    project: CompilerProject
    exe: Path
    revision: Revision

    def get_verbose_info(self) -> str:
        """Returns:
        str:
            the output of exe -v
        """
        return run_cmd(f"{self.exe} -v".split()).stderr

    @staticmethod
    def get_system_gcc() -> CompilerExe:
        """Returns:
        CompilerExe:
            the system's gcc compiler
        """
        gcc = which("gcc")
        assert gcc, "gcc is not in PATH"
        gcc_path = Path(gcc)
        project_revision = parse_compiler(gcc_path)
        assert project_revision is not None
        return CompilerExe(CompilerProject.GCC, gcc_path, project_revision[1])

    @staticmethod
    def get_system_clang() -> CompilerExe:
        """Returns:
        CompilerExe:
            the system's clang compiler
        """
        clang = which("clang")
        assert clang, "clang is not in PATH"
        clang_path = Path(clang)
        project_revision = parse_compiler(clang_path)
        assert project_revision is not None
        return CompilerExe(CompilerProject.LLVM, clang_path, project_revision[1])

    @staticmethod
    def from_path(cc: Path) -> CompilerExe:
        project_revision = parse_compiler(cc)
        assert project_revision
        return CompilerExe(project_revision[0], cc, project_revision[1])


class OptLevel(Enum):
    """Optimization Levels supported by gcc and clang"""

    O0 = 0
    O1 = 1
    O2 = 2
    O3 = 3
    Os = 4
    Oz = 5

    @staticmethod
    def from_str(s: str) -> OptLevel:
        """ "Convertion from string

        Args:
            s (str):
                the optimization level string

        Returns:
            OptLevel:
                the conversion result
        """

        match s:
            case "O0" | "0":
                return OptLevel.O0
            case "O1" | "1":
                return OptLevel.O1
            case "O2" | "2":
                return OptLevel.O2
            case "O3" | "3":
                return OptLevel.O3
            case "Os" | "s":
                return OptLevel.Os
            case "Oz" | "z":
                return OptLevel.Oz

        raise ValueError(f"{s} is not a valid optimization level")


class CompileError(Exception):
    """Exception raised when the compiler fails to compile something.

    There are two common reasons for this to appear:
    - Easy: The code file has is not present/disappeard.
    - Hard: Internal compiler errors.
    """

    @staticmethod
    def from_called_process_exception(
        cmd: str,
        e: subprocess.CalledProcessError,
    ) -> CompileError:
        """Convertion from a CalledProcessError

        Args:
            e (CalledProcessError):
                the exception raised by subprocess.run

        Returns:
            CompileError:
                error containing the stdout and stderr of the compiler invocation
        """

        output = cmd
        if e.stdout:
            output += "\nSTDOUT====\n" + e.stdout.decode("utf-8")
        if e.stderr:
            output += "\nSTDERR====\n" + e.stderr.decode("utf-8")
        return CompileError(output)


class CompilationOutput(ABC):
    """Represents the output of a compiler invocation,e.g.,
    an Object file, an Executable, assembly code, etc.

    Subclasses of CompilationOutput are used to specify what kind of output is
    desired in `CompilationResult.compile_program`.

    Attributes:
        filename (Path):
            the output filename that will be passed as `-o filename` to the
            compiler invocation, if not specified a temporary file will be
            created.
        temporary_file (tempfile.NamedTemporaryFile):
            a temporary file where the output will be writen, if no filename
            is specified when creating the CompilationOutput object

    """

    def __init__(self, filename: Path | None = None) -> None:
        """Create a compilation output, either using the specified path or with
        a temporary file. The temporary file is automatically removed with the
        CompilationOutput object is garbage collected.

        Args:
            filename (Path | None):
                where to write the compilation output if not None
        """

        if filename:
            self.filename_ = filename
            self.temporary_file = None
        else:
            self.temporary_file = tempfile.NamedTemporaryFile(
                suffix=type(self).suffix(), delete=False
            )
            self.temporary_file.close()
            self.filename_ = Path(self.temporary_file.name)

    @property
    def filename(self) -> Path:
        return self.filename_

    def __del__(self) -> None:
        """Delete the temporary file if one was created and still exists"""
        if self.temporary_file is None:
            return
        if Path(self.filename).exists():
            os.remove(self.filename)

    def to_cmd(self) -> str:
        """Create the relevant compilation flags for this output.

        Used in CompilationSetting.get_compilation_cmd.

        Returns:
            str:
                the necessary compilation flags, e.g., "-c -o filename.o"
        """
        if type(self).empty_command():
            return ""
        return type(self).flag() + " -o " + str(self.filename)

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, CompilationOutput):
            raise NotImplementedError
        return (
            type(self) == type(other)
            and self.filename == other.filename
            and self.temporary_file == other.temporary_file
        )

    @staticmethod
    @abstractmethod
    def flag() -> str:
        """Return the relevant flag for this output.

        E.g., for object outputs it should be "-c"

        Subclasses of CompilationOutput should implement this method.

        Returns:
            str:
                the compiler flag for this kind of output
        """
        raise NotImplementedError

    @staticmethod
    @abstractmethod
    def suffix() -> str:
        """Return the relevant filename suffix for this output.

        E.g., for object outputs it should be ".o"

        Subclasses of CompilationOutput should implement this method.

        Returns:
            str:
                the filename output for the compilation output
        """

        raise NotImplementedError

    @staticmethod
    def empty_command() -> bool:
        """Whether this kind of output should not include any compiler flags.

        Subclasses of CompilationOutput can override this method.

        Currently only relevant to NoCompilationOutput.

        Returns:
            bool:
                if this compilation output kind should not inlcude any flags
        """
        return False


class BinaryOutputMixin(ABC):
    """Mixin for binary compilation outputs adding utility methods."""

    @property
    @abstractmethod
    def filename(self) -> Path:
        raise NotImplementedError

    def strip_symbols(self) -> None:
        """Runs the strip utility on the output, this the program's removes
        symbols.

        Useful, e.g., for comparing whether two outputs are equal.
        """
        run_cmd(f"strip {self.filename}")

    def read(self) -> bytes:
        """Read the output.

        Returns:
            bytes:
                The binary's contents.
        """

        with open(str(self.filename), "rb") as f:
            return f.read()

    def text_size(self) -> int:
        """Return the text section size of the binary.

        Returns:
            int:
                The binary's text section size.
        """
        size_cmd_output = run_cmd(f"size {self.filename}").stdout
        line = list(size_cmd_output.splitlines())[-1].strip()
        s = line.split()[0]
        return int(s)


class ExeCompilationOutput(CompilationOutput, BinaryOutputMixin):
    """An executable compilation output.

    Attributes: (see `CompilationOutput`)
    """

    def __init__(self, filename: Path | None = None) -> None:
        """Create an ExeCompilationOutput and set the correct permissions
        if a temporary file is created such that it is executable.
        """
        super().__init__(filename)
        if self.temporary_file is not None:
            os.chmod(self.filename, 0o777)
        else:
            # check for permissions if the file exists?
            pass

    def run(
        self, flags: tuple[str, ...] = tuple(), timeout: int | None = None
    ) -> CommandOutput:
        """Runs the exe with the provided flags.

        Args:
            flags (tuple[str]):
                flags passed to the exe
            timeout (int | None):
                if not None, the execution will abort after `timeout` seconds
        Returns:
            CommandOutput:
                the captured stdout and stderr
        """
        return run_cmd(f"{self.filename} {' '.join(flags)}", timeout=timeout)

    @staticmethod
    def flag() -> str:
        return ""

    @staticmethod
    def suffix() -> str:
        return ".exe"


class ObjectCompilationOutput(CompilationOutput, BinaryOutputMixin):
    """An object file compilation output.

    Attributes: (see `CompilationOutput`)
    """

    @staticmethod
    def flag() -> str:
        return "-c"

    @staticmethod
    def suffix() -> str:
        return ".o"


class ASMCompilationOutput(CompilationOutput):
    """An assembly file compilation output.

    Attributes: (see `CompilationOutput`)
    """

    @staticmethod
    def flag() -> str:
        return "-S"

    @staticmethod
    def suffix() -> str:
        return ".s"

    def read(self) -> str:
        """Read the assembly code.

        Returns:
            str:
                the assembly code read from the output file
        """
        with open(str(self.filename), "r") as f:
            return f.read()


class LLVMIRCompilationOutput(CompilationOutput):
    """An LLVM IR file compilation output.

    Attributes: (see `CompilationOutput`)
    """

    @staticmethod
    def flag() -> str:
        return "-S -emit-llvm"

    @staticmethod
    def suffix() -> str:
        return ".ll"

    def read(self) -> str:
        """Read the LLVM IR.

        Returns:
            str:
                the LLVM IR read from the output file
        """
        with open(str(self.filename), "r") as f:
            return f.read()


class NoCompilationOutput(CompilationOutput):
    """No compilation output.

    Used in `parse_compilation_setting_from_string`.
    """

    def __init__(self) -> None:
        super().__init__(Path(""))

    @staticmethod
    def flag() -> str:
        return ""

    @staticmethod
    def suffix() -> str:
        return ""

    @staticmethod
    def empty_command() -> bool:
        return True


CompilationOutputType = TypeVar("CompilationOutputType", bound=CompilationOutput)


@dataclass(frozen=True, kw_only=True)
class CompilationResult(Generic[CompilationOutputType]):
    """A compilation result

    Attributes:
        source_file (Path):
            the (temporary) source file used by the compiler
        output (CompilationOutputType):
            the output of the compiler, e.g., an executable (ExeCompilationOutput)
        stdout_stderr_output (str):
            the captured stdout and stderr
    """

    source_file: Path
    output: CompilationOutputType
    stdout_stderr_output: str


@dataclass(frozen=True)
class AsyncCompilationResult(Generic[CompilationOutputType]):
    """A wrapper over a pending `CompilationResult`
    from a compiler that is running in a subprocess.

    Returned by CompilationSetting.compile_program_async

    Attributes:
        cmd (str):
            the compiler command that is running in the subprocess
        proc (Popen[Any]):
            the running subprocess
        code_file (SourcePath | None):
            the source used to compile the program if it exists
        output (CompilationOutputType):
            the pending compilation output
    """

    cmd: str
    proc: Popen[Any]
    code_file: SourcePath | None
    output: CompilationOutputType

    def result(
        self, timeout: int | None = None
    ) -> CompilationResult[CompilationOutputType]:
        """Waits for the subprocess to finish
        and returns the compilation output.

        Args:
            timeout (int | None):
                if not None, how many seconds to wait before
                raising a subprocess.TimeoutExpired

        Returns:
            CompilationOutputType:
                the compilation output
        """
        outs, errs = self.proc.communicate(timeout=timeout)
        assert isinstance(outs, str)
        assert isinstance(errs, str)

        if self.proc.returncode != 0:
            output = self.cmd
            if outs:
                output += "\nSTDOUT====\n" + outs
            if errs:
                output += "\nSTDERR====\n" + errs
            raise CompileError(output)

        return CompilationResult(
            source_file=Path(
                self.code_file.filename if self.code_file is not None else ""
            ),
            output=self.output,
            stdout_stderr_output=outs + "\n" + errs,
        )

    def wait(self, timeout: int | None = None) -> None:
        """Waits for the subprocess to finish.

        Args:
            timeout (int | None):
                if not None, how many seconds to wait before
                raising a subprocess.TimeoutExpired
        """
        self.proc.wait(timeout)

    def __del__(self) -> None:
        if not self.proc.returncode:
            self.proc.kill()


@dataclass(frozen=True, kw_only=True)
class CompilationSetting:
    """
    A compilation setting that can be used to compile source programs

    Attributes:
        compiler (CompilerExe):
            the compiler used to compile inputs
        opt_level (OptLevel):
            which optimization level to use
        flags (tuple[str,...]):
            which flags to use when compiling programs including "dashes" and
            arguments, e.g., flags = ("-XX", "--foo", "bar")
        include_paths (tuple[str,...]):
            which include paths to pass to the compiler (passed to the compiler
            with -I), e.g., include_paths=tuple("/path/1", "path/2",...)
        system_include_path (tuple[str,...]):
            which system include paths to pass to the compiler
            (passed to the compiler with -isystem) with -I),
            e.g., include_paths=tuple("/path/1", "path/2",...)
        macro_definitions (tuple[str,...]):
            which macro definition to pass to the compiler,
            without the -D prefix, e.g., macros_defintions = tuple("MACRO1",
            "MACROWITHARG=1", "MACROWITHARGUMENT=2")
    """

    compiler: CompilerExe
    opt_level: OptLevel
    flags: tuple[str, ...] = tuple()
    include_paths: tuple[str, ...] = tuple()
    system_include_paths: tuple[str, ...] = tuple()
    macro_definitions: tuple[str, ...] = tuple()
    # TODO: timeout_s: int = 8

    def __post_init__(self) -> None:
        """Sanity checks"""

        # macros should not include "-D"
        for macro in self.macro_definitions:
            assert not macro.strip().startswith("-D")

        # (system) include paths must actually by paths and not include a flag
        for path in self.include_paths:
            assert not path.strip().startswith("-I")
        for path in self.system_include_paths:
            assert not path.strip().startswith("-isystem")

        # XXX: can't check flags as the args and flags may be split

    def get_compilation_cmd(
        self,
        program: tuple[Source, Path],
        output: CompilationOutput,
        include_language_flags: bool = True,
    ) -> list[str]:
        """Assembles a compilation invocation based on the
        input programs and the output.

        Args:
            program (tuple[Source, Path]):
                flags from the program are extracted and
                the corresponding path are included in the output
            output (CompilationOutput):
                the ouput of the compilation
            include_language_flags (bool):
                whether to include additional flags that specify
                the source language and relevant linker flags
        Returns:
            str:
                The assembled compilation command
        """
        cmd = list(
            chain(
                (
                    str(self.compiler.exe),
                    f"-{self.opt_level.name}",
                ),
                (program[0].language.get_language_flag(),)
                if include_language_flags
                else ("",),
                self.flags,
                (f"-I{path}" for path in self.include_paths),
                (f"-isystem{path}" for path in self.system_include_paths),
                (f"-D{macro}" for macro in self.macro_definitions),
                program[0].get_compilation_flags(),
                (str(program[1]),),
            )
        )

        if include_language_flags and isinstance(output, ExeCompilationOutput):
            if linker_flag := program[0].language.get_linker_flag():
                cmd.append(linker_flag)
        cmd.append(output.to_cmd())
        return cmd

    def compile_program(
        self,
        program: Source,
        output: CompilationOutputType,
        additional_flags: tuple[str, ...] = tuple(),
        timeout: int | None = None,
    ) -> CompilationResult[CompilationOutputType]:
        """Compile a program with this setting.

        Args:
            program (Source):
                input program
            output (CompilationOutputType):
                the desired output, e.g., executable or object file
            additional_flags (tuple[str, ...]):
                additional flags used for the compilation
            timeout (int | None):
                timeout in seconds for the compilation command

        Returns:
            CompilationResult[CompilationOutputType]:
                The result of the compilation (if successful).
        """

        code_file = program.get_filename()

        cmd = self.get_compilation_cmd(
            (program, Path(code_file.filename)), output, True
        ) + list(additional_flags)
        try:
            command_output = run_cmd(
                cmd,
                timeout=timeout,
                additional_env={"TMPDIR": tempfile.gettempdir()},
            )
        except subprocess.CalledProcessError as e:
            raise CompileError.from_called_process_exception(" ".join(cmd), e)
        return CompilationResult(
            source_file=code_file.filename,
            output=output,
            stdout_stderr_output=command_output.stdout + "\n" + command_output.stderr,
        )

    def compile_program_async(
        self,
        program: Source,
        output: CompilationOutputType,
        additional_flags: tuple[str, ...] = tuple(),
    ) -> AsyncCompilationResult[CompilationOutputType]:
        """Compile a program with this setting asynchronously.

        You most likely want `compile_program` instead of this method.
        `compile_program_async` is useful if the calling process must
        interact with the compiler, e.g., via IPC

        Args:
            program (Source):
                input program
            output (CompilationOutputType):
                the desired output, e.g., executable or object file
            additional_flags (tuple[str, ...]):
                additional flags used for the compilation

        Returns:
            AsyncCompilationResult[CompilationOutputType]:
                The result of the compilation (if successful).
        """
        code_file = program.get_filename()
        cmd = self.get_compilation_cmd(
            (program, code_file.filename), output, True
        ) + list(additional_flags)
        return AsyncCompilationResult(
            " ".join(cmd),
            run_cmd_async(
                cmd,
                additional_env={"TMPDIR": tempfile.gettempdir()},
                text=True,
            ),
            code_file,
            output,
        )

    def preprocess_program(
        self,
        program: ProgramType,
        make_compiler_agnostic: bool = False,
        additional_flags: tuple[str, ...] = tuple(),
        timeout: int | None = None,
    ) -> ProgramType:
        """Preprocesses the program

        Args:
            program (Source):
                input program
            additional_flags (tuple[str, ...]):
                additional flags used for the compilation
            make_compiler_agnostic (bool):
                if true will try to remove certain constructs (e.g., attributes)
                such that the resulting program can be compiled with both gcc and clang
            timeout (int | None):
                timeout in seconds for the compilation command

        Returns:
            ProgramType:
                the prepocessed program
        """

        result = self.compile_program(
            program,
            ASMCompilationOutput(None),
            ("-P", "-E") + additional_flags,
            timeout=timeout,
        )
        preprocessed_source = result.output.read()

        if make_compiler_agnostic:
            # remove malloc attributes with args, clang doesn't understand these
            preprocessed_source = re.sub(
                r"__attribute__ \(\(__malloc__ \(.*, .*\)\)\)", r"", preprocessed_source
            )
            # remove f128 builtins builtins, clang doesn't understand these
            preprocessed_source = re.sub(
                r"extern int [^;]*f128[^;]*;", r"", preprocessed_source
            )
            # remove Float*** typedefs, gcc doesn't like these
            preprocessed_source = re.sub(
                r"typedef [^;]*_Float\d+x?;", r"", preprocessed_source
            )
            # replace remaining FloatX types with the standard ones
            preprocessed_source = re.sub(r"_Float32x", r"double", preprocessed_source)
            preprocessed_source = re.sub(
                r"_Float64x", r"long double", preprocessed_source
            )
            preprocessed_source = re.sub(r"_Float32", r"float", preprocessed_source)
            preprocessed_source = re.sub(r"_Float64", r"double", preprocessed_source)

        return program.with_preprocessed_code(preprocessed_source)

    def get_linking_cmd(
        self,
        objects: Sequence[ObjectCompilationOutput],
        output: ExeCompilationOutput,
        additional_flags: tuple[str, ...] = tuple(),
    ) -> list[str]:
        """Assembles a compilation invocation for linking
        the input `objects` to the `output`.

        Args:
            objects (Sequence[ObjectCompilationOutput]):
                the object to be linked
            output (ExeCompilationOutput):
                the output executable
            additional_flags (tuple[str, ...]):
                additional flags used for the compilation
        Returns:
            list[str]:
                The assembled compilation command
        """
        return list(
            chain(
                (
                    str(self.compiler.exe),
                    f"-{self.opt_level.name}",
                ),
                (str(obj.filename) for obj in objects),
                self.flags,
                additional_flags,
                ("-o", str(output.filename)),
            )
        )

    def link_objects(
        self,
        objects: Sequence[ObjectCompilationOutput],
        output: ExeCompilationOutput,
        additional_flags: tuple[str, ...] = tuple(),
        timeout: int | None = None,
    ) -> CompilationResult[ExeCompilationOutput]:
        """Linking the input `objects` to the `output`.

        Args:
            objects (Sequence[ObjectCompilationOutput]):
                the object to be linked
            output (ExeCompilationOutput):
                the output executable
            additional_flags (tuple[str, ...]):
                additional flags used for the compilation
            timeout (int | None):
                timeout in seconds for the compilation command

        Returns:
            CompilationResult[ExeCompilationOutputType]:
                The result of the linking (if successful).
        """
        cmd = self.get_linking_cmd(
            objects,
            output,
            additional_flags,
        )
        try:
            command_output = run_cmd(
                cmd,
                timeout=timeout,
                additional_env={"TMPDIR": str(tempfile.gettempdir())},
            )
        except subprocess.CalledProcessError as e:
            raise CompileError.from_called_process_exception(" ".join(cmd), e)
        return CompilationResult(
            source_file=Path(""),
            output=output,
            stdout_stderr_output=command_output.stdout + "\n" + command_output.stderr,
        )

    def link_objects_async(
        self,
        objects: Sequence[ObjectCompilationOutput],
        output: ExeCompilationOutput,
        additional_flags: tuple[str, ...] = tuple(),
    ) -> AsyncCompilationResult[ExeCompilationOutput]:
        """Linking the input `objects` to the `output` asynchronously.

        Args:
            objects (Sequence[ObjectCompilationOutput]):
                the object to be linked
            output (ExeCompilationOutput):
                the output executable
            additional_flags (tuple[str, ...]):
                additional flags used for the compilation
            timeout (int | None):
                timeout in seconds for the compilation command

        Returns:
            AsyncCompilationResult[ExeCompilationOutputType]:
                The result of the linking (if successful).
        """
        cmd = self.get_linking_cmd(
            objects,
            output,
            additional_flags,
        )
        return AsyncCompilationResult(
            " ".join(cmd),
            run_cmd_async(
                cmd,
                additional_env={"TMPDIR": str(tempfile.gettempdir())},
                text=True,
            ),
            None,
            output,
        )


def parse_opt_version(opt_exe: Path) -> Revision | None:
    """Tries to parse the revision of the opt.

    Args:
        opt_exe (Path): a path to the opt executable

    Returns:
        (CompilerProject, Revision) | None :
            compiler project (LLVM or GCC)  and the parsed version, None if
            the parsing failed
    """
    info = run_cmd(f"{str(opt_exe)} --version".split())
    for line in info.stdout.splitlines():
        if "LLVM version" in line:
            return line[len("LLVM version") :].strip()
    return None


@dataclass(frozen=True)
class Opt:
    """An LLVM opt wrapper

    Attributes:
        exe (Path): the path to the executable
        revision (Revision): the revision/version
    """

    exe: Path
    revision: Revision

    @staticmethod
    def get_system_opt() -> Opt:
        """Returns:
        Opt:
            the system's opt
        """
        opt = which("opt")
        assert opt, "opt is not in PATH"
        opt_path = Path(opt)
        project_revision = parse_opt_version(opt_path)
        assert project_revision is not None
        return Opt(opt_path, project_revision)

    @staticmethod
    def from_path(opt_path: Path) -> Opt:
        project_revision = parse_opt_version(opt_path)
        assert project_revision
        return Opt(opt_path, project_revision)

    def run_on_input(
        self,
        input_file: Path,
        flags: Sequence[str],
        timeout: int | None = None,
    ) -> CommandOutput:
        """Run opt on `input_file` and capture stdout and stderr"""

        cmd = list(chain((str(self.exe), str(input_file)), flags))
        try:
            return run_cmd(
                cmd,
                timeout=timeout,
                additional_env={"TMPDIR": str(tempfile.gettempdir())},
            )
        except subprocess.CalledProcessError as e:
            raise CompileError.from_called_process_exception(" ".join(cmd), e)


def find_standard_include_paths(
    clang: CompilerExe, cpp: bool = False
) -> tuple[str, ...]:
    """Finds the stanard include paths used by clang.

    This is used by clang tools as the standard include paths must be
    explicilty passed to them.

    Args:
        clang (CompilerExe): the clang executable from which to extract the paths
        cpp (bool): whether to include the standard c++ includes

    Returns:
        tuple[str,...]:
            the include paths
    """
    tf = temporary_file(contents="", suffix=".c" if not cpp else ".cpp")
    # run clang with verbose output on an empty temporary file
    cmd = [str(clang.exe), str(tf.name), "-c", "-o/dev/null", "-v"]
    result = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    assert result.returncode == 0

    # parse the output and extract includes
    output = result.stdout.decode("utf-8").split("\n")
    start = (
        next(
            i
            for i, line in enumerate(output)
            if "#include <...> search starts here:" in line
        )
        + 1
    )
    end = next(i for i, line in enumerate(output) if "End of search list." in line)
    return tuple(output[i].strip() for i in range(start, end))


class ClangToolMode(Enum):
    CAPTURE_OUT_ERR = 0
    READ_MODIFIED_FILE = 1
    CAPTURE_OUT_ERR_AND_READ_MODIFIED_FILED = 2


@dataclass(frozen=True, kw_only=True)
class ClangToolResult:
    modified_source_code: str | None
    stdout: str | None
    stderr: str | None


@dataclass(frozen=True)
class ClangTool:
    """A clang based tool that can be run on SourceProgram(s).

    Attributes:
        exe (Path):
            the clang tool executable
        standard_c_include_paths (tuple[str, ...]):
            which standard include paths to use for C program inputs
        standard_cxx_include_paths (tuple[str, ...]):
            which standard include paths to use for C++ program inputs
        timeout_s (int, default = 8):
            timeout in seconds for running the clang tool
    """

    exe: Path
    standard_c_include_paths: tuple[str, ...]
    standard_cxx_include_paths: tuple[str, ...]

    # TODO: @cache?
    @staticmethod
    def init_with_paths_from_clang(exe: Path, clang: CompilerExe) -> ClangTool:
        """Create a clang tool using clang's standard include paths.

        Args:
            exe (Path): path to the clang tool
            clang (CompilerExe): which clang to use to extract the standard paths

        Returns:
            ClangTool:
                the clang tool
        """
        assert clang.project == CompilerProject.LLVM
        return ClangTool(
            exe,
            find_standard_include_paths(clang, cpp=False),
            find_standard_include_paths(clang, cpp=True),
        )

    def run_on_program(
        self,
        program: SourceProgram,
        tool_flags: list[str],
        mode: ClangToolMode,
        timeout: int | None = None,
    ) -> ClangToolResult:
        """Run the clang tool on the input program

        Args:
            program (SourceProgram):
                the input program
            tool_flags (list[str]):
                flags to pass to the clang tool
            mode (ClangToolMode):
                whether to capture and return stdout & stderr,
                return the modified source code, or do both
           timeout (int | None): timeout in seconds

        Returns:
            ClangToolResult:
                captured stdout/stderr and/or modified source code

        """

        tf = temporary_file(
            contents=program.get_modified_code(), suffix=program.get_file_suffix()
        )
        match program.language:
            case Language.C:
                standard_include_paths = self.standard_c_include_paths
            case Language.CPP:
                standard_include_paths = self.standard_cxx_include_paths

        cmd = list(
            chain(
                (str(self.exe), str(tf.name)),
                tool_flags,
                (f"--extra-arg=-isystem{path}" for path in standard_include_paths),
                (f"--extra-arg={flag}" for flag in program.get_compilation_flags()),
                ("--",),
            )
        )
        try:
            result = run_cmd(
                cmd,
                timeout=timeout,
                additional_env={"TMPDIR": str(tempfile.gettempdir())},
            )
        except subprocess.CalledProcessError as e:
            raise CompileError.from_called_process_exception(" ".join(cmd), e)

        match mode:
            case ClangToolMode.CAPTURE_OUT_ERR:
                return ClangToolResult(
                    modified_source_code=None,
                    stdout=result.stdout,
                    stderr=result.stderr,
                )
            case ClangToolMode.READ_MODIFIED_FILE:
                with open(str(tf.name), "r") as f:
                    return ClangToolResult(
                        modified_source_code=f.read(), stdout=None, stderr=None
                    )
            case ClangToolMode.CAPTURE_OUT_ERR_AND_READ_MODIFIED_FILED:
                with open(str(tf.name), "r") as f:
                    return ClangToolResult(
                        modified_source_code=f.read(),
                        stdout=result.stdout,
                        stderr=result.stderr,
                    )


@dataclass(frozen=True, kw_only=True)
class CComp:
    """A ccomp(compcert) instance.

    Attributes:
        exe (Path): path to compcert/ccomp
    """

    exe: Path
    # TODO: timeout_s: int = 8

    @staticmethod
    def get_system_ccomp() -> CComp | None:
        """Returns:
        CComp:
            the system's ccomp
        """

        ccomp = which("ccomp")
        if not ccomp:
            return None
        return CComp(exe=Path(ccomp).resolve(strict=True))

    def check_program(
        self, program: SourceProgram, timeout: int | None = None, debug: bool = False
    ) -> bool:
        """Checks the input program for errors using ccomp's interpreter mode.

        Args:
           program (SourceProgram): the input program
           timeout (int | None): timeout in seconds for the checking
           debug (bool): if true ccomp's output will be printed on failure

        Returns:
            bool:
                was the check successful?
        """
        assert program.language == Language.C

        # ccomp doesn't like these
        code = re.sub(r"__asm__ [^\)]*\)", r"", program.get_modified_code())

        tf = temporary_file(contents=code, suffix=".c")
        cmd = (
            [
                str(self.exe),
                str(tf.name),
                "-interp",
                "-fall",
            ]
            + [
                f"-I{ipath}"
                for ipath in chain(program.include_paths, program.system_include_paths)
            ]
            + [f"-D{macro}" for macro in program.defined_macros]
        )
        try:
            run_cmd(
                cmd,
                additional_env={"TMPDIR": str(tempfile.gettempdir())},
                timeout=timeout,
            )
        except subprocess.CalledProcessError as e:
            if debug:
                print(CompileError.from_called_process_exception(" ".join(cmd), e))
            return False
        return True


def __compilation_setting_parser() -> argparse.ArgumentParser:
    """Create an ArgumentParser for CompilationSetting.
    Should be integrated with another parser via the `parent`
    constructor argument as it does not create the `help` output
    itself (otherwise, it would not be composable anymore).

    Note: -isystem is parsed as --isystem with a space after "m" as a
    workaround, the input to the parser should be adjusted accordingly

    Args:

    Returns:
        argparse.ArgumentParser:
    """
    # We do not add the help hear so this parser can be extendend or extend another one.
    parser = argparse.ArgumentParser(add_help=False, allow_abbrev=False)

    parser.add_argument(
        "compiler",
        type=Path,
    )
    parser.add_argument("-I", type=str, action="append")
    parser.add_argument("-O")
    parser.add_argument("--isystem", type=str, action="append")
    parser.add_argument("-D", action="append")
    parser.add_argument("-o")
    parser.add_argument("-c", action="store_true")
    parser.add_argument("-S", action="store_true")
    parser.add_argument("-MT", type=str, action="append")
    parser.add_argument("-MQ", type=str, action="append")

    return parser


def parse_compilation_setting_from_string(
    s: str,
) -> tuple[
    CompilationSetting, list[SourceFile | ObjectCompilationOutput], CompilationOutput
]:
    """Parse the compilation setting provided in `s`.

    Args:
        s (str): compilation command string to be parsed.

    Returns:
        tuple[
            CompilationSetting,
            list[SourceProgram | ObjectCompilationOutput],
            CompilationOutput
        ]:
            - CompilationSetting
            - source files provided
            - specified compilation output file and kind
    """
    parser = __compilation_setting_parser()
    parsed_args, rest = parser.parse_known_intermixed_args(
        [p for p in s.replace("-isystem", "--isystem ").split()]
    )
    CPP_EXT = (".cc", ".cxx", ".cpp")
    C_EXT = (".c",)
    OBJ_EXT = (".o",)

    sources: list[SourceFile | ObjectCompilationOutput] = []
    flags: list[str] = []
    for arg in rest:
        if arg.lower().endswith(CPP_EXT):
            sources.append(SourceFile(language=Language.CPP, filename=Path(arg)))
        elif arg.lower().endswith(C_EXT):
            sources.append(SourceFile(language=Language.C, filename=Path(arg)))
        elif arg.lower().endswith(OBJ_EXT):
            sources.append(ObjectCompilationOutput(filename=Path(arg)))
        else:
            flags.append(arg)

    # append flags caputred by the parser
    if parsed_args.MT:
        for mt in parsed_args.MT:
            flags.extend(["-MT", mt])
    if parsed_args.MQ:
        for mq in parsed_args.MQ:
            flags.extend(["-MQ", mq])

    include_paths: tuple[str, ...] = tuple(parsed_args.I) if parsed_args.I else tuple()
    system_include_paths: tuple[str, ...] = (
        tuple(parsed_args.isystem) if parsed_args.isystem else tuple()
    )
    macro_definitions: tuple[str, ...] = (
        tuple(parsed_args.D) if parsed_args.D else tuple()
    )

    cexe = CompilerExe.from_path(Path(parsed_args.compiler))

    opt = parsed_args.O
    if not opt:
        opt = "O0"

    csetting = CompilationSetting(
        compiler=cexe,
        opt_level=OptLevel.from_str(opt),
        include_paths=include_paths,
        system_include_paths=system_include_paths,
        macro_definitions=macro_definitions,
        flags=tuple(flags),
    )
    output: CompilationOutput
    if parsed_args.o:
        if parsed_args.c:
            output = ObjectCompilationOutput(Path(parsed_args.o))
        elif parsed_args.S:
            # TODO: check for emit-llvm?
            output = ASMCompilationOutput(Path(parsed_args.o))
        else:
            output = ExeCompilationOutput(Path(parsed_args.o))
    else:
        output = NoCompilationOutput()

    return csetting, sources, output
