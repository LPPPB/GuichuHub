#!/bin/sh
set -eu

read_secret() {
  value="$(tr -d '\r\n' < "/run/secrets/$1")" || return 1
  [ -n "$value" ] || return 1
  printf '%s' "$value"
}
KICHU_POSTGRES_API_PASSWORD="$(read_secret postgres_api_password)"
KICHU_POSTGRES_WORKER_PASSWORD="$(read_secret postgres_worker_password)"
KICHU_POSTGRES_MIGRATION_PASSWORD="$(read_secret postgres_migration_password)"
KICHU_POSTGRES_BACKUP_PASSWORD="$(read_secret postgres_backup_password)"
export KICHU_POSTGRES_API_PASSWORD KICHU_POSTGRES_WORKER_PASSWORD
export KICHU_POSTGRES_MIGRATION_PASSWORD KICHU_POSTGRES_BACKUP_PASSWORD
psql --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" \
  <<'SQL'
\getenv api_password KICHU_POSTGRES_API_PASSWORD
\getenv worker_password KICHU_POSTGRES_WORKER_PASSWORD
\getenv migration_password KICHU_POSTGRES_MIGRATION_PASSWORD
\getenv backup_password KICHU_POSTGRES_BACKUP_PASSWORD
CREATE ROLE kichu_api LOGIN PASSWORD :'api_password';
CREATE ROLE kichu_worker LOGIN PASSWORD :'worker_password';
CREATE ROLE kichu_migration LOGIN PASSWORD :'migration_password';
CREATE ROLE kichu_backup LOGIN PASSWORD :'backup_password';
GRANT CONNECT ON DATABASE kichu TO kichu_api, kichu_worker, kichu_migration, kichu_backup;
REVOKE TEMPORARY ON DATABASE kichu FROM PUBLIC;
GRANT CREATE, TEMPORARY ON DATABASE kichu TO kichu_migration;
SQL
unset KICHU_POSTGRES_API_PASSWORD KICHU_POSTGRES_WORKER_PASSWORD \
  KICHU_POSTGRES_MIGRATION_PASSWORD KICHU_POSTGRES_BACKUP_PASSWORD
