# agent/tools.py — Herramientas de SofIA para Lapora
# Generado por AgentKit

"""
Herramientas especificas del negocio Lapora.
Estas funciones extienden las capacidades de SofIA mas alla de responder texto.

Casos de uso configurados:
1. Responder preguntas frecuentes (FAQ)
2. Agendar diagnosticos y consultorias
3. Calificar leads (doctores interesados)
4. Tomar pedidos (contratar servicios)
5. Soporte post-venta
"""

import os
import yaml
import logging
from datetime import datetime, time
from pathlib import Path

logger = logging.getLogger("agentkit")


# ═══════════════════════════════════════════════════════════
# UTILIDADES BASE
# ═══════════════════════════════════════════════════════════

def cargar_info_negocio() -> dict:
    """Carga la informacion del negocio desde business.yaml."""
    try:
        with open("config/business.yaml", "r", encoding="utf-8") as f:
            return yaml.safe_load(f)
    except FileNotFoundError:
        logger.error("config/business.yaml no encontrado")
        return {}


def buscar_en_knowledge(consulta: str) -> str:
    """
    Busca informacion relevante en los archivos de /knowledge.
    Retorna el contenido mas relevante encontrado.
    """
    resultados = []
    knowledge_dir = Path("knowledge")

    if not knowledge_dir.exists():
        return "No hay archivos de conocimiento disponibles."

    for archivo in knowledge_dir.iterdir():
        if archivo.name.startswith(".") or not archivo.is_file():
            continue
        try:
            contenido = archivo.read_text(encoding="utf-8")
            # Busqueda simple por coincidencia de texto
            if consulta.lower() in contenido.lower():
                # Encontrar el contexto alrededor de la palabra
                idx = contenido.lower().find(consulta.lower())
                inicio = max(0, idx - 200)
                fin = min(len(contenido), idx + 500)
                fragmento = contenido[inicio:fin]
                resultados.append(f"[{archivo.name}]: ...{fragmento}...")
        except (UnicodeDecodeError, IOError):
            continue

    if resultados:
        return "\n---\n".join(resultados[:3])  # Maximo 3 resultados
    return "No encontre informacion especifica sobre eso en mis archivos."


# ═══════════════════════════════════════════════════════════
# HORARIO Y DISPONIBILIDAD
# ═══════════════════════════════════════════════════════════

def esta_en_horario() -> bool:
    """
    Verifica si la hora actual esta dentro del horario de atencion.
    Lapora: Todos los dias 7:00 AM - 8:00 PM (hora Colombia, UTC-5).
    """
    ahora = datetime.now()
    hora_actual = ahora.time()
    apertura = time(7, 0)
    cierre = time(20, 0)
    return apertura <= hora_actual <= cierre


def obtener_horario() -> dict:
    """Retorna el horario de atencion del negocio."""
    info = cargar_info_negocio()
    return {
        "horario": info.get("negocio", {}).get("horario", "No disponible"),
        "esta_abierto": esta_en_horario(),
    }


# ═══════════════════════════════════════════════════════════
# CALIFICACION DE LEADS (DOCTORES INTERESADOS)
# ═══════════════════════════════════════════════════════════

def calificar_lead(
    especialidad: str = None,
    ciudad: str = None,
    pacientes_mes: int = None,
    presupuesto_mensual: str = None,
) -> dict:
    """
    Califica un lead segun los criterios de cliente ideal de Lapora.

    Returns:
        dict con score (0-100) y categoria (frio, tibio, caliente, VIP)
    """
    score = 50  # Base
    razones = []

    # Especialidades de alto valor
    especialidades_premium = [
        "cirujano plastico", "cirujano", "ortopeda", "traumatologo",
        "cardiologo", "dermatologo", "neurologo", "ginecologo",
        "odontologo", "implantologo", "ortodoncista", "esteticista",
    ]
    if especialidad:
        if any(e in especialidad.lower() for e in especialidades_premium):
            score += 20
            razones.append("Especialidad premium")

    # Ciudades principales
    ciudades_top = ["bogota", "medellin", "cali", "barranquilla", "bucaramanga", "ibague"]
    if ciudad and any(c in ciudad.lower() for c in ciudades_top):
        score += 10
        razones.append("Ciudad principal")

    # Cantidad de pacientes (mas pacientes = mas establecido)
    if pacientes_mes is not None:
        if pacientes_mes >= 30:
            score += 15
            razones.append("Volumen alto de pacientes (+30/mes)")
        elif pacientes_mes >= 16:
            score += 10
            razones.append("Volumen regular (16-30/mes)")

    # Presupuesto disponible
    if presupuesto_mensual and presupuesto_mensual.lower() not in ["bajo", "ninguno"]:
        score += 15
        razones.append("Presupuesto disponible para invertir")

    # Categorizar
    score = min(100, score)
    if score >= 85:
        categoria = "VIP"
    elif score >= 70:
        categoria = "CALIENTE"
    elif score >= 55:
        categoria = "TIBIO"
    else:
        categoria = "FRIO"

    return {
        "score": score,
        "categoria": categoria,
        "razones": razones,
    }


# ═══════════════════════════════════════════════════════════
# AGENDAMIENTO DE DIAGNOSTICOS
# ═══════════════════════════════════════════════════════════

def registrar_solicitud_diagnostico(
    telefono: str,
    nombre_doctor: str,
    especialidad: str,
    ciudad: str,
    horario_preferido: str = None,
) -> dict:
    """
    Registra una solicitud de diagnostico gratuito.
    En produccion deberia integrarse con un CRM (HubSpot, Salesforce, etc.).
    """
    solicitud = {
        "telefono": telefono,
        "doctor": nombre_doctor,
        "especialidad": especialidad,
        "ciudad": ciudad,
        "horario_preferido": horario_preferido or "Cualquier momento",
        "fecha_solicitud": datetime.now().isoformat(),
        "estado": "pendiente",
    }

    # Aqui se integraria con CRM real. Por ahora se loguea.
    logger.info(f"NUEVA SOLICITUD DIAGNOSTICO: {solicitud}")

    return {
        "exito": True,
        "mensaje": (
            f"Listo, doctor {nombre_doctor}. Su solicitud de diagnostico esta registrada. "
            f"Un asesor de Lapora le contactara hoy en horario de atencion (7am-8pm)."
        ),
        "solicitud": solicitud,
    }


# ═══════════════════════════════════════════════════════════
# CONTACTO HUMANO / ESCALAR
# ═══════════════════════════════════════════════════════════

def escalar_a_asesor_humano(telefono: str, contexto: str, urgencia: str = "normal") -> dict:
    """
    Marca una conversacion para que un asesor humano la atienda.
    En produccion se integraria con un sistema de tickets o notificacion al equipo.
    """
    escalamiento = {
        "telefono": telefono,
        "contexto": contexto,
        "urgencia": urgencia,
        "timestamp": datetime.now().isoformat(),
    }

    logger.warning(f"ESCALAMIENTO A HUMANO: {escalamiento}")

    return {
        "exito": True,
        "mensaje": (
            "Listo, doctor. Le he pasado su caso a un asesor humano de Lapora. "
            "Le escribiran en menos de 30 minutos (en horario 7am-8pm)."
        ),
    }
