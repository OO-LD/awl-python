# Development

## Setup

The project is managed with [uv](https://docs.astral.sh/uv/). One command
creates the environment, installs the dependency groups from `uv.lock` and
installs the pre-commit hooks:

```bash
make install
```

`make` with no target lists everything available.

Three extras are declared, and none of them is installed by `uv sync`:

| Extra | For |
| --- | --- |
| `validate` | `awl.contracts.validate()`, which checks a document against its schema |
| `edit` | structural source edits with trivia preservation, in `awl.writeback` |
| `hitl` | the human-in-the-loop widget. Legacy, and currently uninstallable in practice: the published `oold` wheel omits the built assets `oold.ui.panel` imports |

The dev group installs `validate` and `edit` anyway, so their tests run under a
plain `make install` rather than being skipped in silence.

## Checks

`make ci` is the definition of done and is what CI runs:

```bash
make ci        # check, test, docs-test
```

| Target | Runs |
| --- | --- |
| `make check` | lock file consistency, pre-commit (ruff check and format), `ty` type checking, `deptry` for unused dependencies |
| `make test` | pytest with coverage |
| `make docs-test` | a strict documentation build |
| `make bench` | the benchmarks, which are not part of `make test` |

Commit messages must be [conventional
commits](https://www.conventionalcommits.org/): `python-semantic-release` parses
them to decide the next version, so a message that does not conform silently
does the wrong thing at release time.

## Tests

One test file per module, and each imports only the module under test and
`awl.contracts`. `tests/test_pipeline.py` is the one exception, because
composition is what it tests. A module is done when its tests pass with every
sibling module deleted.

Two directories are not collected by `make test`: `tests/benchmarks`, which has
its own session because coverage distorts timings, and `tests/legacy`, which
covers `awl.legacy.hitl` and needs the `hitl` extra.

The round-trip suite regenerates the whole standard library. By default it
takes every seventh file, which spans the library rather than its alphabetical
head; the full set takes about ten minutes:

```bash
AWL_FULL_SWEEP=1 uv run python -m pytest tests/test_roundtrip.py
```

Run it before changing anything in `awl.astdoc`, `awl.elide` or `awl.compact`.
Nine corpus files cannot see what a thousand modules can: the collision between
a node-type key and `ExceptHandler`'s field named `type`, seven sequence fields
missing from a hand-written list, and `f(a=1, **rest)` losing its `**rest` were
all found this way and none of them by the corpus.

## Documentation

```bash
make docs        # zensical serve, on http://localhost:8000/awl-python/
make docs-test   # a strict build into site/
```

The worked-examples and flavours pages are **generated at render time** from
the corpus and the pipeline, by the macros in `awl.examples`. Only the page
templates are committed, so neither can show how the encoding used to look.

Three things about this build have cost real time, and all three fail quietly.

**The macro module must be importable by name.** It is configured as
`module_name = "awl.examples"` in `zensical.toml`, and it lives in the package
rather than beside the pages it renders. zensical resolves a macro module by
file path first and by import only when the name holds no path separator. Under
`zensical serve` on Windows the project root arrives extended-length-prefixed
(`\\?\C:\...`), the file lookup finds nothing, and a name like `docs/macros`
never reaches the import. Nothing is logged; the page simply ships its own
macro call to the reader.

A macro call is a Jinja expression wherever it appears, **including inside
backticks and fenced blocks**. Writing one in prose to talk about it calls it:
this page did, and quietly grew the whole worked-examples output into itself.
Wrap it in a Jinja `raw` block to show one. That applies to the raw tags
themselves, which is why they are not spelled out here.

**`.cache` is keyed on the markdown file, not on what produced the render.**
One bad render poisons it, and every later build and serve reuses that entry
and reports "No issues found". A strict build inside `make ci` will re-emit a
poisoned page without complaint. After any bad render:

```bash
rm -rf .cache site
```

Restarting the serve alone does not help.

**A serve and a build fight over `site/` and `.cache/`.** Do not run `make docs`
and `make ci` at the same time; that is how the cache gets poisoned in the first
place. Deleting those directories under a running serve kills it with
`os error 2`, so stop the serve first.

Verify a page by reading the built HTML, not the markdown the macro returned. A
test asserting `=== "Python"` is in the macro output passes while the tab fails
to render, which is exactly what happened once: the JSON column had no blank
lines and rendered, the Python column had them and did not.

## Local-only files

`docs/graph-derivation.md` and `docs/specs/` are deliberately not committed and
are protected by `.git/info/exclude`. They are working notes, not documentation.
