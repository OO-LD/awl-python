"""The documentation macros.

The worked-examples page is built from the corpus at render time, so nothing
about it is committed except the template. What can still break is the macro
itself, and a page that renders empty looks fine until someone opens it.
"""

from pathlib import Path

import pytest

from awl import contracts, examples


@pytest.fixture(scope="module")
def page():
    """Render the macro exactly as the site build does."""
    registered = {}

    class _Env:
        def macro(self, function):
            registered[function.__name__] = function
            return function

    examples.define_env(_Env())
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


@pytest.fixture(scope="module")
def flavours():
    """Render both flavour macros, as the site build does."""
    registered = {}

    class _Env:
        def macro(self, function):
            registered[function.__name__] = function
            return function

    examples.define_env(_Env())
    return registered["single_flavours"](), registered["combined_flavours"]()


def test_every_lookup_is_shown_on_its_own(flavours):
    """A lookup added to the generator must not be missing from the page."""
    from awl import vocab

    single, _ = flavours
    assert single.count("## ") == len(vocab.LAYERS) + 1, "one per lookup, plus the located tree"


def test_each_flavour_pairs_the_source_with_both_notations(flavours):
    """The point of the page: the same thing, three ways, side by side."""
    for page in flavours:
        sections = page.count("## ")
        assert page.count('=== "Python"') == sections
        assert page.count('=== "AWL AST"') == sections
        assert page.count('=== "RDF"') == sections


def test_every_query_on_the_page_can_be_copied_and_run(flavours):
    """A query shown without its prefixes is not a query, it is a fragment.

    Checked on what the page prints, not on what the macro happens to run, so
    the two cannot drift into showing one thing and answering another.
    """
    import re

    from rdflib import Graph

    for page in flavours:
        blocks = re.findall(r"```sparql\n(.*?)```", page, re.S)
        assert blocks, "the page shows no query"
        for block in blocks:
            declared = set(re.findall(r"PREFIX (\w+):", block))
            body = re.sub(r"PREFIX .*", "", block)
            used = set(re.findall(r"(?<![<\w])(\w+):(?!//)", body))
            assert used <= declared, f"undeclared {sorted(used - declared)} in {block[:60]}"
            Graph().query(block), "and it parses"


def test_the_combinations_end_with_what_a_query_runs_against(flavours):
    """Otherwise the page stops short of the form anyone actually uses."""
    from awl import vocab

    _, combined = flavours
    assert "Everything" in combined
    assert combined.index("Tree and plan") < combined.index("Everything"), "least to most"
    assert vocab.LOOKUPS["ast"] == vocab.LAYERS, "and Everything is the ast profile"


def test_the_landing_page_example_runs():
    """The first thing a reader copies, executed rather than proofread.

    It went stale unnoticed once already: the page documented a query against
    a vocabulary the pipeline had stopped emitting, and it still passed review
    because the code was never run.
    """
    import re

    page = (Path(__file__).resolve().parents[1] / "docs" / "index.md").read_text(encoding="utf-8")
    blocks = re.findall(r"```py\n(.*?)```", page, re.S)
    assert blocks, "the page shows no example"
    for index, block in enumerate(blocks):
        exec(compile(block, f"docs/index.md[{index}]", "exec"), {})  # noqa: S102


def test_no_page_calls_a_macro_it_only_meant_to_mention():
    """Every macro call is a Jinja expression wherever it appears.

    Backticks and fenced blocks included. Mentioning one in prose runs it: the
    development page did, and grew the whole worked-examples output into
    itself. A strict build reported no issues and the page still rendered, only
    a hundred times longer than it reads, so nothing but its output gives it
    away.

    Skipped when the site has not been built; CI builds it in docs-test.
    """
    site = Path(__file__).resolve().parents[1] / "site"
    if not site.exists():
        pytest.skip("run `uv run zensical build` first")

    generated = {"examples", "flavours"}
    for built in site.glob("*/index.html"):
        emitted = '<label for="' in (html := built.read_text(encoding="utf-8")) and "AWL AST" in html
        if built.parent.name in generated:
            assert emitted, f"{built.parent.name} renders no examples"
        else:
            assert not emitted, f"{built.parent.name} rendered a macro it should only have named"


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

    html = built.read_text(encoding="utf-8")
    assert "corpus_examples()" not in html, "the macro reached the reader unrendered"

    labels = re.findall(r"<label[^>]*>([^<]+)</label>", html)
    expected = len(contracts.corpus_files())
    for title in ("Python", "AWL AST, collapsed", "AWL AST, plain", "RDF"):
        assert labels.count(title) == expected, f"{title}: {labels.count(title)} of {expected}"


def test_the_macro_module_is_reachable_by_import_alone():
    """How zensical must find it, and the only way that works under `serve`.

    A macro module is resolved by file path against the project root first and
    by import only when the name holds no path separator. On Windows `serve`
    passes an extended-length project root, so the file lookup silently finds
    nothing, and a name like `docs/macros` never reaches the import: the page
    shipped `{{ corpus_examples() }}` to the reader instead of the examples.
    """
    import importlib
    import tomllib

    configured = tomllib.loads((Path(__file__).resolve().parents[1] / "zensical.toml").read_text(encoding="utf-8"))[
        "project"
    ]["plugins"]["macros"]["module_name"]

    assert "/" not in configured and "\\" not in configured, configured
    assert hasattr(importlib.import_module(configured), "define_env")
