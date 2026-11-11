"""Juntia, paso 1: la tabla cuentas acepta el tipo BOLSILLO, también en bases creadas antes."""

import sqlite3

import pytest

from habi import db, services

# Esquema de cuentas tal como estaba antes de Juntia (solo USUARIO y FONDEO).
ESQUEMA_ANTERIOR = """
CREATE TABLE usuarios (
    id            INTEGER PRIMARY KEY,
    nombre        TEXT NOT NULL UNIQUE,
    password_hash TEXT NOT NULL,
    creado_en     TEXT NOT NULL
);
CREATE TABLE cuentas (
    id         INTEGER PRIMARY KEY,
    usuario_id INTEGER UNIQUE REFERENCES usuarios(id) ON DELETE RESTRICT,
    tipo       TEXT NOT NULL CHECK (tipo IN ('USUARIO', 'FONDEO')),
    saldo      INTEGER NOT NULL DEFAULT 0 CHECK (typeof(saldo) = 'integer'),
    creada_en  TEXT NOT NULL,
    CHECK (tipo = 'FONDEO' OR saldo >= 0),
    CHECK ((tipo = 'FONDEO') = (usuario_id IS NULL))
);
CREATE UNIQUE INDEX ux_cuenta_fondeo ON cuentas(tipo) WHERE tipo = 'FONDEO';
CREATE TABLE operaciones (
    id                 INTEGER PRIMARY KEY,
    tipo               TEXT NOT NULL CHECK (tipo IN ('CARGA', 'TRANSFERENCIA')),
    clave_idempotencia TEXT UNIQUE,
    monto              INTEGER NOT NULL CHECK (typeof(monto) = 'integer' AND monto > 0),
    creada_en          TEXT NOT NULL
);
CREATE TABLE movimientos (
    id           INTEGER PRIMARY KEY,
    operacion_id INTEGER NOT NULL REFERENCES operaciones(id) ON DELETE RESTRICT,
    cuenta_id    INTEGER NOT NULL REFERENCES cuentas(id) ON DELETE RESTRICT,
    monto        INTEGER NOT NULL CHECK (typeof(monto) = 'integer' AND monto <> 0),
    creado_en    TEXT NOT NULL
);
INSERT INTO usuarios (id, nombre, password_hash, creado_en) VALUES (1, 'ana', 'h', '2026-01-01T00:00:00+00:00');
INSERT INTO cuentas (id, usuario_id, tipo, saldo, creada_en) VALUES (1, NULL, 'FONDEO', -70000, '2026-01-01T00:00:00+00:00');
INSERT INTO cuentas (id, usuario_id, tipo, saldo, creada_en) VALUES (2, 1, 'USUARIO', 70000, '2026-01-01T00:00:00+00:00');
INSERT INTO operaciones (id, tipo, monto, creada_en) VALUES (1, 'CARGA', 70000, '2026-01-01T00:00:00+00:00');
INSERT INTO movimientos (operacion_id, cuenta_id, monto, creado_en) VALUES (1, 1, -70000, '2026-01-01T00:00:00+00:00');
INSERT INTO movimientos (operacion_id, cuenta_id, monto, creado_en) VALUES (1, 2, 70000, '2026-01-01T00:00:00+00:00');
"""


@pytest.fixture
def conn_antigua(tmp_path):
    """Base de datos con el esquema anterior a Juntia y algunos datos."""
    conn = db.conectar(tmp_path / "antigua.db")
    conn.executescript(ESQUEMA_ANTERIOR)
    yield conn
    conn.close()


def _insertar_bolsillo(conn) -> int:
    return conn.execute(
        "INSERT INTO cuentas (usuario_id, tipo, saldo, creada_en) VALUES (NULL, 'BOLSILLO', 0, ?)",
        (db.ahora_iso(),),
    ).lastrowid


def test_esquema_anterior_rechaza_bolsillo(conn_antigua):
    """Confirma que la base de prueba de verdad tiene el CHECK viejo."""
    with pytest.raises(sqlite3.IntegrityError):
        _insertar_bolsillo(conn_antigua)


def test_migracion_conserva_los_datos(conn_antigua):
    db.inicializar(conn_antigua)

    cuentas = conn_antigua.execute("SELECT id, usuario_id, tipo, saldo FROM cuentas ORDER BY id").fetchall()
    assert [tuple(c) for c in cuentas] == [(1, None, "FONDEO", -70000), (2, 1, "USUARIO", 70000)]
    assert conn_antigua.execute("SELECT COUNT(*) FROM movimientos").fetchone()[0] == 2
    assert conn_antigua.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
    assert conn_antigua.execute("PRAGMA foreign_key_check").fetchall() == []


def test_migracion_permite_bolsillos_y_mantiene_reglas(conn_antigua):
    db.inicializar(conn_antigua)
    _insertar_bolsillo(conn_antigua)

    # Sigue existiendo una sola cuenta de fondeo.
    with pytest.raises(sqlite3.IntegrityError):
        conn_antigua.execute(
            "INSERT INTO cuentas (usuario_id, tipo, saldo, creada_en) VALUES (NULL, 'FONDEO', 0, 'x')"
        )
    # Las llaves foráneas siguen activas: una cuenta con movimientos no se borra.
    with pytest.raises(sqlite3.IntegrityError):
        conn_antigua.execute("DELETE FROM cuentas WHERE id = 2")


def test_migracion_es_idempotente(conn_antigua):
    db.inicializar(conn_antigua)
    db.inicializar(conn_antigua)
    assert conn_antigua.execute("SELECT COUNT(*) FROM cuentas").fetchone()[0] == 2


def test_usuario_existente_sigue_operando_tras_migrar(conn_antigua):
    db.inicializar(conn_antigua)
    beto = services.registrar_usuario(conn_antigua, "beto", "clave-segura")
    services.cargar_saldo(conn_antigua, beto, 1_000)
    assert services.consultar_saldo(conn_antigua, beto) == 1_000


def test_bolsillo_no_puede_quedar_negativo(conn):
    cuenta_id = _insertar_bolsillo(conn)
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("UPDATE cuentas SET saldo = -1 WHERE id = ?", (cuenta_id,))


def test_bolsillo_no_tiene_dueno_y_usuario_si(conn, crear_usuario):
    ana = crear_usuario("ana")
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO cuentas (usuario_id, tipo, saldo, creada_en) VALUES (?, 'BOLSILLO', 0, 'x')", (ana.id,)
        )
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("INSERT INTO cuentas (usuario_id, tipo, saldo, creada_en) VALUES (NULL, 'USUARIO', 0, 'x')")
