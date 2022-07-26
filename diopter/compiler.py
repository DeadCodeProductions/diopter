import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from diopter.utils import (
    get_asm_str,
    save_to_tmp_file,
    run_cmd,
    CompileError,
    CompileContext,
    TempDirEnv,
)


@dataclass
class CompilerInvocation:
    compiler_binary: Path
    code: str
    flags: list[str]

    def get_asm(self) -> Optional[str]:
        return get_asm_str(self.code, str(self.compiler_binary), self.flags)

    def get_compilation_log(self) -> str:
        with CompileContext(self.code) as context:
            code_file, _ = context
            cmd = (
                f"{self.compiler_binary} -o /dev/null {code_file}".split() + self.flags
            )
            try:
                output = run_cmd(cmd)
            except subprocess.CalledProcessError:
                # capture the error and bundle it in CompilerError?
                raise CompileError()
        return output

    def capture_output_from_generated_file(self, file_suffix: str) -> str:
        with TempDirEnv(change_dir=True) as tdir:
            with save_to_tmp_file(self.code, ".c") as code_file:
                cmd = (
                    f"{self.compiler_binary} -c -o /dev/null {code_file.name}".split()
                    + self.flags
                )
                try:
                    # print(" ".join(cmd))
                    # while True:
                    # pass
                    run_cmd(cmd)
                except subprocess.CalledProcessError as e:
                    # capture the error and bundle it in CompilerError?
                    raise CompileError(e)
                for file in Path(tdir).glob(f"*{file_suffix}"):
                    with open(file, "r") as f:
                        return f.read()
            return ""
