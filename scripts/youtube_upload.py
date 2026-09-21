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

import google_auth_httplib2
import httplib2
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload

SCOPES = ["https://www.googleapis.com/auth/youtube.upload"]

# Sin esto, la librería de Google no le pone ningún límite de tiempo a las
# conexiones de red: si una conexión se traba a mitad de subir el video (algo
# que puede pasar, por ejemplo, por un problema de red pasajero del runner de
# GitHub Actions), la subida se queda esperando PARA SIEMPRE, sin ningún
# error ni aviso, y la corrida entera queda colgada. Con este timeout, una
# conexión trabada corta con un error a los 2 minutos en vez de colgarse.
HTTP_TIMEOUT_SECONDS = 120


def get_youtube_client():
    creds = Credentials(
        token=None,
        refresh_token=os.environ["YT_REFRESH_TOKEN"],
        client_id=os.environ["YT_CLIENT_ID"],
        client_secret=os.environ["YT_CLIENT_SECRET"],
        token_uri="https://oauth2.googleapis.com/token",
        scopes=SCOPES,
    )

    http = httplib2.Http(timeout=HTTP_TIMEOUT_SECONDS)

    # OJO - esto es lo que causaba el error "RedirectMissingLocation" que
    # empezó a aparecer al subir videos por partes (chunksize de abajo):
    #
    # Cuando se sube el video en pedazos, el servidor de YouTube responde a
    # cada pedazo intermedio (no al último) con el código HTTP 308, que en
    # este contexto significa "recibido, mandame el resto" (no es un
    # redirect de verdad, no trae ningún header "Location"). httplib2 trata
    # SIEMPRE el código 308 como si fuera un redirect que hay que seguir,
    # sin importar el método HTTP usado (esto viene de una interpretación
    # estricta de una RFC, ver https://github.com/httplib2/httplib2 issue
    # #156 y https://github.com/googleapis/google-api-python-client issue
    # #803/#891) — como esa respuesta 308 no trae "Location", httplib2
    # explota con "Redirected but the response is missing a Location:
    # header" en vez de simplemente devolvérsela a la librería de Google,
    # que sabe perfectamente qué hacer con un 308 en medio de una subida
    # (seguir con el próximo pedazo).
    #
    # Con el archivo entero en un solo pedazo (como era antes de este
    # cambio) nunca aparecía este 308 intermedio -> nunca se disparaba el
    # bug. Al subir en pedazos de a 8MB, cualquier video de más de 8MB
    # empezó a recibir ese 308 legítimo y a chocar con este comportamiento
    # de httplib2.
    #
    # La solución: sacarle el 308 a la lista de códigos que httplib2
    # considera "hay que seguir este redirect", para que lo deje pasar tal
    # cual a la librería de Google (verificado línea por línea contra el
    # código fuente de httplib2 instalado). Esto no afecta redirects reales
    # (301/302/303/307), que siguen funcionando igual que siempre.
    http.redirect_codes = http.redirect_codes - {308}

    authorized_http = google_auth_httplib2.AuthorizedHttp(creds, http=http)
    return build("youtube", "v3", http=authorized_http)


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

    # Subimos en pedazos de 8MB en vez de todo el archivo de una sola vez
    # (chunksize=-1). Así, cada pedido de red individual es chico y termina
    # rápido (el timeout de arriba cubre cada pedazo, no el archivo entero),
    # y de paso vamos viendo el progreso real en el log en vez de silencio
    # total hasta que termine todo.
    media = MediaFileUpload(video_path, chunksize=8 * 1024 * 1024, resumable=True, mimetype="video/mp4")

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
