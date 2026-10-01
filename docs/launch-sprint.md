# Launch sprint: Thu 1 Oct to the soft launch, Thu 8 Oct 2026

One page for the week to the soft launch. Times are PDT with UTC in brackets. It narrows the larger
[Fantasy soft launch](fantasy-launch.md) plan to the owner's **minimum viable demo** (owner, 2026-10-01 22:23Z):

1. Exchange prices recorded for every listed event (F1, NASCAR, MotoGP on Polymarket, Kalshi, OG.com).
2. Forecasts wherever a model exists, and trading recommendations on the Strategy pages.
3. Live viewing of the Lake Placid UCI downhill (2-4 Oct) plus one private-book sim, set up as at Whistler.
4. One new-user sign-up, tested by hand by the owner (the walkthrough is written in its own thread).
5. A loss cap on every strategy that touches a live exchange book.

**Freeze.** The F1 round 16 book runs **Thu 1 Oct 20:30 to Sun 4 Oct 00:00 (Fri 03:30Z to Sun 07:00Z)**. No merge to
`main` in that window unless the owner says so, because every code merge deploys the VM. Fri to Sun is verify-only on
production; staging (`staging` branch, staging.racinglines.bet) may change at any time.

**Who.** *Owner* = a step only the owner can take (merge, VM command, decision). *Copilot* = a one-message handoff the
owner pastes into Copilot. *Cloud thread* = a Claude thread that writes code, docs or handoffs; it never runs long jobs.
*Mac RC* = a Remote Control session on the owner's Mac, only for read-only checks the cloud network blocks
(ChronoRace, exchanges); never for Copilot work.

## Priorities, in order

| # | Item | Done when | Owner of the work |
|---|---|---|---|
| 1 | Loss cap (PR 14, `max_loss = 500` approved by the owner) | `max_loss` really in `live/f1/2026-16.toml`, merged before Thu 20:30 | Cloud thread fixes PR 14; owner merges |
| 2 | Lake Placid live view + private-book sim | Spec with the ChronoRace event and session keys; `racinglines-live-dh@<event>` runs on the VM through Sunday's finals | Mac RC read-only probe; cloud thread writes the spec and the VM command; owner pastes it (backup first) |
| 3 | Prices recorded for every event | `vm.sh record status` shows Kalshi + OG.com books every 5 min through the weekend | Owner checks; already running |
| 4 | UI round 3 (PR 12, `track/app`) | On staging and checked by Sun, merged Mon | Copilot; owner merges Mon |
| 5 | One manual sign-up | Owner signs up a throwaway user on staging (Sat) and on production (Tue), every step ticked | Owner, with the walkthrough thread |
| 6 | Off-VM copy of the VM's data (STG-5) | A dump and `data/archive/markets` in the bucket before real users sign up | Cloud thread writes the script; owner runs it Tue |
| 7 | Forecasts and recommendations visible | Markets and Strategy pages show F1, NASCAR (next race) and MotoGP prices and recs on staging | Owner checks on staging Wed |

## Day by day

### Thu 1 Oct (today)

- **Owner:** merge PR 14 once fixed (`max_loss = 500`, already approved), **before 20:30**; R16 tier call at 18:00 (existing
  routine). Before bed: `vm.sh record status` and `vm.sh status`, both green.
- **Cloud thread (PR 14):** put the real `[live.quoting] max_loss = 500` in the spec, restore or disclose `h2h_from`,
  make the title match the diff.
- **Cloud thread (Lake Placid):** draft the downhill spec from Whistler's and the VM command for
  `racinglines-live-dh@<event>` (argument confirmed in the Lake Placid thread), backup first. Lake Placid is a World
  Cup round and timed practice may already run today: if the timing page is up, the Mac RC probe starts tonight.

### Fri 2 Oct (freeze: verify only)

- R16 FP1 Thu 21:30, FP2 Fri 01:00. **Owner:** glance at the Live tab after each session; nothing else on production.
- **Mac RC (read-only):** once `live.ucimtbworldseries.com` shows Lake Placid timing, read the ChronoRace event id
  and the qualifying and final keys from the page's requests. The cloud thread fills them into the spec.
- **Owner, VM:** `vm.sh backup <purpose>`, then paste the `racinglines-live-dh@<event>` command for a **dry run on
  timed practice or qualifying, whichever comes first** (live view only, book off), to prove the feed. Nothing
  starts on the VM until the owner pastes it.
- **Copilot:** UI round 3 Task 1 (smoke without Events/Athletes) and Task 2 (first-run path), pushed to `track/app`
  and then to `staging`.

### Sat 3 Oct (freeze: verify only)

- R16 qualifying 01:00. Lake Placid downhill qualifying (Eastern time, check the timing page).
- **Owner, VM:** if Friday's dry run was missed, run it on qualifying now (live view only, book off).
- **Owner:** sign-up test 1 on **staging**, following the walkthrough; send failures to the walkthrough thread.
- **Copilot:** round 3 Task 3 (Markets on a phone) to staging.

### Sun 4 Oct (freeze ends 00:00)

- R16 race 00:00; results about 03:00.
- **Owner, VM:** Lake Placid finals on `racinglines-live-dh@<event>` with the private book on, the same setup as
  Whistler, cap on. Afterwards stop the unit and run `racinglines live report <spec> --pdf` on the VM.
- No production merge today: the downhill book is live.

### Mon 5 Oct (merge day)

- **Owner, VM:** OWNER-5 (settle, reconcile, report R16; disable `racinglines-live-f1@2026-16.timer`).
- **Owner, GitHub:** merge PR 12 (deploys production), wait for the Actions run, then any other code PR one at a time
  (STG-6: no two deploys at once).
- **Owner, VM:** champion replays, steps 5-7 of the season-replays handoff (backup first).
- **Cloud thread:** Lake Placid report folder with `SOURCES.md`; R16 scorecard summary.

### Tue 6 Oct

- **Owner, VM:** STG-5 off-VM copy (backup, then upload); `vm.sh switch OG_VENUE on` if not on already.
- **Owner:** sign-up test 2 on **production** with a throwaway account, then delete or disable it in the admin view.
- **Owner, VM, one at a time with a backup each:** the OG.com weekly trades/books timer (its API forgets after a
  month) and the NASCAR forecast refresh.

### Wed 7 Oct

- **Owner, VM:** OWNER-9, R17 listings check (Kalshi usually lists 2-4 days out); `RACINGLINES_KALSHI_SPRINTS` per
  DEC-12.
- **Owner, staging:** the demo walkthrough end to end (sign in, Markets, a forecast, a Strategy rec, Live replay of
  Lake Placid); list anything broken.
- **Copilot:** fixes from that list only; to staging, then one PR. Last code merge of the week by 16:00.

### Thu 8 Oct (launch)

- **Owner, 12:00:** go/no-go: priorities 1-7 done or cut on purpose.
- **Owner, 18:00:** R17 tier call; invite the first users (sign-up is already open on production since PR 7); enable
  `racinglines-live-f1@2026-17.timer` before Fri 00:30.

## Owner decisions

| Decision | When | Recommendation |
|---|---|---|
| Paste the Lake Placid VM command (backup, then `racinglines-live-dh@<event>`) | Fri, when timing is up | Yes, dry run first with the book off |
| Downhill book loss cap | Sat | Use the same 500 if the downhill spec takes `max_loss`; if it doesn't, run it as a sim with no exchange link (it has none) |
| Launch scope | Mon | The MVP demo above; the full fantasy trading build (book, exchange, settlement) moves to the 22 Oct fallback date |
| STG-5 off-VM copy before inviting users | Tue | Yes: the VM disk is the only copy of the newest data |
| Install the Claude GitHub App on `racinglines-public` (STG-11) | Any time | Yes: threads then see PR and CI events |
| Who gets the first invites | Thu 12:00 | Five people or fewer; the owner's list |

## The cut line

If time runs out, cut from the bottom. Above the line ships on Thu 8 Oct; below it moves to after R17.

1. Loss cap merged (priority 1)
2. Prices recorded for every listed event (3)
3. Sign-up tested on production (5)
4. Off-VM data copy (6)
5. PR 12 UI round 3 merged (4)
6. Lake Placid live view and sim (2): if the ChronoRace keys never show, replay Whistler on staging instead

**Cut line**

7. Lake Placid report polish and `SOURCES.md`
8. New VM timers (OG.com weekly, NASCAR forecast refresh, U9 tapes)
9. MotoGP calendar ingest (MotoGP next-race price) and Polymarket MotoGP links
10. Fantasy trading, book, exchange and settlement (DEC-* batch), CI workflow patches (STG-2, STG-6, STG-8), report
    reproducibility (REP-1 to REP-7)
