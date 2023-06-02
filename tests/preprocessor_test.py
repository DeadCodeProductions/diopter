from pathlib import Path

from diopter.compiler import (
    CompilationSetting,
    CompilerExe,
    CompilerProject,
    ObjectCompilationOutput,
    OptLevel,
)
from diopter.generator import CSmithGenerator
from diopter.sanitizer import Sanitizer


def test_preprocessor_make_compiler_agnostic() -> None:
    gcc = CompilerExe(CompilerProject.GCC, Path("gcc"), "")
    clang = CompilerExe(CompilerProject.GCC, Path("clang"), "")

    san = Sanitizer(debug=True)
    gen = CSmithGenerator(san)
    program = gen.generate_program()

    optlevels = [OptLevel.O0, OptLevel.O1, OptLevel.O2, OptLevel.O3, OptLevel.Os]

    for optlevel_preprocess in optlevels:
        for optlevel_test in optlevels:
            gccOp = CompilationSetting(
                compiler=gcc,
                opt_level=optlevel_preprocess,
            )
            clangOp = CompilationSetting(compiler=clang, opt_level=optlevel_preprocess)
            gccOt = CompilationSetting(compiler=gcc, opt_level=optlevel_test)
            clangOt = CompilationSetting(compiler=clang, opt_level=optlevel_test)

            pp_with_gcc = gccOp.preprocess_program(program, make_compiler_agnostic=True)
            gccOt.compile_program(
                pp_with_gcc, ObjectCompilationOutput(Path("/dev/null"))
            )
            clangOt.compile_program(
                pp_with_gcc, ObjectCompilationOutput(Path("/dev/null"))
            )
            san.sanitize(pp_with_gcc)

            pp_with_clang = clangOp.preprocess_program(
                program, make_compiler_agnostic=True
            )
            gccOt.compile_program(
                pp_with_clang, ObjectCompilationOutput(Path("/dev/null"))
            )
            clangOt.compile_program(
                pp_with_clang, ObjectCompilationOutput(Path("/dev/null"))
            )
            san.sanitize(pp_with_clang)
