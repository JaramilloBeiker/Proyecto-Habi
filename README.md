# Nexo — Sistema de transferencias entre personas

## Cómo ejecutar

```bash
python -m venv .venv
.venv\Scripts\activate          # Windows  (Linux/macOS: source .venv/bin/activate)
pip install -r requirements.txt

python -m habi                  # servidor local: abre http://127.0.0.1:5000 en el navegador
python -m pytest                # suite completa
python -m habi.cli              # versión de consola (opcional)
```

Variables de entorno opcionales:

| Variable | Uso | Por defecto |
|---|---|---|
| `HABI_DB_PATH` | Ruta del archivo SQLite | `data/habi.db` |
| `HABI_SECRET_KEY` | Clave para firmar la cookie de sesión | Una aleatoria en cada arranque (las sesiones abiertas se pierden al reiniciar; los datos no) |

---

## 1. Decisiones clave

Entre mis decisiones clave estuvieron definir los requerimientos funcionales y no funcionales para ejecutar el proyecto de forma ordenada y acotada, y usar GitHub Flow para organizar el repositorio. En el desarrollo decidí usar claves de idempotencia (UUID por formulario) para crear una clave por transferencia y poder verificarla después. En el diseño decidí un estilo moderno, donde los títulos se distinguen del resto de los campos para que apartados como el saldo destaquen. Otra decisión clave fue implementar el modelo de forma local. Para este reto me pareció más conveniente, porque permitía trabajar con tecnologías que estaban directamente en el IDE y no tener que desplegar la app en un servidor en internet para que funcionara.

## 2. Cómo sé que el sistema no pierde un peso

Sabía que el manejo del dinero iba a ser un tema muy delicado, así que investigué un poco sobre cómo los bancos trabajan este tema. El detalle que me pareció más importante fue la clave que mencioné antes: las transferencias y los aportes llevan una clave única por formulario. Si llega un reenvío, se devuelve el resultado original en lugar de mover dinero otra vez. Otros aspectos clave están en la base de datos: el débito es un solo `UPDATE ... WHERE saldo >= monto`, así que la verificación y el cambio ocurren en el mismo paso, y dos transferencias simultáneas no pueden gastar el mismo saldo. También se protege con un `CHECK` que impide saldos negativos (salvo en la cuenta de fondeo) y montos que no sean enteros positivos, y con un trigger que impide modificar o borrar movimientos. Que cada suma de movimientos dé cero se verifica en el código y en las pruebas, no en la base de datos.

Lo que no está protegido: las propuestas de retiro no tienen clave única. Lo reproduje: con un solo miembro, un doble envío mueve el dinero dos veces. Es el punto más débil del sistema y no lo corregí.

Para comprobarlo, con ayuda de IA realicé algunas pruebas automatizadas, incluidas en la carpeta `tests`. La suite se ejecuta con `python -m pytest`. Entre las pruebas están `test_20_transferencias_simultaneas_desde_10000` (20 hilos con conexiones propias), `test_movimientos_no_se_modifican_ni_eliminan`, `test_suma_de_movimientos_por_operacion_es_cero`, `test_saldo_coincide_con_suma_de_movimientos` y `test_propuestas_simultaneas_no_reservan_dos_veces_el_mismo_dinero`.

## 3. Qué dejé fuera

Dejé fuera publicar el programa en internet. Escogí no usar Spring Boot ni React, y no construir una arquitectura de servicios REST separada: la API JSON solo atiende a las páginas. En un primer intento, planeando un poco, había muchas tecnologías que podía usar. Sin embargo, con un tiempo bastante limitado, construir un programa capaz de funcionar con esas tecnologías me hubiera tomado mucho tiempo con mis conocimientos actuales. Sí podría haberlo hecho, pero creí que era mejor usar tecnologías más básicas que me ayudaran a construir la plataforma de forma rápida y que pudiera comprender.

## 4. Qué haría distinto con más tiempo

Hubiera intentado publicar el servicio de forma web, y también me hubiera gustado usar otros frameworks que me permitieran hacer la plataforma más sólida. Algo clave que, con más tiempo, implementaría sí o sí en las juntias es la clave de idempotencia para los retiros, igual que en las transferencias y los aportes. Hoy el botón se deshabilita al enviar, pero si la petición llega dos veces, por ejemplo porque el botón no alcanza a bloquear el segundo envío, el bolsillo puede pagar dos veces. Siento que es un aspecto clave para mantener el estándar de conservación del dinero. También me hubiera gustado hacer pruebas de seguridad para verificar que el código funcione correctamente en ese aspecto.

## 5. Qué no sé

No tengo mucho conocimiento en desarrollo web ni en trabajo de frontend. Realmente no estoy muy familiarizado con ello. Conozco varias tecnologías que podría usar, pero no sé usarlas bien.

## 6. Supuestos

- El dinero se representa como números enteros, para no tener problemas con los centavos y evitar errores de redondeo.
- Cada operación está limitada a un rango de 1 a 5.000.000 COP. Así todas tienen el mismo tope, y si hay que mover más, los movimientos se dividen en varios.
- La carga de saldo es simulada: el usuario puede cargar su saldo directamente desde su cuenta, sin pasarela de pagos.
- Quien propone un retiro en una juntia vota automáticamente a favor. Si propone es porque quiere hacer el retiro, así que si el bolsillo tiene un solo miembro, el retiro se ejecuta de inmediato.
- Todos los miembros deben aprobar un retiro en una juntia, para mantener la unanimidad en el manejo del dinero.
- Los nombres distintos en mayúsculas son usuarios distintos: "Ana" y "ana" pueden registrarse por separado.
- Cada bolsillo tiene una meta de hasta 1.000.000.000 COP.

## 7. Cómo usé IA

Las herramientas que utilicé fueron Claude y Gemini. Claude me ayudó en la construcción del código; un ejemplo claro es el esqueleto del programa. Sin embargo, yo creé la estructura de carpetas que usaríamos y aprobaba los push a las ramas donde se implementaban las características. Mientras tanto, con Gemini agilicé procesos sencillos, como la construcción del documento en LaTeX para documentar el proceso y definir lo que estábamos realizando.

La IA solía equivocarse al definir los requerimientos: los terminaba volviendo demasiado extensos e incluían más de una necesidad por requerimiento. Considero que esa parte del análisis es muy importante para definir lo que realmente queremos hacer, así que me tomé un tiempo para revisarla a detalle. Por otro lado, cuando hice una consulta para que me aconsejara sobre la división de carpetas del programa, la respuesta fue extremadamente complicada para el nivel de este reto.

## 8. Qué aprendí

Me pareció interesante manejar contraseñas con hash. Conocía su significado, pero nunca había trabajado con esa tecnología. También aprendí conceptos sobre sesiones y cookies, y cómo se conecta el frontend en Python para poder usar HTML y plantillas. El reto en general me pareció interesante, porque tenía varios conceptos que conocía a medias y que nunca había implementado realmente.
