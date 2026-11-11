"""Juntia, paso 2: bolsillos, miembros, invitaciones y aceptación."""

import pytest

from habi import services
from habi.dominio import ErrorAutorizacion, ErrorValidacion, NoEncontrado, OperacionNoPermitida


def test_crear_bolsillo_deja_al_creador_activo_con_saldo_cero(conn, crear_usuario):
    ana = crear_usuario("ana")
    bolsillo = services.crear_bolsillo(conn, ana, "  Viaje a Cartagena ", 2_000_000)
    assert bolsillo.nombre == "Viaje a Cartagena"
    assert bolsillo.meta == 2_000_000
    assert bolsillo.saldo == 0
    assert bolsillo.creador == "ana"
    assert [(m.nombre, m.estado) for m in services.miembros_de_bolsillo(conn, ana, bolsillo.id)] == [
        ("ana", "ACTIVO")
    ]
    assert [b.id for b in services.listar_bolsillos(conn, ana)] == [bolsillo.id]


def test_bolsillo_tiene_su_propia_cuenta(conn, crear_usuario):
    ana = crear_usuario("ana")
    bolsillo = services.crear_bolsillo(conn, ana, "Regalo", 100_000)
    fila = conn.execute(
        "SELECT c.tipo, c.usuario_id FROM bolsillos b JOIN cuentas c ON c.id = b.cuenta_id WHERE b.id = ?",
        (bolsillo.id,),
    ).fetchone()
    assert tuple(fila) == ("BOLSILLO", None)


@pytest.mark.parametrize(
    "nombre, meta, campo",
    [
        ("", 1_000, "nombre"),
        ("x" * 61, 1_000, "nombre"),
        ("Viaje", 0, "meta"),
        ("Viaje", 1_000_000_001, "meta"),
        ("Viaje", 10.5, "meta"),
        ("Viaje", True, "meta"),
    ],
)
def test_crear_bolsillo_valida_datos(conn, crear_usuario, nombre, meta, campo):
    ana = crear_usuario("ana")
    with pytest.raises(ErrorValidacion) as e:
        services.crear_bolsillo(conn, ana, nombre, meta)
    assert e.value.campo == campo


def test_invitado_no_ve_el_saldo_hasta_aceptar(conn, crear_usuario):
    ana = crear_usuario("ana")
    beto = crear_usuario("beto")
    bolsillo = services.crear_bolsillo(conn, ana, "Viaje", 500_000)
    services.invitar_a_bolsillo(conn, ana, bolsillo.id, "beto")

    with pytest.raises(ErrorAutorizacion):
        services.ver_bolsillo(conn, beto, bolsillo.id)
    assert services.listar_bolsillos(conn, beto) == []
    invitaciones = services.listar_invitaciones(conn, beto)
    assert [(i.bolsillo_nombre, i.invitado_por) for i in invitaciones] == [("Viaje", "ana")]

    services.aceptar_invitacion(conn, beto, bolsillo.id)
    assert services.ver_bolsillo(conn, beto, bolsillo.id).saldo == 0
    assert services.listar_invitaciones(conn, beto) == []
    estados = {m.nombre: m.estado for m in services.miembros_de_bolsillo(conn, ana, bolsillo.id)}
    assert estados == {"ana": "ACTIVO", "beto": "ACTIVO"}


def test_quien_no_fue_invitado_no_ve_el_bolsillo(conn, crear_usuario):
    ana = crear_usuario("ana")
    carla = crear_usuario("carla")
    bolsillo = services.crear_bolsillo(conn, ana, "Viaje", 500_000)
    with pytest.raises(NoEncontrado):
        services.ver_bolsillo(conn, carla, bolsillo.id)
    with pytest.raises(NoEncontrado):
        services.invitar_a_bolsillo(conn, carla, bolsillo.id, "carla")


def test_bolsillo_inexistente(conn, crear_usuario):
    ana = crear_usuario("ana")
    with pytest.raises(NoEncontrado):
        services.ver_bolsillo(conn, ana, 999)
    with pytest.raises(NoEncontrado):
        services.aceptar_invitacion(conn, ana, 999)


def test_invitado_pendiente_no_puede_invitar(conn, crear_usuario):
    ana = crear_usuario("ana")
    crear_usuario("beto")
    crear_usuario("carla")
    bolsillo = services.crear_bolsillo(conn, ana, "Viaje", 500_000)
    services.invitar_a_bolsillo(conn, ana, bolsillo.id, "beto")
    beto = services.iniciar_sesion(conn, "beto", "clave-segura")
    with pytest.raises(ErrorAutorizacion):
        services.invitar_a_bolsillo(conn, beto, bolsillo.id, "carla")


def test_invitar_valida_destinatario(conn, crear_usuario):
    ana = crear_usuario("ana")
    crear_usuario("beto")
    bolsillo = services.crear_bolsillo(conn, ana, "Viaje", 500_000)

    with pytest.raises(ErrorValidacion) as e:
        services.invitar_a_bolsillo(conn, ana, bolsillo.id, "   ")
    assert e.value.campo == "invitado"
    with pytest.raises(NoEncontrado):
        services.invitar_a_bolsillo(conn, ana, bolsillo.id, "nadie")
    with pytest.raises(ErrorValidacion, match="ya es miembro"):
        services.invitar_a_bolsillo(conn, ana, bolsillo.id, "ana")

    services.invitar_a_bolsillo(conn, ana, bolsillo.id, "beto")
    with pytest.raises(ErrorValidacion, match="invitación pendiente"):
        services.invitar_a_bolsillo(conn, ana, bolsillo.id, "beto")


def test_rechazar_invitacion_y_volver_a_invitar(conn, crear_usuario):
    ana = crear_usuario("ana")
    beto = crear_usuario("beto")
    bolsillo = services.crear_bolsillo(conn, ana, "Viaje", 500_000)
    services.invitar_a_bolsillo(conn, ana, bolsillo.id, "beto")
    services.rechazar_invitacion(conn, beto, bolsillo.id)

    with pytest.raises(ErrorAutorizacion):
        services.ver_bolsillo(conn, beto, bolsillo.id)
    with pytest.raises(OperacionNoPermitida):
        services.aceptar_invitacion(conn, beto, bolsillo.id)

    services.invitar_a_bolsillo(conn, ana, bolsillo.id, "beto")
    services.aceptar_invitacion(conn, beto, bolsillo.id)
    assert [b.id for b in services.listar_bolsillos(conn, beto)] == [bolsillo.id]


def test_aceptar_sin_invitacion(conn, crear_usuario):
    ana = crear_usuario("ana")
    bolsillo = services.crear_bolsillo(conn, ana, "Viaje", 500_000)
    with pytest.raises(OperacionNoPermitida):
        services.aceptar_invitacion(conn, ana, bolsillo.id)  # ya es miembro activo
