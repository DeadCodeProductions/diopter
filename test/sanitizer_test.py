from pathlib import Path
from shutil import which

from ccbuilder import CompilerProject

from diopter.compiler import (
    CompilerExe,
    Language,
    SourceProgram,
    parse_compiler_revision,
)
from diopter.sanitizer import Sanitizer


def find_clang() -> CompilerExe | None:
    v = ["-10", "-11", "-12", "-13", "-14", "-15", "-16", ""]
    v.reverse()

    for version in v:
        path = Path("clang" + version)
        if which(path):
            return CompilerExe(
                CompilerProject.LLVM, path, parse_compiler_revision(path)
            )

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


if __name__ == "__main__":
    test_check_for_compiler_warnings()
