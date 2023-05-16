from pathlib import Path
from shutil import which

import pytest

from diopter.compiler import (
    CompilerExe,
    CompilerProject,
    Language,
    SourceProgram,
    parse_compiler,
)
from diopter.sanitizer import Sanitizer


def find_clang() -> CompilerExe | None:
    v = ["-10", "-11", "-12", "-13", "-14", "-15", "-16", ""]
    v.reverse()

    for version in v:
        path = Path("clang" + version)
        project_revision = parse_compiler(path)
        assert project_revision
        if which(path):
            return CompilerExe(CompilerProject.LLVM, path, project_revision[1])

    return None


def test_check_for_compiler_warnings() -> None:
    # TODO: Can I find a test case that only clang
    # catches and a test case that only gcc catches?

    clang = find_clang()
    assert clang, "Could not find a clang executable"
    san = Sanitizer(clang=clang)
    p1 = SourceProgram(
        code="int main(){return 0;}",
        language=Language.C,
    )

    assert san.check_for_compiler_warnings(p1)

    p2 = SourceProgram(
        code="void main(){}",
        language=Language.C,
    )

    assert san.check_for_compiler_warnings(p2).check_warnings_failed

    p2 = SourceProgram(
        code="v main(){}",
        language=Language.C,
    )
    assert san.check_for_compiler_warnings(p2).check_warnings_failed


@pytest.mark.parametrize(
    "code",
    [
        "int main(){ int a[1] = {0}; return a[1];}",
        "int printf(const char *, ...); int main()"
        '{int a = 2147483647;printf("a+1: %d", a+1);}',
    ],
)
def test_sanitizer(code: str) -> None:
    clang = find_clang()
    assert clang, "Could not find a clang executable"
    san = Sanitizer(clang=clang, debug=True)
    p = SourceProgram(code=code, language=Language.C)
    assert san.check_for_ub_and_address_sanitizer_errors(p).ub_address_sanitizer_failed


if __name__ == "__main__":
    test_check_for_compiler_warnings()
