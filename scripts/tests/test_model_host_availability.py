from __future__ import annotations

import importlib.util
import json
import shutil
import sys
import tempfile
import unittest
from email.message import Message
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location(
    "model_host_availability", ROOT / "scripts/model_host_availability.py"
)
assert SPEC and SPEC.loader
module = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = module
SPEC.loader.exec_module(module)


class Response:
    def __init__(self, *, total: int, host: str = "cas-bridge.xethub.hf.co", status: int = 206, body: bytes = b"x"):
        self.status = status
        self._body = body
        self._url = f"https://{host}/artifact"
        self.headers = Message()
        self.headers["Content-Range"] = f"bytes 0-0/{total}"

    def __enter__(self) -> "Response":
        return self

    def __exit__(self, *_arguments: object) -> None:
        return None

    def getcode(self) -> int:
        return self.status

    def geturl(self) -> str:
        return self._url

    def read(self, _size: int) -> bytes:
        return self._body


class ModelHostAvailabilityTests(unittest.TestCase):
    def test_live_contract_selects_one_pinned_artifact_per_ios_model(self) -> None:
        rows = module.validate()
        self.assertEqual({row["modelID"] for row in rows}, {"pro_custom", "pro_design", "pro_clone"})
        self.assertTrue(all("url" in row for row in rows))
        self.assertTrue(all(row["expectedBytes"] > 1_000_000_000 for row in rows))

    def test_probe_is_anonymous_minimal_and_redacted(self) -> None:
        expected = {row["modelID"]: row["expectedBytes"] for row in module.validate()}
        requests: list[object] = []

        def opener(request: object, timeout: int) -> Response:
            requests.append(request)
            self.assertLessEqual(timeout, 60)
            model = next(row for row in module.validate() if row["url"] == request.full_url)
            self.assertEqual(request.headers["Range"], "bytes=0-0")
            return Response(total=expected[model["modelID"]])

        result = module.probe(region="north-america-east", opener=opener)
        self.assertEqual(result["status"], "PASS")
        self.assertEqual(len(requests), 3)
        encoded = json.dumps(result)
        self.assertNotIn("huggingface", encoded)
        self.assertNotIn("PowerBeef", encoded)
        self.assertNotIn("https://", encoded)

    def test_wrong_size_range_and_redirect_fail_closed(self) -> None:
        with self.assertRaisesRegex(module.AvailabilityError, "byte total"):
            module.probe(region="europe-west", opener=lambda _request, _timeout: Response(total=7))
        with self.assertRaisesRegex(module.AvailabilityError, "byte range"):
            module.probe(
                region="europe-west",
                opener=lambda _request, _timeout: Response(total=7, status=200),
            )
        with self.assertRaisesRegex(module.AvailabilityError, "allowlist"):
            first = module.validate()[0]
            module.probe(
                region="europe-west",
                opener=lambda _request, _timeout: Response(
                    total=first["expectedBytes"], host="untrusted.invalid"
                ),
            )

    def test_unpinned_credentialed_and_total_drift_catalogs_fail(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "config").mkdir()
            (root / "Sources/Resources").mkdir(parents=True)
            shutil.copy2(ROOT / "config/model-host-availability-policy.json", root / "config")
            catalog_path = root / "Sources/Resources/qwenvoice_ios_model_catalog.json"
            catalog = json.loads((ROOT / catalog_path.relative_to(root)).read_text())
            catalog["models"][0]["baseURL"] = "https://token@huggingface.co/repo/resolve/main"
            catalog_path.write_text(json.dumps(catalog))
            with self.assertRaisesRegex(module.AvailabilityError, "credential-free"):
                module.validate(root)
            catalog = json.loads((ROOT / catalog_path.relative_to(root)).read_text())
            catalog["models"][0]["totalBytes"] += 1
            catalog_path.write_text(json.dumps(catalog))
            with self.assertRaisesRegex(module.AvailabilityError, "totalBytes"):
                module.validate(root)


if __name__ == "__main__":
    unittest.main()
