"""Rutas de RF-03 Carga, RF-05 Saldo, RF-06 Historial, RNF-U-02/03 y RNF-SEC-02."""

import pytest

from habi.formato import formatear_cop


def test_formatear_cop():
    """RNF-U-02"""
    assert formatear_cop(50_000) == "50.000 COP"
    assert formatear_cop(5_000_000) == "5.000.000 COP"
    assert formatear_cop(0) == "0 COP"


@pytest.mark.parametrize("ruta", ["/api/saldo", "/api/historial"])
def test_rutas_de_cuenta_requieren_sesion(cliente, ruta):
    """RNF-SEC-01"""
    assert cliente.get(ruta).status_code == 401


def test_carga_requiere_sesion(cliente):
    assert cliente.post("/api/cargas", json={"monto": 1000}).status_code == 401


def test_saldo_inicial_cero(cliente, registrar_y_entrar):
    """RF-05"""
    registrar_y_entrar("ana")
    r = cliente.get("/api/saldo")
    assert r.status_code == 200
    assert r.get_json()["saldo"] == 0
    assert r.get_json()["saldo_cop"] == "0 COP"


def test_carga_por_api(cliente, registrar_y_entrar):
    """RF-03"""
    registrar_y_entrar("ana")
    r = cliente.post("/api/cargas", json={"monto": 50_000})
    assert r.status_code == 201
    datos = r.get_json()
    assert datos["mensaje"] == "Carga de 50.000 COP registrada."
    assert datos["saldo_cop"] == "50.000 COP"
    assert cliente.get("/api/saldo").get_json()["saldo"] == 50_000


def test_carga_desde_formulario_html(cliente, registrar_y_entrar):
    registrar_y_entrar("ana")
    assert cliente.post("/api/cargas", data={"monto": "7000"}).status_code == 201
    assert cliente.get("/api/saldo").get_json()["saldo"] == 7_000


@pytest.mark.parametrize("monto", [0, -5, 10.5, "10.5", "1.000", "abc", "", None, True, 5_000_001])
def test_carga_invalida_indica_campo_y_no_cambia_saldo(cliente, registrar_y_entrar, conn, monto):
    """RNF-U-03 / RNF-D-02"""
    registrar_y_entrar("ana")
    r = cliente.post("/api/cargas", json={"monto": monto})
    assert r.status_code == 400
    assert r.get_json()["campo"] == "monto"
    assert cliente.get("/api/saldo").get_json()["saldo"] == 0
    assert conn.execute("SELECT COUNT(*) FROM movimientos").fetchone()[0] == 0


def test_cada_usuario_ve_solo_su_saldo(cliente, ruta_db, registrar_y_entrar):
    """RNF-SEC-02: el saldo sale de la sesión, no de un parámetro de la petición."""
    from habi.web import crear_app

    registrar_y_entrar("ana")
    cliente.post("/api/cargas", json={"monto": 9_000})

    otro = crear_app(ruta_db, secret_key="clave-de-pruebas").test_client()
    otro.post("/api/registro", json={"nombre": "beto", "password": "clave-segura"})
    otro.post("/api/login", json={"nombre": "beto", "password": "clave-segura"})
    assert otro.get("/api/saldo?usuario=ana").get_json()["saldo"] == 0
    assert otro.get("/api/historial?usuario=ana").get_json()["movimientos"] == []


def test_historial_por_api(cliente, registrar_y_entrar):
    """RF-06: más reciente primero, montos con signo y fecha ISO 8601."""
    registrar_y_entrar("ana")
    cliente.post("/api/cargas", json={"monto": 1_000})
    cliente.post("/api/cargas", json={"monto": 2_000})

    datos = cliente.get("/api/historial").get_json()
    assert datos["hay_mas"] is False
    primero = datos["movimientos"][0]
    assert primero["monto"] == 2_000
    assert primero["monto_cop"] == "+2.000 COP"
    assert primero["tipo"] == "CARGA"
    assert primero["contraparte"] == "FONDEO"
    assert "T" in primero["fecha"]  # ISO 8601


def test_historial_en_bloques_de_20(cliente, registrar_y_entrar):
    """RF-06"""
    registrar_y_entrar("ana")
    for i in range(1, 26):
        cliente.post("/api/cargas", json={"monto": i})

    pagina0 = cliente.get("/api/historial").get_json()
    pagina1 = cliente.get("/api/historial?pagina=1").get_json()
    assert len(pagina0["movimientos"]) == 20
    assert pagina0["hay_mas"] is True
    assert pagina0["movimientos"][0]["monto"] == 25
    assert [m["monto"] for m in pagina1["movimientos"]] == [5, 4, 3, 2, 1]


@pytest.mark.parametrize("pagina", ["-1", "abc", "1.5"])
def test_historial_pagina_invalida(cliente, registrar_y_entrar, pagina):
    registrar_y_entrar("ana")
    r = cliente.get(f"/api/historial?pagina={pagina}")
    assert r.status_code == 400
    assert r.get_json()["campo"] == "pagina"
