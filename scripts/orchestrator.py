"""
Orquestador de las dos fases del posteo.

FASE 1 (fase1): agarra el próximo video "pending" de config/queue.json,
  lo sube a YouTube, publica el Trial Reel en Instagram, y guarda en
  state/pending_normal.json los datos necesarios para la Fase 2.

FASE 2 (fase2): lee state/pending_normal.json (lo que dejó la Fase 1 media
  hora antes) y publica el Reel normal en Instagram, como post
  independiente del trial (no lo modifica ni lo reemplaza).

Se ejecuta desde GitHub Actions, que llama:
    python scripts/orchestrator.py fase1
    python scripts/orchestrator.py fase2

El propio workflow decide qué fase correr según el cron que disparó
la corrida (ver .github/workflows/publish.yml).
"""

import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from instagram_publish import publish_reel  # noqa: E402
from youtube_upload import upload_video  # noqa: E402

ROOT = Path(__file__).parent.parent
QUEUE_PATH = ROOT / "config" / "queue.json"
PENDING_PATH = ROOT / "state" / "pending_normal.json"


def _video_public_url(file_relative_path: str) -> str:
    """Construye la URL pública raw.githubusercontent.com del video.

    Requiere que el repo sea PÚBLICO (ver GUIA_CONFIGURACION.md) y que el
    video ya esté commiteado en la rama principal antes de que corra
    esta fase.
    """
    repo = os.environ["GITHUB_REPOSITORY"]  # ej: "usuario/tiktok-repost-bot"
    branch = os.environ.get("GITHUB_BRANCH", "main")
    return f"https://raw.githubusercontent.com/{repo}/{branch}/{file_relative_path}"


def _load_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def _save_json(path: Path, data) -> None:
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


def fase1() -> None:
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

    _save_json(
        PENDING_PATH,
        {
            "id": siguiente["id"],
            "video_url": video_url,
            "caption": caption,
        },
    )

    print(f"Fase 1 lista para {siguiente['id']}. La Fase 2 publicará el reel normal en ~30 min.")


def fase2() -> None:
    pending = _load_json(PENDING_PATH)

    if not pending:
        print("No hay ningún reel esperando su publicación normal. Nada que hacer.")
        return

    queue = _load_json(QUEUE_PATH)
    item = next((v for v in queue if v["id"] == pending["id"]), None)
    if item is None:
        print(f"Aviso: no se encontró en la cola el video {pending['id']}")
        return

    ig_normal_id = publish_reel(video_url=pending["video_url"], caption=pending["caption"], trial=False)

    item["status"] = "done"
    item["ig_normal_media_id"] = ig_normal_id
    _save_json(QUEUE_PATH, queue)
    _save_json(PENDING_PATH, {})

    print(f"Fase 2 completa para {pending['id']}: reel normal publicado.")


if __name__ == "__main__":
    if len(sys.argv) != 2 or sys.argv[1] not in ("fase1", "fase2"):
        print("Uso: python orchestrator.py [fase1|fase2]")
        sys.exit(1)

    if sys.argv[1] == "fase1":
        fase1()
    else:
        fase2()
