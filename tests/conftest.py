import pytest

from habi import config, db, services


@pytest.fixture(autouse=True)
def hash_rapido(monkeypatch):
    """Menos iteraciones de PBKDF2 en pruebas para que la suite sea rápida."""
    monkeypatch.setattr(config, "PBKDF2_ITERACIONES", 1_000)


@pytest.fixture
def ruta_db(tmp_path):
    """Base de datos nueva y aislada por prueba."""
    ruta = tmp_path / "test.db"
    conn = db.conectar(ruta)
    db.inicializar(conn)
    conn.close()
    return ruta


@pytest.fixture
def conn(ruta_db):
    conexion = db.conectar(ruta_db)
    yield conexion
    conexion.close()


@pytest.fixture
def crear_usuario(conn):
    """Fábrica: crea un usuario (y opcionalmente le carga saldo)."""

    def _crear(nombre: str = "ana", password: str = "clave-segura", saldo: int = 0):
        usuario = services.registrar_usuario(conn, nombre, password)
        if saldo:
            services.cargar_saldo(conn, usuario, saldo)
        return usuario

    return _crear


@pytest.fixture
def cliente(ruta_db):
    """Cliente de pruebas de Flask sobre una base de datos aislada."""
    from habi.web import crear_app

    app = crear_app(ruta_db, secret_key="clave-de-pruebas")
    app.config["TESTING"] = True
    return app.test_client()


@pytest.fixture
def registrar_y_entrar(cliente):
    """Registra un usuario por la API e inicia sesión con él."""

    def _hacer(nombre: str = "ana", password: str = "clave-segura"):
        cliente.post("/api/registro", json={"nombre": nombre, "password": password})
        respuesta = cliente.post("/api/login", json={"nombre": nombre, "password": password})
        assert respuesta.status_code == 200
        return respuesta

    return _hacer
