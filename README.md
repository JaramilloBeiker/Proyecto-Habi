# Nexo — Sistema de transferencias entre personas

Aplicación web local (Flask) para crear cuentas, cargar saldo simulado, transferir dinero entre
cuentas, consultar saldo y ver el historial de movimientos. Reto Técnico HabiCapital 2027.

> La interfaz se llama **Nexo**. El paquete de Python sigue siendo `habi` (y las variables de
> entorno `HABI_*`) para no romper imports, comandos ni bases de datos existentes.

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
| `/juntias` | Mis bolsillos, invitaciones pendientes y crear bolsillo | Juntia |
| `/juntias/<id>` | Saldo, reservado y meta; aportar, proponer y votar retiros, miembros, invitar, salir y movimientos | Juntia |

- El formulario de transferencia lleva una clave `uuid4` oculta generada por el servidor. Si se
  envía dos veces (doble clic o recarga), la transferencia no se repite (RNF-R-03).
- JavaScript (`static/js/app.js`) solo agrega dos mejoras: deshabilita el botón al enviar y muestra
  el monto en COP mientras se escribe. Sin JavaScript todo sigue funcionando.
- Diseño: fuente Plus Jakarta Sans (Google Fonts) con títulos en 700–800. Una sola escala de azul
  marino para la marca, los botones y la tarjeta de saldo, que es el punto focal de cada panel.
  Sombras suaves, bordes redondeados y espacios amplios. El verde y el rojo se usan solo para el
  dinero que entra o sale. En celular, la navegación baja a una segunda fila y la tabla de
  movimientos se apila.

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
| GET | `/api/juntias` | — (mis bolsillos e invitaciones) | Sí | Juntia |
| POST | `/api/juntias` | `nombre`, `meta` | Sí | Juntia |
| GET | `/api/juntias/<id>` | — (bolsillo, miembros y retiros) | Sí | Juntia |
| POST | `/api/juntias/<id>/invitaciones` | `invitado` | Sí | Juntia |
| POST | `/api/juntias/<id>/aceptar` · `/rechazar` · `/salir` | — | Sí | Juntia |
| GET | `/api/juntias/<id>/aportes/nueva` | — (devuelve `clave_idempotencia`) | Sí | Juntia |
| POST | `/api/juntias/<id>/aportes` | `monto`, `clave_idempotencia` | Sí | Juntia |
| GET | `/api/juntias/<id>/historial` | `?pagina=0` | Sí | Juntia |
| POST | `/api/juntias/<id>/retiros` | `destino`, `monto`, `motivo` (opcional) | Sí | Juntia |
| POST | `/api/juntias/<id>/retiros/<retiro_id>/votos` | `voto`: `A_FAVOR` o `EN_CONTRA` | Sí | Juntia |

Códigos HTTP: `400` dato inválido, `401` sin sesión o sesión expirada, `403` invitación sin aceptar
o ya no es miembro, `404` destino o bolsillo inexistente (también si no eres miembro), `409` saldo
insuficiente o acción no permitida en el estado actual (ej.: votar un retiro cerrado).

## Estructura

```
habi/
  config.py      Constantes y límites (montos, página del historial, PBKDF2, sesión, ruta de BD)
  db.py          Conexión, esquema SQLite y transacciones (BEGIN IMMEDIATE)
  dominio.py     Modelos y errores de negocio
  security.py    Hash y verificación de contraseñas
  repository.py  Acceso a datos (solo SQL)
  services.py    Lógica de negocio: sesiones, cargas, transferencias, saldo, historial y Juntia
  formato.py     Formato de montos en COP
  web.py         Creación de la app Flask y rutas de la API JSON
  paginas.py     Rutas de las páginas HTML
  templates/     Plantillas Jinja2 (base, acceso, cuenta, historial, juntias, macros)
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

## Juntia: bolsillos compartidos

Un bolsillo es una meta de ahorro común entre dos o más personas.

- **Miembros.** Quien crea el bolsillo queda como miembro activo. Los demás entran por invitación
  de un miembro activo y deben aceptarla; mientras tanto ven el nombre del bolsillo y quién los
  invitó, pero no el saldo. Se puede volver a invitar a quien rechazó o salió.
- **Aportes.** Un miembro activo pasa dinero de su cuenta personal al bolsillo. Es la misma
  transferencia de siempre (`services._mover_dinero`): valida el monto, verifica el saldo dentro de
  la transacción y usa clave de idempotencia, así que reenviar el formulario no duplica el aporte.
- **Retiros.** Retirar es una propuesta hacia cualquier usuario de Habi. Mientras está pendiente su
  monto queda **reservado**: `disponible = saldo − reservado`, y una nueva propuesta no puede pasar
  de lo disponible. Quien propone vota a favor automáticamente. Al proponer se guarda una foto de
  los miembros activos en ese momento (`votos_retiro`): solo ellos votan, y quien entra después no.
  - Todos a favor → se ejecuta la transferencia del bolsillo al destino.
  - Un voto en contra → se cancela y la reserva se libera.
  - Sin la respuesta de todos en 7 días → expira y la reserva se libera.
- **Expiración pasiva.** No hay tareas en segundo plano. Cada vez que se consulta un bolsillo, se
  propone o se vota, primero se marcan como `EXPIRADO` los retiros pendientes cuya fecha límite ya
  pasó. Al votar se revisa la fecha otra vez dentro de la transacción.
- **Salida.** Un miembro que nunca aportó puede salir. Quien ya aportó no puede salir.

### Cómo se guarda

- `cuentas.tipo` acepta `BOLSILLO`: cada bolsillo tiene su propia cuenta sin dueño. Los aportes y
  retiros son operaciones `TRANSFERENCIA` con sus dos movimientos, así que se mantienen las reglas
  de siempre: cada operación suma cero, la cuenta no puede quedar negativa y los movimientos son
  inmutables.
- Tablas nuevas: `bolsillos`, `miembros_bolsillo`, `retiros` y `votos_retiro`.
- **Migración.** SQLite no permite cambiar un `CHECK` con `ALTER TABLE`. Por eso, en una base creada
  antes de Juntia, `db.migrar_cuentas()` reconstruye la tabla `cuentas`: crea la tabla nueva, copia
  todas las filas con los mismos id y saldos, borra la vieja y renombra la nueva. Todo ocurre en una
  sola transacción y al final se ejecuta `PRAGMA foreign_key_check`. Corre sola al arrancar y no
  hace nada si la tabla ya acepta `BOLSILLO`.

### Limitaciones conocidas

- **No hay forma de cerrar un bolsillo.** Como quien aportó no puede salir, un bolsillo con aportes
  existe para siempre. Para sacar todo el dinero se propone un retiro por el saldo disponible y todos
  votan a favor; el bolsillo queda con saldo 0, pero sigue existiendo.
- Mientras alguien tenga un voto pendiente no puede salir del bolsillo. Sin esta regla, un retiro
  podría quedar esperando el voto de alguien que ya se fue.
- Si salen todos los miembros que nunca aportaron, el bolsillo puede quedar sin miembros activos. No
  tiene dinero, porque nadie aportó, pero sigue existiendo y nadie puede invitar.
- Un retiro aprobado mueve como máximo 5.000.000 COP, el mismo límite de las transferencias. Para
  sumas mayores se proponen varios retiros.

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
