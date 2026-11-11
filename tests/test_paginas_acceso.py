"""Páginas de acceso: RF-01 registro, RF-02 inicio y cierre de sesión, RNF-SEC-01."""


def registrar_por_formulario(cliente, nombre="ana", password="clave-segura"):
    return cliente.post("/registro", data={"nombre": nombre, "password": password})


def test_inicio_sin_sesion_lleva_a_entrar(cliente):
    r = cliente.get("/")
    assert r.status_code == 302
    assert r.headers["Location"].endswith("/entrar")


def test_paginas_de_acceso_se_muestran(cliente):
    assert "Iniciar sesión" in cliente.get("/entrar").get_data(as_text=True)
    assert "Crear cuenta" in cliente.get("/registro").get_data(as_text=True)
    assert cliente.get("/static/css/estilos.css").status_code == 200


def test_registro_abre_sesion_y_muestra_saldo_cero(cliente):
    """RF-01"""
    r = registrar_por_formulario(cliente)
    assert r.headers["Location"].endswith("/cuenta")
    pagina = cliente.get("/cuenta").get_data(as_text=True)
    assert "Cuenta creada. Bienvenido, ana." in pagina
    assert "0 COP" in pagina


def test_registro_invalido_marca_el_campo(cliente, conn):
    """RNF-U-03"""
    r = registrar_por_formulario(cliente, password="corta")
    assert r.status_code == 400
    pagina = r.get_data(as_text=True)
    assert "Revisa los datos marcados." in pagina
    assert "campo--error" in pagina
    assert "Debe tener al menos 8 caracteres." in pagina
    assert conn.execute("SELECT COUNT(*) FROM usuarios").fetchone()[0] == 0


def test_registro_duplicado_conserva_el_nombre(cliente):
    registrar_por_formulario(cliente)
    cliente.post("/salir")
    r = registrar_por_formulario(cliente, password="otra-clave")
    pagina = r.get_data(as_text=True)
    assert "&#39;ana&#39; ya está registrado." in pagina
    assert 'value="ana"' in pagina


def test_entrar_y_salir(cliente):
    """RF-02"""
    registrar_por_formulario(cliente)
    cliente.post("/salir")
    assert cliente.get("/cuenta").status_code == 302

    r = cliente.post("/entrar", data={"nombre": "ana", "password": "clave-segura"})
    assert r.headers["Location"].endswith("/cuenta")
    assert "Cerrar sesión" in cliente.get("/cuenta").get_data(as_text=True)


def test_entrar_con_clave_errada_muestra_motivo(cliente):
    registrar_por_formulario(cliente)
    cliente.post("/salir")
    r = cliente.post("/entrar", data={"nombre": "ana", "password": "clave-errada"})
    assert r.status_code == 401
    assert "Usuario o contraseña incorrectos." in r.get_data(as_text=True)


def test_cuenta_sin_sesion_redirige(cliente):
    """RNF-SEC-01"""
    r = cliente.get("/cuenta")
    assert r.status_code == 302
    assert r.headers["Location"].endswith("/entrar")


def test_sesion_expirada_avisa(cliente, conn):
    registrar_por_formulario(cliente)
    conn.execute("UPDATE sesiones SET expira_en = '2000-01-01T00:00:00+00:00'")
    r = cliente.get("/cuenta", follow_redirects=True)
    assert "Tu sesión expiró" in r.get_data(as_text=True)


def test_cookie_vieja_no_sirve_despues_de_salir(cliente):
    """RF-02: cerrar sesión invalida el acceso anterior."""
    registrar_por_formulario(cliente)
    cookie_vieja = cliente.get_cookie("session").value
    cliente.post("/salir")
    cliente.set_cookie("session", cookie_vieja)
    assert cliente.get("/cuenta").status_code == 302
