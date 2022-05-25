from pathlib import Path
from diopter.preprocessor import preprocess_lines


def test_extern_removal() -> None:
    prefix = str(Path(__file__).parent)

    with open(f"{prefix}/gcc_preprocessed_code.c", "r") as f:
        lines = f.read().split("\n")

    with open(f"{prefix}/preprocessed_oracle.c", "r") as f:
        oracle = f.read()
    assert oracle == preprocess_lines(lines).strip()
