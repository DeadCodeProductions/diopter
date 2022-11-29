from __future__ import annotations

import os
import subprocess
import tempfile
from dataclasses import dataclass, replace
from enum import Enum
from itertools import chain
from pathlib import Path
from shutil import which
from types import TracebackType

# TODO: replace Optinal with | None
from typing import Optional

from ccbuilder import Builder, CompilerProject, Revision

from diopter.utils import run_cmd, save_to_tmp_file


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


@dataclass(frozen=True, kw_only=True)
class SourceProgram:
    """A C or C++ source program together with flags, includes and macro definitions.

    Attributes:
        code (str):
            the source code
        language (Language):
            the program's language
        available_macros (tuple[str,...]):
            known macros that can be defined to affect the program's compilation (this
            is not exhaustive, additional, e.g., system macros, might be available)
        available_macros (tuple[str,...]):
            macros that will be defined when compiling this program
        include_paths (tuple[str,...]):
            include paths which will be passed to the compiler (with -I)
        system_include_paths (tuple[str,...]):
            system include paths which will be passed to the compiler (with -isystem)
        flags (tuple[str,...]):
            flags, prefixed with a dash ("-") that will be passed to the compiler
    """

    code: str
    language: Language
    available_macros: tuple[str, ...] = tuple()
    defined_macros: tuple[str, ...] = tuple()
    include_paths: tuple[str, ...] = tuple()
    system_include_paths: tuple[str, ...] = tuple()
    flags: tuple[str, ...] = tuple()

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

    def with_code(self, new_code: str) -> SourceProgram:
        """Returns a new program with its code replaced with new_code

        Returns:
            SourceProgram:
                the new program
        """
        return replace(self, code=new_code)


def parse_compiler_revision(compiler_exe: Path) -> Revision:
    """Tries to parse the compiler revision of the given executable (clang/gcc).

    Args:
        compiler_exe (Path): a path to the compiler executable

    Returns:
        Revision:
            the parsed version
    """
    info = run_cmd(f"{str(compiler_exe)} -v".split())
    for line in info.stderr.splitlines():
        if "clang version" in line:
            return line[len("clang version") :].strip()
        if "gcc version" in line:
            return line[len("gcc version") :].strip().split()[0]
    return "unknown"


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
        return CompilerExe(
            CompilerProject.GCC, gcc_path, parse_compiler_revision(gcc_path)
        )

    @staticmethod
    def get_system_clang() -> CompilerExe:
        """Returns:
        CompilerExe:
            the system's clang compiler
        """
        clang = which("clang")
        assert clang, "clang is not in PATH"
        clang_path = Path(clang)
        return CompilerExe(
            CompilerProject.LLVM, clang_path, parse_compiler_revision(clang_path)
        )


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

        output = ""
        if e.stdout:
            output += "\nSTDOUT====\n" + e.stdout.decode("utf-8")
        if e.stderr:
            output = "\nSTDERR====\n" + e.stderr.decode("utf-8")
        return CompileError(output)


class CompileContext:
    def __init__(self, code: str):
        self.code = code
        self.fd_code: Optional[int] = None
        self.fd_asm: Optional[int] = None
        self.code_file: Optional[str] = None
        self.asm_file: Optional[str] = None

    def __enter__(self) -> tuple[str, str]:
        self.fd_code, self.code_file = tempfile.mkstemp(suffix=".c")
        self.fd_asm, self.asm_file = tempfile.mkstemp(suffix=".s")

        with open(self.code_file, "w") as f:
            f.write(self.code)

        return (self.code_file, self.asm_file)

    def __exit__(
        self,
        exc_type: Optional[type[BaseException]],
        exc_value: Optional[BaseException],
        exc_traceback: Optional[TracebackType],
    ) -> None:
        if self.code_file and self.fd_code and self.asm_file and self.fd_asm:
            os.remove(self.code_file)
            os.close(self.fd_code)
            # In case of a CompileError,
            # the file itself might not exist.
            if Path(self.asm_file).exists():
                os.remove(self.asm_file)
            os.close(self.fd_asm)
        else:
            raise CompileError("Compiler context exited but was not entered")


@dataclass(frozen=True, kw_only=True)
class CompilationInfo:
    source_file: Path
    stdout_stderr_output: str


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
            which flags to use when compiling programs
        include_path (tuple[str,...]):
            which include paths to pass to the compiler (passed with -I)
        system_include_path (tuple[str,...]):
            which system include paths to pass to the compiler (passed with -isystem)
    """

    compiler: CompilerExe
    opt_level: OptLevel
    flags: tuple[str, ...] = tuple()
    include_paths: tuple[str, ...] = tuple()
    system_include_paths: tuple[str, ...] = tuple()
    # TODO: timeout_s: int = 8

    # TODO: drop this, ccbuilder should be independent of this file
    def with_revision(self, revision: Revision, builder: Builder) -> CompilationSetting:
        new_compiler = CompilerExe(
            self.compiler.project,
            builder.build(self.compiler.project, revision, True),
            revision,
        )
        return CompilationSetting(
            compiler=new_compiler,
            opt_level=self.opt_level,
            flags=self.flags,
            include_paths=self.include_paths,
            system_include_paths=self.system_include_paths,
        )

    def get_compilation_base_cmd(self, program: SourceProgram) -> list[str]:
        """Combines the program's flags with the flags of this compilation
        setting.

        Args:
            program(SourceProgram):
                the program whose flags will be extracted

        Returns:
            list[str]:
                list of flags
        """
        cmd = list(
            chain(
                (
                    str(self.compiler.exe),
                    program.language.get_language_flag(),
                    f"-{self.opt_level.name}",
                ),
                self.flags,
                (f"-I{path}" for path in self.include_paths),
                (f"-isystem{path}" for path in self.system_include_paths),
                program.get_compilation_flags(),
            )
        )
        if linker_flag := program.language.get_linker_flag():
            cmd.append(linker_flag)
        return cmd

    def get_llvm_ir_from_program(
        self, program: SourceProgram, timeout: Optional[int] = None
    ) -> str:
        """Extracts LLVM-IR from the program.

        This only works with LLVM compilers.

        Args:
           program (SourceProgram): input program
           timeout (int | None): timeout in seconds for the compilation command
        Returns:
            str:
                LLVM-IR
        """
        return self.get_asm_from_program(program, ("--emit-llvm",), timeout=timeout)

    def get_asm_from_program(
        self,
        program: SourceProgram,
        additional_flags: tuple[str, ...] = (),
        timeout: Optional[int] = None,
    ) -> str:
        """Extracts assembly code from the program.

        Args:
           program (SourceProgram): input program
           additional_flags (tuple[str, ...]): additional flags used for the compilation
           timeout (int | None): timeout in seconds for the compilation command

        Returns:
            str:
                assembly code
        """
        with CompileContext(program.code) as context_res:
            code_file, asm_file = context_res
            cmd = (
                self.get_compilation_base_cmd(program)
                + [
                    code_file,
                    "-S",
                    "-o",
                    asm_file,
                ]
                + list(additional_flags)
            )

            try:
                run_cmd(
                    cmd,
                    timeout=timeout,
                    additional_env={"TMPDIR": str(tempfile.gettempdir())},
                )
            except subprocess.CalledProcessError as e:
                raise CompileError.from_called_process_exception(e)

            with open(asm_file, "r") as f:
                return f.read()

    def _compile_program_to_X(
        self,
        program: SourceProgram,
        output_file: Optional[Path],
        flags: tuple[str, ...] = tuple(),
        timeout: Optional[int] = None,
    ) -> CompilationInfo:

        with CompileContext(program.code) as context_res:
            code_file, _ = context_res
            cmd = (
                self.get_compilation_base_cmd(program)
                + [code_file]
                + (["-o", str(output_file)] if output_file else [])
                + list(flags)
            )
            try:
                output = run_cmd(
                    cmd,
                    timeout=timeout,
                    additional_env={"TMPDIR": str(tempfile.gettempdir())},
                )
            except subprocess.CalledProcessError as e:
                raise CompileError.from_called_process_exception(e)
            return CompilationInfo(
                source_file=Path(code_file),
                stdout_stderr_output=output.stdout + "\n" + output.stderr,
            )

    def compile_program_to_object(
        self,
        program: SourceProgram,
        object_file: Path,
        additional_flags: tuple[str, ...] = tuple(),
        timeout: Optional[int] = None,
    ) -> CompilationInfo:
        """Compiles program to object file

        Args:
           program (SourceProgram): input program
           object_file (Path): path to the output
           additional_flags (tuple[str, ...]): additional flags used for the compilation
           timeout (int | None): timeout in seconds for the compilation command

        Returns:
            CompilationInfo:
                information about the compilation
        """

        return self._compile_program_to_X(
            program, object_file, ("-c",) + additional_flags, timeout=timeout
        )

    def compile_program_to_executable(
        self,
        program: SourceProgram,
        executable_path: Path,
        additional_flags: tuple[str, ...] = tuple(),
        timeout: Optional[int] = None,
    ) -> CompilationInfo:
        """Compiles program to object file

        Args:
           program (SourceProgram): input program
           executable_file (Path): path to the output
           additional_flags (tuple[str, ...]): additional flags used for the compilation
           timeout (int | None): timeout in seconds for the compilation command

        Returns:
            CompilationInfo:
                information about the compilation
        """

        # TODO: check/set file permissions of executable_path if it exists?
        return self._compile_program_to_X(
            program, executable_path, additional_flags, timeout=timeout
        )

    def preprocess_program(
        self,
        program: SourceProgram,
        additional_flags: tuple[str, ...] = tuple(),
        timeout: Optional[int] = None,
    ) -> CompilationInfo:
        """Preprocesses the program

        Args:
           program (SourceProgram): input program
           additional_flags (tuple[str, ...]): additional flags used for the compilation
           timeout (int | None): timeout in seconds for the compilation command

        Returns:
            CompilationInfo:
                information about the compilation, the
                preprocessing result is stored in the output

        """

        return self._compile_program_to_X(
            program, None, ("-P", "-E") + additional_flags, timeout=timeout
        )


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
    with tempfile.NamedTemporaryFile(suffix=".c" if not cpp else ".cpp") as tf:
        # run clang with verbose output on an empty temporary file
        cmd = [str(clang.exe), tf.name, "-c", "-o/dev/null", "-v"]
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
    timeout_s: int = 8

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
        self, program: SourceProgram, tool_flags: list[str], mode: ClangToolMode
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

        Returns:
            ClangToolResult:
                captured stdout/stderr and/or modified source code

        """
        with tempfile.NamedTemporaryFile(suffix=program.get_file_suffix()) as tf:
            with open(tf.name, "w") as f:
                f.write(program.code)

            match program.language:
                case Language.C:
                    standard_include_paths = self.standard_c_include_paths
                case Language.CPP:
                    standard_include_paths = self.standard_cxx_include_paths

            cmd = list(
                chain(
                    (str(self.exe), tf.name),
                    tool_flags,
                    (f"--extra-arg=-isystem{path}" for path in standard_include_paths),
                    (f"--extra-arg={flag}" for flag in program.get_compilation_flags()),
                    ("--",),
                )
            )
            try:
                result = run_cmd(
                    cmd,
                    timeout=self.timeout_s,
                    additional_env={"TMPDIR": str(tempfile.gettempdir())},
                )
            except subprocess.CalledProcessError as e:
                raise CompileError.from_called_process_exception(e)

            match mode:
                case ClangToolMode.CAPTURE_OUT_ERR:
                    return ClangToolResult(
                        modified_source_code=None,
                        stdout=result.stdout,
                        stderr=result.stderr,
                    )
                case ClangToolMode.READ_MODIFIED_FILE:
                    with open(tf.name, "r") as f:
                        return ClangToolResult(
                            modified_source_code=f.read(), stdout=None, stderr=None
                        )
                case ClangToolMode.CAPTURE_OUT_ERR_AND_READ_MODIFIED_FILED:
                    with open(tf.name, "r") as f:
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
    def get_system_ccomp() -> Optional[CComp]:
        """Returns:
        CComp:
            the system's ccomp
        """

        ccomp = which("ccomp")
        if not ccomp:
            return None
        return CComp(exe=Path(ccomp).absolute())

    def check_program(
        self, program: SourceProgram, timeout: Optional[int] = None
    ) -> bool:
        """Checks the input program for errors using ccomp's interpreter mode.

        Args:
           program (SourceProgram): the input program
           timeout (int | None): timeout in seconds for the checking

        Returns:
            bool:
                was the check successful?
        """
        tf = save_to_tmp_file(program.code, suffix=program.language.to_suffix())
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
        except subprocess.CalledProcessError:
            return False
        return True
