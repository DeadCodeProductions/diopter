from __future__ import annotations

from multiprocessing import cpu_count
from pathlib import Path

from diopter.compiler import CompilerExe, CompilerProject
from diopter.git import GitRepository, GitRevision
from diopter.utils import run_cmd_to_logfile


def make_build_dir(ws_dir: Path) -> Path:
    assert ws_dir.exists()
    build_dir = ws_dir / "build"
    build_dir.mkdir(exist_ok=True)
    return build_dir


def configure_llvm(ws_dir: Path, output_prefix: Path) -> Path:
    build_dir = make_build_dir(ws_dir)
    run_cmd_to_logfile(
        [
            "cmake",
            "-G",
            "Ninja",
            "-DCMAKE_BUILD_TYPE=Release",
            "-DCMAKE_INSTALL_PREFIX=" + str(output_prefix),
            "-DLLVM_ENABLE_PROJECTS=clang",
            "-DLLVM_TARGETS_TO_BUILD=X86",
            "-DLLVM_INCLUDE_TESTS=OFF",
            "-DLLVM_INCLUDE_BENCHMARKS=OFF",
            "-DLLVM_INCLUDE_EXAMPLES=OFF",
            "-DLLVM_INCLUDE_DOCS=OFF",
            "-DLLVM_BUILD_LLVM_DYLIB=ON",
            str(ws_dir / "llvm"),
        ],
        additional_env={"CC": "clang", "CXX": "clang++"},
        log_file=open("/tmp/cbuilder.log", "a"),
        working_dir=build_dir,
    )
    return build_dir


def build_llvm(
    revision: GitRevision, repo: GitRepository, output_prefix: Path, jobs: int
) -> CompilerExe:
    ws = repo.get_workspace(revision)
    build_dir = configure_llvm(ws.path(), output_prefix)
    run_cmd_to_logfile(
        ["ninja", "-j", str(jobs)],
        log_file=open("/tmp/cbuilder.log", "a"),
        working_dir=build_dir,
    )

    run_cmd_to_logfile(
        ["ninja", "install", str(jobs)],
        log_file=open("/tmp/cbuilder.log", "a"),
        working_dir=build_dir,
    )
    return CompilerExe(
        CompilerProject.LLVM, output_prefix / "bin" / "clang", str(revision)
    )


def configure_gcc(ws_dir: Path, output_prefix: Path) -> Path:
    build_dir = make_build_dir(ws_dir)
    with open("/tmp/cbuilder.log", "a") as log_file:
        run_cmd_to_logfile(
            "./contrib/download_prerequisites", log_file=log_file, working_dir=ws_dir
        )
        run_cmd_to_logfile(
            [
                "../configure",
                "--prefix={output_prefix}",
                "--disable-bootstrap",
                "--disable-multilib",
                "--enable-languages=c,c++",
                "--disable-libsanitizer",
                "--without-isl",
                "--disable-cet",
                "--disable-libstdcxx-pch",
                "--disable-static",
                "--disable-multilib",
            ],
            log_file=log_file,
            additional_env={"CC": "gcc", "CXX": "g++"},
            working_dir=build_dir,
        )
    return build_dir


def build_gcc(
    revision: GitRevision, repo: GitRepository, output_prefix: Path, jobs: int
) -> CompilerExe:
    ws = repo.get_workspace(revision)
    build_dir = configure_gcc(ws.path(), output_prefix)
    run_cmd_to_logfile(
        ["make", "-j", str(jobs)],
        log_file=open("/tmp/cbuilder.log", "a"),
        working_dir=build_dir,
    )
    run_cmd_to_logfile(
        ["make", "install-strip", str(jobs)],
        log_file=open("/tmp/cbuilder.log", "a"),
        working_dir=build_dir,
    )
    return CompilerExe(
        CompilerProject.GCC, output_prefix / "bin" / "gcc", str(revision)
    )


class CompilerBuildRegistry:
    def add_revision(
        self, project: CompilerProject, revision: GitRevision, output_prefix: Path
    ) -> None:
        pass

    def get_revision(
        self, project: CompilerProject, revision: GitRevision
    ) -> CompilerExe | None:
        pass

    def get_next_built_revision(
        self, project: CompilerProject, revision: GitRevision
    ) -> CompilerExe | None:
        pass

    def get_previous_built_revision(
        self, project: CompilerProject, revision: GitRevision
    ) -> CompilerExe | None:
        pass

    def get_closest_built_revision(
        self, project: CompilerProject, revision: GitRevision
    ) -> CompilerExe | None:
        pass

    @staticmethod
    def from_path(path: Path) -> CompilerBuildRegistry:
        raise NotImplementedError()

    def dump_to_file(self, path: Path) -> None:
        raise NotImplementedError()


def build_compiler(
    project: CompilerProject,
    revision: GitRevision,
    repo: GitRepository,
    installation_prefix: Path,
    registry: CompilerBuildRegistry,
    jobs: int = cpu_count(),
) -> CompilerExe:
    if compiler := registry.get_revision(project, revision):
        return compiler
    match project:
        case CompilerProject.LLVM:
            return build_llvm(revision, repo, installation_prefix, jobs)
        case CompilerProject.GCC:
            return build_gcc(revision, repo, installation_prefix, jobs)
        case _:
            raise NotImplementedError(f"Project {project} not implemented")
