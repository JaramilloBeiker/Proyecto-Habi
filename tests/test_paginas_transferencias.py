"""Formulario de transferencia: RF-04, RNF-R-03 idempotencia, RNF-U-01/03."""

import re

import pytest


@pytest.fixture
def ana(cliente):
    """beto existe; ana tiene sesión iniciada y 10.000 COP."""
    cliente.post("/registro", data={"nombre": "beto", "password": "clave-segura"})
    cliente.post("/salir")
    cliente.post("/registro", data={"nombre": "ana", "password": "clave-segura"})
    cliente.post("/cuenta/cargar", data={"monto": "10000"})
    return cliente


def clave_del_formulario(cliente) -> str:
    pagina = cliente.get("/cuenta").get_data(as_text=True)
    return re.search(r'name="clave_idempotencia" value="([^"]+)"', pagina).group(1)


def saldo_de(conn, nombre: str) -> int:
    return conn.execute(
        "SELECT c.saldo FROM cuentas c JOIN usuarios u ON u.id = c.usuario_id WHERE u.nombre = ?", (nombre,)
    ).fetchone()[0]


def contar_movimientos(conn) -> int:
    return conn.execute("SELECT COUNT(*) FROM movimientos").fetchone()[0]


def test_cada_formulario_trae_clave_nueva(ana):
    """RNF-R-03"""
    assert clave_del_formulario(ana) != clave_del_formulario(ana)


def test_transferencia_por_formulario(ana, conn):
    """RF-04"""
    datos = {"destino": "beto", "monto": "3000", "clave_idempotencia": clave_del_formulario(ana)}
    pagina = ana.post("/cuenta/transferir", data=datos, follow_redirects=True).get_data(as_text=True)
    assert "Transferencia de 3.000 COP a beto realizada." in pagina
    assert "7.000 COP" in pagina
    assert saldo_de(conn, "beto") == 3_000


def test_reenviar_el_formulario_no_repite(ana, conn):
    """RNF-R-03: doble clic o recarga envían la misma clave."""
    datos = {"destino": "beto", "monto": "1000", "clave_idempotencia": clave_del_formulario(ana)}
    ana.post("/cuenta/transferir", data=datos)
    movimientos = contar_movimientos(conn)

    pagina = ana.post("/cuenta/transferir", data=datos, follow_redirects=True).get_data(as_text=True)
    assert "ya se había realizado" in pagina
    assert contar_movimientos(conn) == movimientos
    assert saldo_de(conn, "ana") == 9_000


def test_saldo_insuficiente_muestra_motivo(ana, conn):
    """RF-04 / RNF-U-01"""
    datos = {"destino": "beto", "monto": "20000", "clave_idempotencia": clave_del_formulario(ana)}
    r = ana.post("/cuenta/transferir", data=datos)
    assert r.status_code == 409
    pagina = r.get_data(as_text=True)
    assert "Saldo insuficiente: tienes 10.000 COP y quieres transferir 20.000 COP." in pagina
    assert 'value="beto"' in pagina  # conserva lo escrito
    assert saldo_de(conn, "beto") == 0


@pytest.mark.parametrize(
    "cambios, motivo",
    [
        ({"destino": "nadie"}, "No existe un usuario con ese nombre."),
        ({"destino": "ana"}, "No puedes transferirte a ti mismo."),
        ({"destino": ""}, "Es obligatorio."),
        ({"monto": "1,5"}, "Debe ser un número entero positivo"),
        ({"monto": "5000001"}, "No puede superar 5.000.000 COP."),
    ],
)
def test_datos_invalidos_marcan_el_campo(ana, conn, cambios, motivo):
    """RNF-U-03"""
    datos = {"destino": "beto", "monto": "1000", "clave_idempotencia": clave_del_formulario(ana), **cambios}
    pagina = ana.post("/cuenta/transferir", data=datos).get_data(as_text=True)
    assert motivo in pagina
    assert "campo--error" in pagina
    assert saldo_de(conn, "ana") == 10_000


def test_clave_invalida_entrega_formulario_nuevo(ana, conn):
    datos = {"destino": "beto", "monto": "1000", "clave_idempotencia": "inventada"}
    pagina = ana.post("/cuenta/transferir", data=datos).get_data(as_text=True)
    assert "Este formulario ya no es válido" in pagina
    assert 'value="inventada"' not in pagina
    assert saldo_de(conn, "ana") == 10_000


def test_transferir_sin_sesion_redirige(cliente):
    r = cliente.post("/cuenta/transferir", data={"destino": "beto", "monto": "1"})
    assert r.status_code == 302
