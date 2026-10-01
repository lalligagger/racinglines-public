"""racinglines users  ->  web-app accounts and the fantasy-bucks ledger from the command line (web/accounts.py).

    racinglines users setup                         the accounts schema and ledger (idempotent); every active
                                                    account without its 1,000 signup grant gets it
    racinglines users list                          accounts, role, active, fantasy bucks
    racinglines users add NAME --role basic|pro|admin   a new account; prints a one-time password
    racinglines users reset-password NAME           a new one-time password, printed once
    racinglines users remove NAME                   delete an account with no markets or bets (else deactivate)
    racinglines users deactivate NAME | activate NAME

Passwords are never read back: they are stored as scrypt hashes, and a reset prints a fresh one exactly once.
"""

import argparse

from sqlalchemy import text


def main(argv=None):
    ap = argparse.ArgumentParser(prog="racinglines users", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("setup")
    sub.add_parser("list")
    a = sub.add_parser("add")
    a.add_argument("name")
    a.add_argument("--role", default="basic", choices=("basic", "pro", "admin"))
    for cmd in ("reset-password", "remove", "deactivate", "activate"):
        sub.add_parser(cmd).add_argument("name")
    args = ap.parse_args(argv)

    from racinglines.db.config import get_engine, get_session
    from racinglines.web import accounts as ACC
    from racinglines.web import users as U
    eng = get_engine()

    if args.cmd == "setup":
        n = ACC.setup(eng)
        print(f"accounts.fantasy_ledger ready; {n} signup grants of {ACC.SIGNUP_GRANT} added")
        return 0
    if args.cmd == "list":
        with eng.connect() as c:
            bal = ACC.balances(c)
            for i, name, role, active in c.execute(text("SELECT id, username, role, active FROM users ORDER BY id")):
                print(f"{i:>5}  {name:<30} {U.canonical(role):<6} {'active' if active else 'inactive':<8} "
                      f"{bal.get(i, 0):>10,.0f}")
        return 0

    with get_session() as s:
        u = U.get_user(s, username=args.name)
        if args.cmd == "add":
            temp = ACC.temp_password()
            u = U.create_user(s, args.name, temp, args.role)
            if ACC.ready(s.connection()):
                ACC.grant(s.connection(), u.id, note="cli add")
                s.commit()
            U.log(eng, None, "user_create", username=args.name, role=args.role, via="cli")
            print(f"created {args.role} {args.name}; one-time password (not shown again): {temp}")
            return 0
        if u is None:
            print(f"no user {args.name!r}")
            return 1
        if args.cmd == "reset-password":
            temp = ACC.temp_password()
            u.password_hash = U.hash_password(temp)
            s.commit()
            U.log(eng, None, "user_password_reset", username=args.name, via="cli")
            print(f"new one-time password for {args.name} (not shown again): {temp}")
        elif args.cmd in ("deactivate", "activate"):
            u.active = args.cmd == "activate"
            s.commit()
            U.log(eng, None, f"user_{args.cmd}", username=args.name, via="cli")
            print(f"{args.name}: {args.cmd}d")
        elif args.cmd == "remove":
            history = s.execute(text("""SELECT (SELECT count(*) FROM house_markets WHERE maker_id = :u)
                                             + (SELECT count(*) FROM house_bets WHERE taker_id = :u)"""),
                                dict(u=u.id)).scalar()
            if history:
                print(f"{args.name} has markets or bets: not removed (racinglines users deactivate {args.name})")
                return 1
            s.delete(u)
            s.commit()
            U.log(eng, None, "user_delete", username=args.name, via="cli")
            print(f"removed {args.name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
