# -*- coding: utf-8 -*-
# agent/clinic_calendar.py — Calendar service per-tenant para Lapora Clinic
# Lapora Marketing Digital

"""
Servicio Google Calendar para Lapora Clinic.

Estrategia simple (MVP):
- Cada clínica configura SU google_calendar_id (ej: secretaria@suclinica.com)
- Comparten el Service Account de Lapora con permisos "Hacer cambios"
- El Service Account vive en GOOGLE_SERVICE_ACCOUNT_JSON (env var global)
- Las citas se crean en el calendar de cada clínica

Para conectar una clínica:
1. La clínica obtiene el email del SA (en /clinic/app/configuracion)
2. Comparten su Google Calendar con ese email con permisos de modificación
3. Pegan el Calendar ID en configuración
4. Listo — Lapora puede crear/leer/cancelar eventos
"""

import os
import json
import logging
from datetime import datetime, timedelta
from typing import Optional
import pytz

try:
    from google.oauth2 import service_account
    from googleapiclient.discovery import build
    from googleapiclient.errors import HttpError
    GOOGLE_AVAILABLE = True
except ImportError:
    GOOGLE_AVAILABLE = False

logger = logging.getLogger("agentkit")

SCOPES = ["https://www.googleapis.com/auth/calendar"]
TIMEZONE = pytz.timezone("America/Bogota")
DURATION_MIN_DEFAULT = 30


def _obtener_servicio():
    """Crea un cliente de Google Calendar API con el Service Account global."""
    if not GOOGLE_AVAILABLE:
        raise ImportError("google-api-python-client no esta instalado")
    json_str = os.getenv("GOOGLE_SERVICE_ACCOUNT_JSON")
    if not json_str:
        raise ValueError("GOOGLE_SERVICE_ACCOUNT_JSON no esta configurado")
    info = json.loads(json_str)
    creds = service_account.Credentials.from_service_account_info(info, scopes=SCOPES)
    return build("calendar", "v3", credentials=creds, cache_discovery=False)


def obtener_email_service_account() -> str:
    """Devuelve el email del Service Account para que las clínicas lo compartan."""
    try:
        info = json.loads(os.getenv("GOOGLE_SERVICE_ACCOUNT_JSON", "{}"))
        return info.get("client_email", "")
    except Exception:
        return ""


def crear_evento(
    calendar_id: str,
    fecha_hora: datetime,
    titulo: str,
    descripcion: str = "",
    duracion_min: int = 30,
    email_paciente: Optional[str] = None,
) -> dict:
    """Crea un evento en el calendar de una clínica.

    Args:
        calendar_id: ID del calendar de la clínica (configurado en su perfil)
        fecha_hora: datetime de inicio (debe estar localizado en America/Bogota)
        titulo: Título del evento
        descripcion: Descripción / notas
        duracion_min: Duración en minutos
        email_paciente: Si se incluye, se manda invitación

    Returns:
        {"exito": bool, "evento_id": str, "link_meet": str, "mensaje": str}
    """
    if not GOOGLE_AVAILABLE:
        return {"exito": False, "mensaje": "Google Calendar API no disponible (instalar dependencias)"}
    if not calendar_id:
        return {"exito": False, "mensaje": "La clínica no tiene Calendar configurado"}

    try:
        service = _obtener_servicio()
    except Exception as e:
        return {"exito": False, "mensaje": f"Error de credenciales: {e}"}

    # Asegurar timezone
    if fecha_hora.tzinfo is None:
        fecha_hora = TIMEZONE.localize(fecha_hora)
    fecha_fin = fecha_hora + timedelta(minutes=duracion_min)

    evento = {
        "summary": titulo,
        "description": descripcion,
        "start": {"dateTime": fecha_hora.isoformat(), "timeZone": "America/Bogota"},
        "end":   {"dateTime": fecha_fin.isoformat(),  "timeZone": "America/Bogota"},
        "conferenceData": {
            "createRequest": {
                "requestId": f"lapora-{int(fecha_hora.timestamp())}",
                "conferenceSolutionKey": {"type": "hangoutsMeet"},
            }
        },
    }
    if email_paciente:
        evento["attendees"] = [{"email": email_paciente, "responseStatus": "needsAction"}]

    try:
        creado = service.events().insert(
            calendarId=calendar_id,
            body=evento,
            conferenceDataVersion=1,
            sendUpdates="all" if email_paciente else "none",
        ).execute()
        link_meet = ""
        if creado.get("conferenceData"):
            entry_points = creado["conferenceData"].get("entryPoints", [])
            for ep in entry_points:
                if ep.get("entryPointType") == "video":
                    link_meet = ep.get("uri", "")
                    break
        return {
            "exito": True,
            "evento_id": creado.get("id", ""),
            "link_meet": link_meet,
            "link_evento": creado.get("htmlLink", ""),
            "mensaje": "Cita agendada correctamente",
        }
    except HttpError as e:
        msg = str(e)[:200]
        if "404" in msg:
            return {"exito": False, "mensaje": f"Calendar no encontrado o sin permisos. Verifica que compartiste el calendar con {obtener_email_service_account()}"}
        return {"exito": False, "mensaje": f"Error Google: {msg}"}
    except Exception as e:
        return {"exito": False, "mensaje": f"Error: {str(e)[:200]}"}


def listar_eventos(calendar_id: str, dias: int = 30, max_resultados: int = 50) -> list[dict]:
    """Lista próximos eventos del calendar."""
    if not GOOGLE_AVAILABLE or not calendar_id:
        return []
    try:
        service = _obtener_servicio()
        ahora = datetime.now(TIMEZONE)
        fin = ahora + timedelta(days=dias)
        events = service.events().list(
            calendarId=calendar_id,
            timeMin=ahora.isoformat(),
            timeMax=fin.isoformat(),
            singleEvents=True,
            orderBy="startTime",
            maxResults=max_resultados,
        ).execute()
        return [
            {
                "id": e["id"],
                "titulo": e.get("summary", ""),
                "descripcion": e.get("description", ""),
                "inicio": e["start"].get("dateTime", e["start"].get("date")),
                "fin": e["end"].get("dateTime", e["end"].get("date")),
                "link_meet": next(
                    (ep["uri"] for ep in e.get("conferenceData", {}).get("entryPoints", [])
                     if ep.get("entryPointType") == "video"), ""
                ),
                "link_evento": e.get("htmlLink", ""),
            }
            for e in events.get("items", [])
        ]
    except Exception:
        return []


def cancelar_evento(calendar_id: str, evento_id: str) -> bool:
    """Cancela un evento."""
    if not GOOGLE_AVAILABLE or not calendar_id or not evento_id:
        return False
    try:
        service = _obtener_servicio()
        service.events().delete(
            calendarId=calendar_id,
            eventId=evento_id,
            sendUpdates="all",
        ).execute()
        return True
    except Exception:
        return False


def verificar_disponibilidad(calendar_id: str, fecha_hora: datetime, duracion_min: int = 30) -> bool:
    """Devuelve True si NO hay eventos solapados en ese horario."""
    if not GOOGLE_AVAILABLE or not calendar_id:
        return True  # Si no hay Calendar, asumimos disponible
    try:
        service = _obtener_servicio()
        if fecha_hora.tzinfo is None:
            fecha_hora = TIMEZONE.localize(fecha_hora)
        fin = fecha_hora + timedelta(minutes=duracion_min)
        events = service.events().list(
            calendarId=calendar_id,
            timeMin=fecha_hora.isoformat(),
            timeMax=fin.isoformat(),
            singleEvents=True,
        ).execute()
        return len(events.get("items", [])) == 0
    except Exception:
        return True
