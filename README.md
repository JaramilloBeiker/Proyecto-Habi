# Habi — Sistema de transferencias entre personas

Aplicación de consola para crear cuentas, cargar saldo simulado, transferir dinero entre cuentas,
consultar saldo y ver el historial de movimientos. Reto Técnico HabiCapital 2027.

## Tecnologías

Python 3.12+ · consola (`input`/`print`) · SQLite (`sqlite3`) · `hashlib.pbkdf2_hmac` · `uuid` · pytest

## Cómo ejecutar

```bash
python -m venv .venv
.venv\Scripts\activate          # Windows  (Linux/macOS: source .venv/bin/activate)
pip install -r requirements.txt

python -m habi                  # aplicación de consola
python -m pytest                # suite completa (RNF-S-02)
```

La base de datos se guarda en `data/habi.db` (configurable con la variable `HABI_DB_PATH`).

## Estructura

```
habi/
  config.py      Constantes y límites (montos, página del historial, PBKDF2, ruta de BD)
  db.py          Conexión, esquema SQLite y transacciones (BEGIN IMMEDIATE)
  dominio.py     Modelos y errores de negocio
  security.py    Hash y verificación de contraseñas
  repository.py  Acceso a datos (solo SQL)
  services.py    Lógica de negocio: cargas, transferencias, saldo, historial
  cli.py         Menú de consola
tests/           Una o más pruebas por requerimiento
```

Separación de capas (RNF-S-01): `cli` → `services` → `repository` → SQLite.

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
