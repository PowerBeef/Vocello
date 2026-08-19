#!/usr/bin/env python3
"""Validate active Vocello documentation against repository-owned interfaces."""

from __future__ import annotations

import argparse
import glob
import json
import re
import subprocess
import sys
import urllib.parse
from pathlib import Path


CONTRACT_PATH = Path("config/documentation-contract.json")
PUBLIC_FACTS_PATH = Path("config/public-product-facts.json")
OPTIONAL_CAPABILITY_CLAIMS = {
    "installed GitHub integration": "describe GitHub integration as conditional and keep gh as fallback",
    "Build iOS Apps supplies": "describe the shared XcodeBuildMCP route as conditional when callable",
    "The plugin supplies the one shared XcodeBuildMCP": "describe the shared XcodeBuildMCP route as conditional when callable",
    "Codex/ChatGPT Desktop only": "describe scripts-first agents; optional MCP tooling is never a prerequisite",
    "Development is Codex-first": "describe scripts-first development with optional MCP assists",
}
SCRIPT_HELP_SURFACES = {
    "scripts/ui_test.sh",
    "scripts/macos_test.sh",
    "scripts/ios_device.sh",
    "scripts/clean_build_caches.sh",
    "scripts/build.sh",
}
CURRENT_RUNTIME_STALE_GUIDANCE = {
    re.compile(r"\.unbounded", re.I):
        "current generation event streams are bounded on both platforms",
    re.compile(r"bufferingNewest\(64\)", re.I):
        "the current iOS generation event capacity is 96",
    re.compile(r"bufferingNewest\((?:96|256)\)", re.I):
        "product events now use the custom bounded suspending router without eviction",
    re.compile(r"streaming\s+chunk(?:'s)?\s+`?previewAudio`?\s+PCM\s+is\s+emitted", re.I):
        "preview PCM cannot be described as using the coalescing GenerationEvent route",
    re.compile(
        r"(?:cooperative(?:[- ]only)?\s+(?:iOS\s+)?cancel|iOS\s+cancel[^\n]{0,40}cooperative(?:[- ]only)?)",
        re.I,
    ):
        "iOS cancellation now owns and awaits the active generation task",
    re.compile(r"does not conform to `?ActiveGenerationCancellable`?", re.I):
        "MLXTTSEngine now provides the ActiveGenerationCancellable capability",
}


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _expand_group(root: Path, patterns: list[str]) -> set[Path]:
    paths: set[Path] = set()
    for pattern in patterns:
        paths.update(path for path in root.glob(pattern) if path.is_file())
    return paths


def documentation_groups(root: Path) -> list[dict]:
    contract = load_json(root / CONTRACT_PATH)
    return contract["groups"]


def active_markdown_paths(root: Path) -> list[Path]:
    if not (root / CONTRACT_PATH).is_file():
        # Small fixture fallback. Production inventory is always manifest-owned.
        candidates = [
            root / "AGENTS.md",
            root / "README.md",
            root / "CONTRIBUTING.md",
            root / "PRODUCT.md",
            root / "website/AGENTS.md",
        ]
        candidates.extend((root / ".agents/rules").glob("*.md"))
        candidates.extend((root / "docs/reference").glob("*.md"))
        return sorted(
            path for path in candidates if path.is_file()
            and path.name != "backend-optimization-research-report.md"
            and "releases" not in path.parts
        )
    paths: set[Path] = set()
    historical: set[Path] = set()
    for group in documentation_groups(root):
        if group["status"] == "historical":
            historical.update(_expand_group(root, group["paths"]))
    for group in documentation_groups(root):
        if group["status"] != "active":
            continue
        paths.update(_expand_group(root, group["paths"]))
    return sorted(paths - historical)


def historical_markdown_paths(root: Path) -> list[Path]:
    if not (root / CONTRACT_PATH).is_file():
        paths = [path for path in (root / "docs").glob("releases/*.md") if path.is_file()]
        backend = root / "docs/reference/backend-optimization-research-report.md"
        if backend.is_file():
            paths.append(backend)
        return sorted(paths)
    paths: set[Path] = set()
    for group in documentation_groups(root):
        if group["status"] == "historical":
            paths.update(_expand_group(root, group["paths"]))
    return sorted(paths)


def markdown_slug(value: str) -> str:
    value = re.sub(r"<[^>]+>", "", value).strip().lower()
    value = re.sub(r"[^\w\- ]", "", value, flags=re.UNICODE)
    return re.sub(r"\s", "-", value)


def headings(path: Path) -> set[str]:
    found: set[str] = set()
    counts: dict[str, int] = {}
    fenced = False
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.lstrip().startswith("```"):
            fenced = not fenced
            continue
        if fenced:
            continue
        match = re.match(r"^#{1,6}\s+(.+?)\s*#*\s*$", line)
        if not match:
            continue
        base = markdown_slug(match.group(1))
        index = counts.get(base, 0)
        counts[base] = index + 1
        found.add(base if index == 0 else f"{base}-{index}")
    return found


def validate_relative_links(root: Path, paths: list[Path]) -> list[str]:
    errors: list[str] = []
    pattern = re.compile(r"\[[^\]]*\]\(([^)]+)\)")
    anchor_cache: dict[Path, set[str]] = {}
    for source in paths:
        text = source.read_text(encoding="utf-8")
        for raw_target in pattern.findall(text):
            target = raw_target.strip().strip("<>")
            if not target or target.startswith(("http://", "https://", "mailto:", "plugin://")):
                continue
            path_part, separator, anchor = target.partition("#")
            resolved = source if not path_part else (source.parent / urllib.parse.unquote(path_part)).resolve()
            if not resolved.exists():
                errors.append(f"{source.relative_to(root)}: missing relative link target {raw_target}")
                continue
            if separator and anchor and resolved.suffix.lower() == ".md":
                available = anchor_cache.setdefault(resolved, headings(resolved))
                decoded = urllib.parse.unquote(anchor).lower()
                if decoded not in available and decoded.lstrip("-") not in {item.lstrip("-") for item in available}:
                    errors.append(f"{source.relative_to(root)}: missing Markdown heading anchor {raw_target}")
    return errors


def validate_script_references(root: Path, paths: list[Path]) -> list[str]:
    errors: list[str] = []
    pattern = re.compile(r"(?<![A-Za-z0-9_])(?:\./)?(scripts/[A-Za-z0-9_.*?/-]+\.(?:sh|py))")
    for source in paths:
        for raw in pattern.findall(source.read_text(encoding="utf-8")):
            candidate = raw.rstrip(".,;:")
            matches = glob.glob(str(root / candidate)) if any(char in candidate for char in "*?") else []
            if not matches and not (root / candidate).is_file():
                errors.append(f"{source.relative_to(root)}: missing repository script {candidate}")
    return errors


def validate_repository_paths(root: Path, paths: list[Path]) -> list[str]:
    prefixes = ("Sources/", "Tests/", "scripts/", "config/", ".github/", ".agents/", ".codex/", "docs/", "benchmarks/", "website/", "Packages/")
    generated_roots: set[str] = set()
    contract_path = root / CONTRACT_PATH
    if contract_path.is_file():
        contract = load_json(contract_path)
        generated_roots = {
            entry["path"].strip("/")
            for entry in contract.get("generatedRepositoryPaths", [])
            if isinstance(entry, dict) and isinstance(entry.get("path"), str)
        }
    errors: list[str] = []
    for source in paths:
        text = source.read_text(encoding="utf-8")
        for value in re.findall(r"`([^`\n]+)`", text):
            candidate = value.strip().split()[0].rstrip(".,;:")
            candidate = re.sub(r":\d+(?:-\d+)?$", "", candidate)
            if not candidate.startswith(prefixes) or any(marker in candidate for marker in ("<", ">", "{", "}", "$", "...")):
                continue
            normalized = candidate.rstrip("/")
            if any(normalized == root_path or normalized.startswith(root_path + "/") for root_path in generated_roots):
                continue
            matches = glob.glob(str(root / candidate)) if "*" in candidate else []
            if not matches and (root / candidate).exists():
                matches = [str(root / candidate)]
            if not matches and candidate.startswith(("Sources/", "Tests/")):
                runtime = root / "Packages/VocelloQwen3Core" / candidate
                if runtime.exists():
                    matches = [str(runtime)]
            if not matches:
                errors.append(f"{source.relative_to(root)}: stale inline repository path {candidate}")
    return errors


def _allowed_build_paths(manifest: dict) -> set[str]:
    paths = {entry["path"].rstrip("/") for entry in manifest["entries"]}
    paths.update(link["path"].rstrip("/") for link in manifest.get("publicLinks", []))
    allowed = {"build"}
    for path in paths:
        parts = Path(path).parts
        allowed.update("/".join(parts[:index]) for index in range(1, len(parts) + 1))
    return allowed | paths


def validate_build_references(root: Path, paths: list[Path]) -> list[str]:
    manifest = load_json(root / "config/build-output-policy.json")
    allowed = _allowed_build_paths(manifest)
    owned_roots = {entry["path"].rstrip("/") for entry in manifest["entries"]}
    owned_roots.update(link["path"].rstrip("/") for link in manifest.get("publicLinks", []))
    pattern = re.compile(r"(?P<path>build/[A-Za-z0-9_.{}<>/,-]+)")
    errors: list[str] = []
    for source in paths:
        text = source.read_text(encoding="utf-8")
        regions = [(match.group(1), match.start(1)) for match in re.finditer(r"`([^`\n]+)`", text)]
        regions.extend((match.group(1), match.start(1)) for match in re.finditer(r"```[^\n]*\n(.*?)```", text, re.DOTALL))
        for region, offset in regions:
            for match in pattern.finditer(region):
                candidate = match.group("path").rstrip("/.,;:")
                static = re.split(r"[<{]", candidate, maxsplit=1)[0].rstrip("/")
                if static in allowed or any(candidate == owned or candidate.startswith(owned + "/") for owned in owned_roots):
                    continue
                line = text.count("\n", 0, offset + match.start("path")) + 1
                errors.append(f"{source.relative_to(root)}:{line}: unowned documented build path {candidate}")
    return errors


def validate_optional_capabilities(root: Path, paths: list[Path]) -> list[str]:
    checked = list(paths)
    for relative in (".xcodebuildmcp/config.yaml", "docs/project-map.html"):
        path = root / relative
        if path.is_file():
            checked.append(path)
    errors: list[str] = []
    for source in checked:
        text = source.read_text(encoding="utf-8")
        for phrase, remediation in OPTIONAL_CAPABILITY_CLAIMS.items():
            if phrase in text:
                errors.append(f"{source.relative_to(root)}: {remediation}; found {phrase!r}")
    return errors


def validate_current_runtime_guidance(root: Path, paths: list[Path]) -> list[str]:
    """Reject high-risk prose that contradicts current executable contracts."""
    errors: list[str] = []
    for source in paths:
        text = source.read_text(encoding="utf-8")
        for pattern, remediation in CURRENT_RUNTIME_STALE_GUIDANCE.items():
            match = pattern.search(text)
            if match:
                line = text.count("\n", 0, match.start()) + 1
                errors.append(
                    f"{source.relative_to(root)}:{line}: {remediation}; found {match.group(0)!r}"
                )

    architecture_path = root / "docs/ARCHITECTURE.md"
    if architecture_path.is_file():
        architecture = architecture_path.read_text(encoding="utf-8")
        for required in (
            "frame-bounded suspending audio channel",
            "audio-bearing events are not evicted",
        ):
            if required not in architecture:
                errors.append(f"docs/ARCHITECTURE.md: missing current event-delivery contract {required}")
        if "config/runtime-debug-knobs.json" not in architecture:
            errors.append("docs/ARCHITECTURE.md: runtime-debug registry is missing from active architecture")
        if "config/concurrency-safety.json" not in architecture:
            errors.append("docs/ARCHITECTURE.md: concurrency-safety registry is missing from active architecture")

    agents_path = root / "AGENTS.md"
    if agents_path.is_file():
        agents = agents_path.read_text(encoding="utf-8")
        for required in ("config/runtime-debug-knobs.json", "config/concurrency-safety.json"):
            if required not in agents:
                errors.append(f"AGENTS.md: missing authoritative runtime contract {required}")

    errors.extend(validate_model_catalog_guidance(root))
    return errors


def validate_model_catalog_guidance(root: Path) -> list[str]:
    """Bind active prose and product routing to the generated catalog state."""
    catalog_path = root / "Sources/Resources/qwenvoice_production_model_catalog.json"
    if not catalog_path.is_file():
        return []
    catalog = load_json(catalog_path)
    state = catalog.get("activationState")
    errors: list[str] = []
    critical_docs = (
        "AGENTS.md",
        ".agents/rules/backend-mlx.md",
        ".agents/rules/release-qa.md",
        "docs/ARCHITECTURE.md",
        "docs/development-progress.md",
        "docs/reference/model-delivery.md",
        "docs/project-map.html",
    )
    if state == "staged":
        for relative in ("docs/ARCHITECTURE.md", "docs/development-progress.md"):
            target = root / relative
            if not target.is_file():
                continue
            text = target.read_text(encoding="utf-8").lower()
            if "staged" not in text or "quality" not in text or "pending" not in text:
                errors.append(
                    f"{relative}: staged catalog must state that Quality identities remain pending"
                )
        return errors
    if state != "complete":
        return ["production model catalog activationState must be staged or complete"]
    if catalog.get("missingArtifactIdentities") not in ([], None):
        errors.append("complete production model catalog cannot report missing artifact identities")
    stale = re.compile(
        r"(?:catalog[^\n]{0,100}staged|quality[^\n]{0,100}(?:remain|is|are)[^\n]{0,40}pending|"
        r"speed[^\n]{0,80}complete[^\n]{0,80}quality[^\n]{0,80}pending)",
        re.IGNORECASE,
    )
    for relative in critical_docs:
        target = root / relative
        if not target.is_file():
            continue
        text = target.read_text(encoding="utf-8")
        if stale.search(text):
            errors.append(f"{relative}: complete model catalog is described as staged or Quality-pending")
        if "complete" not in text.lower():
            errors.append(f"{relative}: active guidance does not state that the model catalog is complete")
    for relative in (
        "Sources/ViewModels/ModelManagerViewModel.swift",
        "Sources/VocelloCLI/ModelsCommand.swift",
    ):
        target = root / relative
        if not target.is_file():
            continue
        text = target.read_text(encoding="utf-8")
        for token in ("ProductionModelCatalog", "downloadFiles"):
            if token not in text:
                errors.append(f"{relative}: complete catalog runtime route is missing {token}")
        if "downloadRepo(" in text:
            errors.append(f"{relative}: product route must not restore live repository enumeration")
    return errors


def _top_level_names(project: str, section: str) -> list[str]:
    start = re.search(rf"(?m)^{re.escape(section)}:\s*$", project)
    if not start:
        return []
    values: list[str] = []
    for line in project[start.end():].splitlines():
        if line and not line.startswith(" "):
            break
        match = re.match(r"^  ([A-Za-z0-9_-]+):\s*$", line)
        if match:
            values.append(match.group(1))
    return values


def benchmark_baseline_status(root: Path, platform: str) -> bool:
    for path in (root / "benchmarks/runs").glob("*/*.json"):
        try:
            record = load_json(path)
        except (OSError, json.JSONDecodeError):
            continue
        run = record.get("run", {})
        source = record.get("source", {})
        if (record.get("schemaVersion") == 2 and run.get("platform") == platform
                and run.get("classification") == "canonical" and not source.get("dirty")
                and run.get("status") in {"passed", "passedWithWarnings"}):
            return True
    return False


def validate_facts(root: Path) -> list[str]:
    errors: list[str] = []
    public = load_json(root / PUBLIC_FACTS_PATH)
    hardware = load_json(root / "benchmarks/hardware-profiles.json")
    models = load_json(root / "Sources/Resources/qwenvoice_contract.json")
    project = (root / "project.yml").read_text(encoding="utf-8")
    targets = _top_level_names(project, "targets")
    schemes = _top_level_names(project, "schemes")
    cli_template = root / "config/xcode-schemes/VocelloCLI.xcscheme.template"
    ios_logic_template = root / "config/xcode-schemes/VocelloiOSLogic.xcscheme.template"
    if len(targets) != 13:
        errors.append(f"project.yml: expected 13 targets, found {len(targets)}")
    if len(schemes) != 4 or not cli_template.is_file() or not ios_logic_template.is_file():
        errors.append(
            "project schemes must contain four XcodeGen schemes plus the generated "
            "VocelloCLI and VocelloiOSLogic schemes"
        )
    architecture = (root / "docs/ARCHITECTURE.md").read_text(encoding="utf-8")
    if "13 targets" not in architecture or "six shared schemes" not in architecture.lower():
        errors.append("docs/ARCHITECTURE.md: target/scheme inventory must state 13 targets and six shared schemes")
    if re.search(r"QwenVoiceBackendCore[^\n]{0,120}(?:Low-level MLX|MLX/audio primitives|owns model load|owns codecs)", architecture, re.I):
        errors.append("docs/ARCHITECTURE.md: BackendCore is incorrectly described as the MLX/codec implementation boundary")
    qwen = (root / "docs/reference/qwen3-tts-guide.md").read_text(encoding="utf-8")
    if re.search(r"Code Predictor[^\n]{0,100}greedy", qwen, re.I):
        errors.append("docs/reference/qwen3-tts-guide.md: Code Predictor cannot be described as unconditionally greedy")
    mimi = (root / "docs/reference/mimi-codec-guide.md").read_text(encoding="utf-8")
    if any(re.search(r"100[^\n]{0,80}0\.8\s*(?:s|seconds)", line, re.I) and "not 0.8" not in line.lower() for line in mimi.splitlines()):
        errors.append("docs/reference/mimi-codec-guide.md: 100 frames at 12.5 Hz are about 8 seconds, not 0.8")
    profiles = {item["id"] for item in hardware["profiles"]}
    for platform, profile in public["canonicalBenchmarkProfiles"].items():
        if profile not in profiles:
            errors.append(f"public-product-facts: unknown {platform} hardware profile {profile}")
    if not models.get("models") or not models.get("speakers"):
        errors.append("qwenvoice_contract.json: public model/speaker contract is empty")
    version = public["stableMacRelease"]["version"]
    if f'MARKETING_VERSION: "{version}"' not in project:
        errors.append("public-product-facts stable Mac version differs from project.yml")
    readme = (root / "README.md").read_text(encoding="utf-8")
    website = "\n".join(
        path.read_text(encoding="utf-8")
        for path in (root / "website/src").rglob("*.jsx")
    )
    if version not in readme or version not in website:
        errors.append("public stable Mac release is missing from README or website copy")
    if public["ios"]["minimumDevice"] not in readme:
        errors.append("README minimum iPhone support differs from public-product-facts")
    ios_status = public["ios"]["distributionStatus"]
    if ios_status == "implemented-distribution-pending":
        pending_phrases = (
            "arriving soon",
            "distribution pending",
            "not public yet",
            "public distribution is not",
            "awaiting public distribution",
        )
        readme_pending = any(phrase in readme.lower() for phrase in pending_phrases)
        website_pending = any(phrase in website.lower() for phrase in pending_phrases)
        if not readme_pending or not website_pending:
            errors.append("public iPhone distribution-pending status is missing from README or website")
    elif ios_status == "public-testflight-beta":
        beta_link = public["ios"].get("testflightPublicLink", "")
        if not beta_link or beta_link not in readme:
            errors.append("public TestFlight beta link is missing from README")
        if "testflight" not in website.lower():
            errors.append("public TestFlight beta status is missing from website copy")
    else:
        errors.append(f"public-product-facts: unknown iOS distributionStatus {ios_status}")
    progress = (root / "docs/development-progress.md").read_text(encoding="utf-8")
    if benchmark_baseline_status(root, "macos") and "clean canonical macOS schema-v2 baseline exists" not in progress:
        errors.append("docs/development-progress.md: tracked history has a clean canonical macOS baseline but the checkpoint does not")
    if not benchmark_baseline_status(root, "ios") and "clean canonical iPhone schema-v2 baseline remains pending" not in progress:
        errors.append("docs/development-progress.md: iPhone clean canonical status must remain pending")
    return errors


def validate_readme_public_contract(root: Path) -> list[str]:
    """Keep the GitHub landing page aligned with public product contracts."""
    readme_path = root / "README.md"
    if not readme_path.is_file():
        return ["README.md: public product page is missing"]
    readme = readme_path.read_text(encoding="utf-8")
    public = load_json(root / PUBLIC_FACTS_PATH)
    version = public["stableMacRelease"]["version"]
    tag = public["stableMacRelease"]["tag"]
    direct_dmg = (
        "https://github.com/PowerBeef/Vocello/releases/download/"
        f"{tag}/Vocello-macos26.dmg"
    )
    errors: list[str] = []
    rejected = {
        r"(?i)every generation records its sampling seed":
            "interactive generations cannot be described as universally seed-replayable",
        r"(?i)exactly like the Mac app":
            "iPhone copy must preserve its platform-specific runtime and model-variant differences",
        r"https://vocello\.vercel\.app/assets/screens/":
            "README product screenshots must use repository-versioned assets",
        r"(?i)social preview \(maintainers\)":
            "repository administration instructions do not belong on the public product page",
        "—":
            "public product copy bans em dashes; use commas, colons, semicolons, periods, or parentheses",
    }
    for pattern, message in rejected.items():
        if re.search(pattern, readme):
            errors.append(f"README.md: {message}")
    if direct_dmg not in readme:
        errors.append(f"README.md: stable {version} install CTA must link directly to the DMG asset")
    if "[mlx-audio-swift](https://github.com/Blaizzy/mlx-audio-swift)" not in readme:
        errors.append("README.md: acknowledgements must identify the actual mlx-audio-swift upstream")
    if not re.search(r"(?is)\|\s*Mac\s*\|[^\n]+Speed \(4-bit\) and Quality \(8-bit\)", readme):
        errors.append("README.md: Mac model availability must state Speed and Quality")
    if not re.search(r"(?is)\|\s*iPhone\s*\|[^\n]+\|\s*Speed \(4-bit\)\s*\|", readme):
        errors.append("README.md: iPhone model availability must state Speed only")
    if not re.search(r"(?i)Voice Cloning follows the reference voice", readme):
        # Since the emotion-reference banks (DP-16), clone personas DO offer a
        # delivery choice, but it selects a verified reference clip; the
        # instruction channel stays scoped away and the copy must attribute
        # clone delivery to the reference, never to an instruction control.
        errors.append(
            "README.md: clone delivery must be attributed to the reference voice"
        )
    local_assets = set(re.findall(r"\]\((docs/(?:screenshots/[^)]+|readme_banner_vocello\.png))\)", readme))
    if len(local_assets) < 5:
        errors.append("README.md: expected repository-versioned banner and product screenshots are missing")
    for asset in local_assets:
        if not (root / asset).is_file():
            errors.append(f"README.md: missing repository-versioned product asset {asset}")
    return errors


def _script_help(root: Path, script: str) -> str:
    result = subprocess.run([str(root / script), "--help"], cwd=root, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=10, check=False)
    return result.stdout


def validate_documented_subcommands(root: Path, paths: list[Path]) -> list[str]:
    errors: list[str] = []
    help_text = {script: _script_help(root, script) for script in SCRIPT_HELP_SURFACES if (root / script).is_file()}
    # Same-line whitespace only: a command and its subcommand never span a
    # line break, and letting them join lines false-matched a frontmatter
    # `sourceOfTruth: scripts/ui_test.sh` entry with the closing `---` fence.
    command = re.compile(r"(?:^|\s)(?:\./)?(?P<script>scripts/[A-Za-z0-9_-]+\.sh)[^\S\n]+(?P<sub>[A-Za-z0-9_-]+)")
    for source in paths:
        for match in command.finditer(source.read_text(encoding="utf-8")):
            script, subcommand = match.group("script"), match.group("sub")
            if script in help_text and subcommand not in help_text[script]:
                errors.append(f"{source.relative_to(root)}: undocumented or retired subcommand {script} {subcommand}")
    return errors


def validate_website_copy(root: Path) -> list[str]:
    errors: list[str] = []
    source_root = root / "website/src"
    for path in sorted(source_root.rglob("*")):
        if not path.is_file() or path.suffix not in {".js", ".jsx", ".json"}:
            continue
        text = path.read_text(encoding="utf-8")
        if "—" in text:
            errors.append(f"{path.relative_to(root)}: visible website source contains a prohibited em dash")
        if re.search(r"(?i)faster than real[ -]?time", text):
            errors.append(f"{path.relative_to(root)}: public copy makes a universal faster-than-realtime claim")
    return errors


def render_index(root: Path) -> str:
    lines = [
        "# Documentation index",
        "",
        "> Generated by `python3 scripts/documentation_contract.py rebuild-index`. Do not edit manually.",
        "",
        "Code, machine-readable contracts, and repository scripts remain higher authority than prose.",
        "",
    ]
    groups = documentation_groups(root)
    historical = set().union(*(
        _expand_group(root, group["paths"]) for group in groups if group["status"] == "historical"
    ))
    for group in groups:
        lines.extend([f"## {group['title']}", "", f"Status: **{group['status']}** · Owner: **{group['owner']}** · Audience: {group['audience']}.", "", f"Authority: {group['authority']}.", "", "Review when: " + "; ".join(group["reviewTriggers"]) + ".", ""])
        group_paths = _expand_group(root, group["paths"])
        if group["status"] == "active":
            group_paths -= historical
        for path in sorted(group_paths):
            if path == root / load_json(root / CONTRACT_PATH)["indexPath"]:
                continue
            relative = path.relative_to(root)
            link = Path("..") / relative
            lines.append(f"- [`{relative.as_posix()}`]({link.as_posix()})")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def validate_index(root: Path) -> list[str]:
    index = root / load_json(root / CONTRACT_PATH)["indexPath"]
    expected = render_index(root)
    if not index.is_file():
        return [f"{index.relative_to(root)}: generated documentation index is missing"]
    if index.read_text(encoding="utf-8") != expected:
        return [f"{index.relative_to(root)}: generated documentation index is stale"]
    return []


def validate_historical_banners(root: Path) -> list[str]:
    errors: list[str] = []
    for path in historical_markdown_paths(root):
        if "audits/archive" not in path.as_posix() and path.name != "backend-optimization-research-report.md":
            continue
        opening = "\n".join(path.read_text(encoding="utf-8").splitlines()[:12])
        if "Historical snapshot" not in opening and "Historical resolution" not in opening:
            errors.append(f"{path.relative_to(root)}: missing opening historical-snapshot notice")
    return errors


def validate(root: Path) -> list[str]:
    paths = active_markdown_paths(root)
    errors: list[str] = []
    errors.extend(validate_relative_links(root, paths))
    errors.extend(validate_script_references(root, paths))
    errors.extend(validate_repository_paths(root, paths))
    errors.extend(validate_build_references(root, paths))
    errors.extend(validate_optional_capabilities(root, paths))
    errors.extend(validate_current_runtime_guidance(root, paths))
    errors.extend(validate_documented_subcommands(root, paths))
    errors.extend(validate_facts(root))
    errors.extend(validate_readme_public_contract(root))
    errors.extend(validate_website_copy(root))
    errors.extend(validate_historical_banners(root))
    errors.extend(validate_index(root))
    for source in paths:
        if re.search(r"--ledger(?:-row)?\b", source.read_text(encoding="utf-8")):
            errors.append(f"{source.relative_to(root)}: retired manual benchmark-ledger option returned")
    return sorted(set(errors))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", type=Path, default=Path(__file__).resolve().parents[1], help=argparse.SUPPRESS)
    subparsers = parser.add_subparsers(dest="command")
    subparsers.add_parser("validate")
    rebuild = subparsers.add_parser("rebuild-index")
    rebuild.add_argument("--check", action="store_true")
    arguments = parser.parse_args(argv)
    root = arguments.repo_root.resolve()
    if arguments.command == "rebuild-index":
        errors = validate_index(root)
        if arguments.check:
            if errors:
                print("\n".join(errors), file=sys.stderr)
                return 1
            print("Documentation index: PASS")
            return 0
        target = root / load_json(root / CONTRACT_PATH)["indexPath"]
        target.write_text(render_index(root), encoding="utf-8")
        print(f"Rebuilt {target.relative_to(root)}")
        return 0
    errors = validate(root)
    if errors:
        print("\n".join(errors), file=sys.stderr)
        return 1
    print("Documentation contract: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
