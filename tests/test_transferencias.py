"""RF-04 Transferencias, RNF-R-02 Atomicidad, RNF-R-03 Idempotencia, RNF-SEC-02 Autorización."""

import uuid

import pytest

from habi import repository, services
from habi.dominio import ErrorValidacion, NoEncontrado, SaldoInsuficiente


def _clave() -> str:
    return str(uuid.uuid4())


def _total_movimientos(conn) -> int:
    return conn.execute("SELECT COUNT(*) FROM movimientos").fetchone()[0]


def test_transferencia_mueve_saldo(conn, crear_usuario):
    """RF-04"""
    ana = crear_usuario("ana", saldo=10_000)
    beto = crear_usuario("beto")
    resultado = services.transferir(conn, ana, "beto", 3_000, _clave())
    assert resultado.tipo == "TRANSFERENCIA"
    assert not resultado.repetida
    assert services.consultar_saldo(conn, ana) == 7_000
    assert services.consultar_saldo(conn, beto) == 3_000
    movimientos = repository.movimientos_de_operacion(conn, resultado.operacion_id)
    assert [tuple(m) for m in movimientos] == [(ana.cuenta_id, -3_000), (beto.cuenta_id, 3_000)]


def test_transferencia_de_todo_el_saldo(conn, crear_usuario):
    ana = crear_usuario("ana", saldo=5_000)
    crear_usuario("beto")
    services.transferir(conn, ana, "beto", 5_000, _clave())
    assert services.consultar_saldo(conn, ana) == 0


def test_transferencia_saldo_insuficiente_no_crea_movimientos(conn, crear_usuario):
    """RF-04: SaldoInsuficiente, saldos y movimientos sin cambios."""
    ana = crear_usuario("ana", saldo=1_000)
    beto = crear_usuario("beto")
    antes = _total_movimientos(conn)
    with pytest.raises(SaldoInsuficiente):
        services.transferir(conn, ana, "beto", 1_001, _clave())
    assert services.consultar_saldo(conn, ana) == 1_000
    assert services.consultar_saldo(conn, beto) == 0
    assert _total_movimientos(conn) == antes


def test_transferencia_a_si_mismo_rechazada(conn, crear_usuario):
    """RF-04: destino distinto al origen."""
    ana = crear_usuario("ana", saldo=1_000)
    with pytest.raises(ErrorValidacion) as e:
        services.transferir(conn, ana, "ana", 500, _clave())
    assert e.value.campo == "destino"
    assert services.consultar_saldo(conn, ana) == 1_000


def test_transferencia_a_destino_inexistente_rechazada(conn, crear_usuario):
    """RF-04: destino debe existir."""
    ana = crear_usuario("ana", saldo=1_000)
    antes = _total_movimientos(conn)
    with pytest.raises(NoEncontrado):
        services.transferir(conn, ana, "fantasma", 500, _clave())
    assert services.consultar_saldo(conn, ana) == 1_000
    assert _total_movimientos(conn) == antes


@pytest.mark.parametrize("monto", [0, -500, 5_000_001, 10.0, "500", True])
def test_transferencia_rechaza_montos_invalidos(conn, crear_usuario, monto):
    """RNF-D-02: un monto negativo no puede usarse para 'robar' saldo al destino."""
    ana = crear_usuario("ana", saldo=1_000)
    beto = crear_usuario("beto", saldo=1_000)
    with pytest.raises(ErrorValidacion):
        services.transferir(conn, ana, "beto", monto, _clave())
    assert services.consultar_saldo(conn, ana) == 1_000
    assert services.consultar_saldo(conn, beto) == 1_000


def test_misma_clave_devuelve_resultado_original(conn, crear_usuario):
    """RNF-R-03: segunda llamada con la misma clave -> repetida=True y sin movimientos nuevos."""
    ana = crear_usuario("ana", saldo=10_000)
    beto = crear_usuario("beto")
    clave = _clave()
    primera = services.transferir(conn, ana, "beto", 2_000, clave)
    antes = _total_movimientos(conn)
    segunda = services.transferir(conn, ana, "beto", 2_000, clave)
    assert segunda.repetida
    assert segunda.operacion_id == primera.operacion_id
    assert _total_movimientos(conn) == antes
    assert services.consultar_saldo(conn, ana) == 8_000
    assert services.consultar_saldo(conn, beto) == 2_000


def test_misma_clave_con_otros_datos_se_rechaza(conn, crear_usuario):
    """RNF-R-03: una clave no puede reutilizarse para una transferencia distinta."""
    ana = crear_usuario("ana", saldo=10_000)
    crear_usuario("beto")
    clave = _clave()
    services.transferir(conn, ana, "beto", 2_000, clave)
    with pytest.raises(ErrorValidacion) as e:
        services.transferir(conn, ana, "beto", 3_000, clave)
    assert e.value.campo == "clave_idempotencia"
    assert services.consultar_saldo(conn, ana) == 8_000


def test_fallo_a_mitad_hace_rollback(conn, crear_usuario, monkeypatch):
    """RNF-R-02: forzar excepción tras el débito (monkeypatch en repository) y verificar saldos intactos."""
    ana = crear_usuario("ana", saldo=10_000)
    beto = crear_usuario("beto")
    antes = _total_movimientos(conn)

    def falla(*args, **kwargs):
        raise RuntimeError("fallo simulado a mitad de la transferencia")

    monkeypatch.setattr(repository, "crear_movimiento", falla)
    clave = _clave()
    with pytest.raises(RuntimeError):
        services.transferir(conn, ana, "beto", 4_000, clave)
    monkeypatch.undo()

    assert services.consultar_saldo(conn, ana) == 10_000
    assert services.consultar_saldo(conn, beto) == 0
    assert _total_movimientos(conn) == antes
    assert repository.obtener_operacion_por_clave(conn, clave) is None
    # La misma clave puede reintentarse tras el fallo y ahora sí se aplica una sola vez.
    services.transferir(conn, ana, "beto", 4_000, clave)
    assert services.consultar_saldo(conn, ana) == 6_000
