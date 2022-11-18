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
from typing import Optional

from ccbuilder import Builder, CompilerProject, Revision

from diopter.utils import run_cmd, save_to_tmp_file


class Language(Enum):
    C = 0
    CPP = 1

    def get_lang_flag(self) -> str:
        match self:
            case Language.C:
                return "-xc"
            case Language.CPP:
                return "-xc++"

    def to_suffix(self) -> str:
        match self:
            case Language.C:
                return ".c"
            case Language.CPP:
                return ".cpp"


@dataclass(frozen=True, kw_only=True)
class SourceProgram:
    code: str
    language: Language
    available_macros: tuple[str, ...] = tuple()
    defined_macros: tuple[str, ...] = tuple()
    include_paths: tuple[str, ...] = tuple()
    system_include_paths: tuple[str, ...] = tuple()
    flags: tuple[str, ...] = tuple()

    def get_compilation_flags(self) -> tuple[str, ...]:
        return tuple(
            chain(
                self.flags,
                (f"-D{m}" for m in self.defined_macros),
                (f"-I{i}" for i in self.include_paths),
                (f"-isystem{i}" for i in self.system_include_paths),
            )
        )

    def get_file_suffix(self) -> str:
        match self.language:
            case Language.C:
                return ".c"
            case Language.CPP:
                return ".cpp"

    def with_code(self, new_code: str) -> SourceProgram:
        return replace(self, code=new_code)


def parse_compiler_revision(compiler_exe: Path) -> Revision:
    info = run_cmd(f"{str(compiler_exe)} -v".split())
    for line in info.splitlines():
        if "clang version" in line:
            return line[len("clang version") :].strip()
        if "gcc version" in line:
            return line[len("gcc version") :].strip().split()[0]
    return "unknown"


@dataclass(frozen=True)
class CompilerExe:
    project: CompilerProject
    exe: Path
    revision: Revision

    def get_verbose_info(self) -> str:
        return run_cmd(f"{self.exe} -v".split())

    @staticmethod
    def get_system_gcc() -> CompilerExe:
        gcc = which("gcc")
        assert gcc, "gcc is not in PATH"
        gcc_path = Path(gcc)
        return CompilerExe(
            CompilerProject.GCC, gcc_path, parse_compiler_revision(gcc_path)
        )

    @staticmethod
    def get_system_clang() -> CompilerExe:
        clang = which("clang")
        assert clang, "clang is not in PATH"
        clang_path = Path(clang)
        return CompilerExe(
            CompilerProject.LLVM, clang_path, parse_compiler_revision(clang_path)
        )


class OptLevel(Enum):
    O0 = 0
    O1 = 1
    O2 = 2
    O3 = 3
    Os = 4
    Oz = 5

    @staticmethod
    def from_str(s: str) -> OptLevel:
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
    compiler: CompilerExe
    opt_level: OptLevel
    flags: tuple[str, ...] = tuple()
    include_paths: tuple[str, ...] = tuple()
    system_include_paths: tuple[str, ...] = tuple()

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
        return list(
            chain(
                (
                    str(self.compiler.exe),
                    program.language.get_lang_flag(),
                    f"-{self.opt_level.name}",
                ),
                self.flags,
                (f"-I{path}" for path in self.include_paths),
                (f"-isystem{path}" for path in self.system_include_paths),
                program.get_compilation_flags(),
            )
        )

    def get_llvm_ir_from_program(
        self, program: SourceProgram, timeout: Optional[int] = None
    ) -> str:
        return self.get_asm_from_program(program, ("--emit-llvm",), timeout=timeout)

    def get_asm_from_program(
        self,
        program: SourceProgram,
        additional_flags: tuple[str, ...] = (),
        timeout: Optional[int] = None,
    ) -> str:
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
                source_file=Path(code_file), stdout_stderr_output=output
            )

    def compile_program_to_object(
        self,
        program: SourceProgram,
        object_file: Path,
        additional_flags: tuple[str, ...] = tuple(),
        timeout: Optional[int] = None,
    ) -> CompilationInfo:
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
        return self._compile_program_to_X(
            program, None, ("-P", "-E") + additional_flags, timeout=timeout
        )


class ClangToolMode(Enum):
    CAPTURE_OUT_ERR = 0
    READ_MODIFIED_FILE = 1


def find_standard_include_paths(
    llvm: CompilerExe, cpp: bool = False
) -> tuple[str, ...]:
    with tempfile.NamedTemporaryFile(suffix=".c" if not cpp else ".cpp") as tf:
        cmd = [str(llvm.exe), tf.name, "-c", "-o/dev/null", "-v"]
        result = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        assert result.returncode == 0
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


@dataclass(frozen=True)
class ClangTool:
    exe: Path
    standard_c_include_paths: tuple[str, ...]
    standard_cxx_include_paths: tuple[str, ...]
    timeout_s: int = 8

    @staticmethod
    def init_with_paths_from_llvm(exe: Path, llvm: CompilerExe) -> ClangTool:
        assert llvm.project == CompilerProject.LLVM
        return ClangTool(
            exe,
            find_standard_include_paths(llvm, cpp=False),
            find_standard_include_paths(llvm, cpp=True),
        )

    def run_on_program(
        self, program: SourceProgram, tool_flags: list[str], mode: ClangToolMode
    ) -> str:
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
                ).strip()
            except subprocess.CalledProcessError as e:
                raise CompileError.from_called_process_exception(e)

            match mode:
                case ClangToolMode.CAPTURE_OUT_ERR:
                    return result
                case ClangToolMode.READ_MODIFIED_FILE:
                    with open(tf.name, "r") as f:
                        return f.read()


@dataclass(frozen=True, kw_only=True)
class CComp:
    exe: Path

    @staticmethod
    def get_system_ccomp() -> Optional[CComp]:
        ccomp = which("ccomp")
        if not ccomp:
            return None
        return CComp(exe=Path(ccomp).absolute())

    def check_program(
        self, program: SourceProgram, timeout: Optional[int] = None
    ) -> bool:
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
