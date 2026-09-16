#!/bin/sh
set -eu

read_secret() { tr -d '\r\n' < "/run/secrets/$1"; }
psql --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" \
  --set=api_password="$(read_secret postgres_api_password)" \
  --set=worker_password="$(read_secret postgres_worker_password)" \
  --set=migration_password="$(read_secret postgres_migration_password)" \
  --set=backup_password="$(read_secret postgres_backup_password)" <<'SQL'
CREATE SCHEMA IF NOT EXISTS app;
CREATE SCHEMA IF NOT EXISTS auth;
CREATE ROLE kichu_api LOGIN PASSWORD :'api_password';
CREATE ROLE kichu_worker LOGIN PASSWORD :'worker_password';
CREATE ROLE kichu_migration LOGIN PASSWORD :'migration_password';
CREATE ROLE kichu_backup LOGIN PASSWORD :'backup_password';
ALTER SCHEMA app OWNER TO kichu_migration;
ALTER SCHEMA auth OWNER TO kichu_migration;
GRANT CONNECT ON DATABASE kichu TO kichu_api, kichu_worker, kichu_migration, kichu_backup;
GRANT USAGE ON SCHEMA app, auth TO kichu_api, kichu_worker, kichu_backup;
GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA app, auth TO kichu_api, kichu_worker;
GRANT SELECT ON ALL TABLES IN SCHEMA app, auth TO kichu_backup;
ALTER DEFAULT PRIVILEGES FOR ROLE kichu_migration IN SCHEMA app GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO kichu_api, kichu_worker;
ALTER DEFAULT PRIVILEGES FOR ROLE kichu_migration IN SCHEMA auth GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO kichu_api, kichu_worker;
ALTER DEFAULT PRIVILEGES FOR ROLE kichu_migration IN SCHEMA app GRANT SELECT ON TABLES TO kichu_backup;
ALTER DEFAULT PRIVILEGES FOR ROLE kichu_migration IN SCHEMA auth GRANT SELECT ON TABLES TO kichu_backup;
SQL
