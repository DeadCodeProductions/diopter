import inspect
from typing import Callable
from pathlib import Path

from diopter.utils import get_asm_str
from diopter.sanitizer import sanitize_file


def emit_module_imports(
    check: Callable[..., bool], sanitize: bool, sanitize_flags: str
) -> str:
    this_source_file = inspect.getsourcefile(emit_module_imports)
    assert this_source_file
    diopter_init = str(Path(this_source_file).parent / "__init__.py")

    check_name = check.__name__
    check_module_path = inspect.getsourcefile(check)
    assert check_module_path
    check_module = inspect.getmodulename(check_module_path)

    prologue = f"""import importlib
import sys

spec = importlib.util.spec_from_file_location("diopter", "{diopter_init}")
module = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = module
spec.loader.exec_module(module)

spec = importlib.util.spec_from_file_location("{check_module}", "{check_module_path}")
module = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = module
spec.loader.exec_module(module)

from {check_module} import {check_name}
"""
    if sanitize:
        sanitize_name = sanitize_file.__name__
        sanitize_module_path = inspect.getsourcefile(sanitize_file)
        assert sanitize_module_path
        sanitize_module = inspect.getmodulename(sanitize_module_path)
        prologue += f"""
spec = importlib.util.spec_from_file_location("{sanitize_module}", "{sanitize_module_path}")
module = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = module
spec.loader.exec_module(module)

from {sanitize_module} import {sanitize_name}

if not {sanitize_name}("gcc", "clang", "ccomp", "code.c", "{sanitize_flags}"):
    exit(1)

"""
    return prologue


def emit_call(check: Callable[..., bool], **kwargs: str) -> str:
    if not kwargs:
        call = "exit(not " + check.__name__ + "(code))"
    else:
        call = (
            "exit(not "
            + check.__name__
            + "(code, "
            + ", ".join(f'{k} = "{v}"' for k, v in kwargs.items())
            + "))"
        )
    return f"""with open(\"code.c\", \"r\") as f:
    code = f.read()
{call}
    """


def make_interestingness_check(
    check: Callable[..., bool], sanitize: bool, sanitize_flags: str, **kwargs: str
) -> str:
    """
    Helper function to create a script useful for use with diopter.Reducer

    Args:
        check: a Python function that implements the check, its first argument
        should be the code (str) to test.
        kwargs: additional arguments passed to the check, these hardcoded in
        the script

    Returns:
        The script
    """
    prologue = "#!/usr/bin/env python3"
    return "\n".join(
        (
            prologue,
            emit_module_imports(check, sanitize, sanitize_flags),
            emit_call(check, **kwargs),
        )
    )
