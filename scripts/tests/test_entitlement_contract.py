from __future__ import annotations

import importlib.util
import json
import plistlib
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


SCRIPT = Path(__file__).resolve().parents[1] / "entitlement_contract.py"
SPEC = importlib.util.spec_from_file_location("entitlement_contract", SCRIPT)
assert SPEC and SPEC.loader
module = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = module
SPEC.loader.exec_module(module)


class EntitlementContractTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        for relative in (
            "config",
            "Sources/App",
            "Sources/Engine",
            "Packages/VocelloQwen3Core/Sources/Runtime",
            "QwenVoice.xcodeproj/project.xcworkspace/xcshareddata/swiftpm",
            "scripts",
        ):
            (self.root / relative).mkdir(parents=True, exist_ok=True)
        self.app_allowed = {
            "com.apple.security.app-sandbox": False,
            "com.apple.security.cs.allow-unsigned-executable-memory": True,
            "com.apple.security.cs.disable-library-validation": True,
            "com.apple.security.device.audio-input": True,
            "com.apple.security.files.user-selected.read-write": True,
        }
        self.xpc_allowed = {
            "com.apple.security.cs.allow-unsigned-executable-memory": True,
            "com.apple.security.cs.disable-library-validation": True,
        }
        self.write_plist("Sources/QwenVoice.entitlements", self.app_allowed)
        self.write_plist("Sources/QwenVoiceEmbeddedRuntime.entitlements", self.xpc_allowed)
        (self.root / "Sources/App/App.swift").write_text("struct App {}\n")
        (self.root / "Sources/Engine/Engine.swift").write_text("struct Engine {}\n")
        (self.root / "Packages/VocelloQwen3Core/Sources/Runtime/Core.swift").write_text(
            "struct Core {}\n"
        )
        (self.root / "project.yml").write_text(
            """name: Fixture
targets:
  QwenVoice:
    type: application
    platform: macOS
    settings:
      base:
        CODE_SIGN_ENTITLEMENTS: Sources/QwenVoice.entitlements
  QwenVoiceEngineService:
    type: xpc-service
    platform: macOS
    settings:
      base:
        CODE_SIGN_ENTITLEMENTS: Sources/QwenVoiceEmbeddedRuntime.entitlements
  Library:
    type: framework
    platform: macOS
"""
        )
        (self.root / "scripts/release.sh").write_text(
            """while IFS= read -r -d '' xpc_path; do
  run_codesign "$xpc_path" --entitlements "$PROJECT_DIR/Sources/QwenVoiceEmbeddedRuntime.entitlements"
done < <(find "$APP_PATH/Contents/XPCServices" -name '*.xpc')
run_codesign "$APP_PATH" --entitlements "$PROJECT_DIR/Sources/QwenVoice.entitlements"
"""
        )
        (self.root / "scripts/verify_release_bundle.sh").write_text(
            """python3 "$SCRIPT_DIR/entitlement_contract.py" verify-bundle --role macos-app --bundle "$APP_PATH"
python3 "$SCRIPT_DIR/entitlement_contract.py" verify-bundle --role macos-engine-xpc --bundle "$XPC_SERVICE_PATH"
python3 "$SCRIPT_DIR/entitlement_contract.py" verify-bundle --role macos-framework --bundle "$framework_path"
"""
        )
        lock = {
            "version": 3,
            "pins": [
                {"identity": "mlx-swift", "state": {"version": "0.31.6"}},
                {"identity": "mlx-swift-lm", "state": {"version": "3.31.4"}},
            ],
        }
        (self.root / module.LOCK_PATH).write_text(json.dumps(lock))
        self.policy = {
            "schemaVersion": 1,
            "policy": "fixture",
            "targets": [
                {
                    "id": "macos-app",
                    "projectTarget": "QwenVoice",
                    "source": "Sources/QwenVoice.entitlements",
                    "allowed": self.app_allowed,
                },
                {
                    "id": "macos-engine-xpc",
                    "projectTarget": "QwenVoiceEngineService",
                    "source": "Sources/QwenVoiceEmbeddedRuntime.entitlements",
                    "allowed": self.xpc_allowed,
                },
                {"id": "macos-framework", "projectTarget": None, "source": None, "allowed": {}},
            ],
            "forbiddenDynamicLoadingAPIs": [
                "dlopen",
                "NSCreateObjectFileImageFromFile",
                "CFBundleLoadExecutable",
                "NSBundle.load",
            ],
            "scannedSourceRoots": ["Sources", "Packages/VocelloQwen3Core/Sources"],
            "mlxExceptionReview": {
                "reviewedAt": "2026-08-26",
                "reviewedPins": {"mlx-swift": "0.31.6", "mlx-swift-lm": "3.31.4"},
                "exceptionEntitlements": [
                    "com.apple.security.cs.allow-unsigned-executable-memory",
                    "com.apple.security.cs.disable-library-validation",
                ],
                "conclusion": "Retain only for the pinned MLX runtime under the signed trust boundary.",
                "removalCondition": "Remove after a measured MLX and Metal loading proof succeeds without each exception.",
            },
        }
        self.policy_path = self.root / module.POLICY_PATH
        self.policy_path.write_text(json.dumps(self.policy))

    def tearDown(self) -> None:
        self.temp.cleanup()

    def write_plist(self, relative: str, value: dict[str, object]) -> None:
        path = self.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(plistlib.dumps(value, sort_keys=True))

    def test_exact_source_project_release_and_mlx_review_pass(self) -> None:
        self.assertEqual(module.validate(self.root), [])

    def test_added_app_entitlement_fails_closed(self) -> None:
        changed = dict(self.app_allowed)
        changed["com.apple.security.network.server"] = True
        self.write_plist("Sources/QwenVoice.entitlements", changed)
        self.assertTrue(any("differs from the exact" in error for error in module.validate(self.root)))

    def test_xpc_cannot_inherit_the_broader_app_entitlements(self) -> None:
        path = self.root / "project.yml"
        path.write_text(
            path.read_text().replace(
                "CODE_SIGN_ENTITLEMENTS: Sources/QwenVoiceEmbeddedRuntime.entitlements",
                "CODE_SIGN_ENTITLEMENTS: Sources/QwenVoice.entitlements",
            )
        )
        self.assertTrue(any("routing differs" in error for error in module.validate(self.root)))

    def test_release_xpc_signing_must_use_narrow_allowlist(self) -> None:
        path = self.root / "scripts/release.sh"
        path.write_text(
            path.read_text().replace(
                "Sources/QwenVoiceEmbeddedRuntime.entitlements",
                "Sources/QwenVoice.entitlements",
            )
        )
        self.assertTrue(any("XPC signing" in error for error in module.validate(self.root)))

    def test_mlx_pin_change_requires_new_exception_review(self) -> None:
        path = self.root / module.LOCK_PATH
        lock = json.loads(path.read_text())
        lock["pins"][0]["state"]["version"] = "0.32.0"
        path.write_text(json.dumps(lock))
        self.assertTrue(any("review is stale" in error for error in module.validate(self.root)))

    def test_owned_dynamic_loading_api_is_rejected(self) -> None:
        path = self.root / "Sources/Engine/Engine.swift"
        path.write_text("func load() { _ = dlopen(name, 0) }\n")
        self.assertTrue(any("arbitrary executable code" in error for error in module.validate(self.root)))

    def test_loading_api_in_a_comment_is_not_a_false_positive(self) -> None:
        path = self.root / "Sources/Engine/Engine.swift"
        path.write_text("// dlopen(name, 0) is intentionally forbidden\nstruct Engine {}\n")
        self.assertEqual(module.validate(self.root), [])

    def test_signed_bundle_exact_match_passes(self) -> None:
        bundle = self.root / "Vocello.app"
        bundle.mkdir()
        with mock.patch.object(module, "_signed_entitlements", return_value=self.app_allowed):
            module.verify_bundle(self.root, "macos-app", bundle)

    def test_signed_bundle_added_entitlement_is_rejected(self) -> None:
        bundle = self.root / "Vocello.app"
        bundle.mkdir()
        actual = dict(self.app_allowed, **{"com.apple.security.network.server": True})
        with mock.patch.object(module, "_signed_entitlements", return_value=actual):
            with self.assertRaisesRegex(module.EntitlementError, "added"):
                module.verify_bundle(self.root, "macos-app", bundle)


if __name__ == "__main__":
    unittest.main()
