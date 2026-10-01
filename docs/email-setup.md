# Email for racinglines.bet: Proton Mail, Cloudflare DNS and app mail

racinglines.bet has no mail today: no MX, SPF, DKIM or DMARC record, and no mail code in the web app. The
fantasy soft launch needs it for two jobs. Players get a verification link at sign-up and a reset link
when they forget a password, and the owner needs a real inbox for invites and support. This page is the owner's
runbook for putting Proton Mail Plus on the domain, with every DNS record entered in Cloudflare, which
is the authoritative DNS. Squarespace is the registrar only, and nothing is added there. It also covers
how the app sends its mail through a Proton SMTP token (MAIL-1, MAIL-2; DEC-3), the tests that prove it
works, and how to move app mail to a transactional provider later.

**Status:** draft for the owner, Tue 2026-09-29. Tasks: OWNER-3 (steps 1–12), MAIL-1 (the mailer code), MAIL-2
(the token on the VM). Decisions: DEC-3 (provider) and DEC-21 (DMARC), both in batch A, due Wed 30 Sep
18:00 PDT (Thu 1 Oct 01:00 UTC). Part of the sprint set: [Fantasy launch](fantasy-launch.md) (the index), [the runbook](fantasy-runbook.md),
[Fantasy accounts](fantasy-accounts.md), [Fantasy trading](fantasy-trading.md),
[VM reliability](vm-reliability.md).

## What you end up with

One Proton Mail Plus account with the custom domain racinglines.bet and three addresses. Plus allows
1 custom domain and 10 addresses, so 7 stay free.

| Address | What it is | Who reads it |
|---|---|---|
| `admin@racinglines.bet` | The owner mailbox. Invites go out from here (LAUNCH-1). | Owner |
| `support@racinglines.bet` | The catch-all target and the Reply-To on every app mail. Mail to any address that doesn't exist lands here. | Owner |
| `noreply@racinglines.bet` | The app's sender. It holds the one SMTP token. Bounces come back here. | Owner, weekly for bounces |

**Cost.** EUR 4.99 a month, or EUR 47.88 a year (EUR 3.99 a month), per Proton's support page. Yearly saves
EUR 12.00. The USD prices are unverified: third-party sites quote $4.99 monthly or $3.99 a month billed
yearly. Monthly keeps the exit cheap until the retro decision on Mon 12 Oct (OWNER-10). If you want more
than one domain later, Proton Unlimited allows 3 (check its price at the time).

**Timeline.**

| When | What | Task |
|---|---|---|
| Wed 30 Sep 18:00 PDT | DEC-3 and DEC-21 signed with batch A; no DNS work yet | OWNER-2 |
| Fri 2 – Sun 4 Oct (recommended Fri 2 Oct) | Steps 1–12: account, domain, every DNS record (`_dmarc` at `p=none`), green checks, tests | OWNER-3 |
| Mon 5 Oct 12:00 PDT (hard deadline) | Every Proton tab green, step 11 tests pass | OWNER-3 |
| Tue 6 Oct, after the deploy that carries MAIL-1 | SMTP token on the VM, backend still `log`, `racinglines mail test` passes | MAIL-2 |
| Tue 6 Oct, before STAGE-1 part A (no later than the go/no-go) | DMARC from `p=none` to `p=quarantine` once step 11 tests 3–4 and MAIL-2 step 7 pass at two providers | DEC-21 |
| Wed 7 Oct 17:00–21:00 PDT (Thu 8 Oct 00:00–04:00 UTC) | Staging rehearsal sends real verify and reset mail, then the backend goes back to `log` | STAGE-1 |
| Thu 8 Oct 18:00 PDT (Fri 9 Oct 01:00 UTC) | `RACINGLINES_MAIL_BACKEND=smtp` for the soft launch | LAUNCH-1 |
| Mon 12 Oct | Stay on Proton, or plan the move to a transactional provider | OWNER-10 |
| Wed 14 Oct | DMARC `p=reject` decision only (applied after the season, if at all) | DEC-21 |

## How the pieces fit

```
Squarespace (registrar only)
  racinglines.bet -> nameservers kipp.ns.cloudflare.com, zara.ns.cloudflare.com
        |
        v
Cloudflare DNS (authoritative; every record goes here)
  @, mcp          proxied  -> tunnel racinglines-vm -> web :8000, MCP :8100   (not touched by this page)
  MX, SPF, DKIM x3, verification TXT   DNS only -> Proton
  _dmarc          rua -> Cloudflare DMARC Management
        |
        v
Proton Mail Plus
  inbound:  MX -> admin@ / support@ (catch-all) / noreply@ mailboxes
  outbound: racinglines-vm --SMTP 587, STARTTLS, noreply@ token--> smtp.protonmail.ch -> players' inboxes
```

| Piece | Role | What you change there |
|---|---|---|
| **Squarespace** | Registrar. Its nameservers point at Cloudflare (`kipp.ns.cloudflare.com`, `zara.ns.cloudflare.com`), so its own DNS panel is ignored by the internet. | Nothing. Check four settings once ([Squarespace](#squarespace)). |
| **Cloudflare** | Authoritative DNS, the tunnel `racinglines-vm`, and DMARC reports. | 8 new records (step 12). The tunnel records for `racinglines.bet` and `mcp.racinglines.bet` are not touched. |
| **Proton** | Mailboxes, the catch-all, SMTP submission for the app. | The account, the domain, three addresses, one SMTP token. |
| **racinglines-vm** | Sends app mail through Proton on port 587. GCE blocks outbound port 25 but allows 587. | The `RACINGLINES_SMTP_*` / `RACINGLINES_MAIL_*` lines in `/etc/racinglines.env` (MAIL-2). |

The VM cutover (OWNER-4, Wed 30 Sep, two days before this page's steps start) moves the `racinglines.bet` hostname from the Mac's tunnel to
`racinglines-vm` ([VM deploy: cutover](vm-deploy.md#cutover) step 4). It edits only that hostname's record. When
the tunnel dialog offers to replace the existing DNS record, it replaces the proxied `@` record only. The MX
and TXT records at `@` sit beside it and stay. Cloudflare allows MX and TXT next to a flattened apex CNAME;
that is normal. After the cutover, re-run the step 11 dig block: every mail answer must be unchanged.

## Before you start

**1. Account logins and recovery addresses.** Every account that controls DNS or mail must recover through
the owner's Gmail, never through an `@racinglines.bet` address. If mail on the domain breaks and the DNS
account's recovery goes to that domain, you cannot get back in to fix it.

| Account | Login and recovery email should be | Check |
|---|---|---|
| Squarespace (registrar) | Owner's Gmail | Account settings > email; domain contact email |
| Cloudflare | Owner's Gmail | My Profile > Email |
| Proton | Its own `@proton.me` login; recovery email = owner's Gmail | Set in step 1 |
| Google Cloud, GitHub | Owner's Gmail (unchanged) | No change; never move them to `@racinglines.bet` |

No MX exists today, so nothing can depend on an `@racinglines.bet` address yet. The rule is to keep it that way.

**2. Two-factor authentication** at Proton, Cloudflare and Squarespace (an authenticator app or a security
key). Save each site's backup codes offline, not in the Proton mailbox.

**3. Export the zone before you edit it.** Cloudflare > racinglines.bet > DNS > Records > Import and Export >
Export. Save the file locally as `data/backups/dns/racinglines.bet-before-email-<UTC>.txt` (under `data/`, so
git ignores it). It is the DNS version of "back up before any write". Cloudflare's audit log (Manage
Account > Audit Log) also lists every record change.

**4. Baseline.** Answers as of Tue 29 Sep 13:55 PDT (20:55 UTC) are in the comments.

```sh
# LOCAL (Mac) — baseline before any change
dig racinglines.bet NS +short                            # kipp.ns.cloudflare.com. / zara.ns.cloudflare.com.
dig racinglines.bet A +short                             # 104.21.49.248 / 172.67.154.124 (Cloudflare proxy: the tunnel)
dig mcp.racinglines.bet A +short                         # the same two Cloudflare addresses
dig racinglines.bet MX +short                            # (empty)
dig racinglines.bet TXT +short                           # (empty)
dig _dmarc.racinglines.bet TXT +short                    # (empty)
dig protonmail._domainkey.racinglines.bet CNAME +short   # (empty)
dig racinglines.bet DS +short                            # (empty: DNSSEC is off)
```

The Cloudflare A addresses can change over time; any Cloudflare address is fine. No AAAA answer is
returned today. The zone's negative-cache time is 1800 s (the last field of `dig racinglines.bet SOA +short`),
so a resolver that looked up "no MX" before step 5 can keep that answer for up to 30 minutes.

**5. Cloudflare Email Routing stays off.** Cloudflare > racinglines.bet > Email > Email Routing must show it as
not enabled. If it were on, it would add its own MX records (`route1/2/3.mx.cloudflare.net`) and a second
SPF, which conflict with Proton. DMARC Management (step 8) is a separate item in the same menu and does not
turn routing on.

**6. Do not enable "Flatten all CNAMEs"** (DNS > Settings, if your plan shows it). The default flattens the
apex only, which the tunnel needs. Flattening every CNAME would turn the three DKIM CNAMEs into plain
answers, and Proton's DKIM check would fail.

**7. DEC-3 and DEC-21 are signed.** DEC-3 (Proton SMTP now, transactional later) and DEC-21 (DMARC `p=none`,
reports to Cloudflare) are in batch A. If DEC-3 comes back as "transactional provider now", do steps 1–12
anyway for the mailboxes, skip [App mail](#app-mail-mail-1-mail-2-dec-3), and go straight to
[Switching to a transactional provider later](#switching-to-a-transactional-provider-later).

## Step 1: buy Proton Mail Plus

1. At proton.me, choose Mail Plus (or Unlimited if you want 3 domains). Monthly or yearly, as above.
2. The sign-up creates the account's own `@proton.me` address. It is the login; pick one you are happy to keep.
3. Settings > All settings > Account (or Recovery): set the **recovery email to the owner's Gmail**. Save the
   recovery phrase offline.
4. Turn on two-factor authentication and save the backup codes offline.

5. **Check that the plan allows SMTP tokens.** Proton's SMTP-submission page says SMTP tokens come with
   paid Mail plans that have a custom domain, but it does not name Mail Plus. After step 4 (the addresses
   exist), open Settings > All settings > IMAP/SMTP and confirm the **SMTP tokens** section offers
   `noreply@racinglines.bet`. Don't generate the token yet (that is MAIL-2 step 3). If the section is missing
   or doesn't offer `noreply@`, app mail cannot go through Proton: tell the deciding seat that DEC-3 falls back
   to its option (b), and follow [Switching to a transactional provider later](#switching-to-a-transactional-provider-later)
   for app mail while Proton keeps the mailboxes.

Done when: you can sign in with 2FA, and the recovery email shows the Gmail address as verified. The SMTP
check in item 5 is done once step 4 is, and before DEC-3 is treated as settled.

## Step 2: add the domain in Proton

Proton > Settings > All settings > Domain names (Proton's own guide lists it under Organization) >
**Add domain** > `racinglines.bet`.

Proton then shows one tab per record: Verify, MX, SPF, DKIM, DMARC. Keep this page open in one browser tab
and Cloudflare > racinglines.bet > DNS > Records in another. Every value below is copied from Proton's tab into
Cloudflare's **Add record** form.

## Step 3: verification TXT

In Cloudflare > racinglines.bet > DNS > Records > **Add record**:

| Field | Value |
|---|---|
| Type | TXT |
| Name | `@` |
| Content | `protonmail-verification=<value from Proton's Verify tab>` (paste without surrounding quotes; Cloudflare adds them) |
| TTL | Auto |

Save, then click **Verify** in Proton. If it fails, wait 5–30 minutes and try again (the negative cache above).

Done when: Proton's Verify tab is green.

## Step 4: create the addresses before MX

Create the three addresses now, so the first mail after step 5 has somewhere to land. Proton > Settings >
All settings > Identity and addresses (search "address" in settings if the label has moved) > **Add address**:

| Address | Display name |
|---|---|
| `admin@racinglines.bet` | racinglines admin |
| `support@racinglines.bet` | racinglines support |
| `noreply@racinglines.bet` | racinglines |

All three share one inbox; the To address shows which one a message was sent to. A Proton filter that files
mail to `noreply@` into a folder (for example "app bounces") keeps bounces out of the way. That is optional.

Done when: the three addresses show as active. Now do step 1 item 5 (the SMTP-token check).

## Step 5: MX

No MX record exists today, so there is nothing to delete. Add two:

| Type | Name | Mail server | Priority | TTL |
|---|---|---|---:|---|
| MX | `@` | `mail.protonmail.ch` | 10 | Auto |
| MX | `@` | `mailsec.protonmail.ch` | 20 | Auto |

MX records cannot be proxied; Cloudflare shows them as DNS only. If Proton's MX tab shows different hosts,
Proton's tab wins.

Done when: Proton's MX tab is green, and there are exactly two MX records in Cloudflare.

## Step 6: SPF

One TXT record at `@`, pasted exactly from Proton's SPF tab. Proton's SPF tab is the source of truth; the
line below is an example of its usual shape, not a value to type:

```
v=spf1 include:_spf.protonmail.ch ~all
```

If the SPF tab shows something different (for example with an extra `mx`), paste the tab's value, and use
that value wherever this page shows the SPF line (step 11's dig comment, step 12). **Only one SPF record may exist at `@`.** Two
TXT records that both start with `v=spf1` make SPF fail for every message (a permerror). Before saving, filter
Cloudflare's record list by TXT and check that the only other TXT at `@` is the verification record from step 3.

Done when: Proton's SPF tab is green.

## Step 7: DKIM

Three CNAME records, one per Proton key. Proton rotates its keys (new 2048-bit keys about every six months),
and the three CNAMEs let it do so without you. Keep all three, always.

| Type | Name | Target | Proxy status | TTL |
|---|---|---|---|---|
| CNAME | `protonmail._domainkey` | copied from Proton's DKIM tab | **DNS only** (grey cloud) | Auto |
| CNAME | `protonmail2._domainkey` | copied from Proton's DKIM tab | **DNS only** (grey cloud) | Auto |
| CNAME | `protonmail3._domainkey` | copied from Proton's DKIM tab | **DNS only** (grey cloud) | Auto |

- **Cloudflare sets new CNAMEs to Proxied by default.** Turn the orange cloud off before saving. A proxied DKIM
  record answers with Cloudflare addresses instead of Proton's key, and Proton's check fails.
- The targets look like `protonmail.domainkey.<id>.domains.proton.ch` (Proton's page shows that pattern; the
  exact format here is unverified). Copy them; don't type them.
- **Trailing dot.** Proton's values may end with a dot. Cloudflare accepts either form. If a form ever
  rejects the value, delete the final dot.
- **Name only.** Enter `protonmail._domainkey`, not `protonmail._domainkey.racinglines.bet`. Cloudflare appends
  the zone name, and a pasted full name can end up doubled.

Done when: Proton's DKIM tab is green for all three.

## Step 8: DMARC

1. Cloudflare > racinglines.bet > Email > **DMARC Management** > Enable (free on Cloudflare DNS). It shows a
   reporting address like `<id>@dmarc-reports.cloudflare.net`. Copy it.
2. The record (DEC-21):

| Type | Name | Content | TTL |
|---|---|---|---|
| TXT | `_dmarc` | `v=DMARC1; p=none; rua=mailto:<id>@dmarc-reports.cloudflare.net` | Auto |

If Cloudflare offers to create or update the `_dmarc` record for you, accept, then check the result matches
the row above and that exactly one `_dmarc` TXT exists. Proton's DMARC tab suggests `p=quarantine`; start at
`p=none` for the first days anyway, so the first tests can't quarantine anything.

`p=none` changes nothing about delivery. It only asks receivers to send reports, which Cloudflare shows as
a list of sending sources with pass and fail counts.

**Move to `p=quarantine` before the launch (DEC-21, recommended).** While the policy is `none`, anyone can send
mail that claims to be from `noreply@racinglines.bet` and receivers will still deliver it. The soft launch sends
50 invited players verification and reset links from that address, so a spoofed "reset your password" mail is an
easy phishing setup against a new brand. So: as soon as step 11 tests 3 and 4 show SPF, DKIM and DMARC PASS for
both `admin@` and `noreply@`, and the MAIL-2 step 7 mail passes at Gmail and the second provider, edit the record
to `p=quarantine` (`pct` left at its default of 100, same `rua`). Target **Tue 6 Oct, before STAGE-1 part A**, and
no later than the go/no-go (Thu 8 Oct 12:00 PDT). Nothing but Proton sends as racinglines.bet today, so the risk of
quarantining real mail is small; if a third-party sender is ever added, it goes on a subdomain
(see [Switching](#switching-to-a-transactional-provider-later)).

| Type | Name | Content | TTL |
|---|---|---|---|
| TXT | `_dmarc` | `v=DMARC1; p=quarantine; rua=mailto:<id>@dmarc-reports.cloudflare.net` | Auto |

Consider `p=reject` only after the season, if the reports show only Proton sending and passing (DEC-21).

Done when: the record exists and Proton's DMARC tab has checked it (see Open items on `p=none` and green).

## Step 9: catch-all

Proton > Settings > All settings > Domain names (under Organization) > racinglines.bet > **Actions** >
**Set catch-all** > `support@racinglines.bet`.

Mail to any address that doesn't exist (`info@`, typos) now lands in `support@`. A catch-all also attracts
guessed-address spam; if that gets heavy, turn it off here and nothing else changes.

## Step 10: wait for green

Proton re-checks the records on its own; the domain page also has a button to re-check. Expect minutes to a
few hours. Allow up to 24 h. The authoritative answers (step 11's first dig block) are instant, so if those
are right and Proton is still red after an hour, use [Troubleshooting](#troubleshooting).

Done when: Proton shows green for verification, MX, SPF, DKIM (all three) and DMARC. Hard deadline Mon 5 Oct 12:00 PDT.

## Step 11: tests

| # | Test | How | Pass when |
|---:|---|---|---|
| 1 | Inbound | From Gmail, send to `admin@racinglines.bet` | Arrives in Proton within 2 minutes |
| 2 | Catch-all | From Gmail, send to `hello@racinglines.bet` | Arrives in Proton, addressed to `hello@` |
| 3 | Outbound and authentication | Reply from `admin@` to Gmail. In Gmail, open it > ⋮ (More) > **Show original** | SPF: PASS, DKIM: PASS (domain racinglines.bet), DMARC: PASS |
| 4 | The app's address | In Proton, send a message from `noreply@` to Gmail; check Show original | Same three PASS lines |
| 5 | Score | Send from `admin@` to the address mail-tester.com gives you | 9/10 or better (the site allows a few free tests a day) |
| 6 | DNS | The two dig blocks below | Answers as in the comments |

```sh
# LOCAL (Mac) — answers straight from Cloudflare's nameserver (no cache delay)
NS=kipp.ns.cloudflare.com
dig @$NS racinglines.bet MX +short                    # 10 mail.protonmail.ch. / 20 mailsec.protonmail.ch.
dig @$NS racinglines.bet TXT +short                   # "protonmail-verification=..." and the SPF line from step 6
dig @$NS _dmarc.racinglines.bet TXT +short            # "v=DMARC1; p=none; rua=mailto:...@dmarc-reports.cloudflare.net"
for s in protonmail protonmail2 protonmail3; do dig @$NS $s._domainkey.racinglines.bet CNAME +short; done
                                                      # three ...domains.proton.ch. targets; empty means proxied or missing
dig @$NS racinglines.bet A +short                     # still the Cloudflare addresses: the tunnel is untouched
```

```sh
# LOCAL (Mac) — the same through your normal resolver (can lag by up to 30 minutes)
dig racinglines.bet MX +short                         # the same two MX answers
dig _dmarc.racinglines.bet TXT +short                 # the same DMARC answer
bash scripts/deploy/smoke.sh https://racinglines.bet  # the site still works
```

Keep the dig output and the mail-tester score: they are evidence for the go/no-go email line (line 7) in the
[runbook](fantasy-runbook.md#go-no-go).

## Step 12: the whole zone after setup

Ten records: the two tunnel records that were already there, plus the eight this page adds. Values in
angle brackets are copied from Proton or Cloudflare.

| Type | Name | Content | Priority | Proxy status | TTL | Owner of the record |
|---|---|---|---:|---|---|---|
| CNAME (flattened) | `racinglines.bet` (`@`) | the tunnel: today the Mac's; after the cutover `<racinglines-vm tunnel id>.cfargotunnel.com` | – | Proxied | Auto | Tunnel. **Not touched here.** The cutover edits only this one. |
| CNAME | `mcp` | `<racinglines-vm tunnel id>.cfargotunnel.com` | – | Proxied | Auto | Tunnel. **Not touched.** |
| TXT | `@` | `protonmail-verification=<value>` | – | DNS only | Auto | Proton (step 3) |
| MX | `@` | `mail.protonmail.ch` | 10 | DNS only | Auto | Proton (step 5) |
| MX | `@` | `mailsec.protonmail.ch` | 20 | DNS only | Auto | Proton (step 5) |
| TXT | `@` | `<SPF line from Proton's SPF tab>` (step 6) | – | DNS only | Auto | Proton (step 6) |
| CNAME | `protonmail._domainkey` | `<Proton DKIM target 1>` | – | DNS only | Auto | Proton (step 7) |
| CNAME | `protonmail2._domainkey` | `<Proton DKIM target 2>` | – | DNS only | Auto | Proton (step 7) |
| CNAME | `protonmail3._domainkey` | `<Proton DKIM target 3>` | – | DNS only | Auto | Proton (step 7) |
| TXT | `_dmarc` | `v=DMARC1; p=none; rua=mailto:<id>@dmarc-reports.cloudflare.net` | – | DNS only | Auto | Cloudflare DMARC (step 8) |

That is 2 + 8 = 10 (the two TXT records at `@`, verification and SPF, count separately). If the
dashboard shows any other record (for example a leftover from the Mac's tunnel), leave it alone and add a
line for it here. How the Mac's tunnel serves `racinglines.bet` today is not in the repo
([VM deploy: cutover](vm-deploy.md#cutover) step 4 says how to check), so the apex row may be a proxied A
record rather than a CNAME until the cutover.

## Squarespace

Squarespace is the registrar: it holds the registration and points the domain at Cloudflare's nameservers.
Nothing else there matters while the nameservers are `kipp`/`zara`.

**Check once** (Squarespace > Domains > racinglines.bet):

| Setting | Should be |
|---|---|
| DNS > Domain nameservers | Custom nameservers `kipp.ns.cloudflare.com` and `zara.ns.cloudflare.com` |
| Auto-renew | On, with a payment method that won't expire before the renewal date |
| Registrar lock (domain / transfer lock) | On |
| Contact email | The owner's Gmail (renewal and ICANN verification notices go there) |

**Do not:**

- Add DNS records at Squarespace. With custom nameservers, the internet never reads them. A record added
  there by mistake is the most common reason a Proton tab stays red.
- Buy Squarespace email, Google Workspace, or Squarespace email forwarding. Proton does this job; forwarding
  needs Squarespace's own nameservers anyway.
- Switch the nameservers back to Squarespace's. That would drop every Cloudflare record at once: the tunnel
  (the site and the MCP server go down) and all mail.

**Optional, not this sprint: DNSSEC.** Off today (no DS record). To turn it on: Cloudflare > DNS > Settings >
DNSSEC > Enable shows one DS record; paste it into Squarespace's DNSSEC panel (one DS allowed; whether
Squarespace accepts a DS with custom nameservers is unverified). Remove the DS at Squarespace first, and
wait a day, before ever moving the nameservers away from Cloudflare or turning DNSSEC off there. Otherwise
validating resolvers treat the whole domain as broken.

## App mail (MAIL-1, MAIL-2; DEC-3)

The app sends four kinds of mail, all plain text, one recipient per message, from
`racinglines <noreply@racinglines.bet>` with Reply-To `support@racinglines.bet`. Links are built from
`RACINGLINES_URL=https://racinglines.bet`. Token rules and page flows are in
[Fantasy accounts](fantasy-accounts.md); this is the mail side.

| Message | Template (new) | Sent when | Link and lifetime |
|---|---|---|---|
| Verify | `mail/verify.txt` | Sign-up, and `/verify/resend` (3 an hour per user) | `/verify/{token}`, 24 h |
| Reset | `mail/reset.txt` | `/password/forgot` (3 an hour per email, 10 an hour per IP) | `/password/reset/{token}`, 1 h |
| Email change | `mail/email_changed.txt` | An email change on `/account` | email_change token, 24 h |
| Welcome | `mail/welcome.txt` | After verification, with the season, role and F$ grant | none |

### MAIL-1: the mailer (code; Sonnet; switches off)

Everything here is **new**. Nothing sends mail until `RACINGLINES_MAIL_BACKEND=smtp`.

| File | Change |
|---|---|
| `racinglines/web/mailer.py` (new) | `RACINGLINES_MAIL_BACKEND=log|smtp`, default `log`. `log` writes the message to the journal and a metadata row to activity_log; no network. `smtp` uses `smtplib.SMTP(host, 587, timeout=10)`, `starttls()`, `login(RACINGLINES_SMTP_USER, RACINGLINES_SMTP_TOKEN)`. Sends in a background thread with 3 retries on temporary (4xx) errors and no retry on permanent (5xx) ones. Refuses past `RACINGLINES_MAIL_DAILY_CAP` messages per UTC day, counted from activity_log so the count survives restarts. Never logs the token. activity_log gets a `mail_sent` or `mail_failed` row with metadata only (the recipient's user id, the recipient's domain, template, result), never the full address and never the link, per [Fantasy accounts](fantasy-accounts.md) (no row holds a full email address). |
| `racinglines/cli/mail.py` (new) | `racinglines mail test --to <addr> [--backend log|smtp]`: sends one test message, prints backend, host, port, user, the server's reply and the elapsed time; exit 0 on success. Never prints the token. |
| `racinglines/cli/__init__.py` | Add `mail` to `GROUPS` and to the module docstring. |
| `racinglines/web/templates/mail/verify.txt`, `reset.txt`, `welcome.txt`, `email_changed.txt` (new) | Plain text. "F$", never a bare "$". A line saying who sent it and that the reader can ignore it if they didn't ask. |
| `deploy/vm/racinglines.env.example` | The block in MAIL-2 step 4, with the token left blank. |
| `tests/test_mailer.py` (new) | `smtplib` mocked, no network: log backend opens no connection; smtp backend calls `starttls` then `login` on port 587; 4xx is retried 3 times, 5xx not at all; the daily cap refuses message 201; links start with `RACINGLINES_URL`; the token never appears in logs or activity_log; activity_log rows hold the recipient's domain, never the full address; `mail test --backend smtp` overrides a `log` setting. |

In `log` mode the journal line includes the link, so the owner can finish a test sign-up without SMTP. Only
sudo users read the journal. activity_log never holds the link, because the MCP SQL console could read it
before ADM-1 hides that table.

A retry that is still waiting when the web app restarts is lost; the player uses `/verify/resend` or
`/password/forgot` again. The daily cap of 200 fits 50 invited players at about 4 mails each (verify,
welcome, one resend, one reset).

Verify:

```sh
# LOCAL (Mac)
python -m pytest tests/test_mailer.py -m "not live"
```

### MAIL-2: the SMTP token on the VM (owner; Tue 6 Oct)

Prerequisites: steps 1–11 done, and the deploy that carries MAIL-1 is on the VM. Tue 6 Oct has no race
session, so the web restart below costs a few seconds of nobody's time. It writes no race data.
`racinglines mail test` adds one activity_log audit row, the same kind a sign-in writes, so no backup is needed.

**1. Reach the VM.**

```sh
# LOCAL (Mac)
bash scripts/deploy/vm.sh ssh
```

**2. Check that MAIL-1 is deployed and port 587 is reachable.**

```sh
# VM (production) — read-only
LOG=/opt/racinglines/data/backups/mail-precheck-$(date -u +%Y%m%dT%H%M%SZ).log
{ sudo -u racinglines /opt/racinglines/.venv/bin/racinglines mail -h | head -5
  timeout 10 openssl s_client -starttls smtp -connect smtp.protonmail.ch:587 -brief </dev/null 2>&1 | head -5
} 2>&1 | sudo tee "$LOG"
```

Pass: the first lines show `racinglines mail` usage (not the top-level group list), and `openssl` prints
`CONNECTION ESTABLISHED` and a TLS protocol line. If `mail` is missing, MAIL-1 is not deployed yet; stop here.

**3. Generate the token (Proton, in the browser).** Proton > Settings > All settings > IMAP/SMTP >
SMTP tokens > **Generate token**. Choose the address `noreply@racinglines.bet`; name it `racinglines-vm` if
asked. The token is shown **once**. Keep the popup open and go straight to the next block. Don't paste it
into chat, a Claude session, a note, or a command line.

**4. Add the block to `/etc/racinglines.env`.** ⚠️ VM configuration: this edits the production settings
file. Only the owner runs it.

```sh
# VM (production) — opens an editor; the token goes into the file only, never into shell history
sudoedit /etc/racinglines.env
```

Add these lines at the end (or `sudo nano /etc/racinglines.env`, as in [VM deploy](vm-deploy.md)). The token goes
between the single quotes:

```sh
RACINGLINES_MAIL_BACKEND=log
RACINGLINES_SMTP_HOST=smtp.protonmail.ch
RACINGLINES_SMTP_PORT=587
RACINGLINES_SMTP_USER=noreply@racinglines.bet
RACINGLINES_SMTP_TOKEN='<paste the token here>'
RACINGLINES_MAIL_FROM="racinglines <noreply@racinglines.bet>"
RACINGLINES_MAIL_REPLY_TO=support@racinglines.bet
RACINGLINES_MAIL_DAILY_CAP=200
```

Keep the quotes. The same file is read by systemd (`EnvironmentFile=`) and sourced by bash for CLI commands
(`set -a; . /etc/racinglines.env`). Unquoted, bash reads the `<` and `>` in `MAIL_FROM` as redirections and
every CLI command fails. The backend stays `log` until the launch (LAUNCH-1). Close the Proton popup after saving.

**5. Check the key names (never the values).**

```sh
# VM (production) — prints names only
sudo grep -E '^RACINGLINES_(SMTP|MAIL)_' /etc/racinglines.env | cut -d= -f1
ls -l /etc/racinglines.env        # -rw-r----- root racinglines
```

Pass: eight names, and the file is still mode 640, owner root, group racinglines.

**6. Restart the web app.** ⚠️ Restarts racinglines-web for a few seconds. Do it between sessions. Sessions
survive, because `APP_SECRET` is set.

```sh
# VM (production)
sudo systemctl restart racinglines-web && sleep 3 && systemctl is-active racinglines-web
```

**7. Send the test mail** to the owner's Gmail and to one address at another provider (Outlook.com or
Yahoo). The go/no-go needs both.

```sh
# VM (production) — sends two real messages through Proton; the backend in the file stays log
LOG=/opt/racinglines/data/backups/mail-test-$(date -u +%Y%m%dT%H%M%SZ).log
for TO in '<owner Gmail>' '<second provider address>'; do
  sudo -u racinglines bash -c "set -a; . /etc/racinglines.env; set +a; cd /opt/racinglines && .venv/bin/racinglines mail test --to '$TO' --backend smtp"
done 2>&1 | sudo tee "$LOG"
```

Pass: each run prints a `250` reply from the server. Both messages arrive within 2 minutes,
not in spam. Show original shows SPF, DKIM and DMARC PASS for racinglines.bet. The log holds no token.

**8. Check the site** (from a second terminal on the Mac, or after `exit`).

```sh
# LOCAL (Mac)
bash scripts/deploy/smoke.sh https://racinglines.bet
```

Done when: steps 2–8 pass. The two log paths go into the P2 check-in.

**After MAIL-2.** The staging rehearsal (STAGE-1, Wed 7 Oct) sets `RACINGLINES_MAIL_BACKEND=smtp` for the
rehearsal and puts it back to `log` at the end. The launch (LAUNCH-1, Thu 8 Oct 18:00 PDT / Fri 9 Oct 01:00
UTC) sets it to `smtp` with the other switches; that block is in the [runbook's launch day](fantasy-runbook.md#launch-day).

## Limits and caveats

- **Proton is not built for bulk mail.** Its terms treat bulk or unsolicited mail as abuse. Verification and
  reset mail to 50 invited players is ordinary use. A newsletter is not.
- **The paid SMTP cap is undisclosed.** Proton's page gives Free-plan limits (50 an hour, 150 a day) and says
  paid limits depend on the account's reputation. `RACINGLINES_MAIL_DAILY_CAP=200` is our own ceiling, below
  whatever Proton allows a new account.
- **100 recipients per message**, and each recipient counts as one email. The app sends one recipient per
  message. Send the launch invites from `admin@` one per player (each has its own code), not as one BCC batch.
- **Error codes.** Proton lists these on its SMTP-errors page as codes any mail server may return. The reply
  text in the `mail test` output or the journal says which server returned it.

| Code | Meaning | What to do |
|---|---|---|
| `550 5.4.5` | Daily sending quota exceeded. Permanent: the mailer does not retry. | Set `RACINGLINES_MAIL_BACKEND=log` and restart web, so players aren't told a mail went out. Verify waiting players by hand: **Mark email verified** on `/admin/fantasy/members/{user_id}` (ADM-1; writes `email_verify` with `by=admin`). Try again the next day. If it happens twice, move app mail to a transactional provider (below). |
| `421 4.7.0` | Temporary: unusual volume from the sending IP, or the IP is not allowed for that recipient. The mailer retries 3 times. | If it persists for an hour: backend to `log`, check the Proton account for a notice, contact Proton support. Same escalation as above. |
| `535` (authentication failed) | The token was revoked or mistyped, or the user is not `noreply@racinglines.bet` exactly. | Generate a new token and redo MAIL-2 steps 4–7. |

- **Replies land in `support@` in Proton.** The app reads no mail: no IMAP, no Proton Bridge. Bounces go to
  the envelope sender, `noreply@`, in the same inbox; check them weekly.
- **Not end-to-end encrypted.** SMTP submission uses ordinary TLS to Proton and on to the recipient. That is
  fine for links that expire in 1–24 h.

## Switching to a transactional provider later

**When** (decided at OWNER-10, Mon 12 Oct, or earlier if forced). Any one of:

- open sign-up (`RACINGLINES_SIGNUP=open`, not before Thu 22 Oct);
- more than about 100 app mails a day;
- verification mail landing in spam at Gmail or Outlook in tests or player reports;
- any `550 5.4.5`, or `421 4.7.0` more than once.

**How.** Use Postmark or Resend (or SES) on a sending subdomain, for example `notify.racinglines.bet`. The
root domain keeps Proton for the mailboxes.

1. Add the domain `notify.racinglines.bet` in the provider. It gives you a DKIM record, a Return-Path (bounce)
   record with its own SPF, and sometimes a verification TXT. **All of them go under the subdomain**, in
   Cloudflare, DNS only. The exact names and values come from the provider; they are not guessed here.
2. **Never add a second SPF at `@`**, and don't add the provider to Proton's SPF. Receivers check SPF on the
   Return-Path domain, which is the provider's host under `notify`.
3. DMARC needs no new record. The root `_dmarc` covers subdomains, and relaxed alignment accepts DKIM signed
   for `notify.racinglines.bet` on mail from `noreply@notify.racinglines.bet`. Watch the Cloudflare DMARC
   reports for the new source passing.
4. App change, env only (no code): the `RACINGLINES_SMTP_*` values become the provider's SMTP host, port 587,
   user and token (see the provider's docs; for example Postmark's `smtp.postmarkapp.com`, Resend's
   `smtp.resend.com`), and `RACINGLINES_MAIL_FROM` becomes `"racinglines <noreply@notify.racinglines.bet>"` if the From
   moves to the subdomain. `RACINGLINES_MAIL_REPLY_TO` stays `support@racinglines.bet`, so replies still reach Proton.
5. Redo MAIL-2 steps 4–8 with the new values, then revoke the Proton SMTP token.

Prices and free tiers are not verified here; check them when you decide.

## Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| A Proton tab stays red, but the record looks right | Added at Squarespace instead of Cloudflare | Add it in Cloudflare. Records at Squarespace are ignored. |
| Verification or SPF red | Checked too early (negative cache, up to 30 min); quotes pasted into Content; a typo | Compare with the authoritative dig block; re-check after 30 minutes |
| DKIM red, dig returns nothing or an IP | The CNAME is Proxied (orange cloud) | Edit the record, set DNS only |
| DKIM red, name looks odd | Full name pasted, so the zone was appended twice | Name must be `protonmail._domainkey` (and 2, 3) only |
| DKIM red, value rejected | Trailing dot | Remove the final dot |
| DKIM red, record is DNS only, but `dig ... CNAME` returns nothing | "Flatten all CNAMEs" is on | Turn it off (DNS > Settings) |
| SPF fails in Show original (permerror) | Two `v=spf1` TXT records at `@` | Merge into one; delete the other |
| Extra MX or SPF appeared | Cloudflare Email Routing was enabled | Disable Email Routing; delete its `route*.mx.cloudflare.net` MX and its SPF |
| Mail from the app lands in spam | New domain with no reputation yet; a failing check | Show original: all three PASS? Run mail-tester and read its report. Keep templates plain text with one link. If it persists, see [Switching](#switching-to-a-transactional-provider-later). |
| `mail test` fails with 535 | Token revoked or mistyped; wrong user | New token; MAIL-2 steps 3–7 |
| `mail test` times out | Outbound 587 blocked | Rerun MAIL-2 step 2. The default VPC allows outbound 587; check for a custom egress rule. |
| Every CLI command fails with `noreply@racinglines.bet: No such file or directory` | `RACINGLINES_MAIL_FROM` is unquoted in `/etc/racinglines.env` | Add the double quotes (MAIL-2 step 4) |
| Links in mail point to the wrong host | `RACINGLINES_URL` | Must be `https://racinglines.bet` |
| The site or MCP went down after a DNS edit | The `@` or `mcp` record was edited | Restore it from the zone export or the audit log; [VM deploy: cutover](vm-deploy.md#cutover) has the tunnel steps |

## Rollback

Undo in this order: the app first, then the token, then DNS. Only go as far as you need.

**1. Stop app mail.** ⚠️ VM configuration and a web restart.

```sh
# VM (production) — set RACINGLINES_MAIL_BACKEND=log in the editor, save
sudoedit /etc/racinglines.env
```

```sh
# VM (production)
sudo systemctl restart racinglines-web && sleep 3 && systemctl is-active racinglines-web
```

Players waiting for a mail are verified by hand with **Mark email verified** on
`/admin/fantasy/members/{user_id}` (ADM-1, in [Fantasy accounts](fantasy-accounts.md)); the mail-failure
runbook is in [VM reliability](vm-reliability.md).

**2. Revoke the token.** Proton > Settings > All settings > IMAP/SMTP > SMTP tokens > revoke `racinglines-vm`.
Then delete the `RACINGLINES_SMTP_TOKEN` line from `/etc/racinglines.env` (same `sudoedit`).

**3. Stop inbound mail (only if leaving Proton).** In Cloudflare, delete the two MX records. Senders then find
no mail server for the domain and their mail bounces after their retries. Mail already in Proton stays.
To remove Proton completely, also delete the verification TXT, the SPF TXT, the three DKIM CNAMEs and
`_dmarc` (step 12 lists them), then remove the domain in Proton. Never delete the `@` or `mcp` tunnel records.
Keep SPF, DKIM and DMARC for as long as anything still sends as racinglines.bet.

## Security

**The SMTP token.**

- It lives in one place: `/etc/racinglines.env` on racinglines-vm (root-owned, mode 640, group racinglines).
  Never in git, chat, a Claude session, shell history, a ticket, or a log. `deploy/vm/racinglines.env.example`
  carries the key with an empty value.
- Anyone with sudo on the VM, or in the racinglines group, can read it. So can anyone who can read the GCE
  snapshots of disk `racinglines-vm` (the snapshot schedule racinglines-daily copies the whole disk). Keep
  the project's IAM owner-only.
- `/healthz` and the ops alerts carry no secrets (OPS-1). Don't `cat` the env file on a shared screen or in
  a block that tees to a log; MAIL-2 step 5 shows how to check names only.
- **One token per client.** The VM has `racinglines-vm`. If the Mac ever needs to send real mail, it gets its
  own token (`racinglines-mac`), so revoking one never breaks the other. By default the Mac stays on `log`.
- **Rotate** by adding the new before removing the old: generate a new token, replace it with `sudoedit`,
  restart web, run MAIL-2 step 7, then revoke the old token. Rotate when anyone with VM access leaves, on any
  suspicion, and otherwise every 6 months (next by Tue 6 Apr 2027).

**Who holds access.**

| Account | Who | 2FA | Recovery path |
|---|---|---|---|
| Owner's Gmail | Owner | Security key or authenticator | Recovery phone. This is the root of every other recovery, so protect it most. |
| Proton | Owner only (Plus is a single-user plan) | Authenticator plus offline backup codes | Recovery email = Gmail; recovery phrase kept offline |
| Cloudflare | Owner (Super Administrator) | Authenticator plus offline backup codes | Gmail |
| Squarespace | Owner | Authenticator | Gmail |
| `/etc/racinglines.env` on the VM | Owner, through `vm.sh ssh` (IAP, Google login) | Google account 2FA | GCE snapshot, or rebuild per [VM deploy](vm-deploy.md) |

Don't share the Proton login. If a collaborator needs to answer `support@`, that is a plan change (Proton's
business plans have more than one user); decide it then. If someone needs DNS access, add them as a
Cloudflare member instead of sharing the login.

## Tasks

| Id | Title | Role / model | Files | Size | Depends on | Verify |
|---|---|---|---|---|---|---|
| OWNER-3 | Proton Mail Plus for racinglines.bet and every DNS record in Cloudflare (steps 1–12) | owner | Cloudflare DNS zone racinglines.bet; Proton account settings | S (~1–2 h hands-on; up to 24 h propagation) | OWNER-2 (DEC-3, DEC-21) | Proton green for verification, MX, SPF, DKIM x3 and DMARC; step 11 tests. Fri 2 – Sun 4 Oct; green by Mon 5 Oct 12:00 PDT. |
| MAIL-1 | Mailer: `racinglines/web/mailer.py` with `RACINGLINES_MAIL_BACKEND=log|smtp`, plain-text templates, `racinglines mail test --to` | implement / Sonnet | see [MAIL-1](#mail-1-the-mailer-code-sonnet-switches-off) | M (~16 calls, 9 files) | none | `python -m pytest tests/test_mailer.py -m "not live"` |
| MAIL-2 | SMTP token for `noreply@racinglines.bet` in `/etc/racinglines.env` (backend still `log`), restart web, `racinglines mail test` with `--backend smtp` | owner | `/etc/racinglines.env` (VM) | S (~20 min) | OWNER-3, MAIL-1 deployed | MAIL-2 steps 2–8; Tue 6 Oct |

Related tasks in the other docs: OWNER-4 (cutover; edits only the `racinglines.bet` hostname record),
ACC-3 (the sign-up, verify and reset flows that call the mailer), STAGE-1 and LAUNCH-1 (backend to `smtp`),
OWNER-10 (stay on Proton or switch; the DMARC `p=reject` decision). OWNER-3, MAIL-1 and MAIL-2 are not
money-adjacent; OWNER-4 and LAUNCH-1 are, and carry their ⚠️ in their own docs. MAIL-2 and the rollback blocks
are VM configuration and carry the ⚠️ marker for that reason.

## Names used across these docs

The subset of the conventions this page uses, copied from the master copy in [Fantasy launch](fantasy-launch.md).

- EMAIL (Proton Mail Plus, 10-address cap): admin@racinglines.bet (owner mailbox), support@racinglines.bet (catch-all target and reply-to), noreply@racinglines.bet (app sender, holds the SMTP token). DMARC reports go to the rua address from Cloudflare DMARC Management.
- ENV: RACINGLINES_MAIL_BACKEND=log|smtp (default log); RACINGLINES_SMTP_HOST=smtp.protonmail.ch; RACINGLINES_SMTP_PORT=587; RACINGLINES_SMTP_USER=noreply@racinglines.bet; RACINGLINES_SMTP_TOKEN (secret, never in git); RACINGLINES_MAIL_FROM=racinglines <noreply@racinglines.bet>; RACINGLINES_MAIL_REPLY_TO=support@racinglines.bet; RACINGLINES_MAIL_DAILY_CAP=200. Existing: RACINGLINES_URL=https://racinglines.bet (base for mail links); APP_SECRET (must be set). Never touched: POLYMARKET_TRADING_ENABLED, KALSHI_TRADING_ENABLED.
- email_tokens: id, user_id FK CASCADE, purpose (verify|reset|email_change), token_hash String(64) UNIQUE (sha256 hex), email, created_at, expires_at, used_at. TTL: verify 24 h, reset 1 h, email_change 24 h.
- Public routes (add to PUBLIC_PATHS): /signup, /verify/{token}, /verify/resend, /password/forgot, /password/reset/{token}.
- CLI: racinglines mail test --to <addr>.
- CODE: racinglines/web/mailer.py; racinglines/cli/mail.py; templates mail/verify.txt, mail/reset.txt, mail/welcome.txt, mail/email_changed.txt; tests/test_mailer.py.
- activity_log actions (new), the ones about mail: signup, verify_resend, password_reset_request, email_change, mail_sent, mail_failed.
- soft launch = RACINGLINES_SIGNUP=invite from Thu 8 Oct 18:00 PDT (Fri 9 Oct 01:00 UTC). open sign-up = RACINGLINES_SIGNUP=open (not before Thu 22 Oct).
- staging rehearsal = Wed 7 Oct on the VM with RACINGLINES_SIGNUP=invite and tester codes in season 2026-dryrun.
- Times: owner-facing times in PDT with UTC in brackets; systemd OnCalendar in UTC.
- Owner-run logs: /opt/racinglines/data/backups/<name>-<UTC>.log.

In `/etc/racinglines.env` the `RACINGLINES_MAIL_FROM` value is written with double quotes (MAIL-2 step 4); the
value itself is the one above.

## What this doesn't cover

- The sign-up, verification, reset, email-change and deletion flows, token storage and rate limits:
  [Fantasy accounts](fantasy-accounts.md).
- The launch switch flips, the off switch and the go/no-go checklist: [Fantasy launch runbook](fantasy-runbook.md).
- The mail-failure incident runbook, ops alerts and the admin-verify fallback in context:
  [VM reliability](vm-reliability.md).
- Turnstile and Cloudflare rate-limiting rules on the public forms (DEC-16).
- Marketing or newsletter mail. Not planned; it would need a bulk provider and consent records.
- The app reading mail (IMAP, Proton Bridge, parsing replies or bounces).
- Cloudflare Access for `mcp.racinglines.bet`, and DNSSEC beyond the optional note above.
- The privacy page's wording about email addresses (LEGAL-1, DEC-22).

## Open items

1. **DEC-3 and DEC-21 unsigned.** Batch A, due Wed 30 Sep 18:00 PDT (Thu 1 Oct 01:00 UTC). Steps 1–12 wait for them, and start Fri 2 Oct.
2. **DKIM target format** is unverified until Proton's DKIM tab shows it. Copy, don't type.
3. **Proton's DMARC check at `p=none`.** Whether Proton shows green or a warning while the policy is `none` is
   unverified. If it warns, the go/no-go email line should read "record present, `p=none` per DEC-21" rather
   than "green".
4. **USD pricing** is unverified; Proton bills in EUR on its support page.
5. **Proton menu labels** ("Domain names" under Organization, "Identity and addresses", "IMAP/SMTP") may differ
   on Mail Plus. Proton's settings search finds them.
6. **A second test address** at another provider (Outlook.com or Yahoo) for MAIL-2 step 7 and the go/no-go.
   The owner picks it.
7. **Cloudflare DMARC Management's menu location** in the current dashboard (Email > DMARC Management) should be
   confirmed on Fri 2 Oct.
8. **Squarespace and DNSSEC.** Whether Squarespace accepts a DS record with custom nameservers is unverified.
   Not needed this sprint.
9. **Mail lost on restart.** A retry still pending when the web app restarts is dropped. The player resends.
    Accept it for the soft launch, or have MAIL-1 queue mail in the database (a schema change, so not this sprint).
