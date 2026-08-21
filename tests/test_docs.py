"""The documentation macros.

The worked-examples page is built from the corpus at render time, so nothing
about it is committed except the template. What can still break is the macro
itself, and a page that renders empty looks fine until someone opens it.
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "docs"))

macros = pytest.importorskip("macros")

from awl import contracts  # noqa: E402


@pytest.fixture(scope="module")
def page():
    """Render the macro exactly as the site build does."""
    registered = {}

    class _Env:
        def macro(self, function):
            registered[function.__name__] = function
            return function

    macros.define_env(_Env())
    return registered["corpus_examples"]()


def test_every_corpus_file_appears(page):
    """A new fixture must not be silently omitted from the survey."""
    for path in contracts.corpus_files():
        assert f"`{path.parent.name}/{path.name}`" in page, path


def test_each_file_pairs_its_source_with_tabbed_representations(page):
    """Left is the source, right is tabbed: the layout is the point."""
    assert page.count('<div class="grid" markdown>') == len(contracts.corpus_files())
    assert page.count('=== "Python"') == len(contracts.corpus_files())
    assert page.count('=== "AWL AST, collapsed"') == len(contracts.corpus_files())
    assert page.count('=== "AWL AST, plain"') == len(contracts.corpus_files())


def test_the_source_column_is_tabbed_too(page):
    """Both columns are tab sets, so they sit at the same height and read as
    one artefact in two notations rather than as two different kinds of thing.
    """
    assert '=== "Python"' in page
    assert chr(10) + "```python" not in page, "no bare code block outside a tab"


def test_the_collapsed_view_actually_differs_from_the_plain_one(page):
    """Otherwise the tabs show the same thing twice and prove nothing."""
    assert '"@type": ["ChargeParam"]' in page, "tier 2 collapses to its class name"
    assert '"@type": ["ChargeParam", "ex:ChargeParam"]' in page, "tier 3 adds the declared IRI"


def test_nothing_is_left_unrendered(page):
    """An unexpanded macro call would ship its own source to the reader."""
    assert "corpus_examples()" not in page
    assert "corpus_count()" not in page


def test_the_built_page_renders_three_tab_labels_per_file():
    """Asserted on the HTML, not the markdown.

    A test that only checks `=== "Python"` is in the source passes while the
    tab silently fails to render, which is exactly what happened: the JSON
    column had no blank lines and rendered, the Python column had them and
    did not, and the markdown assertion could not tell the difference.

    Skipped when the site has not been built; CI builds it in docs-test.
    """
    import re

    built = Path(__file__).resolve().parents[1] / "site" / "examples" / "index.html"
    if not built.exists():
        pytest.skip("run `uv run zensical build` first")

    labels = re.findall(r"<label[^>]*>([^<]+)</label>", built.read_text(encoding="utf-8"))
    expected = len(contracts.corpus_files())
    for title in ("Python", "AWL AST, collapsed", "AWL AST, plain", "RDF"):
        assert labels.count(title) == expected, f"{title}: {labels.count(title)} of {expected}"
