# agent/calendar_service.py — Integracion con Google Calendar
# Generado por AgentKit

"""
Servicio para gestionar citas en Google Calendar usando Service Account.

Funciones disponibles:
- verificar_disponibilidad(fecha_hora)
- agendar_cita(fecha_hora, nombre_doctor, email_doctor, descripcion, telefono)
- listar_citas_proximas(dias)
- cancelar_cita(event_id)

Requiere las variables de entorno:
- GOOGLE_SERVICE_ACCOUNT_JSON: JSON completo del Service Account
- GOOGLE_CALENDAR_ID: ID del calendario (ej: mgelvezchavarro3@gmail.com)
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

# Configuracion
CALENDAR_ID = os.getenv("GOOGLE_CALENDAR_ID", "primary")
SCOPES = ["https://www.googleapis.com/auth/calendar"]
TIMEZONE = pytz.timezone("America/Bogota")
DURATION_MIN = int(os.getenv("CITAS_DURATION_MINUTES", "30"))
HORA_INICIO = int(os.getenv("CITAS_HORA_INICIO", "7"))  # 7 AM
HORA_FIN = int(os.getenv("CITAS_HORA_FIN", "20"))  # 8 PM


def _obtener_credenciales():
    """Carga las credenciales del Service Account desde la variable de entorno."""
    if not GOOGLE_AVAILABLE:
        raise ImportError("google-api-python-client no esta instalado")

    json_str = os.getenv("GOOGLE_SERVICE_ACCOUNT_JSON")
    if not json_str:
        raise ValueError(
            "GOOGLE_SERVICE_ACCOUNT_JSON no esta configurado en .env"
        )

    try:
        info = json.loads(json_str)
    except json.JSONDecodeError as e:
        raise ValueError(f"GOOGLE_SERVICE_ACCOUNT_JSON no es un JSON valido: {e}")

    creds = service_account.Credentials.from_service_account_info(
        info, scopes=SCOPES
    )
    return creds


def _obtener_servicio():
    """Crea un cliente de Google Calendar API."""
    creds = _obtener_credenciales()
    service = build("calendar", "v3", credentials=creds, cache_discovery=False)
    return service


def _parsear_fecha_hora(fecha_str: str, hora_str: str) -> datetime:
    """
    Convierte fecha y hora en string a datetime con zona horaria Colombia.

    Args:
        fecha_str: "2026-05-25" o "25/05/2026" o "manana"
        hora_str: "15:00" o "3pm" o "3:00 pm"
    """
    # Parsear fecha
    fecha_str = fecha_str.strip().lower()
    hoy = datetime.now(TIMEZONE).date()

    if fecha_str in ("hoy", "today"):
        fecha = hoy
    elif fecha_str in ("manana", "mañana", "tomorrow"):
        fecha = hoy + timedelta(days=1)
    elif fecha_str in ("pasado", "pasado manana", "pasado mañana"):
        fecha = hoy + timedelta(days=2)
    elif "/" in fecha_str:
        # 25/05/2026 o 25/05
        partes = fecha_str.split("/")
        dia = int(partes[0])
        mes = int(partes[1])
        anio = int(partes[2]) if len(partes) > 2 else hoy.year
        fecha = datetime(anio, mes, dia).date()
    elif "-" in fecha_str:
        # 2026-05-25
        fecha = datetime.strptime(fecha_str, "%Y-%m-%d").date()
    else:
        raise ValueError(f"No pude interpretar la fecha: {fecha_str}")

    # Parsear hora
    hora_str = hora_str.strip().lower().replace(" ", "")

    if "pm" in hora_str:
        hora_str = hora_str.replace("pm", "")
        if ":" in hora_str:
            h, m = hora_str.split(":")
            hora = int(h)
            minuto = int(m)
        else:
            hora = int(hora_str)
            minuto = 0
        if hora < 12:
            hora += 12
    elif "am" in hora_str:
        hora_str = hora_str.replace("am", "")
        if ":" in hora_str:
            h, m = hora_str.split(":")
            hora = int(h)
            minuto = int(m)
        else:
            hora = int(hora_str)
            minuto = 0
        if hora == 12:
            hora = 0
    elif ":" in hora_str:
        h, m = hora_str.split(":")
        hora = int(h)
        minuto = int(m)
    else:
        hora = int(hora_str)
        minuto = 0

    dt = datetime(fecha.year, fecha.month, fecha.day, hora, minuto)
    return TIMEZONE.localize(dt)


def verificar_disponibilidad(fecha: str, hora: str) -> dict:
    """
    Verifica si una franja horaria esta disponible.

    Args:
        fecha: "manana", "2026-05-25", "25/05/2026"
        hora: "3pm", "15:00", "3:30 pm"

    Returns:
        dict con 'disponible' (bool) y 'mensaje' (str)
    """
    try:
        dt_inicio = _parsear_fecha_hora(fecha, hora)
        dt_fin = dt_inicio + timedelta(minutes=DURATION_MIN)

        # Validar horario de atencion
        if dt_inicio.hour < HORA_INICIO or dt_inicio.hour >= HORA_FIN:
            return {
                "disponible": False,
                "mensaje": f"Esa hora esta fuera de nuestro horario de atencion ({HORA_INICIO}am - {HORA_FIN}pm).",
            }

        # Validar que no sea en el pasado
        ahora = datetime.now(TIMEZONE)
        if dt_inicio < ahora:
            return {
                "disponible": False,
                "mensaje": "Esa fecha y hora ya pasaron. Por favor proponga una fecha futura.",
            }

        # Validar que sea con al menos 1 hora de anticipacion
        if dt_inicio < ahora + timedelta(hours=1):
            return {
                "disponible": False,
                "mensaje": "Necesitamos al menos 1 hora de anticipacion para agendar.",
            }

        service = _obtener_servicio()
        eventos = service.events().list(
            calendarId=CALENDAR_ID,
            timeMin=dt_inicio.isoformat(),
            timeMax=dt_fin.isoformat(),
            singleEvents=True,
            orderBy="startTime",
        ).execute()

        items = eventos.get("items", [])

        if items:
            return {
                "disponible": False,
                "mensaje": f"Esa franja esta ocupada. Ya hay un evento agendado a esa hora.",
            }

        return {
            "disponible": True,
            "mensaje": f"Disponible: {dt_inicio.strftime('%A %d de %B a las %I:%M %p')} (Colombia).",
            "fecha_iso": dt_inicio.isoformat(),
        }

    except ValueError as e:
        return {"disponible": False, "mensaje": f"Error: {e}"}
    except HttpError as e:
        logger.error(f"Error Google Calendar al verificar: {e}")
        return {"disponible": False, "mensaje": f"Error tecnico con el calendario."}
    except Exception as e:
        logger.error(f"Error inesperado verificando disponibilidad: {e}")
        return {"disponible": False, "mensaje": f"Error inesperado: {e}"}


def agendar_cita(
    fecha: str,
    hora: str,
    nombre_doctor: str,
    email_doctor: Optional[str] = None,
    telefono: Optional[str] = None,
    especialidad: Optional[str] = None,
    ciudad: Optional[str] = None,
    notas: Optional[str] = None,
) -> dict:
    """
    Crea un evento de diagnostico en Google Calendar.

    Args:
        fecha: "manana", "2026-05-25"
        hora: "3pm", "15:00"
        nombre_doctor: Nombre del doctor
        email_doctor: Email para enviar invitacion (opcional)
        telefono: WhatsApp del doctor
        especialidad: Especialidad medica
        ciudad: Ciudad
        notas: Contexto adicional

    Returns:
        dict con 'exito' (bool), 'mensaje' (str), 'evento_id' (str)
    """
    try:
        # Verificar disponibilidad primero
        disp = verificar_disponibilidad(fecha, hora)
        if not disp["disponible"]:
            return {
                "exito": False,
                "mensaje": disp["mensaje"],
            }

        dt_inicio = datetime.fromisoformat(disp["fecha_iso"])
        dt_fin = dt_inicio + timedelta(minutes=DURATION_MIN)

        # Construir descripcion del evento
        descripcion_lineas = [
            "🩺 Diagnostico digital agendado via SofIA (WhatsApp Bot Lapora)",
            "",
            f"Doctor: {nombre_doctor}",
        ]
        if especialidad:
            descripcion_lineas.append(f"Especialidad: {especialidad}")
        if ciudad:
            descripcion_lineas.append(f"Ciudad: {ciudad}")
        if telefono:
            descripcion_lineas.append(f"WhatsApp: {telefono}")
        if email_doctor:
            descripcion_lineas.append(f"Email: {email_doctor}")
        if notas:
            descripcion_lineas.append("")
            descripcion_lineas.append("Notas:")
            descripcion_lineas.append(notas)

        descripcion = "\n".join(descripcion_lineas)

        # Crear evento
        evento = {
            "summary": f"🩺 Lapora — Diagnostico con {nombre_doctor}",
            "description": descripcion,
            "start": {
                "dateTime": dt_inicio.isoformat(),
                "timeZone": "America/Bogota",
            },
            "end": {
                "dateTime": dt_fin.isoformat(),
                "timeZone": "America/Bogota",
            },
            "reminders": {
                "useDefault": False,
                "overrides": [
                    {"method": "popup", "minutes": 30},
                    {"method": "email", "minutes": 60},
                ],
            },
        }

        # Agregar invitado si tiene email
        if email_doctor:
            evento["attendees"] = [{"email": email_doctor}]
            # Agregar Google Meet automatico
            evento["conferenceData"] = {
                "createRequest": {
                    "requestId": f"sofia-{int(dt_inicio.timestamp())}",
                    "conferenceSolutionKey": {"type": "hangoutsMeet"},
                }
            }

        service = _obtener_servicio()
        kwargs = {"calendarId": CALENDAR_ID, "body": evento}
        if email_doctor:
            kwargs["conferenceDataVersion"] = 1
            kwargs["sendUpdates"] = "all"  # Envia email a invitados

        evento_creado = service.events().insert(**kwargs).execute()

        link_meet = ""
        if "hangoutLink" in evento_creado:
            link_meet = f"\nEnlace de Google Meet: {evento_creado['hangoutLink']}"

        fecha_legible = dt_inicio.strftime("%A %d de %B a las %I:%M %p")

        return {
            "exito": True,
            "mensaje": (
                f"Cita agendada exitosamente para el {fecha_legible} (Colombia). "
                f"Duracion: {DURATION_MIN} minutos."
                f"{link_meet}"
            ),
            "evento_id": evento_creado.get("id"),
            "link_calendar": evento_creado.get("htmlLink"),
            "link_meet": evento_creado.get("hangoutLink", ""),
        }

    except HttpError as e:
        logger.error(f"Error Google Calendar al agendar: {e}")
        return {
            "exito": False,
            "mensaje": f"Error al crear el evento en el calendario.",
        }
    except Exception as e:
        logger.error(f"Error inesperado agendando cita: {e}", exc_info=True)
        return {
            "exito": False,
            "mensaje": f"Error inesperado: {e}",
        }


def listar_citas_proximas(dias: int = 7) -> dict:
    """
    Lista las citas proximas en los proximos N dias.

    Args:
        dias: cuantos dias hacia adelante mirar (default 7)

    Returns:
        dict con 'exito' y 'citas' (lista)
    """
    try:
        ahora = datetime.now(TIMEZONE)
        hasta = ahora + timedelta(days=dias)

        service = _obtener_servicio()
        eventos = service.events().list(
            calendarId=CALENDAR_ID,
            timeMin=ahora.isoformat(),
            timeMax=hasta.isoformat(),
            singleEvents=True,
            orderBy="startTime",
            maxResults=50,
        ).execute()

        items = eventos.get("items", [])
        citas = []
        for ev in items:
            start = ev.get("start", {}).get("dateTime") or ev.get("start", {}).get("date")
            citas.append({
                "id": ev.get("id"),
                "titulo": ev.get("summary", "Sin titulo"),
                "inicio": start,
                "descripcion": ev.get("description", ""),
            })

        return {
            "exito": True,
            "total": len(citas),
            "citas": citas,
        }

    except Exception as e:
        logger.error(f"Error listando citas: {e}")
        return {
            "exito": False,
            "mensaje": str(e),
            "citas": [],
        }


def cancelar_cita(evento_id: str) -> dict:
    """Cancela una cita por su ID."""
    try:
        service = _obtener_servicio()
        service.events().delete(
            calendarId=CALENDAR_ID,
            eventId=evento_id,
            sendUpdates="all",
        ).execute()
        return {"exito": True, "mensaje": "Cita cancelada exitosamente."}
    except Exception as e:
        logger.error(f"Error cancelando cita: {e}")
        return {"exito": False, "mensaje": str(e)}
