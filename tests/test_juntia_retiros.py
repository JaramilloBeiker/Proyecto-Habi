"""Juntia, paso 4: propuestas de retiro, votos, reserva de saldo y expiración pasiva."""

import uuid

import pytest

from habi import services
from habi.dominio import (
    ErrorAutorizacion,
    ErrorValidacion,
    NoEncontrado,
    OperacionNoPermitida,
    SaldoInsuficiente,
)


def _clave() -> str:
    return str(uuid.uuid4())


def _vencer(conn, retiro_id: int) -> None:
    """Simula que pasaron los 7 días moviendo la fecha límite al pasado."""
    conn.execute("UPDATE retiros SET expira_en = '2000-01-01T00:00:00+00:00' WHERE id = ?", (retiro_id,))


@pytest.fixture
def escenario(conn, crear_usuario):
    """Bolsillo 'Viaje' con ana y beto activos y 100.000 COP aportados. carla no es miembro."""
    ana = crear_usuario("ana", saldo=100_000)
    beto = crear_usuario("beto")
    carla = crear_usuario("carla")
    bolsillo = services.crear_bolsillo(conn, ana, "Viaje", 1_000_000)
    services.invitar_a_bolsillo(conn, ana, bolsillo.id, "beto")
    services.aceptar_invitacion(conn, beto, bolsillo.id)
    services.aportar_a_bolsillo(conn, ana, bolsillo.id, 100_000, _clave())
    return ana, beto, carla, bolsillo


def test_propuesta_reserva_el_monto_sin_mover_dinero(conn, escenario):
    ana, beto, _, bolsillo = escenario
    retiro = services.proponer_retiro(conn, ana, bolsillo.id, "carla", 30_000, "Tiquetes")

    assert retiro.estado == "PENDIENTE"
    assert (retiro.destino, retiro.proponente, retiro.motivo) == ("carla", "ana", "Tiquetes")
    assert retiro.voto_de("ana").voto == "A_FAVOR"   # quien propone vota a favor
    assert retiro.voto_de("beto").voto is None
    detalle = services.ver_bolsillo(conn, beto, bolsillo.id)
    assert (detalle.saldo, detalle.reservado, detalle.disponible) == (100_000, 30_000, 70_000)


def test_lo_reservado_no_se_puede_volver_a_gastar(conn, escenario):
    ana, beto, _, bolsillo = escenario
    services.proponer_retiro(conn, ana, bolsillo.id, "carla", 80_000)
    with pytest.raises(SaldoInsuficiente, match="20.000 COP disponibles"):
        services.proponer_retiro(conn, beto, bolsillo.id, "beto", 20_001)
    services.proponer_retiro(conn, beto, bolsillo.id, "beto", 20_000)  # justo lo disponible
    assert services.ver_bolsillo(conn, ana, bolsillo.id).disponible == 0


def test_retiro_se_ejecuta_cuando_todos_votan_a_favor(conn, escenario):
    ana, beto, carla, bolsillo = escenario
    retiro = services.proponer_retiro(conn, ana, bolsillo.id, "carla", 30_000)
    retiro = services.votar_retiro(conn, beto, bolsillo.id, retiro.id, "A_FAVOR")

    assert retiro.estado == "EJECUTADO"
    assert services.consultar_saldo(conn, carla) == 30_000
    detalle = services.ver_bolsillo(conn, ana, bolsillo.id)
    assert (detalle.saldo, detalle.reservado) == (70_000, 0)
    ultimo = services.historial_bolsillo(conn, ana, bolsillo.id)[0]
    assert (ultimo.contraparte, ultimo.monto) == ("carla", -30_000)


def test_un_voto_en_contra_cancela_y_libera_la_reserva(conn, escenario):
    ana, beto, carla, bolsillo = escenario
    retiro = services.proponer_retiro(conn, ana, bolsillo.id, "carla", 30_000)
    retiro = services.votar_retiro(conn, beto, bolsillo.id, retiro.id, "EN_CONTRA")

    assert retiro.estado == "RECHAZADO"
    assert services.consultar_saldo(conn, carla) == 0
    assert services.ver_bolsillo(conn, ana, bolsillo.id).disponible == 100_000


def test_unico_miembro_activo_ejecuta_de_inmediato(conn, crear_usuario):
    ana = crear_usuario("ana", saldo=10_000)
    beto = crear_usuario("beto")
    bolsillo = services.crear_bolsillo(conn, ana, "Solo", 50_000)
    services.aportar_a_bolsillo(conn, ana, bolsillo.id, 10_000, _clave())
    retiro = services.proponer_retiro(conn, ana, bolsillo.id, "beto", 4_000)
    assert retiro.estado == "EJECUTADO"
    assert services.consultar_saldo(conn, beto) == 4_000


def test_solo_votan_los_activos_al_proponer(conn, escenario, crear_usuario):
    """Quien entra después de la propuesta no vota ni bloquea la ejecución."""
    ana, beto, _, bolsillo = escenario
    dani = crear_usuario("dani")
    retiro = services.proponer_retiro(conn, ana, bolsillo.id, "carla", 10_000)
    services.invitar_a_bolsillo(conn, ana, bolsillo.id, "dani")
    services.aceptar_invitacion(conn, dani, bolsillo.id)

    with pytest.raises(ErrorAutorizacion, match="no eras miembro activo"):
        services.votar_retiro(conn, dani, bolsillo.id, retiro.id, "EN_CONTRA")
    assert services.votar_retiro(conn, beto, bolsillo.id, retiro.id, "A_FAVOR").estado == "EJECUTADO"


def test_no_se_vota_dos_veces_ni_un_retiro_cerrado(conn, escenario):
    ana, beto, _, bolsillo = escenario
    retiro = services.proponer_retiro(conn, ana, bolsillo.id, "carla", 10_000)
    with pytest.raises(OperacionNoPermitida, match="Ya votaste"):
        services.votar_retiro(conn, ana, bolsillo.id, retiro.id, "EN_CONTRA")
    services.votar_retiro(conn, beto, bolsillo.id, retiro.id, "A_FAVOR")
    with pytest.raises(OperacionNoPermitida, match="ya se cerró"):
        services.votar_retiro(conn, beto, bolsillo.id, retiro.id, "A_FAVOR")
    # El dinero salió una sola vez.
    assert services.ver_bolsillo(conn, ana, bolsillo.id).saldo == 90_000


def test_retiro_vencido_expira_al_consultar_y_libera_saldo(conn, escenario):
    ana, beto, _, bolsillo = escenario
    retiro = services.proponer_retiro(conn, ana, bolsillo.id, "carla", 30_000)
    _vencer(conn, retiro.id)

    detalle = services.ver_bolsillo(conn, beto, bolsillo.id)
    assert (detalle.reservado, detalle.disponible) == (0, 100_000)
    assert services.listar_retiros(conn, ana, bolsillo.id)[0].estado == "EXPIRADO"


def test_retiro_vencido_no_se_puede_votar(conn, escenario):
    ana, beto, carla, bolsillo = escenario
    retiro = services.proponer_retiro(conn, ana, bolsillo.id, "carla", 30_000)
    _vencer(conn, retiro.id)
    with pytest.raises(OperacionNoPermitida, match="expiró"):
        services.votar_retiro(conn, beto, bolsillo.id, retiro.id, "A_FAVOR")
    assert services.consultar_saldo(conn, carla) == 0
    assert services.ver_bolsillo(conn, ana, bolsillo.id).saldo == 100_000


def test_propuesta_expira_en_siete_dias(conn, escenario):
    from datetime import datetime, timedelta

    ana, _, _, bolsillo = escenario
    retiro = services.proponer_retiro(conn, ana, bolsillo.id, "carla", 1_000)
    plazo = datetime.fromisoformat(retiro.expira_en) - datetime.fromisoformat(retiro.creado_en)
    assert plazo == timedelta(days=7)


def test_propuesta_valida_datos(conn, escenario):
    ana, _, _, bolsillo = escenario
    with pytest.raises(ErrorValidacion) as e:
        services.proponer_retiro(conn, ana, bolsillo.id, "", 1_000)
    assert e.value.campo == "destino"
    with pytest.raises(ErrorValidacion) as e:
        services.proponer_retiro(conn, ana, bolsillo.id, "carla", 0)
    assert e.value.campo == "monto"
    with pytest.raises(ErrorValidacion) as e:
        services.proponer_retiro(conn, ana, bolsillo.id, "carla", 1_000, "x" * 141)
    assert e.value.campo == "motivo"
    with pytest.raises(NoEncontrado):
        services.proponer_retiro(conn, ana, bolsillo.id, "nadie", 1_000)


def test_quien_no_es_miembro_no_propone_ni_vota(conn, escenario):
    ana, _, carla, bolsillo = escenario
    retiro = services.proponer_retiro(conn, ana, bolsillo.id, "carla", 1_000)
    with pytest.raises(NoEncontrado):
        services.proponer_retiro(conn, carla, bolsillo.id, "carla", 1_000)
    with pytest.raises(NoEncontrado):
        services.votar_retiro(conn, carla, bolsillo.id, retiro.id, "A_FAVOR")


def test_voto_invalido_o_retiro_de_otro_bolsillo(conn, escenario):
    ana, beto, _, bolsillo = escenario
    otro = services.crear_bolsillo(conn, beto, "Otro", 1_000)
    retiro = services.proponer_retiro(conn, ana, bolsillo.id, "carla", 1_000)
    with pytest.raises(ErrorValidacion):
        services.votar_retiro(conn, beto, bolsillo.id, retiro.id, "TAL_VEZ")
    with pytest.raises(NoEncontrado):
        services.votar_retiro(conn, beto, otro.id, retiro.id, "A_FAVOR")


def test_no_puede_salir_quien_tiene_votos_pendientes(conn, escenario):
    ana, beto, _, bolsillo = escenario
    retiro = services.proponer_retiro(conn, ana, bolsillo.id, "carla", 1_000)
    with pytest.raises(OperacionNoPermitida, match="vota antes de salir"):
        services.salir_de_bolsillo(conn, beto, bolsillo.id)
    services.votar_retiro(conn, beto, bolsillo.id, retiro.id, "EN_CONTRA")
    services.salir_de_bolsillo(conn, beto, bolsillo.id)


def test_retiros_mantienen_la_contabilidad_cuadrada(conn, escenario):
    """RNF-D-05 con Juntia: todo suma cero y cada saldo = suma de sus movimientos."""
    ana, beto, _, bolsillo = escenario
    r1 = services.proponer_retiro(conn, ana, bolsillo.id, "carla", 12_345)
    services.votar_retiro(conn, beto, bolsillo.id, r1.id, "A_FAVOR")
    r2 = services.proponer_retiro(conn, beto, bolsillo.id, "ana", 5_000)
    services.votar_retiro(conn, ana, bolsillo.id, r2.id, "A_FAVOR")

    assert conn.execute("SELECT SUM(saldo) FROM cuentas").fetchone()[0] == 0
    descuadres = conn.execute(
        "SELECT c.id FROM cuentas c LEFT JOIN movimientos m ON m.cuenta_id = c.id "
        "GROUP BY c.id HAVING c.saldo <> COALESCE(SUM(m.monto), 0)"
    ).fetchall()
    assert descuadres == []
    assert services.ver_bolsillo(conn, ana, bolsillo.id).saldo == 100_000 - 12_345 - 5_000


def test_propuestas_simultaneas_no_reservan_dos_veces_el_mismo_dinero(ruta_db):
    """RNF-R-04 en Juntia: bolsillo con 10.000 COP, 20 hilos proponen retirar 1.000 COP cada uno.

    Hay 3 miembros, así que ninguna propuesta se ejecuta sola: todas quedan reservando.
    Esperado: 10 propuestas creadas, 10 SaldoInsuficiente, reservado = 10.000.
    """
    import threading

    from habi import db

    conn = db.conectar(ruta_db)
    nombres = ["ana", "beto", "carla"]
    usuarios = [services.registrar_usuario(conn, n, "clave-segura") for n in nombres]
    ana = usuarios[0]
    services.cargar_saldo(conn, ana, 10_000)
    bolsillo = services.crear_bolsillo(conn, ana, "Viaje", 50_000)
    for otro in usuarios[1:]:
        services.invitar_a_bolsillo(conn, ana, bolsillo.id, otro.nombre)
        services.aceptar_invitacion(conn, otro, bolsillo.id)
    services.aportar_a_bolsillo(conn, ana, bolsillo.id, 10_000, _clave())

    hilos = 20
    barrera = threading.Barrier(hilos)
    resultados: list[str] = []
    candado = threading.Lock()

    def trabajador():
        c = db.conectar(ruta_db)
        try:
            barrera.wait()
            try:
                services.proponer_retiro(c, ana, bolsillo.id, "beto", 1_000)
                resultado = "ok"
            except SaldoInsuficiente:
                resultado = "insuficiente"
            except Exception as e:
                resultado = f"error: {e!r}"
            with candado:
                resultados.append(resultado)
        finally:
            c.close()

    threads = [threading.Thread(target=trabajador) for _ in range(hilos)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert sorted(resultados) == ["insuficiente"] * 10 + ["ok"] * 10
    detalle = services.ver_bolsillo(conn, ana, bolsillo.id)
    assert (detalle.saldo, detalle.reservado, detalle.disponible) == (10_000, 10_000, 0)
    conn.close()
