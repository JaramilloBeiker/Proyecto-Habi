"""RNF-R-04 Concurrencia."""

import pytest

pendiente = pytest.mark.skip(reason="Pendiente: implementar services/repository")


@pendiente
def test_20_transferencias_simultaneas_desde_10000(ruta_db):
    """RNF-R-04: cuenta con 10.000 COP, 20 hilos transfieren 1.000 COP cada uno
    (cada hilo con su propia conexión db.conectar(ruta_db) y su propia clave uuid).
    Esperado: 10 exitosas, 10 SaldoInsuficiente, saldo final 0.
    """
