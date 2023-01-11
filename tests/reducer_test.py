from diopter.compiler import Language, SourceProgram
from diopter.reducer import Reducer, ReductionCallback


class SimpleCallback(ReductionCallback):
    def test(self, program: SourceProgram) -> bool:
        return "a" in program.code


def test_simple() -> None:
    reducer_input = SourceProgram(
        code="as;lkjfa;sf922930942394209ababababababa", language=Language.C
    )
    reducer = Reducer()

    output = reducer.reduce(reducer_input, SimpleCallback(), debug=True)
    assert output
    assert output.code.strip() == "a", f"output={output}"


if __name__ == "__main__":
    test_simple()
