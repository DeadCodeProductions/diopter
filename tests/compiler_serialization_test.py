from pathlib import Path

import pytest

from diopter.compiler import (
    CompilationSetting,
    CompilerExe,
    CompilerProject,
    Language,
    OptLevel,
    Source,
    SourceFile,
    SourceProgram,
)


def test_setting_serialization() -> None:
    setting0 = CompilationSetting(
        compiler=CompilerExe(CompilerProject.GCC, Path("gcc"), "test"),
        opt_level=OptLevel.O2,
        include_paths=("a", "b"),
        system_include_paths=("sa", "sb"),
        macro_definitions=("M1",),
    )
    setting1 = CompilationSetting(
        compiler=CompilerExe(CompilerProject.LLVM, Path("llvm"), "test"),
        opt_level=OptLevel.O0,
        system_include_paths=("sb",),
    )
    assert setting0 == CompilationSetting.from_json_dict(setting0.to_json_dict())
    assert setting1 == CompilationSetting.from_json_dict(setting1.to_json_dict())


def test_sourceprogram_serialization() -> None:
    p0 = SourceProgram(
        language=Language.C,
        defined_macros=("M1", "M2"),
        include_paths=("a", "b"),
        system_include_paths=("sa", "sb"),
        flags=("-fPIC", "-fno-omit-frame-pointer"),
        code="bla bla",
    )

    assert p0 == SourceProgram.from_json_dict(p0.to_json_dict())
    assert p0 == Source.from_json_dict(p0.to_json_dict())

    p1 = SourceProgram(
        language=Language.CPP,
        defined_macros=("M1",),
        system_include_paths=("sa",),
        code="bla bla blac",
    )

    assert p1 == SourceProgram.from_json_dict(p1.to_json_dict())
    assert p1 == Source.from_json_dict(p1.to_json_dict())

    with pytest.raises(AssertionError):
        SourceFile.from_json_dict(p1.to_json_dict())


def test_sourcefile_serialization() -> None:
    p0 = SourceFile(
        language=Language.C,
        filename=Path("/bla/bla"),
    )

    assert p0 == SourceFile.from_json_dict(p0.to_json_dict())
    assert p0 == Source.from_json_dict(p0.to_json_dict())

    p1 = SourceFile(
        language=Language.CPP,
        defined_macros=("M1",),
        system_include_paths=("sa",),
        filename=Path("bla/bla/blac"),
    )

    assert p1 == SourceFile.from_json_dict(p1.to_json_dict())
    assert p1 == Source.from_json_dict(p1.to_json_dict())

    with pytest.raises(AssertionError):
        SourceProgram.from_json_dict(p1.to_json_dict())
