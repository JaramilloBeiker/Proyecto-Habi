# Habi — Sistema de transferencias entre personas

Aplicación web local (Flask) para crear cuentas, cargar saldo simulado, transferir dinero entre
cuentas, consultar saldo y ver el historial de movimientos. Reto Técnico HabiCapital 2027.

> **Advertencia:** la aplicación usa el servidor de desarrollo de Flask. Está pensado **solo para
> uso local** (escucha en `127.0.0.1`) y no debe publicarse en internet ni usarse en producción.

## Tecnologías

Python 3.12+ · Flask (rutas y cookie de sesión firmada) · HTML, CSS y JavaScript sin frameworks con
plantillas Jinja2 · SQLite (`sqlite3`) · `hashlib.pbkdf2_hmac` · `uuid` · pytest y cliente de pruebas de Flask

## Cómo ejecutar

```bash
python -m venv .venv
.venv\Scripts\activate          # Windows  (Linux/macOS: source .venv/bin/activate)
pip install -r requirements.txt

python -m habi                  # servidor local: abre http://127.0.0.1:5000 en el navegador
python -m pytest                # suite completa (RNF-S-02)
python -m habi.cli              # versión de consola (opcional)
```

Variables de entorno opcionales:

| Variable | Uso | Por defecto |
|---|---|---|
| `HABI_DB_PATH` | Ruta del archivo SQLite | `data/habi.db` |
| `HABI_SECRET_KEY` | Clave para firmar la cookie de sesión | Una aleatoria en cada arranque (las sesiones abiertas se pierden al reiniciar; los datos no) |

## Páginas

Páginas HTML hechas con plantillas Jinja2. Cada formulario se envía al servidor, que llama a la
misma capa de servicios que la API y muestra en la página el resultado o el motivo del error,
marcando el campo que falló (RNF-U-01, RNF-U-03).

| Ruta | Qué muestra | Requerimiento |
|---|---|---|
| `/registro` | Crear cuenta (abre sesión al terminar) | RF-01 |
| `/entrar` | Iniciar sesión | RF-02 |
| `/salir` (POST) | Cerrar sesión | RF-02 |
| `/cuenta` | Saldo, cargar saldo, transferir y últimos 5 movimientos | RF-03, RF-04, RF-05 |
| `/historial?pagina=0` | Movimientos en bloques de 20 | RF-06 |

- El formulario de transferencia lleva una clave `uuid4` oculta generada por el servidor. Si se
  envía dos veces (doble clic o recarga), la transferencia no se repite (RNF-R-03).
- JavaScript (`static/js/app.js`) solo agrega dos mejoras: deshabilita el botón al enviar y muestra
  el monto en COP mientras se escribe. Sin JavaScript todo sigue funcionando.
- Paleta sobria: fondo gris claro, tarjetas blancas, azul marino como color principal; verde y rojo
  solo para dinero que entra o sale. En celular la tabla de movimientos se apila.

## API

Todas las respuestas son JSON. Éxito: `{"ok": true, "mensaje": ..., ...}`.
Error: `{"ok": false, "error": "motivo", "campo": "monto" | null}`.
Los cuerpos se aceptan como JSON o como formulario HTML.

| Método | Ruta | Cuerpo / parámetros | Requiere sesión | Requerimiento |
|---|---|---|---|---|
| POST | `/api/registro` | `nombre`, `password` | No | RF-01 |
| POST | `/api/login` | `nombre`, `password` | No | RF-02 |
| POST | `/api/logout` | — | No | RF-02 |
| GET | `/api/sesion` | — | Sí | RF-02 |
| GET | `/api/saldo` | — | Sí | RF-05 |
| POST | `/api/cargas` | `monto` | Sí | RF-03 |
| GET | `/api/transferencias/nueva` | — (devuelve `clave_idempotencia`) | Sí | RNF-R-03 |
| POST | `/api/transferencias` | `destino`, `monto`, `clave_idempotencia` | Sí | RF-04 |
| GET | `/api/historial` | `?pagina=0` (bloques de 20) | Sí | RF-06 |

Códigos HTTP: `400` dato inválido, `401` sin sesión o sesión expirada, `404` destino inexistente,
`409` saldo insuficiente.

## Estructura

```
habi/
  config.py      Constantes y límites (montos, página del historial, PBKDF2, sesión, ruta de BD)
  db.py          Conexión, esquema SQLite y transacciones (BEGIN IMMEDIATE)
  dominio.py     Modelos y errores de negocio
  security.py    Hash y verificación de contraseñas
  repository.py  Acceso a datos (solo SQL)
  services.py    Lógica de negocio: sesiones, cargas, transferencias, saldo, historial
  formato.py     Formato de montos en COP
  web.py         Creación de la app Flask y rutas de la API JSON
  paginas.py     Rutas de las páginas HTML
  templates/     Plantillas Jinja2 (base, acceso, cuenta, historial, macros)
  static/        estilos.css y app.js
  cli.py         Menú de consola (opcional)
tests/           Una o más pruebas por requerimiento (servicios, API y páginas)
```

Separación de capas (RNF-S-01): `paginas` / `web` / `cli` → `services` → `repository` → SQLite.
Las plantillas solo presentan datos; no tienen reglas de negocio.

## Sesiones

La cookie de sesión de Flask va firmada con `SECRET_KEY`, expira a los 60 minutos y solo guarda un
token aleatorio. El token se registra en la tabla `sesiones` con su fecha de expiración. Al cerrar
sesión se borra la fila, así que una copia de la cookie anterior deja de dar acceso.

---

<!-- ENT-02: responder en primera persona -->

## 1. Decisiones clave
_TODO_

## 2. Cómo sé que el sistema no pierde un peso
_TODO_ (qué puede salir mal, cómo lo protejo, evidencia)

## 3. Qué dejé fuera
_TODO_

## 4. Qué haría distinto con más tiempo
_TODO_

## 5. Qué no sé
_TODO_

## 6. Supuestos
_TODO_

## 7. Cómo usé IA
_TODO_ (incluir al menos un error de la IA)

## 8. Qué aprendí
_TODO_
