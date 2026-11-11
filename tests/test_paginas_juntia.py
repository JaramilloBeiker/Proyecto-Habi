"""Juntia, paso 5: páginas HTML de bolsillos, aportes, retiros y votos."""

import re

import pytest


def entrar(cliente, nombre: str) -> None:
    """Registra (si hace falta) e inicia sesión por las páginas."""
    cliente.post("/salir")
    cliente.post("/registro", data={"nombre": nombre, "password": "clave-segura"})
    cliente.post("/entrar", data={"nombre": nombre, "password": "clave-segura"})


def clave_de_aporte(cliente, bolsillo_id: int) -> str:
    pagina = cliente.get(f"/juntias/{bolsillo_id}").get_data(as_text=True)
    return re.search(r'name="clave_idempotencia" value="([^"]+)"', pagina).group(1)


def saldo_de(conn, nombre: str) -> int:
    return conn.execute(
        "SELECT c.saldo FROM cuentas c JOIN usuarios u ON u.id = c.usuario_id WHERE u.nombre = ?", (nombre,)
    ).fetchone()[0]


@pytest.fixture
def viaje(cliente):
    """ana crea 'Viaje', aporta 40.000 e invita a beto, que acepta. Queda la sesión de ana."""
    entrar(cliente, "carla")
    entrar(cliente, "beto")
    entrar(cliente, "ana")
    cliente.post("/cuenta/cargar", data={"monto": "60000"})
    respuesta = cliente.post("/juntias/crear", data={"nombre": "Viaje", "meta": "200000"})
    bolsillo_id = int(respuesta.headers["Location"].rstrip("/").split("/")[-1])
    cliente.post(f"/juntias/{bolsillo_id}/aportar",
                 data={"monto": "40000", "clave_idempotencia": clave_de_aporte(cliente, bolsillo_id)})
    cliente.post(f"/juntias/{bolsillo_id}/invitar", data={"invitado": "beto"})
    entrar(cliente, "beto")
    cliente.post(f"/juntias/{bolsillo_id}/aceptar")
    entrar(cliente, "ana")
    return bolsillo_id


def test_juntias_sin_sesion_redirige(cliente):
    assert cliente.get("/juntias").status_code == 302
    assert cliente.get("/juntias/1").status_code == 302


def test_lista_vacia_y_enlace_en_la_navegacion(cliente):
    entrar(cliente, "ana")
    html = cliente.get("/juntias").get_data(as_text=True)
    assert "Aún no participas en ningún bolsillo." in html
    assert 'href="/juntias"' in cliente.get("/cuenta").get_data(as_text=True)


def test_crear_bolsillo_lleva_al_detalle(cliente):
    entrar(cliente, "ana")
    respuesta = cliente.post("/juntias/crear", data={"nombre": "Regalo", "meta": "100000"}, follow_redirects=True)
    html = respuesta.get_data(as_text=True)
    assert "Bolsillo Regalo creado" in html
    assert "Saldo del bolsillo" in html
    assert "0 % de la meta de 100.000 COP" in html


def test_crear_bolsillo_invalido_marca_el_campo(cliente):
    entrar(cliente, "ana")
    respuesta = cliente.post("/juntias/crear", data={"nombre": "Viaje", "meta": "abc"})
    assert respuesta.status_code == 400
    html = respuesta.get_data(as_text=True)
    assert "campo--error" in html and 'value="Viaje"' in html


def test_detalle_muestra_saldo_miembros_y_movimientos(cliente, viaje):
    html = cliente.get(f"/juntias/{viaje}").get_data(as_text=True)
    assert "40.000 COP" in html
    assert "20 % de la meta de 200.000 COP" in html
    assert "Aportó 40.000 COP" in html
    assert "Aporte" in html and "beto" in html


def test_invitado_ve_la_invitacion_y_no_el_detalle(cliente, viaje):
    cliente.post(f"/juntias/{viaje}/invitar", data={"invitado": "carla"})
    entrar(cliente, "carla")
    html = cliente.get("/juntias").get_data(as_text=True)
    assert "Invitaciones pendientes" in html and "te invitó ana" in html
    assert "40.000" not in html

    respuesta = cliente.get(f"/juntias/{viaje}", follow_redirects=True)
    assert "Debes aceptar la invitación" in respuesta.get_data(as_text=True)


def test_invitar_usuario_inexistente_marca_el_campo(cliente, viaje):
    respuesta = cliente.post(f"/juntias/{viaje}/invitar", data={"invitado": "nadie"})
    assert respuesta.status_code == 404
    assert "No existe un usuario con ese nombre." in respuesta.get_data(as_text=True)


def test_reenviar_aporte_no_lo_repite(cliente, conn, viaje):
    datos = {"monto": "1000", "clave_idempotencia": clave_de_aporte(cliente, viaje)}
    cliente.post(f"/juntias/{viaje}/aportar", data=datos)
    respuesta = cliente.post(f"/juntias/{viaje}/aportar", data=datos, follow_redirects=True)
    assert "no se repitió" in respuesta.get_data(as_text=True)
    assert saldo_de(conn, "ana") == 19_000


def test_aporte_sin_saldo_muestra_motivo(cliente, viaje):
    datos = {"monto": "20001", "clave_idempotencia": clave_de_aporte(cliente, viaje)}
    respuesta = cliente.post(f"/juntias/{viaje}/aportar", data=datos)
    assert respuesta.status_code == 409
    assert "Saldo insuficiente" in respuesta.get_data(as_text=True)


def test_retiro_propuesto_votado_y_ejecutado(cliente, conn, viaje):
    respuesta = cliente.post(f"/juntias/{viaje}/retiros",
                             data={"destino": "carla", "monto": "15000", "motivo": "Hotel"}, follow_redirects=True)
    html = respuesta.get_data(as_text=True)
    assert "queda reservado" in html
    assert "Pendiente" in html and "Hotel" in html

    entrar(cliente, "beto")
    html = cliente.get(f"/juntias/{viaje}").get_data(as_text=True)
    retiro_id = re.search(r"/retiros/(\d+)/votar", html).group(1)
    respuesta = cliente.post(f"/juntias/{viaje}/retiros/{retiro_id}/votar", data={"voto": "A_FAVOR"},
                             follow_redirects=True)
    assert "Todos votaron a favor" in respuesta.get_data(as_text=True)
    assert saldo_de(conn, "carla") == 15_000


def test_quien_ya_voto_no_ve_los_botones(cliente, viaje):
    cliente.post(f"/juntias/{viaje}/retiros", data={"destino": "carla", "monto": "1000"})
    html = cliente.get(f"/juntias/{viaje}").get_data(as_text=True)
    assert "/votar" not in html  # ana propuso: su voto a favor ya cuenta


def test_retiro_mayor_a_lo_disponible(cliente, viaje):
    respuesta = cliente.post(f"/juntias/{viaje}/retiros", data={"destino": "carla", "monto": "40001"})
    assert respuesta.status_code == 409
    assert "disponibles" in respuesta.get_data(as_text=True)


def test_retiro_a_destino_inexistente_marca_el_campo(cliente, viaje):
    respuesta = cliente.post(f"/juntias/{viaje}/retiros", data={"destino": "nadie", "monto": "1000"})
    assert respuesta.status_code == 404
    assert "No existe un usuario con ese nombre." in respuesta.get_data(as_text=True)


def test_salir_del_bolsillo(cliente, viaje):
    respuesta = cliente.post(f"/juntias/{viaje}/salir", follow_redirects=True)
    assert "no puedes salir" in respuesta.get_data(as_text=True)  # ana ya aportó
    entrar(cliente, "beto")
    respuesta = cliente.post(f"/juntias/{viaje}/salir", follow_redirects=True)
    assert "Saliste del bolsillo." in respuesta.get_data(as_text=True)


def test_historial_personal_nombra_el_bolsillo(cliente, viaje):
    html = cliente.get("/historial").get_data(as_text=True)
    assert "Aporte a Juntia" in html and "Viaje" in html
