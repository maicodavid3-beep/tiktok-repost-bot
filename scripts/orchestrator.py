"""
Orquestador del posteo con demora de 24 horas entre el Trial Reel y el Reel
normal (antes eran 30 minutos).

Cada corrida programada ejecuta un "ciclo" completo que hace dos cosas, en
este orden:

1. Revisa state/pending_normal.json (videos que ya tienen su Trial Reel
   publicado) y, de los que ya cumplieron sus 24 horas de espera, publica el
   Reel normal correspondiente (Fase 2). Los que todavía no cumplieron las
   24 horas se dejan esperando para la próxima corrida (no se tocan).
2. Toma el próximo video "pending" de config/queue.json (con su archivo ya
   subido), lo sube a YouTube y publica su Trial Reel en Instagram (Fase 1),
   guardando en state/pending_normal.json la marca de tiempo exacta en que
   se publicó el trial, para poder calcular después cuándo le toca su
   Fase 2 (24hs más tarde).

Se ejecuta desde GitHub Actions, que llama normalmente:
    python scripts/orchestrator.py ciclo

También se pueden forzar las fases por separado para pruebas manuales
(workflow_dispatch), aunque el uso normal en el horario programado es
siempre "ciclo":
    python scripts/orchestrator.py fase1   # fuerza solo un trial nuevo
    python scripts/orchestrator.py fase2   # fuerza la publicación de TODOS
                                            # los que estén esperando, SIN
                                            # esperar las 24hs (útil para
                                            # probar manualmente)

PROTECCIÓN CONTRA DISPAROS DUPLICADOS: como hay dos disparadores en paralelo
(el cron nativo de GitHub Actions + el respaldo externo de cron-job.org),
puede pasar que los dos disparen casi al mismo horario. Para que eso no
duplique el procesamiento, cada modo registra en state/last_run.json cuándo
corrió por última vez, y si ya corrió hace menos de RECENT_RUN_MINUTES
minutos, la corrida nueva no hace nada (asume que es un disparo duplicado
del mismo horario, no un horario nuevo).
"""

import json
import os
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from instagram_publish import publish_reel  # noqa: E402
from youtube_upload import upload_video  # noqa: E402

ROOT = Path(__file__).parent.parent
QUEUE_PATH = ROOT / "config" / "queue.json"
PENDING_PATH = ROOT / "state" / "pending_normal.json"
LAST_RUN_PATH = ROOT / "state" / "last_run.json"

# Cuánto tiempo tiene que pasar desde el Trial Reel para publicar el Reel
# normal del mismo video. Antes era 30 minutos, ahora 24 horas.
NORMAL_DELAY = timedelta(hours=24)

# Margen de tolerancia para no perderse el horario que le toca a un video
# por unos minutos de atraso/adelanto del disparador (GitHub Actions es
# "best effort" y puede atrasarse un poco). Un video se considera "listo"
# un poco antes de cumplir las 24hs exactas de esta manera.
NORMAL_DELAY_TOLERANCE = timedelta(minutes=15)

# Si en una misma corrida hay que publicar más de un Reel normal acumulado
# (por ejemplo tras una corrida perdida), esperamos esto entre uno y otro
# para que no salgan pegados.
BACKLOG_GAP_SECONDS = 15 * 60

# Ventana de "esto es probablemente un disparo duplicado del mismo horario".
RECENT_RUN_MINUTES = 110


def _video_public_url(file_relative_path: str) -> str:
    """Construye la URL pública raw.githubusercontent.com del video.

    Requiere que el repo sea PÚBLICO (ver GUIA_CONFIGURACION.md) y que el
    video ya esté commiteado en la rama principal antes de que corra
    esta fase.
    """
    repo = os.environ["GITHUB_REPOSITORY"]  # ej: "usuario/tiktok-repost-bot"
    branch = os.environ.get("GITHUB_BRANCH", "main")
    return f"https://raw.githubusercontent.com/{repo}/{branch}/{file_relative_path}"


def _load_json(path: Path, default=None):
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def _save_json(path: Path, data) -> None:
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _recently_ran(key: str) -> bool:
    """True si esta clave (ciclo/fase1/fase2) ya se ejecutó hace menos de
    RECENT_RUN_MINUTES."""
    data = _load_json(LAST_RUN_PATH, default={}) or {}
    ts = data.get(key)
    if not ts:
        return False
    try:
        last = datetime.fromisoformat(ts)
    except ValueError:
        return False
    return (_now() - last) < timedelta(minutes=RECENT_RUN_MINUTES)


def _mark_ran(key: str) -> None:
    data = _load_json(LAST_RUN_PATH, default={}) or {}
    data[key] = _now().isoformat()
    _save_json(LAST_RUN_PATH, data)


def _is_due(pending_item: dict, force: bool = False) -> bool:
    """True si a este video ya le toca su Reel normal."""
    if force:
        return True
    ts = pending_item.get("trial_posted_at")
    if not ts:
        # Entrada vieja, de antes de este cambio (guardada sin marca de
        # tiempo bajo el esquema de 30 minutos). Para no dejarla trabada
        # para siempre esperando algo que nunca va a poder calcularse, se
        # considera lista para publicar ahora mismo.
        print(
            f"Aviso: {pending_item.get('id')} no tiene 'trial_posted_at' "
            "guardado (es de antes de este cambio). Se publica ahora en "
            "vez de esperar 24hs."
        )
        return True
    try:
        posted_at = datetime.fromisoformat(ts)
    except ValueError:
        return True
    return (_now() - posted_at) >= (NORMAL_DELAY - NORMAL_DELAY_TOLERANCE)


def _do_fase1() -> None:
    queue = _load_json(QUEUE_PATH)

    siguiente = next(
        (v for v in queue if v["status"] == "pending" and (ROOT / v["file"]).exists()),
        None,
    )
    if siguiente is None:
        print(
            "[Fase 1] No hay videos pendientes en la cola (o están pending "
            "pero el archivo todavía no fue subido). Nada que hacer."
        )
        return

    video_url = _video_public_url(siguiente["file"])
    caption = siguiente["caption"]
    titulo_youtube = caption[:95] if caption else "Short"

    # Aseguramos el hashtag #Shorts en la descripción de YouTube para que
    # lo clasifique como Short de forma confiable (además de que ya lo
    # detecta solo por ser vertical y de corta duración). Esto NO afecta a
    # Instagram: la publicación en IG sigue siendo un Reel/Trial Reel normal,
    # sin ningún hashtag agregado, y sin ningún concepto de "prueba" en YouTube.
    descripcion_youtube = caption or ""
    if "#shorts" not in descripcion_youtube.lower():
        descripcion_youtube = f"{descripcion_youtube}\n\n#Shorts".strip()

    print(f"[Fase 1] Procesando video {siguiente['id']} ({siguiente['file']})")

    youtube_id = upload_video(
        video_path=str(ROOT / siguiente["file"]),
        title=titulo_youtube,
        description=descripcion_youtube,
    )

    ig_trial_id = publish_reel(video_url=video_url, caption=caption, trial=True)

    siguiente["status"] = "trial_posted"
    siguiente["youtube_video_id"] = youtube_id
    siguiente["ig_trial_media_id"] = ig_trial_id
    _save_json(QUEUE_PATH, queue)

    # IMPORTANTE: agregamos a la lista (no sobreescribimos), así si alguna
    # vez queda más de un video esperando su Fase 2, no se pierde ninguno.
    # Guardamos también trial_posted_at para poder calcular cuándo le toca
    # su Reel normal (24hs después de este momento).
    pendientes = _load_json(PENDING_PATH, default=[]) or []
    pendientes.append(
        {
            "id": siguiente["id"],
            "video_url": video_url,
            "caption": caption,
            "trial_posted_at": _now().isoformat(),
        }
    )
    _save_json(PENDING_PATH, pendientes)

    print(
        f"[Fase 1] Trial Reel publicado para {siguiente['id']}. "
        "Su Reel normal va a salir en ~24hs."
    )


def _do_fase2(force: bool = False) -> None:
    pendientes = _load_json(PENDING_PATH, default=[]) or []

    if not pendientes:
        print("[Fase 2] No hay ningún reel esperando su publicación normal. Nada que hacer.")
        return

    listos = [p for p in pendientes if _is_due(p, force=force)]
    no_listos = [p for p in pendientes if not _is_due(p, force=force)]

    if not listos:
        print(
            f"[Fase 2] Hay {len(pendientes)} video(s) esperando su turno, "
            "pero ninguno cumplió todavía sus 24hs. No se publica nada en "
            "esta corrida."
        )
        return

    queue = _load_json(QUEUE_PATH)
    publicados = []

    # Procesamos TODOS los que ya estén listos (no solo el primero), por si
    # se acumuló más de uno (por ejemplo tras una corrida perdida). Si hay
    # más de uno, los espaciamos un poco entre sí.
    for idx, pending in enumerate(listos):
        item = next((v for v in queue if v["id"] == pending["id"]), None)
        if item is None:
            print(f"Aviso: no se encontró en la cola el video {pending['id']}. Lo descarto de la lista de espera.")
            continue

        if idx > 0:
            print(f"[Fase 2] Esperando {BACKLOG_GAP_SECONDS // 60} min antes de publicar el siguiente...")
            time.sleep(BACKLOG_GAP_SECONDS)

        ig_normal_id = publish_reel(video_url=pending["video_url"], caption=pending["caption"], trial=False)

        item["status"] = "done"
        item["ig_normal_media_id"] = ig_normal_id
        publicados.append(pending["id"])
        print(f"[Fase 2] Reel normal publicado para {pending['id']}.")

    _save_json(QUEUE_PATH, queue)
    # Los que todavía no cumplieron sus 24hs quedan esperando en la lista.
    _save_json(PENDING_PATH, no_listos)

    if len(publicados) > 1:
        print(
            f"Nota: se publicaron {len(publicados)} reels normales en esta "
            f"corrida: {', '.join(publicados)}"
        )
    if no_listos:
        print(
            f"Quedan {len(no_listos)} video(s) esperando a cumplir sus 24hs: "
            f"{', '.join(p['id'] for p in no_listos)}"
        )


def ciclo() -> None:
    """Modo normal, usado por el horario programado: revisa si hay algún
    Reel normal que ya cumplió sus 24hs (y lo publica), y después sube el
    próximo Trial Reel nuevo."""
    if _recently_ran("ciclo"):
        print(
            f"El ciclo ya se ejecutó hace menos de {RECENT_RUN_MINUTES} minutos. "
            "Esto es probablemente un disparo duplicado del mismo horario "
            "(cron nativo de GitHub + respaldo de cron-job.org). No hago nada."
        )
        return

    _do_fase2(force=False)
    _do_fase1()
    _mark_ran("ciclo")


def fase1() -> None:
    """Fuerza SOLO la Fase 1 (subir un trial nuevo). Pensado para pruebas
    manuales desde 'Run workflow', no para el horario programado."""
    if _recently_ran("fase1"):
        print(f"Fase 1 (manual) ya se ejecutó hace menos de {RECENT_RUN_MINUTES} minutos. No hago nada.")
        return
    _do_fase1()
    _mark_ran("fase1")


def fase2() -> None:
    """Fuerza la Fase 2 para TODOS los que estén esperando, sin importar si
    ya cumplieron las 24hs o no. Pensado para pruebas manuales desde 'Run
    workflow', no para el horario programado."""
    if _recently_ran("fase2"):
        print(f"Fase 2 (manual) ya se ejecutó hace menos de {RECENT_RUN_MINUTES} minutos. No hago nada.")
        return
    _do_fase2(force=True)
    _mark_ran("fase2")


def claim(key: str) -> None:
    """Usado por el workflow de GitHub Actions para "reservar" el turno
    ANTES de hacer ningún trabajo real (publicar en YouTube/Instagram).

    Si esta clave (ciclo/fase1/fase2) ya se reservó/ejecutó hace menos de
    RECENT_RUN_MINUTES, termina con código de salida 2 (le avisa al workflow
    que tiene que saltear esta corrida) sin modificar nada. Si no, marca la
    clave como "reservada ahora" en state/last_run.json y termina con
    código 0; el workflow va a intentar commitear y pushear ese cambio de
    inmediato, ANTES de tocar cualquier API real.

    Por qué esto importa: el "concurrency" del workflow de GitHub Actions
    debería evitar que dos corridas se ejecuten en paralelo, pero una vez
    falló (dos corridas llegaron a ejecutar el orquestador completo al mismo
    tiempo, y una publicó un video dos veces antes de que la segunda se
    diera cuenta). Este chequeo no depende de que GitHub coordine bien las
    corridas: usa el hecho de que Git solo deja que UNA de dos corridas que
    intentan pushear casi al mismo tiempo tenga éxito (la otra es
    rechazada). Si esta corrida pierde esa carrera, se cancela sola antes de
    publicar nada, así nunca se llega a publicar el mismo video dos veces.
    """
    if _recently_ran(key):
        print(
            f"'{key}' ya se reservó/ejecutó hace menos de {RECENT_RUN_MINUTES} "
            "minutos. Salteo esta corrida antes de hacer ningún trabajo real."
        )
        sys.exit(2)
    _mark_ran(key)
    print(f"Turno '{key}' reservado. Sigue el resto de la corrida.")


if __name__ == "__main__":
    if len(sys.argv) < 2 or sys.argv[1] not in ("ciclo", "fase1", "fase2", "claim"):
        print("Uso: python orchestrator.py [ciclo|fase1|fase2|claim <clave>]")
        sys.exit(1)

    if sys.argv[1] == "claim":
        if len(sys.argv) != 3:
            print("Uso: python orchestrator.py claim [ciclo|fase1|fase2]")
            sys.exit(1)
        claim(sys.argv[2])
    else:
        {"ciclo": ciclo, "fase1": fase1, "fase2": fase2}[sys.argv[1]]()
