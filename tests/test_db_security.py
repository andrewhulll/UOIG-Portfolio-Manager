"""Tests for db security against SQL injections."""

import sqlite3
import pytest
from src.model import db
from src.model.schema import create_schema, truncate_all, _ADDED_COLUMNS

def test_quote_ident():
    assert db.quote_ident("test") == '"test"'
    assert db.quote_ident("test table") == '"test table"'
    assert db.quote_ident('test"table') == '"test""table"'
    assert db.quote_ident('"test"') == '"""test"""'
    assert db.quote_ident("'; DROP TABLE test;") == '"' + "'; DROP TABLE test;" + '"'

def test_upsert_sql_sqlite():
    conn = sqlite3.connect(":memory:")

    # Standard query
    sql = db.upsert_sql(conn, "my_table", ["id", "name"], ["id"])
    assert sql == 'INSERT OR REPLACE INTO "my_table" ("id", "name") VALUES (?, ?)'

    # Injection attempt in table name
    sql = db.upsert_sql(conn, "table\" (injection)", ["id"], ["id"])
    assert sql == 'INSERT OR REPLACE INTO "table"" (injection)" ("id") VALUES (?)'

def test_upsert_sql_pg():
    class DummyPgConn:
        pass
    DummyPgConn.__module__ = "psycopg"
    conn = DummyPgConn()

    # Standard query
    sql = db.upsert_sql(conn, "my_table", ["id", "name"], ["id"])
    assert sql == 'INSERT INTO "my_table" ("id", "name") VALUES (%s, %s) ON CONFLICT ("id") DO UPDATE SET "name"=EXCLUDED."name"'

    # Injection attempt
    sql = db.upsert_sql(conn, "table\" injection", ["id", "na\"me"], ["id"])
    assert sql == 'INSERT INTO "table"" injection" ("id", "na""me") VALUES (%s, %s) ON CONFLICT ("id") DO UPDATE SET "na""me"=EXCLUDED."na""me"'

def test_schema_truncate_all_safe():
    conn = sqlite3.connect(":memory:")
    create_schema(conn)
    # This shouldn't raise any syntax errors and shouldn't fail
    truncate_all(conn)
