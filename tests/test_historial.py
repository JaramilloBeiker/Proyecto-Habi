"""RF-06 Historial de movimientos."""

import uuid

import pytest

from habi import services
from habi.dominio import ErrorValidacion


def _transferir(conn, origen, destino: str, monto: int):
    return services.transferir(conn, origen, destino, monto, str(uuid.uuid4()))


def test_historial_ordenado_del_mas_reciente(conn, crear_usuario):
    """RF-06"""
    ana = crear_usuario("ana", saldo=10_000)
    crear_usuario("beto", saldo=5_000)
    beto = services.iniciar_sesion(conn, "beto", "clave-segura")
    _transferir(conn, ana, "beto", 1_000)
    _transferir(conn, beto, "ana", 300)

    historial = services.consultar_historial(conn, ana)
    assert [(m.tipo_operacion, m.monto, m.contraparte) for m in historial] == [
        ("TRANSFERENCIA", 300, "beto"),
        ("TRANSFERENCIA", -1_000, "beto"),
        ("CARGA", 10_000, "FONDEO"),
    ]
    assert all(m.creado_en for m in historial)


def test_historial_paginado_en_bloques_de_20(conn, crear_usuario):
    """RF-06: 25 movimientos -> página 0 con 20, página 1 con 5."""
    ana = crear_usuario("ana")
    for i in range(1, 26):
        services.cargar_saldo(conn, ana, i)
    pagina0 = services.consultar_historial(conn, ana, 0)
    pagina1 = services.consultar_historial(conn, ana, 1)
    assert len(pagina0) == 20
    assert len(pagina1) == 5
    assert [m.monto for m in pagina0 + pagina1] == list(range(25, 0, -1))
    assert services.consultar_historial(conn, ana, 2) == []


def test_historial_solo_de_la_cuenta_propia(conn, crear_usuario):
    """RNF-SEC-02: un usuario no ve movimientos de otro."""
    ana = crear_usuario("ana", saldo=1_000)
    beto = crear_usuario("beto", saldo=2_000)
    crear_usuario("carla")
    _transferir(conn, beto, "carla", 500)

    historial_ana = services.consultar_historial(conn, ana)
    assert len(historial_ana) == 1
    assert historial_ana[0].monto == 1_000
    assert {m.contraparte for m in services.consultar_historial(conn, beto)} == {"FONDEO", "carla"}


def test_historial_vacio(conn, crear_usuario):
    assert services.consultar_historial(conn, crear_usuario("ana")) == []


@pytest.mark.parametrize("pagina", [-1, 1.5, "0", True])
def test_historial_rechaza_pagina_invalida(conn, crear_usuario, pagina):
    with pytest.raises(ErrorValidacion):
        services.consultar_historial(conn, crear_usuario("ana"), pagina)
