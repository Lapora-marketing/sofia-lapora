# tests/auditoria_completa.py — Auditoria completa del flujo SofIA
"""
Audita TODO el sistema para diagnosticar por que Meta no entrega
los webhooks de mensajes reales a SofIA.
"""

import asyncio
import os
import sys
import httpx

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv
load_dotenv(override=True)


async def auditar():
    token = os.getenv("META_ACCESS_TOKEN")
    phone_id = os.getenv("META_PHONE_NUMBER_ID")
    waba_id = os.getenv("META_WABA_ID")
    verify_token = os.getenv("META_VERIFY_TOKEN")
    api_version = "v21.0"

    print("=" * 70)
    print("  AUDITORIA COMPLETA — SofIA Lapora")
    print("=" * 70)
    print()

    headers = {"Authorization": f"Bearer {token}"}

    async with httpx.AsyncClient(timeout=30.0) as client:

        # ============================================================
        # 1. RAILWAY - Verificar que SofIA responde
        # ============================================================
        print("[1] RAILWAY — Verificando endpoints de SofIA...")
        try:
            r = await client.get("https://sofia-lapora-production.up.railway.app/")
            print(f"   GET /       : {r.status_code} -> {r.text[:100]}")
            r = await client.get(
                f"https://sofia-lapora-production.up.railway.app/webhook"
                f"?hub.mode=subscribe&hub.verify_token={verify_token}&hub.challenge=12345"
            )
            print(f"   GET /webhook: {r.status_code} -> {r.text[:50]}")
        except Exception as e:
            print(f"   ERROR: {e}")

        # ============================================================
        # 2. META - Verificar phone number ID
        # ============================================================
        print()
        print("[2] META — Verificando phone number ID...")
        r = await client.get(
            f"https://graph.facebook.com/{api_version}/{phone_id}",
            headers=headers,
        )
        print(f"   Status: {r.status_code}")
        if r.status_code == 200:
            data = r.json()
            print(f"   Display name: {data.get('display_phone_number')}")
            print(f"   Verified name: {data.get('verified_name')}")
            print(f"   Quality: {data.get('quality_rating')}")
            print(f"   Status: {data.get('status')}")
        else:
            print(f"   Body: {r.text[:300]}")

        # ============================================================
        # 3. META - Verificar WABA (cuenta WhatsApp Business)
        # ============================================================
        print()
        print("[3] META — Verificando WhatsApp Business Account...")
        r = await client.get(
            f"https://graph.facebook.com/{api_version}/{waba_id}",
            headers=headers,
            params={"fields": "name,timezone_id,message_template_namespace,id"},
        )
        print(f"   Status: {r.status_code}")
        print(f"   Body: {r.text[:300]}")

        # ============================================================
        # 4. META - Verificar suscripciones del webhook
        # ============================================================
        print()
        print("[4] META — Verificando suscripciones del webhook en la WABA...")
        r = await client.get(
            f"https://graph.facebook.com/{api_version}/{waba_id}/subscribed_apps",
            headers=headers,
        )
        print(f"   Status: {r.status_code}")
        print(f"   Body: {r.text[:500]}")

        # ============================================================
        # 5. META - Verificar destinatarios autorizados
        # ============================================================
        print()
        print("[5] META — Lista de numeros destinatarios autorizados...")
        # Este endpoint depende del app_id
        r = await client.get(
            f"https://graph.facebook.com/{api_version}/{phone_id}/whatsapp_business_phone_number",
            headers=headers,
        )
        print(f"   Status: {r.status_code}")
        print(f"   Body: {r.text[:300]}")

        # ============================================================
        # 6. META - Probar envio de template hello_world
        # ============================================================
        print()
        print("[6] META — Probando envio de template directo...")
        url = f"https://graph.facebook.com/{api_version}/{phone_id}/messages"
        payload = {
            "messaging_product": "whatsapp",
            "to": "573209989552",
            "type": "template",
            "template": {
                "name": "hello_world",
                "language": {"code": "en_US"},
            },
        }
        r = await client.post(
            url,
            json=payload,
            headers={**headers, "Content-Type": "application/json"},
        )
        print(f"   Status: {r.status_code}")
        print(f"   Body: {r.text[:300]}")

        # ============================================================
        # RESUMEN
        # ============================================================
        print()
        print("=" * 70)
        print("  DIAGNOSTICO FINAL")
        print("=" * 70)


if __name__ == "__main__":
    asyncio.run(auditar())
