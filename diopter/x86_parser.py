from typing import Union

from diopter.ply import lex
from diopter.ply import yacc
from diopter.ply.lex import LexToken  # type:ignore
from diopter.ply.yacc import Production  # type:ignore

import diopter.x86 as x86
from diopter.x86_mnemonics import mnemonics
from diopter.x86_registers import registers
from diopter.x86_gas_directives import directives

tokens = (
    "ID",
    "INTEGER",
    "DOLLAR",
    "COMMA",
    "LPAREN",
    "RPAREN",
    "COLON",
    "MNEMONIC",
    "REGISTER",
)

t_ignore = " \t"


def t_comment(t: LexToken) -> None:
    r"\#.*\n"
    t.lexer.lineno += t.value.count("\n")


def t_NEWLINE(t: LexToken) -> None:
    r"\n+"
    t.lexer.lineno += t.value.count("\n")


def t_ID(t: LexToken) -> LexToken:
    r"[a-zA-Z_\.0-9%\-\+][a-zA-Z0-9_\.@+-]*"
    # r"[a-zA-Z_\\./\"@][a-zA-Z0-9_\\./\"%@]*"
    # r"[a-zA-Z_\\./%][a-zA-Z0-9_\\./%]*"
    if t.value.startswith("%") and t.value[1:] in registers:
        t.value = t.value[1:]
        t.type = "REGISTER"
        return t
    try:
        v = int(t.value)
        t.type = "INTEGER"
        t.value = v
    except:
        t.type = "MNEMONIC" if t.value in mnemonics else "ID"
    return t


t_DOLLAR = r"\$"
t_COMMA = r","
t_LPAREN = r"\("
t_RPAREN = r"\)"
t_COLON = r":"
t_INTEGER = r"-?\d+([uU]|[lL]|[uU][lL]|[lL][uU])?"


class LexError(Exception):
    pass


def t_error(t: LexToken) -> None:
    raise LexError("Illegal character %s" % repr(t.value[0]))


class ParseError(Exception):
    pass


def p_line_1(p: Production) -> None:
    "line : label COLON"
    p[0] = p[1]


def p_label(p: Production) -> None:
    "label : ID"
    p[0] = x86.Label(p[1])


def p_line_2(p: Production) -> None:
    "line : instr"
    p[0] = p[1]


def p_instr(p: Production) -> None:
    "instr : MNEMONIC instr_args"
    p[0] = x86.Instruction(p[1], *p[2])


def p_instr_args_1(p: Production) -> None:
    "instr_args : empty"
    p[0] = []


def p_instr_args_2(p: Production) -> None:
    "instr_args : op"
    p[0] = [p[1]]


def p_instr_args_3(p: Production) -> None:
    "instr_args : instr_args COMMA op"
    p[0] = p[1] + [p[3]]


def p_op(p: Production) -> None:
    """op : label
    | register
    | address_segment
    | MNEMONIC
    """
    p[0] = p[1]


def p_imm(p: Production) -> None:
    """immediate : DOLLAR INTEGER
    | INTEGER
    | ID
    """
    if len(p) == 3:
        p[0] = int(p[2])
    else:
        p[0] = p[1]


def p_register(p: Production) -> None:
    "register : REGISTER"
    p[0] = x86.Register(x86.get_register_core(p[1]), x86.get_register_length(p[1]))


def p_address_with_segment(p: Production) -> None:
    "address_segment : register COLON address"
    # XXX: handle the segment
    p[0] = p[1]


def p_address_without_segment(p: Production) -> None:
    "address_segment : address"
    p[0] = p[1]


def p_address_1(p: Production) -> None:
    "address : immediate"
    p[0] = x86.ImmediateAddress(p[1])


def p_address_2(p: Production) -> None:
    "address : address_offset LPAREN address_base address_index address_scale RPAREN"
    p[0] = x86.IndirectAddress(p[4], p[2], p[5], p[6])


def p_address_3(p: Production) -> None:
    "address : label LPAREN register RPAREN"
    p[0] = x86.RipRelativeAddress(p[3], [1])


def p_empty(p: Production) -> None:
    "empty :"
    p = None


def p_address_base(p: Production) -> None:
    """address_base : empty
    | register
    """
    p[0] = p[1]


def p_address_offset_1(p: Production) -> None:
    """address_offset : empty"""
    p[0] = None


def p_address_offset_2(p: Production) -> None:
    """address_offset : INTEGER"""
    p[0] = int(p[1])


def p_address_offset_3(p: Production) -> None:
    """address_offset : ID"""
    p[0] = p[1]


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


def p_error(t: LexToken) -> None:
    if not t:
        raise ParseError("Unexpected end of input")
    raise ParseError(f"Syntax error {t}")


def parse_x86(lines: str, debug: bool = False) -> list[x86.AsmLine]:
    lexer = lex.lex()  # type:ignore
    parser = yacc.yacc()  # type:ignore
    output = []
    for line in lines.split("\n"):
        line, _, _ = line.strip().partition("#")
        if not line:
            continue
        if line.strip().split()[0] in directives:
            continue
        try:
            output.append(parser.parse(line, debug=debug, lexer=lexer))
        except LexError as e:
            raise LexError(f"Could not lex {line}: {e.__str__()}")
        except ParseError as e:
            raise ParseError(f"Could not parse {line}: {e.__str__()}")
    return output
