from pathlib import Path

from diopter.compiler import (
    CompilationSetting,
    CompilerExe,
    CompilerProject,
    Language,
    ObjectCompilationOutput,
    OptLevel,
    SourceProgram,
)
from diopter.generator import find_csmith_include_path
from diopter.utils import standard_includes


def test_preprocessor_do_not_expand_includes() -> None:
    gcc = CompilationSetting(
        compiler=CompilerExe(CompilerProject.GCC, Path("gcc"), ""),
        opt_level=OptLevel.O0,
    )

    program = SourceProgram(
        language=Language.C,
        code="""
            #include <assert.h>
            """,
    )

    pp = gcc.preprocess_program(program, do_not_expand_includes=("assert.h",))
    print(pp.code)
    assert "#include <assert.h>" in pp.code


def test_preprocessor_do_not_expand_includes_slashes() -> None:
    gcc = CompilationSetting(
        compiler=CompilerExe(CompilerProject.GCC, Path("gcc"), ""),
        opt_level=OptLevel.O0,
    )

    program = SourceProgram(
        language=Language.C,
        code="""
            #include <test/slash/included.h>
            """,
    )

    pp = gcc.preprocess_program(
        program, do_not_expand_includes=("test/slash/included.h",)
    )
    print(pp.code)
    assert "#include <test/slash/included.h>" in pp.code


CSMITH_FILE = Path(__file__).parent / "csmith_test_source.c"


def test_preprocessor_csmith_gcc_and_clang() -> None:
    gcc = CompilationSetting(
        compiler=CompilerExe(CompilerProject.GCC, Path("gcc"), ""),
        opt_level=OptLevel.O1,
        flags=("-march=native",),
    )
    clang = CompilationSetting(
        compiler=CompilerExe(CompilerProject.GCC, Path("clang"), ""),
        opt_level=OptLevel.O1,
    )

    with open(CSMITH_FILE, "r") as f:
        code = f.read()
    source = SourceProgram(
        code=code,
        language=Language.C,
        system_include_paths=(find_csmith_include_path(),),
    )
    pp_with_gcc = gcc.preprocess_program(
        source, do_not_expand_includes=standard_includes()
    )
    pp_with_clang = clang.preprocess_program(
        source, do_not_expand_includes=standard_includes()
    )

    additional_flags = (
        "-Wno-constant-conversion",
        "-Wno-unused-value",
        "-Wno-tautological-constant-out-of-range-comparison",
        "-Wno-tautological-constant-out-of-range-compare",
    )

    gcc.compile_program(
        pp_with_clang,
        ObjectCompilationOutput(Path("/dev/null")),
        additional_flags=additional_flags,
    )
    clang.compile_program(
        pp_with_gcc,
        ObjectCompilationOutput(Path("/dev/null")),
        additional_flags=additional_flags,
    )
