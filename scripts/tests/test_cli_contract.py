#!/usr/bin/env python3
"""The CLI machine contract: the schema-profile validator and `cli_contract.py`'s checks.

Contract cases run on a copy of `config/cli-contract/v1/` in a temporary root, edited the way a
change would edit it, so each check is exercised by the outcome it guards.
"""

from __future__ import annotations

import contextlib
import copy
import io
import json
from pathlib import Path
import shutil
import sys
import tempfile
from typing import Any, Callable
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import cli_contract  # noqa: E402
from lib import cli_contract_schema as profile  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
CONTRACT = ROOT / "config" / "cli-contract" / "v1"


def load(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


class ProfileTests(unittest.TestCase):
    """The validator implements the profile and refuses schemas outside it."""

    def schema(self, **node: Any) -> dict[str, Any]:
        return {"$schema": profile.DIALECT, "$id": "urn:vocello:cli:v1:fixture", **node}

    def test_the_committed_schemas_keep_to_the_profile(self) -> None:
        for path in sorted(CONTRACT.glob("*.schema.json")):
            self.assertEqual(profile.profile_issues(load(path)), [], path.name)

    def test_keywords_outside_the_profile_are_refused(self) -> None:
        for keyword, value in (("anyOf", [{}, {}]), ("format", "uuid"), ("minLength", 1),
                               ("patternProperties", {}), ("allOf", [{}, {}]), ("if", {})):
            with self.subTest(keyword=keyword):
                issues = profile.profile_issues(self.schema(**{keyword: value}))
                self.assertTrue(any("outside the Vocello schema profile" in issue for issue in issues), issues)

    def test_references_and_identities_stay_local(self) -> None:
        network_ref = self.schema(properties={"a": {"$ref": "https://example.com/s.json"}},
                                  type="object", additionalProperties=False)
        self.assertTrue(any("only #/$defs/<name>" in issue for issue in profile.profile_issues(network_ref)))
        undefined = self.schema(**{"$ref": "#/$defs/missing"})
        self.assertTrue(any("is not defined" in issue for issue in profile.profile_issues(undefined)))
        network_id = self.schema(**{"$id": "https://example.com/envelope.json"})
        self.assertTrue(any("never a network location" in issue for issue in profile.profile_issues(network_id)))
        nested = self.schema(**{"$defs": {"a": {"$defs": {}}}})
        self.assertTrue(any("only at the document root" in issue for issue in profile.profile_issues(nested)))
        cycle = self.schema(**{"$defs": {"a": {"items": {"$ref": "#/$defs/b"}}, "b": {"$ref": "#/$defs/a"}}})
        self.assertEqual(sorted(issue for issue in profile.profile_issues(cycle) if "reaches itself" in issue),
                         ["#/$defs/a: reaches itself through $ref; the profile has no recursive schemas",
                          "#/$defs/b: reaches itself through $ref; the profile has no recursive schemas"])

    def test_objects_close_their_properties_and_patterns_are_anchored(self) -> None:
        open_object = self.schema(type="object", properties={"a": {"type": "string"}})
        self.assertTrue(any("additionalProperties: false" in issue for issue in profile.profile_issues(open_object)))
        schema_valued = self.schema(type="object", properties={}, additionalProperties={"type": "string"})
        self.assertTrue(any("only false" in issue for issue in profile.profile_issues(schema_valued)))
        unanchored = self.schema(type="string", pattern="[a-z]+")
        self.assertTrue(any("anchored" in issue for issue in profile.profile_issues(unanchored)))
        broken = self.schema(type="string", pattern="^([a-z]$")
        self.assertTrue(any("does not compile" in issue for issue in profile.profile_issues(broken)))
        unknown_required = self.schema(type="object", properties={}, additionalProperties=False, required=["a"])
        self.assertTrue(any("not among the declared" in issue for issue in profile.profile_issues(unknown_required)))
        boolean_schema = self.schema(properties={"a": True})
        self.assertTrue(any("boolean schemas" in issue for issue in profile.profile_issues(boolean_schema)))

    def test_validating_with_a_schema_outside_the_profile_raises(self) -> None:
        with self.assertRaises(profile.SchemaProfileError):
            profile.validate({}, self.schema(anyOf=[{}, {}]))


class ValidationTests(unittest.TestCase):
    """Validation semantics, with the instance path of every issue."""

    envelope = load(CONTRACT / "envelope.schema.json")

    def issues(self, instance: Any, schema: dict[str, Any] | None = None) -> list[str]:
        return [str(issue) for issue in profile.validate(instance, schema or self.envelope)]

    def example(self) -> dict[str, Any]:
        return load(CONTRACT / "examples" / "invalid-mode.json")

    def test_the_committed_examples_are_valid_envelopes(self) -> None:
        for path in sorted((CONTRACT / "examples").glob("*.json")):
            self.assertEqual(self.issues(load(path)), [], path.name)

    def test_issues_name_their_instance_paths(self) -> None:
        envelope = self.example()
        envelope["meta"]["durationMs"] = -1
        envelope["error"]["code"] = "no_such_code"
        envelope["warnings"] = [{"code": "Bad Code", "message": "m", "extra": 1}]
        del envelope["requestID"]
        found = self.issues(envelope)
        self.assertIn("$.meta.durationMs: -1 is less than the minimum 0", found)
        self.assertIn("$: missing required property 'requestID'", found)
        self.assertIn("$.warnings[0]: unexpected property 'extra'", found)
        self.assertIn('$.warnings[0].code: "Bad Code" does not match ^[a-z][a-z0-9_]*$', found)
        self.assertTrue(any(issue.startswith('$.error.code: "no_such_code" is not one of') for issue in found), found)

    def test_one_of_reports_the_closest_alternative(self) -> None:
        envelope = self.example()
        envelope["error"] = None  # a failure without an error matches neither branch
        found = self.issues(envelope)
        self.assertTrue(any("matches none of the 2 oneOf alternatives" in issue and "Failure" in issue
                            for issue in found), found)
        self.assertIn("$.error: expected object, found null", found)
        both = {"oneOf": [{"type": "integer"}, {"type": "number"}]}
        self.assertTrue(any("matches 2 oneOf alternatives" in issue for issue in self.issues(3, both)))

    def test_types_constants_and_lengths_follow_json_semantics(self) -> None:
        self.assertEqual(self.issues(2.0, {"type": "integer"}), [])
        self.assertEqual(self.issues(2, {"type": "number"}), [])
        self.assertTrue(self.issues(True, {"type": "integer"}))
        self.assertTrue(self.issues(True, {"const": 1}), "true is not 1 in JSON")
        self.assertTrue(self.issues(1, {"enum": [True, False]}))
        self.assertEqual(self.issues(None, {"type": ["string", "null"], "maxLength": 1}), [])
        self.assertTrue(self.issues("é" * 3, {"type": "string", "maxLength": 2}))
        self.assertEqual(self.issues({"b": 1, "a": [1]}, {"const": {"a": [1.0], "b": 1}}), [])

    def test_an_anchored_pattern_does_not_accept_a_trailing_newline(self) -> None:
        schema = {"type": "string", "pattern": "^[a-z]+$"}
        self.assertEqual(self.issues("abc", schema), [])
        self.assertTrue(self.issues("abc\n", schema))

    def test_check_raises_with_every_issue(self) -> None:
        with self.assertRaises(profile.SchemaValidationError) as raised:
            profile.check({"schemaVersion": 2}, self.envelope, label="fixture")
        self.assertGreater(len(raised.exception.issues), 1)
        self.assertTrue(str(raised.exception).startswith("fixture: "))


class ContractFixture(unittest.TestCase):
    """A writable copy of the committed contract in a temporary repository root."""

    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.contract = self.root / "config" / "cli-contract" / "v1"
        shutil.copytree(CONTRACT, self.contract)

    def edit(self, name: str, change: Callable[[Any], Any]) -> None:
        """Apply an in-place change to one JSON file of the copy."""
        path = self.contract / name
        value = load(path)
        change(value)
        path.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")

    def edit_error_schema(self, change: Callable[[dict[str, Any]], None]) -> None:
        """Change the error schema and its two embedded copies alike."""
        self.edit("error.schema.json", change)
        self.edit("envelope.schema.json", lambda schema: change(schema["$defs"]["error"]))
        self.edit("event.schema.json", lambda schema: change(schema["$defs"]["error"]))

    def edit_envelope_schema(self, change: Callable[[dict[str, Any]], None]) -> None:
        """Change the envelope schema and the event schema's copy alike."""
        self.edit("envelope.schema.json", change)

        def embedded(schema: dict[str, Any]) -> None:
            body = schema["$defs"]["envelope"]
            change(body)
            for name in ("error", "meta", "warning"):
                schema["$defs"][name] = copy.deepcopy(load(self.contract / "envelope.schema.json")["$defs"][name])
        self.edit("event.schema.json", embedded)

    def add_event_type(self, kind: str) -> None:
        self.edit("event-types.json", lambda document: document["eventTypes"].insert(
            -1, {"type": kind, "summary": "A fixture event."}))

        def schema(document: dict[str, Any]) -> None:
            document["properties"]["type"]["enum"].insert(-1, kind)
            document["oneOf"][1]["properties"]["type"]["enum"].append(kind)
        self.edit("event.schema.json", schema)

    def run_validate(self) -> list[str]:
        issues, _summary = cli_contract.validate(self.root)
        return issues

    def assertIssue(self, fragment: str) -> None:  # noqa: N802 (unittest naming)
        issues = self.run_validate()
        self.assertTrue(any(fragment in issue for issue in issues), f"{fragment!r} not in {issues}")


class CommittedContractTests(unittest.TestCase):
    def test_the_committed_contract_validates(self) -> None:
        issues, summary = cli_contract.validate(ROOT)
        self.assertEqual(issues, [])
        self.assertIn("v1 revision", summary)

    def test_the_command_line_reports_pass(self) -> None:
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            self.assertEqual(cli_contract.main(["--root", str(ROOT), "validate"]), 0)
        self.assertTrue(out.getvalue().startswith("CLI contract: PASS"))


class TableTests(ContractFixture):
    def test_the_copied_contract_validates(self) -> None:
        self.assertEqual(self.run_validate(), [])

    def test_an_error_code_exits_with_its_category(self) -> None:
        self.edit("error-codes.json", lambda document: document["errorCodes"][0].update(exitCode=75))
        self.assertIssue("exitCode 75 is not an exit of category failure")

    def test_retryable_is_true_exactly_for_the_transient_category(self) -> None:
        def flip(document: dict[str, Any]) -> None:
            for row in document["errorCodes"]:
                if row["code"] in ("engine_busy", "generation_failed"):
                    row["retryable"] = not row["retryable"]
        self.edit("error-codes.json", flip)
        issues = self.run_validate()
        self.assertTrue(any("engine_busy: retryable" in issue for issue in issues), issues)
        self.assertTrue(any("generation_failed: retryable" in issue for issue in issues), issues)

    def test_every_failing_category_needs_an_error_code(self) -> None:
        self.edit("exit-codes.json", lambda document: document["exitCodes"].insert(
            -2, {"exit": 79, "category": "quota", "meaning": "A fixture category."}))
        self.assertIssue("category quota has no error code")

    def test_exit_zero_alone_is_ok_and_exits_ascend(self) -> None:
        self.edit("exit-codes.json", lambda document: document["exitCodes"][1].update(category="ok"))
        self.assertIssue("exit 0, and only exit 0, has category ok")
        self.setUp()
        self.edit("exit-codes.json", lambda document: document["exitCodes"].append(document["exitCodes"][1]))
        self.assertIssue("repeats or is out of ascending order")

    def test_a_stream_needs_its_started_and_result_types(self) -> None:
        self.edit("event-types.json", lambda document: document["eventTypes"].pop())
        self.assertIssue("the result type is missing")

    def test_rows_hold_exactly_their_fields(self) -> None:
        self.edit("error-codes.json", lambda document: document["errorCodes"][0].update(httpStatus=500))
        self.assertIssue("fields must be exactly")


class SchemaAgreementTests(ContractFixture):
    def test_the_error_schema_enumerates_the_tables(self) -> None:
        self.edit_error_schema(lambda schema: schema["properties"]["code"]["enum"].remove("store_busy"))
        self.assertIssue("properties.code.enum must be")

    def test_embedded_copies_must_match_their_source(self) -> None:
        self.edit("error.schema.json", lambda schema: schema["properties"]["hint"].update(description="Changed."))
        self.assertIssue("$defs.error must equal error.schema.json")
        self.setUp()
        self.edit("envelope.schema.json", lambda schema: schema["properties"]["meta"].update(description="Changed."))
        self.assertIssue("$defs.envelope must equal envelope.schema.json")

    def test_the_event_schema_enumerates_the_event_types(self) -> None:
        self.edit("event-types.json", lambda document: document["eventTypes"].insert(
            0, {"type": "heartbeat", "summary": "A fixture event."}))
        self.assertIssue("properties.type.enum must list event-types.json's types")

    def test_every_schema_declares_its_urn(self) -> None:
        self.edit("error.schema.json", lambda schema: schema.update({"$id": "urn:vocello:cli:v1:mistake"}))
        self.assertIssue("$id must be urn:vocello:cli:v1:error")


class BaselineTests(ContractFixture):
    def test_an_addition_must_be_recorded_and_record_bumps_the_revision(self) -> None:
        self.add_event_type("heartbeat")
        self.assertIssue("event type heartbeat is not in baseline.json")
        issues, message = cli_contract.record(self.root, "Adds the heartbeat record.", "2026-10-22")
        self.assertEqual(issues, [])
        self.assertIn("revision 2", message)
        baseline = load(self.contract / "baseline.json")
        self.assertEqual(baseline["contractRevision"], 2)
        self.assertEqual(baseline["revisions"][-1],
                         {"revision": 2, "date": "2026-10-22", "change": "Adds the heartbeat record."})
        self.assertIn("heartbeat", baseline["eventTypes"])
        self.assertEqual(self.run_validate(), [])
        _issues, message = cli_contract.record(self.root, "Nothing new.", "2026-10-22")
        self.assertIn("nothing to record", message)

    def test_an_added_optional_property_is_recorded_like_any_addition(self) -> None:
        self.edit_envelope_schema(lambda schema: schema["$defs"]["meta"]["properties"].update(
            host={"type": "string", "maxLength": 64}) if "$defs" in schema else None)
        self.assertIssue("envelope.schema.json: property meta.host is not in baseline.json")
        self.assertEqual(cli_contract.record(self.root, "Adds meta.host.", "2026-10-22")[0], [])
        self.assertEqual(self.run_validate(), [])

    def test_removing_or_reclassifying_an_error_code_is_breaking(self) -> None:
        self.edit("error-codes.json", lambda document: document.update(
            errorCodes=[row for row in document["errorCodes"] if row["code"] != "store_busy"]))
        self.edit_error_schema(lambda schema: schema["properties"]["code"]["enum"].remove("store_busy"))
        self.assertIssue("error code store_busy was removed or renamed")
        issues, _message = cli_contract.record(self.root, "Drops store_busy.", "2026-10-22")
        self.assertTrue(any("store_busy was removed" in issue for issue in issues), "record refuses a break")
        self.assertEqual(load(self.contract / "baseline.json")["contractRevision"], 1)

        self.setUp()
        self.edit("error-codes.json", lambda document: next(
            row for row in document["errorCodes"] if row["code"] == "engine_busy").update(
                category="usage", exitCode=2, retryable=False))
        self.assertIssue("error code engine_busy was reclassified")

    def test_the_command_surface_only_grows(self) -> None:
        def command(document: dict[str, Any], path: str) -> dict[str, Any]:
            return next(row for row in document["commands"] if row["path"] == path)

        self.edit("commands.json", lambda document: command(document, "generate")["options"].pop(0))
        self.assertIssue("command generate: option --text was removed or renamed")

        self.setUp()
        self.edit("commands.json", lambda document: command(document, "generate")["options"][0].update(
            takesValue=False))
        self.assertIssue("command generate: option --text changed between a flag and a value")

        self.setUp()
        self.edit("commands.json", lambda document: document.update(
            commands=[row for row in document["commands"] if row["path"] != "models.install"]))
        self.assertIssue("command models.install was removed or renamed")

        self.setUp()
        self.edit("commands.json", lambda document: command(document, "voices")["aliases"].clear())
        self.assertIssue("command voices: alias voice was removed")

        self.setUp()
        self.edit("commands.json", lambda document: command(document, "generate")["options"].append(
            {"name": "fixture", "placeholder": None, "summary": "A fixture flag.", "takesValue": False,
             "type": "flag", "valueOptional": False}))
        self.assertIssue("command generate: option --fixture is not in baseline.json")
        issues, _message = cli_contract.record(self.root, "Adds --fixture.", "2026-10-22")
        self.assertEqual(issues, [])
        self.assertEqual(self.run_validate(), [])

    def test_an_exit_class_never_changes(self) -> None:
        def move(document: dict[str, Any]) -> None:
            for row in document["exitCodes"]:
                if row["exit"] == 74:
                    row["category"] = "storage"
            for_codes = load(self.contract / "error-codes.json")
            for row in for_codes["errorCodes"]:
                if row["category"] == "io":
                    row["category"] = "storage"
            (self.contract / "error-codes.json").write_text(json.dumps(for_codes), encoding="utf-8")
        self.edit("exit-codes.json", move)
        self.edit_error_schema(lambda schema: schema["properties"]["category"].update(
            enum=sorted({*schema["properties"]["category"]["enum"], "storage"} - {"io"})))
        self.assertIssue("exit 74 moved from io to storage")

    def test_removing_a_property_or_making_it_optional_is_breaking(self) -> None:
        def drop(schema: dict[str, Any]) -> None:
            if "$defs" in schema:
                meta = schema["$defs"]["meta"]
                del meta["properties"]["replayed"]
                meta["required"].remove("replayed")
        self.edit_envelope_schema(drop)
        for path in sorted((self.contract / "examples").glob("*.json")):
            self.edit(f"examples/{path.name}", lambda envelope: envelope["meta"].pop("replayed"))
        stream = self.contract / "examples" / "generate-stream.jsonl"
        records = [json.loads(line) for line in stream.read_text(encoding="utf-8").splitlines()]
        records[-1]["data"]["meta"].pop("replayed")
        stream.write_text("".join(json.dumps(record) + "\n" for record in records), encoding="utf-8")
        self.assertIssue("envelope.schema.json: property meta.replayed was removed or renamed")

        self.setUp()
        self.edit_envelope_schema(lambda schema: schema["required"].remove("warnings"))
        self.assertIssue("envelope.schema.json: property warnings is no longer required")

    def test_the_revision_history_matches_the_revision(self) -> None:
        self.edit("baseline.json", lambda baseline: baseline.update(contractRevision=2))
        self.assertIssue("revisions must hold one entry per contract revision")

    def test_a_missing_baseline_is_reported_and_record_writes_the_first(self) -> None:
        (self.contract / "baseline.json").unlink()
        self.assertIssue("baseline.json is missing")
        self.assertEqual(cli_contract.record(self.root, "The initial contract.", "2026-10-21")[0], [])
        self.assertEqual(load(self.contract / "baseline.json")["contractRevision"], 1)
        self.assertEqual(self.run_validate(), [])


class ExampleTests(ContractFixture):
    def test_an_error_must_agree_with_the_tables(self) -> None:
        self.edit("examples/invalid-mode.json", lambda envelope: envelope["error"].update(exitCode=1))
        self.assertIssue("$.error.exitCode: 1 is not an exit of category usage")
        self.setUp()
        self.edit("examples/batch-memory-pressure.json", lambda envelope: envelope["error"].update(retryable=False))
        self.assertIssue("$.error.retryable: memory_pressure has retryable true")
        self.setUp()
        self.edit("examples/invalid-mode.json", lambda envelope: envelope["error"].update(retryAfterMs=1000))
        self.assertIssue("only a retryable error suggests a wait")

    def test_a_cancellation_signal_matches_its_exit(self) -> None:
        self.edit("examples/cancelled-sigterm.json", lambda envelope: envelope["error"].update(exitCode=130))
        self.assertIssue("'SIGTERM' does not exit 130")

    def test_a_success_needs_an_object_result_and_no_error(self) -> None:
        self.edit("examples/generate-success.json", lambda envelope: envelope.update(result=None))
        self.assertIssue("matches none of the 2 oneOf alternatives")

    def test_an_example_from_a_future_revision_is_refused(self) -> None:
        self.edit("examples/speakers-list.json", lambda envelope: envelope["meta"].update(contractRevision=9))
        self.assertIssue("is newer than baseline.json's 1")

    def stream(self, change: Callable[[list[dict[str, Any]]], Any]) -> None:
        path = self.contract / "examples" / "generate-stream.jsonl"
        records = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
        change(records)
        path.write_text("".join(json.dumps(record) + "\n" for record in records), encoding="utf-8")

    def test_a_stream_is_ordered_and_ends_with_its_result(self) -> None:
        self.stream(lambda records: records[3].update(seq=7))
        self.assertIssue("$.seq: expected 3, found 7")
        self.setUp()
        self.stream(lambda records: records[3].update(t=0.0001))
        self.assertIssue("is before the previous record's")
        self.setUp()
        self.stream(lambda records: records.pop())
        self.assertIssue("the stream must end with a result record")
        self.setUp()
        self.stream(lambda records: records.pop(0))
        issues = self.run_validate()
        self.assertTrue(any("starts with a started record" in issue for issue in issues), issues)

    def test_a_stream_carries_one_request(self) -> None:
        self.stream(lambda records: records[-1]["data"].update(requestID="another"))
        self.assertIssue("the envelope names another request")
        self.setUp()
        self.stream(lambda records: records[2].update(requestID="another"))
        self.assertIssue("a stream carries one request")

    def test_a_record_type_outside_the_table_is_refused(self) -> None:
        self.stream(lambda records: records[2].update(type="heartbeat"))
        self.assertIssue('"heartbeat" is not one of')

    def test_the_examples_keep_each_kind(self) -> None:
        (self.contract / "examples" / "generate-stream.jsonl").unlink()
        self.assertIssue("keep at least one success envelope, one failure envelope and one .jsonl stream")


class DocsTableTests(ContractFixture):
    def write_docs(self, rows: list[tuple[str, str]], extra: str = "") -> None:
        path = self.root / "docs" / "reference" / "cli.md"
        path.parent.mkdir(parents=True, exist_ok=True)
        table = "\n".join(f"| `{code}` | `{category}` | Meaning. |" for code, category in rows)
        path.write_text(f"# CLI\n\n## Exit codes\n\n| Exit | Category | Meaning |\n|---|---|---|\n{table}\n{extra}",
                        encoding="utf-8")

    def canonical(self) -> list[tuple[str, str]]:
        return [(str(row["exit"]), row["category"]) for row in load(self.contract / "exit-codes.json")["exitCodes"]]

    def test_no_docs_or_no_table_is_not_checked(self) -> None:
        self.assertEqual(self.run_validate(), [])
        (self.root / "docs" / "reference").mkdir(parents=True)
        (self.root / "docs" / "reference" / "cli.md").write_text("Exit codes: `0` success.\n", encoding="utf-8")
        issues, summary = cli_contract.validate(self.root)
        self.assertEqual(issues, [])
        self.assertIn("no exit-code table", summary)

    def test_a_matching_table_passes(self) -> None:
        self.write_docs(self.canonical())
        issues, summary = cli_contract.validate(self.root)
        self.assertEqual(issues, [])
        self.assertIn("docs checked", summary)

    def test_a_differing_table_fails(self) -> None:
        rows = self.canonical()
        rows[1] = ("1", "error")
        self.write_docs(rows)
        self.assertIssue("the exit-code table lists")
        self.write_docs(self.canonical()[:-1])
        self.assertIssue("the exit-code table lists")

    def test_two_tables_are_refused(self) -> None:
        self.write_docs(self.canonical(), extra="\n| Exit code | Category |\n|---|---|\n| 0 | ok |\n")
        self.assertIssue("holds 2 exit-code tables")


class CommandLineTests(ContractFixture):
    def test_validate_exits_1_with_its_issues_on_stderr(self) -> None:
        self.edit("error-codes.json", lambda document: document["errorCodes"][0].update(exitCode=75))
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            self.assertEqual(cli_contract.main(["--root", str(self.root), "validate"]), 1)
        self.assertIn("CLI contract: FAIL", err.getvalue())
        self.assertIn("error: error-codes.json generation_failed", err.getvalue())

    def test_record_needs_a_description_and_a_date(self) -> None:
        self.assertEqual(cli_contract.record(self.root, " ", "2026-10-22")[0], ["--change must describe the change"])
        self.assertTrue(cli_contract.record(self.root, "x", "22/10/2026")[0])
        self.add_event_type("heartbeat")
        issues, _message = cli_contract.record(self.root, "Adds heartbeat.", "2026-10-01")
        self.assertTrue(any("before revision 1" in issue for issue in issues), issues)


if __name__ == "__main__":
    unittest.main()
