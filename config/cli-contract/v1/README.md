# The vocello CLI machine contract, v1

What `vocello` prints for programs and agents in `--output-format json` (alias `--json`) and
`--output-format ndjson` (alias `--ndjson`). Text output is for people and is not part of the contract.
These files are the canonical data: the Swift side is golden-tested against them, and
`scripts/cli_contract.py validate` (run by the contract gate) keeps them consistent.

| File | What it holds |
|---|---|
| `exit-codes.json` | Every process exit status, its category and meaning. |
| `error-codes.json` | Every error code: its category, exit code, `retryable` and a summary. |
| `event-types.json` | Every NDJSON record type. |
| `envelope.schema.json` | The one object json mode prints, and the `data` of ndjson's final `result` record. |
| `error.schema.json` | The envelope's `error` object (embedded in the envelope's `$defs`). |
| `event.schema.json` | One NDJSON record (it embeds the envelope and its definitions). |
| `baseline.json` | The frozen v1 surface at `contractRevision`, and the history of revisions. |
| `examples/` | Envelopes (`.json`) and an NDJSON stream (`.jsonl`) that validate. |

## Output

- **json**: stdout holds exactly one envelope, success or failure. stderr stays quiet unless
  `--verbose`.
- **ndjson**: stdout holds one record per line, `seq` counting from 0 and `t` (seconds since the start)
  never decreasing, all with one `requestID`; the first is `started` and the last is the one `result`
  record, whose `data` is the envelope. A consumer ignores record types it does not know.
- **Envelope**: `schemaVersion` (1), `ok`, `command` (the dotted canonical path: `generate`,
  `voices.list`, `models.install`), `requestID`, `result`, `error`, `warnings` and `meta`
  (`vocelloVersion`, `build`, `contractRevision`, `durationMs`, `replayed`). A success has an object
  `result` and a null `error`. A failure has an `error` and a null `result`, except that a stopped batch
  keeps its partial `result` (every planned row).
- **Error**: `code`, `category`, `exitCode`, `message`, `retryable`, `retryAfterMs`, `hint`, `detail`.
  The process exits with `exitCode`. `retryable` is true exactly for the transient category (exit 75).
  `cancelled` exits 130 for SIGINT and 143 for SIGTERM and names the signal in `detail.signal`. A
  consumer meeting a code it does not know falls back on `category` and `exitCode`.
- **Values**: seeds and other 64-bit integers are decimal strings. `message` and `hint` are English
  prose for people; programs read `code`. No envelope or record carries text to speak, transcripts, PCM
  or private paths beyond the output paths a command returns.

## The Vocello schema profile

The schemas use a small part of JSON Schema 2020-12 so the CLI's own validator
(`scripts/lib/cli_contract_schema.py`, no third-party package) and any conforming validator agree:
`type`, `properties`, `required`, `additionalProperties: false`, `enum`, `const`, `items`, `oneOf`,
`$ref` to the same document's `$defs` only, anchored `pattern`, `minimum`, `maximum`, `maxLength` and
`description`, with `$schema`, `$id` (a `urn:vocello:cli:v1:<name>` URN, never a network location),
`title` and `$defs` at the root. An object schema with `properties` closes them with
`additionalProperties: false`: the schemas state exactly what the producer emits at their revision, so a
consumer reading a later revision ignores fields it does not know instead of validating strictly.

## Compatibility policy

v1 changes only by addition.

- **Never** remove or rename a command, flag, property, event type, error code or exit code; never
  change an exit code's category, an error code's category, exit code or `retryable`; never make a
  required property optional.
- **Allowed**: new optional properties, new commands and flags, new event types, new error codes in an
  existing category.
- Each additive change bumps `contractRevision` and records the new surface in `baseline.json`, in the
  same change: `python3 scripts/cli_contract.py record --change "<what it adds>"`. `record` refuses a
  breaking change. The CLI reports the revision it implements in `meta.contractRevision`.
- A breaking change is v2: a new `config/cli-contract/v2/`, while v1 stays available.
- Until the first release that ships the CLI with this contract (RF-31), revision 1 is still being
  built: additions re-record revision 1 (delete `baseline.json`, then `record`) instead of bumping it.
  The additive-only rule still applies to everything already recorded.

`cli_contract.py validate` fails when the tables, schemas or examples disagree, when anything in
`baseline.json` was removed or reclassified, when something new is not recorded there, and when the
exit-code table of `docs/reference/cli.md` (once it has one: a table whose header starts with "Exit" and
has a "Category" column) differs from `exit-codes.json`.

## Reading the output from Python

`scripts/lib/vocello_cli_json.py` reads both this contract and the bare per-command JSON of CLIs built
before it: `read_result` (the result, or a `VocelloCLIError`), `rows` (a list command's rows),
`read_batch` (a batch's rows, complete or stopped) and `read_ndjson` (the records and the final
envelope).
