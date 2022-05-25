from __future__ import annotations

from dataclasses import dataclass
from typing import Union, Optional, TypeAlias


@dataclass
class Label:
    identifier: str


@dataclass
class Global:
    type_: str
    value: Union[str, int, Label]


Immediate: TypeAlias = Union[Label, int]


@dataclass
class Register:
    # XXX: these can be interned
    name: str
    width: int

    @staticmethod
    def from_str(reg: str) -> Register:
        if reg[0] == "%":
            reg = reg[1:]
        return Register(get_register_core(reg), get_register_length(reg))

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, Register):
            return NotImplemented
        return self.name == other.name and self.width == other.width

    def __lt__(self, other: Register) -> bool:
        if not isinstance(other, Register):
            return NotImplemented
        return self.name == other.name and self.width < other.width

    def __le__(self, other: Register) -> bool:
        if not isinstance(other, Register):
            return NotImplemented
        return self.name == other.name and self.width <= other.width


@dataclass
class ImmediateAddress:
    imm: Immediate


@dataclass
class IndirectAddress:
    base: Register
    disp: Optional[int] = None
    index: Optional[Register] = None
    scale: Optional[int] = None


@dataclass
class RipRelativeAddress:
    base: Register
    offset: Immediate


Address: TypeAlias = Union[ImmediateAddress, IndirectAddress, RipRelativeAddress]

Operand: TypeAlias = Union[Register, Immediate, Address]


@dataclass
class Instruction:
    name: str
    op1: Optional[Operand] = None
    op2: Optional[Operand] = None
    op3: Optional[Operand] = None


AsmLine: TypeAlias = Union[Instruction, Label, Global]


def get_register_core(reg: str) -> str:
    if reg[0] == "r" and reg[1:].isdigit():
        core = reg[1:]
    elif reg[0] == "r" and reg[1:-1].isdigit():
        core = reg[1:-1]
    elif reg[0] in ["r", "e"]:
        core = reg[1] if reg[-1] == "x" else reg[1:]
    elif reg[-1] in ["l", "h", "x"]:
        core = reg[0:-1]
    else:
        core = reg[0:]
    assert core in [
        "a",
        "b",
        "c",
        "d",
        "sp",
        "bp",
        "di",
        "si",
        "ip",
        "8",
        "9",
        "10",
        "11",
        "12",
        "13",
        "14",
        "15",
    ], f"{reg}:{core}"
    return core


def get_register_length(reg: str) -> int:
    if reg in [
        "rax",
        "rbx",
        "rcx",
        "rdx",
        "rbp",
        "rsi",
        "rdi",
        "rip",
        "r8",
        "r9",
        "r10",
        "r11",
        "r12",
        "r13",
        "r14",
        "r15",
    ]:
        return 64
    if reg in [
        "eax",
        "ebx",
        "ecx",
        "edx",
        "ebp",
        "esi",
        "edi",
        "eip",
        "r8d",
        "r9d",
        "r10d",
        "r11d",
        "r12d",
        "r13d",
        "r14d",
        "r15d",
    ]:
        return 32
    if reg in [
        "ax",
        "bx",
        "cx",
        "dx",
        "bp",
        "si",
        "di",
        "ip",
        "r8w",
        "r9w",
        "r10w",
        "r11w",
        "r12w",
        "r13w",
        "r14w",
        "r15w",
    ]:
        return 16
    if reg in [
        "al",
        "bl",
        "cl",
        "dl",
        "ah",
        "bh",
        "ch",
        "dh",
        "bpl",
        "sil",
        "dil",
        "r8b",
        "r9b",
        "r10b",
        "r11b",
        "r12b",
        "r13b",
        "r14b",
        "r15b",
    ]:
        return 8
    raise Exception(f"get_register_length, unknown register {reg}")
