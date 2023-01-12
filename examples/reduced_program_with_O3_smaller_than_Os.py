#!/usr/bin/env python3

"""
In this example diopter is used to generate and reduce a csmith
that results in larger text with -Os than -O3
"""

from pathlib import Path
from tempfile import NamedTemporaryFile

from diopter.compiler import CompilationSetting, CompilerExe, OptLevel, SourceProgram
from diopter.generator import CSmithGenerator
from diopter.reducer import Reducer, ReductionCallback
from diopter.sanitizer import Sanitizer
from diopter.utils import run_cmd


def get_size(program: SourceProgram, setting: CompilationSetting) -> int:
    with NamedTemporaryFile(suffix=".o") as ntf:
        setting.compile_program_to_object(program, Path(ntf.name))
        size_cmd_output = run_cmd(f"size {ntf.name}").stdout
        line = list(size_cmd_output.splitlines())[-1].strip()
        s = line.split()[0]
        return int(s)


def filter(
    program: SourceProgram, O3: CompilationSetting, Os: CompilationSetting
) -> bool:
    O3_size = get_size(program, O3)
    Os_size = get_size(program, Os)
    return O3_size < Os_size


class ReduceObjectSize(ReductionCallback):
    def __init__(
        self,
        san: Sanitizer,
        O3: CompilationSetting,
        Os: CompilationSetting,
    ):
        self.san = san
        self.O3 = O3
        self.Os = Os

    def test(self, program: SourceProgram) -> bool:
        if not self.san.sanitize(program):
            return False
        return filter(program, self.O3, self.Os)


if __name__ == "__main__":
    O3 = CompilationSetting(
        compiler=CompilerExe.get_system_gcc(),
        opt_level=OptLevel.O3,
        flags=("-march=native",),
    )
    Os = CompilationSetting(
        compiler=CompilerExe.get_system_gcc(),
        opt_level=OptLevel.Os,
        flags=("-march=native",),
    )
    sanitizer = Sanitizer()
    while True:
        p = CSmithGenerator(sanitizer).generate_program()
        p = Os.preprocess_program(p, make_compiler_agnostic=True)
        if filter(p, O3, Os):
            break
    print(f"O3 size: {get_size(p, O3)}")
    print(f"Os size: {get_size(p, Os)}")
    rprogram = Reducer().reduce(p, ReduceObjectSize(sanitizer, O3, Os))  # , debug=True)
    assert rprogram
    print(f"O3 size: {get_size(rprogram, O3)}")
    print(f"Os size: {get_size(rprogram, Os)}")
