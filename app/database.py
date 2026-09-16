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
    if "target_sites" in inspector.get_table_names():
        site_existing = {column["name"] for column in inspector.get_columns("target_sites")}
        site_columns = {
            "author_name": "VARCHAR(200)",
            "email": "VARCHAR(320)",
            "tagline": "VARCHAR(300)",
            "short_description": "TEXT",
            "medium_description": "TEXT",
            "long_description": "TEXT",
            "keywords": "TEXT",
        }
        with target_engine.begin() as connection:
            for column_name, column_type in site_columns.items():
                if column_name not in site_existing:
                    connection.execute(
                        text(f"ALTER TABLE target_sites ADD COLUMN {column_name} {column_type}")
                    )

    if "submissions" in inspector.get_table_names():
        submission_existing = {column["name"] for column in inspector.get_columns("submissions")}
        if "backlink_record_id" not in submission_existing:
            with target_engine.begin() as connection:
                connection.execute(text("ALTER TABLE submissions ADD COLUMN backlink_record_id INTEGER"))
            inspector.clear_cache()

    if "backlink_records" in inspector.get_table_names():
        record_existing = {column["name"] for column in inspector.get_columns("backlink_records")}
        record_columns = {
            "target_url": "VARCHAR(2048)",
            "link_rel": "TEXT",
            "first_seen_at": "DATETIME",
            "last_verified_at": "DATETIME",
            "origin": "VARCHAR(30)",
        }
        with target_engine.begin() as connection:
            for column_name, column_type in record_columns.items():
                if column_name not in record_existing:
                    connection.execute(
                        text(f"ALTER TABLE backlink_records ADD COLUMN {column_name} {column_type}")
                    )
            if "method" in record_existing:
                connection.execute(text(
                    "UPDATE backlink_records SET origin = 'automation' "
                    "WHERE origin IS NULL AND method = 'auto'"
                ))
            connection.execute(text(
                "UPDATE backlink_records SET origin = 'manual' WHERE origin IS NULL"
            ))
            inspector.clear_cache()
            table_names = set(inspector.get_table_names())
            if "submission_batch_items" in table_names:
                connection.execute(text(
                    "UPDATE backlink_records SET origin = 'batch' "
                    "WHERE id IN (SELECT record_id FROM submission_batch_items WHERE record_id IS NOT NULL)"
                ))
            if "submissions" in table_names and "backlink_record_id" in {
                column["name"] for column in inspector.get_columns("submissions")
            }:
                connection.execute(text(
                    "UPDATE backlink_records SET origin = 'extension_verified' "
                    "WHERE id IN (SELECT backlink_record_id FROM submissions WHERE backlink_record_id IS NOT NULL)"
                ))

    if "channels" not in inspector.get_table_names():
        return
    existing = {column["name"] for column in inspector.get_columns("channels")}
    with target_engine.begin() as connection:
        if "channel_type_other" not in existing:
            connection.execute(text("ALTER TABLE channels ADD COLUMN channel_type_other VARCHAR(80)"))
        if "requires_login" not in existing:
            connection.execute(text("ALTER TABLE channels ADD COLUMN requires_login BOOLEAN NOT NULL DEFAULT 0"))
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
        if "last_dispatched_at" not in kw_existing:
            connection.execute(text("ALTER TABLE keyword_candidates ADD COLUMN last_dispatched_at DATETIME"))

    # KeywordSource 的基线标记列。
    # is_initialized：False=下次抓取走首次基线模式（只建指纹不计新增）；True=已基准化走增量。
    if "keyword_sources" not in inspector.get_table_names():
        return
    src_existing = {column["name"] for column in inspector.get_columns("keyword_sources")}
    with target_engine.begin() as connection:
        if "is_initialized" not in src_existing:
            # 先加列，默认 0（未初始化）；存量来源在下一行统一回填为已基准化。
            connection.execute(text("ALTER TABLE keyword_sources ADD COLUMN is_initialized BOOLEAN NOT NULL DEFAULT 0"))
            # 存量来源此前已经抓过、已有指纹数据，标记为已基准化，下次抓取照常增量计新增；
            # 只有此后新增的来源才从 False 起步、首次抓取建基线。
            connection.execute(text("UPDATE keyword_sources SET is_initialized = 1"))


def migrate_legacy_channel_credentials(target_engine) -> int:
    """把旧 channels 明文账号密码迁入 ChannelCredential，并清空明文列。"""
    from sqlalchemy import inspect, text

    inspector = inspect(target_engine)
    tables = set(inspector.get_table_names())
    if "channels" not in tables or "channel_credentials" not in tables:
        return 0
    channel_columns = {column["name"] for column in inspector.get_columns("channels")}
    if not {"login_username", "login_password"} <= channel_columns:
        return 0

    from .models import now_local
    from .security import CredentialCipher

    cipher = CredentialCipher()
    migrated = 0
    with target_engine.begin() as connection:
        legacy_rows = connection.execute(text(
            "SELECT id, login_username, login_password FROM channels "
            "WHERE login_username IS NOT NULL OR login_password IS NOT NULL"
        )).mappings().all()
        for row in legacy_rows:
            existing = connection.execute(
                text(
                    "SELECT id, username, encrypted_password FROM channel_credentials "
                    "WHERE channel_id = :channel_id"
                ),
                {"channel_id": row["id"]},
            ).mappings().first()
            username = (row["login_username"] or "").strip() or None
            password = row["login_password"] or None
            encrypted_password = cipher.encrypt(password) if password else None
            if existing:
                connection.execute(
                    text(
                        "UPDATE channel_credentials SET "
                        "username = COALESCE(username, :username), "
                        "encrypted_password = COALESCE(encrypted_password, :encrypted_password), "
                        "updated_at = :updated_at WHERE id = :credential_id"
                    ),
                    {
                        "username": username,
                        "encrypted_password": encrypted_password,
                        "updated_at": now_local().isoformat(),
                        "credential_id": existing["id"],
                    },
                )
            else:
                connection.execute(
                    text(
                        "INSERT INTO channel_credentials "
                        "(channel_id, username, encrypted_password, encrypted_extra_fields, updated_at) "
                        "VALUES (:channel_id, :username, :encrypted_password, NULL, :updated_at)"
                    ),
                    {
                        "channel_id": row["id"],
                        "username": username,
                        "encrypted_password": encrypted_password,
                        "updated_at": now_local().isoformat(),
                    },
                )
            connection.execute(
                text(
                    "UPDATE channels SET login_username = NULL, login_password = NULL WHERE id = :channel_id"
                ),
                {"channel_id": row["id"]},
            )
            migrated += 1
    return migrated
