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

__all__ = ["analyze", "to_ast_doc", "to_compact", "to_graph"]


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


def to_ast_doc(
    source: str,
    *,
    module: str = "",
    profile: str = "ast",
    file: str = "<source>",
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

    Returns
    -------
    dict
        An ``AstDoc``. Only constructors whose callee resolved are collapsed;
        an unresolved name stays a plain call.
    """
    observed = facts.extract(source, module=module, file=file)
    types = {entry["identity"]["symbol"]: entry for entry in observed["types"]}
    resolved = {name: name for name in types}
    doc = elide.elide(to_doc(ast.parse(source)), profile=profile, source=source)
    return collapse.collapse(doc, types=types, resolved=resolved, embed_context=False)


def to_compact(
    source: str,
    *,
    module: str = "",
    profile: str = "ast",
    spans: bool = False,
    file: str = "<source>",
) -> Any:
    """Run the chain and return the editor model.

    Parameters
    ----------
    spans : bool, optional
        Keep source spans, which are the join key for in-place patching and
        for the trace overlay. Not needed to regenerate code.
    """
    return compact.encode(to_ast_doc(source, module=module, profile=profile, file=file), keep_spans=spans)


def to_graph(
    source: str,
    *,
    module: str = "",
    profile: str = "ast",
    file: str = "<source>",
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
    document = context.build_context(observed["types"])

    flow = dataflow.analyze(source, module=module, file=file)
    plan = controlflow.analyze(source, module=module, file=file)
    _attach_condition_reads(plan, flow)

    graph = Graph()
    for part in (
        to_ast_doc(source, module=module, profile=profile, file=file),
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
