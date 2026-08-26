"""
Orquestador de las dos fases del posteo.

FASE 1 (fase1): agarra el próximo video "pending" de config/queue.json,
  lo sube a YouTube, publica el Trial Reel en Instagram, y AGREGA a
  state/pending_normal.json (una lista) los datos necesarios para su
  Fase 2 futura.

FASE 2 (fase2): lee state/pending_normal.json y publica el Reel normal del
  video MÁS ANTIGUO en espera (el primero de la lista), como post
  independiente del trial (no lo modifica ni lo reemplaza). Si hay más de
  uno esperando (por ejemplo porque se saltearon corridas), los va
  procesando de a uno por corrida, en orden.

Se ejecuta desde GitHub Actions, que llama:
    python scripts/orchestrator.py fase1
    python scripts/orchestrator.py fase2

El propio workflow decide qué fase correr según el cron que disparó
la corrida (ver .github/workflows/publish.yml).

PROTECCIÓN CONTRA DISPAROS DUPLICADOS: como hay dos disparadores en paralelo
(el cron nativo de GitHub Actions + el respaldo externo de cron-job.org),
puede pasar que los dos disparen casi al mismo horario para la MISMA fase
(por ejemplo si GitHub se atrasa unos minutos y coincide con cron-job.org).
Para que eso no haga que se procesen dos videos en el mismo horario en vez
de uno, cada fase registra en state/last_run.json cuándo corrió por última
vez, y si la misma fase ya corrió hace menos de RECENT_RUN_MINUTES minutos,
la corrida nueva no hace nada (asume que es un disparo duplicado del mismo
horario, no un horario nuevo).
"""

import json
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from instagram_publish import publish_reel  # noqa: E402
from youtube_upload import upload_video  # noqa: E402

ROOT = Path(__file__).parent.parent
QUEUE_PATH = ROOT / "config" / "queue.json"
PENDING_PATH = ROOT / "state" / "pending_normal.json"
LAST_RUN_PATH = ROOT / "state" / "last_run.json"

# Ventana de "esto es probablemente un disparo duplicado del mismo horario".
# Los horarios reales de una misma fase están separados por ~3 horas, así que
# cualquier valor bien por debajo de eso (pero por encima del atraso típico
# que puede tener el cron nativo de GitHub) es seguro.
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


def _recently_ran(fase_key: str) -> bool:
    """True si esta fase ya se ejecutó hace menos de RECENT_RUN_MINUTES."""
    data = _load_json(LAST_RUN_PATH, default={}) or {}
    ts = data.get(fase_key)
    if not ts:
        return False
    try:
        last = datetime.fromisoformat(ts)
    except ValueError:
        return False
    return (datetime.now(timezone.utc) - last) < timedelta(minutes=RECENT_RUN_MINUTES)


def _mark_ran(fase_key: str) -> None:
    data = _load_json(LAST_RUN_PATH, default={}) or {}
    data[fase_key] = datetime.now(timezone.utc).isoformat()
    _save_json(LAST_RUN_PATH, data)


def fase1() -> None:
    if _recently_ran("fase1"):
        print(
            f"Fase 1 ya se ejecutó hace menos de {RECENT_RUN_MINUTES} minutos. "
            "Esto es probablemente un disparo duplicado del mismo horario "
            "(cron nativo de GitHub + respaldo de cron-job.org). No hago nada "
            "para no procesar dos videos en el mismo horario."
        )
        return

    queue = _load_json(QUEUE_PATH)

    siguiente = next(
        (v for v in queue if v["status"] == "pending" and (ROOT / v["file"]).exists()),
        None,
    )
    if siguiente is None:
        print("No hay videos pendientes en la cola (o están pending pero el archivo todavía no fue subido). Nada que hacer.")
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

    print(f"Procesando video {siguiente['id']} ({siguiente['file']})")

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
    pendientes = _load_json(PENDING_PATH, default=[]) or []
    pendientes.append(
        {
            "id": siguiente["id"],
            "video_url": video_url,
            "caption": caption,
        }
    )
    _save_json(PENDING_PATH, pendientes)

    _mark_ran("fase1")

    print(f"Fase 1 lista para {siguiente['id']}. La Fase 2 publicará el reel normal en ~30 min.")


def fase2() -> None:
    if _recently_ran("fase2"):
        print(
            f"Fase 2 ya se ejecutó hace menos de {RECENT_RUN_MINUTES} minutos. "
            "Esto es probablemente un disparo duplicado del mismo horario "
            "(cron nativo de GitHub + respaldo de cron-job.org). No hago nada "
            "para no publicar el mismo reel normal dos veces."
        )
        return

    pendientes = _load_json(PENDING_PATH, default=[]) or []

    if not pendientes:
        print("No hay ningún reel esperando su publicación normal. Nada que hacer.")
        return

    pending = pendientes[0]

    queue = _load_json(QUEUE_PATH)
    item = next((v for v in queue if v["id"] == pending["id"]), None)
    if item is None:
        print(f"Aviso: no se encontró en la cola el video {pending['id']}. Lo descarto de la lista de espera.")
        _save_json(PENDING_PATH, pendientes[1:])
        return

    ig_normal_id = publish_reel(video_url=pending["video_url"], caption=pending["caption"], trial=False)

    item["status"] = "done"
    item["ig_normal_media_id"] = ig_normal_id
    _save_json(QUEUE_PATH, queue)

    pendientes = pendientes[1:]
    _save_json(PENDING_PATH, pendientes)

    _mark_ran("fase2")

    print(f"Fase 2 completa para {pending['id']}: reel normal publicado.")
    if pendientes:
        restantes = ", ".join(p["id"] for p in pendientes)
        print(f"Nota: todavía quedan {len(pendientes)} video(s) esperando su Fase 2, se van a procesar de a uno en las próximas corridas: {restantes}")


if __name__ == "__main__":
    if len(sys.argv) != 2 or sys.argv[1] not in ("fase1", "fase2"):
        print("Uso: python orchestrator.py [fase1|fase2]")
        sys.exit(1)

    if sys.argv[1] == "fase1":
        fase1()
    else:
        fase2()
