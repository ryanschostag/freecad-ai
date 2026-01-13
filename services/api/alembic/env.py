from logging.config import fileConfig
from sqlalchemy import engine_from_config, pool
from alembic import context
import logging
import os
config = context.config
if config.config_file_name:
    try:
        fileConfig(config.config_file_name)
    except KeyError:
        # alembic.ini has no logging sections; fall back to default logging
        logging.basicConfig(level=logging.INFO)
from app.models import Base
target_metadata = Base.metadata
def run_migrations_offline():
    url = os.environ.get("DATABASE_URL", config.get_main_option("sqlalchemy.url"))
    context.configure(url=url, target_metadata=target_metadata, literal_binds=True)
    with context.begin_transaction():
        context.run_migrations()
def run_migrations_online():
    url = os.environ.get("DATABASE_URL", config.get_main_option("sqlalchemy.url"))
    cfg = config.get_section(config.config_ini_section)
    cfg["sqlalchemy.url"] = url
    connectable = engine_from_config(cfg, prefix="sqlalchemy.", poolclass=pool.NullPool)
    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()
if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
