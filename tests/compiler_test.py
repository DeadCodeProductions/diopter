from pathlib import Path
from shutil import which

from diopter.compiler import (
    ASMCompilationOutput,
    CompilationSetting,
    CompilerExe,
    CompilerProject,
    ExeCompilationOutput,
    Language,
    ObjectCompilationOutput,
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
    asm = cs.compile_program(program, ASMCompilationOutput(None)).output.read()

    tf = temporary_file(contents=program.code, suffix=program.get_file_suffix())
    result = run_cmd(f"gcc {tf.name} -mno-red-zone -o /dev/stdout -O2 -m32 -S")
    asm_manual = result.stdout

    def canonicalize(asm: str) -> str:
        return "\n".join(
            line for line in asm.splitlines() if ".file" not in line
        ).strip()

    assert canonicalize(asm) == canonicalize(asm_manual)


def strip_and_read_binary(path: Path) -> bytes:
    run_cmd(f"strip {path}")
    with open(str(path), "rb") as f:
        return f.read()


def test_compile_to_object() -> None:
    input_code = "int foo(int a){ return a + 1; }"
    program = SourceProgram(code=input_code, language=Language.C)
    compiler = CompilerExe(CompilerProject.GCC, Path("gcc"), "")
    cs = CompilationSetting(compiler=compiler, opt_level=OptLevel.O2)
    object1 = strip_and_read_binary(
        cs.compile_program(
            program,
            ObjectCompilationOutput(None),
        ).output.filename
    )

    code_file = temporary_file(contents=program.code, suffix=program.get_file_suffix())
    object_file2 = temporary_file(contents="", suffix=".o")
    cmd = f"gcc {code_file.name} -o {object_file2.name} -O2 -c"
    run_cmd(cmd)

    object2 = strip_and_read_binary(Path(object_file2.name))

    assert object1 == object2


def test_compile_to_object_cpp() -> None:
    input_code = """#include <iostream>
                    void foo(int a){ std::cout<< a; }
                 """
    program = SourceProgram(code=input_code, language=Language.CPP)
    compiler = CompilerExe(CompilerProject.GCC, Path("gcc"), "")
    cs = CompilationSetting(compiler=compiler, opt_level=OptLevel.O2)
    object1 = strip_and_read_binary(
        cs.compile_program(program, ObjectCompilationOutput(None)).output.filename
    )

    object_file2 = temporary_file(contents="", suffix=".o")
    code_file = temporary_file(contents=program.code, suffix=program.get_file_suffix())
    cmd = f"g++ {code_file.name} -o {object_file2.name} -O2 -c"
    run_cmd(cmd)

    object2 = strip_and_read_binary(Path(object_file2.name))

    assert object1 == object2


def test_compile_to_exec() -> None:
    input_code = "int foo(int a){ return a + 1; } int main(){return foo(1);}"
    program = SourceProgram(code=input_code, language=Language.C)
    compiler = CompilerExe(CompilerProject.GCC, Path("gcc"), "")
    cs = CompilationSetting(compiler=compiler, opt_level=OptLevel.O2)
    res = cs.compile_program(
        program,
        ExeCompilationOutput(None),
    )
    assert which(res.output.filename)
    exe1 = strip_and_read_binary(res.output.filename)

    exe_file2 = temporary_file(contents="", suffix=".exe")
    code_file = temporary_file(contents=program.code, suffix=program.get_file_suffix())
    cmd = f"gcc {code_file.name} -o {exe_file2.name} -O2 "
    run_cmd(cmd)

    assert which(exe_file2.name)
    exe2 = strip_and_read_binary(Path(exe_file2.name))

    assert exe1 == exe2


def test_preprocess() -> None:
    input_code = """
    #define MACRO1 4
    int foo(){
        return MACRO1 + MACRO2;
    }
    """
    program = SourceProgram(code=input_code, language=Language.C)
    compiler = CompilerExe(CompilerProject.GCC, Path("gcc"), "")
    cs = CompilationSetting(compiler=compiler, opt_level=OptLevel.O2)
    pp_code = cs.preprocess_program(program, False, ("-DMACRO2=33",)).code
    assert "".join(pp_code.split()) == "".join(
        "int foo(){ return 4 + 33; }".split()
    ), pp_code
