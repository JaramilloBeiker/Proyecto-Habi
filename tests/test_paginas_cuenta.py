"""Panel de cuenta: RF-05 saldo y RF-03 carga desde el formulario."""

import pytest


@pytest.fixture
def ana(cliente):
    """ana registrada y con sesión iniciada por formulario."""
    cliente.post("/registro", data={"nombre": "ana", "password": "clave-segura"})
    return cliente


def test_panel_muestra_saldo_y_formulario_de_carga(ana):
    """RF-05"""
    pagina = ana.get("/cuenta").get_data(as_text=True)
    assert "Saldo disponible" in pagina
    assert "0 COP" in pagina
    assert 'action="/cuenta/cargar"' in pagina


def test_carga_por_formulario(ana):
    """RF-03 / RNF-U-01 / RNF-U-02"""
    r = ana.post("/cuenta/cargar", data={"monto": "50000"}, follow_redirects=True)
    pagina = r.get_data(as_text=True)
    assert "Carga de 50.000 COP registrada." in pagina
    assert "50.000 COP" in pagina


@pytest.mark.parametrize(
    "monto, motivo",
    [
        ("", "Debe ser un número entero positivo"),
        ("10.5", "Debe ser un número entero positivo"),
        ("0", "Debe ser mayor o igual a 1 COP"),
        ("5000001", "No puede superar 5.000.000 COP"),
    ],
)
def test_carga_invalida_marca_el_campo(ana, conn, monto, motivo):
    """RNF-U-03: el error se muestra junto al campo y no cambia nada."""
    r = ana.post("/cuenta/cargar", data={"monto": monto})
    assert r.status_code == 400
    pagina = r.get_data(as_text=True)
    assert motivo in pagina
    assert "campo--error" in pagina
    assert conn.execute("SELECT COUNT(*) FROM movimientos").fetchone()[0] == 0


def test_carga_sin_sesion_redirige(cliente, conn):
    r = cliente.post("/cuenta/cargar", data={"monto": "1000"})
    assert r.status_code == 302
    assert conn.execute("SELECT COUNT(*) FROM movimientos").fetchone()[0] == 0
