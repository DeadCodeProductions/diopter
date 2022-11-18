""" Preprocessing of csmith files in a compiler portable manner

Example:

csmith_program: SourceProgram = ...
preprocessed_csmith_program = preprocess_csmith_program(csmith_program)
if preprocess_csmith_program:
    # preprocessing was successful
"""

import re
from dataclasses import replace
from typing import Optional

from diopter.compiler import (
    CompilationSetting,
    CompileError,
    CompilerExe,
    OptLevel,
    SourceProgram,
)


def preprocess_lines(lines: list[str]) -> str:
    start_patterns = [
        re.compile(r"^extern.*"),
        re.compile(r"^typedef.*"),
        re.compile(r"^struct.*"),
        # The following patterns are to catch if the last of the previous
        # patterns in the file was tainted and we'd otherwise mark the rest
        # of the file as tainted, as we'll find no end in this case.
        re.compile(r"^static.*"),
        re.compile(r"^void.*"),
    ]
    taint_patterns = [
        re.compile(r".*__access__.*"),  # LLVM doesn't know about this
        re.compile(r".*__malloc__.*"),
        re.compile(
            r".*_[F|f]loat[0-9]{1,3}x{0,1}.*"
        ),  # https://gcc.gnu.org/onlinedocs/gcc/Floating-Types.html#Floating-Types
        re.compile(r".*__asm__.*"),  # CompCert has problems
    ]

    def is_start(line: str) -> bool:
        return any([p_start.match(line) for p_start in start_patterns])

    lines_to_skip: list[int] = []
    for i, line in enumerate(lines):
        for p in taint_patterns:
            if p.match(line):
                # Searching for start of tainted region
                up_i = i
                up_line = lines[up_i]
                while up_i > 0 and not is_start(up_line):
                    up_i -= 1
                    up_line = lines[up_i]

                # Searching for end of tainted region
                down_i = i + 1
                down_line = lines[down_i]
                while down_i < len(lines) and not is_start(down_line):
                    down_i += 1
                    down_line = lines[down_i]

                lines_to_skip.extend(list(range(up_i, down_i)))

    return "\n".join([line for i, line in enumerate(lines) if i not in lines_to_skip])


def preprocess_csmith_program(
    program: SourceProgram, compiler: CompilerExe
) -> Optional[SourceProgram]:
    """Will *try* to preprocess code as if it comes from csmith.

    Args:
        program (SourceProgram):
            program to preprocess
        compiler (CompilerExe):
            the compiler to use for preprocessing

    Returns:
        Optional[SourceProgram]:
            preprocessed program if it was able to preprocess it.
    """

    try:
        result = CompilationSetting(
            compiler=compiler, opt_level=OptLevel.O0
        ).preprocess_program(program)
        return replace(
            program,
            code=preprocess_lines(result.stdout_stderr_output.split("\n")),
            system_include_paths=tuple(
                path
                for path in program.system_include_paths
                if not path.endswith("csmith.h")
            ),
        )
    except CompileError:
        return None
