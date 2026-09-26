---
status: active
owner: release-qa
reviewed: 2026-09-22
summary: Set up a new Mac from a fresh clone — Xcode and its components, the pinned CLI tools, Python and website toolchains, Git, signing and permissions, models, and the Claude Code tooling — then verify with the repository's own checks.
sourceOfTruth:
  - config/toolchain.json
  - scripts/install_pinned_tools.sh
  - scripts/lib/ios_platform_preflight.py
  - scripts/supply_chain_contract.py
---
# Development setup on a new Mac

A fresh clone contains the whole project: source, the tracked Xcode project and schemes, contracts,
scripts, CI, `CLAUDE.md` and the Claude Code configuration. What it cannot contain is the machine:
Xcode and its downloadable components, command-line tools, Python and Node toolchains, credentials,
signing identities, privacy grants, downloaded models and caches. This guide sets those up in order.
Versions are never repeated here; `config/toolchain.json` is the pin authority and the commands below
read it.

```sh
git clone https://github.com/PowerBeef/Vocello.git
cd Vocello
```

## 1. Xcode and its components

- An Apple Silicon Mac on macOS 26 or newer with **full Xcode**; the Command Line Tools alone cannot
  build any product. CI pins the version in `config/toolchain.json` (`native.xcode`). A newer local
  Xcode (27) builds the project, but it accepts some code the pinned CI Xcode rejects, so push CI stays
  the judge; the toolchain move is roadmap item CONV-21.
- Select it and finish its first launch:

  ```sh
  sudo xcode-select -s /Applications/Xcode.app/Contents/Developer
  xcodebuild -runFirstLaunch
  ```

- MLX compiles Metal shaders. Xcode 27 ships the Metal toolchain as a separate one-time download:
  `xcodebuild -downloadComponent MetalToolchain`.
- The phone-free iOS compile (`scripts/dev.sh ios`) needs the iOS platform component:
  `xcodebuild -downloadPlatform iOS -architectureVariant arm64`, then
  `python3 scripts/lib/ios_platform_preflight.py check`. The repository never downloads it for you
  and never uses it to run a Simulator.

## 2. Command-line tools (Homebrew plus the pinned installer)

Homebrew supplies the general tools; the four tools whose exact version matters to the build come
from the repository's SHA-pinned installer instead:

```sh
brew install gh python node@24
./scripts/install_pinned_tools.sh
./scripts/install_pinned_tools.sh swiftlint   # optional: the advisory local lint
cat >> ~/.zprofile <<'EOF'
export PATH="$HOME/.qwenvoice-pinned-tools/bin:/opt/homebrew/opt/node@24/bin:$PATH"
EOF
exec zsh -l        # reload PATH, then check: which xcodegen rg python3 node
gh auth login
```

`./scripts/install_pinned_tools.sh` downloads xcodegen, ripgrep, xcbeautify and shellcheck from the
release artifacts pinned in `config/toolchain.json`, verifies each SHA-256 and installs them into
`~/.qwenvoice-pinned-tools/bin`; CI runs the same script, and naming other pinned tools (such as `gh`)
installs those instead. Keep that directory first on `PATH` so a Homebrew copy never shadows it:
xcodegen's version decides the bytes of the generated Xcode project. xcodegen is needed on the very
first build even if you never edit `project.yml`, because the build scripts regenerate the project
whenever their generation stamp under `build/` is missing; `rg` is required by
`scripts/repo_invariants.sh` and the contract gate. `node@24` is keg-only, hence its `PATH` entry.
SwiftLint is optional and pinned the same way (`artifactPins.swiftlint`, installed only when named):
`scripts/dev.sh lint` runs its advisory rules, and reports when it is missing or is not the pinned
version. `gh` is the CI and release interface (`gh run watch`).

## 3. Python

The tooling needs Python 3.11 or newer as `python3`, ahead of Apple's `/usr/bin/python3` on `PATH`;
Homebrew's `python` provides it (`which python3` should print `/opt/homebrew/bin/python3`). The test
suite also needs numpy, pytest and pytest-xdist at the pinned versions; this reads them from the
manifest exactly as CI does:

```sh
python3 -m pip install --user --break-system-packages $(python3 -c 'import json; n = json.load(open("config/toolchain.json"))["native"]; print(" ".join(k + "==" + n[k]["version"] for k in ("numpy", "pytest", "pytest-xdist")))')
```

Homebrew marks its Python as externally managed; `--user` installs the pins into your user
site-packages without touching Homebrew's files (CI passes the same flag). The scripts always run
`python3 -m pytest`, so the user `bin` directory does not need to be on `PATH`. After a Homebrew Python
upgrade to a new minor version, run the command again. The research-only `.venv` for advisory
speaker-identity scoring is optional and never part of the ordinary loop; see
[`delivery-harness.md`](delivery-harness.md) and [`emotion-reference-banks.md`](emotion-reference-banks.md).

## 4. Website

```sh
npm --prefix website ci
npx --prefix website playwright install chromium
npm --prefix website run check
```

Node and npm pin only their major version (`config/toolchain.json` `website.node` 24, `website.npm`
11): CI's `setup-node` takes the latest 24.x with its bundled npm, and Homebrew's `node@24` follows the
same line, so `scripts/dev.sh ci` and `supply_chain_contract.py --installed website` pass on it. The
dependencies themselves stay exact through `website/package-lock.json`. Vercel deploys through its Git
integration; `vercel link --repo` is needed only to use the Vercel CLI.

## 5. Git

Set a global identity (`git config --global user.name …` and `user.email …`) and do not add a
repository-local override. HTTPS credentials come from `gh auth login` or the macOS keychain. There
are no Git hooks, submodules or LFS files; the guards are Claude Code hooks. Release tags must be
signed and GitHub-verified (`git tag -s`), so configure a signing key only if you cut releases
([`macos-release-qa.md`](macos-release-qa.md)).

## 6. First run

```sh
scripts/dev.sh status
python3 scripts/supply_chain_contract.py --installed native     # a newer local Xcode shows as drift; expected
python3 scripts/supply_chain_contract.py --installed website    # any Node 24.x / npm 11.x passes
scripts/dev.sh check                                            # first run: regenerate, resolve packages, cold build
scripts/dev.sh build && scripts/dev.sh run
```

The first `check` resolves the Swift packages over the network and compiles everything cold, which
takes a while; later runs reuse the owned caches under `build/` ([`config/build-output-policy.json`](../../config/build-output-policy.json)).
Never copy `build/` from another machine; rebuild it.

## 7. Signing, permissions, models and devices

- **Signing.** Local macOS builds sign with the first Apple Development identity in the keychain and
  fall back to ad-hoc with a warning (ad-hoc grants for microphone and speech reset on every rebuild).
  Sign in under Xcode → Settings → Accounts, or import the old Mac's certificate together with its
  private key. Release signing lives only in CI secrets.
- **Permissions.** Run `scripts/permissions_doctor.sh` and follow
  [`macos-permissions.md`](macos-permissions.md): the UI-test runner's System Audio Recording and
  Accessibility grants are added by hand in System Settings, and reading the privacy database needs
  Full Disk Access for the terminal. macOS UI lanes also need Automation Mode without a password
  prompt: run `sudo automationmodetool enable-automationmode-without-authentication` once, and keep
  the session unlocked while a lane runs.
- **Models.** The apps download the production catalog on first use into
  `~/Library/Application Support/QwenVoice`. Test fixtures come from `scripts/macos_test.sh models
  ensure` on explicit request; copying that folder from the old Mac also works.
- **iPhone.** Device lanes need an Apple Development identity with its key, an iPhone paired with and
  trusting this Mac, and Developer Mode enabled on the phone ([`ios-device-testing.md`](ios-device-testing.md)).
  Pair once over USB; afterwards CoreDevice reaches the unlocked phone over the local network
  (`scripts/ios_device.sh device-state`). With the Apple ID signed in under Xcode → Settings →
  Accounts, the first `scripts/ios_device.sh build` creates the team development provisioning profile.

## 8. Claude Code

Install Claude Code, open the clone and trust the folder. The tracked `CLAUDE.md`, `.claude/rules/`,
`.claude/skills/`, `.claude/agents/` and `.claude/settings.json` (hooks and permissions) load from the
clone; confirm with `/memory`, `/hooks`, `/permissions` and the `/` skill menu, as the
[development workflow](development-workflow.md#claude-code-setup-and-tool-routing) describes.
Personal overrides go in the ignored `.claude/settings.local.json`.

Optional user-scope assistance used by this workflow (none is required, and CI never depends on it):

```sh
claude plugin marketplace add CharlesWiltgen/Axiom
claude plugin install axiom@axiom-marketplace
claude plugin marketplace add pbakaus/impeccable
claude plugin install impeccable@impeccable
for p in swift-lsp pyright-lsp chrome-devtools-mcp huggingface-skills vercel claude-md-management; do
  claude plugin install "$p@claude-plugins-official"
done

claude mcp add -s user XcodeBuildMCP -- npx -y xcodebuildmcp@latest mcp
claude mcp add -s user --transport http context7 https://mcp.context7.com/mcp
claude mcp add -s user --transport http sosumi https://sosumi.ai/mcp

brew install asccli   # tddworks asc CLI behind the asc-* App Store Connect skills
```

XcodeBuildMCP runs through `npx` (Node from section 2) and reads its workflows and the
`macos`/`ios-device` profiles from the tracked `.xcodebuildmcp/config.yaml`; do not enable its
Simulator workflow (the project settings deny its Simulator tools). The GitHub connector comes from
the claude.ai account and needs no personal token; `gh` covers the same workflow. Claude in Chrome is
the Chrome extension; use it for the website and, on explicit request, portal chores. The asc-*
skills drive the tddworks `asc`; the repository itself pins no App Store Connect CLI.

swift-lsp resolves symbols through a `buildServer.json` at the repository root. It is ignored because
it holds machine paths; create it after the first build:

```sh
brew install xcode-build-server
xcode-build-server config -project QwenVoice.xcodeproj -scheme QwenVoice --build_root "$PWD/build/cache/xcode/macos"
```

## Troubleshooting

- A build that fails on missing Xcode stat caches right after a disk cleanup means `build/cache` was
  deleted: rebuild with `scripts/dev.sh ci` or the individual lanes. The LSP stays broken until the
  `build/cache/xcode/macos` arena is rebuilt.
- `xcodegen` not found: the pinned tools directory is not on `PATH` (section 2).
- The iOS compile refuses to start: the iOS platform component is missing or does not match the
  selected Xcode (section 1).
