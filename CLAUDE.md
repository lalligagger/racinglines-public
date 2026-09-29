# Working with Claude Code on racinglines

This is the standing project note for Claude Code sessions on this repo. It sets the dev cycle, model/thread
allocation, command-formatting, merge, and reporting conventions. Read this first in every new session.
For the domain itself (phases, decisions, what's built), read [docs/todo.md](docs/todo.md) and
[docs/f1-roadmap.md](docs/f1-roadmap.md) next — this file is process, those are substance.

## Environments (always label commands with one of these)

| Label | Where | Notes |
|---|---|---|
| **LOCAL (Mac)** | This machine, `.venv` | Dev, tests, the demo maker/taker, `mkdocs serve` |
| **VM (production)** | `racinglines-vm`, via `scripts/deploy/vm.sh` | `racinglines.bet`. Never edited directly — only `vm.sh deploy` |
| **CLOUD (sweep)** | An ephemeral cloud session | Long searches (`f1 search`); no Kalshi network access; see [docs/cloud-sweep.md](docs/cloud-sweep.md) |

Every command block in a reply must be labeled with one of these, in the order they should run, one block per
step (not one giant script), so they can be run and checked one at a time.

## Model / thread allocation

**Goal:** maximize throughput on the Claude Code budget; spend the separate Fable budget on the highest-complexity
work only, but don't let it sit unused if genuinely high-complexity work exists this session.

| Tier | Use for | Model |
|---|---|---|
| **High** | Model/pricing methodology changes, anything touching settlement rules, order signing, or trading flags, cross-cutting refactors touching 4+ modules, ambiguous roadmap items needing a judgment call, the final review pass before a merge batch | `Fable` (pass as the literal model name) |
| **Medium** | A roadmap item that follows an existing pattern (a new sweep setting, a new venue path, a CLI subcommand, tests for either) | Sonnet-class |
| **Low** | Mechanical work: doc sync, rote test scaffolding, formatting, dependency bumps, git housekeeping | Haiku-class |

At the start of a session, state which tier each queued task falls into and why, before assigning models. If a
session has no genuinely high-complexity task, say so explicitly rather than routing something to Fable to use
the budget — but check hard before concluding that, since "no high-complexity work" is the failure mode we're
avoiding here.

## Dev cycle

1. **Plan.** Restate the ask, resolve ambiguity, no code yet. Check `docs/todo.md` for whether this is already a
   tracked item (U-numbers, P0/P1/P2) and cite it.
2. **Develop roadmap.** Break the plan into ordered tasks. For each: complexity tier, files/modules touched, and
   its test/doc obligations (`docs/f1-roadmap.md` "ground rules": golden
   tests, leakage-rule tests for new pricing/trading paths, `tests/test_no_data_in_git.py`).
3. **Implementation.** Only after the roadmap is confirmed (or the task is trivial and low-risk).
4. **Run one thread per task**, one task at a time, model per the tier table, on its own branch off `main`.
5. **Report back**, every check-in:
   - status per task (done / blocked / needs a decision),
   - open questions, especially anything the roadmap calls an "owner decision" (`docs/todo.md#owner-decisions`),
   - a sequenced git command block to merge, in the order that avoids conflicts (one branch per task), e.g.:

```
# LOCAL (Mac) — merge sequence, run in order
git checkout main && git pull
git merge --no-ff work/<task-1>          # ⚠️ touches settlement rules — read the diff first
git merge --no-ff work/<task-2>          # a later task's branch, if it is ready in the same batch
python -m pytest -m "not live"
git push
```

   Mark any merge touching money-adjacent code (settlement, order signing, trading flags, live-event units,
   VM systemd units, DB migrations) with **⚠️ needs special attention** and say why, right in the command block's
   comment, not just in prose above it.

**Before any merge is proposed, not after:**

```
# LOCAL (Mac)
racinglines check
python -m pytest -m "not live"
mkdocs build --strict
```

Run the full suite too when the local database is up. `UPDATE_GOLDEN=1` only in a deliberate promotion change,
per the [F1 roadmap](docs/f1-roadmap.md#5-promotion-rule-when-a-challenger-becomes-the-default), with a decision
log entry in the same change.

**Live-event freeze.** No thread should touch VM deploy paths while a live event's systemd unit
is active there (`vm.sh deploy` already refuses this — don't override it with `--force` as a way around a merge
conflict).

## Report generation

**Already built, for live events:**

```
# LOCAL (Mac) or VM
racinglines live report <spec> --pdf
```

Produces `reports/<event>/report.md` (+ `img/` for charts) → `report.html` (`racinglines/reporting/markdown_html.py`)
→ `report.pdf` (weasyprint or a headless browser). Use this as-is for any completed live event.

**Not yet built, for other large updates** (a finished roadmap milestone, a sizing review, a season close): no
generic pipeline exists today — these have been ad hoc so far. Reuse the same `markdown_html.render` step: write
the report as Markdown with images saved under an `img/` folder next to it (plots, screenshots, tables as
Markdown tables), then render HTML → PDF the same way `live report` does. Whether this becomes a real
`racinglines report build <folder>` command or stays a per-report script is an open question for the first time
we need one — raise it then rather than guessing now.

**Quality bar, until then:** match the two existing reports, not a generic template.

- [reports/2026-09-27-whistler-live/report.md](reports/2026-09-27-whistler-live/report.md) (the Whistler live
  event): a one-paragraph scene-setter, a top-line summary table, a section per phase of the event, a timeline
  table with bolded turning points, winners/losers tables with real numbers (not rounded categories), and a
  named "what this does and doesn't show" caveat section. Every claim carries its number.
- `data/runs/search/<name>/REPORT.md` (a cloud sweep, spec in
  [docs/cloud-sweep.md](docs/cloud-sweep.md#agent-protocol) step 6): what ran, the leaderboard, the best combo
  for what's ahead, what held in both the primary and held-out windows and what didn't (labelled
  robust / 2026-specific / not better), every queue change with its reason, the candidates, and what to run
  next.

Both share: numbers over adjectives, every tuned or chosen setting named explicitly, and a closing section that
says what's next or what wasn't shown — never just a leaderboard or a wall of metrics with no verdict.

## Handoff to Copilot ("troubleshoot in Copilot")

When I say this, produce one dated Markdown file I can paste into VS Code Copilot, containing:

- **What's broken** — one paragraph.
- **Environment** — LOCAL / VM / CLOUD, branch, last commit.
- **What's been tried** — commands run and their result (trimmed, not full logs).
- **Relevant files** — as a list, so Copilot can jump straight there.
- **The exact question** — what you need Copilot's tools (terminal, editor diagnostics, browser) for that Claude
  Code's own tools couldn't resolve.

Default location: `reports/handoffs/<date>-<slug>.md`, **local only** (gitignored) — never commit or push these.

## Safety rails (non-negotiable, carried over from the project's own rules)

- Never flip `POLYMARKET_TRADING_ENABLED` / `KALSHI_TRADING_ENABLED`, run `vm.sh public on`, or run a DB migration
  against the VM without my explicit sign-off in the same conversation turn.
- Never `git push --force` or rewrite published history.
- Every tuned setting (spread, filter, model choice) needs a decision-log entry before it's treated as final —
  match the existing `docs/f1-roadmap.md` decision log format.
