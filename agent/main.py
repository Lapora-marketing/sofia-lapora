# agent/main.py — Servidor FastAPI + Webhook de WhatsApp
# Generado por AgentKit

"""
Servidor principal del agente SofIA de Lapora.
Funciona con cualquier proveedor (Meta, Twilio) gracias a la capa de providers.
"""

import os
import asyncio
import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import PlainTextResponse
from dotenv import load_dotenv

from agent.brain import generar_respuesta
from agent.memory import inicializar_db, guardar_mensaje, obtener_historial, upsert_contacto
from agent.providers import obtener_proveedor
from agent.dashboard import router as dashboard_router
from agent.clinic import router as clinic_router
from agent.lapora_bot import router as lapora_bot_router
from agent.voice_bot import router as voice_bot_router
from agent.reminders import scheduler_loop
from fastapi.middleware.cors import CORSMiddleware

load_dotenv(override=True)

# Configuracion de logging segun entorno
ENVIRONMENT = os.getenv("ENVIRONMENT", "development")
log_level = logging.DEBUG if ENVIRONMENT == "development" else logging.INFO
logging.basicConfig(
    level=log_level,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("agentkit")

# Proveedor de WhatsApp (se configura en .env con WHATSAPP_PROVIDER)
proveedor = obtener_proveedor()
PORT = int(os.getenv("PORT", 8000))


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Inicializa la base de datos y el scheduler al arrancar el servidor."""
    await inicializar_db()
    # Aplicar migraciones de Lapora Clinic (columnas nuevas en tablas existentes)
    try:
        from agent.clinic_models import aplicar_migraciones
        await aplicar_migraciones()
    except Exception as e:
        logger.warning(f"Migraciones fallaron (no crítico): {e}")

    # Iniciar el scheduler de recordatorios de SofIA (CRM Lapora) en background
    scheduler_task = asyncio.create_task(scheduler_loop())

    # Iniciar workers de Lapora Clinic (recordatorios per-tenant)
    workers_clinic_iniciados = False
    try:
        from agent.clinic_workers import iniciar_workers as iniciar_workers_clinic
        await iniciar_workers_clinic()
        workers_clinic_iniciados = True
    except Exception as e:
        logger.warning(f"Workers Clinic no se pudieron iniciar (no crítico): {e}")

    # Iniciar Voice Bot scheduler (calling automatizado)
    voice_workers_iniciados = False
    try:
        from agent.voice_workers import iniciar_voice_workers
        await iniciar_voice_workers()
        voice_workers_iniciados = True
    except Exception as e:
        logger.warning(f"Voice workers no se pudieron iniciar (no crítico): {e}")

    logger.info("=" * 60)
    logger.info("  SofIA — Agente de Lapora arrancando...")
    logger.info("=" * 60)
    logger.info(f"  Base de datos: inicializada")
    logger.info(f"  Puerto: {PORT}")
    logger.info(f"  Proveedor WhatsApp: {proveedor.__class__.__name__}")
    logger.info(f"  Entorno: {ENVIRONMENT}")
    logger.info(f"  Scheduler SofIA CRM: ACTIVO (revisa cada 5 min)")
    logger.info(f"  Workers Lapora Clinic: {'ACTIVOS' if workers_clinic_iniciados else 'OFF'}")
    logger.info(f"  Voice Bot scheduler: {'ACTIVO (Lun-Vie 9-12+14-17 CO)' if voice_workers_iniciados else 'OFF'}")
    logger.info("=" * 60)
    yield

    # Apagar el scheduler SofIA limpiamente
    scheduler_task.cancel()
    try:
        await scheduler_task
    except asyncio.CancelledError:
        pass

    # Apagar workers Clinic limpiamente
    if workers_clinic_iniciados:
        try:
            from agent.clinic_workers import detener_workers as detener_workers_clinic
            await detener_workers_clinic()
        except Exception as e:
            logger.warning(f"Error deteniendo workers Clinic: {e}")

    # Apagar Voice workers limpiamente
    if voice_workers_iniciados:
        try:
            from agent.voice_workers import detener_voice_workers
            await detener_voice_workers()
        except Exception as e:
            logger.warning(f"Error deteniendo voice workers: {e}")

    logger.info("SofIA: servidor apagandose.")


app = FastAPI(
    title="SofIA — Agente IA de Lapora",
    description="Asistente virtual de WhatsApp para Lapora (marketing digital salud)",
    version="1.0.0",
    lifespan=lifespan,
)

# CORS para Lapora Bot — permite que el widget en lapora.studio llame al backend
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "https://lapora.studio",
        "https://www.lapora.studio",
        "https://sofia-lapora-production.up.railway.app",
        "http://localhost:3000",
        "http://localhost:8000",
        "http://127.0.0.1:8000",
    ],
    allow_credentials=False,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["Content-Type", "Authorization"],
    max_age=3600,
)

# Dashboard administrativo en /admin/conversaciones
app.include_router(dashboard_router)
# Lapora Clinic SaaS en /clinic/
app.include_router(clinic_router)
# Lapora Bot widget API en /lapora-bot/chat
app.include_router(lapora_bot_router)
# Lapora Voice Bot (calling) en /voice/
app.include_router(voice_bot_router)


@app.get("/")
async def health_check():
    """Endpoint de salud para Railway/monitoreo."""
    return {
        "status": "ok",
        "service": "sofia-lapora",
        "agente": "SofIA",
        "empresa": "Lapora",
    }


@app.get("/webhook")
async def webhook_verificacion(request: Request):
    """Verificacion GET del webhook (requerido por Meta Cloud API, no-op para Twilio)."""
    resultado = await proveedor.validar_webhook(request)
    if resultado is not None:
        return PlainTextResponse(str(resultado))
    return {"status": "ok"}


@app.post("/webhook")
async def webhook_handler(request: Request):
    """
    Recibe mensajes de WhatsApp via el proveedor configurado.
    Procesa el mensaje, genera respuesta con Claude y la envia de vuelta.
    """
    try:
        # Parsear webhook — el proveedor normaliza el formato
        mensajes = await proveedor.parsear_webhook(request)

        for msg in mensajes:
            # Ignorar mensajes propios o vacios
            if msg.es_propio or not msg.texto:
                continue

            logger.info(f"Mensaje de {msg.telefono}: {msg.texto}")

            # CRM: crear/actualizar contacto automaticamente
            await upsert_contacto(msg.telefono)

            # Obtener historial ANTES de guardar el mensaje actual
            # (brain.py agrega el mensaje actual, evitando duplicados)
            historial = await obtener_historial(msg.telefono)

            # Generar respuesta con Claude (con telefono para tools)
            respuesta = await generar_respuesta(msg.texto, historial, telefono_usuario=msg.telefono)

            # Guardar mensaje del usuario Y respuesta del agente en memoria
            await guardar_mensaje(msg.telefono, "user", msg.texto)
            await guardar_mensaje(msg.telefono, "assistant", respuesta)

            # Enviar respuesta por WhatsApp via el proveedor
            await proveedor.enviar_mensaje(msg.telefono, respuesta)

            logger.info(f"Respuesta a {msg.telefono}: {respuesta}")

        return {"status": "ok"}

    except Exception as e:
        logger.error(f"Error en webhook: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))
