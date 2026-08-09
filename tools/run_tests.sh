#!/bin/bash
set -euo pipefail

project_root="$(cd "$(dirname "$0")/.." && pwd)"
cd "$project_root"

python_bin="${ANO_TIME_PYTHON:-$project_root/.venv/bin/python}"
QT_QPA_PLATFORM=offscreen "$python_bin" -m unittest discover -s tests -p 'test_*.py'
