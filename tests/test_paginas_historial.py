"""Historial: RF-06 paginado de 20 en 20, RNF-U-02 formato de montos y fechas."""

import re
from datetime import datetime

import pytest


@pytest.fixture
def ana(cliente):
    cliente.post("/registro", data={"nombre": "ana", "password": "clave-segura"})
    return cliente


def montos_en_tabla(pagina: str) -> list[str]:
    return [m.strip() for m in re.findall(r'class="tabla__monto monto--\w+">\s*([^<]+?)\s*</td>', pagina)]


def test_historial_vacio(ana):
    pagina = ana.get("/historial").get_data(as_text=True)
    assert "Aún no tienes movimientos." in pagina


def test_historial_muestra_movimientos(ana):
    """RF-06 / RNF-U-02"""
    ana.post("/cuenta/cargar", data={"monto": "50000"})
    pagina = ana.get("/historial").get_data(as_text=True)
    assert "Carga de saldo" in pagina
    assert "Cuenta de fondeo" in pagina
    assert montos_en_tabla(pagina) == ["+50.000 COP"]
    fecha = re.search(r'<time datetime="([^"]+)"', pagina).group(1)
    datetime.fromisoformat(fecha)  # ISO 8601


def test_historial_en_bloques_de_20(ana):
    """RF-06: del más reciente al más antiguo, con navegación entre bloques."""
    for i in range(1, 26):
        ana.post("/cuenta/cargar", data={"monto": str(i)})

    primera = ana.get("/historial").get_data(as_text=True)
    assert len(montos_en_tabla(primera)) == 20
    assert montos_en_tabla(primera)[0] == "+25 COP"
    assert "Más antiguos" in primera
    assert "Más recientes" not in primera

    segunda = ana.get("/historial?pagina=1").get_data(as_text=True)
    assert montos_en_tabla(segunda) == ["+5 COP", "+4 COP", "+3 COP", "+2 COP", "+1 COP"]
    assert "Más recientes" in segunda


def test_transferencias_enviadas_y_recibidas(cliente):
    cliente.post("/registro", data={"nombre": "beto", "password": "clave-segura"})
    cliente.post("/salir")
    cliente.post("/registro", data={"nombre": "ana", "password": "clave-segura"})
    cliente.post("/cuenta/cargar", data={"monto": "5000"})
    pagina = cliente.get("/cuenta").get_data(as_text=True)
    clave = re.search(r'name="clave_idempotencia" value="([^"]+)"', pagina).group(1)
    cliente.post("/cuenta/transferir", data={"destino": "beto", "monto": "2000", "clave_idempotencia": clave})

    de_ana = cliente.get("/historial").get_data(as_text=True)
    assert "Transferencia enviada" in de_ana
    assert montos_en_tabla(de_ana)[0] == "-2.000 COP"

    cliente.post("/salir")
    cliente.post("/entrar", data={"nombre": "beto", "password": "clave-segura"})
    de_beto = cliente.get("/historial").get_data(as_text=True)
    assert "Transferencia recibida" in de_beto
    assert montos_en_tabla(de_beto) == ["+2.000 COP"]


def test_panel_muestra_ultimos_5(ana):
    for i in range(1, 8):
        ana.post("/cuenta/cargar", data={"monto": str(i)})
    pagina = ana.get("/cuenta").get_data(as_text=True)
    assert montos_en_tabla(pagina) == ["+7 COP", "+6 COP", "+5 COP", "+4 COP", "+3 COP"]


def test_pagina_invalida_vuelve_al_inicio(ana):
    r = ana.get("/historial?pagina=abc", follow_redirects=True)
    assert "La página pedida no es válida." in r.get_data(as_text=True)


def test_historial_sin_sesion_redirige(cliente):
    """RNF-SEC-02"""
    assert cliente.get("/historial").status_code == 302
