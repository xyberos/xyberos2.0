"""Render a page's ``<!-- snippet: path -->`` markers, and prove that every one rendered.

The marker is the form this site's tests read: a page claims code by naming the file the suite runs,
so the claim and the code cannot drift. MkDocs itself only understands the ``--8<--`` directive, so
``on_page_markdown`` translates the checked form into the rendered one, and ``unrendered_pages``
checks the built output — a marker that survives reaches readers as a page with no code on it, which
is a failure that no inspection of the source can see.

The translation wraps the directive in a fenced block, which is not decoration. A bare ``--8<--``
line splices the file into the Markdown stream, so a Python module arrives as *prose*: its docstring
becomes a paragraph, ``from __future__ import annotations`` renders with **future** in bold, and a
``#:`` comment becomes a heading. The fence is what makes the included file a code block, and the
language and title are what make it readable once it is one.
"""

from __future__ import annotations

import re
from pathlib import Path

# Safe: MkDocs puts a hook's own directory on `sys.path` while it imports it, and `build.py` runs
# with that directory as `sys.path[0]`, so both readers resolve the module the same way.
from frontmatter import load_config

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
MKDOCS = REPOSITORY_ROOT / "mkdocs.yml"

#: The canonical marker, which a page writes on its own line.
MARKER = "<!-- snippet:"

#: Kept in step with ``frontmatter._SNIPPET``, which reads the same markers for its own checks.
SNIPPET = re.compile(r"<!--\s*snippet:\s*([^\s>]+)\s*-->")

#: The fence language for each kind of file a page may include, keyed by suffix.
LANGUAGES = {
    ".py": "python",
    ".html": "html",
    ".json": "json",
    ".md": "markdown",
    ".sh": "bash",
    ".sql": "sql",
    ".toml": "toml",
    ".yaml": "yaml",
    ".yml": "yaml",
}


def language(path: str) -> str:
    """Return the fence language for an included file, defaulting to plain text."""
    return LANGUAGES.get(Path(path).suffix, "text")


def fenced(path: str) -> str:
    """Return the fenced directive that renders ``path`` as a code block titled with its path."""
    return f'```{language(path)} title="{path}"\n--8<-- "{path}"\n```'


def on_page_markdown(markdown: str, **kwargs: object) -> str:
    """Replace every snippet marker line with the fenced directive MkDocs renders as code."""
    rendered: list[str] = []
    for line in markdown.splitlines(keepends=True):
        match = SNIPPET.fullmatch(line.strip())
        rendered.append(f"{fenced(match.group(1))}\n" if match else line)
    return "".join(rendered)


def output_directory() -> Path:
    """The directory MkDocs writes, read from the configuration rather than assumed."""
    loaded = load_config(MKDOCS)
    return REPOSITORY_ROOT / str(loaded.get("site_dir", "site"))


def unrendered_pages(output_dir: Path) -> list[Path]:
    """The built pages that still contain a snippet marker."""
    if not output_dir.is_dir():
        return []
    return sorted(
        page
        for page in output_dir.rglob("*.html")
        if MARKER in page.read_text(encoding="utf-8", errors="ignore")
    )
