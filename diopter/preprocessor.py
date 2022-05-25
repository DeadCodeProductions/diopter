import os
import re
import shutil
import tempfile
from pathlib import Path
from typing import Generator, Iterable, Optional

from diopter.utils import save_to_tmp_file, run_cmd


"""
Functions to preprocess code for creduce.
See creduce --help to see what it wants.
"""


class PreprocessError(Exception):
    pass


def find_platform_main_end(lines: Iterable[str]) -> Optional[int]:
    p = re.compile(".*platform_main_end.*")
    for i, line in enumerate(lines):
        if p.match(line):
            return i
    return None


def remove_platform_main_begin(lines: Iterable[str]) -> list[str]:
    p = re.compile(".*platform_main_begin.*")
    return [line for line in lines if not p.match(line)]


def remove_print_hash_value(lines: Iterable[str]) -> list[str]:
    p = re.compile(".*print_hash_value = 1.*")
    return [line for line in lines if not p.match(line)]


def preprocess_csmith_file(
    path: os.PathLike[str], compiler: str, flags: list[str]
) -> str:

    with tempfile.NamedTemporaryFile(suffix=".c") as tf:
        shutil.copy(path, tf.name)

        cmd = [
            compiler,
            tf.name,
            "-P",
            "-E",
        ] + flags
        lines = run_cmd(cmd).split("\n")
        platform_main_end_line = find_platform_main_end(lines)
        if not platform_main_end_line:
            raise PreprocessError("Couldn't find 'platform_main_end'")

        lines = lines[platform_main_end_line + 1 :]
        lines = remove_print_hash_value(remove_platform_main_begin(lines))
        lines = [
            "typedef unsigned int size_t;",
            "typedef signed char int8_t;",
            "typedef short int int16_t;",
            "typedef int int32_t;",
            "typedef long long int int64_t;",
            "typedef unsigned char uint8_t;",
            "typedef unsigned short int uint16_t;",
            "typedef unsigned int uint32_t;",
            "typedef unsigned long long int uint64_t;",
            "int printf (const char *, ...);",
            "void __assert_fail (const char *__assertion, const char *__file, unsigned int __line, const char *__function);",
            "static void",
            "platform_main_end(uint32_t crc, int flag)",
        ] + list(lines)

        return "\n".join(lines)


def preprocess_csmith_code(code: str, compiler: str, flags: list[str]) -> Optional[str]:
    """Will *try* to preprocess code as if it comes from csmith.

    Args:
        code (str): code to preprocess
        compiler (str): the compiler to use for preprocessing

    Returns:
        Optional[str]: preprocessed code if it was able to preprocess it.
    """
    tf = save_to_tmp_file(code, ".c")
    try:
        res = preprocess_csmith_file(Path(tf.name), compiler, flags)
        return res
    except PreprocessError:
        return None
