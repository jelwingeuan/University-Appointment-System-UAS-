# PostgreSQL Backup and Recovery

UAS does not back up its own database. Use a managed PostgreSQL backup service or an external scheduled job with a least-privilege backup role. Set the recovery-point and recovery-time objectives with the university operator; a backup is useful only if it can be restored.

## Routine backups

Take a PostgreSQL custom-format logical backup at least daily. A reasonable starting retention schedule is 35 daily backups, 12 weekly backups, and 12 monthly backups; adjust it to institutional policy and recovery needs. Keep copies in a separate failure domain, encrypt them at rest (preferably before upload as well as at the storage provider), use TLS for transfer, and keep encryption keys separate from the backup files.

Use a protected `pg_service.conf` entry and permission-restricted `PGPASSFILE` or the deployment's managed identity. Do not put passwords in scripts, command arguments, source control, or this document. For example, with a service named `uas-production`:

```sh
BACKUP_FILE="/secure-staging/uas-$(date -u +%Y%m%dT%H%M%SZ).dump"
pg_dump --format=custom --no-owner --no-privileges \
  --file="$BACKUP_FILE" --dbname="service=uas-production"
pg_restore --list "$BACKUP_FILE" >/dev/null
```

After validating and encrypting the file, transfer it to the protected backup store. Monitor the scheduler, backup age, encryption/upload result, and available storage. A successful `pg_dump` exit alone is not a restore test.

## Restore drill

Perform a periodic drill, such as quarterly, against a disposable database in a separate non-production environment. A restored production backup may contain personal data, so keep the drill environment access-controlled and encrypted as well. Never test a destructive restore against production. Keep the source backup unchanged and record the backup timestamp, migration revision, row counts, and drill result.

1. Obtain and decrypt a backup using the separately managed key. Check its contents with `pg_restore --list`.
2. Create a new empty database in the isolated restore environment. Configure a separate `uas-restore` service; do not point it at production.
3. Restore without `--clean` so the example cannot erase an existing database:

   ```sh
   createdb --maintenance-db="service=uas-restore" uas_restore_drill
   pg_restore --exit-on-error --no-owner --no-privileges \
     --dbname="service=uas-restore dbname=uas_restore_drill" "$BACKUP_FILE"
   ```

4. Point a temporary UAS environment's `DATABASE_URL` at that restored database, then run `flask --app app db current` and `flask --app app db upgrade`. The upgrade should be a no-op for a current backup and apply forward migrations for an older supported backup.
5. Verify key table counts, foreign-key/integrity checks, and expected `alembic_version`. Start UAS only against the isolated restore settings, check `/health` and `/ready`, then smoke-test sign-in and representative student, lecturer, and admin pages using non-production accounts.
6. Record elapsed restore time, issues, and the backup/migration revisions. Remove the disposable database only after the drill is documented and no process is using it.

For an actual incident, restore into a replacement or recovery environment first, validate it, and only then coordinate cutover. Do not overwrite the original backup or use migration downgrade as a substitute for restoring a known-good backup. Keep the old database available until the recovered service and data are verified.
