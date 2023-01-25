from __future__ import annotations

import argparse
import os
import re
import subprocess
import tempfile
from dataclasses import dataclass, replace
from enum import Enum
from itertools import chain
from pathlib import Path
from shutil import which
from types import TracebackType
from typing import TypeVar

from diopter.utils import run_cmd


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


ProgramType = TypeVar("ProgramType", bound="SourceProgram")


@dataclass(frozen=True, kw_only=True)
class SourceProgram:
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


class TemporaryFile:
    def __init__(self, *, contents: str, suffix: str):
        self.contents = contents
        self.suffix = suffix
        self.path: str | None = None

    def __enter__(self) -> Path:
        fd, self.path = tempfile.mkstemp(suffix=self.suffix)
        os.close(fd)
        if self.contents:
            with open(self.path, "w") as f:
                f.write(self.contents)
        return Path(self.path).resolve(strict=True)

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        exc_traceback: TracebackType | None,
    ) -> None:
        if self.path and Path(self.path).exists():
            os.remove(self.path)


@dataclass(frozen=True, kw_only=True)
class CompilationInfo:
    source_file: Path
    stdout_stderr_output: str


class CompilationOutputKind(Enum):
    Object = 0
    Assembly = 1
    Exec = 2
    Unspecified = 3

    def to_flag(self) -> str:
        match self:
            case CompilationOutputKind.Object:
                return "-c"
            case CompilationOutputKind.Assembly:
                return "-S"
            case CompilationOutputKind.Exec | CompilationOutputKind.Unspecified:
                return ""


@dataclass(frozen=True)
class CompilationOutput:
    filename: Path
    kind: CompilationOutputKind

    def to_cmd(self) -> str:
        if self.kind == CompilationOutputKind.Unspecified:
            return ""
        if kind_flag := self.kind.to_flag():
            return kind_flag + " -o " + str(self.filename)
        return "-o " + str(self.filename)


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
        program: tuple[ProgramType, Path],
        output: CompilationOutput,
        include_language_flags: bool = True,
    ) -> list[str]:
        """Assembles a compilation invocation based on the
        input programs and the output.

        Args:
            program (tuple[ProgramType, Path]):
                flags from the program are extracted and
                the corresponding path are included in the output
            output (CompilationOutput):
                the output path and potentially additional flags
                based on the output kind
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

        if include_language_flags and output.kind == CompilationOutputKind.Exec:
            if linker_flag := program[0].language.get_linker_flag():
                cmd.append(linker_flag)
        cmd.append(output.to_cmd())
        return cmd

    def compile_program(
        self,
        program: ProgramType,
        output: CompilationOutput,
        additional_flags: tuple[str, ...] = tuple(),
        timeout: int | None = None,
    ) -> CompilationInfo:

        with TemporaryFile(
            contents=program.get_modified_code(), suffix=program.get_file_suffix()
        ) as code_file:
            cmd = self.get_compilation_cmd((program, code_file), output, True) + list(
                additional_flags
            )
            try:
                command_output = run_cmd(
                    cmd,
                    timeout=timeout,
                    additional_env={"TMPDIR": str(tempfile.gettempdir())},
                )
            except subprocess.CalledProcessError as e:
                raise CompileError.from_called_process_exception(" ".join(cmd), e)
            return CompilationInfo(
                source_file=Path(code_file),
                stdout_stderr_output=command_output.stdout
                + "\n"
                + command_output.stderr,
            )

    def get_llvm_ir_from_program(
        self, program: ProgramType, timeout: int | None = None
    ) -> str:
        """Extracts LLVM-IR from the program.

        This only works with LLVM compilers.

        Args:
           program (ProgramType): input program
           timeout (int | None): timeout in seconds for the compilation command
        Returns:
            str:
                LLVM-IR
        """
        return self.get_asm_from_program(program, ("--emit-llvm",), timeout=timeout)

    def get_asm_from_program(
        self,
        program: ProgramType,
        additional_flags: tuple[str, ...] = (),
        timeout: int | None = None,
    ) -> str:
        """Extracts assembly code from the program.

        Args:
           program (ProgramType): input program
           additional_flags (tuple[str, ...]): additional flags used for the compilation
           timeout (int | None): timeout in seconds for the compilation command

        Returns:
            str:
                assembly code
        """
        with TemporaryFile(contents="", suffix=".s") as asm_file:
            self.compile_program(
                program,
                CompilationOutput(asm_file, CompilationOutputKind.Assembly),
                additional_flags,
                timeout,
            )
            with open(str(asm_file), "r") as f:
                return f.read()

    def compile_program_to_object(
        self,
        program: ProgramType,
        object_file: Path,
        additional_flags: tuple[str, ...] = tuple(),
        timeout: int | None = None,
    ) -> CompilationInfo:
        """Compiles program to object file

        Args:
           program (ProgramType): input program
           object_file (Path): path to the output
           additional_flags (tuple[str, ...]): additional flags used for the compilation
           timeout (int | None): timeout in seconds for the compilation command

        Returns:
            CompilationInfo:
                information about the compilation
        """

        return self.compile_program(
            program,
            CompilationOutput(object_file, CompilationOutputKind.Object),
            additional_flags,
            timeout=timeout,
        )

    def compile_program_to_executable(
        self,
        program: ProgramType,
        executable_path: Path,
        additional_flags: tuple[str, ...] = tuple(),
        timeout: int | None = None,
    ) -> CompilationInfo:
        """Compiles program to object file

        Args:
           program (ProgramType): input program
           executable_file (Path): path to the output
           additional_flags (tuple[str, ...]): additional flags used for the compilation
           timeout (int | None): timeout in seconds for the compilation command

        Returns:
            CompilationInfo:
                information about the compilation
        """

        # TODO: check/set file permissions of executable_path if it exists?
        return self.compile_program(
            program,
            CompilationOutput(executable_path, CompilationOutputKind.Exec),
            additional_flags,
            timeout=timeout,
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
           program (ProgramType): input program
           additional_flags (tuple[str, ...]): additional flags used for the compilation
           make_compiler_agnostic (bool):
               if true will try to remove certain constructs (e.g., attributes)
               such that the resulting program can be compiled with both gcc and clang
           timeout (int | None): timeout in seconds for the compilation command

        Returns:
            Source:
                the prepocessed program

        """

        preprocessed_source = self.compile_program(
            program,
            CompilationOutput(Path(""), CompilationOutputKind.Unspecified),
            ("-P", "-E") + additional_flags,
            timeout=timeout,
        ).stdout_stderr_output

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

        return program.with_preprocessed_code(preprocessed_source)


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
    with TemporaryFile(contents="", suffix=".c" if not cpp else ".cpp") as tf:
        # run clang with verbose output on an empty temporary file
        cmd = [str(clang.exe), str(tf), "-c", "-o/dev/null", "-v"]
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

        with TemporaryFile(
            contents=program.get_modified_code(), suffix=program.get_file_suffix()
        ) as tf:
            match program.language:
                case Language.C:
                    standard_include_paths = self.standard_c_include_paths
                case Language.CPP:
                    standard_include_paths = self.standard_cxx_include_paths

            cmd = list(
                chain(
                    (str(self.exe), str(tf)),
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
                    with open(str(tf), "r") as f:
                        return ClangToolResult(
                            modified_source_code=f.read(), stdout=None, stderr=None
                        )
                case ClangToolMode.CAPTURE_OUT_ERR_AND_READ_MODIFIED_FILED:
                    with open(str(tf), "r") as f:
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

        with TemporaryFile(contents=code, suffix=".c") as tf:
            cmd = (
                [
                    str(self.exe),
                    str(tf),
                    "-interp",
                    "-fall",
                ]
                + [
                    f"-I{ipath}"
                    for ipath in chain(
                        program.include_paths, program.system_include_paths
                    )
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

    return parser


def parse_compilation_setting_from_string(
    s: str,
) -> tuple[CompilationSetting, list[str], CompilationOutput]:
    """Parse the compilation setting provided in `s`.

    Args:
        s (str): compilation command string to be parsed.

    Returns:
        tuple[CompilationSetting, list[str], CompilationOutput]:
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

    sources: list[str] = []
    flags: list[str] = []
    for arg in rest:
        if arg.lower().endswith(CPP_EXT + C_EXT):
            sources.append(arg)
        else:
            flags.append(arg)

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

    if parsed_args.o:
        if parsed_args.c:
            kind = CompilationOutputKind.Object
        elif parsed_args.S:
            kind = CompilationOutputKind.Assembly
        else:
            kind = CompilationOutputKind.Exec
        output = CompilationOutput(parsed_args.o, kind)
    else:
        output = CompilationOutput(Path(""), CompilationOutputKind.Unspecified)

    return csetting, sources, output
