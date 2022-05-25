import re
from collections import defaultdict
from typing import Optional

from diopter.x86 import (
    AsmLine,
    Instruction,
    Register,
    Address,
    Label,
    RipRelativeAddress,
)
from diopter.x86_parser import parse_x86
from diopter.utils import get_asm_str


def strip_csmith_static_from_globals(src: str) -> str:
    new_lines = []
    for line in src.split("\n"):
        if not line.startswith("static") or not "g_" in line:
            new_lines.append(line)
            continue
        new_lines.append(line[7:])

    return "\n".join(new_lines)


def normalize_global_with_offset(g: str) -> str:
    if "+" not in g:
        return g
    t1, t2 = g.split("+")
    try:
        int(t1)
        return t1 + "+" + t2
    except:
        return t2 + "+" + t1


def find_first_previous_modification_of_register_within_bb(
    reg: Register, starting_line: int, asm_lines: list[AsmLine]
) -> Optional[int]:
    for line_n in range(starting_line - 1, -1, -1):
        line = asm_lines[line_n]

        match line:
            case Label(_):
                return None
            case Instruction(_, Register(reg.name, _), None, None) | Instruction(
                _, _, Register(reg.name, _), None
            ) | Instruction(_, _, _, Register(reg.name, _)):
                return line_n

    return None


def previous_instr_modifying_source_register_of_write(
    line: int, asm_lines: list[AsmLine]
) -> Optional[Instruction]:
    if line == 0:
        return None

    instr = asm_lines[line]
    if not isinstance(instr, Instruction):
        return None

    if not instr.name.startswith("mov"):
        return None
    if not isinstance(instr.op1, Register):
        return None

    previous_mod_line = find_first_previous_modification_of_register_within_bb(
        instr.op1, line, asm_lines
    )

    if previous_mod_line is None:
        return None

    prev_instr = asm_lines[previous_mod_line]
    assert isinstance(prev_instr, Instruction)
    return prev_instr


def is_write_from_xored_register(line: int, asm_lines: list[AsmLine]) -> bool:
    prev_instr = previous_instr_modifying_source_register_of_write(line, asm_lines)
    if not prev_instr or not isinstance(prev_instr, Instruction):
        return False
    instr = asm_lines[line]
    assert isinstance(instr, Instruction)
    if not prev_instr.name.startswith("xor"):
        return False
    assert isinstance(prev_instr.op1, Register)
    assert isinstance(instr.op1, Register)
    return prev_instr.op1 == prev_instr.op2 and instr.op1 <= prev_instr.op1


def is_write_from_constant_register(
    line: int, asm_lines: list[AsmLine]
) -> Optional[int]:
    prev_instr = previous_instr_modifying_source_register_of_write(line, asm_lines)
    if not prev_instr or not isinstance(prev_instr, Instruction):
        return None
    instr = asm_lines[line]
    assert isinstance(instr, Instruction)
    if not prev_instr.name.startswith("mov"):
        return None
    assert isinstance(prev_instr.op2, Register)
    assert isinstance(instr.op1, Register)
    if isinstance(prev_instr.op1, int) and instr.op1 <= prev_instr.op2:
        return prev_instr.op1
    else:
        return None


def find_constant_globals(asm_lines: list[AsmLine]) -> tuple[dict[str, int], set[str]]:
    writes_to_globals = defaultdict(list)
    # p = re.compile(r".*mov.*\s(.*),\s+(.*)\(%rip\)")
    for i, line in enumerate(asm_lines):
        if not isinstance(line, Instruction):
            continue
        instr: Instruction = line
        if not instr.name.startswith("mov"):
            continue
        if isinstance(instr.op2, RipRelativeAddress) and isinstance(
            instr.op2.offset, Label
        ):
            writes_to_globals[
                normalize_global_with_offset(instr.op2.offset.identifier)
            ].append((i, instr.op1))

    constant_globals = {}
    non_constant_globals = set()
    for g, writes in writes_to_globals.items():
        if len(writes) != 1:
            non_constant_globals.add(g)
            continue
        line_number, value = next(writes.__iter__())
        match value:
            case int(i):
                constant_globals[g] = i
            case Register(n, w):
                if is_write_from_xored_register(line_number, asm_lines):
                    constant_globals[g] = 0
                elif (
                    constant := is_write_from_constant_register(line_number, asm_lines)
                ) is not None:
                    constant_globals[g] = constant
                else:
                    non_constant_globals.add(g)
            case _:
                non_constant_globals.add(g)

    return constant_globals, non_constant_globals


def has_different_global_constants(
    code: str, compiler1: str, compiler2: str, flags: str
) -> bool:
    asm1 = get_asm_str(code, compiler1, flags.split(" "))
    asm2 = get_asm_str(code, compiler2, flags.split(" "))
    assert asm1 and asm2
    gconst1, gnconst1 = find_constant_globals(parse_x86(asm1))
    gconst2, gnconst2 = find_constant_globals(parse_x86(asm2))

    if (gconst1.keys() - gconst2.keys()) & gnconst2:
        return True
    if (gconst2.keys() - gconst1.keys()) & gnconst1:
        return True
    return False
