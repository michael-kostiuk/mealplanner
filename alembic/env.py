import os
import sys
from logging.config import fileConfig

from dotenv import load_dotenv
from sqlalchemy import engine_from_config, pool

from alembic import context

load_dotenv()

# Add the parent directory to sys.path so we can import app
sys.path.append(os.getcwd())

from app.models import Base

# this is the Alembic Config object, which provides
# access to the values within the .ini file in use.
config = context.config

# set the sqlalchemy.url in the configuration to the one in .env
config.set_main_option("sqlalchemy.url", os.getenv("DATABASE_URL"))

# Interpret the config file for Python logging.
# This line sets up loggers basically.
if config.config_file_name is not None:
    # Only configure logging from alembic.ini if we are running from CLI
    # If running from app (which sets up its own logging), skip this.
    # We detect this by checking if 'app' logger is already configured or if we are in a specific context.
    # But simpler: if logging.getLogger().handlers is set, we might skip.
    # However, alembic needs some logging.
    # Let's check if we are running via 'alembic' command or via app.
    # If 'uvicorn' is loaded, we are likely in app.
    if "uvicorn" not in sys.modules:
        fileConfig(config.config_file_name)
    else:
        # We are likely running inside the app.
        # We might want to keep existing logging.
        # But we can allow alembic to configure its loggers if needed,
        # just be careful about root logger.
        # For now, let's skip fileConfig if uvicorn is present to avoid resetting root logger.
        pass

# add your model's MetaData object here
# for 'autogenerate' support
# from myapp import mymodel
# target_metadata = mymodel.Base.metadata
target_metadata = Base.metadata

# other values from the config, defined by the needs of env.py,
# can be acquired:
# my_important_option = config.get_main_option("my_important_option")
# ... etc.


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode.

    This configures the context with just a URL
    and not an Engine, though an Engine is acceptable
    here as well.  By skipping the Engine creation
    we don't even need a DBAPI to be available.

    Calls to context.execute() here emit the given string to the
    script output.

    """
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations in 'online' mode.

    In this scenario we need to create an Engine
    and associate a connection with the context.

    """
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
