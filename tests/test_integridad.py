"""RNF-R-01 Persistencia, RNF-D-03/04/05: reglas que garantiza el esquema de la BD."""

import sqlite3
import uuid

import pytest

from habi import db, services
from habi.dominio import SaldoInsuficiente


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


def _escenario_con_operaciones(conn, crear_usuario):
    ana = crear_usuario("ana", saldo=50_000)
    beto = crear_usuario("beto", saldo=20_000)
    crear_usuario("carla")
    services.transferir(conn, ana, "beto", 12_345, str(uuid.uuid4()))
    services.transferir(conn, beto, "carla", 30_000, str(uuid.uuid4()))
    services.transferir(conn, ana, "carla", 1, str(uuid.uuid4()))
    with pytest.raises(SaldoInsuficiente):
        services.transferir(conn, beto, "ana", 5_000_000, str(uuid.uuid4()))


def test_suma_de_movimientos_por_operacion_es_cero(conn, crear_usuario):
    """RNF-D-05: tras cargas y transferencias, SUM(monto) GROUP BY operacion_id = 0 en todas."""
    _escenario_con_operaciones(conn, crear_usuario)
    filas = conn.execute(
        "SELECT operacion_id, SUM(monto) AS total, COUNT(*) AS n FROM movimientos GROUP BY operacion_id"
    ).fetchall()
    assert len(filas) == 5  # 2 cargas + 3 transferencias exitosas
    assert all(f["total"] == 0 and f["n"] == 2 for f in filas)
    # Todo el dinero del sistema suma cero: lo que tienen los usuarios salió del fondeo.
    assert conn.execute("SELECT SUM(saldo) FROM cuentas").fetchone()[0] == 0


def test_saldo_coincide_con_suma_de_movimientos(conn, crear_usuario):
    """Saldo de cada cuenta = SUM(movimientos.monto) de esa cuenta."""
    _escenario_con_operaciones(conn, crear_usuario)
    descuadres = conn.execute(
        """
        SELECT c.id, c.saldo, COALESCE(SUM(m.monto), 0) AS suma
        FROM cuentas c LEFT JOIN movimientos m ON m.cuenta_id = c.id
        GROUP BY c.id
        HAVING c.saldo <> suma
        """
    ).fetchall()
    assert descuadres == []


def test_datos_persisten_al_reabrir(ruta_db):
    """RNF-R-01: registrar y cargar, cerrar conexión, reabrir y verificar saldo."""
    conn = db.conectar(ruta_db)
    services.registrar_usuario(conn, "ana", "clave-segura")
    ana = services.iniciar_sesion(conn, "ana", "clave-segura")
    services.cargar_saldo(conn, ana, 75_000)
    conn.close()

    conn = db.conectar(ruta_db)
    try:
        ana = services.iniciar_sesion(conn, "ana", "clave-segura")
        assert services.consultar_saldo(conn, ana) == 75_000
        assert len(services.consultar_historial(conn, ana)) == 1
    finally:
        conn.close()
