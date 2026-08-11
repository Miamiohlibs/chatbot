#!/usr/bin/env bash
#
# Point git at the tracked hooks. Run once per clone.
#
#     bash scripts/setup_hooks.sh
#
# Why this is not automatic: git will not run a hook the repo installs by
# itself, and that is the correct behaviour -- cloning a repo must not
# execute its code. So it takes one deliberate command per machine.

set -euo pipefail
cd "$(git rev-parse --show-toplevel)"

git config core.hooksPath scripts/hooks
chmod +x scripts/hooks/*

echo "hooks enabled: $(git config core.hooksPath)"
echo
echo "Checking it actually runs..."
if bash scripts/hooks/pre-commit >/dev/null 2>&1; then
    echo "  the pre-commit scan runs and passes on your current index."
else
    echo "  the pre-commit scan runs and currently reports findings --"
    echo "  run 'python3 scripts/scan_for_pii.py --staged' to see them."
fi
echo
echo "To see what is already in the repo (reports, never blocks):"
echo "  python3 scripts/scan_for_pii.py --all"
