#!/bin/bash
set -euo pipefail

cd "$(dirname "$0")"
swift package resolve --package-path native_notch

checkout="native_notch/.build/checkouts/DynamicNotchKit"
patch_file="native_notch/dynamic_notch_kit_clt.patch"
if git -C "$checkout" apply --check "$(pwd)/$patch_file" 2>/dev/null; then
  git -C "$checkout" apply "$(pwd)/$patch_file"
fi

swift build -c release --package-path native_notch
echo "Built native DynamicNotchKit subtitle helper"
