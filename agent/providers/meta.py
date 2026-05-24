# agent/providers/meta.py — Adaptador para Meta WhatsApp Cloud API
# Generado por AgentKit

"""
Proveedor de WhatsApp usando la API oficial de Meta (Cloud API).
Documentacion: https://developers.facebook.com/docs/whatsapp/cloud-api
"""

import os
import logging
import httpx
from fastapi import Request
from agent.providers.base import ProveedorWhatsApp, MensajeEntrante

logger = logging.getLogger("agentkit")


class ProveedorMeta(ProveedorWhatsApp):
    """Proveedor de WhatsApp usando la API oficial de Meta (Cloud API)."""

    def __init__(self):
        self.access_token = os.getenv("META_ACCESS_TOKEN")
        self.phone_number_id = os.getenv("META_PHONE_NUMBER_ID")
        self.verify_token = os.getenv("META_VERIFY_TOKEN", "lapora-sofia-verify")
        # Version de la Graph API (usa la mas reciente estable)
        self.api_version = "v21.0"

    async def validar_webhook(self, request: Request) -> dict | int | None:
        """
        Meta requiere verificacion GET con hub.verify_token.
        Cuando configuras el webhook en Meta, ellos hacen un GET con
        hub.mode=subscribe & hub.verify_token=TU_TOKEN & hub.challenge=NUMERO
        Debes devolver el challenge tal cual si el token coincide.
        """
        params = request.query_params
        mode = params.get("hub.mode")
        token = params.get("hub.verify_token")
        challenge = params.get("hub.challenge")

        if mode == "subscribe" and token == self.verify_token:
            logger.info("Webhook de Meta verificado exitosamente")
            try:
                return int(challenge)
            except (TypeError, ValueError):
                return challenge

        logger.warning(
            f"Verificacion de webhook Meta fallida. "
            f"mode={mode}, token_recibido={token}"
        )
        return None

    async def parsear_webhook(self, request: Request) -> list[MensajeEntrante]:
        """
        Parsea el payload anidado de Meta Cloud API.

        Estructura del payload:
        {
          "entry": [
            {
              "changes": [
                {
                  "value": {
                    "messages": [
                      {
                        "from": "573228783019",
                        "id": "wamid.xxx",
                        "text": {"body": "Hola"},
                        "type": "text"
                      }
                    ]
                  }
                }
              ]
            }
          ]
        }
        """
        try:
            body = await request.json()
        except Exception as e:
            logger.error(f"No se pudo parsear JSON del webhook Meta: {e}")
            return []

        mensajes = []

        for entry in body.get("entry", []):
            for change in entry.get("changes", []):
                value = change.get("value", {})

                # Procesar mensajes entrantes
                for msg in value.get("messages", []):
                    tipo = msg.get("type")

                    # Solo procesamos texto por ahora
                    if tipo == "text":
                        mensajes.append(MensajeEntrante(
                            telefono=msg.get("from", ""),
                            texto=msg.get("text", {}).get("body", ""),
                            mensaje_id=msg.get("id", ""),
                            es_propio=False,  # Meta solo envia mensajes entrantes aqui
                        ))
                    elif tipo in ("image", "audio", "video", "document"):
                        # Por ahora respondemos a multimedia con texto generico
                        mensajes.append(MensajeEntrante(
                            telefono=msg.get("from", ""),
                            texto=f"[El usuario envio un {tipo}]",
                            mensaje_id=msg.get("id", ""),
                            es_propio=False,
                        ))
                    else:
                        logger.info(f"Tipo de mensaje no soportado: {tipo}")

        return mensajes

    async def enviar_mensaje(self, telefono: str, mensaje: str) -> bool:
        """Envia mensaje de texto via Meta WhatsApp Cloud API."""
        if not self.access_token or not self.phone_number_id:
            logger.error(
                "META_ACCESS_TOKEN o META_PHONE_NUMBER_ID no configurados en .env"
            )
            return False

        url = (
            f"https://graph.facebook.com/{self.api_version}"
            f"/{self.phone_number_id}/messages"
        )
        headers = {
            "Authorization": f"Bearer {self.access_token}",
            "Content-Type": "application/json",
        }
        payload = {
            "messaging_product": "whatsapp",
            "recipient_type": "individual",
            "to": telefono,
            "type": "text",
            "text": {
                "preview_url": False,
                "body": mensaje,
            },
        }

        async with httpx.AsyncClient(timeout=30.0) as client:
            try:
                r = await client.post(url, json=payload, headers=headers)
                if r.status_code != 200:
                    logger.error(
                        f"Error Meta API ({r.status_code}): {r.text}"
                    )
                    return False
                logger.info(f"Mensaje enviado a {telefono} via Meta Cloud API")
                return True
            except Exception as e:
                logger.error(f"Excepcion enviando mensaje a Meta: {e}")
                return False
