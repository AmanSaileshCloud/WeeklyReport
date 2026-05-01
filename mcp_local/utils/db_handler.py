import os
import bcrypt
from contextlib import contextmanager

_DATABASE_URL = os.environ.get("DATABASE_URL")

# ── Backend selection ────────────────────────────────────────────────────────
# DATABASE_URL set  →  PostgreSQL via Supabase (production)
# DATABASE_URL unset →  SQLite (local development)

if _DATABASE_URL:
    import psycopg2
    import psycopg2.pool

    _pool = psycopg2.pool.SimpleConnectionPool(1, 5, _DATABASE_URL)

    @contextmanager
    def _get_conn():
        conn = _pool.getconn()
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            _pool.putconn(conn)

    def _fetchone(cur) -> dict | None:
        row = cur.fetchone()
        if row is None:
            return None
        return dict(zip([d[0] for d in cur.description], row))

    def _fetchall(cur) -> list[dict]:
        cols = [d[0] for d in cur.description]
        return [dict(zip(cols, row)) for row in cur.fetchall()]

    def _init_db():
        with _get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    CREATE TABLE IF NOT EXISTS users (
                        id       SERIAL PRIMARY KEY,
                        username TEXT NOT NULL UNIQUE,
                        email    TEXT NOT NULL UNIQUE,
                        password TEXT NOT NULL,
                        role     TEXT NOT NULL DEFAULT 'viewer'
                    )
                """)

    def _query(conn, sql, params=()):
        cur = conn.cursor()
        cur.execute(sql, params)
        return cur

    _PH = "%s"  # PostgreSQL placeholder

else:
    import sqlite3

    _DB_PATH = os.environ.get(
        "DB_PATH",
        os.path.join(os.path.dirname(__file__), "..", "users.db"),
    )

    @contextmanager
    def _get_conn():
        conn = sqlite3.connect(_DB_PATH, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def _fetchone(cur) -> dict | None:
        row = cur.fetchone()
        return dict(row) if row else None

    def _fetchall(cur) -> list[dict]:
        return [dict(r) for r in cur.fetchall()]

    def _init_db():
        with _get_conn() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS users (
                    id       INTEGER PRIMARY KEY AUTOINCREMENT,
                    username TEXT    NOT NULL UNIQUE,
                    email    TEXT    NOT NULL UNIQUE,
                    password TEXT    NOT NULL,
                    role     TEXT    NOT NULL DEFAULT 'viewer'
                )
            """)

    def _query(conn, sql, params=()):
        return conn.execute(sql, params)

    _PH = "?"  # SQLite placeholder


_init_db()


# ── Public API (identical regardless of backend) ─────────────────────────────

def get_user_by_email(email: str) -> dict | None:
    with _get_conn() as conn:
        cur = _query(conn, f"SELECT * FROM users WHERE LOWER(email) = LOWER({_PH})", (email,))
        return _fetchone(cur)


def authenticate_user(email: str, password: str) -> bool:
    user = get_user_by_email(email)
    if not user:
        bcrypt.checkpw(b"dummy", bcrypt.hashpw(b"dummy", bcrypt.gensalt()))
        return False
    return bcrypt.checkpw(password.encode(), user["password"].encode())


def verify_duplicate_user(email: str) -> bool:
    with _get_conn() as conn:
        cur = _query(conn, f"SELECT 1 FROM users WHERE LOWER(email) = LOWER({_PH})", (email,))
        return _fetchone(cur) is not None


def save_user(email: str, password: str):
    username = email.split("@")[0].lower().replace(".", "_")
    hashed = bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()
    with _get_conn() as conn:
        _query(
            conn,
            f"INSERT INTO users (username, email, password, role) VALUES ({_PH},{_PH},{_PH},{_PH})",
            (username, email, hashed, "viewer"),
        )


def get_users() -> list[dict]:
    with _get_conn() as conn:
        cur = _query(conn, "SELECT * FROM users")
        return _fetchall(cur)
