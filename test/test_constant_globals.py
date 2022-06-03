from diopter.constant_globals import find_written_globals


def test_find_written_globals() -> None:
    source1 = """ 
            int a;
            float b;

            int foo() {
                b = 2;
                a = 0;
                return 0;
            }
    """
    for cc in ("gcc", "clang"):
        for opt in ("-O0", "-O1", "-O2", "-O3"):
            assert find_written_globals(source1, cc, opt) == {"a", "b"}
    source2 = """ 
            int a;
            int b;

            int foo() {
                a = b;
                return 0;
            }
    """
    for cc in ("gcc", "clang"):
        for opt in ("-O0", "-O1", "-O2", "-O3"):
            assert find_written_globals(source2, cc, opt) == {"a"}
    source3 = """ 
            int a;
            int b;

            int foo(int c) {
                a = c;
                c = b;
                return c;
            }
    """
    for cc in ("gcc", "clang"):
        for opt in ("-O0", "-O1", "-O2", "-O3"):
            assert find_written_globals(source3, cc, opt) == {"a"}
    source4 = """ 
            int a;

            int foo(int b) {
                int  *c = &a; 
                *c = b;
                return a;
            }
    """
    for cc in ("gcc", "clang"):
        for opt in ("-O0", "-O1", "-O2", "-O3"):
            assert find_written_globals(source4, cc, opt) == {"a"}


# assert (
# find_first_previous_modification_of_register_within_bb(
# Register.from_str("%ax"), 3, asm1
# )
# == 0
# )
# assert (
# find_first_previous_modification_of_register_within_bb(
# Register.from_str("%dx"), 4, asm1
# )
# == 1
# )
# assert (
# find_first_previous_modification_of_register_within_bb(
# Register.from_str("%cx"), 4, asm1
# )
# == None
# )
# asm2 = parse_x86(
# """
# movl    $2, %eax
# xorl    %edx, %edx
# label:
# movw    %ax, b(%rip)
# xorl    %eax, %eax
# movw    %dx, a(%rip)
# """
# )
# assert (
# find_first_previous_modification_of_register_within_bb(
# Register.from_str("%ax"), 3, asm2
# )
# == None
# )
# assert (
# find_first_previous_modification_of_register_within_bb(
# Register.from_str("%dx"), 5, asm2
# )
# == None
# )
# asm3 = parse_x86(
# """
# movb    a(%rip), %al
# movb    %al, c(%rip)
# xorl    %ecx, %ecx
# testb   %al, %al
# setne   %cl
# movl    %ecx, b(%rip)
# """
# )
# assert (
# find_first_previous_modification_of_register_within_bb(
# Register.from_str("%ecx"), 5, asm3
# )
# == 4
# )


# def test_find_first_previous_modification_of_register_within_bb() -> None:
# asm1 = parse_x86(
# """
# movl    $2, %eax
# xorl    %edx, %edx
# movw    %ax, b(%rip)
# xorl    %eax, %eax
# movw    %dx, a(%rip)
# """
# )
# assert (
# find_first_previous_modification_of_register_within_bb(
# Register.from_str("%ax"), 3, asm1
# )
# == 0
# )
# assert (
# find_first_previous_modification_of_register_within_bb(
# Register.from_str("%dx"), 4, asm1
# )
# == 1
# )
# assert (
# find_first_previous_modification_of_register_within_bb(
# Register.from_str("%cx"), 4, asm1
# )
# == None
# )
# asm2 = parse_x86(
# """
# movl    $2, %eax
# xorl    %edx, %edx
# label:
# movw    %ax, b(%rip)
# xorl    %eax, %eax
# movw    %dx, a(%rip)
# """
# )
# assert (
# find_first_previous_modification_of_register_within_bb(
# Register.from_str("%ax"), 3, asm2
# )
# == None
# )
# assert (
# find_first_previous_modification_of_register_within_bb(
# Register.from_str("%dx"), 5, asm2
# )
# == None
# )
# asm3 = parse_x86(
# """
# movb    a(%rip), %al
# movb    %al, c(%rip)
# xorl    %ecx, %ecx
# testb   %al, %al
# setne   %cl
# movl    %ecx, b(%rip)
# """
# )
# assert (
# find_first_previous_modification_of_register_within_bb(
# Register.from_str("%ecx"), 5, asm3
# )
# == 4
# )


# def test_xored_register() -> None:

# return
# asm1 = parse_x86(
# """
# main:
# movl    e(%rip), %edx
# testl   %edx, %edx
# jne     .L3
# xorl    %rax, %rax
# movl    %eax, a(%rip)
# xorl    %eax, %eax
# ret
# """
# )
# assert is_write_from_xored_register(5, asm1)
# asm2 = parse_x86(
# """
# main:
# movl    e(%rip), %edx
# testl   %edx, %edx
# jne     .L3
# xorl    %rax, %rax
# movl    %ebx, a(%rip)
# xorl    %eax, %eax
# ret
# """
# )
# assert not is_write_from_xored_register(5, asm2)
# asm3 = parse_x86(
# """
# movl    $2, %eax
# xorl    %dx, %dx
# movw    %ax, b(%rip)
# xorl    %eax, %eax
# movw    %edx, a(%rip)
# """
# )
# assert not is_write_from_xored_register(4, asm3)
# asm4 = parse_x86(
# """
# movl    $2, %eax
# xorl    %edx, %edx
# movw    %ax, b(%rip)
# xorl    %eax, %eax
# movw    %dx, a(%rip)
# """
# )
# assert is_write_from_xored_register(4, asm4)
# asm5 = parse_x86(
# """
# movb    a(%rip), %al
# movb    %al, c(%rip)
# xorl    %ecx, %ecx
# testb   %al, %al
# setne   %cl
# movl    %ecx, b(%rip)
# """
# )
# assert not is_write_from_xored_register(5, asm5)


# def test_write_from_constant_register() -> None:
# return
# asm1 = """
# main:
# movl    $1, %eax
# movw    %ax, a(%rip)
# xorl    %eax, %eax
# ret
# a:
# .zero   2
# """

# assert is_write_from_constant_register(2, parse_x86(asm1)) == 1

# asm2 = """
# main:
# movl    %ebx, %eax
# movw    %ax, a(%rip)
# xorl    %eax, %eax
# ret
# a:
# .zero   2
# """
# assert not is_write_from_constant_register(2, parse_x86(asm2))
# asm3 = parse_x86(
# """
# movl    $2, %eax
# xorl    %edx, %edx
# movw    %ax, b(%rip)
# xorl    %eax, %eax
# movw    %dx, a(%rip)
# """
# )
# assert len(asm3) == 5
# assert is_write_from_constant_register(2, asm3) == 2
# assert not is_write_from_constant_register(4, asm3)


# def test_find_constant_globals() -> None:
# return
# asm1 = parse_x86(
# """
# main:
# movl    e(%rip), %edx
# testl   %edx, %edx
# jne     .L3
# xorl    %rax, %rax
# movl    %eax, a(%rip)
# xorl    %eax, %eax
# ret
# """
# )
# assert find_constant_globals(asm1) == ({"a": 0}, set())

# asm2 = parse_x86(
# """
# main:
# movl    $1, %eax
# movw    %ax, a(%rip)
# xorl    %eax, %eax
# movw    %edx, b(%rip)
# ret
# a:
# .zero   2
# """
# )
# assert find_constant_globals(asm2) == ({"a": 1}, {"b"})
# asm3 = parse_x86(
# """
# main:
# movl    $1, %eax
# movw    %ax, a(%rip)
# xorl    %eax, %eax
# movw    $2, a(%rip)
# ret
# a:
# .zero   2
# """
# )
# assert find_constant_globals(asm3) == ({}, {"a"})
