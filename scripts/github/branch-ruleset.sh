#!/usr/bin/env bash
# Create (or update) a GitHub ruleset protecting main, via the Rulesets API (not the legacy
# branch-protection endpoint used by branch-protection.sh). See:
#   https://docs.github.com/en/repositories/configuring-branches-and-merges-in-your-repository/managing-rulesets/about-rulesets
#
#   bash scripts/github/branch-ruleset.sh [owner/repo]
#
# No PR review requirement (solo maintainer): required status checks only, no force-pushes, no
# deletion, linear history. Repository admins (the owner) bypass the ruleset entirely, so this
# never blocks a solo merge or an emergency push.
set -euo pipefail

REPO="${1:-$(gh repo view --json nameWithOwner -q .nameWithOwner)}"

if ! command -v gh >/dev/null 2>&1; then
  echo "gh CLI is required. Install it and run: gh auth login" >&2
  exit 1
fi

if ! gh auth status >/dev/null 2>&1; then
  echo "GitHub CLI is not authenticated. Run: gh auth login" >&2
  exit 1
fi

echo "Creating ruleset for ${REPO} on main ..."

payload=$(cat <<'JSON'
{
  "name": "main",
  "target": "branch",
  "enforcement": "active",
  "bypass_actors": [
    { "actor_id": 5, "actor_type": "RepositoryRole", "bypass_mode": "always" }
  ],
  "conditions": {
    "ref_name": { "include": ["refs/heads/main"], "exclude": [] }
  },
  "rules": [
    { "type": "deletion" },
    { "type": "non_fast_forward" },
    { "type": "required_linear_history" },
    {
      "type": "required_status_checks",
      "parameters": {
        "strict_required_status_checks_policy": true,
        "required_status_checks": [
          { "context": "predeploy-staging" },
          { "context": "pytest (not live)" }
        ]
      }
    }
  ]
}
JSON
)

echo "$payload" | gh api \
  --method POST \
  -H "Accept: application/vnd.github+json" \
  "/repos/${REPO}/rulesets" \
  --input -

echo "Ruleset created for ${REPO} on main. Required checks: predeploy-staging, pytest (not live)"
