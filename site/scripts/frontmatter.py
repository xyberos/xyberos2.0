"""Read the page metadata that the site's build and tests both depend on.

Front matter here is data rather than decoration: the roadmap, the navigation gates, and the test
suite all read it. A lesson page declares which example module it includes and which path and lesson
number it occupies, so a missing key is a build failure instead of a blank cell on a page.

Nothing in this module imports Xyberos. It reads files, so it works from a checkout with no extras
installed, which is what lets the same checks run in the docs job and in the test suite.
"""

from __future__ import annotations

import fnmatch
import os
import re
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

SITE_ROOT = Path(__file__).resolve().parents[1]
REPOSITORY_ROOT = SITE_ROOT.parent
EXAMPLES_ROOT = REPOSITORY_ROOT / "examples"
CONFIG = REPOSITORY_ROOT / "mkdocs.yml"


class _ConfigLoader(yaml.SafeLoader):
    """A ``SafeLoader`` that resolves the ``!ENV`` tag MkDocs itself accepts.

    ``mkdocs.yml`` writes ``site_url: !ENV [SITE_URL, "https://docs.xyberos.com/"]``, so one build
    can publish under a preview URL. A plain ``safe_load`` refuses the tag outright, and every
    reader here would then fail on a configuration MkDocs is perfectly happy with.
    """


def _resolve_env(loader: _ConfigLoader, node: yaml.Node) -> str:
    """Resolve ``!ENV [VARIABLE, default]``, which is how a preview overrides one value."""
    if isinstance(node, yaml.SequenceNode):
        values = loader.construct_sequence(node)
    else:
        values = [loader.construct_scalar(node)]  # type: ignore[arg-type]
    for value in values:
        resolved = os.environ.get(str(value))
        if resolved:
            return resolved
    return str(values[-1]) if values else ""


_ConfigLoader.add_constructor("!ENV", _resolve_env)


def load_config(path: Path | None = None) -> dict[str, Any]:
    """Read ``mkdocs.yml`` the way MkDocs reads it, environment tags included."""
    loaded = yaml.load((path or CONFIG).read_text(encoding="utf-8"), Loader=_ConfigLoader)
    return loaded if isinstance(loaded, dict) else {}


#: Keys every lesson page declares. A page with ``lesson`` in its front matter is a lesson.
LESSON_KEYS = ("title", "path", "lesson", "tier", "status", "verify")

#: ``planned`` is honest incomplete work that is allowed to exist but never to ship.
STATUSES = ("planned", "draft", "verified")

#: How a lesson is checked. ``output`` runs the example and compares what it printed; ``pytest``
#: runs the example as a test, because its subject is testing; ``command`` runs the command a page
#: quotes; ``scaffold`` runs a command in a throwaway directory and compares the *files* it wrote,
#: because a scaffolding command's paths are absolute and its file list is the claim worth checking.
VERIFICATIONS = ("output", "pytest", "command", "scaffold")

#: The availability labels from the plan's feature-support matrix.
TIERS = ("built-in", "extension-point", "third-party", "not-provided")

#: Directories a page's front matter may declare as its learning path.
PATHS = ("fundamentals", "traditional", "ai", "hybrid")

_SNIPPET = re.compile(r"<!--\s*snippet:\s*([^\s>]+)\s*-->")
_OUTPUT = re.compile(r"<!--\s*output:\s*([^\s>]+)\s*-->")
_DELIMITER = re.compile(r"^---\s*$", re.MULTILINE)


def module_name(path: str) -> str | None:
    """Return the importable dotted name of an example module, or ``None`` if it is not one.

    ``examples/learn_fundamentals/fundamentals04_your_first_application.py`` is
    ``learn_fundamentals.fundamentals04_your_first_application`` — the convention
    ``tests/integration/test_tutorial.py`` already uses for ``examples/tutorial``.
    """
    if not path.startswith("examples/") or not path.endswith(".py"):
        return None
    parts = list(Path(path).with_suffix("").parts[1:])
    if parts and parts[-1] == "__init__":
        parts.pop()
    return ".".join(parts) if parts else None


@dataclass(frozen=True)
class Page:
    """One markdown page under ``site/``."""

    source: Path
    meta: dict[str, Any]
    body: str

    @property
    def relative(self) -> str:
        """The page's path relative to ``site/``, which is what the navigation names."""
        return self.source.relative_to(SITE_ROOT).as_posix()

    @property
    def repository_relative(self) -> str:
        """The page's path relative to the repository root, for messages and links."""
        return self.source.relative_to(REPOSITORY_ROOT).as_posix()

    @property
    def title(self) -> str:
        value = self.meta.get("title")
        return value if isinstance(value, str) else self.relative

    @property
    def status(self) -> str:
        value = self.meta.get("status")
        return value if isinstance(value, str) else ""

    @property
    def is_lesson(self) -> bool:
        """A lesson is a page that occupies a numbered position in a learning path."""
        return "lesson" in self.meta

    @property
    def tier(self) -> str:
        value = self.meta.get("tier")
        return value if isinstance(value, str) else ""

    @property
    def verify(self) -> str:
        """How this lesson is checked; ``output`` when the page does not say."""
        value = self.meta.get("verify")
        return value if isinstance(value, str) else "output"

    @property
    def command(self) -> str:
        """The command a ``verify: command`` lesson quotes, without its program name."""
        value = self.meta.get("command")
        return value if isinstance(value, str) else ""

    @property
    def example(self) -> Path | None:
        """The absolute path of the example module this lesson includes, if it declares one."""
        value = self.meta.get("example")
        if not isinstance(value, str) or not value:
            return None
        return REPOSITORY_ROOT / value

    @property
    def module(self) -> str | None:
        """The importable dotted name of the lesson's example, derived from its path."""
        example = self.example
        if example is None:
            return None
        try:
            relative = example.relative_to(REPOSITORY_ROOT).as_posix()
        except ValueError:
            return None
        return module_name(relative)

    @property
    def snippets(self) -> tuple[str, ...]:
        """Every ``<!-- snippet: path -->`` include the page declares, repository-relative."""
        return tuple(_SNIPPET.findall(self.body))

    @property
    def outputs(self) -> tuple[str, ...]:
        """Every ``<!-- output: module -->`` claim the page makes."""
        return tuple(_OUTPUT.findall(self.body))


def parse(text: str) -> tuple[dict[str, Any], str]:
    """Split front matter from a page's body.

    A page with no front matter is legal — a generated reference page has none — so this returns an
    empty mapping rather than raising.
    """
    lines = text.splitlines(keepends=True)
    if not lines or not _DELIMITER.match(lines[0].rstrip("\r\n")):
        return {}, text
    for index, line in enumerate(lines[1:], start=1):
        if _DELIMITER.match(line.rstrip("\r\n")):
            loaded = yaml.safe_load("".join(lines[1:index])) or {}
            if not isinstance(loaded, dict):
                raise ValueError("front matter must be a mapping")
            return loaded, "".join(lines[index + 1 :])
    raise ValueError("front matter is opened but never closed")


def load_page(source: Path) -> Page:
    """Read one page from disk."""
    meta, body = parse(source.read_text(encoding="utf-8"))
    return Page(source=source, meta=meta, body=body)


def excluded_pages() -> tuple[str, ...]:
    """The pages ``mkdocs.yml`` excludes from the build.

    Read from the configuration rather than repeated here, because a page the build does not render
    is not a site page: it has no front matter contract, it is not a lesson, and any output marker
    in its prose belongs to an example quoted in a plan rather than to a page a reader sees.
    """
    if not CONFIG.exists():
        return ()
    loaded = load_config()
    declared = loaded.get("exclude_docs")
    if isinstance(declared, str):
        return tuple(line.strip() for line in declared.splitlines() if line.strip())
    return ()


def _is_excluded(relative: str, patterns: tuple[str, ...]) -> bool:
    """Match a page path against ``exclude_docs`` patterns.

    The patterns this project declares are file names rather than globs, so matching them exactly,
    or as any path segment, is enough — and the build fails if the two ever disagree.
    """
    parts = relative.split("/")
    for pattern in patterns:
        patched = pattern.lstrip("/")
        if fnmatch.fnmatch(relative, patched) or patched in parts:
            return True
    return False


def is_excluded(relative: str, patterns: tuple[str, ...] | None = None) -> bool:
    """Whether a page path is excluded from the build, by the rules ``mkdocs.yml`` declares.

    Public because the navigation is written for the pages the build will actually contain, and a
    reader of that list has to apply the same rules rather than a second copy of them.
    """
    return _is_excluded(relative, excluded_pages() if patterns is None else patterns)


def iter_pages(root: Path | None = None) -> Iterator[Page]:
    """Yield every page under ``site/``, sorted by path, skipping generated and excluded pages.

    ``site/reference/`` is a copy of ``docs/``: it has no front matter of its own, and its content
    belongs to the repository rather than to the site, so it is not part of the site's own checks.
    """
    root = SITE_ROOT if root is None else root
    for source in sorted(root.rglob("*.md")):
        relative = source.relative_to(root).as_posix()
        if relative.startswith("reference/") or is_excluded(relative):
            continue
        yield load_page(source)
