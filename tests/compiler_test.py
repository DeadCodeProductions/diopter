from pathlib import Path

from diopter.compiler import CompilerExe, CompilerProject


def test_compiler_exe_from_path() -> None:
    clang = CompilerExe.from_path(Path("clang-14"))
    assert clang.exe == Path("clang-14")
    assert "14." in clang.revision
    assert clang.project == CompilerProject.LLVM
