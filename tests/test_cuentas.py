"""RF-01 Registro, RF-02 Inicio de sesión, RF-05 Consulta de saldo, RNF-SEC-01."""

import pytest

from habi import security

pendiente = pytest.mark.skip(reason="Pendiente: implementar services/repository")


def test_hash_no_guarda_password_en_claro_y_verifica():
    almacenado = security.hash_password("clave-segura")
    assert "clave-segura" not in almacenado
    assert security.verificar_password("clave-segura", almacenado)
    assert not security.verificar_password("otra-clave", almacenado)


@pendiente
def test_registro_crea_cuenta_con_saldo_cero(conn, crear_usuario):
    """RF-01"""


@pendiente
def test_registro_rechaza_nombre_duplicado(conn, crear_usuario):
    """RF-01: nombre único -> ErrorValidacion('nombre')."""


@pendiente
def test_registro_rechaza_password_corta(conn):
    """RF-01: menos de 8 caracteres -> ErrorValidacion('password')."""


@pendiente
def test_login_exitoso(conn, crear_usuario):
    """RF-02"""


@pendiente
def test_login_rechaza_credenciales_invalidas(conn, crear_usuario):
    """RF-02 / RNF-SEC-01 -> ErrorAutenticacion."""


@pendiente
def test_consultar_saldo(conn, crear_usuario):
    """RF-05"""
