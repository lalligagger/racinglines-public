<!-- Captured by scripts/docs/capture_examples.py (id help-users, scripts/docs/examples.toml) on 2026-10-14 05:12 UTC, commit 3ed9335+dirty, 0.5 s, exit 0. Output as printed: trailing spaces dropped, 0 ANSI escape codes removed. Do not edit: re-run the script. -->

<!-- --8<-- [start:command] -->
```bash title="Command"
racinglines users -h
```
<!-- --8<-- [end:command] -->

<!-- --8<-- [start:output] -->
```text title="Output"
usage: racinglines users [-h]
                         {setup,list,add,reset-fantasy,season-demo,reset-password,remove,deactivate,activate} ...

racinglines users  ->  web-app accounts and the fantasy-bucks ledger from the command line (web/accounts.py).

    racinglines users setup                         the accounts schema, ledger and manual-trading tables
                                                    (idempotent; fantasy/ledger.py); every active account
                                                    without its 1,000 signup grant gets it
    racinglines users list                          accounts, role, active, fantasy bucks
    racinglines users add NAME --role basic|pro|admin   a new account; prints a one-time password
    racinglines users reset-password NAME           a new one-time password, printed once
    racinglines users remove NAME                   delete an account with no markets or bets (else deactivate)
    racinglines users deactivate NAME | activate NAME
    racinglines users reset-fantasy [--keep maker,taker] [--apply]
                                                    every active account but --keep back to one 1,000 grant and no
                                                    trading history (paper positions, signals, house bets) and no
                                                    strategy profile; counts
                                                    only without --apply (on the VM: scripts/vm/reset_fantasy.sh)
    racinglines users season-demo [--seed N] [--year 2026] [--apply]
                                                    every fantasy player follows a random alpha style at a random
                                                    weekend share and follow rate through the season so far, replayed
                                                    on the real tapes (fantasy/season_demo.py); a database whose name
                                                    contains "demo" only; the draw only without --apply (on the VM:
                                                    scripts/vm/season_demo.sh)

Passwords are never read back: they are stored as scrypt hashes, and a reset prints a fresh one exactly once.

positional arguments:
  {setup,list,add,reset-fantasy,season-demo,reset-password,remove,deactivate,activate}

options:
  -h, --help            show this help message and exit
```
<!-- --8<-- [end:output] -->
