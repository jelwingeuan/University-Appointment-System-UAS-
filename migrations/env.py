"""Run Alembic against the engine configured by the application factory."""

from alembic import context
from flask import current_app

database = current_app.extensions["migrate"].db
metadata = database.metadata


def run_migrations():
    options = {
        "target_metadata": metadata,
        "compare_type": True,
        "render_as_batch": database.engine.dialect.name == "sqlite",
    }
    if context.is_offline_mode():
        context.configure(
            url=database.engine.url.render_as_string(hide_password=False),
            literal_binds=True,
            **options,
        )
        with context.begin_transaction():
            context.run_migrations()
    else:
        with database.engine.connect() as connection:
            sqlite = connection.dialect.name == "sqlite"
            sqlite_dbapi = connection.connection.driver_connection if sqlite else None
            if sqlite:
                # SQLite cannot rebuild referenced tables while FK checks are enabled.
                sqlite_dbapi.execute("PRAGMA foreign_keys=OFF")
            context.configure(connection=connection, **options)
            try:
                with context.begin_transaction():
                    context.run_migrations()
                    if sqlite:
                        violations = sqlite_dbapi.execute("PRAGMA foreign_key_check").fetchall()
                        if violations:
                            raise RuntimeError(
                                f"SQLite migration left {len(violations)} foreign-key violation(s)"
                            )
            finally:
                if sqlite:
                    sqlite_dbapi.execute("PRAGMA foreign_keys=ON")


run_migrations()
