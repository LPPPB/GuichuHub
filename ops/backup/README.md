# Backup target boundary

`backup_postgres.py` creates a PostgreSQL custom-format dump with `pg_dump`,
records a SHA-256 checksum and release metadata, and verifies the result with
`pg_restore --list`. PostgreSQL is the sole production persistence system, so
there is no runtime SQLite or mutable-JSON backup path.

The optional systemd timer invokes the Compose maintenance `backup` service.
It never deletes the source database or existing dumps. Restore drills use
`restore_drill.py` and must target a new database whose name begins with
`kichu_restore_drill_`; they never overwrite the production database.

An optional off-host uploader is a replaceable host-side adapter. It is not
implemented or invoked by this baseline. A future adapter must:

- read backups from `/srv/kichu/backups` without deleting or rewriting them;
- implement a portable S3-compatible API using deployment configuration;
- obtain credentials from protected files or runtime secret bindings, never
  from Git or command-line arguments;
- require TLS verification, fail closed, and leave the local backup intact;
- preserve the checksum and manifest without logging credentials.

Provider-specific endpoints and credentials belong only in external deployment
configuration. Replacing an uploader must not change Flask, React, PostgreSQL
backup commands, or the local backup timer.
