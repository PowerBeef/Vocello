import tempfile
import unittest
from pathlib import Path

from scripts import python_test_contract


class PythonTestContractTests(unittest.TestCase):
    def _root(self) -> tuple[tempfile.TemporaryDirectory, Path]:
        temporary = tempfile.TemporaryDirectory()
        root = Path(temporary.name)
        (root / "scripts/tests").mkdir(parents=True)
        return temporary, root

    def test_accepts_unittest_and_function_adapter_modules(self):
        temporary, root = self._root()
        self.addCleanup(temporary.cleanup)
        (root / "scripts/test_unit.py").write_text(
            "import unittest\n"
            "class UnitTests(unittest.TestCase):\n"
            "    def test_value(self):\n"
            "        self.assertEqual(1, 1)\n",
            encoding="utf-8",
        )
        (root / "scripts/tests/test_function.py").write_text(
            "def test_value():\n"
            "    assert True\n"
            "def load_tests(loader, tests, pattern):\n"
            "    return tests\n",
            encoding="utf-8",
        )

        inventory = python_test_contract.validate(root)

        self.assertEqual(2, len(inventory))
        self.assertEqual(2, sum(item.declared_tests for item in inventory))

    def test_rejects_unexpected_zero_test_module(self):
        temporary, root = self._root()
        self.addCleanup(temporary.cleanup)
        (root / "scripts/tests/test_empty.py").write_text("VALUE = 1\n", encoding="utf-8")

        with self.assertRaisesRegex(ValueError, "unexpected zero-test module"):
            python_test_contract.validate(root)

    def test_rejects_function_tests_without_unittest_adapter(self):
        temporary, root = self._root()
        self.addCleanup(temporary.cleanup)
        (root / "scripts/tests/test_pytest_only.py").write_text(
            "def test_value():\n"
            "    assert True\n",
            encoding="utf-8",
        )

        with self.assertRaisesRegex(ValueError, "invisible to unittest discovery"):
            python_test_contract.validate(root)

    def test_new_module_is_inventoried_without_a_curated_list(self):
        temporary, root = self._root()
        self.addCleanup(temporary.cleanup)
        first = root / "scripts/tests/test_first.py"
        first.write_text(
            "import unittest\n"
            "class FirstTests(unittest.TestCase):\n"
            "    def test_first(self):\n"
            "        self.assertTrue(True)\n",
            encoding="utf-8",
        )
        self.assertEqual(1, len(python_test_contract.validate(root)))

        (root / "scripts/tests/test_unlisted.py").write_text(
            "import unittest\n"
            "class NewlyAddedTests(unittest.TestCase):\n"
            "    def test_new(self):\n"
            "        self.assertTrue(True)\n",
            encoding="utf-8",
        )

        inventory = python_test_contract.validate(root)
        self.assertEqual(
            ["test_first.py", "test_unlisted.py"],
            [item.path.name for item in inventory],
        )


if __name__ == "__main__":
    unittest.main()
