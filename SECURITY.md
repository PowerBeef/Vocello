# Security policy

## Supported versions

Security fixes are applied to the current source on `main` and, when practical, to the latest
public macOS release. Older releases and development snapshots are not supported security branches.

| Surface | Supported |
| --- | --- |
| Current `main` | Yes |
| Latest signed and notarized macOS release | Yes |
| Older releases and beta snapshots | No |
| iPhone builds distributed outside an official project channel | No |

## Dependency monitoring

Dependabot monitors the repository's GitHub Actions, website npm lock, and owned Swift package
declarations. The security workflow also submits privacy-safe dependency snapshots from both
tracked SwiftPM resolution files after changes land on `main`, on the weekly security schedule,
and when run manually. These snapshots make the root Xcode workspace and the owned Qwen3 runtime
visible to GitHub's dependency graph and advisory matching without uploading source, credentials,
absolute paths, or local device data.

Pull requests receive dependency-diff review for newly introduced high-severity findings.
Path-relevant CodeQL runs for native or website changes, and the website lock receives a
high-severity npm advisory audit whenever website paths are relevant. The weekly schedule and
manual dispatch conservatively run both surfaces. `Security required` aggregates those jobs into a
stable exact-commit verdict; skipped irrelevant jobs do not become false failures. Release SBOM
generation continues to use the committed lock files as its authoritative input.

The repository intentionally permits its maintainer to develop directly on `main`, so that
administrator bypass is treated as a residual risk rather than as release authorization. A release
candidate requires an annotated version tag whose signature GitHub verifies as valid, a tag commit
contained in `origin/main`, and latest successful `CI required` and `Security required` check runs
on that exact commit. Candidate creation and later public promotion both re-evaluate this authority
and fail closed on lightweight or unsigned tags, missing checks, cross-commit evidence, or an
incomplete check-run response.

## Report a vulnerability privately

Do not open a public issue for a suspected vulnerability or include user data, credentials, model
tokens, private audio, prompts, transcripts, absolute paths, device identifiers, or exploit details
in public project content.

Use the repository's **Security** tab and select **Report a vulnerability** to open a private
security advisory with the maintainer. Include the affected version or commit, platform, impact,
and minimal reproduction steps. If private vulnerability reporting is temporarily unavailable,
contact the repository owner privately through their GitHub profile and provide only enough detail
to establish a secure follow-up channel.

The maintainer will acknowledge a complete report when it is reviewed, coordinate validation and a
fix privately, and publish an advisory after affected users have a reasonable update path. Exact
response times are not promised for this maintainer-run project.

## Scope

In scope: the Vocello macOS/iPhone applications, the `vocello` CLI, signed release artifacts,
release automation, model-download integrity, local persistence, XPC boundaries, and the project
website. Upstream vulnerabilities in Qwen, MLX, Apple frameworks, GitHub Actions, npm packages, or
Hugging Face should also be reported to their owners; report them here when Vocello needs a
mitigation or ships an affected version.
