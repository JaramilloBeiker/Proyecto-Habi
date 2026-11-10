"""RF-03 Carga de saldo, RNF-D-02 Validación de montos."""

import pytest

from habi import repository, services
from habi.dominio import ErrorValidacion


def _saldo_fondeo(conn) -> int:
    return repository.obtener_saldo(conn, repository.obtener_cuenta_fondeo_id(conn))


def test_carga_aumenta_saldo(conn, crear_usuario):
    """RF-03"""
    ana = crear_usuario("ana")
    resultado = services.cargar_saldo(conn, ana, 50_000)
    assert resultado.tipo == "CARGA"
    assert resultado.monto == 50_000
    services.cargar_saldo(conn, ana, 2_500)
    assert services.consultar_saldo(conn, ana) == 52_500


def test_carga_crea_contrapartida_en_fondeo(conn, crear_usuario):
    """RF-03 / RNF-D-05: movimiento -monto en fondeo y +monto en el usuario."""
    ana = crear_usuario("ana")
    resultado = services.cargar_saldo(conn, ana, 10_000)
    fondeo_id = repository.obtener_cuenta_fondeo_id(conn)
    movimientos = conn.execute(
        "SELECT cuenta_id, monto FROM movimientos WHERE operacion_id = ? ORDER BY monto",
        (resultado.operacion_id,),
    ).fetchall()
    assert [tuple(m) for m in movimientos] == [(fondeo_id, -10_000), (ana.cuenta_id, 10_000)]
    assert _saldo_fondeo(conn) == -10_000


@pytest.mark.parametrize("monto", [0, -1, 5_000_001, 1.5, "100", True])
def test_carga_rechaza_montos_invalidos(conn, crear_usuario, monto):
    """RNF-D-02 / RNF-U-03: error de validación y saldos sin cambios."""
    ana = crear_usuario("ana")
    with pytest.raises(ErrorValidacion) as e:
        services.cargar_saldo(conn, ana, monto)
    assert e.value.campo == "monto"
    assert services.consultar_saldo(conn, ana) == 0
    assert _saldo_fondeo(conn) == 0
    assert conn.execute("SELECT COUNT(*) FROM movimientos").fetchone()[0] == 0


@pytest.mark.parametrize("monto", [1, 5_000_000])
def test_carga_acepta_limites(conn, crear_usuario, monto):
    """RNF-D-02: los extremos del rango son válidos."""
    ana = crear_usuario("ana")
    services.cargar_saldo(conn, ana, monto)
    assert services.consultar_saldo(conn, ana) == monto
