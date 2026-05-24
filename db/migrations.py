import os
from config import Config
from db.models import db, RegisteredUser, GeneratedPlan, CreativeBrief, BatchJob

# Versioned migration registry
_migrations = []


def _migration(number):
    """Decorator to register a numbered migration function."""
    def decorator(func):
        _migrations.append((number, func))
        return func
    return decorator


@_migration(1)
def _create_initial_tables():
    """Migration 1: Create initial tables and indexes."""
    db.create_tables([RegisteredUser], safe=True)


@_migration(2)
def _create_plan_tables():
    """Migration 2: Add GeneratedPlan for plan persistence."""
    db.create_tables([GeneratedPlan], safe=True)
    db.execute_sql(
        "CREATE INDEX IF NOT EXISTS idx_plan_created ON generatedplan(created_at DESC);"
    )


@_migration(3)
def _add_plan_rating():
    """Migration 3: Add rating + performance_note for data flywheel."""
    db.execute_sql(
        "ALTER TABLE generatedplan ADD COLUMN rating INTEGER DEFAULT NULL;"
    )
    db.execute_sql(
        "ALTER TABLE generatedplan ADD COLUMN performance_note TEXT DEFAULT '';"
    )
    db.execute_sql(
        "CREATE INDEX IF NOT EXISTS idx_plan_rating ON generatedplan(rating);"
    )


@_migration(4)
def _add_creative_brief():
    """Migration 4: Add creative_brief for structured creative pipeline."""
    db.execute_sql(
        "ALTER TABLE generatedplan ADD COLUMN creative_brief TEXT DEFAULT '';"
    )


@_migration(5)
def _create_brief_and_batch_tables():
    """Migration 5: Create CreativeBrief and BatchJob tables."""
    from peewee import IntegrityError, OperationalError

    # If tables exist with old schema (INTEGER id PK instead of VARCHAR brief_id/job_id),
    # drop and recreate — SQLite doesn't support ALTER TABLE ADD COLUMN with UNIQUE.
    for table, pk_col in [("creativebrief", "brief_id"), ("batchjob", "job_id")]:
        try:
            cols = [row[1] for row in db.execute_sql(f"PRAGMA table_info({table});").fetchall()]
        except OperationalError:
            continue
        if cols and pk_col not in cols:
            db.execute_sql(f"DROP TABLE IF EXISTS {table};")

    try:
        db.create_tables([CreativeBrief, BatchJob], safe=True)
    except IntegrityError:
        pass

    _ensure_columns("creativebrief", [
        ("brief_id", "VARCHAR(32) UNIQUE"),
        ("industry", "VARCHAR(32)"),
        ("product_name", "VARCHAR(128) DEFAULT ''"),
        ("product_analysis", "TEXT"),
        ("creative_brief", "TEXT"),
        ("image_paths", "TEXT"),
        ("scene_images", "TEXT DEFAULT '[]'"),
        ("status", "VARCHAR(16) DEFAULT 'draft'"),
        ("created_at", "DATETIME"),
        ("updated_at", "DATETIME"),
    ])
    _ensure_columns("batchjob", [
        ("job_id", "VARCHAR(32) UNIQUE"),
        ("brief_id", "INTEGER"),
        ("status", "VARCHAR(16) DEFAULT 'pending'"),
        ("progress", "INTEGER DEFAULT 0"),
        ("message", "VARCHAR(256) DEFAULT ''"),
        ("input_config", "TEXT"),
        ("output_summary", "TEXT DEFAULT '{}'"),
        ("output_files", "TEXT DEFAULT '[]'"),
        ("created_at", "DATETIME"),
        ("updated_at", "DATETIME"),
        ("completed_at", "DATETIME"),
    ])

    db.execute_sql(
        "CREATE INDEX IF NOT EXISTS idx_brief_created ON creativebrief(created_at DESC);"
    )
    db.execute_sql(
        "CREATE INDEX IF NOT EXISTS idx_brief_status ON creativebrief(status);"
    )
    db.execute_sql(
        "CREATE INDEX IF NOT EXISTS idx_job_created ON batchjob(created_at DESC);"
    )
    db.execute_sql(
        "CREATE INDEX IF NOT EXISTS idx_job_status ON batchjob(status);"
    )


def _ensure_columns(table: str, columns: list[tuple[str, str]]):
    """Add any missing columns to a table. Columns is list of (name, type_spec)."""
    import sqlite3
    from peewee import OperationalError
    try:
        existing = [row[1] for row in db.execute_sql(f"PRAGMA table_info({table});").fetchall()]
    except OperationalError:
        return  # Table doesn't exist yet — create_tables above will handle it

    for col_name, col_type in columns:
        if col_name not in existing:
            try:
                db.execute_sql(f"ALTER TABLE {table} ADD COLUMN {col_name} {col_type};")
            except (OperationalError, sqlite3.OperationalError):
                pass


def init_db():
    """Initialize database, create directories, and apply pending migrations."""
    # Ensure all required directories exist (DATA_DIR first — fixes missing data/ bug)
    os.makedirs(Config.DATA_DIR, exist_ok=True)
    os.makedirs(Config.UPLOADS_DIR, exist_ok=True)
    os.makedirs(Config.PROCESSED_DIR, exist_ok=True)
    os.makedirs(Config.SCENES_DIR, exist_ok=True)
    os.makedirs(os.path.join(Config.SCENES_DIR, "custom"), exist_ok=True)
    os.makedirs(Config.VIDEOS_DIR, exist_ok=True)

    db.init(Config.DATABASE_PATH)

    # WAL mode for better concurrent read/write performance
    db.execute_sql("PRAGMA journal_mode=WAL;")

    # Create schema version tracking table
    db.execute_sql(
        "CREATE TABLE IF NOT EXISTS schema_version ("
        "  version INTEGER PRIMARY KEY,"
        "  applied_at TEXT NOT NULL DEFAULT (datetime('now'))"
        ");"
    )

    # Determine which migrations have already been applied
    cursor = db.execute_sql("SELECT COALESCE(MAX(version), 0) FROM schema_version;")
    last_version = cursor.fetchone()[0]

    # Apply any pending migrations in order
    _migrations.sort(key=lambda x: x[0])
    for number, func in _migrations:
        if number > last_version:
            func()
            db.execute_sql(
                "INSERT OR REPLACE INTO schema_version (version, applied_at) "
                "VALUES (?, datetime('now'));",
                (number,)
            )
