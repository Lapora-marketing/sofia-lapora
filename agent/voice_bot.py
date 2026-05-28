# -*- coding: utf-8 -*-
# agent/voice_bot.py — Lapora Voice Bot: calling bot con Twilio + Claude + ElevenLabs
# Lapora Marketing Digital

"""
Voice Bot de Lapora — Day 1 skeleton.

Endpoints expuestos:
- GET  /voice/health                          → health check
- POST /voice/twilio/answer                   → TwiML cuando Twilio inicia la llamada
- WS   /voice/twilio/stream/{call_id}         → Media Streams bidireccional (audio)
- POST /voice/twilio/status                   → callbacks de Twilio (estado de la llamada)
- GET  /voice/metricas                        → JSON con métricas (cola, outcomes, costo)
- POST /voice/optout                          → registrar opt-out manualmente
- POST /voice/encolar/prospectos              → cargar el CSV de prospectos a la cola

Día 1 (HOY): solo skeleton con endpoints stub que responden correctamente.
Día 2+: integración real con Twilio + Deepgram + ElevenLabs.
"""

import os
import logging
from datetime import datetime
from typing import Optional
from fastapi import APIRouter, Request, HTTPException, Form, WebSocket, WebSocketDisconnect
from fastapi.responses import Response, JSONResponse, PlainTextResponse
from pydantic import BaseModel, Field
from sqlalchemy import select, desc

from agent.memory import async_session
from agent.voice_models import (
    VoiceCall, VoiceQueue, VoiceTranscript, VoiceOptOut,
    telefono_en_optout, registrar_optout, encolar_prospecto, metricas_voice,
)

logger = logging.getLogger("agentkit")

router = APIRouter(prefix="/voice", tags=["voice-bot"])


# ════════════════════════════════════════════════════════════
# HEALTH CHECK
# ════════════════════════════════════════════════════════════

@router.get("/health")
async def health():
    """Health check rápido del voice bot."""
    creds = {
        "twilio":     bool(os.getenv("TWILIO_ACCOUNT_SID") and os.getenv("TWILIO_AUTH_TOKEN")),
        "twilio_num": bool(os.getenv("TWILIO_VOICE_NUMBER")),
        "deepgram":   bool(os.getenv("DEEPGRAM_API_KEY")),
        "elevenlabs": bool(os.getenv("ELEVENLABS_API_KEY")),
        "anthropic":  bool(os.getenv("ANTHROPIC_API_KEY")),
    }
    listo = all(creds.values())
    return {
        "status": "ok" if listo else "config_pendiente",
        "service": "lapora-voice-bot",
        "credenciales": creds,
        "listo_para_llamar": listo,
    }


# ════════════════════════════════════════════════════════════
# TWILIO — Callback inicial (TwiML response)
# ════════════════════════════════════════════════════════════

@router.post("/twilio/answer")
async def twilio_answer(request: Request):
    """Cuando Twilio responde la llamada, devuelve TwiML que abre Media Stream.

    Día 2+: TwiML real con <Connect><Stream> apuntando a /voice/twilio/stream/{call_id}
    Día 1: TwiML stub que dice "Hola, soy SofIA. Sistema en construcción." y cuelga.
    """
    form = await request.form()
    call_sid = form.get("CallSid", "")
    to_number = form.get("To", "")
    logger.info(f"[voice] Twilio answer: SID={call_sid} to={to_number}")

    # TwiML stub (Día 1) — voz de Twilio, sin streaming aún
    twiml = """<?xml version="1.0" encoding="UTF-8"?>
<Response>
  <Say voice="Polly.Lupe-Neural" language="es-MX">
    Hola, soy SofIA, asistente virtual de Lapora.
    El sistema de llamadas está en construcción. Pronto te llamamos de verdad.
  </Say>
  <Hangup/>
</Response>"""
    return Response(content=twiml, media_type="application/xml")


@router.post("/twilio/status")
async def twilio_status(request: Request):
    """Callback de Twilio con el estado final de la llamada.

    Twilio nos avisa cuando la llamada termina (CallStatus=completed) con:
    - CallDuration: segundos
    - SipResponseCode: 200, 487, etc.
    - RecordingUrl: si hay grabación

    Actualizamos VoiceCall.estado, duracion_seg, costo_usd y disparamos análisis.
    """
    form = await request.form()
    call_sid = form.get("CallSid", "")
    status = form.get("CallStatus", "")
    duration = int(form.get("CallDuration", 0) or 0)

    logger.info(f"[voice] Twilio status: SID={call_sid} status={status} dur={duration}s")

    async with async_session() as session:
        call = (await session.execute(
            select(VoiceCall).where(VoiceCall.twilio_call_sid == call_sid)
        )).scalar_one_or_none()
        if call:
            call.duracion_seg = duration
            if status == "completed":
                call.estado = "completed"
                call.fin = datetime.utcnow()
                # Cálculo de costo: $0.014/min Twilio + ~$0.05/min ElevenLabs + STT + Claude
                # = ~$0.10/min como estimado conservador
                call.costo_usd = round((duration / 60.0) * 0.10, 4)
            elif status in ("failed", "busy", "no-answer", "canceled"):
                call.estado = "failed"
                call.outcome = "no_answer" if status == "no-answer" else "failed"
                call.fin = datetime.utcnow()
            await session.commit()

    return {"status": "ok"}


# ════════════════════════════════════════════════════════════
# WEBSOCKET — Media Streams bidireccional (audio in/out)
# ════════════════════════════════════════════════════════════

@router.websocket("/twilio/stream/{call_id}")
async def twilio_stream(websocket: WebSocket, call_id: int):
    """Media Streams: Twilio nos envía audio del prospecto en vivo, y nosotros
    le mandamos respuesta de Claude (vía TTS) de vuelta.

    Día 1: skeleton WebSocket que solo registra el inicio y cierra.
    Día 2+: integración Deepgram STT + Claude + ElevenLabs TTS streaming.
    """
    await websocket.accept()
    logger.info(f"[voice WS] Stream abierto para call_id={call_id}")

    try:
        # Loop principal: recibe frames de Twilio (base64 audio + eventos)
        while True:
            msg = await websocket.receive_text()
            # Día 2+: procesar audio y responder
            # Por ahora solo logueamos eventos para debug
            if '"event":"start"' in msg:
                logger.info(f"[voice WS] Stream START call_id={call_id}")
            elif '"event":"stop"' in msg:
                logger.info(f"[voice WS] Stream STOP call_id={call_id}")
                break
    except WebSocketDisconnect:
        logger.info(f"[voice WS] Disconnect call_id={call_id}")
    except Exception as e:
        logger.error(f"[voice WS] Error: {e}", exc_info=True)
    finally:
        try:
            await websocket.close()
        except Exception:
            pass


# ════════════════════════════════════════════════════════════
# MÉTRICAS — JSON con números agregados
# ════════════════════════════════════════════════════════════

@router.get("/metricas")
async def get_metricas(clinica_id: Optional[int] = None):
    """Resumen agregado: cola, llamadas hoy, outcomes, costo del mes."""
    return await metricas_voice(clinica_id=clinica_id)


# ════════════════════════════════════════════════════════════
# OPT-OUT — Registrar manualmente que un número NO debe ser llamado
# ════════════════════════════════════════════════════════════

class OptOutRequest(BaseModel):
    telefono: str = Field(..., min_length=7, max_length=50)
    motivo: str = Field(default="", max_length=300)


@router.post("/optout")
async def post_optout(req: OptOutRequest):
    """Agrega un número a la lista negra. NUNCA será llamado de nuevo."""
    ok = await registrar_optout(req.telefono, req.motivo, origen="manual")
    if not ok:
        raise HTTPException(status_code=400, detail="Teléfono inválido")
    return {"status": "ok", "telefono": req.telefono}


@router.get("/optout/check/{telefono}")
async def check_optout(telefono: str):
    """Consulta si un número está en la lista negra."""
    en_optout = await telefono_en_optout(telefono)
    return {"telefono": telefono, "en_optout": en_optout}


# ════════════════════════════════════════════════════════════
# ENCOLAR PROSPECTOS DESDE CSV (admin only)
# ════════════════════════════════════════════════════════════

@router.post("/encolar/prospectos")
async def encolar_prospectos_csv(
    csv_path: str = Form("D:/CLAUDE/LAPORA/outreach/prospectos_200_reales.csv"),
    solo_verificados: bool = Form(True),
    solo_ibague: bool = Form(True),
    prioridad_default: int = Form(50),
):
    """Carga prospectos del CSV a la cola. Para uso desde admin.

    Args:
        csv_path: Ruta absoluta al CSV de prospectos
        solo_verificados: Si True, solo los que tienen email_verificado='SI'
        solo_ibague: Si True, solo los que tienen 'Ibague' en dirección
        prioridad_default: Prioridad para los nuevos (0-100). muy_alta sube +20, alta +10.
    """
    import csv as _csv

    if not os.path.exists(csv_path):
        raise HTTPException(status_code=404, detail=f"CSV no encontrado: {csv_path}")

    encolados = 0
    saltados_optout = 0
    saltados_duplicados = 0
    saltados_sin_tel = 0

    with open(csv_path, "r", encoding="utf-8-sig") as f:
        reader = _csv.DictReader(f)
        for row in reader:
            if solo_verificados and row.get("email_verificado", "").upper() != "SI":
                continue
            telefono = (row.get("telefono", "") or "").strip()
            if not telefono or len(telefono.replace("+", "")) < 7:
                saltados_sin_tel += 1
                continue
            direccion = (row.get("direccion", "") or "").lower()
            if solo_ibague and "ibague" not in direccion and "ibagué" not in direccion:
                continue

            # Prioridad según campo del CSV
            prio_csv = (row.get("prioridad", "") or "").lower()
            prioridad = prioridad_default
            if prio_csv == "muy_alta":
                prioridad = min(100, prioridad_default + 30)
            elif prio_csv == "alta":
                prioridad = min(100, prioridad_default + 15)
            elif prio_csv == "media":
                prioridad = prioridad_default
            elif prio_csv == "baja":
                prioridad = max(0, prioridad_default - 20)

            entry = await encolar_prospecto(
                target_type="prospect",
                target_id=row.get("id", ""),
                target_nombre=row.get("nombre_negocio", "") or row.get("nombre_doctor", ""),
                telefono=telefono,
                script_id="outreach_medicos",
                prioridad=prioridad,
                intentos_max=3,
            )
            if entry is None:
                saltados_optout += 1
            else:
                # Si ya existía no se duplica (encolar_prospecto retorna el existente)
                if entry.creada_en < datetime.utcnow().replace(hour=0, minute=0, second=0):
                    saltados_duplicados += 1
                else:
                    encolados += 1

    return {
        "status": "ok",
        "encolados_nuevos": encolados,
        "saltados_optout": saltados_optout,
        "saltados_duplicados": saltados_duplicados,
        "saltados_sin_tel": saltados_sin_tel,
        "total_procesados": encolados + saltados_optout + saltados_duplicados + saltados_sin_tel,
    }
