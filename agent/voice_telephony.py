# -*- coding: utf-8 -*-
# agent/voice_telephony.py — Integración real con Twilio + Deepgram + ElevenLabs
# Lapora Marketing Digital — Voice Bot Day 2

"""
Capa de telefonía REAL del Voice Bot.

Arquitectura por llamada:

    Twilio Voice (outbound call)
        ↓ Media Streams (WebSocket bidireccional, μ-law 8kHz)
    agent/voice_bot /voice/twilio/stream/{call_id}
        ↓ TwilioStreamHandler (esta clase)
        │
        ├─ Audio entrante → DeepgramStreamHandler
        │                       ↓ Transcripts parciales/finales
        │                       └─ Detecta silencio → llama voice_brain.generar_turno()
        │
        └─ Respuesta del brain → ElevenLabsTTS
                                    ↓ Audio μ-law 8kHz
                                    └─ Envía de vuelta a Twilio

Diseño:
- Audio format: Twilio Media Streams usa μ-law 8kHz mono. Deepgram nova-2 lo
  acepta nativo. ElevenLabs entrega ulaw_8000 nativo. No hay conversión.
- VAD: Deepgram `endpointing` detecta cuándo la persona terminó de hablar.
- Latencia: STT streaming (200ms) + Claude (300-500ms) + TTS streaming (150ms)
  = ~700-1000ms total. Aceptable para conversación natural.

Si falta CUALQUIER credencial, las funciones retornan errores claros pero el
sistema sigue funcionando en mock mode (voice_mock.py).
"""

import os
import json
import asyncio
import logging
import base64
from typing import Optional, AsyncIterator
from datetime import datetime
import httpx

logger = logging.getLogger("agentkit")


# ════════════════════════════════════════════════════════════
# CONFIGURACIÓN DESDE ENV VARS
# ════════════════════════════════════════════════════════════

def creds_twilio() -> tuple[Optional[str], Optional[str], Optional[str]]:
    """(account_sid, auth_token, from_number) — None si falta alguna."""
    return (
        os.getenv("TWILIO_ACCOUNT_SID") or None,
        os.getenv("TWILIO_AUTH_TOKEN") or None,
        os.getenv("TWILIO_VOICE_NUMBER") or None,
    )


def creds_deepgram() -> Optional[str]:
    return os.getenv("DEEPGRAM_API_KEY") or None


def creds_elevenlabs() -> tuple[Optional[str], str]:
    """(api_key, voice_id). voice_id por defecto: 'EXAVITQu4vr4xnSDxMaL' (Sarah ES)."""
    return (
        os.getenv("ELEVENLABS_API_KEY") or None,
        os.getenv("ELEVENLABS_VOICE_ID", "EXAVITQu4vr4xnSDxMaL"),
    )


def base_url_publica() -> str:
    """URL pública del backend (para Twilio callbacks)."""
    return os.getenv("PUBLIC_BASE_URL", "https://sofia-lapora-production.up.railway.app").rstrip("/")


# ════════════════════════════════════════════════════════════
# TWILIO — Iniciar llamada outbound vía REST API
# ════════════════════════════════════════════════════════════

async def twilio_iniciar_call(
    to_number: str,
    call_id: int,
    timeout_seg: int = 20,
) -> dict:
    """Inicia una llamada Twilio outbound.

    Args:
        to_number: número destino con +57 prefix
        call_id: nuestro VoiceCall.id (lo pasamos para identificar en el callback)
        timeout_seg: cuánto esperar que conteste antes de dar no_answer

    Returns:
        {"exito": bool, "twilio_call_sid": str, "error": str}
    """
    sid, token, from_num = creds_twilio()
    if not (sid and token and from_num):
        return {
            "exito": False,
            "twilio_call_sid": "",
            "error": "Credenciales Twilio faltantes en .env",
        }

    base = base_url_publica()
    answer_url = f"{base}/voice/twilio/answer?call_id={call_id}"
    status_url = f"{base}/voice/twilio/status"

    # Twilio REST API — POST a /Accounts/{SID}/Calls.json
    api_url = f"https://api.twilio.com/2010-04-01/Accounts/{sid}/Calls.json"
    auth = base64.b64encode(f"{sid}:{token}".encode()).decode()

    data = {
        "To": to_number,
        "From": from_num,
        "Url": answer_url,
        "StatusCallback": status_url,
        "StatusCallbackEvent": ["initiated", "ringing", "answered", "completed"],
        "StatusCallbackMethod": "POST",
        "Timeout": str(timeout_seg),
        "MachineDetection": "Enable",  # Twilio AMD para detectar buzón de voz
        "MachineDetectionTimeout": "5",
    }

    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            r = await client.post(
                api_url,
                data=data,
                headers={"Authorization": f"Basic {auth}"},
            )
        if r.status_code in (200, 201):
            j = r.json()
            return {
                "exito": True,
                "twilio_call_sid": j.get("sid", ""),
                "error": "",
            }
        else:
            logger.error(f"[twilio] init call falló {r.status_code}: {r.text[:300]}")
            return {
                "exito": False,
                "twilio_call_sid": "",
                "error": f"Twilio {r.status_code}: {r.text[:200]}",
            }
    except Exception as e:
        logger.error(f"[twilio] excepción init call: {e}", exc_info=True)
        return {
            "exito": False,
            "twilio_call_sid": "",
            "error": str(e)[:300],
        }


def twiml_para_stream(call_id: int) -> str:
    """Devuelve el TwiML que abre el Media Stream bidireccional.

    Llamado desde el endpoint POST /voice/twilio/answer.
    El WebSocket apunta a /voice/twilio/stream/{call_id}.
    """
    base = base_url_publica()
    # Convertir https → wss
    ws_base = base.replace("https://", "wss://").replace("http://", "ws://")
    stream_url = f"{ws_base}/voice/twilio/stream/{call_id}"

    return f"""<?xml version="1.0" encoding="UTF-8"?>
<Response>
  <Connect>
    <Stream url="{stream_url}">
      <Parameter name="call_id" value="{call_id}" />
    </Stream>
  </Connect>
</Response>"""


# ════════════════════════════════════════════════════════════
# DEEPGRAM — Streaming STT en vivo
# ════════════════════════════════════════════════════════════

class DeepgramStreamSTT:
    """Wrapper de Deepgram streaming para una llamada.

    Conecta a Deepgram via WebSocket, envía audio μ-law 8kHz desde Twilio,
    recibe transcripts parciales/finales en español.

    Usa endpointing nativo de Deepgram para detectar fin de turno.
    """

    DEEPGRAM_URL = "wss://api.deepgram.com/v1/listen"

    def __init__(self):
        self.api_key = creds_deepgram()
        self.ws = None  # type: ignore
        self._closed = False

    async def conectar(self) -> bool:
        """Abre la conexión WebSocket con Deepgram."""
        if not self.api_key:
            logger.error("[deepgram] DEEPGRAM_API_KEY faltante")
            return False

        try:
            import websockets
        except ImportError:
            logger.error("[deepgram] paquete 'websockets' no instalado")
            return False

        # Parámetros del stream
        params = {
            "model": "nova-2",
            "language": "es",
            "encoding": "mulaw",
            "sample_rate": "8000",
            "channels": "1",
            "punctuate": "true",
            "interim_results": "true",
            "endpointing": "500",  # 500ms de silencio = fin del turno
            "smart_format": "true",
        }
        qs = "&".join(f"{k}={v}" for k, v in params.items())
        url = f"{self.DEEPGRAM_URL}?{qs}"

        try:
            self.ws = await websockets.connect(
                url,
                additional_headers={"Authorization": f"Token {self.api_key}"},
                max_size=10 * 1024 * 1024,
            )
            logger.info("[deepgram] conectado")
            return True
        except Exception as e:
            logger.error(f"[deepgram] error conectando: {e}")
            return False

    async def enviar_audio(self, audio_chunk: bytes):
        """Envía un chunk de audio μ-law a Deepgram."""
        if self.ws and not self._closed:
            try:
                await self.ws.send(audio_chunk)
            except Exception as e:
                logger.warning(f"[deepgram] send falló: {e}")

    async def recibir_transcripts(self) -> AsyncIterator[dict]:
        """Yields cada transcript parcial o final de Deepgram.

        Yields:
            {
                "transcript": str,       # texto reconocido
                "is_final": bool,        # True si es final (silencio detectado)
                "speech_final": bool,    # True cuando Deepgram detecta fin de turno
            }
        """
        if not self.ws:
            return
        try:
            async for msg in self.ws:
                if self._closed:
                    break
                try:
                    data = json.loads(msg)
                except Exception:
                    continue

                if data.get("type") == "Results":
                    alt = data.get("channel", {}).get("alternatives", [{}])[0]
                    transcript = (alt.get("transcript") or "").strip()
                    if transcript:
                        yield {
                            "transcript": transcript,
                            "is_final": bool(data.get("is_final", False)),
                            "speech_final": bool(data.get("speech_final", False)),
                        }
        except Exception as e:
            if not self._closed:
                logger.warning(f"[deepgram] recv loop terminó: {e}")

    async def cerrar(self):
        self._closed = True
        if self.ws:
            try:
                await self.ws.close()
            except Exception:
                pass


# ════════════════════════════════════════════════════════════
# ELEVENLABS — Streaming TTS μ-law 8kHz (formato Twilio nativo)
# ════════════════════════════════════════════════════════════

class ElevenLabsStreamTTS:
    """Wrapper de ElevenLabs streaming.

    Pide texto, recibe audio μ-law 8kHz en chunks pequeños listos para Twilio.
    Modelo: eleven_flash_v2_5 (latencia ~150ms, multilenguaje).
    """

    BASE = "https://api.elevenlabs.io/v1"
    MODELO = "eleven_flash_v2_5"
    OUTPUT_FORMAT = "ulaw_8000"  # μ-law 8kHz mono — el formato nativo de Twilio

    def __init__(self):
        self.api_key, self.voice_id = creds_elevenlabs()

    async def sintetizar(self, texto: str) -> AsyncIterator[bytes]:
        """Yields chunks de audio μ-law 8kHz listos para mandar a Twilio.

        Si falla, yields nada (caller debe manejar).
        """
        if not self.api_key:
            logger.error("[elevenlabs] ELEVENLABS_API_KEY faltante")
            return

        if not texto or not texto.strip():
            return

        url = f"{self.BASE}/text-to-speech/{self.voice_id}/stream"
        params = {"output_format": self.OUTPUT_FORMAT}
        headers = {
            "xi-api-key": self.api_key,
            "Content-Type": "application/json",
            "Accept": "audio/basic",
        }
        payload = {
            "text": texto,
            "model_id": self.MODELO,
            "voice_settings": {
                "stability": 0.5,
                "similarity_boost": 0.75,
                "style": 0.15,
                "use_speaker_boost": True,
            },
        }

        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                async with client.stream(
                    "POST", url, params=params, headers=headers, json=payload
                ) as r:
                    if r.status_code != 200:
                        body = await r.aread()
                        logger.error(f"[elevenlabs] {r.status_code}: {body[:200]!r}")
                        return
                    async for chunk in r.aiter_bytes(chunk_size=1024):
                        if chunk:
                            yield chunk
        except Exception as e:
            logger.error(f"[elevenlabs] excepción streaming: {e}", exc_info=True)


# ════════════════════════════════════════════════════════════
# CONTROLLER — orquesta la conversación dentro del WebSocket de Twilio
# ════════════════════════════════════════════════════════════

class ConversacionTelefonica:
    """Estado y orquestación de una llamada activa.

    Mantiene:
    - call: VoiceCall en BD
    - stream_sid: el SID del Media Stream de Twilio (para enviar audio de vuelta)
    - historial: turnos para el brain
    - transcripts_buffer: acumulador de transcripts parciales antes de que sean finales
    """

    def __init__(self, call):
        self.call = call
        self.stream_sid: str = ""
        self.historial: list[dict] = []
        self.transcript_actual = ""
        self.primer_turno_emitido = False
        self.terminada = False
        self.tcps = 0  # turnos del paciente contados
        self.turnos_bot_count = 0

    def variables_brain(self) -> dict:
        """Variables para inyectar al script según el target."""
        return {
            "nombre_doctor":   self.call.target_nombre or "doctor",
            "nombre_negocio":  self.call.target_nombre or "su consultorio",
            "telefono":        self.call.telefono or "",
            "nombre_paciente": self.call.target_nombre or "",
        }
