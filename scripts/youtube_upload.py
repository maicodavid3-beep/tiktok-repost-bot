"""
Sube un video a YouTube (como Short) usando la Data API v3.

Requiere las siguientes variables de entorno (se configuran como GitHub Secrets):
  - YT_CLIENT_ID
  - YT_CLIENT_SECRET
  - YT_REFRESH_TOKEN

El refresh token se obtiene UNA sola vez siguiendo la guía de configuración
(GUIA_CONFIGURACION.md). Una vez que lo tenés, la subida es 100% automática,
sin volver a pedir login.
"""

import os
import sys

from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload

SCOPES = ["https://www.googleapis.com/auth/youtube.upload"]


def get_youtube_client():
    creds = Credentials(
        token=None,
        refresh_token=os.environ["YT_REFRESH_TOKEN"],
        client_id=os.environ["YT_CLIENT_ID"],
        client_secret=os.environ["YT_CLIENT_SECRET"],
        token_uri="https://oauth2.googleapis.com/token",
        scopes=SCOPES,
    )
    return build("youtube", "v3", credentials=creds)


def upload_video(video_path: str, title: str, description: str, tags=None) -> str:
    """Sube el video y devuelve el video_id de YouTube."""
    youtube = get_youtube_client()

    body = {
        "snippet": {
            "title": title[:100] if title else "Short",
            "description": description or "",
            "tags": tags or [],
            "categoryId": "22",  # People & Blogs (podés ajustar la categoría)
        },
        "status": {
            "privacyStatus": "public",
            "selfDeclaredMadeForKids": False,
        },
    }

    media = MediaFileUpload(video_path, chunksize=-1, resumable=True, mimetype="video/mp4")

    request = youtube.videos().insert(part="snippet,status", body=body, media_body=media)

    response = None
    while response is None:
        status, response = request.next_chunk()
        if status:
            print(f"Subiendo a YouTube... {int(status.progress() * 100)}%")

    video_id = response["id"]
    print(f"Subido a YouTube: https://youtube.com/shorts/{video_id}")
    return video_id


if __name__ == "__main__":
    # Uso manual de prueba: python youtube_upload.py video.mp4 "Titulo" "Descripcion"
    if len(sys.argv) < 4:
        print("Uso: python youtube_upload.py <video_path> <title> <description>")
        sys.exit(1)
    upload_video(sys.argv[1], sys.argv[2], sys.argv[3])
