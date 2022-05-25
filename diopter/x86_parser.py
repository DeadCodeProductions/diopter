from typing import Union

from diopter.ply import lex
from diopter.ply import yacc
from diopter.ply.lex import LexToken  # type:ignore
from diopter.ply.yacc import Production  # type:ignore

import diopter.x86 as x86

tokens = (
    "ID",
    "INTEGER",
    "PERCENT",
    "DOLLAR",
    "COMMA",
    "LPAREN",
    "RPAREN",
    "COLON",
    "DQUOTE",
    "TYPE",
)

types = {".quad", ".long", ".short", ".byte", ".asciz", ".zero"}

t_ignore = " \t"


def t_comment(t: LexToken) -> None:
    r"\#.*\n"
    t.lexer.lineno += t.value.count("\n")


def t_NEWLINE(t: LexToken) -> None:
    r"\n+"
    t.lexer.lineno += t.value.count("\n")


def t_ID(t: LexToken) -> LexToken:
    r"[a-zA-Z_\.][a-zA-Z0-9_\.]*"
    t.type = "ID" if t.value not in types else "TYPE"
    return t


t_PERCENT = r"%"
t_DOLLAR = r"\$"
t_COMMA = r","
t_LPAREN = r"\("
t_RPAREN = r"\)"
t_COLON = r":"
t_DQUOTE = r"\""

t_INTEGER = r"-?\d+([uU]|[lL]|[uU][lL]|[lL][uU])?"


class LexError(Exception):
    pass


def t_error(t: LexToken) -> None:
    raise LexError("Illegal character %s" % repr(t.value[0]))


def p_line_1(p: Production) -> None:
    "line : label COLON"
    p[0] = p[1]


def p_label(p: Production) -> None:
    "label : ID"
    p[0] = x86.Label(p[1])


def p_line_2(p: Production) -> None:
    "line : instr"
    p[0] = p[1]


def p_instr_0(p: Production) -> None:
    "instr : ID"
    p[0] = x86.Instruction(p[1])


def p_instr_1(p: Production) -> None:
    "instr : ID op"
    p[0] = x86.Instruction(p[1], p[2])


def p_instr_2(p: Production) -> None:
    "instr : ID op COMMA op"
    p[0] = x86.Instruction(p[1], p[2], p[4])


def p_instr_3(p: Production) -> None:
    "instr : ID op COMMA op COMMA op"
    p[0] = x86.Instruction(p[1], p[2], p[4], p[6])


def p_op(p: Production) -> None:
    """op : immediate
    | register
    | address
    """
    p[0] = p[1]


def p_imm(p: Production) -> None:
    """immediate : DOLLAR INTEGER
    | label
    """
    if len(p) == 3:
        p[0] = int(p[2])
    else:
        p[0] = p[1]


def p_register(p: Production) -> None:
    "register : PERCENT ID"
    p[0] = x86.Register(x86.get_register_core(p[2]), x86.get_register_length(p[2]))


def p_address_1(p: Production) -> None:
    "address : immediate"
    p[0] = x86.ImmediateAddress(p[2])


def p_address_2(p: Production) -> None:
    "address : address_offset LPAREN register address_index address_scale RPAREN"
    p[0] = x86.IndirectAddress(p[3], p[1], p[4], p[5])


def p_empty(p: Production) -> None:
    "empty :"
    p = None


def p_address_offset_1(p: Production) -> None:
    """address_offset : empty
    | label
    """
    p[0] = p[1]


def p_address_offset_2(p: Production) -> None:
    """address_offset : INTEGER"""
    p[0] = int(p[1])


def p_address_index(p: Production) -> None:
    """address_index : empty
    | COMMA register
    """
    p[0] = p[2] if len(p) == 3 else p[1]


def p_address_scale(p: Production) -> None:
    """address_scale : empty
    | COMMA INTEGER
    """
    p[0] = int(p[2]) if len(p) == 3 else p[1]


def p_address_rip(p: Production) -> None:
    "address : immediate LPAREN register RPAREN"
    assert p[3].name == "ip", p[3]
    p[0] = x86.RipRelativeAddress(p[3], p[1])


def p_line_3(p: Production) -> None:
    "line : global"
    p[0] = p[1]


def p_global(p: Production) -> None:
    "global : TYPE global_value"
    p[0] = x86.Global(p[1], p[2])


def p_global_value_1(p: Production) -> None:
    "global_value : INTEGER"
    p[0] = int(p[1])


def p_global_value_2(p: Production) -> None:
    "global_value : label"
    p[0] = p[1]


def p_global_value_3(p: Production) -> None:
    "global_value : DQUOTE ID DQUOTE"
    p[0] = p[2]


def parse_x86(lines: str, debug: bool = False) -> list[x86.AsmLine]:
    lexer = lex.lex()  # type:ignore
    parser = yacc.yacc()  # type:ignore
    output = []
    for line in lines.split("\n"):
        line, _, _ = line.strip().partition("#")
        if not line:
            continue
        try:
            output.append(parser.parse(line, debug=debug, lexer=lexer))
        except LexError as e:
            raise LexError(f"Could not lex {line}: {e.__str__()}")
    return output
