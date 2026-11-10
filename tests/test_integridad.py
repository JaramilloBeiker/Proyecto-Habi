"""RNF-R-01 Persistencia, RNF-D-03/04/05: reglas que garantiza el esquema de la BD."""

import sqlite3

import pytest

from habi import db

pendiente = pytest.mark.skip(reason="Pendiente: implementar services/repository")


def _crear_cuenta_con_movimiento(conn) -> int:
    """Inserta directo por SQL una cuenta de usuario con un movimiento (sin pasar por services)."""
    ahora = db.ahora_iso()
    usuario_id = conn.execute(
        "INSERT INTO usuarios (nombre, password_hash, creado_en) VALUES ('x', 'h', ?)", (ahora,)
    ).lastrowid
    cuenta_id = conn.execute(
        "INSERT INTO cuentas (usuario_id, tipo, creada_en) VALUES (?, 'USUARIO', ?)", (usuario_id, ahora)
    ).lastrowid
    operacion_id = conn.execute(
        "INSERT INTO operaciones (tipo, monto, creada_en) VALUES ('CARGA', 100, ?)", (ahora,)
    ).lastrowid
    conn.execute(
        "INSERT INTO movimientos (operacion_id, cuenta_id, monto, creado_en) VALUES (?, ?, 100, ?)",
        (operacion_id, cuenta_id, ahora),
    )
    return cuenta_id


def test_existe_una_unica_cuenta_de_fondeo(conn):
    db.inicializar(conn)  # inicializar dos veces no duplica la cuenta de fondeo
    total = conn.execute("SELECT COUNT(*) FROM cuentas WHERE tipo = 'FONDEO'").fetchone()[0]
    assert total == 1


def test_movimientos_no_se_modifican_ni_eliminan(conn):
    """RNF-D-04"""
    _crear_cuenta_con_movimiento(conn)
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("UPDATE movimientos SET monto = 999")
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("DELETE FROM movimientos")


def test_cuenta_con_movimientos_no_se_elimina(conn):
    """RNF-D-03"""
    cuenta_id = _crear_cuenta_con_movimiento(conn)
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("DELETE FROM cuentas WHERE id = ?", (cuenta_id,))


def test_cuenta_de_usuario_no_puede_quedar_negativa(conn):
    """RNF-D-05: solo la cuenta de fondeo admite saldo negativo."""
    cuenta_id = _crear_cuenta_con_movimiento(conn)
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("UPDATE cuentas SET saldo = -1 WHERE id = ?", (cuenta_id,))
    conn.execute("UPDATE cuentas SET saldo = -1 WHERE tipo = 'FONDEO'")  # permitido


@pendiente
def test_suma_de_movimientos_por_operacion_es_cero(conn, crear_usuario):
    """RNF-D-05: tras cargas y transferencias, SUM(monto) GROUP BY operacion_id = 0 en todas."""


@pendiente
def test_saldo_coincide_con_suma_de_movimientos(conn, crear_usuario):
    """Saldo de cada cuenta = SUM(movimientos.monto) de esa cuenta."""


@pendiente
def test_datos_persisten_al_reabrir(ruta_db):
    """RNF-R-01: registrar y cargar, cerrar conexión, reabrir y verificar saldo."""
