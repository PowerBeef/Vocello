#!/usr/bin/env python3
"""Public product facts stay truthful: release identity, README and website copy.

`config/public-product-facts.json` declares the stable (published) macOS release and,
while a new version is being prepared, the unpublished candidate. The project version,
the README install link and the website CTA must agree with it, and the public copy
must not make claims the product does not keep.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from lib import jsonio  # noqa: E402

PUBLIC_FACTS = Path("config/public-product-facts.json")


def load_json(path: Path) -> dict:
    return jsonio.load_json(path, error=ValueError, require_object=False)


def validate_release_identity(public: dict, project: str) -> list[str]:
    """Keep published downloads truthful while preparing an explicitly unpublished version."""
    errors: list[str] = []
    stable = public.get("stableMacRelease", {})
    version = stable.get("version")
    if not isinstance(version, str) or not re.fullmatch(r"\d+\.\d+\.\d+", version):
        return ["public-product-facts: invalid stable release version"]
    if stable.get("tag") != f"v{version}":
        errors.append("public-product-facts: stable tag/version mismatch")
    if "candidateRelease" in public:
        candidate = public.get("candidateRelease")
        if not isinstance(candidate, dict) or set(candidate) != {"version", "tag", "distributionStatus"}:
            return errors + ["public-product-facts: invalid candidate release fields"]
        candidate_version = candidate.get("version")
        if not isinstance(candidate_version, str) or not re.fullmatch(r"\d+\.\d+\.\d+", candidate_version):
            return errors + ["public-product-facts: invalid candidate version"]
        if (candidate.get("tag") != f"v{candidate_version}"
                or candidate.get("distributionStatus") != "unpublished"
                or tuple(map(int, candidate_version.split("."))) <= tuple(map(int, version.split(".")))):
            errors.append("public-product-facts: candidate must be unpublished, newer than stable, and tag-matched")
        version = candidate_version
    configured = re.findall(r'^\s*MARKETING_VERSION:\s*"([^"\n]+)"\s*$', project, re.M)
    if configured != [version]:
        errors.append("public-product-facts: project version must exactly match the declared candidate or stable release")
    return errors


def validate_public_guidance(root: Path, public: dict) -> list[str]:
    path = root / "website/PRODUCT.md"
    if not path.is_file():
        return []
    text = path.read_text(encoding="utf-8")
    errors = []
    if "stableMacRelease" not in text or "config/public-product-facts.json" not in text:
        errors.append("website/PRODUCT.md: CTA guidance must reference stableMacRelease, not a hand-maintained version")
    for version in re.findall(r"(?i)primary CTA[^\n]*?Vocello\s+(\d+\.\d+\.\d+)", text):
        if version != public["stableMacRelease"]["version"]:
            errors.append("website/PRODUCT.md: primary CTA contradicts the public stable release")
    return errors


def validate_readme(root: Path, public: dict) -> list[str]:
    """Keep the GitHub landing page aligned with the public product contract."""
    readme_path = root / "README.md"
    if not readme_path.is_file():
        return ["README.md: public product page is missing"]
    readme = readme_path.read_text(encoding="utf-8")
    version = public["stableMacRelease"]["version"]
    tag = public["stableMacRelease"]["tag"]
    direct_dmg = f"https://github.com/PowerBeef/Vocello/releases/download/{tag}/Vocello-macos26.dmg"
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
        errors.append("README.md: clone delivery must be attributed to the reference voice")
    local_assets = set(re.findall(r"\]\((docs/(?:screenshots/[^)]+|readme_banner_vocello\.png))\)", readme))
    if len(local_assets) < 5:
        errors.append("README.md: expected repository-versioned banner and product screenshots are missing")
    for asset in local_assets:
        if not (root / asset).is_file():
            errors.append(f"README.md: missing repository-versioned product asset {asset}")
    return errors


def validate_website_copy(root: Path) -> list[str]:
    errors: list[str] = []
    source_root = root / "website/src"
    if not source_root.is_dir():
        return errors
    for path in sorted(source_root.rglob("*")):
        if not path.is_file() or path.suffix not in {".js", ".jsx", ".json"}:
            continue
        text = path.read_text(encoding="utf-8")
        if "—" in text:
            errors.append(f"{path.relative_to(root)}: visible website source contains a prohibited em dash")
        if re.search(r"(?i)faster than real[ -]?time", text):
            errors.append(f"{path.relative_to(root)}: public copy makes a universal faster-than-realtime claim")
    return errors


def validate(root: Path) -> list[str]:
    public = load_json(root / PUBLIC_FACTS)
    project = (root / "project.yml").read_text(encoding="utf-8") if (root / "project.yml").is_file() else ""
    errors: list[str] = []
    errors.extend(validate_release_identity(public, project))
    errors.extend(validate_public_guidance(root, public))
    errors.extend(validate_readme(root, public))
    errors.extend(validate_website_copy(root))
    return sorted(set(errors))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("command", nargs="?", default="validate", choices=("validate",))
    args = parser.parse_args(argv)
    try:
        errors = validate(args.root.resolve())
    except ValueError as error:
        errors = [str(error)]
    for error in errors:
        print(f"error: {error}", file=sys.stderr)
    if errors:
        return 1
    print("Public facts contract: PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
