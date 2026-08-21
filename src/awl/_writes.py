"""Member-path resolution for attribute writes.

Kept beside the name resolver rather than inside it because the two answer
different questions: one asks what a *name* refers to, this asks what *member
of what class* an assignment targets, and what the range of that member is.
"""

from __future__ import annotations

from typing import Any

from awl.ids import mint

__all__ = ["resolve_writes"]

EXTRACTED = "EXTRACTED"
INFERRED = "INFERRED"
AMBIGUOUS = "AMBIGUOUS"

_WRAPPERS = ("Optional[", "List[", "list[", "Sequence[", "Set[", "set[")


def annotation_target(annotation: str | None) -> str | None:
    """Return the class an annotation denotes, ignoring wrappers and None.

    ``Optional[ModulusOfElasticity]`` denotes ``ModulusOfElasticity``. Read
    from the annotation text rather than the syntax tree, because the text is
    what the observation records.
    """
    if not annotation:
        return None
    text = annotation.strip()
    for wrapper in _WRAPPERS:
        if text.startswith(wrapper) and text.endswith("]"):
            text = text[len(wrapper) : -1].strip()
    for arm in text.split("|"):
        candidate = arm.strip().split("[")[0].strip()
        if candidate and candidate != "None" and candidate[:1].isupper():
            return candidate
    return None


class _Bound:
    """What is known about a name in scope.

    Carries the **rooted member chain**, not just the type. ``s =
    dataset.specimen`` must leave ``s.e_mod`` indistinguishable from
    ``dataset.specimen.e_mod`` in the graph: introducing a local variable is a
    developer's convenience and must not change what the code means.
    """

    __slots__ = ("chain", "root_type", "tier", "type_name")

    def __init__(
        self,
        type_name: str | None,
        tier: str,
        root_type: str | None = None,
        chain: tuple[tuple[str, str], ...] = (),
    ) -> None:
        self.type_name = type_name
        self.tier = tier
        self.root_type = root_type if root_type is not None else type_name
        self.chain = tuple(chain)


def _classes(facts: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Return the declared classes by name."""
    return {entry["name"]: entry for entry in facts.get("declarations", []) if entry.get("kind") == "class"}


def _walk(path: list[str], environment: dict[str, _Bound], classes: dict[str, dict[str, Any]]) -> _Bound | None:
    """Walk an attribute path through declared fields.

    Returns
    -------
    _Bound or None
        None when a hop cannot be walked, so nothing is reported rather than
        something guessed.
    """
    start = environment.get(path[0])
    if start is None:
        return None
    current, chain = start.type_name, list(start.chain)
    for step in path[1:]:
        declared = classes.get(current) if current else None
        if declared is None:
            return None
        field = next((item for item in declared.get("fields", []) if item["name"] == step), None)
        if field is None:
            return None
        chain.append((declared["name"], step))
        current = annotation_target(field.get("annotation"))
    return _Bound(current, start.tier, start.root_type, tuple(chain))


def _bound_from(
    binding: dict[str, Any],
    environment: dict[str, _Bound],
    classes: dict[str, dict[str, Any]],
) -> _Bound | None:
    """Return what a local binding gives its name, or None.

    Three sources, in order: an explicit annotation on the assignment, an
    attribute path whose chain is already known, and a constructor call naming
    a declared class.
    """
    annotated = annotation_target(binding.get("annotation"))
    if annotated:
        return _Bound(annotated, EXTRACTED)

    value_path = binding.get("valuePath")
    if value_path:
        walked = _walk(value_path, environment, classes)
        if walked is not None and walked.type_name:
            # Following a local alias is a deduction, not a reading: no flow
            # analysis happens here, so a binding made inside a branch is
            # assumed to reach a later write. The chain is carried through, so
            # the alias is transparent in the graph while the confidence tier
            # still records that it was followed.
            return _Bound(walked.type_name, INFERRED, walked.root_type, walked.chain)

    callee = binding.get("valueCallee")
    if callee and callee.split(".")[0] in classes:
        return _Bound(callee.split(".")[0], INFERRED)
    return None


def _describe(event: dict[str, Any], walked: _Bound | None, identity_for) -> dict[str, Any]:
    """Turn one resolved write into its output entry."""
    entry: dict[str, Any] = {
        "path": ".".join(event["path"]),
        "span": event["span"],
        "writtenBy": event.get("writtenBy"),
        "confidence": AMBIGUOUS,
    }
    if walked is None or not walked.chain or walked.root_type is None:
        return entry

    owner, member = walked.chain[-1]
    entry["rootType"] = identity_for(walked.root_type)
    entry["memberOf"] = identity_for(owner)
    entry["member"] = f"{identity_for(owner)}/{member}"
    # Canonical and alias-independent, unlike `path`, which is the text the
    # developer happened to write.
    entry["memberPath"] = ".".join([walked.root_type, *(step for _, step in walked.chain)])
    if walked.type_name is not None:
        entry["range"] = identity_for(walked.type_name)
        entry["rangeName"] = walked.type_name
        entry["confidence"] = walked.tier
    return entry


def resolve_writes(facts: dict[str, Any], *, scheme: str = "py") -> dict[str, Any]:
    """Resolve each attribute write to the member it targets.

    Parameters
    ----------
    facts : dict
        A ``SymbolFacts`` document, whose ``writes`` carry attribute paths,
        whose ``bindings`` carry local aliases, and whose ``declarations``
        carry the annotations to walk them against.
    scheme : str, optional
        Language dimension passed through to minting.

    Returns
    -------
    dict
        ``{"file": ..., "writes": [...]}``. Each entry carries the path as
        written, the canonical member path, the member assigned, the class
        declaring it, the class the chain started from, the range, and a
        confidence tier.

    Notes
    -----
    This turns "an attribute named ``e_mod`` was assigned at line 74" into "the
    modulus of elasticity of a tensile test specimen, reached from a tensile
    test dataset, was assigned at line 74, by ``ModulusOfElasticity.from_pint``".

    Bindings and writes are replayed in **source order** within each function,
    so a local alias is in scope for the writes that follow it and the rooted
    chain is carried across it. ``s = dataset.specimen`` followed by ``s.e_mod
    = ...`` therefore produces the same member, owner and root as the direct
    form, differing only in confidence.

    A hop that cannot be walked yields ``AMBIGUOUS`` rather than a guess.
    """
    classes = _classes(facts)
    imports = {entry["localName"]: entry for entry in facts.get("imports", [])}
    module = facts.get("module", "")

    def identity_for(class_name: str) -> str:
        """Mint the identity of a class, following its import if it has one."""
        imported = imports.get(class_name)
        if imported is not None:
            return mint(scheme=scheme, module=imported["fromModule"], symbol=class_name)["iri"]
        return mint(scheme=scheme, module=module, symbol=class_name)["iri"]

    def position(event: dict[str, Any]) -> tuple[int, int]:
        span = event.get("span") or {}
        return span.get("startLine", 0), span.get("startCol", 0)

    events: list[dict[str, Any]] = [
        *({"kind": "binding", **entry} for entry in facts.get("bindings", [])),
        *({"kind": "write", **entry} for entry in facts.get("writes", [])),
    ]
    events.sort(key=position)

    environments: dict[str | None, dict[str, _Bound]] = {}
    for entry in facts.get("declarations", []):
        if entry.get("kind") != "function":
            continue
        environments[entry["name"]] = {
            parameter["name"]: _Bound(target, EXTRACTED)
            for parameter in entry.get("parameters", [])
            if (target := annotation_target(parameter.get("annotation")))
        }

    resolved = []
    for event in events:
        environment = environments.setdefault(event.get("inFunction"), {})

        if event["kind"] == "binding":
            bound = _bound_from(event, environment, classes)
            if bound is None:
                # A rebinding to something unknown drops the old type rather
                # than leaving a stale one in scope.
                environment.pop(event["name"], None)
            else:
                environment[event["name"]] = bound
            continue

        resolved.append(_describe(event, _walk(event["path"], environment, classes), identity_for))

    return {"file": facts["file"], "writes": resolved}
