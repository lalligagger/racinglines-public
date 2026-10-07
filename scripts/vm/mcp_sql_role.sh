#!/usr/bin/env bash
# The MCP sql tool's own database login (docs/mcp.md "The sql tool's database role"), run as root on the VM:
#
#   sudo bash scripts/vm/mcp_sql_role.sh [status]     # in /opt/racinglines; take `vm.sh backup mcp-sql-role` first
#
# Creates (or updates) the login racinglines_mcp_ro: no superuser, no CREATEROLE, no pg_read_* roles, SELECT on every
# table in the public schema except the hidden ones, and SELECT on tables created later (default privileges for the
# app's role, so a migration's new table is readable without a re-run). Each run sets a fresh password, writes
# RACINGLINES_MCP_SQL_URL to the env file, and restarts racinglines-mcp if it runs. The sql tool then connects as this
# login; every other MCP tool keeps the app's own connection. Undo: delete the env line, restart racinglines-mcp, then
# `DROP OWNED BY racinglines_mcp_ro; DROP ROLE racinglines_mcp_ro;` in each database it was granted on.
#
# DB (default racinglines) picks the database: the role is cluster-wide (staging's racinglines_staging lives in the same
# Postgres container), the grants are per database. Run once per database the sql tool reads.
set -euo pipefail
cd "${APP:-/opt/racinglines}"
ENV_FILE=${ENV_FILE:-/etc/racinglines.env}
DB=${DB:-racinglines}
ROLE=racinglines_mcp_ro
# Must match SQL_HIDDEN in racinglines/mcp/tools.py (tests/test_mcp.py checks it)
HIDDEN="users orders"

psql_() { docker compose exec -T db psql -v ON_ERROR_STOP=1 -X -q -U racinglines -d "$DB" "$@"; }

if [ "${1:-}" = status ]; then
  psql_ -At -c "SELECT 'role ' || rolname || ': superuser=' || rolsuper || ' createrole=' || rolcreaterole || ' bypassrls=' || rolbypassrls
                FROM pg_roles WHERE rolname = '$ROLE'"
  psql_ -At -c "SELECT 'readable tables in $DB: ' || count(*) FROM information_schema.role_table_grants
                WHERE grantee = '$ROLE' AND privilege_type = 'SELECT'"
  for t in $HIDDEN; do
    psql_ -At -c "SELECT '$t readable: ' || has_table_privilege('$ROLE', 'public.$t', 'SELECT')"
  done
  grep -q '^RACINGLINES_MCP_SQL_URL=' "$ENV_FILE" && echo "RACINGLINES_MCP_SQL_URL is set in $ENV_FILE" \
    || echo "RACINGLINES_MCP_SQL_URL is not set in $ENV_FILE: the sql tool uses the app's own login"
  exit 0
fi

PW=$(openssl rand -hex 24)
revokes=""
for t in $HIDDEN; do revokes+="REVOKE ALL ON TABLE public.$t FROM $ROLE; "; done

psql_ -1 <<SQL
DO \$\$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '$ROLE') THEN
    CREATE ROLE $ROLE LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS;
  END IF;
END \$\$;
ALTER ROLE $ROLE WITH LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS PASSWORD '$PW';
ALTER ROLE $ROLE SET default_transaction_read_only = on;
ALTER ROLE $ROLE SET statement_timeout = '10s';
REVOKE pg_read_server_files, pg_read_all_data, pg_read_all_settings, pg_execute_server_program FROM $ROLE;
GRANT CONNECT ON DATABASE $DB TO $ROLE;
GRANT USAGE ON SCHEMA public TO $ROLE;
GRANT SELECT ON ALL TABLES IN SCHEMA public TO $ROLE;
ALTER DEFAULT PRIVILEGES FOR ROLE racinglines IN SCHEMA public GRANT SELECT ON TABLES TO $ROLE;
$revokes
SQL

for t in $HIDDEN; do
  [ "$(psql_ -At -c "SELECT has_table_privilege('$ROLE', 'public.$t', 'SELECT')")" = f ] \
    || { echo "mcp_sql_role: $ROLE can still read $t in $DB; stopping before the env file changes"; exit 1; }
done

# the app's own DATABASE_URL with this login and database swapped in (same host and port)
APP_URL=$(grep -E '^DATABASE_URL=' "$ENV_FILE" | tail -n 1 | cut -d= -f2- | tr -d "\"'")
[ -n "$APP_URL" ] || { echo "mcp_sql_role: no DATABASE_URL in $ENV_FILE"; exit 1; }
URL=$(printf '%s' "$APP_URL" | sed -E "s#//[^@/]*@#//$ROLE:$PW@#; s#/[^/?]*(\?.*)?\$#/$DB\1#")
sed -i -E '/^RACINGLINES_MCP_SQL_URL=/d' "$ENV_FILE"
echo "RACINGLINES_MCP_SQL_URL=$URL" >> "$ENV_FILE"
systemctl try-restart racinglines-mcp 2>/dev/null || true
echo "mcp_sql_role: $ROLE reads $DB without $HIDDEN; RACINGLINES_MCP_SQL_URL written to $ENV_FILE; racinglines-mcp restarted if it was running"
