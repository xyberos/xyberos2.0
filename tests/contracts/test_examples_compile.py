from pathlib import Path

CONTRACT_EXAMPLES = Path(__file__).parent / "examples"


def test_phase_one_contract_examples_are_valid_python() -> None:
    """Keep proposed public API examples syntactically valid before implementation."""
    for example in sorted(CONTRACT_EXAMPLES.glob("*.py")):
        source = example.read_text(encoding="utf-8")
        compile(source, str(example), "exec")
