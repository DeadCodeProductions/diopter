from ply import lex  # type: ignore
from ply import yacc

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


def t_comment(t: lex.LexToken) -> None:
    r"\#.*\n"
    t.lexer.lineno += t.value.count("\n")


def t_NEWLINE(t: lex.LexToken) -> None:
    r"\n+"
    t.lexer.lineno += t.value.count("\n")


def t_ID(t: lex.LexToken) -> lex.LexToken:
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


def t_error(t: lex.LexToken) -> None:
    print("Illegal character %s" % repr(t.value[0]))
    exit(1)


def p_line_1(p: yacc.Production) -> None:
    "line : label COLON"
    p[0] = p[1]


def p_label(p):
    "label : ID"
    p[0] = x86.Label(p[1])


def p_line_2(p):
    "line : instr"
    p[0] = p[1]


def p_instr_0(p):
    "instr : ID"
    p[0] = x86.Instruction(p[1])


def p_instr_1(p):
    "instr : ID op"
    p[0] = x86.Instruction(p[1], p[2])


def p_instr_2(p):
    "instr : ID op COMMA op"
    p[0] = x86.Instruction(p[1], p[2], p[4])


def p_instr_3(p):
    "instr : ID op COMMA op COMMA op"
    p[0] = x86.Instruction(p[1], p[2], p[4], p[6])


def p_op(p):
    """op : immediate
    | register
    | address
    """
    p[0] = p[1]


def p_imm(p):
    """immediate : DOLLAR INTEGER
    | label
    """
    if len(p) == 3:
        p[0] = int(p[2])
    else:
        p[0] = p[1]


def p_register(p):
    "register : PERCENT ID"
    p[0] = x86.Register(x86.get_register_core(p[2]), x86.get_register_length(p[2]))


def p_address_1(p):
    "address : immediate"
    p[0] = x86.ImmediateAddress(p[2])


def p_address_2(p):
    "address : address_offset LPAREN register address_index address_scale RPAREN"
    p[0] = x86.IndirectAddress(p[3], p[1], p[4], p[5])


def p_empty(p):
    "empty :"
    p = None


def p_address_offset_1(p):
    """address_offset : empty
    | label
    """
    p[0] = p[1]


def p_address_offset_2(p):
    """address_offset : INTEGER"""
    p[0] = int(p[1])


def p_address_index(p):
    """address_index : empty
    | COMMA register
    """
    p[0] = p[2] if len(p) == 3 else p[1]


def p_address_scale(p):
    """address_scale : empty
    | COMMA INTEGER
    """
    p[0] = int(p[2]) if len(p) == 3 else p[1]


def p_address_rip(p):
    "address : immediate LPAREN register RPAREN"
    assert p[3].name == "ip", p[3]
    p[0] = x86.RipRelativeAddress(p[3], p[1])


def p_line_3(p):
    "line : global"
    p[0] = p[1]


def p_global(p):
    "global : TYPE global_value"
    p[0] = x86.Global(p[1], p[2])


def p_global_value_1(p):
    "global_value : INTEGER"
    p[0] = int(p[1])


def p_global_value_2(p):
    "global_value : label"
    p[0] = p[1]


def p_global_value_3(p):
    "global_value : DQUOTE ID DQUOTE"
    p[0] = p[2]


def parse_x86(lines: str, debug=False):
    lexer = lex.lex()
    parser = yacc.yacc()
    output = []
    for line in lines.split("\n"):
        line, _, _ = line.strip().partition("#")
        if not line:
            continue
        output.append(parser.parse(line, debug=debug, lexer=lexer))

    return output
