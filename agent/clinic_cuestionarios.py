# -*- coding: utf-8 -*-
# agent/clinic_cuestionarios.py — Cuestionarios pre-consulta para clínicas
# Lapora Marketing Digital — PHVA H3

"""
Sistema de formularios pre-consulta:

1. Clínica configura cuestionarios desde /clinic/app/cuestionarios
2. Al crear una cita, opcionalmente se asigna un cuestionario
3. Se genera un token único + link público para el paciente
4. Paciente llena el form sin necesidad de cuenta
5. Doctor ve las respuestas en la página de la cita

Tipos de pregunta soportados:
- texto (campo libre)
- si_no (radio Sí/No)
- escala (1-10)
- numero
- seleccion (dropdown con opciones)
"""

import json
import secrets
import logging
from datetime import datetime
from typing import Optional
from sqlalchemy import select

from agent.memory import async_session
from agent.clinic_models import Cuestionario, RespuestaCuestionario, CitaClinic, Paciente

logger = logging.getLogger("agentkit")


# ════════════════════════════════════════════════════════════
# CUESTIONARIO DEFAULT — Se crea automáticamente con cada clínica nueva
# ════════════════════════════════════════════════════════════

PREGUNTAS_DEFAULT = [
    {
        "id": "motivo_consulta",
        "texto": "¿Cuál es el motivo principal de tu consulta hoy?",
        "tipo": "texto",
        "requerido": True,
    },
    {
        "id": "sintomas_dias",
        "texto": "¿Hace cuántos días tienes molestias?",
        "tipo": "numero",
        "requerido": False,
    },
    {
        "id": "dolor_escala",
        "texto": "Si tienes dolor, califícalo de 1 (mínimo) a 10 (insoportable)",
        "tipo": "escala",
        "requerido": False,
    },
    {
        "id": "alergias",
        "texto": "¿Tienes alergia a algún medicamento o sustancia?",
        "tipo": "si_no",
        "requerido": True,
    },
    {
        "id": "alergias_detalle",
        "texto": "Si sí: ¿a cuáles?",
        "tipo": "texto",
        "requerido": False,
    },
    {
        "id": "medicamentos",
        "texto": "¿Estás tomando algún medicamento actualmente?",
        "tipo": "texto",
        "requerido": False,
    },
    {
        "id": "antecedentes",
        "texto": "Antecedentes médicos importantes (diabetes, HTA, cirugías previas)",
        "tipo": "texto",
        "requerido": False,
    },
]


async def crear_cuestionario_default(clinica_id: int) -> Optional[Cuestionario]:
    """Crea el cuestionario default si la clínica no tiene ninguno."""
    async with async_session() as session:
        existe = (await session.execute(
            select(Cuestionario).where(Cuestionario.clinica_id == clinica_id).limit(1)
        )).scalar_one_or_none()
        if existe:
            return existe
        q = Cuestionario(
            clinica_id=clinica_id,
            titulo="Cuestionario pre-consulta general",
            descripcion="Ayúdanos a prepararte mejor la consulta. Toma 2 minutos.",
            preguntas_json=json.dumps(PREGUNTAS_DEFAULT, ensure_ascii=False),
            activo=True,
            es_default=True,
        )
        session.add(q)
        await session.commit()
        await session.refresh(q)
    return q


# ════════════════════════════════════════════════════════════
# TOKEN PARA CITA + ENVÍO LINK
# ════════════════════════════════════════════════════════════

def generar_token_cuestionario() -> str:
    return secrets.token_urlsafe(24)


async def asegurar_token_cita(cita_id: int) -> str:
    """Devuelve el token único de la cita para acceso público al cuestionario."""
    async with async_session() as session:
        c = (await session.execute(
            select(CitaClinic).where(CitaClinic.id == cita_id)
        )).scalar_one_or_none()
        if not c:
            return ""
        if c.cuestionario_token:
            return c.cuestionario_token
        c.cuestionario_token = generar_token_cuestionario()
        await session.commit()
        return c.cuestionario_token


async def respuesta_de_cita(cita_id: int) -> Optional[RespuestaCuestionario]:
    """Devuelve la respuesta del cuestionario asociada a esta cita, si existe."""
    async with async_session() as session:
        r = (await session.execute(
            select(RespuestaCuestionario)
            .where(RespuestaCuestionario.cita_id == cita_id)
            .order_by(RespuestaCuestionario.creado_en.desc())
            .limit(1)
        )).scalar_one_or_none()
    return r


def parse_preguntas(preguntas_json: str) -> list[dict]:
    """Parsea con safety el JSON de preguntas."""
    if not preguntas_json:
        return []
    try:
        data = json.loads(preguntas_json)
        return data if isinstance(data, list) else []
    except Exception:
        return []


def render_pregunta_html(p: dict, valor_actual: str = "") -> str:
    """Genera el HTML de una pregunta según su tipo."""
    import html as _html
    pid = _html.escape(str(p.get("id", "")), quote=True)
    texto = _html.escape(str(p.get("texto", "")))
    tipo = p.get("tipo", "texto")
    requerido = "required" if p.get("requerido") else ""
    val = _html.escape(str(valor_actual or ""), quote=True)

    label = f'<label style="font-weight:600;display:block;margin-bottom:6px;font-size:14px;color:#374151;">{texto}{" *" if requerido else ""}</label>'

    if tipo == "si_no":
        marked_si = "checked" if valor_actual == "si" else ""
        marked_no = "checked" if valor_actual == "no" else ""
        return f'''
        <div style="margin-bottom:18px;">{label}
            <label style="margin-right:18px;cursor:pointer;"><input type="radio" name="{pid}" value="si" {marked_si} {requerido}> Sí</label>
            <label style="cursor:pointer;"><input type="radio" name="{pid}" value="no" {marked_no} {requerido}> No</label>
        </div>'''
    elif tipo == "escala":
        return f'''
        <div style="margin-bottom:18px;">{label}
            <input type="range" name="{pid}" min="1" max="10" value="{val or 5}" {requerido} oninput="document.getElementById('out_{pid}').textContent=this.value" style="width:100%;">
            <div style="display:flex;justify-content:space-between;font-size:11px;color:#9CA3AF;"><span>1</span><strong id="out_{pid}" style="color:#FF3B30;font-size:16px;">{val or 5}</strong><span>10</span></div>
        </div>'''
    elif tipo == "numero":
        return f'<div style="margin-bottom:18px;">{label}<input type="number" name="{pid}" value="{val}" {requerido} style="width:100%;padding:10px 14px;border:1px solid #E5E7EB;border-radius:8px;font-size:14px;"></div>'
    else:  # texto
        return f'<div style="margin-bottom:18px;">{label}<textarea name="{pid}" rows="3" {requerido} style="width:100%;padding:10px 14px;border:1px solid #E5E7EB;border-radius:8px;font-size:14px;resize:vertical;font-family:inherit;">{val}</textarea></div>'
