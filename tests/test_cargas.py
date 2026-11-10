"""RF-03 Carga de saldo, RNF-D-02 Validación de montos."""

import pytest

pendiente = pytest.mark.skip(reason="Pendiente: implementar services/repository")


@pendiente
def test_carga_aumenta_saldo(conn, crear_usuario):
    """RF-03"""


@pendiente
def test_carga_crea_contrapartida_en_fondeo(conn, crear_usuario):
    """RF-03 / RNF-D-05: movimiento -monto en fondeo y +monto en el usuario."""


@pendiente
@pytest.mark.parametrize("monto", [0, -1, 5_000_001, 1.5, "100", True])
def test_carga_rechaza_montos_invalidos(conn, crear_usuario, monto):
    """RNF-D-02 / RNF-U-03: error de validación y saldos sin cambios."""


@pendiente
@pytest.mark.parametrize("monto", [1, 5_000_000])
def test_carga_acepta_limites(conn, crear_usuario, monto):
    """RNF-D-02: los extremos del rango son válidos."""
