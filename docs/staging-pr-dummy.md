# Staging PR dummy check

This file is a deliberately trivial content change to exercise the feature-branch -> staging -> merge -> production deploy workflow without touching any production behavior.

Use it as a minimal PR body and smoke-test artifact during the staging validation pass.

- branch: track/ops-staging-test
- purpose: validate the deploy pipeline
- expected result: branch deploys on staging, smoke passes, merge lands on main, and production smoke still passes

This file should be removed or replaced once the deploy workflow is proven stable.
