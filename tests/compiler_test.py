from pathlib import Path
from shutil import which

from diopter.compiler import (
    CompilationSetting,
    CompilerExe,
    CompilerProject,
    Language,
    OptLevel,
    SourceProgram,
    TemporaryFile,
)
from diopter.utils import run_cmd


def test_compiler_exe_from_path() -> None:
    clang = CompilerExe.from_path(Path("clang-14"))
    assert clang.exe == Path("clang-14")
    assert "14." in clang.revision
    assert clang.project == CompilerProject.LLVM


def test_get_asm_from_program() -> None:
    input_code = "int foo(int a){ return a + 1; }"
    program = SourceProgram(code=input_code, language=Language.C)
    compiler = CompilerExe(CompilerProject.GCC, Path("gcc"), "")
    cs = CompilationSetting(compiler=compiler, opt_level=OptLevel.O2, flags=("-m32",))
    asm = cs.get_asm_from_program(program)

    with TemporaryFile(contents=program.code, suffix=program.get_file_suffix()) as f:
        result = run_cmd(f"gcc {f} -mno-red-zone -o /dev/stdout -O2 -m32 -S")
        asm_manual = result.stdout

    def canonicalize(asm: str) -> str:
        return "\n".join(
            line for line in asm.splitlines() if ".file" not in line
        ).strip()

    assert canonicalize(asm) == canonicalize(asm_manual)


def test_compile_to_object() -> None:
    input_code = "int foo(int a){ return a + 1; }"
    program = SourceProgram(code=input_code, language=Language.C)
    compiler = CompilerExe(CompilerProject.GCC, Path("gcc"), "")
    cs = CompilationSetting(compiler=compiler, opt_level=OptLevel.O2)
    cs.compile_program_to_object(
        program,
        Path("/tmp/test1.o"),
    )

    run_cmd("strip /tmp/test1.o")
    with open("/tmp/test1.o", "rb") as f:
        object1 = f.read()

    with TemporaryFile(contents=program.code, suffix=program.get_file_suffix()) as f:
        cmd = f"gcc {f} -o /tmp/test2.o -O2 -c"
        run_cmd(cmd)

    run_cmd("strip /tmp/test2.o")
    with open("/tmp/test2.o", "rb") as f:
        object2 = f.read()

    assert object1 == object2


def test_compile_to_object_cpp() -> None:
    input_code = """#include <iostream>
                    void foo(int a){ std::cout<< a; }
                 """
    program = SourceProgram(code=input_code, language=Language.CPP)
    compiler = CompilerExe(CompilerProject.GCC, Path("gcc"), "")
    cs = CompilationSetting(compiler=compiler, opt_level=OptLevel.O2)
    cs.compile_program_to_object(
        program,
        Path("/tmp/test1.o"),
    )

    run_cmd("strip /tmp/test1.o")
    with open("/tmp/test1.o", "rb") as f:
        object1 = f.read()

    with TemporaryFile(contents=program.code, suffix=program.get_file_suffix()) as f:
        cmd = f"g++ {f} -o /tmp/test2.o -O2 -c"
        run_cmd(cmd)

    run_cmd("strip /tmp/test2.o")
    with open("/tmp/test2.o", "rb") as f:
        object2 = f.read()

    assert object1 == object2


def test_compile_to_exec() -> None:
    input_code = "int foo(int a){ return a + 1; } int main(){return foo(1);}"
    program = SourceProgram(code=input_code, language=Language.C)
    compiler = CompilerExe(CompilerProject.GCC, Path("gcc"), "")
    cs = CompilationSetting(compiler=compiler, opt_level=OptLevel.O2)
    cs.compile_program_to_executable(
        program,
        Path("/tmp/test1.exe"),
    )
    assert which("/tmp/test1.exe")
    run_cmd("strip /tmp/test1.exe")
    with open("/tmp/test1.exe", "rb") as f:
        exe1 = f.read()

    with TemporaryFile(contents=program.code, suffix=program.get_file_suffix()) as f:
        cmd = f"gcc {f} -o /tmp/test2.exe -O2 "
        run_cmd(cmd)

    assert which("/tmp/test2.exe")
    run_cmd("strip /tmp/test2.exe")
    with open("/tmp/test2.exe", "rb") as f:
        exe2 = f.read()

    assert exe1 == exe2
