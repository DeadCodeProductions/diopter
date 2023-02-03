from pathlib import Path
from shutil import which

from diopter.compiler import (
    CompilationSetting,
    CompilerExe,
    CompilerProject,
    Language,
    OptLevel,
    SourceProgram,
    temporary_file,
)
from diopter.utils import run_cmd


def test_compiler_exe_from_path() -> None:
    for v in [14, 15, 16]:
        clang_path = Path(f"clang-{v}")
        if not clang_path.exists():
            continue
        clang = CompilerExe.from_path(clang_path)
        assert clang.exe == Path(clang_path)
        assert f"{v}." in clang.revision
        assert clang.project == CompilerProject.LLVM


def test_get_asm_from_program() -> None:
    input_code = "int foo(int a){ return a + 1; }"
    program = SourceProgram(code=input_code, language=Language.C)
    compiler = CompilerExe(CompilerProject.GCC, Path("gcc"), "")
    cs = CompilationSetting(compiler=compiler, opt_level=OptLevel.O2, flags=("-m32",))
    asm = cs.get_asm_from_program(program)

    tf = temporary_file(contents=program.code, suffix=program.get_file_suffix())
    result = run_cmd(f"gcc {tf.name} -mno-red-zone -o /dev/stdout -O2 -m32 -S")
    asm_manual = result.stdout

    def canonicalize(asm: str) -> str:
        return "\n".join(
            line for line in asm.splitlines() if ".file" not in line
        ).strip()

    assert canonicalize(asm) == canonicalize(asm_manual)


def strip_and_read_binary(path: str) -> bytes:
    run_cmd(f"strip {path}")
    with open(path, "rb") as f:
        return f.read()


def test_compile_to_object() -> None:
    input_code = "int foo(int a){ return a + 1; }"
    program = SourceProgram(code=input_code, language=Language.C)
    compiler = CompilerExe(CompilerProject.GCC, Path("gcc"), "")
    cs = CompilationSetting(compiler=compiler, opt_level=OptLevel.O2)
    object_file1 = temporary_file(contents="", suffix=".o")
    cs.compile_program_to_object(
        program,
        Path(object_file1.name),
    )
    object1 = strip_and_read_binary(object_file1.name)

    code_file = temporary_file(contents=program.code, suffix=program.get_file_suffix())
    object_file2 = temporary_file(contents="", suffix=".o")
    cmd = f"gcc {code_file.name} -o {object_file2.name} -O2 -c"
    run_cmd(cmd)

    object2 = strip_and_read_binary(object_file2.name)

    assert object1 == object2


def test_compile_to_object_cpp() -> None:
    input_code = """#include <iostream>
                    void foo(int a){ std::cout<< a; }
                 """
    program = SourceProgram(code=input_code, language=Language.CPP)
    compiler = CompilerExe(CompilerProject.GCC, Path("gcc"), "")
    cs = CompilationSetting(compiler=compiler, opt_level=OptLevel.O2)
    object_file1 = temporary_file(contents="", suffix=".o")
    cs.compile_program_to_object(
        program,
        Path(object_file1.name),
    )
    object1 = strip_and_read_binary(object_file1.name)

    object_file2 = temporary_file(contents="", suffix=".o")
    code_file = temporary_file(contents=program.code, suffix=program.get_file_suffix())
    cmd = f"g++ {code_file.name} -o {object_file2.name} -O2 -c"
    run_cmd(cmd)

    object2 = strip_and_read_binary(object_file2.name)

    assert object1 == object2


def test_compile_to_exec() -> None:
    input_code = "int foo(int a){ return a + 1; } int main(){return foo(1);}"
    program = SourceProgram(code=input_code, language=Language.C)
    compiler = CompilerExe(CompilerProject.GCC, Path("gcc"), "")
    cs = CompilationSetting(compiler=compiler, opt_level=OptLevel.O2)
    exe_file1 = temporary_file(contents="", suffix=".exe")
    cs.compile_program_to_executable(
        program,
        Path(exe_file1.name),
    )
    assert which(exe_file1.name)
    exe1 = strip_and_read_binary(exe_file1.name)

    exe_file2 = temporary_file(contents="", suffix=".exe")
    code_file = temporary_file(contents=program.code, suffix=program.get_file_suffix())
    cmd = f"gcc {code_file.name} -o {exe_file2.name} -O2 "
    run_cmd(cmd)

    assert which(exe_file2.name)
    exe2 = strip_and_read_binary(exe_file2.name)

    assert exe1 == exe2
