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
from fastapi.responses import Response, JSONResponse, PlainTextResponse, HTMLResponse, RedirectResponse
import html as _html
from pydantic import BaseModel, Field
from sqlalchemy import select, desc

from agent.memory import async_session
from agent.voice_models import (
    VoiceCall, VoiceQueue, VoiceTranscript, VoiceOptOut,
    telefono_en_optout, registrar_optout, encolar_prospecto, metricas_voice,
    obtener_config_voice, esta_pausado, pausar_scheduler, reanudar_scheduler,
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

    call_id_para_post = None
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
                call_id_para_post = call.id
            elif status in ("failed", "busy", "no-answer", "canceled"):
                call.estado = "failed"
                call.outcome = "no_answer" if status == "no-answer" else "failed"
                call.fin = datetime.utcnow()
                call_id_para_post = call.id
            await session.commit()

    # Disparar post-call analysis en background (no bloqueamos ACK a Twilio)
    if call_id_para_post is not None:
        import asyncio
        asyncio.create_task(_post_call_background(call_id_para_post))

    return {"status": "ok"}


async def _post_call_background(call_id: int):
    """Wrapper que dispara procesar_post_call sin bloquear el webhook."""
    try:
        from agent.voice_outcomes import procesar_post_call
        resultado = await procesar_post_call(call_id)
        logger.info(
            f"[voice] post-call call_id={call_id} outcome={resultado.get('outcome')} "
            f"wa_prosp={resultado.get('whatsapp_prospecto_enviado')} "
            f"notif_michael={resultado.get('notif_michael_enviada')}"
        )
    except Exception as e:
        logger.error(f"[voice] post-call error call={call_id}: {e}", exc_info=True)


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

# ════════════════════════════════════════════════════════════
# PAUSE / RESUME — Control manual del scheduler
# ════════════════════════════════════════════════════════════

@router.post("/scheduler/pausar")
async def post_pausar(motivo: str = Form(""), por: str = Form("admin")):
    """Pausa el scheduler. Llamadas en curso terminan, pero NO se inician nuevas."""
    await pausar_scheduler(motivo=motivo, por=por)
    return RedirectResponse(url="/voice/dashboard?pausado=1", status_code=303)


@router.post("/scheduler/reanudar")
async def post_reanudar():
    """Reanuda el scheduler."""
    await reanudar_scheduler()
    return RedirectResponse(url="/voice/dashboard?reanudado=1", status_code=303)


# ════════════════════════════════════════════════════════════
# LLAMAR AHORA — Override manual para una entry específica
# ════════════════════════════════════════════════════════════

@router.post("/llamar-ahora/{queue_id}")
async def llamar_ahora(queue_id: int):
    """Dispara INMEDIATAMENTE la llamada para esta entry de cola.

    BYPASS: ignora horario hábil + throttle (override admin).
    NO bypassa opt-out (eso es legal, no se puede saltar).
    """
    async with async_session() as session:
        entry = (await session.execute(
            select(VoiceQueue).where(VoiceQueue.id == queue_id)
        )).scalar_one_or_none()
        if not entry:
            raise HTTPException(status_code=404, detail="Entry no encontrada")
        if entry.estado != "queued":
            return JSONResponse(
                status_code=400,
                content={"error": f"Entry no está en cola (estado={entry.estado})"},
            )

    # Opt-out check (no se puede bypass)
    if await telefono_en_optout(entry.telefono):
        return JSONResponse(
            status_code=403,
            content={"error": "Teléfono en opt-out — no se puede llamar"},
        )

    # Disparar
    from agent.voice_workers import disparar_llamada
    call = await disparar_llamada(entry, worker_id="manual_admin")
    if call is None:
        return JSONResponse(status_code=500, content={"error": "No se pudo disparar la llamada"})

    return RedirectResponse(url="/voice/dashboard?disparado=1", status_code=303)


@router.get("/dashboard", response_class=HTMLResponse)
async def voice_dashboard(
    pausado: Optional[str] = None,
    reanudado: Optional[str] = None,
    disparado: Optional[str] = None,
):
    """UI admin para gestionar el Voice Bot — visible en /voice/dashboard.

    Muestra:
    - Stats top: cola, llamadas hoy, costo mes, outcomes
    - Tabla cola próximas llamadas
    - Tabla últimas 20 llamadas con transcripts expandibles
    - Botón pausar/reanudar (Día 7+ feature)
    """
    # Datos
    metrics = await metricas_voice()
    cfg = await obtener_config_voice()
    pausado_actual = bool(cfg.scheduler_pausado)
    async with async_session() as session:
        # Próximas en cola (15 max)
        cola_result = await session.execute(
            select(VoiceQueue)
            .where(VoiceQueue.estado == "queued")
            .order_by(VoiceQueue.programada_para)
            .limit(15)
        )
        cola = list(cola_result.scalars().all())

        # Últimas 20 llamadas
        calls_result = await session.execute(
            select(VoiceCall).order_by(desc(VoiceCall.creada_en)).limit(20)
        )
        calls = list(calls_result.scalars().all())

        # Opt-outs recientes
        from agent.voice_models import VoiceOptOut
        optouts_result = await session.execute(
            select(VoiceOptOut).order_by(desc(VoiceOptOut.fecha)).limit(10)
        )
        optouts = list(optouts_result.scalars().all())

    def esc(s):
        return _html.escape(str(s or ""), quote=True)

    # Stats top
    outcomes_7d = metrics.get("outcomes_7d", {})
    interested = outcomes_7d.get("interested", 0)
    callback = outcomes_7d.get("callback", 0)
    not_interested = outcomes_7d.get("not_interested", 0)
    opt_out_count = outcomes_7d.get("opt_out", 0)
    voicemail = outcomes_7d.get("voicemail", 0)
    no_answer = outcomes_7d.get("no_answer", 0)
    total_contactados = sum(outcomes_7d.values())
    tasa_conv = round((interested + callback) / total_contactados * 100, 1) if total_contactados else 0

    # Filas cola
    filas_cola = ""
    if not cola:
        filas_cola = '<tr><td colspan="6" style="text-align:center;padding:24px;color:#9CA3AF;">Cola vacía — no hay llamadas programadas</td></tr>'
    for q in cola:
        prog = q.programada_para.strftime("%d/%m %H:%M") if q.programada_para else "-"
        tipo_color = "#3B82F6" if q.target_type == "prospect" else "#10B981"
        filas_cola += f"""
        <tr>
            <td><strong>{esc(q.target_nombre[:40])}</strong></td>
            <td style="font-family:monospace;font-size:12px;">{esc(q.telefono)}</td>
            <td><span style="background:{tipo_color}22;color:{tipo_color};padding:2px 8px;border-radius:10px;font-size:11px;font-weight:700;text-transform:uppercase;">{esc(q.target_type)}</span></td>
            <td style="font-size:12px;color:#6B7280;">{prog}</td>
            <td style="font-weight:700;color:#FF3B30;">{q.prioridad}</td>
            <td><form method="post" action="/voice/llamar-ahora/{q.id}" style="margin:0;" onsubmit="return confirm('¿Llamar AHORA a {esc(q.target_nombre[:30])} ({esc(q.telefono)})? Salta horario y throttle.');">
                <button type="submit" style="background:#10B981;color:white;border:none;padding:5px 10px;border-radius:6px;font-size:11px;font-weight:700;cursor:pointer;">📞 Llamar ya</button>
            </form></td>
        </tr>"""

    # Filas históricas
    filas_calls = ""
    if not calls:
        filas_calls = '<tr><td colspan="6" style="text-align:center;padding:24px;color:#9CA3AF;">Sin llamadas registradas todavía</td></tr>'
    OUTCOME_COLORS = {
        "interested": "#10B981", "callback": "#3B82F6",
        "not_interested": "#9CA3AF", "voicemail": "#F59E0B",
        "no_answer": "#FCA5A5", "opt_out": "#7C2D12",
        "failed": "#EF4444",
    }
    for c in calls:
        when = c.creada_en.strftime("%d/%m %H:%M") if c.creada_en else "-"
        outcome = c.outcome or "—"
        oc_color = OUTCOME_COLORS.get(outcome, "#6B7280")
        dur = f"{c.duracion_seg}s" if c.duracion_seg else "-"
        costo = f"${c.costo_usd:.3f}" if c.costo_usd else "-"
        resumen_corto = esc((c.resumen_ia or "")[:120])
        if len(c.resumen_ia or "") > 120:
            resumen_corto += "..."
        filas_calls += f"""
        <tr>
            <td style="font-size:12px;color:#6B7280;">{when}</td>
            <td><strong>{esc(c.target_nombre[:30])}</strong><br><span style="font-family:monospace;font-size:11px;color:#9CA3AF;">{esc(c.telefono)}</span></td>
            <td><span style="background:{oc_color}22;color:{oc_color};padding:3px 10px;border-radius:10px;font-size:11px;font-weight:700;text-transform:uppercase;">{esc(outcome)}</span></td>
            <td style="font-size:12px;color:#6B7280;">{dur}</td>
            <td style="font-family:monospace;font-size:12px;color:#10B981;font-weight:700;">{costo}</td>
            <td style="font-size:12px;color:#374151;line-height:1.4;max-width:340px;">{resumen_corto}</td>
        </tr>"""

    # Filas opt-outs
    filas_opt = ""
    if not optouts:
        filas_opt = '<tr><td colspan="3" style="text-align:center;padding:12px;color:#9CA3AF;font-size:12px;">Sin opt-outs</td></tr>'
    for o in optouts:
        fecha = o.fecha.strftime("%d/%m %H:%M") if o.fecha else "-"
        filas_opt += f"""
        <tr>
            <td style="font-family:monospace;font-size:12px;">{esc(o.telefono)}</td>
            <td style="font-size:12px;">{esc(o.motivo[:60])}</td>
            <td style="font-size:12px;color:#6B7280;">{fecha}</td>
        </tr>"""

    # Banner de feedback de acciones
    banner = ""
    if pausado == "1":
        banner = '<div style="background:#FEF3C7;border:1px solid #FCD34D;color:#92400E;padding:12px 16px;border-radius:10px;margin-bottom:16px;font-weight:600;">⏸ Scheduler pausado — no se iniciarán llamadas nuevas hasta que reanudes.</div>'
    elif reanudado == "1":
        banner = '<div style="background:#D1FAE5;border:1px solid #10B981;color:#065F46;padding:12px 16px;border-radius:10px;margin-bottom:16px;font-weight:600;">✓ Scheduler reanudado — volverá a llamar en la próxima ventana hábil.</div>'
    elif disparado == "1":
        banner = '<div style="background:#DBEAFE;border:1px solid #3B82F6;color:#1E40AF;padding:12px 16px;border-radius:10px;margin-bottom:16px;font-weight:600;">📞 Llamada disparada — revisa el histórico en unos segundos.</div>'

    # Botón pause / resume
    if pausado_actual:
        boton_estado = f'''
        <form method="post" action="/voice/scheduler/reanudar" style="display:inline;">
            <button type="submit" style="background:#10B981;color:white;border:none;padding:10px 20px;border-radius:8px;font-size:14px;font-weight:700;cursor:pointer;">▶ Reanudar scheduler</button>
        </form>'''
        estado_visual = f'<span style="background:#FEF3C7;color:#92400E;padding:6px 14px;border-radius:8px;font-size:12px;font-weight:700;text-transform:uppercase;letter-spacing:0.05em;">⏸ Pausado</span>'
        if cfg.motivo_pausa:
            estado_visual += f' <span style="font-size:12px;color:#6B7280;margin-left:8px;">({esc(cfg.motivo_pausa[:60])})</span>'
    else:
        boton_estado = '''
        <form method="post" action="/voice/scheduler/pausar" style="display:inline;" onsubmit="return confirm('¿Pausar scheduler? Las llamadas en curso terminan, pero no se iniciarán nuevas.');">
            <input type="hidden" name="motivo" value="Pausa manual desde dashboard">
            <button type="submit" style="background:#F59E0B;color:white;border:none;padding:10px 20px;border-radius:8px;font-size:14px;font-weight:700;cursor:pointer;">⏸ Pausar scheduler</button>
        </form>'''
        estado_visual = '<span style="background:#D1FAE5;color:#065F46;padding:6px 14px;border-radius:8px;font-size:12px;font-weight:700;text-transform:uppercase;letter-spacing:0.05em;">● Activo</span>'

    return HTMLResponse(f"""<!DOCTYPE html><html lang="es"><head>
<meta charset="UTF-8"><title>SofIA Llama — Dashboard</title>
<style>
*,*::before,*::after{{margin:0;padding:0;box-sizing:border-box}}
body{{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;background:#F9FAFB;color:#111827;line-height:1.5;padding:24px;max-width:1400px;margin:0 auto;}}
h1{{font-size:26px;font-weight:800;margin-bottom:6px}}
.subtitle{{color:#6B7280;margin-bottom:24px;font-size:14px}}
.nav-back{{display:inline-block;margin-bottom:20px;color:#6B7280;text-decoration:none;font-size:13px}}
.nav-back:hover{{color:#FF3B30}}
.stats{{display:grid;grid-template-columns:repeat(auto-fit,minmax(160px,1fr));gap:14px;margin-bottom:30px}}
.stat{{background:white;border:1px solid #E5E7EB;border-radius:12px;padding:18px}}
.stat .label{{font-size:11px;color:#6B7280;text-transform:uppercase;letter-spacing:0.05em;font-weight:700;margin-bottom:6px}}
.stat .value{{font-size:28px;font-weight:800;color:#111827}}
.stat .sub{{font-size:11px;color:#9CA3AF;margin-top:4px}}
.stat.green .value{{color:#10B981}}
.stat.blue .value{{color:#3B82F6}}
.stat.red .value{{color:#FF3B30}}
.stat.amber .value{{color:#F59E0B}}
.card{{background:white;border:1px solid #E5E7EB;border-radius:12px;overflow:hidden;margin-bottom:24px}}
.card-header{{padding:14px 18px;border-bottom:1px solid #E5E7EB;display:flex;justify-content:space-between;align-items:center}}
.card-header h2{{font-size:15px;font-weight:700}}
table{{width:100%;border-collapse:collapse}}
th{{text-align:left;padding:10px 14px;font-size:11px;font-weight:700;color:#6B7280;text-transform:uppercase;letter-spacing:0.05em;background:#F9FAFB;border-bottom:1px solid #E5E7EB}}
td{{padding:10px 14px;font-size:13px;border-bottom:1px solid #F3F4F6}}
tr:last-child td{{border-bottom:none}}
.grid-2{{display:grid;grid-template-columns:2fr 1fr;gap:20px;margin-bottom:24px}}
@media (max-width:900px){{.grid-2{{grid-template-columns:1fr}}}}
.badge-conv{{display:inline-block;background:linear-gradient(135deg,#10B981,#059669);color:white;padding:6px 14px;border-radius:8px;font-size:13px;font-weight:700}}
</style></head><body>

<a href="/admin/conversaciones" class="nav-back">← Volver al CRM</a>
<div style="display:flex;justify-content:space-between;align-items:start;gap:20px;margin-bottom:6px;flex-wrap:wrap;">
    <div>
        <h1>📞 SofIA Llama — Dashboard</h1>
        <p class="subtitle">Calling bot con Twilio + Claude + ElevenLabs · {esc(datetime.utcnow().strftime("%d/%m/%Y %H:%M UTC"))}</p>
        <div style="margin-top:8px;">Estado scheduler: {estado_visual}</div>
    </div>
    <div>{boton_estado}</div>
</div>
{banner}

<div class="stats">
    <div class="stat blue"><div class="label">📋 En cola</div><div class="value">{metrics['en_cola']}</div><div class="sub">Esperando llamada</div></div>
    <div class="stat"><div class="label">📞 Hoy</div><div class="value">{metrics['llamadas_hoy']}</div><div class="sub">Llamadas hechas</div></div>
    <div class="stat green"><div class="label">✅ Calificados 7d</div><div class="value">{interested + callback}</div><div class="sub">Interested + callback</div></div>
    <div class="stat amber"><div class="label">📈 Conversión</div><div class="value">{tasa_conv}%</div><div class="sub">{interested + callback} de {total_contactados} contactados</div></div>
    <div class="stat red"><div class="label">💰 Costo mes</div><div class="value">${metrics['costo_mes_usd']}</div><div class="sub">USD acumulado</div></div>
</div>

<div class="grid-2">
    <div class="card">
        <div class="card-header"><h2>🕒 Cola — próximas llamadas</h2><span style="font-size:12px;color:#6B7280;">{len(cola)} próximas</span></div>
        <table>
            <thead><tr><th>Target</th><th>Teléfono</th><th>Tipo</th><th>Programada</th><th>Prio</th><th>Acción</th></tr></thead>
            <tbody>{filas_cola}</tbody>
        </table>
    </div>
    <div class="card">
        <div class="card-header"><h2>🚫 Opt-outs recientes</h2><span style="font-size:12px;color:#6B7280;">No volver a llamar</span></div>
        <table>
            <thead><tr><th>Teléfono</th><th>Motivo</th><th>Fecha</th></tr></thead>
            <tbody>{filas_opt}</tbody>
        </table>
    </div>
</div>

<div class="card">
    <div class="card-header"><h2>📜 Últimas 20 llamadas</h2><span class="badge-conv">Conversión: {tasa_conv}%</span></div>
    <table>
        <thead><tr><th>Cuándo</th><th>Target</th><th>Outcome</th><th>Duración</th><th>Costo</th><th>Resumen IA</th></tr></thead>
        <tbody>{filas_calls}</tbody>
    </table>
</div>

<div style="background:white;border:1px solid #E5E7EB;border-radius:12px;padding:18px;font-size:13px;color:#6B7280;line-height:1.6;">
    <strong style="color:#111827;">Outcomes 7d:</strong>
    ✅ Interested: <strong style="color:#10B981;">{interested}</strong> ·
    📞 Callback: <strong style="color:#3B82F6;">{callback}</strong> ·
    ❌ Not interested: <strong style="color:#9CA3AF;">{not_interested}</strong> ·
    🚫 Opt-out: <strong style="color:#7C2D12;">{opt_out_count}</strong> ·
    📨 Voicemail: <strong style="color:#F59E0B;">{voicemail}</strong> ·
    ⏸ No answer: <strong style="color:#FCA5A5;">{no_answer}</strong>
</div>

</body></html>""")


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
