"""Juntia, paso 5: endpoints JSON bajo /api/juntias."""

import pytest


@pytest.fixture
def entrar(cliente):
    """Registra (si hace falta) e inicia sesión con el usuario dado en el mismo cliente."""

    def _entrar(nombre: str):
        cliente.post("/api/registro", json={"nombre": nombre, "password": "clave-segura"})
        respuesta = cliente.post("/api/login", json={"nombre": nombre, "password": "clave-segura"})
        assert respuesta.status_code == 200

    return _entrar


@pytest.fixture
def bolsillo_compartido(cliente, entrar):
    """ana crea 'Viaje', aporta 50.000 e invita a beto, que acepta. Queda la sesión de ana."""
    entrar("beto")
    entrar("carla")
    entrar("ana")
    cliente.post("/api/cargas", json={"monto": 80_000})
    bolsillo_id = cliente.post("/api/juntias", json={"nombre": "Viaje", "meta": 500_000}).get_json()["bolsillo"]["id"]
    clave = cliente.get(f"/api/juntias/{bolsillo_id}/aportes/nueva").get_json()["clave_idempotencia"]
    cliente.post(f"/api/juntias/{bolsillo_id}/aportes", json={"monto": 50_000, "clave_idempotencia": clave})
    cliente.post(f"/api/juntias/{bolsillo_id}/invitaciones", json={"invitado": "beto"})
    entrar("beto")
    cliente.post(f"/api/juntias/{bolsillo_id}/aceptar")
    entrar("ana")
    return bolsillo_id


def test_juntias_requiere_sesion(cliente):
    assert cliente.get("/api/juntias").status_code == 401
    assert cliente.post("/api/juntias", json={"nombre": "x", "meta": 1}).status_code == 401


def test_crear_y_listar_bolsillo(cliente, entrar):
    entrar("ana")
    respuesta = cliente.post("/api/juntias", json={"nombre": "Regalo", "meta": "100000"})
    assert respuesta.status_code == 201
    datos = respuesta.get_json()["bolsillo"]
    assert (datos["nombre"], datos["meta"], datos["saldo"], datos["creador"]) == ("Regalo", 100_000, 0, "ana")

    lista = cliente.get("/api/juntias").get_json()
    assert [b["nombre"] for b in lista["bolsillos"]] == ["Regalo"]
    assert lista["invitaciones"] == []


def test_crear_bolsillo_con_datos_invalidos(cliente, entrar):
    entrar("ana")
    respuesta = cliente.post("/api/juntias", json={"nombre": "", "meta": 1000})
    assert respuesta.status_code == 400 and respuesta.get_json()["campo"] == "nombre"
    respuesta = cliente.post("/api/juntias", json={"nombre": "Viaje", "meta": "10,5"})
    assert respuesta.status_code == 400 and respuesta.get_json()["campo"] == "meta"


def test_detalle_con_miembros_y_aportes(cliente, bolsillo_compartido):
    datos = cliente.get(f"/api/juntias/{bolsillo_compartido}").get_json()
    assert datos["bolsillo"]["saldo"] == 50_000
    assert datos["bolsillo"]["disponible_cop"] == "50.000 COP"
    assert {m["nombre"]: m["aportado"] for m in datos["miembros"]} == {"ana": 50_000, "beto": 0}
    assert datos["retiros"] == []


def test_invitado_ve_la_invitacion_pero_no_el_saldo(cliente, entrar, bolsillo_compartido):
    cliente.post(f"/api/juntias/{bolsillo_compartido}/invitaciones", json={"invitado": "carla"})
    entrar("carla")
    invitaciones = cliente.get("/api/juntias").get_json()["invitaciones"]
    assert [(i["bolsillo"], i["invitado_por"]) for i in invitaciones] == [("Viaje", "ana")]
    assert "saldo" not in invitaciones[0]
    assert cliente.get(f"/api/juntias/{bolsillo_compartido}").status_code == 403

    assert cliente.post(f"/api/juntias/{bolsillo_compartido}/rechazar").status_code == 200
    assert cliente.post(f"/api/juntias/{bolsillo_compartido}/aceptar").status_code == 409


def test_no_miembro_recibe_404(cliente, entrar, bolsillo_compartido):
    entrar("carla")
    assert cliente.get(f"/api/juntias/{bolsillo_compartido}").status_code == 404
    assert cliente.get("/api/juntias/999").status_code == 404


def test_invitar_usuario_inexistente(cliente, bolsillo_compartido):
    respuesta = cliente.post(f"/api/juntias/{bolsillo_compartido}/invitaciones", json={"invitado": "nadie"})
    assert respuesta.status_code == 404


def test_aporte_repetido_no_se_duplica(cliente, bolsillo_compartido):
    clave = cliente.get(f"/api/juntias/{bolsillo_compartido}/aportes/nueva").get_json()["clave_idempotencia"]
    url = f"/api/juntias/{bolsillo_compartido}/aportes"
    primero = cliente.post(url, json={"monto": 1_000, "clave_idempotencia": clave})
    segundo = cliente.post(url, json={"monto": 1_000, "clave_idempotencia": clave})
    assert primero.status_code == 201 and segundo.status_code == 200
    assert segundo.get_json()["repetida"] is True
    assert segundo.get_json()["bolsillo"]["saldo"] == 51_000


def test_aporte_sin_clave_valida_o_sin_saldo(cliente, bolsillo_compartido):
    url = f"/api/juntias/{bolsillo_compartido}/aportes"
    respuesta = cliente.post(url, json={"monto": 1_000, "clave_idempotencia": "abc"})
    assert respuesta.status_code == 400 and respuesta.get_json()["campo"] == "clave_idempotencia"
    clave = cliente.get(f"/api/juntias/{bolsillo_compartido}/aportes/nueva").get_json()["clave_idempotencia"]
    respuesta = cliente.post(url, json={"monto": 30_001, "clave_idempotencia": clave})
    assert respuesta.status_code == 409


def test_historial_del_bolsillo(cliente, bolsillo_compartido):
    datos = cliente.get(f"/api/juntias/{bolsillo_compartido}/historial").get_json()
    assert [(m["contraparte"], m["monto"]) for m in datos["movimientos"]] == [("ana", 50_000)]
    personal = cliente.get("/api/historial").get_json()["movimientos"][0]
    assert (personal["contraparte"], personal["contraparte_tipo"]) == ("Viaje", "BOLSILLO")


def test_retiro_votado_por_todos_se_ejecuta(cliente, entrar, bolsillo_compartido):
    url = f"/api/juntias/{bolsillo_compartido}/retiros"
    respuesta = cliente.post(url, json={"destino": "carla", "monto": 20_000, "motivo": "Hotel"})
    assert respuesta.status_code == 201
    retiro = respuesta.get_json()["retiro"]
    assert retiro["estado"] == "PENDIENTE"
    assert cliente.get(f"/api/juntias/{bolsillo_compartido}").get_json()["bolsillo"]["reservado"] == 20_000

    entrar("beto")
    voto = cliente.post(f"{url}/{retiro['id']}/votos", json={"voto": "a_favor"})
    assert voto.status_code == 200
    assert voto.get_json()["retiro"]["estado"] == "EJECUTADO"
    entrar("carla")
    assert cliente.get("/api/saldo").get_json()["saldo"] == 20_000


def test_retiro_por_encima_de_lo_disponible(cliente, bolsillo_compartido):
    url = f"/api/juntias/{bolsillo_compartido}/retiros"
    cliente.post(url, json={"destino": "carla", "monto": 40_000})
    respuesta = cliente.post(url, json={"destino": "carla", "monto": 10_001})
    assert respuesta.status_code == 409
    assert "disponibles" in respuesta.get_json()["error"]


def test_voto_en_contra_y_voto_invalido(cliente, entrar, bolsillo_compartido):
    url = f"/api/juntias/{bolsillo_compartido}/retiros"
    retiro_id = cliente.post(url, json={"destino": "carla", "monto": 1_000}).get_json()["retiro"]["id"]
    entrar("beto")
    respuesta = cliente.post(f"{url}/{retiro_id}/votos", json={"voto": "quizas"})
    assert respuesta.status_code == 400 and respuesta.get_json()["campo"] == "voto"
    respuesta = cliente.post(f"{url}/{retiro_id}/votos", json={"voto": "EN_CONTRA"})
    assert respuesta.get_json()["retiro"]["estado"] == "RECHAZADO"
    assert cliente.post(f"{url}/{retiro_id}/votos", json={"voto": "A_FAVOR"}).status_code == 409


def test_salir_del_bolsillo(cliente, entrar, bolsillo_compartido):
    assert cliente.post(f"/api/juntias/{bolsillo_compartido}/salir").status_code == 409  # ana ya aportó
    entrar("beto")
    assert cliente.post(f"/api/juntias/{bolsillo_compartido}/salir").status_code == 200
    assert cliente.get("/api/juntias").get_json()["bolsillos"] == []
