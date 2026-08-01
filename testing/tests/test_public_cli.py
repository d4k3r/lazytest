import importlib.util
import subprocess
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = ROOT / "testing" / "scripts"


def load_script(name: str):
    path = SCRIPTS / name
    spec = importlib.util.spec_from_file_location(name.replace(".", "_"), path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


class PublicCliContractTests(unittest.TestCase):
    def test_help_is_offline_and_side_effect_free(self):
        scripts = [
            "generate_tests_qwen_3.5_fixed_mut.py",
            "generate_baseline.py",
            "recalc_branch_coverage.py",
            "mutation_score.py",
        ]
        before = set(ROOT.iterdir())
        for script in scripts:
            result = subprocess.run(
                [sys.executable, str(SCRIPTS / script), "--help"],
                cwd=ROOT,
                capture_output=True,
                text=True,
                timeout=15,
                check=False,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("usage:", result.stdout.lower())
        self.assertEqual(set(ROOT.iterdir()), before)

    def test_generator_defaults_preserve_five_attempts_without_normalisation(self):
        generator = load_script("generate_tests_qwen_3.5_fixed_mut.py")
        args = generator.parse_args([])
        self.assertEqual(args.attempts, 5)
        self.assertFalse(args.normalise_packages)
        self.assertIsNone(generator.client)

    def test_baseline_defaults_preserve_five_attempts(self):
        baseline = load_script("generate_baseline.py")
        args = baseline.parse_args([])
        self.assertEqual(args.attempts, 5)
        self.assertIsNone(baseline.client)

    def test_coverage_path_normalisation_and_strict_default(self):
        coverage = load_script("recalc_branch_coverage.py")
        args = coverage.parse_args([])
        self.assertTrue(args.strict_coverage)
        self.assertEqual(
            coverage.get_repo_relative_path(
                "/private/checkout/TheAlgorithms/boolean_algebra/not_gate.py"
            ).replace("\\", "/"),
            "boolean_algebra/not_gate.py",
        )


if __name__ == "__main__":
    unittest.main()
