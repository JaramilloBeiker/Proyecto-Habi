"""Rutas de RF-01 Registro, RF-02 Inicio/cierre de sesión y RNF-SEC-01."""

from datetime import timedelta


def test_registro_por_api(cliente, conn):
    """RF-01"""
    r = cliente.post("/api/registro", json={"nombre": "ana", "password": "clave-segura"})
    assert r.status_code == 201
    assert r.get_json()["ok"] is True
    assert conn.execute("SELECT COUNT(*) FROM usuarios WHERE nombre = 'ana'").fetchone()[0] == 1


def test_registro_acepta_formulario_html(cliente):
    r = cliente.post("/api/registro", data={"nombre": "ana", "password": "clave-segura"})
    assert r.status_code == 201


def test_registro_duplicado_indica_campo(cliente):
    """RF-01 / RNF-U-03"""
    cliente.post("/api/registro", json={"nombre": "ana", "password": "clave-segura"})
    r = cliente.post("/api/registro", json={"nombre": "ana", "password": "otra-clave"})
    assert r.status_code == 400
    assert r.get_json() == {"ok": False, "error": "nombre: 'ana' ya está registrado", "campo": "nombre"}


def test_registro_password_corta(cliente):
    r = cliente.post("/api/registro", json={"nombre": "ana", "password": "corta"})
    assert r.status_code == 400
    assert r.get_json()["campo"] == "password"


def test_login_y_sesion_activa(cliente, registrar_y_entrar):
    """RF-02"""
    registrar_y_entrar("ana")
    r = cliente.get("/api/sesion")
    assert r.status_code == 200
    assert r.get_json()["usuario"] == {"nombre": "ana"}


def test_login_credenciales_invalidas(cliente):
    cliente.post("/api/registro", json={"nombre": "ana", "password": "clave-segura"})
    r = cliente.post("/api/login", json={"nombre": "ana", "password": "clave-errada"})
    assert r.status_code == 401
    assert r.get_json()["ok"] is False
    assert cliente.get("/api/sesion").status_code == 401


def test_sin_sesion_rechaza(cliente):
    """RNF-SEC-01"""
    r = cliente.get("/api/sesion")
    assert r.status_code == 401
    assert r.get_json()["error"] == "Debes iniciar sesión."


def test_logout_invalida_la_cookie_anterior(cliente, registrar_y_entrar):
    """RF-02: aunque alguien guarde la cookie vieja, después del logout ya no sirve."""
    registrar_y_entrar("ana")
    cookie_vieja = cliente.get_cookie("session").value

    assert cliente.post("/api/logout").status_code == 200
    assert cliente.get("/api/sesion").status_code == 401

    cliente.set_cookie("session", cookie_vieja)
    assert cliente.get("/api/sesion").status_code == 401


def test_sesion_expira(cliente, registrar_y_entrar, conn):
    """RNF-SEC-01: pasada la hora de expiración, la sesión se rechaza."""
    registrar_y_entrar("ana")
    conn.execute("UPDATE sesiones SET expira_en = '2000-01-01T00:00:00+00:00'")
    r = cliente.get("/api/sesion")
    assert r.status_code == 401
    assert "expiró" in r.get_json()["error"]


def test_cookie_firmada_dura_60_minutos(cliente, registrar_y_entrar, conn):
    """RNF-SEC-01: la cookie es permanente con vida de 60 minutos y no guarda la contraseña."""
    assert cliente.application.permanent_session_lifetime == timedelta(minutes=60)
    registrar_y_entrar("ana")
    cookie = cliente.get_cookie("session")
    assert cookie.expires is not None
    assert "clave-segura" not in cookie.value
    assert conn.execute("SELECT COUNT(*) FROM sesiones").fetchone()[0] == 1
