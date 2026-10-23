from logging.config import fileConfig

from alembic import context
from sqlalchemy import create_engine

from app.models import Base
from app.settings import get_settings

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# Os testes passam a URL do banco de teste por aqui; senão vale DATABASE_URL.
database_url = config.attributes.get("database_url") or get_settings().database_url


def run_migrations_offline() -> None:
    context.configure(url=database_url, target_metadata=Base.metadata, literal_binds=True)
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    engine = create_engine(database_url)
    with engine.connect() as connection:
        context.configure(connection=connection, target_metadata=Base.metadata)
        with context.begin_transaction():
            context.run_migrations()
    engine.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
