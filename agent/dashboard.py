# -*- coding: utf-8 -*-
# agent/dashboard.py — Dashboard CRM para SofIA
# Generado por AgentKit

"""
Dashboard CRM web para gestionar contactos, conversaciones y leads.

Endpoints:
- GET  /admin/                              -> Redirige a /admin/contactos
- GET  /admin/contactos                     -> Lista de contactos con filtros
- GET  /admin/contactos/{tel}               -> Detalle del contacto + chat
- POST /admin/contactos/{tel}/editar        -> Actualizar contacto
- GET  /admin/conversaciones                -> Lista de conversaciones
- GET  /admin/conversaciones/{tel}          -> Chat estilo WhatsApp
- GET  /admin/api/stats                     -> Stats JSON
- GET  /admin/api/contactos                 -> Contactos JSON (filtrable)
"""

import os
import secrets
from datetime import datetime
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, status, Request, Form
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from sqlalchemy import select, func, or_

from agent.memory import async_session, Mensaje, Contacto

router = APIRouter(prefix="/admin", tags=["admin"])
security = HTTPBasic()

ADMIN_USER = os.getenv("ADMIN_USER", "lapora")
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "lapora-sofia-2026")

# Estados disponibles del lead
ESTADOS = ["nuevo", "contactado", "calificado", "agendado", "cliente", "perdido"]
ESTADOS_COLORES = {
    "nuevo": "#6c757d",
    "contactado": "#0dcaf0",
    "calificado": "#ffc107",
    "agendado": "#fd7e14",
    "cliente": "#198754",
    "perdido": "#dc3545",
}


def verificar_credenciales(credentials: HTTPBasicCredentials = Depends(security)):
    """Valida credenciales basicas."""
    usuario_ok = secrets.compare_digest(credentials.username, ADMIN_USER)
    password_ok = secrets.compare_digest(credentials.password, ADMIN_PASSWORD)
    if not (usuario_ok and password_ok):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Credenciales incorrectas",
            headers={"WWW-Authenticate": "Basic"},
        )
    return credentials.username


# ════════════════════════════════════════════════════════════
# CSS Y LAYOUT COMUNES
# ════════════════════════════════════════════════════════════

CSS_COMUN = """
<style>
    * { margin: 0; padding: 0; box-sizing: border-box; }
    body {
        font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
        background: #f5f5f7;
        color: #1d1d1f;
        min-height: 100vh;
    }
    .header {
        background: linear-gradient(135deg, #ff3b30 0%, #ff6b5e 100%);
        color: white;
        padding: 24px 20px 0;
        box-shadow: 0 2px 10px rgba(0,0,0,0.1);
    }
    .header h1 { font-size: 24px; margin-bottom: 4px; }
    .header p { opacity: 0.9; font-size: 13px; margin-bottom: 16px; }
    .nav-tabs {
        display: flex;
        gap: 4px;
    }
    .nav-tab {
        padding: 10px 20px;
        color: white;
        text-decoration: none;
        opacity: 0.7;
        font-weight: 500;
        border-radius: 6px 6px 0 0;
        transition: all 0.2s;
    }
    .nav-tab:hover { opacity: 1; }
    .nav-tab.active {
        background: #f5f5f7;
        color: #ff3b30;
        opacity: 1;
    }
    .container {
        max-width: 1400px;
        margin: 0 auto;
        padding: 20px;
    }
    .stats {
        display: grid;
        grid-template-columns: repeat(auto-fit, minmax(140px, 1fr));
        gap: 12px;
        margin-bottom: 24px;
    }
    .stat-card {
        background: white;
        padding: 16px;
        border-radius: 10px;
        box-shadow: 0 1px 4px rgba(0,0,0,0.05);
        border-left: 4px solid #ff3b30;
    }
    .stat-card.estado-nuevo { border-color: #6c757d; }
    .stat-card.estado-contactado { border-color: #0dcaf0; }
    .stat-card.estado-calificado { border-color: #ffc107; }
    .stat-card.estado-agendado { border-color: #fd7e14; }
    .stat-card.estado-cliente { border-color: #198754; }
    .stat-card.estado-perdido { border-color: #dc3545; }
    .stat-card .value { font-size: 28px; font-weight: 700; color: #1d1d1f; }
    .stat-card .label { font-size: 11px; color: #666; margin-top: 4px; text-transform: uppercase; letter-spacing: 0.5px; }
    .card {
        background: white;
        border-radius: 12px;
        box-shadow: 0 1px 4px rgba(0,0,0,0.05);
        overflow: hidden;
        margin-bottom: 20px;
    }
    .card-header {
        padding: 16px 20px;
        border-bottom: 1px solid #eee;
        font-size: 16px;
        font-weight: 600;
        display: flex;
        justify-content: space-between;
        align-items: center;
    }
    .filtros {
        display: flex;
        gap: 12px;
        flex-wrap: wrap;
        padding: 16px 20px;
        background: #fafafa;
        border-bottom: 1px solid #eee;
    }
    .filtro-input {
        padding: 8px 12px;
        border: 1px solid #ddd;
        border-radius: 6px;
        font-size: 14px;
        flex: 1;
        min-width: 200px;
    }
    .filtro-select {
        padding: 8px 12px;
        border: 1px solid #ddd;
        border-radius: 6px;
        font-size: 14px;
        background: white;
        cursor: pointer;
    }
    .btn {
        padding: 8px 16px;
        border-radius: 6px;
        font-size: 14px;
        font-weight: 500;
        cursor: pointer;
        text-decoration: none;
        display: inline-block;
        border: none;
        transition: all 0.2s;
    }
    .btn-primary { background: #ff3b30; color: white; }
    .btn-primary:hover { background: #e63227; }
    .btn-outline { background: white; color: #ff3b30; border: 1.5px solid #ff3b30; }
    .btn-outline:hover { background: #ff3b30; color: white; }
    table { width: 100%; border-collapse: collapse; }
    th {
        background: #fafafa;
        padding: 12px 16px;
        text-align: left;
        font-size: 11px;
        text-transform: uppercase;
        color: #666;
        letter-spacing: 0.5px;
        border-bottom: 1px solid #eee;
        font-weight: 600;
    }
    td {
        padding: 14px 16px;
        border-bottom: 1px solid #f5f5f7;
        font-size: 14px;
    }
    .row-link {
        cursor: pointer;
        transition: background 0.15s;
    }
    .row-link:hover { background: #fff5f4; }
    a { color: #ff3b30; text-decoration: none; font-weight: 500; }
    a:hover { text-decoration: underline; }
    .badge {
        display: inline-block;
        padding: 3px 10px;
        border-radius: 12px;
        font-size: 11px;
        font-weight: 600;
        text-transform: uppercase;
        letter-spacing: 0.3px;
        color: white;
    }
    .empty-state {
        text-align: center;
        padding: 60px 20px;
        color: #999;
    }
    .empty-state h3 { color: #666; margin-bottom: 8px; }
</style>
"""


def navegacion_html(activa: str) -> str:
    """Genera la barra de navegacion con tab activa."""
    tabs = [
        ("contactos", "Contactos (CRM)", "/admin/contactos"),
        ("conversaciones", "Conversaciones", "/admin/conversaciones"),
    ]
    nav_links = ""
    for key, label, url in tabs:
        clase = "nav-tab active" if key == activa else "nav-tab"
        nav_links += f'<a href="{url}" class="{clase}">{label}</a>'
    return f'<div class="nav-tabs">{nav_links}</div>'


def badge_estado(estado: str) -> str:
    """Genera badge HTML para un estado."""
    color = ESTADOS_COLORES.get(estado, "#6c757d")
    return f'<span class="badge" style="background:{color}">{estado}</span>'


# ════════════════════════════════════════════════════════════
# ENDPOINTS
# ════════════════════════════════════════════════════════════


@router.get("/")
async def admin_index(user: str = Depends(verificar_credenciales)):
    """Redirige al CRM de contactos."""
    return RedirectResponse(url="/admin/contactos")


@router.get("/api/stats")
async def stats(user: str = Depends(verificar_credenciales)):
    """Stats JSON."""
    async with async_session() as session:
        total_msgs = (await session.execute(select(func.count(Mensaje.id)))).scalar() or 0
        total_convs = (await session.execute(
            select(func.count(func.distinct(Mensaje.telefono)))
        )).scalar() or 0
        total_contactos = (await session.execute(select(func.count(Contacto.telefono)))).scalar() or 0

        # Stats por estado
        stats_estado = {}
        for estado in ESTADOS:
            count = (await session.execute(
                select(func.count(Contacto.telefono)).where(Contacto.estado == estado)
            )).scalar() or 0
            stats_estado[estado] = count

        return {
            "total_mensajes": total_msgs,
            "total_conversaciones": total_convs,
            "total_contactos": total_contactos,
            "por_estado": stats_estado,
        }


@router.get("/contactos", response_class=HTMLResponse)
async def listar_contactos(
    user: str = Depends(verificar_credenciales),
    q: Optional[str] = None,
    estado: Optional[str] = None,
    ciudad: Optional[str] = None,
    especialidad: Optional[str] = None,
    orden: Optional[str] = "ultimo_contacto",
):
    """Lista de contactos con filtros."""
    async with async_session() as session:
        # Construir query con filtros
        query = select(Contacto)

        if q:
            q_pattern = f"%{q}%"
            query = query.where(
                or_(
                    Contacto.telefono.ilike(q_pattern),
                    Contacto.nombre.ilike(q_pattern),
                    Contacto.email.ilike(q_pattern),
                )
            )

        if estado and estado != "todos":
            query = query.where(Contacto.estado == estado)

        if ciudad and ciudad != "todas":
            query = query.where(Contacto.ciudad == ciudad)

        if especialidad and especialidad != "todas":
            query = query.where(Contacto.especialidad == especialidad)

        # Ordenamiento
        if orden == "primer_contacto":
            query = query.order_by(Contacto.primer_contacto.desc())
        elif orden == "nombre":
            query = query.order_by(Contacto.nombre.asc())
        elif orden == "total_mensajes":
            query = query.order_by(Contacto.total_mensajes.desc())
        else:
            query = query.order_by(Contacto.ultimo_contacto.desc())

        result = await session.execute(query)
        contactos = result.scalars().all()

        # Listas para filtros
        ciudades_query = await session.execute(
            select(Contacto.ciudad).distinct().where(Contacto.ciudad != "").where(Contacto.ciudad != None)
        )
        ciudades = sorted([c for c in ciudades_query.scalars().all() if c])

        esp_query = await session.execute(
            select(Contacto.especialidad).distinct().where(Contacto.especialidad != "").where(Contacto.especialidad != None)
        )
        especialidades = sorted([e for e in esp_query.scalars().all() if e])

        # Stats
        total_contactos = (await session.execute(select(func.count(Contacto.telefono)))).scalar() or 0
        stats_estado = {}
        for est in ESTADOS:
            count = (await session.execute(
                select(func.count(Contacto.telefono)).where(Contacto.estado == est)
            )).scalar() or 0
            stats_estado[est] = count

    # Render
    stats_html = '<div class="stats">'
    stats_html += f'<div class="stat-card"><div class="value">{total_contactos}</div><div class="label">TOTAL CONTACTOS</div></div>'
    for est in ESTADOS:
        count = stats_estado.get(est, 0)
        stats_html += f'<div class="stat-card estado-{est}"><div class="value">{count}</div><div class="label">{est}</div></div>'
    stats_html += '</div>'

    # Filtros HTML
    opt_estado = '<option value="todos">Todos los estados</option>'
    for e in ESTADOS:
        sel = " selected" if e == estado else ""
        opt_estado += f'<option value="{e}"{sel}>{e.title()}</option>'

    opt_ciudad = '<option value="todas">Todas las ciudades</option>'
    for c in ciudades:
        sel = " selected" if c == ciudad else ""
        opt_ciudad += f'<option value="{c}"{sel}>{c}</option>'

    opt_esp = '<option value="todas">Todas las especialidades</option>'
    for e in especialidades:
        sel = " selected" if e == especialidad else ""
        opt_esp += f'<option value="{e}"{sel}>{e}</option>'

    opt_orden = ""
    ordenes = [
        ("ultimo_contacto", "Ultimo contacto"),
        ("primer_contacto", "Primer contacto"),
        ("nombre", "Nombre A-Z"),
        ("total_mensajes", "Mas mensajes"),
    ]
    for val, lab in ordenes:
        sel = " selected" if val == orden else ""
        opt_orden += f'<option value="{val}"{sel}>{lab}</option>'

    q_val = q or ""
    filtros_html = f"""
    <form method="get" class="filtros">
        <input type="text" name="q" value="{q_val}" placeholder="Buscar por nombre, telefono o email..." class="filtro-input">
        <select name="estado" class="filtro-select">{opt_estado}</select>
        <select name="ciudad" class="filtro-select">{opt_ciudad}</select>
        <select name="especialidad" class="filtro-select">{opt_esp}</select>
        <select name="orden" class="filtro-select">{opt_orden}</select>
        <button type="submit" class="btn btn-primary">Filtrar</button>
        <a href="/admin/contactos" class="btn btn-outline">Limpiar</a>
    </form>
    """

    # Filas
    rows = ""
    for c in contactos:
        nombre = c.nombre or "Sin nombre"
        email = c.email or "—"
        ciudad_v = c.ciudad or "—"
        esp_v = c.especialidad or "—"
        ultimo = c.ultimo_contacto.strftime("%d/%m/%y %H:%M") if c.ultimo_contacto else "—"
        rows += f"""
        <tr class="row-link" onclick="window.location='/admin/contactos/{c.telefono}'">
            <td><strong>{nombre}</strong></td>
            <td>{c.telefono}</td>
            <td>{email}</td>
            <td>{esp_v}</td>
            <td>{ciudad_v}</td>
            <td>{badge_estado(c.estado or "nuevo")}</td>
            <td style="text-align:center">{c.total_mensajes or 0}</td>
            <td style="text-align:center">{c.citas_agendadas or 0}</td>
            <td>{ultimo}</td>
        </tr>
        """

    if not rows:
        rows = '<tr><td colspan="9" class="empty-state"><h3>Sin contactos</h3><p>No hay contactos que coincidan con los filtros.</p></td></tr>'

    html = f"""<!DOCTYPE html>
<html lang="es">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>CRM Contactos - SofIA Lapora</title>
    {CSS_COMUN}
</head>
<body>
    <div class="header">
        <h1>CRM SofIA - Contactos</h1>
        <p>Base de datos de leads y clientes de Lapora Marketing Digital</p>
        {navegacion_html("contactos")}
    </div>
    <div class="container">
        {stats_html}
        <div class="card">
            <div class="card-header">
                Contactos ({len(contactos)})
                <button class="btn btn-outline" onclick="location.reload()">Actualizar</button>
            </div>
            {filtros_html}
            <table>
                <thead>
                    <tr>
                        <th>Nombre</th>
                        <th>Telefono</th>
                        <th>Email</th>
                        <th>Especialidad</th>
                        <th>Ciudad</th>
                        <th>Estado</th>
                        <th style="text-align:center">Msgs</th>
                        <th style="text-align:center">Citas</th>
                        <th>Ultimo</th>
                    </tr>
                </thead>
                <tbody>{rows}</tbody>
            </table>
        </div>
    </div>
</body>
</html>"""
    return HTMLResponse(content=html)


@router.get("/contactos/{telefono}", response_class=HTMLResponse)
async def detalle_contacto(telefono: str, user: str = Depends(verificar_credenciales)):
    """Vista detalle de un contacto."""
    async with async_session() as session:
        contacto = (await session.execute(
            select(Contacto).where(Contacto.telefono == telefono)
        )).scalar_one_or_none()

        if contacto is None:
            return HTMLResponse(f"<h1>Contacto {telefono} no encontrado</h1>", status_code=404)

        # Cargar mensajes
        mensajes_query = await session.execute(
            select(Mensaje).where(Mensaje.telefono == telefono).order_by(Mensaje.timestamp.asc())
        )
        mensajes = mensajes_query.scalars().all()

    # Opciones de estado
    opt_estado = ""
    for e in ESTADOS:
        sel = " selected" if e == contacto.estado else ""
        opt_estado += f'<option value="{e}"{sel}>{e.title()}</option>'

    # Formulario de edicion
    form_html = f"""
    <form method="post" action="/admin/contactos/{telefono}/editar" style="padding:20px">
        <div style="display:grid;grid-template-columns:1fr 1fr;gap:16px;margin-bottom:16px">
            <div>
                <label style="display:block;font-size:12px;color:#666;text-transform:uppercase;margin-bottom:4px">Nombre</label>
                <input type="text" name="nombre" value="{contacto.nombre or ''}" class="filtro-input" style="width:100%">
            </div>
            <div>
                <label style="display:block;font-size:12px;color:#666;text-transform:uppercase;margin-bottom:4px">Email</label>
                <input type="email" name="email" value="{contacto.email or ''}" class="filtro-input" style="width:100%">
            </div>
            <div>
                <label style="display:block;font-size:12px;color:#666;text-transform:uppercase;margin-bottom:4px">Especialidad</label>
                <input type="text" name="especialidad" value="{contacto.especialidad or ''}" class="filtro-input" style="width:100%">
            </div>
            <div>
                <label style="display:block;font-size:12px;color:#666;text-transform:uppercase;margin-bottom:4px">Ciudad</label>
                <input type="text" name="ciudad" value="{contacto.ciudad or ''}" class="filtro-input" style="width:100%">
            </div>
            <div>
                <label style="display:block;font-size:12px;color:#666;text-transform:uppercase;margin-bottom:4px">Volumen pacientes/mes</label>
                <input type="text" name="volumen_pacientes" value="{contacto.volumen_pacientes or ''}" class="filtro-input" style="width:100%">
            </div>
            <div>
                <label style="display:block;font-size:12px;color:#666;text-transform:uppercase;margin-bottom:4px">Presencia digital</label>
                <input type="text" name="presencia_digital" value="{contacto.presencia_digital or ''}" class="filtro-input" style="width:100%">
            </div>
            <div>
                <label style="display:block;font-size:12px;color:#666;text-transform:uppercase;margin-bottom:4px">Perdida mensual estimada</label>
                <input type="text" name="perdida_mensual" value="{contacto.perdida_mensual or ''}" class="filtro-input" style="width:100%">
            </div>
            <div>
                <label style="display:block;font-size:12px;color:#666;text-transform:uppercase;margin-bottom:4px">Estado</label>
                <select name="estado" class="filtro-select" style="width:100%">{opt_estado}</select>
            </div>
        </div>
        <div style="margin-bottom:16px">
            <label style="display:block;font-size:12px;color:#666;text-transform:uppercase;margin-bottom:4px">Reto principal</label>
            <textarea name="reto_principal" rows="2" class="filtro-input" style="width:100%;resize:vertical">{contacto.reto_principal or ''}</textarea>
        </div>
        <div style="margin-bottom:16px">
            <label style="display:block;font-size:12px;color:#666;text-transform:uppercase;margin-bottom:4px">Tags (separados por coma)</label>
            <input type="text" name="tags" value="{contacto.tags or ''}" placeholder="vip, dermatologia, ibague" class="filtro-input" style="width:100%">
        </div>
        <div style="margin-bottom:16px">
            <label style="display:block;font-size:12px;color:#666;text-transform:uppercase;margin-bottom:4px">Notas internas</label>
            <textarea name="notas" rows="4" class="filtro-input" style="width:100%;resize:vertical">{contacto.notas or ''}</textarea>
        </div>
        <button type="submit" class="btn btn-primary">Guardar cambios</button>
    </form>
    """

    # Conversacion (preview ultimos 10 mensajes)
    chat_html = ""
    msgs_recientes = list(mensajes)[-10:] if len(mensajes) > 10 else list(mensajes)
    for m in msgs_recientes:
        autor = "Cliente" if m.role == "user" else "SofIA"
        emoji = "&#128100;" if m.role == "user" else "&#129302;"
        contenido = (m.content or "").replace("\n", "<br>")
        timestamp = m.timestamp.strftime("%d/%m %H:%M") if m.timestamp else ""
        bg = "#DCF8C6" if m.role == "user" else "#fff"
        chat_html += f"""
        <div style="margin-bottom:10px;padding:10px;background:{bg};border-radius:8px">
            <div style="font-size:11px;color:#666;margin-bottom:4px">{emoji} {autor} - {timestamp}</div>
            <div style="font-size:13px">{contenido}</div>
        </div>
        """
    if not chat_html:
        chat_html = '<p style="color:#999;padding:20px">Sin mensajes</p>'

    fecha_primer = contacto.primer_contacto.strftime("%d/%m/%Y %H:%M") if contacto.primer_contacto else "—"
    fecha_ultimo = contacto.ultimo_contacto.strftime("%d/%m/%Y %H:%M") if contacto.ultimo_contacto else "—"

    html = f"""<!DOCTYPE html>
<html lang="es">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{contacto.nombre or contacto.telefono} - CRM SofIA</title>
    {CSS_COMUN}
</head>
<body>
    <div class="header">
        <h1>{contacto.nombre or "Sin nombre"}</h1>
        <p>{contacto.telefono} - {badge_estado(contacto.estado or "nuevo")} - Primer contacto: {fecha_primer}</p>
        {navegacion_html("contactos")}
    </div>
    <div class="container">
        <a href="/admin/contactos" class="btn btn-outline" style="margin-bottom:16px">&larr; Volver al CRM</a>

        <div style="display:grid;grid-template-columns:2fr 1fr;gap:20px">
            <div class="card">
                <div class="card-header">Datos del contacto</div>
                {form_html}
            </div>

            <div>
                <div class="card">
                    <div class="card-header">Resumen</div>
                    <div style="padding:20px">
                        <p style="margin-bottom:8px"><strong>Total mensajes:</strong> {contacto.total_mensajes or 0}</p>
                        <p style="margin-bottom:8px"><strong>Citas agendadas:</strong> {contacto.citas_agendadas or 0}</p>
                        <p style="margin-bottom:8px"><strong>Fuente:</strong> {contacto.fuente or "—"}</p>
                        <p style="margin-bottom:8px"><strong>Ultimo mensaje:</strong> {fecha_ultimo}</p>
                        <p><a href="/admin/conversaciones/{contacto.telefono}" class="btn btn-outline" style="margin-top:12px">Ver chat completo &rarr;</a></p>
                    </div>
                </div>

                <div class="card">
                    <div class="card-header">Ultimos mensajes</div>
                    <div style="padding:16px;max-height:400px;overflow-y:auto">
                        {chat_html}
                    </div>
                </div>
            </div>
        </div>
    </div>
</body>
</html>"""
    return HTMLResponse(content=html)


@router.post("/contactos/{telefono}/editar")
async def editar_contacto(
    telefono: str,
    nombre: str = Form(""),
    email: str = Form(""),
    especialidad: str = Form(""),
    ciudad: str = Form(""),
    volumen_pacientes: str = Form(""),
    presencia_digital: str = Form(""),
    perdida_mensual: str = Form(""),
    reto_principal: str = Form(""),
    estado: str = Form("nuevo"),
    tags: str = Form(""),
    notas: str = Form(""),
    user: str = Depends(verificar_credenciales),
):
    """Actualiza los datos de un contacto."""
    async with async_session() as session:
        contacto = (await session.execute(
            select(Contacto).where(Contacto.telefono == telefono)
        )).scalar_one_or_none()

        if contacto is None:
            raise HTTPException(status_code=404, detail="Contacto no encontrado")

        contacto.nombre = nombre
        contacto.email = email
        contacto.especialidad = especialidad
        contacto.ciudad = ciudad
        contacto.volumen_pacientes = volumen_pacientes
        contacto.presencia_digital = presencia_digital
        contacto.perdida_mensual = perdida_mensual
        contacto.reto_principal = reto_principal
        contacto.estado = estado
        contacto.tags = tags
        contacto.notas = notas

        await session.commit()

    return RedirectResponse(url=f"/admin/contactos/{telefono}", status_code=303)


# ════════════════════════════════════════════════════════════
# CONVERSACIONES (mantiene funcionalidad anterior)
# ════════════════════════════════════════════════════════════

@router.get("/conversaciones", response_class=HTMLResponse)
async def listar_conversaciones(user: str = Depends(verificar_credenciales)):
    """Lista de conversaciones agrupadas por telefono."""
    async with async_session() as session:
        result = await session.execute(
            select(
                Mensaje.telefono,
                func.count(Mensaje.id).label("total"),
                func.max(Mensaje.timestamp).label("ultimo"),
            )
            .group_by(Mensaje.telefono)
            .order_by(func.max(Mensaje.timestamp).desc())
        )
        conversaciones = result.all()

        total_msgs = (await session.execute(select(func.count(Mensaje.id)))).scalar() or 0
        total_convs = len(conversaciones)

    rows = ""
    for c in conversaciones:
        ultimo = c.ultimo.strftime("%d/%m/%Y %H:%M") if c.ultimo else "N/A"
        rows += f"""
        <tr class="row-link" onclick="window.location='/admin/conversaciones/{c.telefono}'">
            <td><strong>{c.telefono}</strong></td>
            <td>{c.total}</td>
            <td>{ultimo}</td>
            <td><a href="/admin/conversaciones/{c.telefono}">Ver &rarr;</a></td>
        </tr>
        """
    if not rows:
        rows = '<tr><td colspan="4" class="empty-state"><h3>Sin conversaciones</h3></td></tr>'

    html = f"""<!DOCTYPE html>
<html lang="es">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Conversaciones - SofIA</title>
    {CSS_COMUN}
</head>
<body>
    <div class="header">
        <h1>SofIA - Conversaciones</h1>
        <p>Historial de chats de WhatsApp</p>
        {navegacion_html("conversaciones")}
    </div>
    <div class="container">
        <div class="stats">
            <div class="stat-card"><div class="value">{total_convs}</div><div class="label">CONVERSACIONES</div></div>
            <div class="stat-card"><div class="value">{total_msgs}</div><div class="label">MENSAJES TOTALES</div></div>
        </div>
        <div class="card">
            <div class="card-header">
                Lista de Conversaciones
                <button class="btn btn-outline" onclick="location.reload()">Actualizar</button>
            </div>
            <table>
                <thead><tr><th>Telefono</th><th>Mensajes</th><th>Ultimo mensaje</th><th>Accion</th></tr></thead>
                <tbody>{rows}</tbody>
            </table>
        </div>
    </div>
</body>
</html>"""
    return HTMLResponse(content=html)


@router.get("/conversaciones/{telefono}", response_class=HTMLResponse)
async def ver_conversacion(telefono: str, user: str = Depends(verificar_credenciales)):
    """Chat estilo WhatsApp."""
    async with async_session() as session:
        result = await session.execute(
            select(Mensaje).where(Mensaje.telefono == telefono).order_by(Mensaje.timestamp.asc())
        )
        mensajes = result.scalars().all()

    if not mensajes:
        return HTMLResponse(f"<h1>Conversacion {telefono} no encontrada</h1>", status_code=404)

    chat = ""
    for m in mensajes:
        clase = "msg-user" if m.role == "user" else "msg-bot"
        autor = "Cliente" if m.role == "user" else "SofIA"
        contenido = (m.content or "").replace("\n", "<br>")
        ts = m.timestamp.strftime("%d/%m/%Y %H:%M:%S")
        chat += f"""
        <div class="message {clase}">
            <div class="bubble">
                <div class="author">{autor}</div>
                <div class="content">{contenido}</div>
                <div class="time">{ts}</div>
            </div>
        </div>"""

    html = f"""<!DOCTYPE html>
<html lang="es">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Chat {telefono} - SofIA</title>
    {CSS_COMUN}
    <style>
        body {{ background: #ECE5DD; }}
        .chat-container {{ max-width:800px; margin:0 auto; padding:20px; }}
        .message {{ display:flex; margin-bottom:12px; }}
        .msg-user {{ justify-content:flex-end; }}
        .msg-bot {{ justify-content:flex-start; }}
        .bubble {{ max-width:70%; padding:12px 16px; border-radius:12px; box-shadow:0 1px 2px rgba(0,0,0,0.1); }}
        .msg-user .bubble {{ background:#DCF8C6; border-bottom-right-radius:2px; }}
        .msg-bot .bubble {{ background:white; border-bottom-left-radius:2px; }}
        .author {{ font-size:12px; font-weight:600; color:#ff3b30; margin-bottom:4px; }}
        .msg-user .author {{ color:#25D366; }}
        .content {{ font-size:14px; line-height:1.4; word-wrap:break-word; }}
        .time {{ font-size:11px; color:#999; margin-top:4px; text-align:right; }}
    </style>
</head>
<body>
    <div class="header">
        <h1>{telefono}</h1>
        <p>Chat completo - SofIA Lapora</p>
        {navegacion_html("conversaciones")}
    </div>
    <div class="chat-container">
        <a href="/admin/contactos/{telefono}" class="btn btn-outline" style="margin-bottom:16px">Ver ficha del contacto</a>
        {chat}
    </div>
</body>
</html>"""
    return HTMLResponse(content=html)
