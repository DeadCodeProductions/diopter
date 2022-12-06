from pathlib import Path

import pytest

from diopter.compiler import parse_compile_settings_from_string

path = Path(__file__).parent / Path("commands.txt")
with open(path, "r") as f:
    LINES = f.readlines()


def filter_set(s: str) -> bool:
    s = s.strip()
    if s == "-c":
        return False
    if s == "-S":
        return False
    return bool(s)


MANUAL_TESTS = [
    "gcc -I/kjlkj/kl -Os",  # No source provided test
]


@pytest.mark.parametrize("line", MANUAL_TESTS)
def test_parsing_compile_settings(line: str) -> None:

    csetting, macros, sources, output = parse_compile_settings_from_string(line)
    # Reassemble CMD
    cmd = (
        f"{csetting.compiler.exe} "
        + ("-D" + " -D".join(macros) if macros else "")
        + f" -{csetting.opt_level.name} "
        + ((" ".join(csetting.flags) + " ") if csetting.flags else "")
        + (
            (" -I" + " -I".join(csetting.include_paths))
            if csetting.include_paths
            else ""
        )
        + (
            (" -isystem " + " -isystem ".join(csetting.system_include_paths))
            if csetting.system_include_paths
            else ""
        )
        + (f" -o {output}" if output else "")
        + (" " + " ".join(sources) if sources else "")
    )

    csetting_2, macros_2, sources_2, output_2 = parse_compile_settings_from_string(cmd)

    assert set([p.strip() for p in line.split(" ") if filter_set(p)]) == set(
        [p.strip() for p in cmd.split(" ") if filter_set(p)]
    )

    assert csetting == csetting_2
    assert macros == macros_2
    assert sources == sources_2
    assert output == output_2
