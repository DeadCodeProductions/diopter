#!/usr/bin/env python3

from pathlib import Path

from diopter.generator import CSmithGenerator
from diopter.utils import save_to_tmp_file, run_cmd
from diopter.compiler import CompilerInvocation
from dead_instrumenter.instrumenter import instrument_program, InstrumenterMode
from vrange_parser import read_value_ranges


def instrument(code: str) -> str:
    tmpfile = save_to_tmp_file(code, ".c")

    instrumented_code = instrument_program(
        Path(tmpfile.name),
        InstrumenterMode.ValueRangeTags,
        ["-isystem/usr/include/csmith-2.3.0"],
    )

    with open(tmpfile.name, "r") as f:
        return f.read()


def get_value_ranges(code, compiler, opt_level):
    instrumented_code = instrument(code)
    vrange_output = CompilerInvocation(
        compiler,
        instrumented_code,
        [opt_level, "-isystem/usr/include/csmith-2.3.0", "-fdump-tree-evrp-alias"],
    ).capture_output_from_generated_file(".040t.evrp")
    return read_value_ranges(vrange_output)


while True:
    print("Trying new case")
    code = CSmithGenerator().generate_code()
    O2_vr = get_value_ranges(code, "gcc", "-O2")
    O3_vr = get_value_ranges(code, "gcc", "-O3")

    for tag in O2_vr.keys() & O3_vr.keys():
        tag_vr_O2 = O2_vr[tag]
        tag_vr_O3 = O3_vr[tag]
        if tag_vr_O2 != tag_vr_O3:
            print(tag)
            print(f"O2: {tag_vr_O2}")
            print(f"O3: {tag_vr_O3}")
