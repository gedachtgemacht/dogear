---
name: sql-database
description: SQLite and Postgres practice: schema, constraints, indexes, safe queries, migrations, transactions, backups
triggers: sql, sqlite, postgres, postgresql, mysql, database, databases, datenbank, schema, migration, migrations, n+1, query plan, foreign key, tabelle, abfrage
---
# SQL and databases

1. **Parameterized queries only.** Pass values separately: `cur.execute("SELECT * FROM users WHERE email = ?", (email,))` (SQLite) or `%s` / `$1` (Postgres). Never build SQL with f-strings, `+` or `format`, not even for numbers. Identifiers (table or column names from input) must be checked against a fixed allowlist.
2. **Schema.** One table per entity, a primary key on each, singular or plural names used consistently, `snake_case` columns. Use the narrowest correct types: integers for ids and money in cents, `TEXT`/`TIMESTAMPTZ` for times in UTC. No comma-separated lists in a column; use a child table.
3. **Constraints do the validation.** `NOT NULL`, `UNIQUE`, `CHECK (price_cents >= 0)`, `FOREIGN KEY ... ON DELETE` with a deliberate choice. SQLite: run `PRAGMA foreign_keys = ON` on every connection.
4. **Indexes** on foreign keys and on columns used in `WHERE`, `JOIN` and `ORDER BY` of frequent queries. A composite index follows the order equality columns first, range column last. Skip indexes on tiny tables and on columns with two values. Every index slows writes.
5. **Migrations.** Numbered files (`0003_add_status.sql`), applied once in order, recorded in a `schema_migrations` table, never edited after release. Make each migration run inside a transaction where the engine allows it. Back up before a destructive one.
6. **Transactions.** Group statements that must succeed together. Keep them short, no network calls inside. SQLite: enable WAL (`PRAGMA journal_mode = WAL`) and a `busy_timeout`. Handle the unique-violation error instead of check-then-insert.
7. **N+1.** If a loop runs one query per row, replace it with one `JOIN` or `WHERE id IN (...)`. Select only the columns you need; never `SELECT *` in application code.
8. **Check plans.** Run `EXPLAIN QUERY PLAN` (SQLite) or `EXPLAIN ANALYZE` (Postgres). A full table scan on a big table in a hot query is the thing to fix. Always add `LIMIT` on user-facing lists.
9. **Backups.** SQLite: `sqlite3 db ".backup file"`, not `cp` on a live file. Postgres: `pg_dump`. Restore it once into a scratch database to prove it works.

Avoid: storing passwords in plain text (hash them), deleting rows without a `WHERE` (run it as a `SELECT` first), `float` for money, business logic hidden in triggers nobody documented.

Verify: run the migration on a copy of real data, run the queries with `EXPLAIN`, and test one duplicate insert and one constraint violation.
