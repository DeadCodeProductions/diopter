from pathlib import Path
from shutil import which

from diopter.compiler import (
    ASMCompilationOutput,
    CompilationSetting,
    CompilerExe,
    CompilerProject,
    ExeCompilationOutput,
    Language,
    LLVMIRCompilationOutput,
    ObjectCompilationOutput,
    Opt,
    OptLevel,
    SourceProgram,
)
from diopter.utils import run_cmd, temporary_file


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
    asm = cs.compile_program(program, ASMCompilationOutput()).output.read()

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
    res = cs.compile_program(
        program,
        ObjectCompilationOutput(),
    )
    res.output.strip_symbols()
    object1 = res.output.read()

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
    res = cs.compile_program(
        program,
        ObjectCompilationOutput(),
    )

    res.output.strip_symbols()
    object1 = res.output.read()

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
        ExeCompilationOutput(),
    )
    assert which(res.output.filename)
    res.output.strip_symbols()
    exe1 = res.output.read()

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


def test_exe_run() -> None:
    input_code = """
    #include <stdio.h>
    void foo(int argc){
        printf("%d \\n", argc);
    }
    int main(int argc, char* argv[]){
        foo(argc);
    }
    """
    program = SourceProgram(code=input_code, language=Language.C)
    compiler = CompilerExe(CompilerProject.GCC, Path("gcc"), "")
    cs = CompilationSetting(compiler=compiler, opt_level=OptLevel.O2)
    res = cs.compile_program(
        program,
        ExeCompilationOutput(),
    )
    output = res.output.run()
    assert output.stdout.strip() == "1"
    output = res.output.run(("asdf",))
    assert output.stdout.strip() == "2"
    output = res.output.run(("asdf", "fff"))
    assert output.stdout.strip() == "3"


def test_async_compile() -> None:
    input_code = "int foo(int a){ return a + 1; }"
    program = SourceProgram(code=input_code, language=Language.C)
    compiler = CompilerExe(CompilerProject.GCC, Path("gcc"), "")
    cs = CompilationSetting(compiler=compiler, opt_level=OptLevel.O2)
    res1 = cs.compile_program(
        program,
        ObjectCompilationOutput(),
    )
    res1.output.strip_symbols()
    object1 = res1.output.read()

    res2 = cs.compile_program_async(
        program,
        ObjectCompilationOutput(),
    ).result(8)

    res2.output.strip_symbols()
    object2 = res2.output.read()

    assert object1 == object2

    async_res3 = cs.compile_program_async(
        program,
        ObjectCompilationOutput(),
    )
    # calling wait should not change the result
    async_res3.wait(8)
    res3 = async_res3.result(8)
    res3.output.strip_symbols()
    object3 = res3.output.read()

    assert object2 == object3


def test_link() -> None:
    input_code1 = "int foo(int a){ return a + 1; }"
    input_code2 = """
                  int foo(int);
                  int bar(int a){ return foo(a + 1); }
                  """
    input_code3 = """
                  int bar(int);
                  int main(int argc, char* argv){ return bar(argc); }
                  """
    program1 = SourceProgram(code=input_code1, language=Language.C)
    program2 = SourceProgram(code=input_code2, language=Language.C)
    program3 = SourceProgram(code=input_code3, language=Language.C)
    compiler = CompilerExe(CompilerProject.GCC, Path("gcc"), "")
    cs = CompilationSetting(compiler=compiler, opt_level=OptLevel.O2)
    res1 = cs.compile_program(
        program1,
        ObjectCompilationOutput(),
    )
    res2 = cs.compile_program(
        program2,
        ObjectCompilationOutput(),
    )
    res3 = cs.compile_program(
        program3,
        ObjectCompilationOutput(),
    )
    exe_res1 = cs.link_objects(
        (res1.output, res2.output, res3.output), ExeCompilationOutput()
    )
    exe_res1.output.strip_symbols()
    exe_res2 = cs.link_objects_async(
        (res1.output, res2.output, res3.output), ExeCompilationOutput()
    ).result()
    exe_res2.output.strip_symbols()

    code_file1 = temporary_file(
        contents=program1.code, suffix=program1.get_file_suffix()
    )
    code_file2 = temporary_file(
        contents=program2.code, suffix=program2.get_file_suffix()
    )
    code_file3 = temporary_file(
        contents=program3.code, suffix=program3.get_file_suffix()
    )
    object_file1 = temporary_file(contents="", suffix=".o")
    object_file2 = temporary_file(contents="", suffix=".o")
    object_file3 = temporary_file(contents="", suffix=".o")
    run_cmd(f"{compiler.exe} -c -O2 {code_file1.name} -o {object_file1.name}")
    run_cmd(f"{compiler.exe} -c -O2 {code_file2.name} -o {object_file2.name}")
    run_cmd(f"{compiler.exe} -c -O2 {code_file3.name} -o {object_file3.name}")

    exe3_file = temporary_file(contents="", suffix=".exe")
    run_cmd(
        f"{compiler.exe} -O2 {object_file1.name} {object_file2.name} "
        f"{object_file3.name} -o {exe3_file.name}"
    )

    assert which(exe3_file.name)
    exe3 = strip_and_read_binary(Path(exe3_file.name))
    assert exe3 == exe_res1.output.read()
    assert exe3 == exe_res2.output.read()


def get_opt() -> Opt:
    for suffix in ["", "-13", "-14", "-15", "-16", "-17"]:
        opt_path = Path(f"opt{suffix}")
        if not which(opt_path):
            continue
        return Opt.from_path(opt_path)
    assert False, "Could not find opt exe"


def test_opt() -> None:
    input_code = """
    int foo(int a){
        return a + 1;
    }
    """
    program = SourceProgram(code=input_code, language=Language.C)
    clang = CompilerExe.get_system_clang()
    cs = CompilationSetting(compiler=clang, opt_level=OptLevel.O0)
    res = cs.compile_program(program, LLVMIRCompilationOutput())
    llvm_ir = res.output.read()
    opt = get_opt()
    opt_res = opt.run_on_input(res.output.filename, ("-S",))
    assert llvm_ir.strip() != opt_res.stdout.strip()
