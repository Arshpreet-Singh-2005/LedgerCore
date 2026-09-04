"""
LedgerAPI - Database layer
SQLite by default (zero-config). Set DATABASE_URL to point at
Postgres/MySQL in production without changing any other code.

SQLite note: pysqlite's default transaction handling only takes a lock on
the *first write* of a transaction, not on read statements — which means
with_for_update() is silently a no-op on SQLite (SQLAlchemy's SQLite
dialect doesn't emit a FOR UPDATE clause at all, since SQLite has no
native row-level locking). Two threads can both read the same "locked"
row before either writes, causing a lost update on the balance despite
the code looking correct. Postgres/MySQL don't have this problem because
FOR UPDATE genuinely blocks concurrent readers there.

The fix below forces SQLite to acquire its write lock at the *start* of
every transaction (BEGIN IMMEDIATE) instead of deferring it to the first
write. That serializes concurrent transfers for real, matching the
guarantee with_for_update() already provides on Postgres/MySQL — so the
same application code is correctness-safe on both, without a Python-level
lock standing in for the database's own concurrency control.

The 15s "timeout" in connect_args matters just as much as BEGIN IMMEDIATE
itself: SQLite's C driver fails instantly with "database is locked" when
a second transaction can't acquire the write lock, rather than waiting.
The timeout tells it to retry for up to 15s instead, so concurrent
requests queue behind each other (the intended behavior) instead of
erroring out immediately.

expire_on_commit=False matters here too, for a less obvious reason: by
default, SQLAlchemy marks an object's attributes "expired" after commit,
so the next attribute access silently issues a fresh SELECT. Combined
with BEGIN IMMEDIATE, that innocent read would itself acquire the write
lock — turning ordinary post-commit attribute access into unexpected lock
contention. Disabling it keeps reads read-only unless explicitly refreshed.
"""

import os
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker, declarative_base

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./ledger.db")
IS_SQLITE = DATABASE_URL.startswith("sqlite")

connect_args = {"check_same_thread": False, "timeout": 15.0} if IS_SQLITE else {}

engine = create_engine(DATABASE_URL, connect_args=connect_args)

if IS_SQLITE:
    @event.listens_for(engine, "connect")
    def _sqlite_disable_pysqlite_autobegin(dbapi_connection, connection_record):
        # Hand transaction control entirely to the "begin" hook below.
        dbapi_connection.isolation_level = None

    @event.listens_for(engine, "begin")
    def _sqlite_begin_immediate(conn):
        # Acquire the write lock up front so concurrent transfers serialize
        # instead of racing on stale reads.
        conn.exec_driver_sql("BEGIN IMMEDIATE")

SessionLocal = sessionmaker(autocommit=False, autoflush=False, expire_on_commit=False, bind=engine)
Base = declarative_base()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db():
    from app import models  # noqa: F401
    Base.metadata.create_all(bind=engine)
