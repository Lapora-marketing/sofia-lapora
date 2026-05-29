# -*- coding: utf-8 -*-
# agent/clinic_engagement.py — Mensajería automatizada de retención
# Lapora Marketing Digital — PHVA ciclo de mejora

"""
Features de retención y engagement automático:

1. Reseñas Google post-cita
   Worker que cada 30 min detecta citas completadas hace N horas (default 24h)
   y envía WhatsApp con link directo a Google Reviews. Marca review_msg_enviado
   para idempotencia.

2. Recordatorio cumpleaños
   Worker diario a las 9am Colombia que detecta pacientes que cumplen años HOY
   y envía WhatsApp template configurable. Idempotente vía cumple_mensaje_enviado_anio.

3. Helpers de inyección de variables en templates (nombre, clinica, fecha, etc.)
"""

import logging
from datetime import datetime, timedelta
from typing import Optional
from sqlalchemy import select, and_, or_, func

from agent.memory import async_session
from agent.clinic_models import Clinica, Paciente, CitaClinic
from agent.whatsapp_helper import enviar_mensaje_meta

logger = logging.getLogger("agentkit")


# ════════════════════════════════════════════════════════════
# TEMPLATES — Inyectar variables {nombre}, {clinica}, etc.
# ════════════════════════════════════════════════════════════

def inyectar_vars(template: str, variables: dict) -> str:
    """Reemplaza {variable} con su valor."""
    if not template:
        return ""
    out = template
    for k, v in variables.items():
        out = out.replace("{" + k + "}", str(v or ""))
    return out


TEMPLATE_REVIEW_DEFAULT = (
    "Hola {nombre}, gracias por visitarnos en {clinica}! 🌟\n\n"
    "¿Nos ayudás con una reseña en Google? Tu opinión nos ayuda muchísimo: {link}\n\n"
    "Te tomará 30 segundos. ¡Mil gracias!"
)

TEMPLATE_CUMPLE_DEFAULT = (
    "¡Hola {nombre}! 🎉🎂\n\n"
    "Hoy es tu cumpleaños y en {clinica} queremos saludarte. "
    "Te deseamos un día espectacular lleno de salud y alegría.\n\n"
    "¡Un abrazo del equipo!"
)


# ════════════════════════════════════════════════════════════
# H1: RESEÑAS GOOGLE POST-CITA
# ════════════════════════════════════════════════════════════

async def enviar_solicitudes_reseña() -> int:
    """Encuentra citas completadas hace N horas (según config de cada clínica)
    y manda WhatsApp pidiendo reseña Google.

    Idempotente: usa CitaClinic.review_msg_enviado para no duplicar.
    Returns: cantidad de mensajes enviados.
    """
    ahora = datetime.utcnow()
    enviados = 0

    async with async_session() as session:
        # Cargar todas las clínicas activas con google_review_url configurado
        clinicas = list((await session.execute(
            select(Clinica)
            .where(Clinica.activo == True)  # noqa: E712
            .where(Clinica.congelada == False)  # noqa: E712
            .where(Clinica.google_review_url != "")
            .where(Clinica.whatsapp_phone_id != "")
            .where(Clinica.whatsapp_token != "")
        )).scalars().all())

    for clinica in clinicas:
        horas = clinica.review_msg_horas_despues or 24
        # Ventana: la cita debe haber sido HACE entre N y N+1 horas (ventana 1h)
        ventana_inicio = ahora - timedelta(hours=horas + 1)
        ventana_fin = ahora - timedelta(hours=horas)

        async with async_session() as session:
            result = await session.execute(
                select(CitaClinic, Paciente)
                .join(Paciente, CitaClinic.paciente_id == Paciente.id)
                .where(CitaClinic.clinica_id == clinica.id)
                .where(CitaClinic.estado == "completada")
                .where(CitaClinic.fecha_hora >= ventana_inicio)
                .where(CitaClinic.fecha_hora <= ventana_fin)
                .where(CitaClinic.review_msg_enviado == False)  # noqa: E712
            )
            elegibles = list(result.all())

            for cita, paciente in elegibles:
                if not paciente.telefono or len(paciente.telefono.replace("+", "")) < 8:
                    continue

                # Construir mensaje
                template = clinica.review_msg_template or TEMPLATE_REVIEW_DEFAULT
                texto = inyectar_vars(template, {
                    "nombre": (paciente.nombre or "").split()[0] if paciente.nombre else "",
                    "clinica": clinica.nombre or "",
                    "link": clinica.google_review_url,
                })

                # Enviar
                resultado = await enviar_mensaje_meta(
                    phone_id=clinica.whatsapp_phone_id,
                    token=clinica.whatsapp_token,
                    telefono=paciente.telefono,
                    mensaje=texto,
                    contexto_log=f"clinica={clinica.id}/review-request",
                )

                if resultado["exito"]:
                    # Marcar como enviado (idempotencia)
                    cita.review_msg_enviado = True
                    enviados += 1

            if elegibles:
                await session.commit()

    if enviados:
        logger.info(f"[engagement] {enviados} solicitudes de reseña enviadas")
    return enviados


# ════════════════════════════════════════════════════════════
# H2: CUMPLEAÑOS
# ════════════════════════════════════════════════════════════

async def enviar_mensajes_cumple() -> int:
    """Envía WhatsApp a pacientes que cumplen años HOY (hora Colombia).

    Idempotente: usa cumple_mensaje_enviado_anio para no duplicar dentro del año.
    """
    try:
        import pytz
        ahora_co = datetime.now(pytz.timezone("America/Bogota"))
    except Exception:
        ahora_co = datetime.utcnow()
    hoy_mes = ahora_co.month
    hoy_dia = ahora_co.day
    anio_actual = ahora_co.year
    enviados = 0

    async with async_session() as session:
        # Clínicas con cumple_msg_activo=True y WhatsApp config
        clinicas = list((await session.execute(
            select(Clinica)
            .where(Clinica.activo == True)  # noqa: E712
            .where(Clinica.congelada == False)  # noqa: E712
            .where(Clinica.cumple_msg_activo == True)  # noqa: E712
            .where(Clinica.whatsapp_phone_id != "")
            .where(Clinica.whatsapp_token != "")
        )).scalars().all())

    for clinica in clinicas:
        async with async_session() as session:
            # SQLite + Postgres: extraer mes y día de fecha_nacimiento
            # Usamos func.strftime que funciona en SQLite + cast int en Postgres
            try:
                pacientes = list((await session.execute(
                    select(Paciente)
                    .where(Paciente.clinica_id == clinica.id)
                    .where(Paciente.fecha_nacimiento.isnot(None))
                    .where(Paciente.cumple_mensaje_enviado_anio != anio_actual)
                    .where(Paciente.estado.in_(["nuevo", "activo"]))
                )).scalars().all())
            except Exception as e:
                logger.warning(f"[engagement] query cumple falló clinica={clinica.id}: {e}")
                continue

            for p in pacientes:
                if not p.fecha_nacimiento:
                    continue
                if p.fecha_nacimiento.month != hoy_mes or p.fecha_nacimiento.day != hoy_dia:
                    continue
                if not p.telefono or len(p.telefono.replace("+", "")) < 8:
                    continue

                template = clinica.cumple_msg_template or TEMPLATE_CUMPLE_DEFAULT
                texto = inyectar_vars(template, {
                    "nombre": (p.nombre or "").split()[0] if p.nombre else "",
                    "clinica": clinica.nombre or "",
                })

                resultado = await enviar_mensaje_meta(
                    phone_id=clinica.whatsapp_phone_id,
                    token=clinica.whatsapp_token,
                    telefono=p.telefono,
                    mensaje=texto,
                    contexto_log=f"clinica={clinica.id}/cumple",
                )

                if resultado["exito"]:
                    p.cumple_mensaje_enviado_anio = anio_actual
                    enviados += 1

            if pacientes:
                await session.commit()

    if enviados:
        logger.info(f"[engagement] {enviados} mensajes de cumpleaños enviados")
    return enviados


# ════════════════════════════════════════════════════════════
# H5: PROGRAMA DE REFERIDOS
# ════════════════════════════════════════════════════════════

def generar_codigo_referido() -> str:
    """Genera código corto único tipo LAP-X4F2 para compartir."""
    import secrets
    import string
    chars = string.ascii_uppercase + string.digits
    sufijo = "".join(secrets.choice(chars) for _ in range(4))
    return f"LAP-{sufijo}"


async def asegurar_codigo_referido(paciente_id: int) -> str:
    """Devuelve el código de referido del paciente, generándolo si no tiene."""
    async with async_session() as session:
        p = (await session.execute(
            select(Paciente).where(Paciente.id == paciente_id)
        )).scalar_one_or_none()
        if not p:
            return ""
        if p.codigo_referido:
            return p.codigo_referido

        # Generar único (reintenta hasta 5 veces si colisión)
        for _ in range(5):
            codigo = generar_codigo_referido()
            existe = (await session.execute(
                select(Paciente.id).where(Paciente.codigo_referido == codigo)
            )).scalar_one_or_none()
            if not existe:
                p.codigo_referido = codigo
                await session.commit()
                return codigo
        return ""


async def top_referidores(clinica_id: int, limite: int = 10) -> list[dict]:
    """Lista pacientes con más referidos en la clínica."""
    async with async_session() as session:
        result = await session.execute(
            select(
                Paciente.referido_por_id,
                func.count(Paciente.id).label("n"),
            )
            .where(Paciente.clinica_id == clinica_id)
            .where(Paciente.referido_por_id.isnot(None))
            .group_by(Paciente.referido_por_id)
            .order_by(func.count(Paciente.id).desc())
            .limit(limite)
        )
        rows = result.all()

        # Cargar info del referidor
        salida = []
        for row in rows:
            referidor = (await session.execute(
                select(Paciente).where(Paciente.id == row[0])
            )).scalar_one_or_none()
            if referidor:
                salida.append({
                    "paciente": referidor,
                    "referidos": int(row[1]),
                    "valor_generado": referidor.valor_total or 0,
                })
    return salida
