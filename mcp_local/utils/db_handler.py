import os
import uuid
import logging
import bcrypt
import psycopg2
import psycopg2.pool
from contextlib import contextmanager
from datetime import datetime, timedelta

def _get_database_url() -> str:
    url = os.environ.get("DATABASE_URL")
    if not url:
        raise RuntimeError(
            "DATABASE_URL is not set. Add it to your Streamlit secrets."
        )
    return url

_pool = None

def _get_pool():
    global _pool
    if _pool is None:
        _pool = psycopg2.pool.SimpleConnectionPool(1, 5, _get_database_url())
    return _pool

@contextmanager
def _get_conn():
    pool = _get_pool()
    conn = pool.getconn()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        pool.putconn(conn)

def _fetchone(cur) -> dict | None:
    row = cur.fetchone()
    if row is None:
        return None
    return dict(zip([d[0] for d in cur.description], row))

def _fetchall(cur) -> list[dict]:
    cols = [d[0] for d in cur.description]
    return [dict(zip(cols, row)) for row in cur.fetchall()]

def _query(conn, sql, params=()):
    cur = conn.cursor()
    cur.execute(sql, params)
    return cur

_PH = "%s"

try:
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
            cur.execute("""
                CREATE TABLE IF NOT EXISTS report_snapshots (
                    id               SERIAL PRIMARY KEY,
                    date_start       TEXT NOT NULL,
                    date_end         TEXT NOT NULL UNIQUE,
                    total            INTEGER,
                    sla_violated     INTEGER,
                    sla_rate         REAL,
                    resolution_rate  REAL,
                    escalation_rate  REAL,
                    resolved_count   INTEGER,
                    escalated_count  INTEGER,
                    saved_at         TIMESTAMPTZ DEFAULT NOW()
                )
            """)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS report_csv (
                    id         SERIAL PRIMARY KEY,
                    data       BYTEA NOT NULL,
                    uploaded_at TIMESTAMPTZ DEFAULT NOW()
                )
            """)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS session_tokens (
                    token      TEXT PRIMARY KEY,
                    email      TEXT NOT NULL,
                    expires_at TIMESTAMPTZ NOT NULL,
                    created_at TIMESTAMPTZ DEFAULT NOW()
                )
            """)
except Exception as e:
    logging.error(f"Database init failed: {e}")


# ── Public API ───────────────────────────────────────────────────────────────

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
        cur = _query(conn, "SELECT id, username, email, role FROM users")
        return _fetchall(cur)


def set_user_role(email: str, role: str):
    if role not in ("admin", "viewer"):
        raise ValueError("Role must be 'admin' or 'viewer'")
    with _get_conn() as conn:
        _query(conn, f"UPDATE users SET role = {_PH} WHERE LOWER(email) = LOWER({_PH})", (role, email))


def load_snapshot(exclude_date_end: str | None = None) -> dict:
    with _get_conn() as conn:
        if exclude_date_end:
            cur = _query(conn, f"SELECT * FROM report_snapshots WHERE date_end != {_PH} ORDER BY saved_at DESC LIMIT 1", (exclude_date_end,))
        else:
            cur = _query(conn, "SELECT * FROM report_snapshots ORDER BY saved_at DESC LIMIT 1")
        row = _fetchone(cur)
        return row if row else {}


def save_snapshot(date_start: str, date_end: str, total: int, sla_violated: int,
                  sla_rate: float, resolution_rate: float, escalation_rate: float,
                  resolved_count: int, escalated_count: int):
    with _get_conn() as conn:
        _query(conn, f"""
            INSERT INTO report_snapshots
                (date_start, date_end, total, sla_violated, sla_rate, resolution_rate, escalation_rate, resolved_count, escalated_count)
            VALUES ({_PH},{_PH},{_PH},{_PH},{_PH},{_PH},{_PH},{_PH},{_PH})
            ON CONFLICT (date_end) DO UPDATE SET
                total           = EXCLUDED.total,
                sla_violated    = EXCLUDED.sla_violated,
                sla_rate        = EXCLUDED.sla_rate,
                resolution_rate = EXCLUDED.resolution_rate,
                escalation_rate = EXCLUDED.escalation_rate,
                resolved_count  = EXCLUDED.resolved_count,
                escalated_count = EXCLUDED.escalated_count,
                saved_at        = NOW()
        """, (str(date_start), str(date_end), int(total), int(sla_violated), float(sla_rate),
              float(resolution_rate), float(escalation_rate), int(resolved_count), int(escalated_count)))


def upload_report_csv(file_bytes: bytes) -> None:
    with _get_conn() as conn:
        _query(conn, "DELETE FROM report_csv")
        _query(conn, f"INSERT INTO report_csv (data) VALUES ({_PH})", (psycopg2.Binary(file_bytes),))


def download_report_csv() -> bytes | None:
    with _get_conn() as conn:
        cur = _query(conn, "SELECT data FROM report_csv ORDER BY uploaded_at DESC LIMIT 1")
        row = _fetchone(cur)
        if row is None:
            return None
        return bytes(row["data"])


def create_session_token(email: str) -> str:
    token = str(uuid.uuid4())
    expires_at = datetime.utcnow() + timedelta(days=30)
    with _get_conn() as conn:
        _query(conn, f"DELETE FROM session_tokens WHERE email = {_PH}", (email,))
        _query(conn, f"INSERT INTO session_tokens (token, email, expires_at) VALUES ({_PH},{_PH},{_PH})",
               (token, email, expires_at))
    return token


def get_user_by_token(token: str) -> dict | None:
    with _get_conn() as conn:
        cur = _query(conn, f"""
            SELECT u.* FROM users u
            JOIN session_tokens st ON LOWER(u.email) = LOWER(st.email)
            WHERE st.token = {_PH} AND st.expires_at > NOW()
        """, (token,))
        return _fetchone(cur)


def delete_session_token(token: str) -> None:
    with _get_conn() as conn:
        _query(conn, f"DELETE FROM session_tokens WHERE token = {_PH}", (token,))
