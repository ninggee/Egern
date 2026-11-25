from pathlib import Path
import tempfile
import unittest

import yaml

from tools.validate_converted_modules import normalize, validate


class ValidateConvertedModulesTests(unittest.TestCase):
    def test_response_actions_become_documented_url_rewrites(self) -> None:
        text = """name: test
rewrites:
  - match: '^https://example.com/old'
    actions:
      - respond:
          status: 302
          headers:
            Location: https://example.com/new
          body: ''
  - match: '^https://example.com/ads'
    actions:
      - respond:
          status: 200
          headers:
            Content-Type: application/json
          body: '{}'
mitm:
  hostnames:
    includes:
      - example.com
"""
        result = yaml.safe_load(normalize(text))
        self.assertNotIn("rewrites", result)
        self.assertEqual(result["url_rewrites"][0]["status_code"], 302)
        self.assertEqual(result["url_rewrites"][1]["location"], "http://reject-dict/")
        self.assertEqual(result["mitm"]["hostnames"]["includes"], ["example.com"])

    def test_custom_response_is_not_approximated(self) -> None:
        text = """name: test
rewrites:
  - match: example
    actions:
      - respond:
          status: 200
          body: custom-data
"""
        with self.assertRaises(ValueError):
            normalize(text)

    def test_incompatible_result_is_removed_from_publishable_artifacts(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            result = directory / "bad-source.yaml"
            result.write_text("name: fallback\ndns: {}\n", encoding="utf-8")
            self.assertEqual(validate(directory, normalize_files=True), 0)
            self.assertFalse(result.exists())

    def test_argument_defaults_are_preserved_with_documented_description(self) -> None:
        result = yaml.safe_load(normalize("""name: test
compat_arguments:
  Mode: fast
compat_arguments_schema:
  Mode:
    description: Speed selection
    options: [fast, slow]
scriptings:
  - generic:
      name: test
      script_url: https://example.com/script.js
"""))
        self.assertEqual(result["compat_arguments"], {"Mode": "fast"})
        self.assertEqual(result["compat_arguments_desc"], "Mode: Speed selection")
        self.assertNotIn("compat_arguments_schema", result)


if __name__ == "__main__":
    unittest.main()
