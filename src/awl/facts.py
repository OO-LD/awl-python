"""Observation: what the source says, with nothing inferred.

Extraction that guesses cannot be audited, and a wrong guess is
indistinguishable from an observation once it is in the graph. So this module
records ``from battery.params import ChargeParam`` as an import fact with an
alias hop and stops. Whether ``ChargeParam`` at a given call site *is* that
class is awl.resolve's judgement, and it carries a confidence tier.

User code is never imported. Tier 3 of the corpus references an experimental
oold branch that need not be installed, and the notation is statically visible,
so static analysis is sufficient.
"""

from __future__ import annotations

import ast
from typing import Any

from awl.ids import class_identity, mint

__all__ = ["extract"]

#: The base class that marks a class as carrying OO-LD semantics. Detection is
#: "a ClassDef whose bases include this", not a decorator check: with the
#: notation, @dataclass stops being the signal.
LINKED_BASE = "LinkedBaseModel"

#: Fields that carry identity rather than payload, so the collapse must not
#: emit them as data.
_IDENTITY_FIELDS = frozenset({"id", "type"})

_LINK_MARKER = "Link"
_LINKED_FIELD = "LinkedField"

#: Annotation wrappers that add nullability but not multiplicity.
_OPTIONAL = frozenset({"Optional", "typing.Optional"})

#: Annotation wrappers that declare multiplicity.
_MANY = frozenset({
    "list",
    "set",
    "tuple",
    "List",
    "Set",
    "Tuple",
    "Sequence",
    "Iterable",
    "typing.List",
    "typing.Sequence",
})


def _span(node: ast.AST, file: str) -> dict[str, Any] | None:
    """Return the source span of *node*, or None when it carries no position."""
    lineno = getattr(node, "lineno", None)
    if lineno is None:
        return None
    return {
        "file": file,
        "start_line": lineno,
        "start_col": getattr(node, "col_offset", 0),
        "end_line": getattr(node, "end_lineno", None) or lineno,
        "end_col": getattr(node, "end_col_offset", None) or 0,
    }


def _name_of(node: ast.AST | None) -> str | None:
    """Return the dotted name a node denotes, or None if it is not a name.

    ``ast.unparse`` would also work but normalises whitespace and quotes; this
    stays literal, which matters because the result is an observation.
    """
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        base = _name_of(node.value)
        return f"{base}.{node.attr}" if base else node.attr
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value  # a forward reference, written as a string
    return None


def _flatten_union(node: ast.AST) -> list[ast.AST]:
    """Return the arms of a union annotation, or the node itself."""
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.BitOr):
        return [*_flatten_union(node.left), *_flatten_union(node.right)]
    if isinstance(node, ast.Subscript) and _name_of(node.value) in ("Union", "typing.Union"):
        inner = node.slice
        if isinstance(inner, ast.Tuple):
            return [arm for element in inner.elts for arm in _flatten_union(element)]
    return [node]


def _is_none(node: ast.AST) -> bool:
    return isinstance(node, ast.Constant) and node.value is None


def _attribute_path(node: ast.AST) -> list[str] | None:
    """Return ``["dataset", "specimen", "e_mod"]`` for an attribute chain.

    Returns None when the chain is rooted in anything other than a plain name,
    for example ``df["strain"].pint``. A subscript has no declared field to
    walk to, so the path would be unresolvable and recording it would imply
    otherwise.
    """
    parts: list[str] = []
    current = node
    while isinstance(current, ast.Attribute):
        parts.append(current.attr)
        current = current.value
    if not isinstance(current, ast.Name):
        return None
    parts.append(current.id)
    return list(reversed(parts))


class _Annotation:
    """One field annotation, reduced to what the contract records.

    Mirrors the judgement ``oold.experimental.notation._unwrap`` makes at
    runtime. Two producers of one judgement that disagree is the ghost-node
    failure a level up, so this is built to be portable to that repository
    rather than restated per consumer.
    """

    __slots__ = ("is_link", "is_many", "literal", "target", "text")

    def __init__(self, node: ast.AST | None) -> None:
        self.text = ast.unparse(node) if node is not None else None
        self.is_link = False
        self.is_many = False
        self.target: str | None = None
        self.literal = False
        if node is not None:
            self._read(node)

    def _read(self, node: ast.AST) -> None:
        for arm in _flatten_union(node):
            if _is_none(arm):
                continue
            self._read_arm(arm)

    def _read_arm(self, arm: ast.AST) -> None:
        if isinstance(arm, ast.Subscript):
            container = _name_of(arm.value)
            if container == _LINK_MARKER:
                self.is_link = True
                self.target = _name_of(arm.slice)
                return
            if container in _OPTIONAL:
                # Optional[T] is T or None. Unwrapping it rather than treating
                # it as an unknown container is what lets a member path walk
                # through a nullable field, which is how most of them are
                # declared.
                self._read(arm.slice)
                return
            if container in _MANY:
                self.is_many = True
                self._read(arm.slice)
                return
        name = _name_of(arm)
        if name is None:
            return
        # A capitalised bare name is a class reference and therefore a possible
        # link target; a lowercase builtin is a literal arm. This is the one
        # place a convention is read, and it only ever widens `arms`, never
        # decides `is_link`, which comes from the declaration.
        if name[:1].isupper():
            self.target = self.target or name
        else:
            self.literal = True


def _field_from(name: str, annotation: ast.AST | None, default: ast.AST | None) -> dict[str, Any]:
    """Build one TypeInfo field from its annotation and default.

    Both link declaration forms are first class here: ``Link[T]`` inside the
    annotation and ``LinkedField(link=True)`` on the value. Neither is a
    migration stage, so neither is treated as canonical, and the two produce
    identical output apart from ``declaration_form``.
    """
    parsed = _Annotation(annotation)
    declared_link = _linked_field_link(default)

    form = "plain"
    if parsed.is_link:
        form = "Link[T]"
    elif declared_link:
        form = "LinkedField(link=True)"

    is_link = parsed.is_link or declared_link
    arms: list[str] = []
    if parsed.literal or not is_link:
        arms.append("literal")
    if is_link:
        arms.extend(("reference", "embedded"))

    return {
        "name": name,
        "is_link": is_link,
        "is_many": parsed.is_many,
        "target": parsed.target if is_link else None,
        "annotation": parsed.text,
        "declaration_form": form,
        "arms": arms,
    }


def _linked_field_link(default: ast.AST | None) -> bool:
    """Return whether *default* is ``LinkedField(link=True)``."""
    if not isinstance(default, ast.Call) or _name_of(default.func) != _LINKED_FIELD:
        return False
    return any(
        keyword.arg == "link" and isinstance(keyword.value, ast.Constant) and keyword.value.value
        for keyword in default.keywords
    )


def _declared_types(default: ast.AST | None) -> list[str]:
    """Return the instance types named by a ``type`` field default.

    ``x-oold-instance-rdf-type`` on the schema takes precedence, but it lives
    in a schema file rather than in the Python source, so this module can only
    see the inline default. Stated rather than papered over.
    """
    if isinstance(default, ast.Constant) and isinstance(default.value, str):
        return [default.value]
    if isinstance(default, ast.List):
        return [
            element.value
            for element in default.elts
            if isinstance(element, ast.Constant) and isinstance(element.value, str)
        ]
    return []


def _class_fields(node: ast.ClassDef) -> tuple[list[dict[str, Any]], list[str]]:
    """Return a class's data fields and its declared instance types."""
    fields: list[dict[str, Any]] = []
    declared: list[str] = []
    for statement in node.body:
        if not isinstance(statement, ast.AnnAssign) or not isinstance(statement.target, ast.Name):
            continue
        name = statement.target.id
        if name in _IDENTITY_FIELDS:
            if name == "type":
                declared = _declared_types(statement.value)
            continue
        fields.append(_field_from(name, statement.annotation, statement.value))
    return fields, declared


def _parameters(node: ast.FunctionDef | ast.AsyncFunctionDef) -> list[dict[str, Any]]:
    """Return a function's parameters with their annotations as written."""
    arguments = node.args
    ordered = [*arguments.posonlyargs, *arguments.args, *arguments.kwonlyargs]
    return [
        {
            "name": argument.arg,
            "annotation": ast.unparse(argument.annotation) if argument.annotation else None,
        }
        for argument in ordered
    ]


class _Walk(ast.NodeVisitor):
    """One pass, producing every SymbolFacts member.

    Populating only ``imports`` and leaving the rest empty would leave name
    resolution with nothing to bind, and make every downstream test pass
    vacuously.
    """

    def __init__(self, module: str, file: str) -> None:
        self.module = module
        self.file = file
        self.declarations: list[dict[str, Any]] = []
        self.imports: list[dict[str, Any]] = []
        self.aliases: list[dict[str, Any]] = []
        self.exports: list[dict[str, Any]] = []
        self.uses: list[dict[str, Any]] = []
        self.types: list[dict[str, Any]] = []
        self.writes: list[dict[str, Any]] = []
        self.bindings: list[dict[str, Any]] = []
        self._depth = 0
        self._functions: list[str] = []

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        prefix = "." * (node.level or 0)
        origin = prefix + (node.module or "")
        for alias in node.names:
            local = alias.asname or alias.name
            self.imports.append({
                "local_name": local,
                "imported_name": alias.name,
                "from_module": origin,
                "is_alias": alias.asname is not None,
                "is_star": alias.name == "*",
                "span": _span(node, self.file),
            })
            if alias.asname is not None:
                self.aliases.append({
                    "local_name": local,
                    "alias_of": alias.name,
                    "alias_root": f"{origin}.{alias.name}" if origin else alias.name,
                })
            self._export(local, origin=origin)
        self.generic_visit(node)

    def visit_Import(self, node: ast.Import) -> None:
        for alias in node.names:
            local = alias.asname or alias.name.split(".")[0]
            self.imports.append({
                "local_name": local,
                "imported_name": alias.name,
                "from_module": "",
                "is_alias": alias.asname is not None,
                "is_star": False,
                "span": _span(node, self.file),
            })
            if alias.asname is not None:
                self.aliases.append({
                    "local_name": local,
                    "alias_of": alias.name,
                    "alias_root": alias.name,
                })
            self._export(local, origin=alias.name)
        self.generic_visit(node)

    def visit_Call(self, node: ast.Call) -> None:
        name = _name_of(node.func)
        if name is not None:
            self.uses.append({
                "local_name": name,
                "span": _span(node, self.file),
                "argument_types": [
                    called
                    for argument in node.args
                    if isinstance(argument, ast.Call) and (called := _name_of(argument.func))
                ],
            })
        self.generic_visit(node)

    def visit_Assign(self, node: ast.Assign) -> None:
        for target in node.targets:
            self._record_write(target, node)
        self.generic_visit(node)

    def visit_AnnAssign(self, node: ast.AnnAssign) -> None:
        self._record_write(node.target, node)
        self.generic_visit(node)

    def _record_write(self, target: ast.AST, statement: ast.AST) -> None:
        """Record an assignment, as either a member write or a local binding.

        A subscript target such as ``df["strain"]`` is skipped: it has no
        declared field to walk to, so recording it would suggest a resolution
        that cannot be made.

        A single-name target is a **binding**, not a write. ``s =
        dataset.specimen`` gives ``s`` a type for the rest of the function, and
        without it a later ``s.e_mod = ...`` is unresolvable even though every
        annotation needed is present.
        """
        path = _attribute_path(target)
        if path is None:
            return
        value = getattr(statement, "value", None)
        callee = _name_of(value.func) if isinstance(value, ast.Call) else None
        common = {
            "in_function": self._functions[-1] if self._functions else None,
            "span": _span(statement, self.file),
        }
        if len(path) == 1:
            self.bindings.append({
                "name": path[0],
                "value_path": _attribute_path(value) if value is not None else None,
                "value_callee": callee,
                "annotation": (
                    ast.unparse(statement.annotation)
                    if isinstance(statement, ast.AnnAssign) and statement.annotation
                    else None
                ),
                **common,
            })
            return
        self.writes.append({"path": path, "written_by": callee, **common})

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        fields, declared = _class_fields(node)
        bases = [name for base in node.bases if (name := _name_of(base))]
        identity = class_identity(
            scheme="py",
            module=self.module,
            symbol=node.name,
            type_field_default=declared or None,
        )
        self.declarations.append({
            "kind": "class",
            "name": node.name,
            "identity": identity,
            "bases": bases,
            "fields": fields,
            "span": _span(node, self.file),
        })
        self._export(node.name)
        if LINKED_BASE in bases:
            self.types.append({
                "identity": identity,
                "declared_types": declared,
                "fields": fields,
                "span": _span(node, self.file),
            })
        self._descend(node)

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self._function(node)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        self._function(node)

    def _function(self, node: ast.FunctionDef | ast.AsyncFunctionDef) -> None:
        self.declarations.append({
            "kind": "function",
            "name": node.name,
            "identity": mint(scheme="py", module=self.module, symbol=node.name),
            "parameters": _parameters(node),
            "span": _span(node, self.file),
        })
        self._export(node.name)
        self._functions.append(node.name)
        self._descend(node)
        self._functions.pop()

    def _descend(self, node: ast.AST) -> None:
        self._depth += 1
        self.generic_visit(node)
        self._depth -= 1

    def _export(self, name: str, *, origin: str = "") -> None:
        """Record a module-level name as importable from here.

        Parameters
        ----------
        name : str
            The name as it is bound in this module.
        origin : str, optional
            Where the name came from, when it was imported rather than defined
            here. A module-level ``from .impl import Thing`` genuinely makes
            ``Thing`` importable from this module, and recording where it came
            from is what lets a re-export be followed one hop. That is an
            observation; deciding whether to follow it is resolution's call.

        Notes
        -----
        Top level only. A method is not importable, and treating it as an
        export is how a re-export resolver ends up with duplicate nodes.
        """
        if self._depth == 0 and not name.startswith("_") and name != "*":
            entry = {"exported_name": name, "module": self.module}
            if origin:
                entry["from_module"] = origin
            self.exports.append(entry)


def extract(source: str, *, module: str, file: str = "<source>") -> dict[str, Any]:
    """Read symbol facts and type info out of one module.

    Parameters
    ----------
    source : str
        The module's text.
    module : str
        Its dotted import path, used to mint identities.
    file : str, optional
        A label for spans.

    Returns
    -------
    dict
        Conforms to ``symbol-facts.schema.json``. ``types`` is populated only
        for classes deriving from ``LinkedBaseModel``; a plain dataclass yields
        a declaration with fields and no ``TypeInfo``, which is the tier 2 rung.

    Notes
    -----
    Never imports the module, and never decides what a name refers to.
    """
    walk = _Walk(module, file)
    walk.visit(ast.parse(source))
    return {
        "file": file,
        "module": module,
        "declarations": walk.declarations,
        "imports": walk.imports,
        "aliases": walk.aliases,
        "exports": walk.exports,
        "uses": walk.uses,
        "writes": walk.writes,
        "bindings": walk.bindings,
        "types": walk.types,
    }
