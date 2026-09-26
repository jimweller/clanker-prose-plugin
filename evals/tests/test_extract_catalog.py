import pathlib
import subprocess
import unittest

SUITE = pathlib.Path(__file__).resolve().parent.parent


class ExtractCatalogTest(unittest.TestCase):
    def test_catalog_starts_at_the_contract_not_at_an_inline_mention_of_the_tag(self):
        # skills/prose/SKILL.md names `<prose-contract>` inline in its header, so an
        # unanchored match began three lines early and fed the judge the editor's
        # "Output the rewritten text" instruction.
        out = subprocess.run(["python3", str(SUITE / "tools" / "extract-catalog.py")], capture_output=True, text=True, check=True).stdout
        self.assertTrue(out.startswith("## How to Write"), out[:120])
        self.assertNotIn("Output the rewritten text", out)

    def test_ids_are_unchanged(self):
        out = subprocess.run(["python3", str(SUITE / "tools" / "extract-catalog.py"), "--ids"], capture_output=True, text=True, check=True).stdout
        self.assertEqual(len(out.split()), 76)


if __name__ == "__main__":
    unittest.main()
