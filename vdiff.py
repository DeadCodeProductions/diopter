#!/usr/bin/env python3

from pathlib import Path
from multiprocessing import cpu_count
from concurrent.futures import ProcessPoolExecutor, as_completed

from diopter.reducer import Reducer
from diopter.reduction_checks import make_interestingness_check
from diopter.generator import CSmithGenerator
from diopter.utils import save_to_tmp_file, run_cmd
from diopter.compiler import CompilerInvocation
from dead_instrumenter.instrumenter import instrument_program, InstrumenterMode
from vrange_parser import read_value_ranges, Range


def instrument(code: str) -> str:
    tmpfile = save_to_tmp_file(code, ".c")

    instrumented_code = instrument_program(
        Path(tmpfile.name),
        InstrumenterMode.ValueRangeTags,
        ["-isystem/usr/include/csmith-2.3.0"],
    )

    with open(tmpfile.name, "r") as f:
        return f.read()


def get_value_ranges(
    instrumented_code: str, compiler: str, opt_level: str
) -> dict[str, Range]:
    vrange_output = CompilerInvocation(
        Path(compiler),
        instrumented_code,
        [opt_level, "-isystem/usr/include/csmith-2.3.0", "-fdump-tree-evrp-alias"],
    ).capture_output_from_generated_file(".evrp")
    return read_value_ranges(vrange_output)


gcc11 = "/zdata/compiler_cache/gcc-releases-gcc-11.1.0/bin/gcc"
gcc12 = "/zdata/compiler_cache/gcc-6f14b4e385d0b2221557faf40fb24eacf22ca7f8/bin/gcc"

gcc11 = "/home/theo/gccs/gcc-releases-gcc-11.1.0/bin/gcc"
gcc12 = "/home/theo/gccs/gcc-6f14b4e385d0b2221557faf40fb24eacf22ca7f8/bin/gcc"


def is_range_interesting(a: Range, b: Range) -> bool:
    if a.inverse != b.inverse or a.type_ != b.type_:
        return True
    return a.lower_bound < b.lower_bound or a.upper_bound > b.upper_bound


def get_differing_value_ranges_from_instrumented(
    instrumented_code: str,
) -> list[tuple[str, Range, Range]]:
    # return [instrumented_code, list[tag,gcc_11_range,gcc_12_range]]
    g11_vr = get_value_ranges(instrumented_code, gcc11, "-O3")
    g12_vr = get_value_ranges(instrumented_code, gcc12, "-O3")
    diff_ranges = []
    for tag in g11_vr.keys() & g12_vr.keys():
        tag_vr_g11 = g11_vr[tag]
        tag_vr_g12 = g12_vr[tag]
        if is_range_interesting(tag_vr_g12, tag_vr_g11):
            diff_ranges.append((tag, tag_vr_g11, tag_vr_g12))

    return diff_ranges


def get_differing_value_ranges(code: str) -> tuple[str, str, list[tuple[str, Range, Range]]]:
    # return [code, instrumented_code, list[tag,gcc_11_range,gcc_12_range]]
    instrumented_code = instrument(code)
    return code, instrumented_code, get_differing_value_ranges_from_instrumented(
        instrumented_code
    )

def reduction_check(code: str) -> bool:
    return len(get_differing_value_ranges(code)) > 0

if __name__ == "__main__":

    # interesting_cases = []

    # with ProcessPoolExecutor(cpu_count()) as p:
        # futures = []
        # for case_ in CSmithGenerator().generate_code_parallel(100, p):
            # futures.append(p.submit(get_differing_value_ranges, case_))

        # for future in as_completed(futures):
            # code, instrumented_code, interesting_ranges = future.result()
            # if interesting_ranges:
                # with open("interesting_case", "w") as f:
                    # f.write(code)
                # exit(2)
                # interesting_cases.append((instrumented_code, interesting_ranges))


    with open("interesting_case", "r") as f:
        instrumented_code = f.read()




    Reducer().reduce(
        instrumented_code,
        make_interestingness_check(
            reduction_check, True, "-I/usr/include/csmith-2.3.0", {}
        ),
    )


    # for instrumented_code, _ in interesting_cases:
    # Reducer().reduce(
    # instrumented_code,
    # make_interestingness_check(
    # reduction_check, True, "-I/usr/include/csmith-2.3.0", {}
    # ),
    # )


    # while True:
    # print("Trying new case")
    # code = CSmithGenerator().generate_code()

    #
    # /zdata/compiler_cache/gcc-releases-gcc-10.3.0/bin/gcc

    #
