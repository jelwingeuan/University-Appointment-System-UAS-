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
            context.configure(connection=connection, **options)
            with context.begin_transaction():
                context.run_migrations()


run_migrations()
