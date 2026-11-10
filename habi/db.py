"""Conexión y esquema de SQLite.

Las reglas de integridad que la base de datos puede garantizar por sí misma
se declaran aquí (CHECK, FOREIGN KEY, UNIQUE y triggers), como segunda línea
de defensa detrás de la capa de servicios.
"""

import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

from habi import config

ESQUEMA = """
CREATE TABLE IF NOT EXISTS usuarios (
    id            INTEGER PRIMARY KEY,
    nombre        TEXT NOT NULL UNIQUE,                  -- RF-01: nombre único
    password_hash TEXT NOT NULL,                         -- RNF-SEC-01: solo hash
    creado_en     TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS cuentas (
    id         INTEGER PRIMARY KEY,
    usuario_id INTEGER UNIQUE REFERENCES usuarios(id) ON DELETE RESTRICT,
    tipo       TEXT NOT NULL CHECK (tipo IN ('USUARIO', 'FONDEO')),
    saldo      INTEGER NOT NULL DEFAULT 0 CHECK (typeof(saldo) = 'integer'),  -- RNF-D-01
    creada_en  TEXT NOT NULL,
    CHECK (tipo = 'FONDEO' OR saldo >= 0),               -- RNF-D-05: solo fondeo puede ser negativa
    CHECK ((tipo = 'FONDEO') = (usuario_id IS NULL))     -- fondeo no pertenece a ningún usuario
);

-- Solo puede existir una cuenta de fondeo.
CREATE UNIQUE INDEX IF NOT EXISTS ux_cuenta_fondeo ON cuentas(tipo) WHERE tipo = 'FONDEO';

CREATE TABLE IF NOT EXISTS operaciones (
    id                 INTEGER PRIMARY KEY,
    tipo               TEXT NOT NULL CHECK (tipo IN ('CARGA', 'TRANSFERENCIA')),
    clave_idempotencia TEXT UNIQUE,                      -- RNF-R-03
    monto              INTEGER NOT NULL CHECK (typeof(monto) = 'integer' AND monto > 0),
    creada_en          TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS movimientos (
    id           INTEGER PRIMARY KEY,
    operacion_id INTEGER NOT NULL REFERENCES operaciones(id) ON DELETE RESTRICT,
    cuenta_id    INTEGER NOT NULL REFERENCES cuentas(id) ON DELETE RESTRICT,  -- RNF-D-03
    monto        INTEGER NOT NULL CHECK (typeof(monto) = 'integer' AND monto <> 0),
    creado_en    TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS ix_movimientos_cuenta ON movimientos(cuenta_id, id DESC);

-- RNF-D-04: los movimientos son inmutables.
CREATE TRIGGER IF NOT EXISTS movimientos_sin_update
BEFORE UPDATE ON movimientos
BEGIN
    SELECT RAISE(ABORT, 'Los movimientos no se pueden modificar');
END;

CREATE TRIGGER IF NOT EXISTS movimientos_sin_delete
BEFORE DELETE ON movimientos
BEGIN
    SELECT RAISE(ABORT, 'Los movimientos no se pueden eliminar');
END;
"""


def ahora_iso() -> str:
    """Fecha y hora actual en UTC, formato ISO 8601 (RNF-U-02)."""
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def conectar(ruta: str | Path | None = None) -> sqlite3.Connection:
    """Abre una conexión. Cada hilo debe usar su propia conexión.

    isolation_level=None: las transacciones se controlan explícitamente
    con `transaccion()` para no depender del modo implícito de sqlite3.
    """
    ruta = Path(ruta or config.DB_PATH)
    ruta.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(ruta, timeout=config.DB_TIMEOUT_SEGUNDOS, isolation_level=None)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    return conn


def inicializar(conn: sqlite3.Connection) -> None:
    """Crea las tablas (si no existen) y la cuenta de fondeo del sistema."""
    conn.executescript(ESQUEMA)
    with transaccion(conn):
        conn.execute(
            "INSERT OR IGNORE INTO cuentas (usuario_id, tipo, saldo, creada_en) "
            "VALUES (NULL, 'FONDEO', 0, ?)",
            (ahora_iso(),),
        )


@contextmanager
def transaccion(conn: sqlite3.Connection):
    """Transacción atómica (RNF-R-02).

    BEGIN IMMEDIATE toma el lock de escritura desde el inicio, así dos
    transferencias simultáneas no leen el mismo saldo (RNF-R-04).
    Si algo falla dentro del bloque, se hace ROLLBACK y nada queda a medias.
    """
    conn.execute("BEGIN IMMEDIATE")
    try:
        yield conn
    except BaseException:
        conn.execute("ROLLBACK")
        raise
    else:
        conn.execute("COMMIT")
