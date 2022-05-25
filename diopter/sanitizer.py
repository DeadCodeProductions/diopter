import subprocess
import tempfile
import logging
import os
from tempfile import NamedTemporaryFile
from pathlib import Path
from typing import Optional
from types import TracebackType

from diopter.utils import run_cmd, save_to_tmp_file


def get_cc_output(cc: str, file: Path, flags: str, cc_timeout: int) -> tuple[int, str]:
    cmd = [
        cc,
        str(file),
        "-c",
        "-o/dev/null",
        "-Wall",
        "-Wextra",
        "-Wpedantic",
        "-O1",
        "-Wno-builtin-declaration-mismatch",
    ]
    if flags:
        cmd.extend(flags.split())
    try:
        logging.debug(cmd)
        result = subprocess.run(
            cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=cc_timeout
        )
    except subprocess.TimeoutExpired:
        return 1, ""
    except subprocess.CalledProcessError:
        # Possibly a compilation failure
        return 1, ""
    return result.returncode, result.stdout.decode("utf-8")


def check_compiler_warnings(
    clang: str, gcc: str, file: Path, flags: str, cc_timeout: int
) -> bool:
    """
    Check if the compiler outputs any warnings that indicate
    undefined behaviour.

    Args:
        clang (str): Normal executable of clang.
        gcc (str): Normal executable of gcc.
        file (Path): File to compile.
        flags (str): (additional) flags to be used when compiling.
        cc_timeout (int): Timeout for the compilation in seconds.

    Returns:
        bool: True if no warnings were found.
    """
    clang_rc, clang_output = get_cc_output(clang, file, flags, cc_timeout)
    gcc_rc, gcc_output = get_cc_output(gcc, file, flags, cc_timeout)

    if clang_rc != 0 or gcc_rc != 0:
        logging.debug(f"Compilation failed: {clang_output}")
        logging.debug(f"Compilation failed: {gcc_output}")
        return False

    warnings = [
        "conversions than data arguments",
        "incompatible redeclaration",
        "ordered comparison between pointer",
        "eliding middle term",
        "end of non-void function",
        "invalid in C99",
        "specifies type",
        "should return a value",
        "uninitialized",
        "incompatible pointer to",
        "incompatible integer to",
        "comparison of distinct pointer types",
        "type specifier missing",
        "uninitialized",
        "Wimplicit-int",
        "division by zero",
        "without a cast",
        "control reaches end",
        "return type defaults",
        "cast from pointer to integer",
        "useless type name in empty declaration",
        "no semicolon at end",
        "type defaults to",
        "too few arguments for format",
        "incompatible pointer",
        "ordered comparison of pointer with integer",
        "declaration does not declare anything",
        "expects type",
        "comparison of distinct pointer types",
        "pointer from integer",
        "incompatible implicit",
        "excess elements in struct initializer",
        "comparison between pointer and integer",
        "return type of ‘main’ is not ‘int’",
        "past the end of the array",
        "no return statement in function returning non-void",
    ]

    ws = [w for w in warnings if w in clang_output or w in gcc_output]
    if len(ws) > 0:
        logging.debug(f"Compiler warnings found: {ws}")
        return False

    return True


class CCompEnv:
    def __init__(self) -> None:
        self.td: tempfile.TemporaryDirectory[str]

    def __enter__(self) -> Path:
        self.td = tempfile.TemporaryDirectory()
        tempfile.tempdir = self.td.name
        return Path(self.td.name)

    def __exit__(
        self,
        exc_type: Optional[type[BaseException]],
        exc_value: Optional[BaseException],
        exc_traceback: Optional[TracebackType],
    ) -> None:
        tempfile.tempdir = None


def verify_with_ccomp(
    ccomp: str, file: Path, flags: str, compcert_timeout: int
) -> bool:
    """Check if CompCert is unhappy about something.

    Args:
        ccomp (str): Path to ccomp executable or name in $PATH.
        file (Path): File to compile.
        flags (str): Additional flags to use.
        compcert_timeout (int): Timeout in seconds.

    Returns:
        bool: True if CompCert does not complain.
    """
    with CCompEnv() as tmpdir:
        cmd = [
            ccomp,
            str(file),
            "-interp",
            "-fall",
        ]
        if flags:
            cmd.extend(flags.split())
        res = True
        try:
            run_cmd(
                cmd,
                additional_env={"TMPDIR": str(tmpdir)},
                timeout=compcert_timeout,
            )
            res = True
        except subprocess.CalledProcessError:
            res = False
        except subprocess.TimeoutExpired:
            res = False

        logging.debug(f"CComp returncode {res}")

        return res


def use_ub_sanitizers(
    clang: str, file: Path, flags: str, cc_timeout: int, exe_timeout: int
) -> bool:
    """Run clang undefined-behaviour tests

    Args:
        clang (str): Path to clang executable or name in $PATH.
        file (Path): File to test.
        flags (str): Additional flags to use.
        cc_timeout (int): Timeout for compiling in seconds.
        exe_timeout (int): Timeout for running the resulting exe in seconds.

    Returns:
        bool: True if no undefined was found.
    """
    cmd = [clang, str(file), "-O2", "-fsanitize=undefined,address"]
    if flags:
        cmd.extend(flags.split())

    with CCompEnv():
        with tempfile.NamedTemporaryFile(suffix=".exe", delete=False) as exe:
            exe.close()
            os.chmod(exe.name, 0o777)
            cmd.append(f"-o{exe.name}")
            result = subprocess.run(
                cmd,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=cc_timeout,
            )
            if result.returncode != 0:
                logging.debug(f"UB Sanitizer returncode {result.returncode}")
                if os.path.exists(exe.name):
                    os.remove(exe.name)
                return False
            result = subprocess.run(
                exe.name,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=exe_timeout,
            )
            os.remove(exe.name)
            logging.debug(f"UB Sanitizer returncode {result.returncode}")
            return result.returncode == 0


def sanitize_file(
    gcc: str,
    clang: str,
    ccomp: str,
    file: Path,
    flags: str,
    cc_timeout: int = 8,
    exe_timeout: int = 4,
    compcert_timeout: int = 16,
) -> bool:
    """Check if there is anything that could indicate undefined behaviour.

    Args:
        gcc (str): Path to gcc executable or name in $PATH.
        clang (str): Path to clang executable or name in $PATH.
        ccomp (str): Path to ccomp executable or name in $PATH.
        file (Path): File to check.
        flags (str): Additional flags to use.
        cc_timeout (int): Compiler timeout in seconds.
        exe_timeout (int): Undef.-Behaviour. runtime timeout in seconds.
        compcert_timeout (int): CompCert timeout in seconds.

    Returns:
        bool: True if nothing indicative of undefined behaviour is found.
    """
    # Taking advantage of shortciruit logic...
    try:
        return (
            check_compiler_warnings(gcc, clang, file, flags, cc_timeout)
            and use_ub_sanitizers(clang, file, flags, cc_timeout, exe_timeout)
            and verify_with_ccomp(ccomp, file, flags, compcert_timeout)
        )
    except subprocess.TimeoutExpired:
        return False


def sanitize_code(
    gcc: str,
    clang: str,
    ccomp: str,
    code: str,
    flags: str,
    cc_timeout: int = 8,
    exe_timeout: int = 4,
    compcert_timeout: int = 16,
) -> bool:
    """Check if there is anything that could indicate undefined behaviour.

    Args:
        gcc (str): Path to gcc executable or name in $PATH.
        clang (str): Path to clang executable or name in $PATH.
        ccomp (str): Path to ccomp executable or name in $PATH.
        code (str): The code to check.
        flags (str): Additional flags to use.
        cc_timeout (int): Compiler timeout in seconds.
        exe_timeout (int): Undef.-Behaviour. runtime timeout in seconds.
        compcert_timeout (int): CompCert timeout in seconds.

    Returns:
        bool: True if nothing indicative of undefined behaviour is found.
    """
    ntf = save_to_tmp_file(code, ".c")
    return sanitize_file(
        gcc,
        clang,
        ccomp,
        Path(ntf.name),
        flags,
        cc_timeout,
        exe_timeout,
        compcert_timeout,
    )
