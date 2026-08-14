import subprocess
import unittest

from tests.support.paths import project_path


class NativePresentationPlannerTests(unittest.TestCase):
    def test_pure_swift_presentation_contracts(self):
        result = subprocess.run(
            ["swift", "run", "PlannerTests"],
            cwd=project_path("native_notch"),
            check=True,
            capture_output=True,
            text=True,
        )
        self.assertIn("SubtitlePresentationPlanner tests passed", result.stdout)


if __name__ == "__main__":
    unittest.main()
