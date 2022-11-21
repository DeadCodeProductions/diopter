from diopter.reducer import Reducer, ReductionCallback


class SimpleCallback(ReductionCallback):
    def test(self, code: str) -> bool:
        return "a" in code


def test_simple() -> None:
    reducer_input = "as;lkjfa;sf922930942394209ababababababa"
    reducer = Reducer()

    output = reducer.reduce(reducer_input, SimpleCallback(), debug=True)
    assert output
    assert output.strip() == "a", f"output={output}"


if __name__ == "__main__":
    test_simple()
