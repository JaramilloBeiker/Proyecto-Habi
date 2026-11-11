"""Juntia, paso 3: aportes con idempotencia, historial del bolsillo y salida."""

import uuid

import pytest

from habi import services
from habi.dominio import (
    ErrorAutorizacion,
    ErrorValidacion,
    NoEncontrado,
    OperacionNoPermitida,
    SaldoInsuficiente,
)


def _clave() -> str:
    return str(uuid.uuid4())


@pytest.fixture
def escenario(conn, crear_usuario):
    """ana crea el bolsillo 'Viaje' y beto entra como miembro activo."""
    ana = crear_usuario("ana", saldo=100_000)
    beto = crear_usuario("beto", saldo=50_000)
    bolsillo = services.crear_bolsillo(conn, ana, "Viaje", 1_000_000)
    services.invitar_a_bolsillo(conn, ana, bolsillo.id, "beto")
    services.aceptar_invitacion(conn, beto, bolsillo.id)
    return ana, beto, bolsillo


def test_aporte_mueve_dinero_al_bolsillo(conn, escenario):
    ana, beto, bolsillo = escenario
    resultado = services.aportar_a_bolsillo(conn, ana, bolsillo.id, 30_000, _clave())
    services.aportar_a_bolsillo(conn, beto, bolsillo.id, 5_000, _clave())

    assert resultado.tipo == "TRANSFERENCIA"
    assert services.consultar_saldo(conn, ana) == 70_000
    assert services.consultar_saldo(conn, beto) == 45_000
    assert services.ver_bolsillo(conn, ana, bolsillo.id).saldo == 35_000
    aportes = {m.nombre: m.aportado for m in services.miembros_de_bolsillo(conn, ana, bolsillo.id)}
    assert aportes == {"ana": 30_000, "beto": 5_000}


def test_aporte_repetido_con_la_misma_clave_no_se_duplica(conn, escenario):
    """RNF-R-03 reutilizado en Juntia."""
    ana, _, bolsillo = escenario
    clave = _clave()
    primero = services.aportar_a_bolsillo(conn, ana, bolsillo.id, 10_000, clave)
    segundo = services.aportar_a_bolsillo(conn, ana, bolsillo.id, 10_000, clave)
    assert segundo.repetida and segundo.operacion_id == primero.operacion_id
    assert services.ver_bolsillo(conn, ana, bolsillo.id).saldo == 10_000
    assert services.consultar_saldo(conn, ana) == 90_000


def test_clave_de_transferencia_no_sirve_para_aportar(conn, escenario):
    ana, _, bolsillo = escenario
    clave = _clave()
    services.transferir(conn, ana, "beto", 1_000, clave)
    with pytest.raises(ErrorValidacion) as e:
        services.aportar_a_bolsillo(conn, ana, bolsillo.id, 1_000, clave)
    assert e.value.campo == "clave_idempotencia"


def test_aporte_sin_saldo_suficiente_no_mueve_nada(conn, escenario):
    _, beto, bolsillo = escenario
    with pytest.raises(SaldoInsuficiente, match="quieres aportar"):
        services.aportar_a_bolsillo(conn, beto, bolsillo.id, 50_001, _clave())
    assert services.consultar_saldo(conn, beto) == 50_000
    assert services.ver_bolsillo(conn, beto, bolsillo.id).saldo == 0


def test_aporte_valida_monto_y_clave(conn, escenario):
    ana, _, bolsillo = escenario
    with pytest.raises(ErrorValidacion) as e:
        services.aportar_a_bolsillo(conn, ana, bolsillo.id, 0, _clave())
    assert e.value.campo == "monto"
    with pytest.raises(ErrorValidacion) as e:
        services.aportar_a_bolsillo(conn, ana, bolsillo.id, 1_000, "")
    assert e.value.campo == "clave_idempotencia"


def test_invitado_sin_aceptar_no_puede_aportar(conn, escenario, crear_usuario):
    ana, _, bolsillo = escenario
    carla = crear_usuario("carla", saldo=10_000)
    services.invitar_a_bolsillo(conn, ana, bolsillo.id, "carla")
    with pytest.raises(ErrorAutorizacion):
        services.aportar_a_bolsillo(conn, carla, bolsillo.id, 1_000, _clave())
    assert services.consultar_saldo(conn, carla) == 10_000


def test_historial_del_bolsillo_muestra_los_aportes(conn, escenario):
    ana, beto, bolsillo = escenario
    services.aportar_a_bolsillo(conn, ana, bolsillo.id, 30_000, _clave())
    services.aportar_a_bolsillo(conn, beto, bolsillo.id, 5_000, _clave())

    historial = services.historial_bolsillo(conn, beto, bolsillo.id)
    assert [(m.contraparte, m.monto) for m in historial] == [("beto", 5_000), ("ana", 30_000)]

    # En el historial personal, la contraparte del aporte es el bolsillo.
    personal = services.consultar_historial(conn, ana)[0]
    assert (personal.contraparte, personal.contraparte_tipo, personal.monto) == ("Viaje", "BOLSILLO", -30_000)


def test_historial_del_bolsillo_solo_para_miembros(conn, escenario, crear_usuario):
    _, _, bolsillo = escenario
    carla = crear_usuario("carla")
    with pytest.raises(NoEncontrado):
        services.historial_bolsillo(conn, carla, bolsillo.id)
    ana = services.iniciar_sesion(conn, "ana", "clave-segura")
    with pytest.raises(ErrorValidacion):
        services.historial_bolsillo(conn, ana, bolsillo.id, -1)


def test_quien_no_ha_aportado_puede_salir(conn, escenario):
    ana, beto, bolsillo = escenario
    services.salir_de_bolsillo(conn, beto, bolsillo.id)
    with pytest.raises(ErrorAutorizacion):
        services.ver_bolsillo(conn, beto, bolsillo.id)
    assert services.listar_bolsillos(conn, beto) == []
    assert [m.nombre for m in services.miembros_de_bolsillo(conn, ana, bolsillo.id)] == ["ana"]
    # Quien salió ya no puede aportar.
    with pytest.raises(ErrorAutorizacion):
        services.aportar_a_bolsillo(conn, beto, bolsillo.id, 1_000, _clave())


def test_quien_ya_aporto_no_puede_salir(conn, escenario):
    _, beto, bolsillo = escenario
    services.aportar_a_bolsillo(conn, beto, bolsillo.id, 1, _clave())
    with pytest.raises(OperacionNoPermitida, match="no puedes salir"):
        services.salir_de_bolsillo(conn, beto, bolsillo.id)
    assert services.ver_bolsillo(conn, beto, bolsillo.id).saldo == 1


def test_quien_salio_puede_ser_invitado_de_nuevo(conn, escenario):
    ana, beto, bolsillo = escenario
    services.salir_de_bolsillo(conn, beto, bolsillo.id)
    services.invitar_a_bolsillo(conn, ana, bolsillo.id, "beto")
    services.aceptar_invitacion(conn, beto, bolsillo.id)
    assert services.ver_bolsillo(conn, beto, bolsillo.id).id == bolsillo.id


def test_aportes_mantienen_la_contabilidad_cuadrada(conn, escenario):
    """RNF-D-05: cada operación suma cero y el saldo del bolsillo = suma de sus movimientos."""
    ana, beto, bolsillo = escenario
    services.aportar_a_bolsillo(conn, ana, bolsillo.id, 12_345, _clave())
    services.aportar_a_bolsillo(conn, beto, bolsillo.id, 678, _clave())
    assert conn.execute(
        "SELECT COUNT(*) FROM (SELECT SUM(monto) s FROM movimientos GROUP BY operacion_id HAVING s <> 0)"
    ).fetchone()[0] == 0
    assert conn.execute("SELECT SUM(saldo) FROM cuentas").fetchone()[0] == 0
    suma = conn.execute(
        "SELECT SUM(m.monto) FROM movimientos m JOIN bolsillos b ON b.cuenta_id = m.cuenta_id WHERE b.id = ?",
        (bolsillo.id,),
    ).fetchone()[0]
    assert suma == services.ver_bolsillo(conn, ana, bolsillo.id).saldo == 13_023
