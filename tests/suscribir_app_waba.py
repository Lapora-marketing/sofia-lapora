# tests/suscribir_app_waba.py — Suscribir la app a la WABA en Meta
"""
Suscribe la app de Meta a la WhatsApp Business Account.
Sin esto, los webhooks de mensajes reales NO llegan al servidor.

Endpoint: POST /{WABA_ID}/subscribed_apps
"""

import asyncio
import os
import sys
import httpx

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv
load_dotenv(override=True)


async def suscribir():
    token = os.getenv("META_ACCESS_TOKEN")
    waba_id = os.getenv("META_WABA_ID")
    api_version = "v21.0"

    print("=" * 60)
    print("  SUSCRIBIR APP A LA WABA")
    print("=" * 60)
    print(f"  WABA ID: {waba_id}")
    print()

    url = f"https://graph.facebook.com/{api_version}/{waba_id}/subscribed_apps"
    headers = {"Authorization": f"Bearer {token}"}

    async with httpx.AsyncClient(timeout=30.0) as client:
        print("[1] Suscribiendo app a la WABA...")
        r = await client.post(url, headers=headers)
        print(f"    Status: {r.status_code}")
        print(f"    Body:   {r.text}")

        # Verificar
        print()
        print("[2] Verificando que la suscripcion quedo activa...")
        r2 = await client.get(url, headers=headers)
        print(f"    Status: {r2.status_code}")
        print(f"    Body:   {r2.text}")

        # Verificar Webhook fields tambien
        print()
        print("[3] Verificando que la WABA tiene fields del webhook activos...")
        url_fields = f"https://graph.facebook.com/{api_version}/{waba_id}"
        r3 = await client.get(
            url_fields,
            headers=headers,
            params={"fields": "id,name,subscribed_apps"},
        )
        print(f"    Status: {r3.status_code}")
        print(f"    Body:   {r3.text}")

        print()
        print("=" * 60)
        if r.status_code == 200:
            print("  EXITO — La app esta suscrita a la WABA")
            print("=" * 60)
            print("  Ahora si manda un mensaje desde WhatsApp")
            print("  y SofIA deberia responderte automaticamente.")
        else:
            print("  ERROR — Revisa la respuesta arriba")
            print("=" * 60)


if __name__ == "__main__":
    asyncio.run(suscribir())
