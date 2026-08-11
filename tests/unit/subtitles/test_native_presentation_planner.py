import subprocess
import tempfile
import unittest

from tests.support.paths import project_path


class NativePresentationPlannerTests(unittest.TestCase):
    def test_pure_swift_presentation_contracts(self):
        sources = [
            project_path(
                "native_notch", "Sources", "SubtitlePresentation",
                "SubtitlePresentationPlanner.swift",
            ),
            project_path(
                "native_notch", "Sources", "SubtitlePresentation",
                "NotchPresentation.swift",
            ),
            project_path("native_notch", "PlannerTests", "main.swift"),
        ]
        with tempfile.TemporaryDirectory() as directory:
            executable = f"{directory}/planner-tests"
            subprocess.run(
                ["swiftc", *(str(path) for path in sources), "-o", executable],
                check=True,
                capture_output=True,
                text=True,
            )
            result = subprocess.run(
                [executable], check=True, capture_output=True, text=True
            )
        self.assertIn("SubtitlePresentationPlanner tests passed", result.stdout)


if __name__ == "__main__":
    unittest.main()
