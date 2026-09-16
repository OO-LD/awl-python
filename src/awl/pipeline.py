"""Compose the stages. This module holds no logic of its own.

Every stage is a total function over plain data, so composition is ordinary
function application and there is nothing here to test except that the stages
fit together. That is not nothing: the failures worth catching at this level
are the ones no single stage can see.

The important one is **identity agreement**. Five producers mint IRIs — the
extraction pass, name resolution, member-write resolution, the def-use graph
and the control-flow graph. If two of them name one entity differently, the
graph contains two disconnected nodes where it should contain one, and every
unit test still passes because each producer is self-consistent.
"""

from __future__ import annotations

import ast
from typing import Any

from awl import collapse, compact, context, controlflow, dataflow, elide, execution, facts, rdf, vocab
from awl.astdoc import to_doc
from awl.resolve import resolve, resolve_writes

__all__ = ["analyze", "resolve_module", "to_ast_doc", "to_compact", "to_document", "to_graph"]


def analyze(source: str, *, module: str = "", file: str = "<source>") -> dict[str, Any]:
    """Run every observation and inference stage over one module.

    Parameters
    ----------
    source : str
        The module's text.
    module : str
        Its dotted import path.
    file : str, optional
        A label for spans.

    Returns
    -------
    dict
        ``facts``, ``names``, ``writes``, ``flow`` and ``plan``: what was seen,
        what it refers to, what was assigned to which typed member, where each
        value came from, and how control moves between steps.
    """
    observed = facts.extract(source, module=module, file=file)
    return {
        "file": file,
        "module": module,
        "facts": observed,
        "names": resolve(observed),
        "writes": resolve_writes(observed),
        "flow": dataflow.analyze(source, module=module, file=file),
        "plan": controlflow.analyze(source, module=module, file=file),
    }


def resolve_module(module: str, origin: str) -> str:
    """Return the absolute path an import names.

    ``from .params import ChargeParam`` inside ``battery.procedure`` names
    ``battery.params``. Extraction records the origin exactly as written,
    because that is what the source says; turning it into a path is an
    inference and belongs here.
    """
    if not origin.startswith("."):
        return origin
    depth = len(origin) - len(origin.lstrip("."))
    parts = module.split(".")[: -depth or None]
    tail = origin.lstrip(".")
    return ".".join([*parts, tail]) if tail else ".".join(parts)


def _classes_of(observed: dict[str, Any], module: str) -> dict[str, Any]:
    """Return every collapsible class a module offers, by qualified name.

    Both rungs of the gradient, which is the point. A class deriving from the
    linked base carries declared IRIs and link forms; a plain annotated class
    carries only field names and their annotations. The collapse needs the
    field names, and both have those, so both collapse. Only the resulting
    node differs, which is the progressive enhancement claim doing real work
    rather than being asserted.
    """
    found = {f"{module}.{entry['identity']['symbol']}": entry for entry in observed.get("types", [])}
    for entry in observed.get("declarations", []):
        if entry.get("kind") != "class" or not entry.get("fields"):
            continue
        qualified = f"{module}.{entry['name']}"
        found.setdefault(
            qualified,
            {"identity": entry["identity"], "declared_types": [], "fields": entry["fields"]},
        )
    return found


def _collapsible(observed: dict[str, Any], module: str, index: dict[str, str]) -> tuple[dict[str, Any], dict[str, str]]:
    """Return the types the collapse may use, and what each local name means.

    Parameters
    ----------
    index : dict
        Module path to that module's source. Without it only classes declared
        in this file can collapse, which is almost never where they live: a
        parameter object is imported, not defined beside the procedure using
        it.
    """
    types = _classes_of(observed, module)
    resolved = {name.rsplit(".", 1)[-1]: name for name in types}

    for entry in observed.get("imports", []):
        if entry.get("is_star"):
            continue
        origin = resolve_module(module, entry["from_module"])
        other = index.get(origin)
        if other is None:
            continue
        available = _classes_of(facts.extract(other, module=origin, file=origin), origin)
        qualified = f"{origin}.{entry['imported_name']}"
        if qualified in available:
            types[qualified] = available[qualified]
            resolved[entry["local_name"]] = qualified
    return types, resolved


def _imported_classes(observed: dict[str, Any], module: str, index: dict[str, str]) -> dict[str, Any]:
    """Return every class an imported module declares, by its own name.

    Member-write resolution reads declarations, and a declaration lives in the
    module that made it. Without these, ``report.capacity = ...`` resolved for
    the collapse, which follows imports, and not for the write, which did not:
    the same class was known and unknown in one pass.

    Every class of the module, not only the imported name, because the range of
    a field is declared in the module that declares the field. Local names win
    on a collision, since a class declared here is what a name here means.
    """
    found: dict[str, Any] = {}
    for entry in observed.get("imports", []):
        if entry.get("is_star"):
            continue
        origin = resolve_module(module, entry["from_module"])
        other = index.get(origin)
        if other is None:
            continue
        for declaration in facts.extract(other, module=origin, file=origin).get("declarations", []):
            if declaration.get("kind") == "class":
                found.setdefault(declaration["name"], declaration)
    return found


def to_ast_doc(
    source: str,
    *,
    module: str = "",
    profile: str = "ast",
    file: str = "<source>",
    index: dict[str, str] | None = None,
) -> Any:
    """Parse, elide by profile, and collapse resolved constructors.

    Parameters
    ----------
    source : str
        The module's text.
    module : str
        Its dotted import path.
    profile : str, optional
        One of ``awl.vocab.PROFILES``.
    file : str, optional
        A label for spans.
    index : dict, optional
        Module path to source, for the modules this one imports from. A
        parameter object is nearly always defined in another file, so without
        it the collapse almost never fires.

    Returns
    -------
    dict
        An ``AstDoc``. Only constructors whose callee resolved are collapsed;
        an unresolved name stays a plain call.
    """
    observed = facts.extract(source, module=module, file=file)
    return _tree(source, observed, module=module, profile=profile, index=index or {})


def _tree(
    source: str,
    observed: dict[str, Any],
    *,
    module: str,
    profile: str,
    index: dict[str, str],
    spans: bool = False,
) -> Any:
    """Elide and collapse against facts that have already been read.

    Split out so a document can be built with one pass of extraction. Calling
    the public entry points in sequence read every module twice and every
    module they import four times, for one answer.

    The span reaches the collapse as well as the encoder. A collapsed node is
    built here and not by the encoder, so with the two apart it was the one
    node in a located document with no position: an editor could show a
    constructor's voltage and then had nowhere to write the change back to.
    """
    types, resolved = _collapsible(observed, module, index)
    doc = elide.elide(to_doc(ast.parse(source)), profile=profile, source=source)
    return collapse.collapse(
        doc,
        types=types,
        resolved=resolved,
        embed_context=vocab.EMBEDS_CONTEXT[profile],
        keep_spans=spans,
    )


def to_compact(
    source: str,
    *,
    module: str = "",
    profile: str = "ast",
    spans: bool = False,
    file: str = "<source>",
    index: dict[str, str] | None = None,
) -> Any:
    """Run the chain and return the editor model.

    Parameters
    ----------
    spans : bool, optional
        Keep source spans, which are the join key for in-place patching and
        for the trace overlay. Not needed to regenerate code.
    """
    observed = facts.extract(source, module=module, file=file)
    tree = _tree(source, observed, module=module, profile=profile, index=index or {}, spans=spans)
    return compact.encode(tree, keep_spans=spans)


def to_document(
    source: str,
    *,
    module: str = "",
    profile: str = "ast",
    file: str = "<source>",
    index: dict[str, str] | None = None,
    layers: tuple[str, ...] | None = None,
    spans: bool | None = None,
    identities: bool | None = None,
    trivia: bool | None = None,
) -> dict[str, Any]:
    """Build the JSON-LD document a profile calls for.

    Parameters
    ----------
    source : str
        The module's text.
    module : str
        Its dotted import path.
    profile : str, optional
        A named set of generator parameters: which wrappers are transparent,
        which types go opaque, whether keywords fold, and which lookups run.
        Defaults to ``ast``, the profile whose obligation is complete value
        provenance. The reduced profiles are paused, and until each is defined
        by the class of question it must answer, choosing one only makes the
        document smaller and no better.
    file : str, optional
        A label for spans.
    index : dict, optional
        Module path to source, for the modules this one imports from.
    layers : tuple of str, optional
        Overrides the profile's lookups, for a caller who wants one of them on
        its own. Asking for ``("document",)`` gives the tree and nothing
        derived from it, which is what a reader comparing notations needs.
    spans : bool, optional
        Overrides the profile's :data:`awl.vocab.MATERIALIZES_SPANS`. On for
        every profile, because a span locates a node in the file it came from,
        which is what a patch and a trace overlay are written against.
    identities : bool, optional
        Overrides the profile's :data:`awl.vocab.MATERIALIZES_IDENTITIES`. On
        for every profile: it names each statement with the identity the plan
        mints for it, so the tree's statement and the plan's step are one node
        rather than two that happen to sit at the same coordinates. Needs
        ``spans``, which is what matches the two sides at build time.
    trivia : bool, optional
        Overrides the profile's :data:`awl.vocab.MATERIALIZES_TRIVIA`. On for
        every profile: it carries the comment written about each statement,
        which the syntax tree has no node for. Needs ``spans`` too, since a
        comment is placed against the span of the statement it describes.

    Returns
    -------
    dict
        A ``@context`` and a ``@graph``. This is the artefact; RDF is one
        serialization of it and the editor model is the first entry in it.

    Raises
    ------
    ValueError
        If a layer is not one of :data:`awl.vocab.LAYERS`, rather than quietly
        returning less than was asked for.
    """
    selected = vocab.LOOKUPS[profile] if layers is None else layers
    located = vocab.MATERIALIZES_SPANS[profile] if spans is None else spans
    named = vocab.MATERIALIZES_IDENTITIES[profile] if identities is None else identities
    noted = vocab.MATERIALIZES_TRIVIA[profile] if trivia is None else trivia
    unknown = set(selected) - set(vocab.LAYERS)
    if unknown:
        raise ValueError(f"unknown layers {sorted(unknown)}; expected some of {list(vocab.LAYERS)}")

    observed = facts.extract(source, module=module, file=file)
    # The same resolution the collapse used. Building the context from this
    # module's types alone left an imported class resolving through @vocab, so
    # the node was typed awl:ChargeParam while the collapse had named it
    # py/tier3_oold.params/ChargeParam: one entity, two IRIs.
    types, _ = _collapsible(observed, module, index or {})
    built = context.build_context(list(types.values()))

    graph: list[Any] = []
    for part in _layers(
        source,
        observed,
        selected,
        module=module,
        profile=profile,
        file=file,
        index=index,
        spans=located,
        # A statement is matched to its step by span, so without one there is
        # nothing to name and asking for both is asking for neither.
        identities=named and located,
        # Same bargain: a comment is placed against the span of the statement
        # it was written about.
        trivia=noted and located,
    ):
        graph.extend(part.get("@graph", [part]))
    return {"@context": built["@context"], "@graph": graph}


def to_graph(
    source: str,
    *,
    module: str = "",
    profile: str = "ast",
    file: str = "<source>",
    index: dict[str, str] | None = None,
    layers: tuple[str, ...] | None = None,
    spans: bool | None = None,
    identities: bool | None = None,
    trivia: bool | None = None,
):
    """Serialize :func:`to_document` as RDF, taking the same parameters.

    Returns
    -------
    rdflib.Graph

    Notes
    -----
    There is nothing here but a change of notation. What the graph contains is
    decided by the profile when the document is built, so the two cannot say
    different things about one program.
    """
    return rdf.to_graph(
        to_document(
            source,
            module=module,
            profile=profile,
            file=file,
            index=index,
            layers=layers,
            spans=spans,
            identities=identities,
            trivia=trivia,
        )
    )


def _document_layer(
    source: str,
    observed: dict[str, Any],
    layers: tuple[str, ...],
    *,
    module: str,
    profile: str,
    file: str,
    index: dict[str, str] | None,
    spans: bool,
    plan: dict[str, Any] | None,
    trivia: bool = False,
) -> Any:
    """Return the tree layer: the editor model, plus what a projection needs.

    A slot number where array position stops being recoverable, a span whose
    four numbers are named, and the identity the plan minted for each statement.
    All three are the profile's call, and all three leave the editor's own model
    alone.
    """
    tree = compact.encode(
        _tree(source, observed, module=module, profile=profile, index=index or {}, spans=spans),
        keep_spans=spans,
    )
    if vocab.MATERIALIZES_ORDERINGS[profile]:
        tree = compact.number_items(tree)
    if plan is not None:
        # Needs the span, which is what matches a statement to the step minted
        # from it. Asking for identities without spans would name nothing rather
        # than fail, so the caller resolves that before getting here.
        tree = compact.link_steps(tree, plan["steps"])
    if trivia:
        # After the identities and before the names, so a comment lands on a
        # node that is already named and a name reference added below cannot
        # be mistaken for a statement.
        tree = compact.link_trivia(tree, source)
    if "names" in layers:
        # The name stays as written, and gains a reference to what it was
        # resolved to, so a query can ask by identity instead of by spelling.
        # Only when the names lookup ran: the reference is that lookup's
        # judgement, not something the tree knows on its own.
        tree = compact.link_names(tree, resolve(observed)["bindings"])
    return compact.name_spans(tree, file=file) if spans else tree


def _layers(
    source: str,
    observed: dict[str, Any],
    layers: tuple[str, ...],
    *,
    module: str,
    profile: str,
    file: str,
    index: dict[str, str] | None,
    spans: bool,
    identities: bool = False,
    trivia: bool = False,
):
    """Yield the requested layers as documents, building only what is asked for."""
    # Before the document, because the document is stamped with what it mints.
    # Built here rather than in the plan branch below so a document can name its
    # statements without the plan layer being asked for: the identity is a
    # property of the statement, and the edges between statements are the thing
    # the plan adds.
    plan = None
    if "plan" in layers or (identities and "document" in layers):
        plan = controlflow.analyze(source, module=module, file=file)

    if "document" in layers:
        yield _document_layer(
            source,
            observed,
            layers,
            module=module,
            profile=profile,
            file=file,
            index=index,
            spans=spans,
            plan=plan if identities else None,
            trivia=trivia,
        )

    flow = None
    if {"plan", "definitions"} & set(layers):
        flow = dataflow.analyze(source, module=module, file=file)

    if "plan" in layers and plan is not None:
        _attach_condition_reads(plan, flow or {})
        # The tree locates the statement when it is naming it, and the step is
        # the same node by then. A condition keeps its own span either way: it
        # is not a statement and has no identity of its own.
        yield controlflow.as_document(plan, spans=not (identities and "document" in layers))

    if "names" in layers:
        yield {"@graph": _name_nodes(resolve(observed))}

    if "writes" in layers:
        imported = _imported_classes(observed, module, index or {})
        yield {"@graph": _write_nodes(resolve_writes(observed, imported=imported))}

    if "definitions" in layers and flow is not None:
        yield {"@graph": _flow_nodes(flow)}


def _attach_condition_reads(plan: dict[str, Any], flow: dict[str, Any]) -> None:
    """Link each condition to the definitions it reads.

    The plan knows a step is governed by a test; the def-use graph knows which
    bindings that test consulted. Neither can say it alone, and joining them
    is this module's whole job. The key is the span, as everywhere else.

    Answering with names instead would be the text-matching mistake one size
    smaller: a name is scope-blind and joins to nothing, where a definition
    identity leads straight on to where the value came from.
    """
    reads = {_span_key(entry["span"]): entry["reads"] for entry in flow.get("conditions", []) if entry.get("span")}
    for step in plan["steps"]:
        condition = step.get("condition")
        if not condition:
            continue
        found = reads.get(_span_key(condition.get("span")))
        if found:
            condition["reads"] = [{"@id": identity} for identity in found]


def _span_key(span: dict[str, Any] | None) -> tuple[Any, ...] | None:
    """Return a span's join key."""
    if not span:
        return None
    return (span.get("file"), span.get("start_line"), span.get("start_col"))


def _write_nodes(writes: dict[str, Any]) -> list[dict[str, Any]]:
    """Return the resolved member writes as graph nodes."""
    return [{"_type": "Write", **entry} for entry in writes["writes"]]


def _name_nodes(names: dict[str, Any]) -> list[dict[str, Any]]:
    """Return each resolved name as a node keyed by the identity it names.

    The tree carries a name as written, because that is what the source says
    and what regenerates it. What that name refers to is a judgement, so it is
    recorded here with the confidence it was reached at, rather than written
    onto the node as though the parser had seen it.
    """
    return [
        {
            "@id": entry["identity"]["iri"],
            "_type": "Binding",
            **{key: value for key, value in entry.items() if key != "identity"},
            **{key: value for key, value in entry["identity"].items() if key != "iri" and value is not None},
        }
        for entry in names["bindings"]
        if (entry.get("identity") or {}).get("iri")
    ]


def _flow_nodes(flow: dict[str, Any]) -> list[dict[str, Any]]:
    """Return the def-use graph as nodes keyed by definition identity."""
    return [
        {"@id": entry["id"], "_type": "Definition", **{k: v for k, v in entry.items() if k != "id"}}
        for entry in flow["definitions"]
    ]


def trace_run(
    source: str,
    call,
    *,
    module: str = "",
    file: str = "<source>",
) -> dict[str, Any]:
    """Run *call* under instrumentation and join the events onto the plan.

    Parameters
    ----------
    source : str
        The text of the module being run, so its plan can be built.
    call : callable
        Invoked with no arguments.

    Returns
    -------
    dict
        One entry per step: whether it ran, on which loop iterations, and for a
        branch which outcomes were observed.
    """
    from awl.trace import trace

    events = trace(call)
    plan = controlflow.analyze(source, module=module, file=file)
    return execution.join(plan, events)
