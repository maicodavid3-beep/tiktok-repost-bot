# Guía de configuración — Repost bot TikTok → YouTube + Instagram

Esta guía te lleva paso a paso desde cero hasta tener el bot corriendo solo,
4 veces por día. No hace falta que sepas programar, pero sí ir con calma:
son varias credenciales y cada plataforma tiene su propio proceso.

Tiempo estimado total: 45-60 minutos, una sola vez.

---

## 0. Cómo funciona, en criollo

- Vos ponés los videos (ya descargados de TikTok) y sus descripciones en una "cola" (`config/queue.json`).
- 4 veces al día, GitHub corre el bot automáticamente:
  - **Fase 1**: agarra el próximo video pendiente, lo sube a YouTube, y publica el Trial Reel en Instagram.
  - **Fase 2** (30 minutos después): publica el mismo video como Reel normal, sin tocar el trial.
- El bot va marcando en `config/queue.json` qué videos ya se publicaron.

**Importante sobre privacidad:** para que Instagram pueda descargar el video y publicarlo, el video tiene que estar en una URL pública. Este proyecto usa tu propio repositorio de GitHub como hosting (tiene que ser un repo **público**). Esto significa que, técnicamente, cualquiera con el link directo podría acceder al archivo del video — igual que ya es público en TikTok, así que en la práctica no cambia mucho, pero es bueno que lo sepas.

---

## 1. Descargar tus videos de TikTok

Por cada video que quieras resubir:

1. Abrí el video en la app de TikTok → los 3 puntos (⋯) → **Guardar video** (sin marca de agua, si tenés esa opción activada en tu perfil).
2. Copiá también la descripción/caption exacta que usaste.

Si son muchos videos y querés todos de una, pedí tu archivo completo en TikTok: **Perfil → Configuración → Cuenta → Descargar mis datos** (te da un ZIP con los videos y un archivo con las descripciones).

---

## 2. Crear el repositorio en GitHub

1. Si no tenés cuenta, creála gratis en [github.com](https://github.com).
2. Creá un repositorio nuevo, **público**, por ejemplo `tiktok-repost-bot`.
3. Subí ahí toda la carpeta que te mandé (podés arrastrar los archivos desde la web de GitHub, o usar `git` si te resulta más cómodo).
4. Poné tus videos dentro de la carpeta `videos/` (nombralos simple, sin espacios: `video-001.mp4`, `video-002.mp4`, etc.).
5. Editá `config/queue.json` y agregá una entrada por cada video, con su `file` y su `caption` (la misma descripción que en TikTok). Ejemplo:

```json
[
  {
    "id": "video-001",
    "file": "videos/video-001.mp4",
    "caption": "Así arranca tu semana 💪 #motivacion",
    "status": "pending",
    "youtube_video_id": null,
    "ig_trial_media_id": null,
    "ig_normal_media_id": null
  },
  {
    "id": "video-002",
    "file": "videos/video-002.mp4",
    "caption": "Otra descripción acá",
    "status": "pending",
    "youtube_video_id": null,
    "ig_trial_media_id": null,
    "ig_normal_media_id": null
  }
]
```

---

## 3. Configurar YouTube (Google Cloud)

1. Andá a [console.cloud.google.com](https://console.cloud.google.com) e iniciá sesión con la cuenta de Google **dueña del canal de YouTube**.
2. Creá un proyecto nuevo (arriba a la izquierda → "Nuevo proyecto").
3. Buscá **"YouTube Data API v3"** en el buscador de arriba y hacé clic en **Habilitar**.
4. Andá a **APIs y servicios → Pantalla de consentimiento OAuth**:
   - Tipo de usuario: **Externo**.
   - Completá nombre de la app y tu email. Guardar y continuar en todos los pasos.
   - En "Usuarios de prueba", agregá tu propio email de Google.
5. Andá a **APIs y servicios → Credenciales → Crear credenciales → ID de cliente de OAuth**:
   - Tipo de aplicación: **App de escritorio**.
   - Descargá el archivo JSON (botón de descarga) y guardalo como `client_secret.json`.
6. En tu computadora (no en GitHub), con Python instalado:
   ```
   pip install google-auth-oauthlib
   python scripts/get_youtube_refresh_token.py client_secret.json
   ```
   Se va a abrir el navegador — iniciá sesión con la cuenta del canal y aceptá los permisos.
7. El script te va a imprimir 3 valores: `YT_CLIENT_ID`, `YT_CLIENT_SECRET`, `YT_REFRESH_TOKEN`. Guardalos, los necesitás en el paso 5.

No hace falta pedir aprobación a Google para esto — como el canal es tuyo, alcanza con dejar la app en modo de prueba y agregarte como usuario de prueba.

---

## 4. Configurar Instagram (Meta for Developers)

1. Confirmá que tu cuenta de Instagram sea **profesional** (Business o Creator) — ya lo tenés.
2. Andá a [developers.facebook.com](https://developers.facebook.com) → **Mis apps → Crear app**.
   - Tipo de app: **Empresa** (Business).
3. Dentro de la app, agregá el producto **"Instagram"** (Instagram API con Instagram Login).
4. Seguí el asistente para conectar tu cuenta de Instagram profesional a la app. Ahí vas a obtener:
   - Tu **`IG_USER_ID`** (el ID numérico de tu cuenta de Instagram).
   - Un **token de acceso**. Con la herramienta "Generar token" de la sección Instagram de tu app, generá un token de larga duración (60 días).
5. Guardá `IG_USER_ID` y `IG_ACCESS_TOKEN`.

**Ojo con la fecha de vencimiento:** el token de Instagram vence a los 60 días. El bot no lo renueva solo (para no complicar la configuración inicial). Poné un recordatorio a los ~50 días para volver a generarlo y actualizar el Secret en GitHub (paso 5), si no las publicaciones a Instagram van a empezar a fallar.

Si Meta te pide verificación de negocio o revisión de la app para publicar en tu propia cuenta, avisame y lo resolvemos — para uso personal (solo tu cuenta) normalmente no debería hacer falta, pero Meta cambia estas reglas seguido.

---

## 5. Cargar las credenciales en GitHub (Secrets)

En tu repositorio de GitHub: **Settings → Secrets and variables → Actions → New repository secret**.

Cargá estos 5 secrets, uno por uno:

| Nombre              | Valor                                  |
|---------------------|-----------------------------------------|
| `YT_CLIENT_ID`       | El que te dio el script de YouTube      |
| `YT_CLIENT_SECRET`   | El que te dio el script de YouTube      |
| `YT_REFRESH_TOKEN`   | El que te dio el script de YouTube      |
| `IG_USER_ID`         | El ID de tu cuenta de Instagram         |
| `IG_ACCESS_TOKEN`    | El token de larga duración de Instagram |

---

## 6. Probar que funciona

1. En GitHub, andá a la pestaña **Actions** de tu repositorio.
2. Elegí el workflow **"Publicar videos (YouTube + Instagram)"**.
3. Hacé clic en **Run workflow**, elegí `fase1`, y ejecutá.
4. Mirá los logs — te va a mostrar el progreso de la subida a YouTube y la publicación del Trial Reel.
5. Esperá ~30 minutos (o corré manualmente `fase2` para no esperar) y volvé a **Run workflow**, esta vez con `fase2`.
6. Revisá tu canal de YouTube y tu Instagram para confirmar que se publicó todo bien.

Una vez que probaste que anda, dejalo tranquilo: los 4 horarios diarios (10:00, 13:00, 17:00 y 20:00, hora Argentina) van a correr solos.

---

## 7. Agregar más videos después

Cada vez que quieras sumar contenido nuevo a la cola: subí el archivo a `videos/`, agregá su entrada en `config/queue.json` con `"status": "pending"`, y hacé commit. El bot lo va a tomar automáticamente en el próximo horario disponible.

---

## Límites a tener en cuenta

- **YouTube**: la quota gratuita de Google alcanza para ~6 subidas por día — con 4 al día vas sobrado.
- **Instagram**: hasta 100 publicaciones por API cada 24 horas — no es un problema con este volumen.
- **GitHub Actions**: cada corrida tarda 1-3 minutos; con 8 corridas diarias (4 fases 1 + 4 fases 2) usás muy por debajo de las ~33 horas gratis por mes.
- **Contenido repetido**: al publicar el mismo video dos veces (trial + normal), Instagram puede a veces limitarle un poco el alcance a la segunda copia por considerarlo "contenido reciclado" — no es un bloqueo, solo puede rendir algo menos que un post 100% original.
