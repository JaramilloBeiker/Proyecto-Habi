"""RF-01 Registro, RF-02 Inicio de sesión, RF-05 Consulta de saldo, RNF-SEC-01."""

import pytest

from habi import security, services
from habi.dominio import ErrorAutenticacion, ErrorValidacion, Usuario


def test_hash_no_guarda_password_en_claro_y_verifica():
    almacenado = security.hash_password("clave-segura")
    assert "clave-segura" not in almacenado
    assert security.verificar_password("clave-segura", almacenado)
    assert not security.verificar_password("otra-clave", almacenado)


def test_registro_crea_cuenta_con_saldo_cero(conn, crear_usuario):
    """RF-01"""
    usuario = crear_usuario("ana")
    assert usuario.nombre == "ana"
    assert services.consultar_saldo(conn, usuario) == 0
    guardado = conn.execute("SELECT password_hash FROM usuarios WHERE id = ?", (usuario.id,)).fetchone()[0]
    assert "clave-segura" not in guardado  # RNF-SEC-01


def test_registro_rechaza_nombre_duplicado(conn, crear_usuario):
    """RF-01: nombre único -> ErrorValidacion('nombre')."""
    crear_usuario("ana")
    with pytest.raises(ErrorValidacion) as e:
        crear_usuario("ana")
    assert e.value.campo == "nombre"
    assert conn.execute("SELECT COUNT(*) FROM cuentas WHERE tipo = 'USUARIO'").fetchone()[0] == 1


@pytest.mark.parametrize("nombre", ["", "   ", "FONDEO", "fondeo"])
def test_registro_rechaza_nombre_invalido(conn, nombre):
    with pytest.raises(ErrorValidacion) as e:
        services.registrar_usuario(conn, nombre, "clave-segura")
    assert e.value.campo == "nombre"


def test_registro_rechaza_password_corta(conn):
    """RF-01: menos de 8 caracteres -> ErrorValidacion('password')."""
    with pytest.raises(ErrorValidacion) as e:
        services.registrar_usuario(conn, "ana", "1234567")
    assert e.value.campo == "password"
    assert conn.execute("SELECT COUNT(*) FROM usuarios").fetchone()[0] == 0


def test_login_exitoso(conn, crear_usuario):
    """RF-02"""
    registrado = crear_usuario("ana", "clave-segura")
    usuario = services.iniciar_sesion(conn, "ana", "clave-segura")
    assert usuario == registrado
    assert isinstance(usuario, Usuario)


def test_login_rechaza_credenciales_invalidas(conn, crear_usuario):
    """RF-02 / RNF-SEC-01 -> ErrorAutenticacion, mismo mensaje en ambos casos."""
    crear_usuario("ana", "clave-segura")
    with pytest.raises(ErrorAutenticacion) as clave_mala:
        services.iniciar_sesion(conn, "ana", "clave-errada")
    with pytest.raises(ErrorAutenticacion) as no_existe:
        services.iniciar_sesion(conn, "nadie", "clave-segura")
    assert str(clave_mala.value) == str(no_existe.value)


def test_consultar_saldo(conn, crear_usuario):
    """RF-05"""
    ana = crear_usuario("ana")
    beto = crear_usuario("beto")
    assert services.consultar_saldo(conn, ana) == 0
    conn.execute("UPDATE cuentas SET saldo = 7000 WHERE id = ?", (ana.cuenta_id,))
    assert services.consultar_saldo(conn, ana) == 7000
    assert services.consultar_saldo(conn, beto) == 0


def test_consultar_saldo_sin_sesion(conn):
    """RNF-SEC-01: un usuario que no existe en la BD no puede consultar."""
    with pytest.raises(ErrorAutenticacion):
        services.consultar_saldo(conn, Usuario(id=999, nombre="x", cuenta_id=1))
