from collections.abc import Generator
from pathlib import Path

from sqlalchemy import create_engine, event
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from .config import get_settings


class Base(DeclarativeBase):
    pass


settings = get_settings()
if settings.database_url.startswith("sqlite:///"):
    database_path = settings.database_url.removeprefix("sqlite:///")
    if database_path != ":memory:":
        Path(database_path).expanduser().parent.mkdir(parents=True, exist_ok=True)

connect_args = {"check_same_thread": False} if settings.database_url.startswith("sqlite") else {}
engine = create_engine(settings.database_url, connect_args=connect_args)


@event.listens_for(engine, "connect")
def enable_sqlite_foreign_keys(dbapi_connection, _connection_record) -> None:
    if settings.database_url.startswith("sqlite"):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()


SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def run_lightweight_migrations(target_engine) -> None:
    """为已存在的 SQLite 表补列。

    Base.metadata.create_all 只建新表不改旧表，所以新字段需要在这里幂等补上，
    避免存量数据库缺少列时报错。
    """
    if not settings.database_url.startswith("sqlite"):
        return
    from sqlalchemy import inspect, text

    inspector = inspect(target_engine)
    if "channels" not in inspector.get_table_names():
        return
    existing = {column["name"] for column in inspector.get_columns("channels")}
    with target_engine.begin() as connection:
        if "channel_type_other" not in existing:
            connection.execute(text("ALTER TABLE channels ADD COLUMN channel_type_other VARCHAR(80)"))
        if "requires_login" not in existing:
            connection.execute(text("ALTER TABLE channels ADD COLUMN requires_login BOOLEAN NOT NULL DEFAULT 0"))
        if "login_username" not in existing:
            connection.execute(text("ALTER TABLE channels ADD COLUMN login_username VARCHAR(255)"))
        if "login_password" not in existing:
            connection.execute(text("ALTER TABLE channels ADD COLUMN login_password VARCHAR(255)"))
        if "link_type" not in existing:
            connection.execute(text("ALTER TABLE channels ADD COLUMN link_type VARCHAR(8)"))
        if "dr_value" not in existing:
            connection.execute(text("ALTER TABLE channels ADD COLUMN dr_value INTEGER"))
        if "monthly_traffic" not in existing:
            connection.execute(text("ALTER TABLE channels ADD COLUMN monthly_traffic INTEGER"))

    # KeywordCandidate 的 Agent 判断列（与规则判定分开存储）。
    if "keyword_candidates" not in inspector.get_table_names():
        return
    kw_existing = {column["name"] for column in inspector.get_columns("keyword_candidates")}
    with target_engine.begin() as connection:
        if "agent_verdict" not in kw_existing:
            connection.execute(text("ALTER TABLE keyword_candidates ADD COLUMN agent_verdict VARCHAR(20)"))
        if "agent_kd" not in kw_existing:
            connection.execute(text("ALTER TABLE keyword_candidates ADD COLUMN agent_kd INTEGER"))
        if "agent_reason" not in kw_existing:
            connection.execute(text("ALTER TABLE keyword_candidates ADD COLUMN agent_reason TEXT"))
        if "agent_judged_at" not in kw_existing:
            connection.execute(text("ALTER TABLE keyword_candidates ADD COLUMN agent_judged_at DATETIME"))
