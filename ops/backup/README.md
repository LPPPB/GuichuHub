# Backup target boundary

`backup.py` always creates local, transactionally consistent snapshots of both
the business and authentication SQLite databases before any off-host transfer
is considered. The files use distinct `business_*.db` and `auth_*.db` names and
each snapshot must pass SQLite `quick_check`. The application and the Compose
topology do not depend on an object-storage provider.

An optional uploader is a replaceable host-side adapter. It is intentionally
not implemented or invoked by this baseline. A future adapter must:

- read backups from `/srv/kichu/backups` without deleting or rewriting them;
- implement the S3-compatible API using `S3_ENDPOINT_URL`, `S3_BUCKET`,
  `S3_PREFIX`, and `S3_REGION` as deployment configuration;
- obtain access credentials from a protected file or runtime secret binding
  under `/srv/kichu/secrets`, never from Git or command-line arguments;
- require TLS verification, fail closed, and leave the local backup intact;
- record an integrity checksum and upload result without logging credentials.

Provider-specific endpoints and credentials belong only in the external
deployment configuration. Replacing the adapter must not change Flask, React,
the SQLite backup API, or the local backup timer.
