import os
import sys
from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool
from sqlmodel import SQLModel

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import app.models.content  # noqa: E402,F401  (registra as tabelas no metadata)

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = SQLModel.metadata

database_url = os.environ.get("DATABASE_URL")
if not database_url:
    raise RuntimeError("DATABASE_URL is not set.")
config.set_main_option("sqlalchemy.url", database_url)


def include_object(object, name, type_, reflected, compare_to):
    """Restringe o autogenerate às tabelas deste módulo.

    ``target_metadata`` só registra as 7 tabelas ``content_*`` deste módulo,
    mas o banco (Supabase compartilhado) pode conter tabelas de outros
    módulos (ex.: agendamento). Sem esse filtro, o autogenerate as trataria
    como "extras" e geraria ``op.drop_table(...)`` para elas.
    """
    if type_ == "table" and not (name.startswith("content_") or name == "alembic_version"):
        return False
    return True


def run_migrations_offline() -> None:
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        include_object=include_object,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            include_object=include_object,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
