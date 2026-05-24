# -*- coding: utf-8 -*-
# agent/dashboard.py — Dashboard web para ver conversaciones de SofIA
# Generado por AgentKit

"""
Dashboard web protegido para visualizar todas las conversaciones de SofIA.

Endpoints:
- GET /admin/conversaciones        → Lista de conversaciones
- GET /admin/conversaciones/{tel}  → Detalle de una conversacion
- GET /admin/api/stats             → Estadisticas en JSON
"""

import os
import secrets
from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException, status, Request
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from fastapi.responses import HTMLResponse, JSONResponse
from sqlalchemy import select, func

from agent.memory import async_session, Mensaje

router = APIRouter(prefix="/admin", tags=["admin"])
security = HTTPBasic()

# Credenciales del dashboard (configurables via .env)
ADMIN_USER = os.getenv("ADMIN_USER", "lapora")
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "lapora-sofia-2026")


def verificar_credenciales(credentials: HTTPBasicCredentials = Depends(security)):
    """Valida las credenciales basicas de acceso al dashboard."""
    usuario_correcto = secrets.compare_digest(credentials.username, ADMIN_USER)
    password_correcto = secrets.compare_digest(credentials.password, ADMIN_PASSWORD)

    if not (usuario_correcto and password_correcto):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Credenciales incorrectas",
            headers={"WWW-Authenticate": "Basic"},
        )
    return credentials.username


@router.get("/api/stats")
async def stats(user: str = Depends(verificar_credenciales)):
    """Devuelve estadisticas en JSON."""
    async with async_session() as session:
        total = (await session.execute(select(func.count(Mensaje.id)))).scalar() or 0
        conversaciones = (await session.execute(
            select(func.count(func.distinct(Mensaje.telefono)))
        )).scalar() or 0
        mensajes_user = (await session.execute(
            select(func.count(Mensaje.id)).where(Mensaje.role == "user")
        )).scalar() or 0
        mensajes_bot = (await session.execute(
            select(func.count(Mensaje.id)).where(Mensaje.role == "assistant")
        )).scalar() or 0

        return {
            "total_mensajes": total,
            "total_conversaciones": conversaciones,
            "mensajes_usuario": mensajes_user,
            "mensajes_sofia": mensajes_bot,
        }


@router.get("/conversaciones", response_class=HTMLResponse)
async def listar_conversaciones(request: Request, user: str = Depends(verificar_credenciales)):
    """Lista todas las conversaciones agrupadas por telefono."""
    async with async_session() as session:
        # Obtener todos los telefonos con su ultimo mensaje
        resultado = await session.execute(
            select(
                Mensaje.telefono,
                func.count(Mensaje.id).label("total"),
                func.max(Mensaje.timestamp).label("ultimo"),
            )
            .group_by(Mensaje.telefono)
            .order_by(func.max(Mensaje.timestamp).desc())
        )
        conversaciones = resultado.all()

        # Stats
        total_msgs = (await session.execute(select(func.count(Mensaje.id)))).scalar() or 0
        total_convs = len(conversaciones)

    # Generar HTML
    rows_html = ""
    for conv in conversaciones:
        ultimo = conv.ultimo.strftime("%d/%m/%Y %H:%M") if conv.ultimo else "N/A"
        rows_html += f"""
        <tr onclick="window.location='/admin/conversaciones/{conv.telefono}'" class="conv-row">
            <td><strong>{conv.telefono}</strong></td>
            <td>{conv.total}</td>
            <td>{ultimo}</td>
            <td><a href="/admin/conversaciones/{conv.telefono}">Ver →</a></td>
        </tr>
        """

    if not rows_html:
        rows_html = '<tr><td colspan="4" style="text-align:center; padding:40px; color:#999;">Aun no hay conversaciones</td></tr>'

    html = f"""<!DOCTYPE html>
<html lang="es">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Conversaciones - SofIA Lapora</title>
    <style>
        * {{ margin: 0; padding: 0; box-sizing: border-box; }}
        body {{
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
            background: #f5f5f7;
            color: #1d1d1f;
            min-height: 100vh;
        }}
        .header {{
            background: linear-gradient(135deg, #ff3b30 0%, #ff6b5e 100%);
            color: white;
            padding: 30px 20px;
            box-shadow: 0 2px 10px rgba(0,0,0,0.1);
        }}
        .header h1 {{ font-size: 28px; margin-bottom: 5px; }}
        .header p {{ opacity: 0.9; font-size: 14px; }}
        .container {{
            max-width: 1200px;
            margin: 0 auto;
            padding: 20px;
        }}
        .stats {{
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
            gap: 15px;
            margin-bottom: 30px;
        }}
        .stat-card {{
            background: white;
            padding: 20px;
            border-radius: 12px;
            box-shadow: 0 2px 8px rgba(0,0,0,0.05);
        }}
        .stat-card .value {{
            font-size: 32px;
            font-weight: 700;
            color: #ff3b30;
        }}
        .stat-card .label {{
            font-size: 13px;
            color: #666;
            margin-top: 5px;
        }}
        .table-container {{
            background: white;
            border-radius: 12px;
            overflow: hidden;
            box-shadow: 0 2px 8px rgba(0,0,0,0.05);
        }}
        .table-header {{
            padding: 20px;
            border-bottom: 1px solid #eee;
            font-size: 18px;
            font-weight: 600;
        }}
        table {{
            width: 100%;
            border-collapse: collapse;
        }}
        th {{
            background: #fafafa;
            padding: 12px 20px;
            text-align: left;
            font-size: 12px;
            text-transform: uppercase;
            color: #666;
            letter-spacing: 0.5px;
            border-bottom: 1px solid #eee;
        }}
        td {{
            padding: 16px 20px;
            border-bottom: 1px solid #f5f5f7;
        }}
        .conv-row {{
            cursor: pointer;
            transition: background 0.2s;
        }}
        .conv-row:hover {{
            background: #fff5f4;
        }}
        a {{
            color: #ff3b30;
            text-decoration: none;
            font-weight: 500;
        }}
        a:hover {{ text-decoration: underline; }}
        .refresh-btn {{
            background: white;
            color: #ff3b30;
            border: 2px solid #ff3b30;
            padding: 8px 16px;
            border-radius: 8px;
            font-weight: 600;
            cursor: pointer;
            float: right;
            margin-top: -5px;
        }}
        .refresh-btn:hover {{
            background: #ff3b30;
            color: white;
        }}
    </style>
</head>
<body>
    <div class="header">
        <h1>SofIA - Conversaciones</h1>
        <p>Dashboard de conversaciones de WhatsApp - Lapora Marketing Digital</p>
    </div>
    <div class="container">
        <div class="stats">
            <div class="stat-card">
                <div class="value">{total_convs}</div>
                <div class="label">CONVERSACIONES</div>
            </div>
            <div class="stat-card">
                <div class="value">{total_msgs}</div>
                <div class="label">MENSAJES TOTALES</div>
            </div>
        </div>

        <div class="table-container">
            <div class="table-header">
                Lista de Conversaciones
                <button class="refresh-btn" onclick="location.reload()">Actualizar</button>
            </div>
            <table>
                <thead>
                    <tr>
                        <th>Telefono</th>
                        <th>Mensajes</th>
                        <th>Ultimo mensaje</th>
                        <th>Accion</th>
                    </tr>
                </thead>
                <tbody>
                    {rows_html}
                </tbody>
            </table>
        </div>
    </div>
</body>
</html>"""

    return HTMLResponse(content=html)


@router.get("/conversaciones/{telefono}", response_class=HTMLResponse)
async def ver_conversacion(telefono: str, user: str = Depends(verificar_credenciales)):
    """Muestra el detalle completo de una conversacion."""
    async with async_session() as session:
        resultado = await session.execute(
            select(Mensaje)
            .where(Mensaje.telefono == telefono)
            .order_by(Mensaje.timestamp.asc())
        )
        mensajes = resultado.scalars().all()

    if not mensajes:
        return HTMLResponse("<h1>Conversacion no encontrada</h1>", status_code=404)

    # Generar burbujas de chat
    chat_html = ""
    for msg in mensajes:
        timestamp = msg.timestamp.strftime("%d/%m/%Y %H:%M:%S")
        clase = "msg-user" if msg.role == "user" else "msg-bot"
        autor = "Cliente" if msg.role == "user" else "SofIA"
        contenido = msg.content.replace("\n", "<br>")

        chat_html += f"""
        <div class="message {clase}">
            <div class="bubble">
                <div class="author">{autor}</div>
                <div class="content">{contenido}</div>
                <div class="time">{timestamp}</div>
            </div>
        </div>
        """

    html = f"""<!DOCTYPE html>
<html lang="es">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Conversacion {telefono} - SofIA</title>
    <style>
        * {{ margin: 0; padding: 0; box-sizing: border-box; }}
        body {{
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
            background: #ECE5DD;
            color: #1d1d1f;
            min-height: 100vh;
        }}
        .header {{
            background: linear-gradient(135deg, #ff3b30 0%, #ff6b5e 100%);
            color: white;
            padding: 20px;
            box-shadow: 0 2px 10px rgba(0,0,0,0.1);
            position: sticky;
            top: 0;
            z-index: 100;
        }}
        .header h1 {{ font-size: 20px; margin-bottom: 5px; }}
        .header a {{
            color: white;
            opacity: 0.9;
            text-decoration: none;
            font-size: 14px;
        }}
        .header a:hover {{ opacity: 1; }}
        .chat-container {{
            max-width: 800px;
            margin: 0 auto;
            padding: 20px;
        }}
        .message {{
            display: flex;
            margin-bottom: 12px;
        }}
        .msg-user {{ justify-content: flex-end; }}
        .msg-bot {{ justify-content: flex-start; }}
        .bubble {{
            max-width: 70%;
            padding: 12px 16px;
            border-radius: 12px;
            box-shadow: 0 1px 2px rgba(0,0,0,0.1);
        }}
        .msg-user .bubble {{
            background: #DCF8C6;
            border-bottom-right-radius: 2px;
        }}
        .msg-bot .bubble {{
            background: white;
            border-bottom-left-radius: 2px;
        }}
        .author {{
            font-size: 12px;
            font-weight: 600;
            color: #ff3b30;
            margin-bottom: 4px;
        }}
        .msg-user .author {{ color: #25D366; }}
        .content {{
            font-size: 14px;
            line-height: 1.4;
            color: #1d1d1f;
            word-wrap: break-word;
        }}
        .time {{
            font-size: 11px;
            color: #999;
            margin-top: 4px;
            text-align: right;
        }}
    </style>
</head>
<body>
    <div class="header">
        <h1>{telefono}</h1>
        <a href="/admin/conversaciones">← Volver a conversaciones</a>
    </div>
    <div class="chat-container">
        {chat_html}
    </div>
</body>
</html>"""

    return HTMLResponse(content=html)
