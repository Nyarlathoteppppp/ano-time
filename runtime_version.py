import os
import subprocess


def current_version(project_dir=None):
    project_dir = project_dir or os.path.dirname(os.path.abspath(__file__))
    try:
        result = subprocess.run(
            ["git", "describe", "--always", "--dirty"],
            cwd=project_dir,
            capture_output=True,
            text=True,
            timeout=0.4,
            check=True,
        )
        return result.stdout.strip() or "development"
    except (OSError, subprocess.SubprocessError):
        return "development"
