"""Execute the public-API contract examples so the surface is proven, not just parsed."""

import asyncio
import importlib.util
from importlib.machinery import ModuleSpec
from pathlib import Path
from types import ModuleType

EXAMPLES = Path(__file__).parent / "examples"


def load_example(name: str) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, EXAMPLES / f"{name}.py")
    assert isinstance(spec, ModuleSpec)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_phase1_example_builds_and_runs() -> None:
    module = load_example("phase1_minimal_app")

    asyncio.run(module.main())


def test_phase4_example_builds_inspects_and_runs() -> None:
    module = load_example("phase4_workflow")

    asyncio.run(module.main())
