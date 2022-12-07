from pathlib import Path

import pytest

from diopter.compiler import (
    Language,
    SourceProgram,
    parse_compilation_setting_from_string,
)


def real_world_compiler_invocations() -> list[str]:
    path = Path(__file__).parent / Path("compilation_command_parsing_inputs.txt")
    with open(path, "r") as f:
        return f.readlines()


@pytest.mark.parametrize(
    "line",
    [
        "gcc",
        "gcc -I/kjlkj/kl -Os",  # No source provided test
        "gcc -Os -c -o test.o test.c",
        "g++ -Os -DNDEBUG  -c -MD -MT Dem.cpp.o -MF Dem.cpp.o.d -o Dem.cpp.o",
        "g++ -Os -I/path1 -isystem/path2 -isystem/path3 -isystem /path4 -I /path5",
    ]
    + real_world_compiler_invocations(),
)
def test_parsing_compile_settings(line: str) -> None:
    csetting, sources, output = parse_compilation_setting_from_string(line)
    assert len(sources) <= 1, sources
    for i, flag in enumerate(csetting.flags):
        if flag.endswith(".o"):
            assert csetting.flags[i - 1] in ["-MT", "-MQ"], (
                csetting.flags[i - 1],
                flag,
            )
        assert not flag.endswith(".cpp"), flag
        assert not flag.endswith(".c"), flag
        assert not flag.endswith(".cxx"), flag
        assert not flag.endswith(".cc"), flag
        assert not flag.startswith("-O"), flag
        assert not flag.startswith("-I"), flag
        assert not flag.startswith("-isystem"), flag
        assert flag != "-o"
        assert flag != "-c"
        assert flag != "-S"
        assert flag != "-o"

    for path in csetting.include_paths:
        assert not path.startswith("-I"), path

    for path in csetting.system_include_paths:
        assert not path.startswith("-isystem"), path

    for macro in csetting.macro_definitions:
        assert not macro.startswith("-D"), macro

    if not sources:
        new_sources = ["dummy_source"]
    else:
        new_sources = sources

    cmd = " ".join(
        csetting.get_compilation_cmd(
            (SourceProgram(code="", language=Language.CPP), Path(new_sources[0])),
            output,
            False,
        )
    ).replace("dummy_source", "")

    csetting_2, sources_2, output_2 = parse_compilation_setting_from_string(cmd)

    assert csetting == csetting_2, (line, cmd)
    assert sources == sources_2
    assert output == output_2

    def canonicalize_whitespace(cmd: str) -> str:
        return " ".join(
            cmd.replace("-o", "-o ")
            .replace("-I", "-I ")
            .replace("-isystem", "-isystem ")
            .split()
        )

    line = canonicalize_whitespace(line)
    cmd = canonicalize_whitespace(cmd)
    if "-O0" in cmd and "-O0" not in line:
        line += " -O0"

    assert set(line.split()) == set(cmd.split())
    cmd_cpp = canonicalize_whitespace(
        " ".join(
            csetting.get_compilation_cmd(
                (SourceProgram(code="", language=Language.CPP), Path(new_sources[0])),
                output,
                True,
            )
            + sources
        ).replace("dummy_source", "")
    )
    assert set(cmd_cpp.split()) - set(line.split()) == set((("-xc++",)))
