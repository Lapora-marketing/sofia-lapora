# -*- coding: utf-8 -*-
# agent/clinic_analytics.py — Analytics avanzado para plan Studio
# Lapora Marketing Digital

"""
Métricas avanzadas para plan Studio:

- Volumen por canal (WhatsApp/Instagram/Email)
- Tasa de respuesta IA vs manual
- Tiempo medio de respuesta del consultorio
- LTV (lifetime value) promedio por paciente
- Conversión cita-mostrar
- Pacientes adquiridos por mes
- Costo estimado de adquisición por paciente
- Top tratamientos por revenue
"""

from datetime import datetime, timedelta
from typing import Optional
from sqlalchemy import select, func, desc, and_, or_

from agent.memory import async_session
from agent.clinic_models import (
    Paciente, MensajeUnificado, CitaClinic, Llamada
)


async def analytics_completo(
    clinica_id: int,
    dias_atras: int = 30,
) -> dict:
    """Calcula todas las métricas para el periodo.

    Returns: dict con todas las secciones organizadas.
    """
    ahora = datetime.utcnow()
    desde = ahora - timedelta(days=dias_atras)

    return {
        "periodo_dias": dias_atras,
        "desde": desde.isoformat(),
        "hasta": ahora.isoformat(),
        "volumen_canal": await _volumen_por_canal(clinica_id, desde),
        "respuesta_ia":  await _stats_respuesta_ia(clinica_id, desde),
        "tiempo_respuesta": await _tiempo_medio_respuesta(clinica_id, desde),
        "pacientes":     await _stats_pacientes(clinica_id, desde),
        "citas":         await _stats_citas(clinica_id, desde),
        "ltv":           await _ltv_promedio(clinica_id),
        "top_tratamientos": await _top_tratamientos(clinica_id),
        "tendencia_diaria": await _tendencia_mensajes_diaria(clinica_id, dias_atras),
    }


# ════════════════════════════════════════════════════════════
# QUERIES INDIVIDUALES
# ════════════════════════════════════════════════════════════

async def _volumen_por_canal(clinica_id: int, desde: datetime) -> dict:
    """Cuántos mensajes ENTRANTES por canal."""
    async with async_session() as session:
        result = await session.execute(
            select(MensajeUnificado.canal, func.count(MensajeUnificado.id))
            .where(MensajeUnificado.clinica_id == clinica_id)
            .where(MensajeUnificado.direccion == "entrada")
            .where(MensajeUnificado.timestamp >= desde)
            .group_by(MensajeUnificado.canal)
        )
        por_canal = {row[0] or "otro": int(row[1]) for row in result.all()}
    total = sum(por_canal.values()) or 1
    return {
        "total": sum(por_canal.values()),
        "whatsapp": por_canal.get("whatsapp", 0),
        "instagram": por_canal.get("instagram", 0),
        "email": por_canal.get("email", 0),
        "otro": sum(v for k, v in por_canal.items() if k not in ("whatsapp", "instagram", "email")),
        "pct_whatsapp": round(100 * por_canal.get("whatsapp", 0) / total, 1),
        "pct_instagram": round(100 * por_canal.get("instagram", 0) / total, 1),
        "pct_email": round(100 * por_canal.get("email", 0) / total, 1),
    }


async def _stats_respuesta_ia(clinica_id: int, desde: datetime) -> dict:
    """Cuántas respuestas fueron generadas por IA vs humano."""
    async with async_session() as session:
        result = await session.execute(
            select(MensajeUnificado.respondido_por, func.count(MensajeUnificado.id))
            .where(MensajeUnificado.clinica_id == clinica_id)
            .where(MensajeUnificado.direccion == "salida")
            .where(MensajeUnificado.timestamp >= desde)
            .group_by(MensajeUnificado.respondido_por)
        )
        por_origen = {row[0] or "manual": int(row[1]) for row in result.all()}

    total = sum(por_origen.values()) or 1
    return {
        "total_respuestas": sum(por_origen.values()),
        "por_ia": por_origen.get("ia", 0),
        "por_humano": por_origen.get("usuario", 0) + por_origen.get("manual", 0),
        "por_recordatorio": por_origen.get("recordatorio", 0),
        "pct_automatizado": round(100 * (por_origen.get("ia", 0) + por_origen.get("recordatorio", 0)) / total, 1),
    }


async def _tiempo_medio_respuesta(clinica_id: int, desde: datetime) -> dict:
    """Tiempo medio entre mensaje entrante y primera respuesta saliente.

    Limitado a últimas N conversaciones por performance.
    """
    async with async_session() as session:
        # Tomar mensajes entrantes recientes con su próxima respuesta de salida
        result = await session.execute(
            select(MensajeUnificado)
            .where(MensajeUnificado.clinica_id == clinica_id)
            .where(MensajeUnificado.direccion == "entrada")
            .where(MensajeUnificado.timestamp >= desde)
            .order_by(desc(MensajeUnificado.timestamp))
            .limit(300)
        )
        entrantes = list(result.scalars().all())

    tiempos_seg: list[float] = []
    async with async_session() as session:
        for entrada in entrantes:
            # Próxima salida del MISMO paciente DESPUÉS de este entrada
            salida = (await session.execute(
                select(MensajeUnificado)
                .where(MensajeUnificado.paciente_id == entrada.paciente_id)
                .where(MensajeUnificado.direccion == "salida")
                .where(MensajeUnificado.timestamp > entrada.timestamp)
                .order_by(MensajeUnificado.timestamp)
                .limit(1)
            )).scalar_one_or_none()
            if salida:
                delta = (salida.timestamp - entrada.timestamp).total_seconds()
                # Filtrar outliers (> 24h)
                if 0 < delta < 86400:
                    tiempos_seg.append(delta)

    if not tiempos_seg:
        return {"muestra": 0, "promedio_seg": 0, "promedio_legible": "Sin datos"}

    promedio = sum(tiempos_seg) / len(tiempos_seg)
    if promedio < 60:
        legible = f"{int(promedio)}s"
    elif promedio < 3600:
        legible = f"{int(promedio/60)} min"
    else:
        legible = f"{round(promedio/3600, 1)}h"

    return {
        "muestra": len(tiempos_seg),
        "promedio_seg": round(promedio, 1),
        "promedio_legible": legible,
    }


async def _stats_pacientes(clinica_id: int, desde: datetime) -> dict:
    """Pacientes nuevos en el periodo + total activos."""
    async with async_session() as session:
        nuevos = (await session.execute(
            select(func.count(Paciente.id))
            .where(Paciente.clinica_id == clinica_id)
            .where(Paciente.primer_contacto >= desde)
        )).scalar() or 0

        activos = (await session.execute(
            select(func.count(Paciente.id))
            .where(Paciente.clinica_id == clinica_id)
            .where(Paciente.estado.in_(["nuevo", "activo"]))
        )).scalar() or 0

        total = (await session.execute(
            select(func.count(Paciente.id))
            .where(Paciente.clinica_id == clinica_id)
        )).scalar() or 0

    return {
        "nuevos_periodo": int(nuevos),
        "activos_total": int(activos),
        "total_base": int(total),
    }


async def _stats_citas(clinica_id: int, desde: datetime) -> dict:
    """Citas en el periodo + tasa de show."""
    async with async_session() as session:
        # Citas agendadas en el periodo
        result = await session.execute(
            select(CitaClinic.estado, func.count(CitaClinic.id))
            .where(CitaClinic.clinica_id == clinica_id)
            .where(CitaClinic.fecha_hora >= desde)
            .group_by(CitaClinic.estado)
        )
        por_estado = {row[0]: int(row[1]) for row in result.all()}

    completadas = por_estado.get("completada", 0)
    no_show = por_estado.get("no_show", 0)
    canceladas = por_estado.get("cancelada", 0)
    total_finalizadas = completadas + no_show
    tasa_show = round(100 * completadas / total_finalizadas, 1) if total_finalizadas else 0

    return {
        "total_periodo": sum(por_estado.values()),
        "completadas": completadas,
        "no_show": no_show,
        "canceladas": canceladas,
        "agendadas_futuras": por_estado.get("agendada", 0),
        "tasa_show_pct": tasa_show,
    }


async def _ltv_promedio(clinica_id: int) -> dict:
    """Valor promedio por paciente (lifetime)."""
    async with async_session() as session:
        result = await session.execute(
            select(func.avg(Paciente.valor_total), func.max(Paciente.valor_total))
            .where(Paciente.clinica_id == clinica_id)
            .where(Paciente.valor_total > 0)
        )
        row = result.one()
        promedio = float(row[0] or 0)
        maximo = float(row[1] or 0)

    return {
        "promedio_cop": int(promedio),
        "maximo_cop": int(maximo),
    }


async def _top_tratamientos(clinica_id: int) -> list[dict]:
    """Top 5 tratamientos por cantidad de pacientes."""
    async with async_session() as session:
        result = await session.execute(
            select(Paciente.tratamiento_actual, func.count(Paciente.id))
            .where(Paciente.clinica_id == clinica_id)
            .where(Paciente.tratamiento_actual != "")
            .group_by(Paciente.tratamiento_actual)
            .order_by(desc(func.count(Paciente.id)))
            .limit(5)
        )
        return [{"tratamiento": row[0] or "Sin definir", "pacientes": int(row[1])} for row in result.all()]


async def _tendencia_mensajes_diaria(clinica_id: int, dias: int) -> list[dict]:
    """Mensajes recibidos por día (para gráfico de líneas).

    Returns: lista [{"fecha": "DD/MM", "mensajes": N}]
    """
    ahora = datetime.utcnow()
    desde = ahora - timedelta(days=dias)

    async with async_session() as session:
        # Agrupar por día (SQLite y Postgres soportan strftime/date_trunc)
        # Usamos SQLAlchemy `func.date()` que funciona en ambos
        result = await session.execute(
            select(
                func.date(MensajeUnificado.timestamp).label("dia"),
                func.count(MensajeUnificado.id).label("n"),
            )
            .where(MensajeUnificado.clinica_id == clinica_id)
            .where(MensajeUnificado.direccion == "entrada")
            .where(MensajeUnificado.timestamp >= desde)
            .group_by(func.date(MensajeUnificado.timestamp))
            .order_by(func.date(MensajeUnificado.timestamp))
        )
        por_dia = {str(row[0]): int(row[1]) for row in result.all()}

    # Rellenar días vacíos
    serie = []
    for i in range(dias, -1, -1):
        d = (ahora - timedelta(days=i)).date()
        d_str = d.isoformat()
        serie.append({
            "fecha": d.strftime("%d/%m"),
            "mensajes": por_dia.get(d_str, 0),
        })
    return serie
