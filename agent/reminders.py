# -*- coding: utf-8 -*-
# agent/reminders.py — Sistema de recordatorios automaticos por WhatsApp
# Generado por AgentKit

"""
Sistema de recordatorios para citas agendadas.

Cuando SofIA agenda una cita, se programa automaticamente un recordatorio
que se envia 1 hora antes por WhatsApp al cliente.

Flujo:
1. SofIA agenda cita -> programar_recordatorio() guarda en BD
2. Scheduler corre cada 5 minutos
3. Busca recordatorios pendientes cuyo enviar_en sea menor o igual a ahora
4. Envia mensaje por WhatsApp y marca como enviado
"""

import logging
import asyncio
from datetime import datetime, timedelta
from sqlalchemy import select, update

from agent.memory import async_session, Recordatorio
from agent.providers import obtener_proveedor

logger = logging.getLogger("agentkit.reminders")

# Configuracion del scheduler
INTERVALO_REVISION_SEGUNDOS = 300  # 5 minutos
ANTICIPACION_HORAS = 1  # Enviar recordatorio 1 hora antes


async def programar_recordatorio(
    telefono: str,
    nombre_doctor: str,
    evento_id: str,
    fecha_cita: datetime,
) -> bool:
    """
    Guarda un recordatorio en la base de datos para ser enviado
    1 hora antes de la cita.

    Args:
        telefono: Numero de WhatsApp del cliente
        nombre_doctor: Nombre del doctor agendado
        evento_id: ID del evento en Google Calendar
        fecha_cita: Datetime de la cita

    Returns:
        True si se programo correctamente
    """
    try:
        # Calcular cuando enviar el recordatorio (1 hora antes)
        # IMPORTANTE: convertir a naive datetime UTC para almacenamiento
        if fecha_cita.tzinfo is not None:
            # Convertir a UTC y quitar tz info
            fecha_cita_utc = fecha_cita.astimezone(tz=None).replace(tzinfo=None)
        else:
            fecha_cita_utc = fecha_cita

        # Usar datetime.utcnow() para consistencia con el scheduler
        from datetime import timezone
        if fecha_cita.tzinfo is not None:
            fecha_cita_utc = fecha_cita.astimezone(timezone.utc).replace(tzinfo=None)

        enviar_en = fecha_cita_utc - timedelta(hours=ANTICIPACION_HORAS)

        async with async_session() as session:
            recordatorio = Recordatorio(
                telefono=telefono,
                nombre_doctor=nombre_doctor,
                evento_id=evento_id,
                fecha_cita=fecha_cita_utc,
                enviar_en=enviar_en,
                enviado=0,
                creado_en=datetime.utcnow(),
            )
            session.add(recordatorio)
            await session.commit()

            logger.info(
                f"Recordatorio programado para {telefono} - "
                f"Cita: {fecha_cita_utc.isoformat()} - "
                f"Enviar en: {enviar_en.isoformat()}"
            )
            return True

    except Exception as e:
        logger.error(f"Error programando recordatorio: {e}", exc_info=True)
        return False


def _construir_mensaje_recordatorio(nombre_doctor: str, fecha_cita: datetime) -> str:
    """Construye el mensaje de recordatorio que se enviara por WhatsApp."""
    # Formatear hora en formato 12h colombia
    hora_str = fecha_cita.strftime("%I:%M %p").lstrip("0")

    mensaje = (
        f"Hola {nombre_doctor}, te escribe SofIA de Lapora.\n\n"
        f"Te recuerdo que tienes una llamada agendada con nuestro equipo "
        f"en *1 hora*, a las *{hora_str}* (hora Colombia).\n\n"
        f"Solo confirmame con un OK si seguimos a la hora.\n\n"
        f"Si necesitas reagendar, escribeme aqui mismo y te ayudo en el momento."
    )
    return mensaje


async def enviar_recordatorios_pendientes():
    """
    Revisa la base de datos por recordatorios pendientes y los envia.
    Se ejecuta cada INTERVALO_REVISION_SEGUNDOS por el scheduler.
    """
    try:
        ahora = datetime.utcnow()

        async with async_session() as session:
            # Buscar recordatorios pendientes que ya deban enviarse
            query = (
                select(Recordatorio)
                .where(Recordatorio.enviado == 0)
                .where(Recordatorio.enviar_en <= ahora)
                .where(Recordatorio.fecha_cita > ahora)  # No enviar si ya paso la cita
            )
            result = await session.execute(query)
            pendientes = result.scalars().all()

            if not pendientes:
                return

            logger.info(f"Procesando {len(pendientes)} recordatorios pendientes")

            proveedor = obtener_proveedor()

            for recordatorio in pendientes:
                try:
                    mensaje = _construir_mensaje_recordatorio(
                        recordatorio.nombre_doctor,
                        recordatorio.fecha_cita,
                    )

                    exito = await proveedor.enviar_mensaje(
                        recordatorio.telefono,
                        mensaje,
                    )

                    if exito:
                        recordatorio.enviado = 1
                        logger.info(
                            f"Recordatorio enviado a {recordatorio.telefono} "
                            f"para cita con {recordatorio.nombre_doctor}"
                        )
                    else:
                        recordatorio.enviado = -1
                        logger.error(
                            f"Error enviando recordatorio a {recordatorio.telefono}"
                        )

                except Exception as e:
                    logger.error(
                        f"Error procesando recordatorio {recordatorio.id}: {e}",
                        exc_info=True,
                    )
                    recordatorio.enviado = -1

            await session.commit()

    except Exception as e:
        logger.error(f"Error en enviar_recordatorios_pendientes: {e}", exc_info=True)


async def scheduler_loop():
    """
    Loop infinito que ejecuta el scheduler de recordatorios.
    Se inicia en main.py con el lifespan de FastAPI.
    """
    logger.info(
        f"Scheduler de recordatorios iniciado "
        f"(intervalo: {INTERVALO_REVISION_SEGUNDOS}s, "
        f"anticipacion: {ANTICIPACION_HORAS}h)"
    )

    while True:
        try:
            await enviar_recordatorios_pendientes()
        except Exception as e:
            logger.error(f"Error en scheduler_loop: {e}", exc_info=True)

        await asyncio.sleep(INTERVALO_REVISION_SEGUNDOS)


async def listar_recordatorios_pendientes() -> list[dict]:
    """Lista todos los recordatorios pendientes (para debug/dashboard)."""
    async with async_session() as session:
        query = (
            select(Recordatorio)
            .where(Recordatorio.enviado == 0)
            .order_by(Recordatorio.enviar_en.asc())
        )
        result = await session.execute(query)
        recordatorios = result.scalars().all()

        return [
            {
                "id": r.id,
                "telefono": r.telefono,
                "doctor": r.nombre_doctor,
                "fecha_cita": r.fecha_cita.isoformat(),
                "enviar_en": r.enviar_en.isoformat(),
            }
            for r in recordatorios
        ]
