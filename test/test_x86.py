from diopter.x86 import (
    get_register_core,
    get_register_length,
    Register,
    Global,
    Operand,
    Address,
    Instruction,
    Immediate,
    Label,
    RipRelativeAddress,
    IndirectAddress,
)
from diopter.x86_parser import parse_x86


def test_get_register_length() -> None:
    assert Register.from_str("rax").width == 64
    assert Register.from_str("r15").width == 64
    assert Register.from_str("r8").width == 64
    assert Register.from_str("r8d").width == 32
    assert Register.from_str("ax").width == 16
    assert Register.from_str("ebx").width == 32


def test_get_register_core() -> None:
    assert Register.from_str("rax").name == "a"
    assert Register.from_str("r15").name == "15"
    assert Register.from_str("r8").name == "8"
    assert Register.from_str("r8d").name == "8"
    assert Register.from_str("ax").name == "a"
    assert Register.from_str("ebx").name == "b"
    assert Register.from_str("bh").name == "b"
    assert Register.from_str("bl").name == "b"
    assert Register.from_str("esi").name == "si"
    assert Register.from_str("dil").name == "di"
    assert Register.from_str("rbp").name == "bp"
    assert Register.from_str("r10w").name == "10"
    assert Register.from_str("si").name == "si"
    assert Register.from_str("rip").name == "ip"
    assert Register.from_str("eip").name == "ip"
    assert Register.from_str("ip").name == "ip"


def test_is_same_or_smaller_register() -> None:
    assert Register.from_str("%rax") <= Register.from_str("%rax")
    assert Register.from_str("%rbx") <= Register.from_str("%rbx")
    assert Register.from_str("%eax") <= Register.from_str("%rax")
    assert not Register.from_str("%eax") <= Register.from_str("%ax")
    assert Register.from_str("%bx") <= Register.from_str("%rbx")
    assert Register.from_str("%bl") <= Register.from_str("%rbx")
    assert Register.from_str("%bh") <= Register.from_str("%rbx")
    assert not Register.from_str("%rbx") <= Register.from_str("%bl")
    assert not Register.from_str("%rbx") <= Register.from_str("%bx")
    assert Register.from_str("%r12d") <= Register.from_str("%r12")
    assert not Register.from_str("%r12") <= Register.from_str("%r12d")
    assert not Register.from_str("%rbx") <= Register.from_str("%rax")


def test_parsing() -> None:
    asm1 = """
        movl    $2, %eax
        xorl    %edx, %edx
        movw    %ax, b(%rip)
        xorl    %eax, %eax
        movw    %dx, a(%rip)
    """
    lines = parse_x86(asm1)
    assert len(lines) == 5
    assert lines[0] == Instruction("movl", int(2), Register.from_str("eax"))
    assert lines[1] == Instruction(
        "xorl", Register.from_str("edx"), Register.from_str("edx")
    )
    assert lines[2] == Instruction(
        "movw",
        Register.from_str("ax"),
        RipRelativeAddress(Register.from_str("rip"), Label("b")),
    )
    assert lines[3] == Instruction(
        "xorl", Register.from_str("eax"), Register.from_str("eax")
    )
    assert lines[4] == Instruction(
        "movw",
        Register.from_str("dx"),
        RipRelativeAddress(Register.from_str("rip"), Label("a")),
    )

    asm2 = """
        leal    (%rsi,%rdi), %eax
        retq
        je      .LBB1_2
.LBB1_1:                                # =>This Inner Loop Header: Depth=1
        jmp     .LBB1_1
d:
        .byte   0                               # 0x0
        """
    lines = parse_x86(asm2)
    assert len(lines) == 6
    assert lines[0] == Instruction(
        "leal",
        IndirectAddress(Register.from_str("%rsi"), index=Register.from_str("%rdi")),
        Register.from_str("%eax"),
    )
    assert lines[1] == Instruction("retq")
    assert lines[2] == Instruction("je", Label(".LBB1_2"))
    assert lines[3] == Label(".LBB1_1")
    assert lines[4] == Instruction("jmp", Label(".LBB1_1"))
    assert lines[5] == Label("d")
    asm3 = """
foo:                                    # @foo
        testl   %esi, %esi
        jle     .LBB0_3
        movl    %esi, %eax
        xorl    %ecx, %ecx
.LBB0_2:                                # =>This Inner Loop Header: Depth=1
        movl    $1, 4(%rdi,%rcx,8)
        addq    $1, %rcx
        cmpq    %rcx, %rax
        jne     .LBB0_2
.LBB0_3:
        retq
    """
    lines = parse_x86(asm3)
    assert len(lines) == 12
    assert lines[0] == Label("foo")
    assert lines[1] == Instruction(
        "testl", Register.from_str("%esi"), Register.from_str("%esi")
    )
    assert lines[2] == Instruction("jle", Label(".LBB0_3"))
    assert lines[3] == Instruction(
        "movl", Register.from_str("%esi"), Register.from_str("%eax")
    )
    assert lines[4] == Instruction(
        "xorl", Register.from_str("%ecx"), Register.from_str("%ecx")
    )

    assert lines[5] == Label(".LBB0_2")
    assert lines[6] == Instruction(
        "movl",
        int(1),
        IndirectAddress(
            Register.from_str("%rdi"), disp=4, index=Register.from_str("%rcx"), scale=8
        ),
    )
    assert lines[7] == Instruction("addq", int(1), Register.from_str("%rcx"))
    assert lines[8] == Instruction(
        "cmpq", Register.from_str("%rcx"), Register.from_str("%rax")
    )
    assert lines[9] == Instruction("jne", Label(".LBB0_2"))
    assert lines[10] == Label(".LBB0_3")
    assert lines[11] == Instruction("retq")
    asm4 = """
foo:                                    # @foo
        movq    a(%rip), %rax
        retq
.L.str:
        .asciz  "test"

a:
        .quad   .L.str
    """
    lines = parse_x86(asm4)
    assert len(lines) == 5
    assert lines[0] == Label("foo")
    assert lines[1] == Instruction(
        "movq",
        RipRelativeAddress(Register.from_str("rip"), Label("a")),
        Register.from_str("rax"),
    )
    assert lines[2] == Instruction("retq")
    assert lines[3] == Label(".L.str")
    assert lines[4] == Label("a")
