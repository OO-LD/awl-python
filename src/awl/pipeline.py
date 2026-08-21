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

from awl import collapse, compact, context, controlflow, dataflow, elide, execution, facts, rdf
from awl.astdoc import to_doc
from awl.resolve import resolve, resolve_writes

__all__ = ["analyze", "resolve_module", "to_ast_doc", "to_compact", "to_graph"]


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
    types, resolved = _collapsible(observed, module, index or {})
    doc = elide.elide(to_doc(ast.parse(source)), profile=profile, source=source)
    return collapse.collapse(doc, types=types, resolved=resolved, embed_context=False)


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
    return compact.encode(
        to_ast_doc(source, module=module, profile=profile, file=file, index=index),
        keep_spans=spans,
    )


def to_graph(
    source: str,
    *,
    module: str = "",
    profile: str = "ast",
    file: str = "<source>",
    index: dict[str, str] | None = None,
):
    """Run the chain and return the RDF graph.

    Parameters
    ----------
    profile : str, optional
        Defaults to ``ast``, the profile whose obligation is complete value
        provenance. The reduced profiles are paused: they elide by
        construction, and until each is defined by the class of question it
        must answer, choosing one only makes the graph smaller and no better.

    Returns
    -------
    rdflib.Graph
        The document, its control-flow plan, its def-use edges and its typed
        member writes, in one graph.
    """
    from rdflib import Graph

    observed = facts.extract(source, module=module, file=file)
    # The same resolution the collapse used. Building the context from this
    # module's types alone left an imported class resolving through @vocab, so
    # the node was typed awl:ChargeParam while the collapse had named it
    # py/tier3_oold.params/ChargeParam: one entity, two IRIs.
    types, _ = _collapsible(observed, module, index or {})
    document = context.build_context(list(types.values()))

    flow = dataflow.analyze(source, module=module, file=file)
    plan = controlflow.analyze(source, module=module, file=file)
    _attach_condition_reads(plan, flow)

    graph = Graph()
    for part in (
        to_ast_doc(source, module=module, profile=profile, file=file, index=index),
        controlflow.as_document(plan),
        {"@graph": _write_nodes(resolve_writes(observed))},
        {"@graph": _flow_nodes(flow)},
    ):
        graph += rdf.to_graph(part, context=document)
    return graph


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
