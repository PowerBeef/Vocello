"""Validate JSON against the Vocello schema profile, the JSON Schema subset of `config/cli-contract/`.

The toolchain carries no `jsonschema` package and the CLI contract needs no more than a small,
well-defined part of JSON Schema 2020-12, so this module implements exactly that part and refuses
any schema that reaches outside it (`profile_issues`). A schema written to the profile means the
same thing to any conforming JSON Schema 2020-12 validator.

The profile:

- at the root only: `$schema` (the 2020-12 dialect URI, an identifier that is never fetched),
  `$id` (a URN such as `urn:vocello:cli:v1:envelope`), `title` and `$defs`;
- anywhere: `type` (one name or a list of names), `properties`, `required`,
  `additionalProperties` (only `false`), `enum`, `const`, `items` (one schema for every element),
  `oneOf`, `$ref` (only `#/$defs/<name>` of the same document, never a cycle), `pattern` (anchored
  with `^` and `$`), `minimum`, `maximum`, `maxLength` and `description`;
- an object schema that declares `properties` also declares `additionalProperties: false`, so the
  schema states the producer's exact shape. A `oneOf` branch without `type` is a refinement of its
  parent and may name properties without closing them.

`validate` returns every issue with the instance path that holds it (`$.error.code`,
`$.warnings[0].message`); `check` raises `SchemaValidationError` carrying them.
"""

from __future__ import annotations

from dataclasses import dataclass
import functools
import json
import math
import re
from typing import Any, Iterable, Mapping

DIALECT = "https://json-schema.org/draft/2020-12/schema"
ID_PATTERN = re.compile(r"urn:vocello:[a-z][a-z0-9-]*(?::[a-z0-9][a-z0-9-]*)+\Z")
DEF_NAME = re.compile(r"[A-Za-z][A-Za-z0-9_]*\Z")
REF_PREFIX = "#/$defs/"
TYPES = ("object", "array", "string", "integer", "number", "boolean", "null")
ROOT_KEYWORDS = frozenset({"$schema", "$id", "title", "$defs"})
KEYWORDS = frozenset({
    "type", "properties", "required", "additionalProperties", "enum", "const", "items", "oneOf", "$ref",
    "pattern", "minimum", "maximum", "maxLength", "description",
})
IDENTIFIER = re.compile(r"[A-Za-z_][A-Za-z0-9_]*\Z")
SHOWN_ENUM_VALUES = 8
SHOWN_VALUE_CHARACTERS = 60


class SchemaProfileError(ValueError):
    """A schema uses something outside the Vocello schema profile."""

    def __init__(self, issues: list[str]) -> None:
        super().__init__("; ".join(issues))
        self.issues = issues


@dataclass(frozen=True)
class Issue:
    """One way an instance fails its schema, at an instance path such as `$.meta.durationMs`."""

    path: str
    message: str

    def __str__(self) -> str:
        return f"{self.path}: {self.message}"


class SchemaValidationError(ValueError):
    """An instance does not satisfy its schema."""

    def __init__(self, issues: list[Issue], label: str = "") -> None:
        prefix = f"{label}: " if label else ""
        super().__init__(prefix + "; ".join(str(issue) for issue in issues))
        self.issues = issues


# --------------------------------------------------------------------------- #
# JSON values
# --------------------------------------------------------------------------- #

def json_type(value: Any) -> str:
    """The JSON type name of a decoded value ("integer" for whole numbers, as JSON Schema counts them)."""
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, int):
        return "integer"
    if isinstance(value, float):
        return "integer" if math.isfinite(value) and value.is_integer() else "number"
    if isinstance(value, str):
        return "string"
    if isinstance(value, list):
        return "array"
    if isinstance(value, dict):
        return "object"
    return type(value).__name__


def json_equal(left: Any, right: Any) -> bool:
    """JSON equality: 1 equals 1.0, but true never equals 1 and key order never matters."""
    left_type, right_type = json_type(left), json_type(right)
    numeric = ("integer", "number")
    if left_type in numeric and right_type in numeric:
        return left == right
    if left_type != right_type:
        return False
    if isinstance(left, list):
        return len(left) == len(right) and all(json_equal(a, b) for a, b in zip(left, right))
    if isinstance(left, dict):
        return left.keys() == right.keys() and all(json_equal(left[key], right[key]) for key in left)
    return left == right


def _shown(value: Any) -> str:
    text = json.dumps(value, ensure_ascii=False, sort_keys=True)
    if len(text) > SHOWN_VALUE_CHARACTERS:
        text = text[:SHOWN_VALUE_CHARACTERS - 3] + "..."
    return text


def _is_number(value: Any) -> bool:
    return json_type(value) in ("integer", "number")


def child_path(path: str, key: str | int) -> str:
    if isinstance(key, int):
        return f"{path}[{key}]"
    return f"{path}.{key}" if IDENTIFIER.match(key) else f"{path}[{json.dumps(key)}]"


# --------------------------------------------------------------------------- #
# The profile
# --------------------------------------------------------------------------- #

def _ends_with_unescaped_dollar(pattern: str) -> bool:
    if not pattern.endswith("$"):
        return False
    backslashes = len(pattern[:-1]) - len(pattern[:-1].rstrip("\\"))
    return backslashes % 2 == 0


@functools.lru_cache(maxsize=None)
def compiled_pattern(pattern: str) -> re.Pattern[str]:
    """The pattern with ECMA-262 end semantics: a final `$` matches only at the very end."""
    if _ends_with_unescaped_dollar(pattern):
        pattern = pattern[:-1] + r"\Z"
    return re.compile(pattern)


def profile_issues(schema: Any) -> list[str]:
    """Every way `schema` reaches outside the profile, as `<schema path>: <problem>`; empty when it complies."""
    issues: list[str] = []
    if not isinstance(schema, dict):
        return ["#: a schema document is a JSON object"]
    if "$schema" in schema and schema["$schema"] != DIALECT:
        issues.append(f"#/$schema: must be {DIALECT} (found {_shown(schema['$schema'])})")
    if "$id" in schema and not (isinstance(schema["$id"], str) and ID_PATTERN.match(schema["$id"])):
        issues.append(f"#/$id: must be a urn:vocello: URN, never a network location (found {_shown(schema['$id'])})")
    if "title" in schema and not isinstance(schema["title"], str):
        issues.append("#/title: must be a string")
    definitions = schema.get("$defs", {})
    if not isinstance(definitions, dict):
        issues.append("#/$defs: must be an object of named schemas")
        definitions = {}
    for name, definition in definitions.items():
        if not DEF_NAME.match(name):
            issues.append(f"#/$defs/{name}: a definition name is letters, digits and _")
        _node_issues(definition, f"#/$defs/{name}", definitions, issues)
    root = {key: value for key, value in schema.items() if key not in ROOT_KEYWORDS}
    _node_issues(root, "#", definitions, issues)
    issues += [f"#/$defs/{name}: reaches itself through $ref; the profile has no recursive schemas"
               for name in _recursive_definitions(definitions)]
    return issues


def _references(node: Any) -> set[str]:
    """The $defs names a schema subtree references."""
    found: set[str] = set()
    if isinstance(node, dict):
        ref = node.get("$ref")
        if isinstance(ref, str) and ref.startswith(REF_PREFIX):
            found.add(ref[len(REF_PREFIX):])
        for value in node.values():
            found |= _references(value)
    elif isinstance(node, list):
        for value in node:
            found |= _references(value)
    return found


def _recursive_definitions(definitions: Mapping[str, Any]) -> list[str]:
    edges = {name: _references(definition) for name, definition in definitions.items()}
    recursive = []
    for start in edges:
        seen: set[str] = set()
        pending = list(edges[start])
        while pending:
            name = pending.pop()
            if name == start:
                recursive.append(start)
                break
            if name in seen or name not in edges:
                continue
            seen.add(name)
            pending.extend(edges[name])
    return recursive


def _node_issues(node: Any, at: str, definitions: Mapping[str, Any], issues: list[str]) -> None:
    if not isinstance(node, dict):
        issues.append(f"{at}: a schema is a JSON object (boolean schemas are outside the profile)")
        return
    for key in node:
        if key in ROOT_KEYWORDS:
            issues.append(f"{at}/{key}: allowed only at the document root")
        elif key not in KEYWORDS:
            issues.append(f"{at}/{key}: keyword outside the Vocello schema profile")
    kind = node.get("type")
    names: list[Any] = [kind] if isinstance(kind, str) else kind if isinstance(kind, list) else []
    if "type" in node:
        if not names or any(name not in TYPES for name in names) or len(set(map(str, names))) != len(names):
            issues.append(f"{at}/type: one of {', '.join(TYPES)}, or a list of distinct names")
    properties = node.get("properties")
    if "properties" in node:
        if not isinstance(properties, dict):
            issues.append(f"{at}/properties: must be an object of schemas")
        else:
            for name, child in properties.items():
                _node_issues(child, f"{at}/properties/{name}", definitions, issues)
    if "required" in node:
        required = node["required"]
        if not (isinstance(required, list) and all(isinstance(name, str) for name in required)
                and len(set(required)) == len(required)):
            issues.append(f"{at}/required: must be a list of distinct property names")
        elif isinstance(properties, dict):
            for name in required:
                if name not in properties:
                    issues.append(f"{at}/required: {name!r} is not among the declared properties")
    if "additionalProperties" in node and node["additionalProperties"] is not False:
        issues.append(f"{at}/additionalProperties: only false is in the profile")
    if isinstance(properties, dict) and "object" in names and node.get("additionalProperties") is not False:
        issues.append(f"{at}: an object schema with properties declares additionalProperties: false")
    if "enum" in node:
        values = node["enum"]
        if not isinstance(values, list) or not values:
            issues.append(f"{at}/enum: must be a non-empty list")
        elif any(json_equal(values[i], values[j]) for i in range(len(values)) for j in range(i)):
            issues.append(f"{at}/enum: values must be distinct")
    if "items" in node:
        _node_issues(node["items"], f"{at}/items", definitions, issues)
    if "oneOf" in node:
        branches = node["oneOf"]
        if not isinstance(branches, list) or len(branches) < 2:
            issues.append(f"{at}/oneOf: must list at least two schemas")
        else:
            for index, branch in enumerate(branches):
                _node_issues(branch, f"{at}/oneOf/{index}", definitions, issues)
    if "$ref" in node:
        ref = node["$ref"]
        target = ref[len(REF_PREFIX):] if isinstance(ref, str) and ref.startswith(REF_PREFIX) else None
        if target is None or "/" in target:
            issues.append(f"{at}/$ref: only #/$defs/<name> of the same document (found {_shown(ref)})")
        elif target not in definitions:
            issues.append(f"{at}/$ref: {ref} is not defined")
    if "pattern" in node:
        pattern = node["pattern"]
        if not isinstance(pattern, str):
            issues.append(f"{at}/pattern: must be a string")
        elif not (pattern.startswith("^") and _ends_with_unescaped_dollar(pattern)):
            issues.append(f"{at}/pattern: must be anchored with ^ and $")
        else:
            try:
                compiled_pattern(pattern)
            except re.error as error:
                issues.append(f"{at}/pattern: does not compile ({error})")
    for keyword in ("minimum", "maximum"):
        if keyword in node and not _is_number(node[keyword]):
            issues.append(f"{at}/{keyword}: must be a number")
    if "maxLength" in node and not (json_type(node["maxLength"]) == "integer" and node["maxLength"] >= 0):
        issues.append(f"{at}/maxLength: must be a non-negative integer")
    if "description" in node and not isinstance(node["description"], str):
        issues.append(f"{at}/description: must be a string")


# --------------------------------------------------------------------------- #
# Validation
# --------------------------------------------------------------------------- #

def validate(instance: Any, schema: Mapping[str, Any]) -> list[Issue]:
    """Every issue of `instance` against a profile schema; raises SchemaProfileError for a non-profile schema."""
    problems = profile_issues(schema)
    if problems:
        raise SchemaProfileError(problems)
    issues: list[Issue] = []
    _validate(instance, schema, "$", schema.get("$defs", {}), issues)
    return issues


def check(instance: Any, schema: Mapping[str, Any], *, label: str = "") -> None:
    """Raise SchemaValidationError unless `instance` satisfies `schema`."""
    issues = validate(instance, schema)
    if issues:
        raise SchemaValidationError(issues, label)


def _declared_types(node: Mapping[str, Any], definitions: Mapping[str, Any]) -> list[str] | None:
    """The type names a schema declares, through its $ref; None when it declares none."""
    while "type" not in node and isinstance(node.get("$ref"), str):
        node = definitions[node["$ref"][len(REF_PREFIX):]]
    kind = node.get("type")
    return [kind] if isinstance(kind, str) else kind if isinstance(kind, list) else None


def _type_matches(value: Any, names: Iterable[str]) -> bool:
    actual = json_type(value)
    return any(actual == name or (name == "number" and actual == "integer") for name in names)


def _validate(value: Any, node: Mapping[str, Any], path: str, definitions: Mapping[str, Any],
              issues: list[Issue]) -> None:
    if "$ref" in node:
        _validate(value, definitions[node["$ref"][len(REF_PREFIX):]], path, definitions, issues)
    if "type" in node:
        names = [node["type"]] if isinstance(node["type"], str) else node["type"]
        if not _type_matches(value, names):
            issues.append(Issue(path, f"expected {' or '.join(names)}, found {json_type(value)}"))
            return
    if "const" in node and not json_equal(value, node["const"]):
        issues.append(Issue(path, f"expected {_shown(node['const'])}, found {_shown(value)}"))
    if "enum" in node and not any(json_equal(value, allowed) for allowed in node["enum"]):
        allowed = node["enum"]
        listed = ", ".join(_shown(item) for item in allowed[:SHOWN_ENUM_VALUES])
        more = f" and {len(allowed) - SHOWN_ENUM_VALUES} more" if len(allowed) > SHOWN_ENUM_VALUES else ""
        issues.append(Issue(path, f"{_shown(value)} is not one of {listed}{more}"))
    if isinstance(value, dict):
        properties = node.get("properties", {})
        for name in node.get("required", ()):
            if name not in value:
                issues.append(Issue(path, f"missing required property {name!r}"))
        for name, child in value.items():
            if name in properties:
                _validate(child, properties[name], child_path(path, name), definitions, issues)
            elif node.get("additionalProperties") is False:
                issues.append(Issue(path, f"unexpected property {name!r}"))
    if isinstance(value, list) and "items" in node:
        for index, item in enumerate(value):
            _validate(item, node["items"], child_path(path, index), definitions, issues)
    if isinstance(value, str):
        if "maxLength" in node and len(value) > node["maxLength"]:
            issues.append(Issue(path, f"is {len(value)} characters long, more than {node['maxLength']}"))
        if "pattern" in node and not compiled_pattern(node["pattern"]).search(value):
            issues.append(Issue(path, f"{_shown(value)} does not match {node['pattern']}"))
    if _is_number(value):
        if "minimum" in node and value < node["minimum"]:
            issues.append(Issue(path, f"{_shown(value)} is less than the minimum {node['minimum']}"))
        if "maximum" in node and value > node["maximum"]:
            issues.append(Issue(path, f"{_shown(value)} is more than the maximum {node['maximum']}"))
    if "oneOf" in node:
        outcomes: list[list[Issue]] = []
        for branch in node["oneOf"]:
            branch_issues: list[Issue] = []
            _validate(value, branch, path, definitions, branch_issues)
            outcomes.append(branch_issues)
        matched = [index for index, found in enumerate(outcomes) if not found]
        if len(matched) > 1:
            issues.append(Issue(path, f"matches {len(matched)} oneOf alternatives ({matched}); exactly one must"))
        elif not matched:
            # The closest alternative is one whose declared type the value has, then the fewest issues.
            def distance(index: int) -> tuple[bool, int]:
                names = _declared_types(node["oneOf"][index], definitions)
                return (names is not None and not _type_matches(value, names), len(outcomes[index]))
            closest = min(range(len(outcomes)), key=distance)
            description = node["oneOf"][closest].get("description")
            label = f" ({description})" if isinstance(description, str) else ""
            issues.append(Issue(path, f"matches none of the {len(outcomes)} oneOf alternatives; "
                                      f"the closest, #{closest}{label}, fails:"))
            issues.extend(outcomes[closest])
