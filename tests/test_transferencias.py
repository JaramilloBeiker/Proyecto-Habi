"""RF-04 Transferencias, RNF-R-02 Atomicidad, RNF-R-03 Idempotencia, RNF-SEC-02 Autorización."""

import pytest

pendiente = pytest.mark.skip(reason="Pendiente: implementar services/repository")


@pendiente
def test_transferencia_mueve_saldo(conn, crear_usuario):
    """RF-04"""


@pendiente
def test_transferencia_saldo_insuficiente_no_crea_movimientos(conn, crear_usuario):
    """RF-04: SaldoInsuficiente, saldos y movimientos sin cambios."""


@pendiente
def test_transferencia_a_si_mismo_rechazada(conn, crear_usuario):
    """RF-04: destino distinto al origen."""


@pendiente
def test_transferencia_a_destino_inexistente_rechazada(conn, crear_usuario):
    """RF-04: destino debe existir."""


@pendiente
def test_misma_clave_devuelve_resultado_original(conn, crear_usuario):
    """RNF-R-03: segunda llamada con la misma clave -> repetida=True y sin movimientos nuevos."""


@pendiente
def test_fallo_a_mitad_hace_rollback(conn, crear_usuario, monkeypatch):
    """RNF-R-02: forzar excepción tras el débito (monkeypatch en repository) y verificar saldos intactos."""
