# tests/test_meta_envio.py — Test de envio real via Meta Cloud API
"""
Envia un mensaje de prueba usando el template pre-aprobado "hello_world".

Este script envia el template "hello_world" que Meta tiene pre-aprobado
para validar que la conexion con Meta Cloud API funciona.

Despues de recibir ese mensaje, si tu respondes desde WhatsApp,
SofIA podra contestar con texto libre durante las siguientes 24 horas.

USO:
    python tests/test_meta_envio.py +573209989552
"""

import asyncio
import sys
import os
import httpx

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv

load_dotenv(override=True)


async def enviar_template_hello_world(telefono: str) -> bool:
    """Envia el template pre-aprobado 'hello_world' a un numero."""
    access_token = os.getenv("META_ACCESS_TOKEN")
    phone_number_id = os.getenv("META_PHONE_NUMBER_ID")
    api_version = "v21.0"

    url = f"https://graph.facebook.com/{api_version}/{phone_number_id}/messages"
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json",
    }
    payload = {
        "messaging_product": "whatsapp",
        "to": telefono,
        "type": "template",
        "template": {
            "name": "hello_world",
            "language": {"code": "en_US"},
        },
    }

    async with httpx.AsyncClient(timeout=30.0) as client:
        r = await client.post(url, json=payload, headers=headers)
        print(f"\nRespuesta HTTP: {r.status_code}")
        print(f"Body: {r.text}\n")
        return r.status_code == 200


async def main():
    if len(sys.argv) < 2:
        print("Uso: python tests/test_meta_envio.py +573209989552")
        sys.exit(1)

    telefono = sys.argv[1].replace("+", "")

    print()
    print("=" * 60)
    print("  Test de envio via Meta Cloud API (Template hello_world)")
    print("=" * 60)
    print(f"  Telefono destino: +{telefono}")
    print(f"  Phone Number ID: {os.getenv('META_PHONE_NUMBER_ID')}")
    print()
    print("Enviando template 'hello_world'...")

    exito = await enviar_template_hello_world(telefono)

    if exito:
        print("=" * 60)
        print("  MENSAJE ENVIADO EXITOSAMENTE")
        print("=" * 60)
        print(f"\n  Revisa el WhatsApp del numero +{telefono}")
        print("\n  Despues de recibirlo, responde 'Hola' desde WhatsApp.")
        print("  Eso abrira la ventana de 24 horas para que SofIA")
        print("  pueda contestar con texto libre.")
    else:
        print("=" * 60)
        print("  ERROR AL ENVIAR — revisa los logs arriba")
        print("=" * 60)


if __name__ == "__main__":
    asyncio.run(main())
