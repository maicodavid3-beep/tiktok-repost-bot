"""
Script de UN SOLO USO para obtener tu YT_REFRESH_TOKEN.

Lo corrés UNA vez en tu computadora (no en GitHub Actions), se abre el
navegador, iniciás sesión con la cuenta de Google dueña del canal de
YouTube, y el script te imprime el refresh token para que lo cargues
como GitHub Secret.

Uso:
    pip install google-auth-oauthlib
    python get_youtube_refresh_token.py client_secret.json
"""

import sys

from google_auth_oauthlib.flow import InstalledAppFlow

SCOPES = ["https://www.googleapis.com/auth/youtube.upload"]


def main():
    if len(sys.argv) != 2:
        print("Uso: python get_youtube_refresh_token.py <ruta-a-client_secret.json>")
        sys.exit(1)

    flow = InstalledAppFlow.from_client_secrets_file(sys.argv[1], SCOPES)
    creds = flow.run_local_server(port=0)

    print("\n¡Listo! Guardá estos 3 valores como GitHub Secrets:\n")
    print(f"YT_CLIENT_ID={creds.client_id}")
    print(f"YT_CLIENT_SECRET={creds.client_secret}")
    print(f"YT_REFRESH_TOKEN={creds.refresh_token}")


if __name__ == "__main__":
    main()
