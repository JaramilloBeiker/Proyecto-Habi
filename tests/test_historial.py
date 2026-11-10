"""RF-06 Historial de movimientos."""

import pytest

pendiente = pytest.mark.skip(reason="Pendiente: implementar services/repository")


@pendiente
def test_historial_ordenado_del_mas_reciente(conn, crear_usuario):
    """RF-06"""


@pendiente
def test_historial_paginado_en_bloques_de_20(conn, crear_usuario):
    """RF-06: 25 movimientos -> página 0 con 20, página 1 con 5."""


@pendiente
def test_historial_solo_de_la_cuenta_propia(conn, crear_usuario):
    """RNF-SEC-02: un usuario no ve movimientos de otro."""
