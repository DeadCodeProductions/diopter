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
    ).capture_output_from_generated_file(".evrp")
    return read_value_ranges(vrange_output)


while True:
    print("Trying new case")
    code = CSmithGenerator().generate_code()
    g11_vr = get_value_ranges(code, "/zdata/compiler_cache/gcc-releases-gcc-11.1.0/bin/gcc", "-O3")
    g12_vr = get_value_ranges(code, "/zdata/compiler_cache/gcc-6f14b4e385d0b2221557faf40fb24eacf22ca7f8/bin/gcc", "-O3")
    print(f"11 tags: {len(g11_vr)}")
    print(f"12 tags: {len(g12_vr)}")
    print(f"common:  {len(g12_vr.keys() & g11_vr.keys())}")

    for tag in g11_vr.keys() & g12_vr.keys():
        tag_vr_g11 = g11_vr[tag]
        tag_vr_g12 = g12_vr[tag]
        if tag_vr_g11 != tag_vr_g12:
            print(tag)
            print(f"G11: {tag_vr_g11}")
            print(f"G12: {tag_vr_g12}")

# 
# /zdata/compiler_cache/gcc-releases-gcc-10.3.0/bin/gcc

#   
