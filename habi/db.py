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

# La tabla cuentas se define aparte porque la migración (ver migrar_cuentas) la
# vuelve a crear con otro nombre. Tipos de cuenta:
#   USUARIO  -> cuenta personal, pertenece a un usuario
#   FONDEO   -> cuenta única del sistema que origina las cargas simuladas
#   BOLSILLO -> cuenta de una Juntia (bolsillo compartido); no pertenece a un solo usuario
TABLA_CUENTAS = """
CREATE TABLE IF NOT EXISTS {nombre} (
    id         INTEGER PRIMARY KEY,
    usuario_id INTEGER UNIQUE REFERENCES usuarios(id) ON DELETE RESTRICT,
    tipo       TEXT NOT NULL CHECK (tipo IN ('USUARIO', 'FONDEO', 'BOLSILLO')),
    saldo      INTEGER NOT NULL DEFAULT 0 CHECK (typeof(saldo) = 'integer'),  -- RNF-D-01
    creada_en  TEXT NOT NULL,
    CHECK (tipo = 'FONDEO' OR saldo >= 0),                -- RNF-D-05: solo fondeo puede ser negativa
    CHECK ((tipo = 'USUARIO') = (usuario_id IS NOT NULL)) -- solo las cuentas personales tienen dueño
);
"""

# Solo puede existir una cuenta de fondeo.
INDICE_FONDEO = "CREATE UNIQUE INDEX IF NOT EXISTS ux_cuenta_fondeo ON cuentas(tipo) WHERE tipo = 'FONDEO';"

ESQUEMA = """
CREATE TABLE IF NOT EXISTS usuarios (
    id            INTEGER PRIMARY KEY,
    nombre        TEXT NOT NULL UNIQUE,                  -- RF-01: nombre único
    password_hash TEXT NOT NULL,                         -- RNF-SEC-01: solo hash
    creado_en     TEXT NOT NULL
);
""" + TABLA_CUENTAS.format(nombre="cuentas") + INDICE_FONDEO + """

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

-- RF-02 / RNF-SEC-01: sesiones abiertas. La cookie firmada solo guarda el token;
-- al cerrar sesión se borra la fila y la cookie vieja deja de servir.
CREATE TABLE IF NOT EXISTS sesiones (
    token      TEXT PRIMARY KEY,
    usuario_id INTEGER NOT NULL REFERENCES usuarios(id),
    expira_en  TEXT NOT NULL
);

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

-- ---------- Juntia: bolsillos compartidos ----------

-- Cada bolsillo tiene su propia cuenta de tipo BOLSILLO: el dinero se mueve con
-- las mismas operaciones y movimientos que las transferencias.
CREATE TABLE IF NOT EXISTS bolsillos (
    id         INTEGER PRIMARY KEY,
    cuenta_id  INTEGER NOT NULL UNIQUE REFERENCES cuentas(id) ON DELETE RESTRICT,
    nombre     TEXT NOT NULL,
    meta       INTEGER NOT NULL CHECK (typeof(meta) = 'integer' AND meta > 0),
    creador_id INTEGER NOT NULL REFERENCES usuarios(id),
    creado_en  TEXT NOT NULL
);

-- Estado de cada persona en un bolsillo. Solo los ACTIVO ven el saldo y operan.
CREATE TABLE IF NOT EXISTS miembros_bolsillo (
    bolsillo_id    INTEGER NOT NULL REFERENCES bolsillos(id),
    usuario_id     INTEGER NOT NULL REFERENCES usuarios(id),
    estado         TEXT NOT NULL CHECK (estado IN ('INVITADO', 'ACTIVO', 'RECHAZADO', 'SALIO')),
    invitado_por   INTEGER REFERENCES usuarios(id),  -- NULL para quien creó el bolsillo
    actualizado_en TEXT NOT NULL,
    PRIMARY KEY (bolsillo_id, usuario_id)
);

-- Propuestas de retiro. Mientras están PENDIENTE su monto queda reservado.
CREATE TABLE IF NOT EXISTS retiros (
    id            INTEGER PRIMARY KEY,
    bolsillo_id   INTEGER NOT NULL REFERENCES bolsillos(id),
    proponente_id INTEGER NOT NULL REFERENCES usuarios(id),
    destino_id    INTEGER NOT NULL REFERENCES usuarios(id),
    monto         INTEGER NOT NULL CHECK (typeof(monto) = 'integer' AND monto > 0),
    motivo        TEXT NOT NULL DEFAULT '',
    estado        TEXT NOT NULL CHECK (estado IN ('PENDIENTE', 'EJECUTADO', 'RECHAZADO', 'EXPIRADO')),
    operacion_id  INTEGER REFERENCES operaciones(id),  -- la transferencia, si se ejecutó
    creado_en     TEXT NOT NULL,
    expira_en     TEXT NOT NULL,
    cerrado_en    TEXT
);

CREATE INDEX IF NOT EXISTS ix_retiros_bolsillo ON retiros(bolsillo_id, estado);

-- Una fila por cada miembro activo al momento de proponer el retiro.
-- voto NULL = todavía no ha votado.
CREATE TABLE IF NOT EXISTS votos_retiro (
    retiro_id  INTEGER NOT NULL REFERENCES retiros(id),
    usuario_id INTEGER NOT NULL REFERENCES usuarios(id),
    voto       TEXT CHECK (voto IN ('A_FAVOR', 'EN_CONTRA')),
    votado_en  TEXT,
    PRIMARY KEY (retiro_id, usuario_id)
);
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
    """Crea las tablas (si no existen), migra bases viejas y crea la cuenta de fondeo."""
    conn.executescript(ESQUEMA)
    migrar_cuentas(conn)
    with transaccion(conn):
        conn.execute(
            "INSERT OR IGNORE INTO cuentas (usuario_id, tipo, saldo, creada_en) "
            "VALUES (NULL, 'FONDEO', 0, ?)",
            (ahora_iso(),),
        )


def migrar_cuentas(conn: sqlite3.Connection) -> None:
    """Migración para Juntia: permite el tipo 'BOLSILLO' en una base creada antes.

    SQLite no deja cambiar un CHECK con ALTER TABLE, así que se sigue el
    procedimiento recomendado por SQLite: crear la tabla nueva, copiar todas las
    filas (mismos id, saldos y fechas), borrar la vieja y renombrar la nueva.
    Todo va en una transacción: si algo falla, la base queda como estaba.
    Si la tabla ya acepta 'BOLSILLO', no hace nada.
    """
    fila = conn.execute("SELECT sql FROM sqlite_master WHERE type = 'table' AND name = 'cuentas'").fetchone()
    if "'BOLSILLO'" in fila["sql"]:
        return

    # Con las llaves foráneas activas no se podría borrar la tabla vieja, porque
    # movimientos apunta a ella. Este PRAGMA no tiene efecto dentro de una transacción.
    conn.execute("PRAGMA foreign_keys = OFF")
    try:
        with transaccion(conn):
            conn.execute(TABLA_CUENTAS.format(nombre="cuentas_nueva"))
            conn.execute(
                "INSERT INTO cuentas_nueva (id, usuario_id, tipo, saldo, creada_en) "
                "SELECT id, usuario_id, tipo, saldo, creada_en FROM cuentas"
            )
            conn.execute("DROP TABLE cuentas")
            conn.execute("ALTER TABLE cuentas_nueva RENAME TO cuentas")
            conn.execute(INDICE_FONDEO)
            # Las demás tablas deben seguir apuntando a cuentas que existen.
            if conn.execute("PRAGMA foreign_key_check").fetchall():
                raise RuntimeError("La migración de cuentas rompió referencias: se deshace")
    finally:
        conn.execute("PRAGMA foreign_keys = ON")


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
