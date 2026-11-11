"""Rutas de RF-04 Transferencias, RNF-R-02/03 y RNF-P-01."""

import time
import uuid

import pytest


@pytest.fixture
def ana_con_saldo(cliente, registrar_y_entrar):
    """beto existe; ana tiene sesión iniciada y 10.000 COP."""
    cliente.post("/api/registro", json={"nombre": "beto", "password": "clave-segura"})
    registrar_y_entrar("ana")
    cliente.post("/api/cargas", json={"monto": 10_000})
    return cliente


def pedir_clave(cliente) -> str:
    r = cliente.get("/api/transferencias/nueva")
    assert r.status_code == 200
    return r.get_json()["clave_idempotencia"]


def contar_movimientos(conn) -> int:
    return conn.execute("SELECT COUNT(*) FROM movimientos").fetchone()[0]


def saldo_de(conn, nombre: str) -> int:
    return conn.execute(
        "SELECT c.saldo FROM cuentas c JOIN usuarios u ON u.id = c.usuario_id WHERE u.nombre = ?", (nombre,)
    ).fetchone()[0]


def test_sistema_genera_claves_unicas(ana_con_saldo):
    """RNF-R-03"""
    clave1, clave2 = pedir_clave(ana_con_saldo), pedir_clave(ana_con_saldo)
    assert clave1 != clave2
    uuid.UUID(clave1)


def test_transferencia_por_api(ana_con_saldo, conn):
    """RF-04"""
    r = ana_con_saldo.post(
        "/api/transferencias", json={"destino": "beto", "monto": 3_000, "clave_idempotencia": pedir_clave(ana_con_saldo)}
    )
    assert r.status_code == 201
    datos = r.get_json()
    assert datos["mensaje"] == "Transferencia de 3.000 COP a 'beto' realizada."
    assert datos["saldo_cop"] == "7.000 COP"
    assert saldo_de(conn, "beto") == 3_000

    movimiento = ana_con_saldo.get("/api/historial").get_json()["movimientos"][0]
    assert movimiento["monto_cop"] == "-3.000 COP"
    assert movimiento["contraparte"] == "beto"


def test_transferencia_desde_formulario_html(ana_con_saldo, conn):
    datos = {"destino": "beto", "monto": "2500", "clave_idempotencia": pedir_clave(ana_con_saldo)}
    assert ana_con_saldo.post("/api/transferencias", data=datos).status_code == 201
    assert saldo_de(conn, "beto") == 2_500


def test_reenviar_misma_clave_no_duplica(ana_con_saldo, conn):
    """RNF-R-03: el reenvío devuelve el resultado original y no crea movimientos."""
    datos = {"destino": "beto", "monto": 1_000, "clave_idempotencia": pedir_clave(ana_con_saldo)}
    primera = ana_con_saldo.post("/api/transferencias", json=datos).get_json()
    movimientos = contar_movimientos(conn)

    r = ana_con_saldo.post("/api/transferencias", json=datos)
    assert r.status_code == 200
    segunda = r.get_json()
    assert segunda["repetida"] is True
    assert segunda["operacion_id"] == primera["operacion_id"]
    assert contar_movimientos(conn) == movimientos
    assert saldo_de(conn, "ana") == 9_000


def test_saldo_insuficiente_no_crea_movimientos(ana_con_saldo, conn):
    """RF-04 / RNF-R-02"""
    movimientos = contar_movimientos(conn)
    r = ana_con_saldo.post(
        "/api/transferencias", json={"destino": "beto", "monto": 10_001, "clave_idempotencia": pedir_clave(ana_con_saldo)}
    )
    assert r.status_code == 409
    assert "Saldo insuficiente" in r.get_json()["error"]
    assert contar_movimientos(conn) == movimientos
    assert saldo_de(conn, "ana") == 10_000
    assert saldo_de(conn, "beto") == 0


@pytest.mark.parametrize(
    "cambios, codigo, campo",
    [
        ({"destino": "nadie"}, 404, None),
        ({"destino": "ana"}, 400, "destino"),
        ({"destino": ""}, 400, "destino"),
        ({"monto": 0}, 400, "monto"),
        ({"monto": "1,5"}, 400, "monto"),
        ({"monto": 5_000_001}, 400, "monto"),
        ({"clave_idempotencia": ""}, 400, "clave_idempotencia"),
        ({"clave_idempotencia": "inventada"}, 400, "clave_idempotencia"),
    ],
)
def test_transferencia_invalida(ana_con_saldo, conn, cambios, codigo, campo):
    """RNF-U-03: el error indica el campo y no altera saldos ni movimientos."""
    datos = {"destino": "beto", "monto": 1_000, "clave_idempotencia": pedir_clave(ana_con_saldo), **cambios}
    movimientos = contar_movimientos(conn)
    r = ana_con_saldo.post("/api/transferencias", json=datos)
    assert r.status_code == codigo
    assert r.get_json()["ok"] is False
    assert r.get_json()["campo"] == campo
    assert contar_movimientos(conn) == movimientos
    assert saldo_de(conn, "ana") == 10_000


def test_transferencia_requiere_sesion(cliente):
    """RNF-SEC-01"""
    assert cliente.get("/api/transferencias/nueva").status_code == 401
    datos = {"destino": "beto", "monto": 1_000, "clave_idempotencia": str(uuid.uuid4())}
    assert cliente.post("/api/transferencias", json=datos).status_code == 401


def test_no_se_puede_elegir_cuenta_origen(ana_con_saldo, conn):
    """RNF-SEC-02: el origen siempre es la cuenta de la sesión; un campo 'origen' se ignora."""
    ana_con_saldo.post("/api/logout")
    ana_con_saldo.post("/api/login", json={"nombre": "beto", "password": "clave-segura"})
    datos = {"origen": "ana", "destino": "ana", "monto": 1_000, "clave_idempotencia": pedir_clave(ana_con_saldo)}
    assert ana_con_saldo.post("/api/transferencias", json=datos).status_code == 409
    assert saldo_de(conn, "ana") == 10_000


def test_transferencia_y_saldo_en_menos_de_1_segundo(ana_con_saldo):
    """RNF-P-01"""
    clave = pedir_clave(ana_con_saldo)
    inicio = time.perf_counter()
    ana_con_saldo.post("/api/transferencias", json={"destino": "beto", "monto": 1_000, "clave_idempotencia": clave})
    ana_con_saldo.get("/api/saldo")
    assert time.perf_counter() - inicio < 1
