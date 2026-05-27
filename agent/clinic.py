# -*- coding: utf-8 -*-
# agent/clinic.py — Router de Lapora Clinic (SaaS multi-tenant)
# Lapora Marketing Digital

"""
Rutas del producto SaaS Lapora Clinic — separado del CRM interno de SofIA.

URLs publicas:
  /clinic/                  → landing redirige a login
  /clinic/registro          → onboarding (crear nueva clinica)
  /clinic/login             → login de clinica existente

URLs privadas (requieren sesion):
  /clinic/app/              → dashboard
  /clinic/app/inbox         → inbox unificado WhatsApp+IG+Email
  /clinic/app/pacientes     → CRUD de pacientes
  /clinic/app/llamadas      → bitacora de llamadas
  /clinic/app/plantillas    → respuestas rapidas
  /clinic/app/configuracion → integraciones (WhatsApp, IG, Sheets)
"""

import html
import secrets
from datetime import datetime
from typing import Optional
from fastapi import APIRouter, Depends, Request, Form, HTTPException, Cookie, UploadFile, File
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import select, func, or_, desc

from agent.memory import async_session
from agent.clinic_models import (
    Clinica, UsuarioClinic, Paciente, MensajeUnificado,
    Llamada, CitaClinic, PlantillaRespuesta,
    crear_clinica, autenticar_usuario, obtener_clinica,
    cargar_demo_data,
)
from io import StringIO
import csv as _csv_mod


router = APIRouter(prefix="/clinic", tags=["clinic"])

# Sesiones en memoria (MVP — para prod usar Redis o DB)
# session_token → {usuario_id, clinica_id, expira}
SESSIONS: dict[str, dict] = {}


# ════════════════════════════════════════════════════════════
# Helpers de sesion
# ════════════════════════════════════════════════════════════

def crear_sesion(usuario: UsuarioClinic) -> str:
    """Crea token de sesion y lo registra."""
    token = secrets.token_urlsafe(32)
    SESSIONS[token] = {
        "usuario_id": usuario.id,
        "clinica_id": usuario.clinica_id,
        "email": usuario.email,
        "nombre": usuario.nombre,
        "rol": usuario.rol,
    }
    return token


def obtener_sesion(token: Optional[str]) -> Optional[dict]:
    if not token or token not in SESSIONS:
        return None
    return SESSIONS[token]


async def requerir_login(clinic_session: Optional[str] = Cookie(None)) -> dict:
    """Dependency que valida sesion activa. Si no, lanza 401."""
    sesion = obtener_sesion(clinic_session)
    if not sesion:
        raise HTTPException(
            status_code=302,
            detail="No autenticado",
            headers={"Location": "/clinic/login"},
        )
    return sesion


# ════════════════════════════════════════════════════════════
# CSS / Estilos compartidos
# ════════════════════════════════════════════════════════════

CSS_CLINIC = """
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&display=swap" rel="stylesheet">
<style>
  *, *::before, *::after { margin:0; padding:0; box-sizing:border-box; }
  :root {
    --primary: #FF3B30;
    --primary-dark: #E63227;
    --primary-light: #FFF1F0;
    --bg: #FAFAF9;
    --card: #FFFFFF;
    --text: #1C1917;
    --text-soft: #78716C;
    --border: #E7E5E4;
    --green: #10B981;
    --blue: #3B82F6;
    --shadow: 0 1px 3px rgba(0,0,0,0.05), 0 1px 2px rgba(0,0,0,0.03);
    --shadow-lg: 0 20px 40px rgba(0,0,0,0.08);
  }
  body {
    font-family: 'Inter', sans-serif;
    background: var(--bg);
    color: var(--text);
    font-size: 14px;
    line-height: 1.5;
    -webkit-font-smoothing: antialiased;
  }
  a { color: var(--primary); text-decoration: none; }
  a:hover { color: var(--primary-dark); }
  .btn {
    display: inline-flex; align-items: center; gap: 8px;
    padding: 12px 22px; border-radius: 10px;
    font-size: 14px; font-weight: 600;
    border: none; cursor: pointer; text-decoration: none;
    transition: all 0.15s;
  }
  .btn-primary {
    background: var(--primary); color: white;
    box-shadow: 0 4px 12px rgba(255,59,48,0.25);
  }
  .btn-primary:hover { background: var(--primary-dark); color: white; transform: translateY(-1px); }
  .btn-ghost { background: transparent; color: var(--text); border: 1.5px solid var(--border); }
  .btn-ghost:hover { border-color: var(--text); }
  .card {
    background: var(--card); border: 1px solid var(--border);
    border-radius: 14px; padding: 24px; box-shadow: var(--shadow);
  }
  .input {
    width: 100%; padding: 12px 14px;
    border: 1.5px solid var(--border); border-radius: 10px;
    font-size: 14px; font-family: inherit; outline: none;
    transition: border-color 0.15s;
  }
  .input:focus { border-color: var(--primary); }

  /* Layout app */
  .app-wrap { display: grid; grid-template-columns: 240px 1fr; min-height: 100vh; }
  .sidebar {
    background: white; border-right: 1px solid var(--border);
    padding: 20px 14px; display: flex; flex-direction: column;
  }
  .brand {
    display: flex; align-items: center; gap: 10px;
    padding: 4px 8px 18px; border-bottom: 1px solid var(--border);
  }
  .brand-logo {
    width: 34px; height: 34px; background: var(--primary);
    border-radius: 10px; color: white; font-weight: 800; font-size: 16px;
    display: flex; align-items: center; justify-content: center;
    box-shadow: 0 4px 10px rgba(255,59,48,0.25);
  }
  .brand-name { font-weight: 800; font-size: 15px; }
  .brand-sub { font-size: 11px; color: var(--text-soft); }
  .nav-item {
    display: flex; align-items: center; gap: 10px;
    padding: 9px 12px; border-radius: 9px;
    color: var(--text-soft); font-weight: 500;
    margin-bottom: 3px; transition: all 0.15s;
  }
  .nav-item:hover { background: var(--bg); color: var(--text); }
  .nav-item.active { background: var(--primary-light); color: var(--primary); font-weight: 600; }
  .main { padding: 28px 36px; min-width: 0; }
  .badge {
    display: inline-block; padding: 3px 10px;
    border-radius: 999px; font-size: 11px; font-weight: 700;
  }
  .badge-free { background: #f5f5f4; color: var(--text-soft); }
  .badge-pro { background: #ECFDF5; color: var(--green); }
  .badge-studio { background: #EFF6FF; color: var(--blue); }
</style>
"""


def sidebar_clinic(activa: str, sesion: dict, clinica: Clinica) -> str:
    """Sidebar de la app del SaaS."""
    items = [
        ("dashboard", "Dashboard",  "/clinic/app/",            "M3 12h2l2-7 4 14 4-7 2 0"),
        ("inbox",     "Inbox",      "/clinic/app/inbox",       "M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"),
        ("pacientes", "Pacientes",  "/clinic/app/pacientes",   "M17 21v-2a4 4 0 0 0-4-4H5a4 4 0 0 0-4 4v2 M12 7a4 4 0 1 1-8 0 4 4 0 0 1 8 0z"),
        ("llamadas",  "Llamadas",   "/clinic/app/llamadas",    "M22 16.92v3a2 2 0 0 1-2.18 2A19.79 19.79 0 0 1 2 5.18 2 2 0 0 1 4 3h3"),
        ("plantillas","Plantillas", "/clinic/app/plantillas",  "M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"),
        ("config",    "Configuración","/clinic/app/configuracion","M12 1v6 M12 17v6 M4.22 4.22l4.24 4.24"),
    ]
    links = ""
    for k, label, url, _path in items:
        clase = "nav-item active" if k == activa else "nav-item"
        links += f'<a href="{url}" class="{clase}">{html.escape(label)}</a>'

    plan = clinica.plan if clinica else "free"
    badge_plan = {"free": "badge-free", "pro": "badge-pro", "studio": "badge-studio"}.get(plan, "badge-free")
    nombre = html.escape(clinica.nombre if clinica else "Clinica")

    return f"""
    <aside class="sidebar">
      <div class="brand">
        <div class="brand-logo">L</div>
        <div>
          <div class="brand-name">Lapora Clinic</div>
          <div class="brand-sub">{nombre}</div>
        </div>
      </div>
      <form action="/clinic/app/buscar" method="get" style="margin:14px 0 6px;">
        <input type="text" name="q" placeholder="🔍 Buscar pacientes, mensajes..."
               style="width:100%;padding:9px 12px;border:1.5px solid var(--border);border-radius:9px;font-size:13px;outline:none;background:var(--bg);"
               onfocus="this.style.borderColor='var(--primary)'"
               onblur="this.style.borderColor='var(--border)'">
      </form>
      <nav style="margin-top: 8px; flex: 1;">{links}</nav>
      <div style="border-top: 1px solid var(--border); padding-top: 14px;">
        <div style="font-size: 12px; color: var(--text-soft); margin-bottom: 6px;">
          {html.escape(sesion.get('nombre', ''))}
        </div>
        <span class="badge {badge_plan}">{plan.upper()}</span>
        <a href="/clinic/logout" style="display:block;margin-top:12px;font-size:12px;color:var(--text-soft);">Salir →</a>
      </div>
    </aside>
    """


# ════════════════════════════════════════════════════════════
# 1) LANDING — Redirige a login
# ════════════════════════════════════════════════════════════

@router.get("/", response_class=HTMLResponse)
async def landing(clinic_session: Optional[str] = Cookie(None)):
    if obtener_sesion(clinic_session):
        return RedirectResponse("/clinic/app/", status_code=303)
    return RedirectResponse("/clinic/login", status_code=303)


# ════════════════════════════════════════════════════════════
# 2) REGISTRO — Onboarding nueva clínica
# ════════════════════════════════════════════════════════════

@router.get("/registro", response_class=HTMLResponse)
async def registro_form(error: Optional[str] = None):
    err_html = f'<div style="background:#FEE2E2;color:#7F1D1D;padding:12px;border-radius:10px;margin-bottom:16px;font-size:13px;">{html.escape(error)}</div>' if error else ""
    return HTMLResponse(f"""<!DOCTYPE html>
<html lang="es"><head><meta charset="UTF-8"><title>Crear cuenta - Lapora Clinic</title>{CSS_CLINIC}</head>
<body>
  <div style="min-height: 100vh; display: flex; align-items: center; justify-content: center; padding: 20px;">
    <div style="max-width: 460px; width: 100%;">
      <div style="text-align: center; margin-bottom: 28px;">
        <div style="display: inline-flex; align-items: center; gap: 12px;">
          <div class="brand-logo" style="width:44px;height:44px;font-size:20px;">L</div>
          <div>
            <div style="font-weight: 800; font-size: 22px; color: var(--text);">Lapora Clinic</div>
            <div style="font-size: 12px; color: var(--text-soft);">El cerebro digital de tu consultorio</div>
          </div>
        </div>
      </div>
      <div class="card" style="padding: 32px;">
        <h1 style="font-size: 22px; font-weight: 800; margin-bottom: 6px;">Crear cuenta gratis</h1>
        <p style="color: var(--text-soft); margin-bottom: 24px; font-size: 13px;">
          Plan FREE incluye: 100 pacientes · Inbox WhatsApp · 1 usuario. Sin tarjeta.
        </p>
        {err_html}
        <form method="post" action="/clinic/registro" style="display: flex; flex-direction: column; gap: 14px;">
          <div>
            <label style="font-size: 12px; font-weight: 700; display: block; margin-bottom: 5px;">Nombre del consultorio</label>
            <input type="text" name="nombre_clinica" required placeholder="Ej: Clínica Sonrisa Plena" class="input">
          </div>
          <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 12px;">
            <div>
              <label style="font-size: 12px; font-weight: 700; display: block; margin-bottom: 5px;">Especialidad</label>
              <input type="text" name="especialidad" placeholder="Odontología" class="input">
            </div>
            <div>
              <label style="font-size: 12px; font-weight: 700; display: block; margin-bottom: 5px;">Ciudad</label>
              <input type="text" name="ciudad" placeholder="Ibagué" value="Ibagué" class="input">
            </div>
          </div>
          <div>
            <label style="font-size: 12px; font-weight: 700; display: block; margin-bottom: 5px;">Tu nombre</label>
            <input type="text" name="nombre_admin" required placeholder="Dr. Juan Pérez" class="input">
          </div>
          <div>
            <label style="font-size: 12px; font-weight: 700; display: block; margin-bottom: 5px;">Email</label>
            <input type="email" name="email" required placeholder="doctor@consultorio.com" class="input">
          </div>
          <div>
            <label style="font-size: 12px; font-weight: 700; display: block; margin-bottom: 5px;">Contraseña</label>
            <input type="password" name="password" required minlength="6" placeholder="Mínimo 6 caracteres" class="input">
          </div>
          <button type="submit" class="btn btn-primary" style="margin-top: 8px; justify-content: center;">
            Crear mi cuenta gratis
          </button>
        </form>
        <p style="margin-top: 18px; font-size: 13px; color: var(--text-soft); text-align: center;">
          ¿Ya tienes cuenta? <a href="/clinic/login" style="font-weight: 600;">Iniciar sesión</a>
        </p>
      </div>
    </div>
  </div>
</body></html>""")


@router.post("/registro", response_class=HTMLResponse)
async def registro_procesar(
    nombre_clinica: str = Form(...),
    especialidad: str = Form(""),
    ciudad: str = Form("Ibagué"),
    nombre_admin: str = Form(...),
    email: str = Form(...),
    password: str = Form(...),
):
    """Crea la clínica + usuario admin + sesión y redirige al dashboard."""
    if len(password) < 6:
        return RedirectResponse(
            f"/clinic/registro?error={html.escape('La contraseña debe tener mínimo 6 caracteres')}",
            status_code=303,
        )

    # Verificar email único
    async with async_session() as session:
        existing = (await session.execute(
            select(UsuarioClinic).where(UsuarioClinic.email == email.lower())
        )).scalar_one_or_none()
        if existing:
            return RedirectResponse(
                f"/clinic/registro?error={html.escape('Ese email ya está registrado. Inicia sesión.')}",
                status_code=303,
            )

    try:
        clinica, usuario = await crear_clinica(
            nombre=nombre_clinica,
            email_admin=email,
            password_admin=password,
            nombre_admin=nombre_admin,
            especialidad=especialidad,
            ciudad=ciudad,
        )
    except Exception as e:
        return RedirectResponse(
            f"/clinic/registro?error={html.escape('Error creando cuenta: ' + str(e)[:80])}",
            status_code=303,
        )

    token = crear_sesion(usuario)
    response = RedirectResponse("/clinic/app/?bienvenida=1", status_code=303)
    response.set_cookie("clinic_session", token, max_age=86400 * 30, httponly=True, samesite="lax")
    return response


# ════════════════════════════════════════════════════════════
# 3) LOGIN
# ════════════════════════════════════════════════════════════

@router.get("/login", response_class=HTMLResponse)
async def login_form(error: Optional[str] = None):
    err_html = f'<div style="background:#FEE2E2;color:#7F1D1D;padding:12px;border-radius:10px;margin-bottom:16px;font-size:13px;">{html.escape(error)}</div>' if error else ""
    return HTMLResponse(f"""<!DOCTYPE html>
<html lang="es"><head><meta charset="UTF-8"><title>Iniciar sesión - Lapora Clinic</title>{CSS_CLINIC}</head>
<body>
  <div style="min-height: 100vh; display: flex; align-items: center; justify-content: center; padding: 20px;">
    <div style="max-width: 420px; width: 100%;">
      <div style="text-align: center; margin-bottom: 28px;">
        <div style="display: inline-flex; align-items: center; gap: 12px;">
          <div class="brand-logo" style="width:44px;height:44px;font-size:20px;">L</div>
          <div>
            <div style="font-weight: 800; font-size: 22px;">Lapora Clinic</div>
            <div style="font-size: 12px; color: var(--text-soft);">Iniciar sesión</div>
          </div>
        </div>
      </div>
      <div class="card" style="padding: 32px;">
        {err_html}
        <form method="post" action="/clinic/login" style="display: flex; flex-direction: column; gap: 14px;">
          <div>
            <label style="font-size: 12px; font-weight: 700; display: block; margin-bottom: 5px;">Email</label>
            <input type="email" name="email" required class="input" autofocus>
          </div>
          <div>
            <label style="font-size: 12px; font-weight: 700; display: block; margin-bottom: 5px;">Contraseña</label>
            <input type="password" name="password" required class="input">
          </div>
          <button type="submit" class="btn btn-primary" style="margin-top: 8px; justify-content: center;">
            Entrar
          </button>
        </form>
        <p style="margin-top: 18px; font-size: 13px; color: var(--text-soft); text-align: center;">
          ¿Sin cuenta? <a href="/clinic/registro" style="font-weight: 600;">Crear gratis</a>
        </p>
      </div>
    </div>
  </div>
</body></html>""")


@router.post("/login", response_class=HTMLResponse)
async def login_procesar(email: str = Form(...), password: str = Form(...)):
    usuario = await autenticar_usuario(email, password)
    if not usuario:
        return RedirectResponse(
            f"/clinic/login?error={html.escape('Email o contraseña incorrectos')}",
            status_code=303,
        )
    token = crear_sesion(usuario)
    response = RedirectResponse("/clinic/app/", status_code=303)
    response.set_cookie("clinic_session", token, max_age=86400 * 30, httponly=True, samesite="lax")
    return response


@router.get("/logout")
async def logout(clinic_session: Optional[str] = Cookie(None)):
    if clinic_session and clinic_session in SESSIONS:
        del SESSIONS[clinic_session]
    response = RedirectResponse("/clinic/login", status_code=303)
    response.delete_cookie("clinic_session")
    return response


# ════════════════════════════════════════════════════════════
# 4) DASHBOARD — Vista principal post-login
# ════════════════════════════════════════════════════════════

@router.get("/app/", response_class=HTMLResponse)
@router.get("/app", response_class=HTMLResponse)
async def dashboard(
    bienvenida: Optional[str] = None,
    demo: Optional[int] = None,
    clinic_session: Optional[str] = Cookie(None),
):
    sesion = obtener_sesion(clinic_session)
    if not sesion:
        return RedirectResponse("/clinic/login", status_code=303)

    clinica = await obtener_clinica(sesion["clinica_id"])
    if not clinica:
        return RedirectResponse("/clinic/login", status_code=303)

    # Stats reales + vista "HOY"
    from datetime import timedelta
    hoy_inicio = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
    hoy_fin = hoy_inicio + timedelta(days=1)
    hace_7_dias = hoy_inicio - timedelta(days=7)
    hace_1_dia = datetime.utcnow() - timedelta(days=1)

    async with async_session() as session:
        total_pacientes = (await session.execute(
            select(func.count(Paciente.id)).where(Paciente.clinica_id == clinica.id)
        )).scalar() or 0
        total_mensajes = (await session.execute(
            select(func.count(MensajeUnificado.id)).where(MensajeUnificado.clinica_id == clinica.id)
        )).scalar() or 0
        mensajes_no_leidos = (await session.execute(
            select(func.count(MensajeUnificado.id))
            .where(MensajeUnificado.clinica_id == clinica.id)
            .where(MensajeUnificado.leido == False)
            .where(MensajeUnificado.direccion == "entrada")
        )).scalar() or 0
        total_citas = (await session.execute(
            select(func.count(CitaClinic.id)).where(CitaClinic.clinica_id == clinica.id)
        )).scalar() or 0

        # === Tareas de HOY ===
        # Pacientes nuevos esta semana
        nuevos_semana = list((await session.execute(
            select(Paciente).where(Paciente.clinica_id == clinica.id)
            .where(Paciente.primer_contacto >= hace_7_dias)
            .order_by(desc(Paciente.primer_contacto)).limit(10)
        )).scalars().all())
        # Citas de hoy
        citas_hoy = list((await session.execute(
            select(CitaClinic).where(CitaClinic.clinica_id == clinica.id)
            .where(CitaClinic.fecha_hora >= hoy_inicio)
            .where(CitaClinic.fecha_hora < hoy_fin)
            .order_by(CitaClinic.fecha_hora)
        )).scalars().all())
        # Mensajes sin responder de hace > 1 día
        mensajes_pendientes = list((await session.execute(
            select(MensajeUnificado).where(MensajeUnificado.clinica_id == clinica.id)
            .where(MensajeUnificado.direccion == "entrada")
            .where(MensajeUnificado.leido == False)
            .where(MensajeUnificado.timestamp < hace_1_dia)
            .order_by(MensajeUnificado.timestamp).limit(5)
        )).scalars().all())
        # Llamadas marcadas como "volver_a_llamar"
        volver_llamar = list((await session.execute(
            select(Llamada).where(Llamada.clinica_id == clinica.id)
            .where(Llamada.resultado == "volver_a_llamar")
            .order_by(desc(Llamada.timestamp)).limit(5)
        )).scalars().all())

    bienvenida_html = ""
    if demo:
        bienvenida_html = f'<div style="background:#ECFDF5;border:1px solid #10B981;color:#065F46;padding:14px 18px;border-radius:12px;margin-bottom:24px;">🎉 ¡Datos demo cargados! Tienes {demo} pacientes de ejemplo para explorar.</div>'
    elif bienvenida:
        bienvenida_html = f"""
        <div style="background:#ECFDF5;border:1px solid #10B981;color:#065F46;padding:14px 18px;border-radius:12px;margin-bottom:24px;">
          🎉 <strong>¡Bienvenido a Lapora Clinic, {html.escape(sesion.get('nombre',''))}!</strong>
          Tu clínica <strong>{html.escape(clinica.nombre)}</strong> está lista.<br>
          <a href="/clinic/app/configuracion" style="font-weight: 700;">Conectar WhatsApp →</a> ·
          <a href="/clinic/app/pacientes/nuevo" style="font-weight: 700;">Crear paciente →</a> ·
          <form method="post" action="/clinic/app/demo-data" style="display:inline;">
            <button type="submit" style="background:none;border:none;color:#065F46;font-weight:700;cursor:pointer;text-decoration:underline;padding:0;font-family:inherit;font-size:14px;">Cargar datos demo →</button>
          </form>
        </div>"""

    # Render bloque "Hoy"
    def render_lista(items, fn_render, vacio_msg):
        if not items:
            return f'<p style="color:var(--text-soft);font-size:13px;padding:14px;text-align:center;">{vacio_msg}</p>'
        return "".join(fn_render(i) for i in items)

    citas_html = render_lista(
        citas_hoy,
        lambda c: f'<div style="padding:10px 14px;border-bottom:1px solid var(--border);font-size:13px;"><strong>{c.fecha_hora.strftime("%H:%M")}</strong> · <a href="/clinic/app/pacientes/{c.paciente_id}">paciente</a> · {html.escape(c.motivo or "")}</div>',
        "Sin citas hoy 🎉",
    )
    pendientes_html = render_lista(
        mensajes_pendientes,
        lambda m: f'<div style="padding:10px 14px;border-bottom:1px solid var(--border);font-size:13px;"><a href="/clinic/app/inbox?paciente_id={m.paciente_id}">{html.escape((m.contenido or "")[:60])}...</a></div>',
        "Todo respondido ✓",
    )
    volver_html = render_lista(
        volver_llamar,
        lambda l: f'<div style="padding:10px 14px;border-bottom:1px solid var(--border);font-size:13px;"><a href="/clinic/app/pacientes/{l.paciente_id}">{html.escape((l.notas or "Pendiente")[:60])}</a></div>',
        "Sin llamadas pendientes 📞",
    )
    nuevos_html = render_lista(
        nuevos_semana,
        lambda p: f'<div style="padding:10px 14px;border-bottom:1px solid var(--border);font-size:13px;"><a href="/clinic/app/pacientes/{p.id}">{html.escape(p.nombre)}</a> · {html.escape(p.tratamiento_actual or "")}</div>',
        "Sin pacientes nuevos esta semana",
    )

    return HTMLResponse(f"""<!DOCTYPE html>
<html lang="es"><head><meta charset="UTF-8"><title>Dashboard - Lapora Clinic</title>{CSS_CLINIC}</head>
<body>
  <div class="app-wrap">
    {sidebar_clinic("dashboard", sesion, clinica)}
    <main class="main">
      <h1 style="font-size: 26px; font-weight: 800; margin-bottom: 4px;">Hola, {html.escape(sesion.get('nombre',''))} 👋</h1>
      <p style="color: var(--text-soft); margin-bottom: 24px;">Vista general de {html.escape(clinica.nombre)}</p>
      {bienvenida_html}

      <div style="display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 14px; margin-bottom: 28px;">
        <div class="card">
          <div style="font-size: 11px; color: var(--text-soft); text-transform: uppercase; letter-spacing: 1px; font-weight: 700;">Pacientes</div>
          <div style="font-size: 32px; font-weight: 800; margin-top: 6px;">{total_pacientes}</div>
          <a href="/clinic/app/pacientes" style="font-size: 12px;">Ver todos →</a>
        </div>
        <div class="card">
          <div style="font-size: 11px; color: var(--text-soft); text-transform: uppercase; letter-spacing: 1px; font-weight: 700;">Mensajes sin leer</div>
          <div style="font-size: 32px; font-weight: 800; color: {('var(--primary)' if mensajes_no_leidos > 0 else 'var(--text)')};margin-top: 6px;">{mensajes_no_leidos}</div>
          <a href="/clinic/app/inbox" style="font-size: 12px;">Ir al inbox →</a>
        </div>
        <div class="card">
          <div style="font-size: 11px; color: var(--text-soft); text-transform: uppercase; letter-spacing: 1px; font-weight: 700;">Mensajes totales</div>
          <div style="font-size: 32px; font-weight: 800; margin-top: 6px;">{total_mensajes}</div>
          <div style="font-size: 12px; color: var(--text-soft);">históricos</div>
        </div>
        <div class="card">
          <div style="font-size: 11px; color: var(--text-soft); text-transform: uppercase; letter-spacing: 1px; font-weight: 700;">Citas agendadas</div>
          <div style="font-size: 32px; font-weight: 800; margin-top: 6px;">{total_citas}</div>
          <div style="font-size: 12px; color: var(--text-soft);">en total</div>
        </div>
      </div>

      <!-- VISTA HOY -->
      <h2 style="font-size:18px;font-weight:800;margin:8px 0 12px;">📅 Hoy y esta semana</h2>
      <div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(260px,1fr));gap:14px;margin-bottom:28px;">
        <div class="card" style="padding:0;overflow:hidden;">
          <div style="padding:12px 14px;background:#3B82F6;color:white;font-size:12px;font-weight:700;text-transform:uppercase;letter-spacing:1px;">
            📅 Citas hoy ({len(citas_hoy)})
          </div>
          {citas_html}
        </div>
        <div class="card" style="padding:0;overflow:hidden;">
          <div style="padding:12px 14px;background:#F59E0B;color:white;font-size:12px;font-weight:700;text-transform:uppercase;letter-spacing:1px;">
            ⚠️ Sin responder ({len(mensajes_pendientes)})
          </div>
          {pendientes_html}
        </div>
        <div class="card" style="padding:0;overflow:hidden;">
          <div style="padding:12px 14px;background:#A855F7;color:white;font-size:12px;font-weight:700;text-transform:uppercase;letter-spacing:1px;">
            📞 Volver a llamar ({len(volver_llamar)})
          </div>
          {volver_html}
        </div>
        <div class="card" style="padding:0;overflow:hidden;">
          <div style="padding:12px 14px;background:#10B981;color:white;font-size:12px;font-weight:700;text-transform:uppercase;letter-spacing:1px;">
            🆕 Nuevos esta semana ({len(nuevos_semana)})
          </div>
          {nuevos_html}
        </div>
      </div>

      <div class="card" style="padding: 28px;">
        <h2 style="font-size: 18px; font-weight: 700; margin-bottom: 16px;">🚀 Empieza en 3 pasos</h2>
        <ol style="padding-left: 20px; line-height: 1.9; color: var(--text); font-size: 14px;">
          <li><strong>Conectá WhatsApp Business</strong> — recibí los mensajes de tus pacientes en el inbox unificado.
            <a href="/clinic/app/configuracion" style="margin-left: 6px;">Conectar →</a></li>
          <li><strong>Sincronizá Google Sheets</strong> — importá tus pacientes existentes desde Excel/Sheets.
            <a href="/clinic/app/configuracion" style="margin-left: 6px;">Sincronizar →</a></li>
          <li><strong>Creá plantillas de respuesta</strong> — respondé a preguntas frecuentes con un click.
            <a href="/clinic/app/plantillas" style="margin-left: 6px;">Crear →</a></li>
        </ol>
        {('<div style="margin-top:20px;padding-top:16px;border-top:1px solid var(--border);"><form method="post" action="/clinic/app/demo-data"><button type="submit" class="btn btn-ghost">🎁 Cargar datos de ejemplo</button></form><p style="font-size:11px;color:var(--text-soft);margin-top:6px;">Crea 5 pacientes, 7 mensajes, 3 llamadas y 4 plantillas demo para explorar la plataforma.</p></div>' if total_pacientes == 0 else '')}
      </div>
    </main>
  </div>
</body></html>""")


# ════════════════════════════════════════════════════════════
# 5) INBOX — Mockup MVP (se llena con datos reales en Mes 1)
# ════════════════════════════════════════════════════════════

@router.get("/app/inbox", response_class=HTMLResponse)
async def vista_inbox(
    canal: Optional[str] = None,
    paciente_id: Optional[int] = None,
    clinic_session: Optional[str] = Cookie(None),
):
    """Inbox unificado: lista de conversaciones a la izquierda, chat seleccionado a la derecha."""
    sesion = obtener_sesion(clinic_session)
    if not sesion:
        return RedirectResponse("/clinic/login", status_code=303)
    clinica = await obtener_clinica(sesion["clinica_id"])

    async with async_session() as session:
        # Última conversación por paciente (group by paciente, order by último msg)
        # Para simplicidad, traemos todos los mensajes recientes y agrupamos en memoria
        query = select(MensajeUnificado).where(MensajeUnificado.clinica_id == clinica.id)
        if canal and canal != "todos":
            query = query.where(MensajeUnificado.canal == canal)
        query = query.order_by(desc(MensajeUnificado.timestamp)).limit(500)
        todos_mensajes = list((await session.execute(query)).scalars().all())

        # Agrupar por paciente: tomar el último mensaje de cada uno
        conversaciones: dict[int, dict] = {}
        for m in todos_mensajes:
            pid = m.paciente_id or 0
            if pid not in conversaciones:
                conversaciones[pid] = {
                    "paciente_id": pid,
                    "ultimo_mensaje": m,
                    "no_leidos": 0,
                    "total": 0,
                    "canales": set(),
                }
            conversaciones[pid]["total"] += 1
            conversaciones[pid]["canales"].add(m.canal)
            if not m.leido and m.direccion == "entrada":
                conversaciones[pid]["no_leidos"] += 1

        # Cargar nombres de pacientes
        pids = [c["paciente_id"] for c in conversaciones.values() if c["paciente_id"]]
        pacientes_map = {}
        if pids:
            for p in (await session.execute(
                select(Paciente).where(Paciente.id.in_(pids))
            )).scalars().all():
                pacientes_map[p.id] = p

        # Mensajes del chat seleccionado
        mensajes_chat: list = []
        paciente_actual = None
        if paciente_id:
            paciente_actual = pacientes_map.get(paciente_id)
            if not paciente_actual:
                paciente_actual = (await session.execute(
                    select(Paciente).where(Paciente.id == paciente_id).where(Paciente.clinica_id == clinica.id)
                )).scalar_one_or_none()
            if paciente_actual:
                mensajes_chat = list((await session.execute(
                    select(MensajeUnificado)
                    .where(MensajeUnificado.clinica_id == clinica.id)
                    .where(MensajeUnificado.paciente_id == paciente_id)
                    .order_by(MensajeUnificado.timestamp.asc())
                )).scalars().all())
                # Marcar como leídos los entrantes
                for m in mensajes_chat:
                    if not m.leido and m.direccion == "entrada":
                        m.leido = True
                await session.commit()

        # Plantillas para insertar
        plantillas = list((await session.execute(
            select(PlantillaRespuesta).where(PlantillaRespuesta.clinica_id == clinica.id)
            .order_by(desc(PlantillaRespuesta.usos)).limit(10)
        )).scalars().all())

    # === Conversaciones (sidebar izquierdo)
    conv_html = ""
    convs_ordenadas = sorted(
        conversaciones.values(),
        key=lambda c: c["ultimo_mensaje"].timestamp if c["ultimo_mensaje"] else datetime.min,
        reverse=True,
    )
    canal_icon = {"whatsapp": "💬", "instagram": "📷", "email": "✉️", "sms": "💬", "llamada": "📞"}
    for conv in convs_ordenadas:
        p = pacientes_map.get(conv["paciente_id"])
        if not p:
            continue
        ultimo = conv["ultimo_mensaje"]
        nombre = html.escape(p.nombre or "Sin nombre")
        preview = html.escape((ultimo.contenido or "")[:55])
        ts = ultimo.timestamp.strftime("%H:%M") if ultimo.timestamp else ""
        no_leidos = conv["no_leidos"]
        canales_icons = "".join(canal_icon.get(c, "·") for c in conv["canales"])
        activa = "background:var(--primary-light);border-left:3px solid var(--primary);" if paciente_id == p.id else ""
        badge_unread = f'<span style="background:var(--primary);color:white;font-size:11px;padding:1px 7px;border-radius:999px;font-weight:700;">{no_leidos}</span>' if no_leidos else ""
        conv_html += f"""
        <a href="/clinic/app/inbox?paciente_id={p.id}{('&canal=' + canal) if canal and canal != 'todos' else ''}"
           style="display:block;padding:12px 14px;border-bottom:1px solid var(--border);text-decoration:none;color:var(--text);{activa}">
          <div style="display:flex;justify-content:space-between;align-items:center;">
            <div style="font-weight:600;font-size:14px;">{nombre}</div>
            <div style="font-size:11px;color:var(--text-soft);">{ts}</div>
          </div>
          <div style="display:flex;justify-content:space-between;align-items:center;margin-top:4px;">
            <div style="font-size:12px;color:var(--text-soft);">{canales_icons} {preview}...</div>
            {badge_unread}
          </div>
        </a>"""

    if not conv_html:
        conv_html = """
        <div style="text-align:center;padding:40px 20px;color:var(--text-soft);">
          <div style="font-size:48px;">📭</div>
          <p style="margin-top:10px;font-size:13px;">Sin conversaciones todavía</p>
        </div>"""

    # === Chat (panel derecho)
    chat_html = ""
    if paciente_actual:
        bubbles = ""
        for m in mensajes_chat:
            es_salida = m.direccion == "salida"
            align = "flex-end" if es_salida else "flex-start"
            color = "var(--primary)" if es_salida else "white"
            text_color = "white" if es_salida else "var(--text)"
            ts = m.timestamp.strftime("%H:%M") if m.timestamp else ""
            icon = canal_icon.get(m.canal, "·")
            bubbles += f"""
            <div style="display:flex;justify-content:{align};margin-bottom:10px;">
              <div style="max-width:65%;background:{color};color:{text_color};padding:10px 14px;border-radius:14px;box-shadow:0 1px 2px rgba(0,0,0,0.06);">
                <div style="font-size:14px;line-height:1.4;">{html.escape(m.contenido or "")}</div>
                <div style="font-size:10px;opacity:0.7;margin-top:4px;text-align:right;">{icon} {ts}</div>
              </div>
            </div>"""
        if not bubbles:
            bubbles = '<div style="text-align:center;color:var(--text-soft);padding:40px;font-size:14px;">Sin mensajes con este paciente todavía</div>'

        opciones_plantilla = "".join(
            f'<option value="{html.escape(pl.contenido, quote=True)}">{html.escape(pl.titulo)}</option>'
            for pl in plantillas
        )
        # Construir el select de plantillas fuera del f-string para evitar líos de escape
        if plantillas:
            select_plantilla_html = (
                '<select onchange="var m=document.getElementById(\'msg\');m.value=this.value;this.value=\'\';" '
                'class="input" style="margin-bottom:8px;font-size:13px;">'
                '<option value="">Insertar plantilla...</option>'
                f'{opciones_plantilla}</select>'
            )
        else:
            select_plantilla_html = ""

        # Header del chat
        tel = html.escape(paciente_actual.telefono or "—")
        chat_html = f"""
        <div style="display:flex;flex-direction:column;height:100%;">
          <div style="padding:16px 20px;border-bottom:1px solid var(--border);background:white;display:flex;justify-content:space-between;align-items:center;">
            <div>
              <div style="font-weight:700;font-size:15px;">{html.escape(paciente_actual.nombre)}</div>
              <div style="font-size:12px;color:var(--text-soft);font-family:monospace;">{tel}</div>
            </div>
            <a href="/clinic/app/pacientes/{paciente_actual.id}" class="btn btn-ghost" style="padding:8px 14px;font-size:13px;">Ver ficha →</a>
          </div>
          <div style="flex:1;overflow-y:auto;padding:20px;background:#fafaf9;">
            {bubbles}
          </div>
          <div style="border-top:1px solid var(--border);padding:14px 16px;background:white;">
            <form method="post" action="/clinic/app/inbox/{paciente_actual.id}/responder" style="display:flex;gap:10px;align-items:flex-end;">
              <div style="flex:1;">
                {select_plantilla_html}
                <textarea id="msg" name="contenido" required rows="2" class="input"
                          style="resize:vertical;font-family:inherit;line-height:1.4;"
                          placeholder="Escribe un mensaje a {html.escape(paciente_actual.nombre)}..."></textarea>
              </div>
              <button type="submit" class="btn btn-primary" style="background:#25D366;box-shadow:0 4px 12px rgba(37,211,102,0.3);">📲 Enviar</button>
            </form>
          </div>
        </div>"""
    else:
        chat_html = """
        <div style="display:flex;flex-direction:column;align-items:center;justify-content:center;height:100%;color:var(--text-soft);text-align:center;padding:40px;">
          <div style="font-size:64px;margin-bottom:16px;">💬</div>
          <h3 style="font-size:18px;font-weight:700;color:var(--text);margin-bottom:8px;">Selecciona una conversación</h3>
          <p style="font-size:14px;max-width:320px;">O conecta WhatsApp e Instagram en Configuración para empezar a recibir mensajes.</p>
        </div>"""

    # Filtros de canal
    canales_disponibles = [
        ("todos", "Todos", "📥"),
        ("whatsapp", "WhatsApp", "💬"),
        ("instagram", "Instagram", "📷"),
        ("email", "Email", "✉️"),
    ]
    filtros_html = ""
    for c, lab, ic in canales_disponibles:
        activo = (canal == c) or (not canal and c == "todos")
        bg = "var(--primary)" if activo else "transparent"
        col = "white" if activo else "var(--text)"
        filtros_html += f'<a href="/clinic/app/inbox?canal={c}" style="background:{bg};color:{col};border:1.5px solid {("var(--primary)" if activo else "var(--border)")};padding:6px 12px;border-radius:999px;font-size:12px;font-weight:600;text-decoration:none;display:inline-block;margin-right:6px;">{ic} {lab}</a>'

    return HTMLResponse(f"""<!DOCTYPE html>
<html lang="es"><head><meta charset="UTF-8"><title>Inbox - Lapora Clinic</title>{CSS_CLINIC}</head>
<body>
  <div class="app-wrap">
    {sidebar_clinic("inbox", sesion, clinica)}
    <main class="main" style="padding:0;display:flex;flex-direction:column;height:100vh;">
      <div style="padding:20px 28px;border-bottom:1px solid var(--border);background:white;">
        <h1 style="font-size:22px;font-weight:800;margin-bottom:4px;">Inbox unificado</h1>
        <div style="margin-top:10px;">{filtros_html}</div>
      </div>
      <div style="flex:1;display:grid;grid-template-columns:340px 1fr;min-height:0;background:white;">
        <div style="border-right:1px solid var(--border);overflow-y:auto;">{conv_html}</div>
        <div>{chat_html}</div>
      </div>
    </main>
  </div>
</body></html>""")


@router.post("/app/inbox/{paciente_id}/responder", response_class=HTMLResponse)
async def responder_inbox(
    paciente_id: int,
    contenido: str = Form(...),
    clinic_session: Optional[str] = Cookie(None),
):
    """Envia un mensaje desde el inbox al paciente vía el canal de su última conversación."""
    sesion = obtener_sesion(clinic_session)
    if not sesion:
        return RedirectResponse("/clinic/login", status_code=303)

    contenido = contenido.strip()
    if not contenido:
        return RedirectResponse(f"/clinic/app/inbox?paciente_id={paciente_id}", status_code=303)

    async with async_session() as session:
        clinica = (await session.execute(
            select(Clinica).where(Clinica.id == sesion["clinica_id"])
        )).scalar_one_or_none()
        paciente = (await session.execute(
            select(Paciente).where(Paciente.id == paciente_id).where(Paciente.clinica_id == sesion["clinica_id"])
        )).scalar_one_or_none()
        if not paciente or not clinica:
            return RedirectResponse("/clinic/app/inbox", status_code=303)

        # Determinar canal del último mensaje (para responder por donde vino)
        ultimo = (await session.execute(
            select(MensajeUnificado)
            .where(MensajeUnificado.paciente_id == paciente_id)
            .order_by(desc(MensajeUnificado.timestamp))
            .limit(1)
        )).scalar_one_or_none()
        canal_resp = ultimo.canal if ultimo else "whatsapp"

        # Enviar por Meta WhatsApp API si el canal es whatsapp y hay token de la clínica
        if canal_resp == "whatsapp" and clinica.whatsapp_phone_id and clinica.whatsapp_token and paciente.telefono:
            try:
                import re as _re_mod
                import httpx as _httpx_mod
                tel = _re_mod.sub(r"\D", "", paciente.telefono)
                if not tel.startswith("57") and len(tel) == 10:
                    tel = f"57{tel}"
                async with _httpx_mod.AsyncClient(timeout=20.0) as client:
                    await client.post(
                        f"https://graph.facebook.com/v21.0/{clinica.whatsapp_phone_id}/messages",
                        headers={
                            "Authorization": f"Bearer {clinica.whatsapp_token}",
                            "Content-Type": "application/json",
                        },
                        json={
                            "messaging_product": "whatsapp",
                            "to": tel,
                            "type": "text",
                            "text": {"body": contenido},
                        },
                    )
            except Exception:
                pass  # Si falla el envío externo, igual guardamos en BD

        # Siempre guardar el mensaje en el inbox para el historial
        session.add(MensajeUnificado(
            clinica_id=sesion["clinica_id"],
            paciente_id=paciente_id,
            canal=canal_resp,
            direccion="salida",
            contenido=contenido,
            leido=True,
            respondido_por="usuario",
        ))
        paciente.ultimo_contacto = datetime.utcnow()
        paciente.total_mensajes = (paciente.total_mensajes or 0) + 1
        await session.commit()

    return RedirectResponse(f"/clinic/app/inbox?paciente_id={paciente_id}", status_code=303)


# ════════════════════════════════════════════════════════════
# 6) PACIENTES — CRUD completo
# ════════════════════════════════════════════════════════════

@router.get("/app/pacientes", response_class=HTMLResponse)
async def vista_pacientes(
    q: Optional[str] = None,
    creado: Optional[str] = None,
    clinic_session: Optional[str] = Cookie(None),
):
    sesion = obtener_sesion(clinic_session)
    if not sesion:
        return RedirectResponse("/clinic/login", status_code=303)
    clinica = await obtener_clinica(sesion["clinica_id"])

    async with async_session() as session:
        query = select(Paciente).where(Paciente.clinica_id == clinica.id)
        if q:
            p = f"%{q}%"
            query = query.where(or_(
                Paciente.nombre.ilike(p),
                Paciente.telefono.ilike(p),
                Paciente.email.ilike(p),
            ))
        query = query.order_by(desc(Paciente.ultimo_contacto)).limit(200)
        pacientes = list((await session.execute(query)).scalars().all())

    if pacientes:
        filas = ""
        for p in pacientes:
            nombre = html.escape(p.nombre or "")
            tel = html.escape(p.telefono or "")
            email = html.escape(p.email or "")
            estado = html.escape(p.estado or "nuevo")
            ult = p.ultimo_contacto.strftime("%d/%m/%Y") if p.ultimo_contacto else "—"
            color_estado = {
                "nuevo": "#3B82F6", "activo": "#10B981",
                "inactivo": "#78716C", "dado_de_alta": "#A855F7",
            }.get(estado, "#78716C")
            filas += f"""
              <tr style="border-bottom:1px solid var(--border);transition:background 0.15s;"
                  onmouseover="this.style.background='var(--bg)'" onmouseout="this.style.background='transparent'">
                <td style="padding:14px;">
                  <a href="/clinic/app/pacientes/{p.id}" style="font-weight:600;color:var(--text);">{nombre}</a>
                </td>
                <td style="padding:14px;color:var(--text-soft);font-family:monospace;font-size:13px;">{tel}</td>
                <td style="padding:14px;color:var(--text-soft);font-size:13px;">{email}</td>
                <td style="padding:14px;">
                  <span style="background:{color_estado}20;color:{color_estado};padding:3px 10px;border-radius:999px;font-size:11px;font-weight:700;text-transform:uppercase;">{estado}</span>
                </td>
                <td style="padding:14px;color:var(--text-soft);font-size:13px;">{ult}</td>
              </tr>"""
        contenido = f"""
        <table style="width:100%;border-collapse:collapse;">
          <thead><tr style="background:#1c1917;color:white;">
            <th style="padding:14px;text-align:left;font-size:11px;text-transform:uppercase;letter-spacing:1px;">Nombre</th>
            <th style="padding:14px;text-align:left;font-size:11px;text-transform:uppercase;letter-spacing:1px;">Teléfono</th>
            <th style="padding:14px;text-align:left;font-size:11px;text-transform:uppercase;letter-spacing:1px;">Email</th>
            <th style="padding:14px;text-align:left;font-size:11px;text-transform:uppercase;letter-spacing:1px;">Estado</th>
            <th style="padding:14px;text-align:left;font-size:11px;text-transform:uppercase;letter-spacing:1px;">Último contacto</th>
          </tr></thead>
          <tbody>{filas}</tbody>
        </table>"""
    else:
        contenido = """
        <div style="text-align:center;padding:60px 20px;color:var(--text-soft);">
          <div style="font-size:64px;margin-bottom:16px;">👥</div>
          <h3 style="font-size:18px;font-weight:700;color:var(--text);margin-bottom:8px;">Sin pacientes aún</h3>
          <p style="margin-bottom:24px;">Crea tu primer paciente manualmente o sincroniza con Google Sheets.</p>
          <div style="display:flex;gap:10px;justify-content:center;">
            <a href="/clinic/app/pacientes/nuevo" class="btn btn-primary">+ Nuevo paciente</a>
            <a href="/clinic/app/configuracion" class="btn btn-ghost">Conectar Google Sheets</a>
          </div>
        </div>"""

    creado_banner = ""
    if creado:
        creado_banner = '<div style="background:#ECFDF5;border:1px solid #10B981;color:#065F46;padding:12px 16px;border-radius:10px;margin-bottom:16px;font-size:14px;font-weight:600;">✓ Paciente guardado correctamente</div>'

    q_val = html.escape(q or "", quote=True)
    return HTMLResponse(f"""<!DOCTYPE html>
<html lang="es"><head><meta charset="UTF-8"><title>Pacientes - Lapora Clinic</title>{CSS_CLINIC}</head>
<body>
  <div class="app-wrap">
    {sidebar_clinic("pacientes", sesion, clinica)}
    <main class="main">
      <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:20px;flex-wrap:wrap;gap:14px;">
        <div>
          <h1 style="font-size:26px;font-weight:800;margin-bottom:4px;">Pacientes</h1>
          <p style="color:var(--text-soft);">{len(pacientes)} pacientes registrados</p>
        </div>
        <div style="display:flex;gap:10px;align-items:center;flex-wrap:wrap;">
          <form method="get" action="/clinic/app/pacientes" style="display:flex;gap:8px;">
            <input type="text" name="q" value="{q_val}" placeholder="Buscar..." class="input" style="width:220px;">
            <button type="submit" class="btn btn-ghost">Buscar</button>
          </form>
          <a href="/clinic/app/pacientes/importar" class="btn btn-ghost" title="Importar CSV">↑ Importar</a>
          <a href="/clinic/app/pacientes-export" class="btn btn-ghost" title="Exportar CSV">↓ Exportar</a>
          <a href="/clinic/app/pacientes/nuevo" class="btn btn-primary">+ Nuevo</a>
        </div>
      </div>
      {creado_banner}
      <div class="card" style="padding:0;overflow:hidden;">{contenido}</div>
    </main>
  </div>
</body></html>""")


@router.get("/app/pacientes/nuevo", response_class=HTMLResponse)
async def nuevo_paciente_form(clinic_session: Optional[str] = Cookie(None)):
    sesion = obtener_sesion(clinic_session)
    if not sesion:
        return RedirectResponse("/clinic/login", status_code=303)
    clinica = await obtener_clinica(sesion["clinica_id"])

    return HTMLResponse(f"""<!DOCTYPE html>
<html lang="es"><head><meta charset="UTF-8"><title>Nuevo paciente - Lapora Clinic</title>{CSS_CLINIC}</head>
<body>
  <div class="app-wrap">
    {sidebar_clinic("pacientes", sesion, clinica)}
    <main class="main">
      <a href="/clinic/app/pacientes" style="font-size:13px;color:var(--text-soft);">← Volver a pacientes</a>
      <h1 style="font-size:26px;font-weight:800;margin:8px 0 24px;">Nuevo paciente</h1>

      <div class="card" style="max-width:680px;">
        <form method="post" action="/clinic/app/pacientes/nuevo" style="display:flex;flex-direction:column;gap:16px;">
          <div>
            <label style="font-size:12px;font-weight:700;display:block;margin-bottom:5px;">Nombre completo *</label>
            <input type="text" name="nombre" required class="input" autofocus>
          </div>
          <div style="display:grid;grid-template-columns:1fr 1fr;gap:14px;">
            <div>
              <label style="font-size:12px;font-weight:700;display:block;margin-bottom:5px;">Teléfono / WhatsApp</label>
              <input type="text" name="telefono" placeholder="+57 300 123 4567" class="input">
            </div>
            <div>
              <label style="font-size:12px;font-weight:700;display:block;margin-bottom:5px;">Email</label>
              <input type="email" name="email" class="input">
            </div>
          </div>
          <div style="display:grid;grid-template-columns:1fr 1fr 1fr;gap:14px;">
            <div>
              <label style="font-size:12px;font-weight:700;display:block;margin-bottom:5px;">Documento</label>
              <input type="text" name="documento" placeholder="CC 12345678" class="input">
            </div>
            <div>
              <label style="font-size:12px;font-weight:700;display:block;margin-bottom:5px;">Género</label>
              <select name="genero" class="input">
                <option value="">—</option>
                <option value="M">Masculino</option>
                <option value="F">Femenino</option>
                <option value="O">Otro</option>
              </select>
            </div>
            <div>
              <label style="font-size:12px;font-weight:700;display:block;margin-bottom:5px;">Estado</label>
              <select name="estado" class="input">
                <option value="nuevo">Nuevo</option>
                <option value="activo">Activo</option>
                <option value="inactivo">Inactivo</option>
              </select>
            </div>
          </div>
          <div>
            <label style="font-size:12px;font-weight:700;display:block;margin-bottom:5px;">Tratamiento actual</label>
            <input type="text" name="tratamiento_actual" placeholder="Ortodoncia, Limpieza, etc." class="input">
          </div>
          <div>
            <label style="font-size:12px;font-weight:700;display:block;margin-bottom:5px;">Alergias</label>
            <input type="text" name="alergias" placeholder="Penicilina, latex..." class="input">
          </div>
          <div>
            <label style="font-size:12px;font-weight:700;display:block;margin-bottom:5px;">Notas básicas</label>
            <textarea name="notas_basicas" rows="3" class="input" style="resize:vertical;font-family:inherit;"
                      placeholder="Cualquier información relevante del paciente..."></textarea>
          </div>
          <div style="display:flex;gap:10px;margin-top:8px;">
            <button type="submit" class="btn btn-primary">Guardar paciente</button>
            <a href="/clinic/app/pacientes" class="btn btn-ghost">Cancelar</a>
          </div>
        </form>
      </div>
    </main>
  </div>
</body></html>""")


@router.post("/app/pacientes/nuevo", response_class=HTMLResponse)
async def nuevo_paciente_procesar(
    nombre: str = Form(...),
    telefono: str = Form(""),
    email: str = Form(""),
    documento: str = Form(""),
    genero: str = Form(""),
    estado: str = Form("nuevo"),
    tratamiento_actual: str = Form(""),
    alergias: str = Form(""),
    notas_basicas: str = Form(""),
    clinic_session: Optional[str] = Cookie(None),
):
    sesion = obtener_sesion(clinic_session)
    if not sesion:
        return RedirectResponse("/clinic/login", status_code=303)

    async with async_session() as session:
        ahora = datetime.utcnow()
        session.add(Paciente(
            clinica_id=sesion["clinica_id"],
            nombre=nombre.strip(),
            telefono=telefono.strip(),
            email=email.strip().lower(),
            documento=documento.strip(),
            genero=genero,
            estado=estado,
            tratamiento_actual=tratamiento_actual.strip(),
            alergias=alergias.strip(),
            notas_basicas=notas_basicas.strip(),
            fuente="manual",
            primer_contacto=ahora,
            ultimo_contacto=ahora,
        ))
        await session.commit()

    return RedirectResponse("/clinic/app/pacientes?creado=1", status_code=303)


@router.get("/app/pacientes/{paciente_id}", response_class=HTMLResponse)
async def detalle_paciente(
    paciente_id: int,
    clinic_session: Optional[str] = Cookie(None),
):
    sesion = obtener_sesion(clinic_session)
    if not sesion:
        return RedirectResponse("/clinic/login", status_code=303)
    clinica = await obtener_clinica(sesion["clinica_id"])

    async with async_session() as session:
        paciente = (await session.execute(
            select(Paciente)
            .where(Paciente.id == paciente_id)
            .where(Paciente.clinica_id == clinica.id)
        )).scalar_one_or_none()

        if not paciente:
            return HTMLResponse("<h1>Paciente no encontrado</h1>", status_code=404)

        mensajes = list((await session.execute(
            select(MensajeUnificado)
            .where(MensajeUnificado.paciente_id == paciente_id)
            .order_by(desc(MensajeUnificado.timestamp))
            .limit(20)
        )).scalars().all())
        llamadas = list((await session.execute(
            select(Llamada).where(Llamada.paciente_id == paciente_id).order_by(desc(Llamada.timestamp))
        )).scalars().all())
        citas = list((await session.execute(
            select(CitaClinic).where(CitaClinic.paciente_id == paciente_id).order_by(desc(CitaClinic.fecha_hora))
        )).scalars().all())

    nombre = html.escape(paciente.nombre or "")
    tel = html.escape(paciente.telefono or "—")
    email = html.escape(paciente.email or "—")
    estado = html.escape(paciente.estado or "")
    color_estado = {
        "nuevo": "#3B82F6", "activo": "#10B981",
        "inactivo": "#78716C", "dado_de_alta": "#A855F7",
    }.get(estado, "#78716C")

    timeline_html = ""
    eventos = []
    for m in mensajes:
        eventos.append((m.timestamp, "💬", f"Mensaje {m.direccion} ({m.canal})",
                        html.escape((m.contenido or "")[:120])))
    for l in llamadas:
        eventos.append((l.timestamp, "📞", f"Llamada {l.direccion}",
                        html.escape((l.notas or "")[:120])))
    for c in citas:
        eventos.append((c.fecha_hora, "📅", f"Cita {c.estado}",
                        html.escape((c.motivo or "")[:120])))
    eventos.sort(key=lambda x: x[0] or datetime.min, reverse=True)

    if eventos:
        for ts, icon, titulo, texto in eventos[:20]:
            fecha = ts.strftime("%d/%m/%Y %H:%M") if ts else ""
            timeline_html += f"""
            <div style="display:flex;gap:14px;padding:14px 0;border-bottom:1px solid var(--border);">
              <div style="font-size:22px;">{icon}</div>
              <div style="flex:1;">
                <div style="font-weight:600;font-size:14px;">{titulo}</div>
                <div style="font-size:13px;color:var(--text-soft);margin-top:2px;">{texto}</div>
                <div style="font-size:11px;color:var(--text-soft);margin-top:4px;">{fecha}</div>
              </div>
            </div>"""
    else:
        timeline_html = '<div style="text-align:center;padding:40px;color:var(--text-soft);"><div style="font-size:48px;">⏳</div><p style="margin-top:10px;">Sin actividad todavía</p></div>'

    return HTMLResponse(f"""<!DOCTYPE html>
<html lang="es"><head><meta charset="UTF-8"><title>{nombre} - Lapora Clinic</title>{CSS_CLINIC}</head>
<body>
  <div class="app-wrap">
    {sidebar_clinic("pacientes", sesion, clinica)}
    <main class="main">
      <a href="/clinic/app/pacientes" style="font-size:13px;color:var(--text-soft);">← Pacientes</a>
      <div style="display:flex;justify-content:space-between;align-items:center;margin:8px 0 24px;flex-wrap:wrap;gap:14px;">
        <div>
          <h1 style="font-size:28px;font-weight:800;">{nombre}</h1>
          <div style="display:flex;gap:10px;margin-top:6px;align-items:center;">
            <span style="background:{color_estado}20;color:{color_estado};padding:4px 12px;border-radius:999px;font-size:12px;font-weight:700;text-transform:uppercase;">{estado}</span>
            <span style="color:var(--text-soft);font-size:13px;">{html.escape(paciente.tratamiento_actual or "Sin tratamiento")}</span>
          </div>
        </div>
        <div style="display:flex;gap:10px;">
          {f'<a href="https://wa.me/{html.escape(paciente.telefono.replace("+", "").replace(" ", ""))}" target="_blank" class="btn btn-primary" style="background:#25D366;box-shadow:0 4px 12px rgba(37,211,102,0.25);">💬 WhatsApp</a>' if paciente.telefono else ''}
          <a href="/clinic/app/pacientes/{paciente.id}/editar" class="btn btn-ghost">✏️ Editar</a>
        </div>
      </div>

      <div style="display:grid;grid-template-columns:1fr 1fr;gap:18px;">
        <div class="card">
          <h3 style="font-size:14px;font-weight:700;text-transform:uppercase;color:var(--text-soft);letter-spacing:1px;margin-bottom:14px;">📇 Contacto</h3>
          <div style="display:grid;gap:10px;font-size:14px;">
            <div><strong style="display:inline-block;width:120px;color:var(--text-soft);">Teléfono</strong> <span style="font-family:monospace;">{tel}</span></div>
            <div><strong style="display:inline-block;width:120px;color:var(--text-soft);">Email</strong> {email}</div>
            <div><strong style="display:inline-block;width:120px;color:var(--text-soft);">Documento</strong> {html.escape(paciente.documento or "—")}</div>
            <div><strong style="display:inline-block;width:120px;color:var(--text-soft);">Alergias</strong> {html.escape(paciente.alergias or "—")}</div>
          </div>
          <div style="margin-top:18px;border-top:1px solid var(--border);padding-top:14px;">
            <strong style="color:var(--text-soft);font-size:13px;display:block;margin-bottom:6px;">📝 Notas</strong>
            <p style="font-size:14px;line-height:1.6;color:var(--text);">{html.escape(paciente.notas_basicas or "Sin notas todavía.")}</p>
          </div>
        </div>

        <div class="card">
          <h3 style="font-size:14px;font-weight:700;text-transform:uppercase;color:var(--text-soft);letter-spacing:1px;margin-bottom:14px;">⏱️ Timeline</h3>
          {timeline_html}
        </div>
      </div>

      <div style="margin-top:18px;display:grid;grid-template-columns:repeat(4,1fr);gap:12px;">
        <div class="card" style="text-align:center;">
          <div style="font-size:11px;color:var(--text-soft);text-transform:uppercase;letter-spacing:1px;font-weight:700;">Mensajes</div>
          <div style="font-size:28px;font-weight:800;color:var(--primary);margin-top:4px;">{len(mensajes)}</div>
        </div>
        <div class="card" style="text-align:center;">
          <div style="font-size:11px;color:var(--text-soft);text-transform:uppercase;letter-spacing:1px;font-weight:700;">Llamadas</div>
          <div style="font-size:28px;font-weight:800;margin-top:4px;">{len(llamadas)}</div>
        </div>
        <div class="card" style="text-align:center;">
          <div style="font-size:11px;color:var(--text-soft);text-transform:uppercase;letter-spacing:1px;font-weight:700;">Citas</div>
          <div style="font-size:28px;font-weight:800;margin-top:4px;">{len(citas)}</div>
        </div>
        <div class="card" style="text-align:center;">
          <div style="font-size:11px;color:var(--text-soft);text-transform:uppercase;letter-spacing:1px;font-weight:700;">Valor total</div>
          <div style="font-size:28px;font-weight:800;color:var(--green);margin-top:4px;">${paciente.valor_total:,}</div>
        </div>
      </div>
    </main>
  </div>
</body></html>""")


@router.get("/app/pacientes/{paciente_id}/editar", response_class=HTMLResponse)
async def editar_paciente_form(
    paciente_id: int,
    clinic_session: Optional[str] = Cookie(None),
):
    sesion = obtener_sesion(clinic_session)
    if not sesion:
        return RedirectResponse("/clinic/login", status_code=303)
    clinica = await obtener_clinica(sesion["clinica_id"])

    async with async_session() as session:
        p = (await session.execute(
            select(Paciente).where(Paciente.id == paciente_id).where(Paciente.clinica_id == clinica.id)
        )).scalar_one_or_none()
        if not p:
            return HTMLResponse("<h1>Paciente no encontrado</h1>", status_code=404)

    def esc(s): return html.escape(s or "", quote=True)
    return HTMLResponse(f"""<!DOCTYPE html>
<html lang="es"><head><meta charset="UTF-8"><title>Editar {esc(p.nombre)}</title>{CSS_CLINIC}</head>
<body>
  <div class="app-wrap">
    {sidebar_clinic("pacientes", sesion, clinica)}
    <main class="main">
      <a href="/clinic/app/pacientes/{p.id}" style="font-size:13px;color:var(--text-soft);">← Volver al paciente</a>
      <h1 style="font-size:26px;font-weight:800;margin:8px 0 24px;">Editar paciente</h1>
      <div class="card" style="max-width:680px;">
        <form method="post" action="/clinic/app/pacientes/{p.id}/editar" style="display:flex;flex-direction:column;gap:16px;">
          <div>
            <label style="font-size:12px;font-weight:700;display:block;margin-bottom:5px;">Nombre completo *</label>
            <input type="text" name="nombre" value="{esc(p.nombre)}" required class="input">
          </div>
          <div style="display:grid;grid-template-columns:1fr 1fr;gap:14px;">
            <div>
              <label style="font-size:12px;font-weight:700;display:block;margin-bottom:5px;">Teléfono</label>
              <input type="text" name="telefono" value="{esc(p.telefono)}" class="input">
            </div>
            <div>
              <label style="font-size:12px;font-weight:700;display:block;margin-bottom:5px;">Email</label>
              <input type="email" name="email" value="{esc(p.email)}" class="input">
            </div>
          </div>
          <div style="display:grid;grid-template-columns:1fr 1fr 1fr;gap:14px;">
            <div>
              <label style="font-size:12px;font-weight:700;display:block;margin-bottom:5px;">Documento</label>
              <input type="text" name="documento" value="{esc(p.documento)}" class="input">
            </div>
            <div>
              <label style="font-size:12px;font-weight:700;display:block;margin-bottom:5px;">Género</label>
              <select name="genero" class="input">
                <option value="" {'selected' if not p.genero else ''}>—</option>
                <option value="M" {'selected' if p.genero == 'M' else ''}>Masculino</option>
                <option value="F" {'selected' if p.genero == 'F' else ''}>Femenino</option>
                <option value="O" {'selected' if p.genero == 'O' else ''}>Otro</option>
              </select>
            </div>
            <div>
              <label style="font-size:12px;font-weight:700;display:block;margin-bottom:5px;">Estado</label>
              <select name="estado" class="input">
                <option value="nuevo" {'selected' if p.estado == 'nuevo' else ''}>Nuevo</option>
                <option value="activo" {'selected' if p.estado == 'activo' else ''}>Activo</option>
                <option value="inactivo" {'selected' if p.estado == 'inactivo' else ''}>Inactivo</option>
                <option value="dado_de_alta" {'selected' if p.estado == 'dado_de_alta' else ''}>Dado de alta</option>
              </select>
            </div>
          </div>
          <div>
            <label style="font-size:12px;font-weight:700;display:block;margin-bottom:5px;">Tratamiento actual</label>
            <input type="text" name="tratamiento_actual" value="{esc(p.tratamiento_actual)}" class="input">
          </div>
          <div>
            <label style="font-size:12px;font-weight:700;display:block;margin-bottom:5px;">Alergias</label>
            <input type="text" name="alergias" value="{esc(p.alergias)}" class="input">
          </div>
          <div>
            <label style="font-size:12px;font-weight:700;display:block;margin-bottom:5px;">Notas</label>
            <textarea name="notas_basicas" rows="4" class="input" style="resize:vertical;font-family:inherit;">{esc(p.notas_basicas)}</textarea>
          </div>
          <div style="display:flex;gap:10px;margin-top:8px;justify-content:space-between;">
            <div style="display:flex;gap:10px;">
              <button type="submit" class="btn btn-primary">Guardar cambios</button>
              <a href="/clinic/app/pacientes/{p.id}" class="btn btn-ghost">Cancelar</a>
            </div>
            <form method="post" action="/clinic/app/pacientes/{p.id}/eliminar"
                  onsubmit="return confirm('¿Eliminar paciente {esc(p.nombre)}? Esta acción NO se puede deshacer.');">
              <button type="submit" style="background:transparent;color:#EF4444;border:1.5px solid #EF4444;padding:12px 22px;border-radius:10px;font-weight:600;cursor:pointer;">🗑️ Eliminar</button>
            </form>
          </div>
        </form>
      </div>
    </main>
  </div>
</body></html>""")


@router.post("/app/pacientes/{paciente_id}/editar", response_class=HTMLResponse)
async def editar_paciente_procesar(
    paciente_id: int,
    nombre: str = Form(...),
    telefono: str = Form(""),
    email: str = Form(""),
    documento: str = Form(""),
    genero: str = Form(""),
    estado: str = Form("nuevo"),
    tratamiento_actual: str = Form(""),
    alergias: str = Form(""),
    notas_basicas: str = Form(""),
    clinic_session: Optional[str] = Cookie(None),
):
    sesion = obtener_sesion(clinic_session)
    if not sesion:
        return RedirectResponse("/clinic/login", status_code=303)

    async with async_session() as session:
        p = (await session.execute(
            select(Paciente)
            .where(Paciente.id == paciente_id)
            .where(Paciente.clinica_id == sesion["clinica_id"])
        )).scalar_one_or_none()
        if not p:
            return HTMLResponse("<h1>Paciente no encontrado</h1>", status_code=404)
        p.nombre = nombre.strip()
        p.telefono = telefono.strip()
        p.email = email.strip().lower()
        p.documento = documento.strip()
        p.genero = genero
        p.estado = estado
        p.tratamiento_actual = tratamiento_actual.strip()
        p.alergias = alergias.strip()
        p.notas_basicas = notas_basicas.strip()
        await session.commit()

    return RedirectResponse(f"/clinic/app/pacientes/{paciente_id}", status_code=303)


@router.post("/app/pacientes/{paciente_id}/eliminar", response_class=HTMLResponse)
async def eliminar_paciente(
    paciente_id: int,
    clinic_session: Optional[str] = Cookie(None),
):
    sesion = obtener_sesion(clinic_session)
    if not sesion:
        return RedirectResponse("/clinic/login", status_code=303)

    async with async_session() as session:
        p = (await session.execute(
            select(Paciente)
            .where(Paciente.id == paciente_id)
            .where(Paciente.clinica_id == sesion["clinica_id"])
        )).scalar_one_or_none()
        if p:
            await session.delete(p)
            await session.commit()

    return RedirectResponse("/clinic/app/pacientes", status_code=303)


# ════════════════════════════════════════════════════════════
# 7) LLAMADAS, PLANTILLAS, CONFIG — mockups MVP
# ════════════════════════════════════════════════════════════

def _vista_simple(titulo: str, descripcion: str, icono: str, cta_url: str, cta_label: str, sesion: dict, clinica: Clinica, activa: str) -> HTMLResponse:
    return HTMLResponse(f"""<!DOCTYPE html>
<html lang="es"><head><meta charset="UTF-8"><title>{html.escape(titulo)} - Lapora Clinic</title>{CSS_CLINIC}</head>
<body>
  <div class="app-wrap">
    {sidebar_clinic(activa, sesion, clinica)}
    <main class="main">
      <h1 style="font-size:26px;font-weight:800;margin-bottom:4px;">{html.escape(titulo)}</h1>
      <p style="color:var(--text-soft);margin-bottom:24px;">{html.escape(descripcion)}</p>
      <div class="card" style="text-align:center;padding:60px 20px;">
        <div style="font-size:64px;margin-bottom:16px;">{icono}</div>
        <p style="color:var(--text-soft);max-width:400px;margin:0 auto 24px;">Esta sección se habilita en los próximos días del MVP.</p>
        <a href="{cta_url}" class="btn btn-primary">{html.escape(cta_label)}</a>
      </div>
    </main>
  </div>
</body></html>""")


# ════════════════════════════════════════════════════════════
# 7) LLAMADAS — Bitácora con CRUD
# ════════════════════════════════════════════════════════════

@router.get("/app/llamadas", response_class=HTMLResponse)
async def vista_llamadas(
    creado: Optional[str] = None,
    clinic_session: Optional[str] = Cookie(None),
):
    sesion = obtener_sesion(clinic_session)
    if not sesion:
        return RedirectResponse("/clinic/login", status_code=303)
    clinica = await obtener_clinica(sesion["clinica_id"])

    async with async_session() as session:
        llamadas = list((await session.execute(
            select(Llamada).where(Llamada.clinica_id == clinica.id).order_by(desc(Llamada.timestamp)).limit(200)
        )).scalars().all())
        # Pre-cargar nombres de pacientes
        pids = [l.paciente_id for l in llamadas if l.paciente_id]
        nombres = {}
        if pids:
            for p in (await session.execute(
                select(Paciente.id, Paciente.nombre).where(Paciente.id.in_(pids))
            )).all():
                nombres[p[0]] = p[1]

    icon_dir = {"entrada": "📥", "salida": "📤", "perdida": "❌"}
    color_resultado = {
        "interesado": "#10B981", "agendado": "#3B82F6",
        "no_interesado": "#EF4444", "volver_a_llamar": "#F59E0B",
    }

    if llamadas:
        filas = ""
        for l in llamadas:
            nombre = html.escape(nombres.get(l.paciente_id, "—"))
            dir_icon = icon_dir.get(l.direccion, "📞")
            duracion = f"{l.duracion_seg // 60}:{l.duracion_seg % 60:02d}" if l.duracion_seg else "—"
            color_r = color_resultado.get(l.resultado, "#78716C")
            resultado = html.escape(l.resultado or "—")
            ts = l.timestamp.strftime("%d/%m %H:%M") if l.timestamp else "—"
            notas = html.escape((l.notas or "")[:80])
            filas += f"""
              <tr style="border-bottom:1px solid var(--border);">
                <td style="padding:14px;font-size:18px;">{dir_icon}</td>
                <td style="padding:14px;">
                  <a href="/clinic/app/pacientes/{l.paciente_id}" style="font-weight:600;color:var(--text);">{nombre}</a>
                  <div style="font-size:12px;color:var(--text-soft);margin-top:2px;">{notas}</div>
                </td>
                <td style="padding:14px;color:var(--text-soft);font-family:monospace;">{duracion}</td>
                <td style="padding:14px;">
                  <span style="background:{color_r}20;color:{color_r};padding:3px 10px;border-radius:999px;font-size:11px;font-weight:700;text-transform:uppercase;">{resultado}</span>
                </td>
                <td style="padding:14px;color:var(--text-soft);font-size:13px;">{ts}</td>
              </tr>"""
        contenido = f"""
        <table style="width:100%;border-collapse:collapse;">
          <thead><tr style="background:#1c1917;color:white;">
            <th style="padding:14px;text-align:left;font-size:11px;text-transform:uppercase;letter-spacing:1px;width:50px;"></th>
            <th style="padding:14px;text-align:left;font-size:11px;text-transform:uppercase;letter-spacing:1px;">Paciente / Notas</th>
            <th style="padding:14px;text-align:left;font-size:11px;text-transform:uppercase;letter-spacing:1px;">Duración</th>
            <th style="padding:14px;text-align:left;font-size:11px;text-transform:uppercase;letter-spacing:1px;">Resultado</th>
            <th style="padding:14px;text-align:left;font-size:11px;text-transform:uppercase;letter-spacing:1px;">Fecha</th>
          </tr></thead>
          <tbody>{filas}</tbody>
        </table>"""
    else:
        contenido = """
        <div style="text-align:center;padding:60px 20px;color:var(--text-soft);">
          <div style="font-size:64px;margin-bottom:16px;">📞</div>
          <h3 style="font-size:18px;font-weight:700;color:var(--text);margin-bottom:8px;">Sin llamadas registradas</h3>
          <p style="margin-bottom:24px;">Registra cada llamada con tus pacientes para no perder seguimiento.</p>
          <a href="/clinic/app/llamadas/nueva" class="btn btn-primary">+ Registrar llamada</a>
        </div>"""

    banner = ""
    if creado:
        banner = '<div style="background:#ECFDF5;border:1px solid #10B981;color:#065F46;padding:12px 16px;border-radius:10px;margin-bottom:16px;font-size:14px;font-weight:600;">✓ Llamada registrada correctamente</div>'

    return HTMLResponse(f"""<!DOCTYPE html>
<html lang="es"><head><meta charset="UTF-8"><title>Llamadas - Lapora Clinic</title>{CSS_CLINIC}</head>
<body>
  <div class="app-wrap">
    {sidebar_clinic("llamadas", sesion, clinica)}
    <main class="main">
      <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:20px;">
        <div>
          <h1 style="font-size:26px;font-weight:800;margin-bottom:4px;">Llamadas</h1>
          <p style="color:var(--text-soft);">{len(llamadas)} llamadas registradas</p>
        </div>
        <a href="/clinic/app/llamadas/nueva" class="btn btn-primary">+ Registrar llamada</a>
      </div>
      {banner}
      <div class="card" style="padding:0;overflow:hidden;">{contenido}</div>
    </main>
  </div>
</body></html>""")


@router.get("/app/llamadas/nueva", response_class=HTMLResponse)
async def nueva_llamada_form(clinic_session: Optional[str] = Cookie(None)):
    sesion = obtener_sesion(clinic_session)
    if not sesion:
        return RedirectResponse("/clinic/login", status_code=303)
    clinica = await obtener_clinica(sesion["clinica_id"])

    async with async_session() as session:
        pacientes = list((await session.execute(
            select(Paciente).where(Paciente.clinica_id == clinica.id).order_by(Paciente.nombre).limit(500)
        )).scalars().all())

    opciones = "".join(f'<option value="{p.id}">{html.escape(p.nombre)} ({html.escape(p.telefono or "")})</option>' for p in pacientes)

    return HTMLResponse(f"""<!DOCTYPE html>
<html lang="es"><head><meta charset="UTF-8"><title>Nueva llamada - Lapora Clinic</title>{CSS_CLINIC}</head>
<body>
  <div class="app-wrap">
    {sidebar_clinic("llamadas", sesion, clinica)}
    <main class="main">
      <a href="/clinic/app/llamadas" style="font-size:13px;color:var(--text-soft);">← Volver</a>
      <h1 style="font-size:26px;font-weight:800;margin:8px 0 24px;">Registrar llamada</h1>
      <div class="card" style="max-width:560px;">
        <form method="post" action="/clinic/app/llamadas/nueva" style="display:flex;flex-direction:column;gap:16px;">
          <div>
            <label style="font-size:12px;font-weight:700;display:block;margin-bottom:5px;">Paciente *</label>
            <select name="paciente_id" required class="input" autofocus>
              <option value="">Selecciona un paciente...</option>
              {opciones}
            </select>
            {('<p style="font-size:12px;color:var(--text-soft);margin-top:6px;">No tienes pacientes todavía. <a href="/clinic/app/pacientes/nuevo">Crear uno</a> primero.</p>' if not pacientes else '')}
          </div>
          <div style="display:grid;grid-template-columns:1fr 1fr;gap:14px;">
            <div>
              <label style="font-size:12px;font-weight:700;display:block;margin-bottom:5px;">Dirección</label>
              <select name="direccion" class="input">
                <option value="entrada">📥 Entrada</option>
                <option value="salida">📤 Salida</option>
                <option value="perdida">❌ Perdida</option>
              </select>
            </div>
            <div>
              <label style="font-size:12px;font-weight:700;display:block;margin-bottom:5px;">Duración (min)</label>
              <input type="number" name="duracion_min" min="0" placeholder="5" class="input">
            </div>
          </div>
          <div>
            <label style="font-size:12px;font-weight:700;display:block;margin-bottom:5px;">Resultado</label>
            <select name="resultado" class="input">
              <option value="">—</option>
              <option value="interesado">✓ Interesado</option>
              <option value="agendado">📅 Agendado</option>
              <option value="volver_a_llamar">🔄 Volver a llamar</option>
              <option value="no_interesado">✗ No interesado</option>
            </select>
          </div>
          <div>
            <label style="font-size:12px;font-weight:700;display:block;margin-bottom:5px;">Notas</label>
            <textarea name="notas" rows="4" class="input" style="resize:vertical;font-family:inherit;"
                      placeholder="Qué pidió el paciente, qué se acordó, próximos pasos..."></textarea>
          </div>
          <div style="display:flex;gap:10px;">
            <button type="submit" class="btn btn-primary" {('disabled' if not pacientes else '')}>Guardar</button>
            <a href="/clinic/app/llamadas" class="btn btn-ghost">Cancelar</a>
          </div>
        </form>
      </div>
    </main>
  </div>
</body></html>""")


@router.post("/app/llamadas/nueva", response_class=HTMLResponse)
async def nueva_llamada_procesar(
    paciente_id: int = Form(...),
    direccion: str = Form("entrada"),
    duracion_min: int = Form(0),
    resultado: str = Form(""),
    notas: str = Form(""),
    clinic_session: Optional[str] = Cookie(None),
):
    sesion = obtener_sesion(clinic_session)
    if not sesion:
        return RedirectResponse("/clinic/login", status_code=303)

    async with async_session() as session:
        session.add(Llamada(
            clinica_id=sesion["clinica_id"],
            paciente_id=paciente_id,
            direccion=direccion,
            duracion_seg=duracion_min * 60,
            resultado=resultado,
            notas=notas.strip(),
        ))
        await session.commit()

    return RedirectResponse("/clinic/app/llamadas?creado=1", status_code=303)


# ════════════════════════════════════════════════════════════
# 8) PLANTILLAS — Respuestas rápidas
# ════════════════════════════════════════════════════════════

@router.get("/app/plantillas", response_class=HTMLResponse)
async def vista_plantillas(
    creado: Optional[str] = None,
    clinic_session: Optional[str] = Cookie(None),
):
    sesion = obtener_sesion(clinic_session)
    if not sesion:
        return RedirectResponse("/clinic/login", status_code=303)
    clinica = await obtener_clinica(sesion["clinica_id"])

    async with async_session() as session:
        plantillas = list((await session.execute(
            select(PlantillaRespuesta).where(PlantillaRespuesta.clinica_id == clinica.id)
            .order_by(desc(PlantillaRespuesta.usos))
        )).scalars().all())

    if plantillas:
        cards = ""
        for pl in plantillas:
            cards += f"""
            <div class="card" style="margin-bottom:12px;">
              <div style="display:flex;justify-content:space-between;align-items:start;gap:14px;">
                <div style="flex:1;">
                  <h3 style="font-size:15px;font-weight:700;margin-bottom:4px;">{html.escape(pl.titulo)}</h3>
                  <div style="font-size:12px;color:var(--text-soft);margin-bottom:10px;">
                    Categoría: {html.escape(pl.categoria or "general")} · Usada {pl.usos} veces
                  </div>
                  <p style="font-size:14px;line-height:1.5;color:var(--text);white-space:pre-wrap;">{html.escape(pl.contenido)}</p>
                </div>
                <form method="post" action="/clinic/app/plantillas/{pl.id}/eliminar"
                      onsubmit="return confirm('¿Eliminar esta plantilla?');">
                  <button type="submit" style="background:transparent;color:#EF4444;border:1px solid #EF4444;padding:6px 12px;border-radius:8px;font-size:12px;font-weight:600;cursor:pointer;">🗑️</button>
                </form>
              </div>
            </div>"""
        contenido = cards
    else:
        contenido = """
        <div class="card" style="text-align:center;padding:60px 20px;color:var(--text-soft);">
          <div style="font-size:64px;margin-bottom:16px;">📝</div>
          <h3 style="font-size:18px;font-weight:700;color:var(--text);margin-bottom:8px;">Sin plantillas todavía</h3>
          <p style="margin-bottom:24px;">Crea respuestas rápidas para preguntas frecuentes (precios, horarios, ubicación).</p>
          <a href="/clinic/app/plantillas/nueva" class="btn btn-primary">+ Crear plantilla</a>
        </div>"""

    banner = ""
    if creado:
        banner = '<div style="background:#ECFDF5;border:1px solid #10B981;color:#065F46;padding:12px 16px;border-radius:10px;margin-bottom:16px;font-size:14px;font-weight:600;">✓ Plantilla guardada correctamente</div>'

    return HTMLResponse(f"""<!DOCTYPE html>
<html lang="es"><head><meta charset="UTF-8"><title>Plantillas - Lapora Clinic</title>{CSS_CLINIC}</head>
<body>
  <div class="app-wrap">
    {sidebar_clinic("plantillas", sesion, clinica)}
    <main class="main">
      <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:20px;">
        <div>
          <h1 style="font-size:26px;font-weight:800;margin-bottom:4px;">Plantillas</h1>
          <p style="color:var(--text-soft);">{len(plantillas)} respuestas rápidas</p>
        </div>
        <a href="/clinic/app/plantillas/nueva" class="btn btn-primary">+ Nueva plantilla</a>
      </div>
      {banner}
      {contenido}
    </main>
  </div>
</body></html>""")


@router.get("/app/plantillas/nueva", response_class=HTMLResponse)
async def nueva_plantilla_form(clinic_session: Optional[str] = Cookie(None)):
    sesion = obtener_sesion(clinic_session)
    if not sesion:
        return RedirectResponse("/clinic/login", status_code=303)
    clinica = await obtener_clinica(sesion["clinica_id"])

    return HTMLResponse(f"""<!DOCTYPE html>
<html lang="es"><head><meta charset="UTF-8"><title>Nueva plantilla - Lapora Clinic</title>{CSS_CLINIC}</head>
<body>
  <div class="app-wrap">
    {sidebar_clinic("plantillas", sesion, clinica)}
    <main class="main">
      <a href="/clinic/app/plantillas" style="font-size:13px;color:var(--text-soft);">← Volver</a>
      <h1 style="font-size:26px;font-weight:800;margin:8px 0 24px;">Nueva plantilla</h1>
      <div class="card" style="max-width:680px;">
        <form method="post" action="/clinic/app/plantillas/nueva" style="display:flex;flex-direction:column;gap:16px;">
          <div>
            <label style="font-size:12px;font-weight:700;display:block;margin-bottom:5px;">Título *</label>
            <input type="text" name="titulo" required placeholder="Ej: Saludo inicial" class="input" autofocus>
          </div>
          <div>
            <label style="font-size:12px;font-weight:700;display:block;margin-bottom:5px;">Categoría</label>
            <select name="categoria" class="input">
              <option value="general">General</option>
              <option value="saludo">Saludo</option>
              <option value="precios">Precios</option>
              <option value="horarios">Horarios</option>
              <option value="ubicacion">Ubicación</option>
              <option value="confirmacion">Confirmación</option>
              <option value="seguimiento">Seguimiento</option>
            </select>
          </div>
          <div>
            <label style="font-size:12px;font-weight:700;display:block;margin-bottom:5px;">Contenido *</label>
            <textarea name="contenido" required rows="6" class="input" style="resize:vertical;font-family:inherit;"
                      placeholder="¡Hola! Gracias por escribir a {{clinica}}. ¿En qué puedo ayudarte hoy?"></textarea>
            <p style="font-size:12px;color:var(--text-soft);margin-top:6px;">
              💡 Tip: Usá <code>{{nombre}}</code>, <code>{{clinica}}</code>, <code>{{tratamiento}}</code> como variables.
            </p>
          </div>
          <div style="display:flex;gap:10px;">
            <button type="submit" class="btn btn-primary">Guardar plantilla</button>
            <a href="/clinic/app/plantillas" class="btn btn-ghost">Cancelar</a>
          </div>
        </form>
      </div>
    </main>
  </div>
</body></html>""")


@router.post("/app/plantillas/nueva", response_class=HTMLResponse)
async def nueva_plantilla_procesar(
    titulo: str = Form(...),
    categoria: str = Form("general"),
    contenido: str = Form(...),
    clinic_session: Optional[str] = Cookie(None),
):
    sesion = obtener_sesion(clinic_session)
    if not sesion:
        return RedirectResponse("/clinic/login", status_code=303)

    async with async_session() as session:
        session.add(PlantillaRespuesta(
            clinica_id=sesion["clinica_id"],
            titulo=titulo.strip(),
            categoria=categoria,
            contenido=contenido.strip(),
        ))
        await session.commit()

    return RedirectResponse("/clinic/app/plantillas?creado=1", status_code=303)


@router.post("/app/plantillas/{pid}/eliminar")
async def eliminar_plantilla(pid: int, clinic_session: Optional[str] = Cookie(None)):
    sesion = obtener_sesion(clinic_session)
    if not sesion:
        return RedirectResponse("/clinic/login", status_code=303)

    async with async_session() as session:
        pl = (await session.execute(
            select(PlantillaRespuesta)
            .where(PlantillaRespuesta.id == pid)
            .where(PlantillaRespuesta.clinica_id == sesion["clinica_id"])
        )).scalar_one_or_none()
        if pl:
            await session.delete(pl)
            await session.commit()

    return RedirectResponse("/clinic/app/plantillas", status_code=303)


# ════════════════════════════════════════════════════════════
# 9) CONFIGURACIÓN — Integraciones y branding
# ════════════════════════════════════════════════════════════

@router.get("/app/configuracion", response_class=HTMLResponse)
async def vista_config(
    guardado: Optional[str] = None,
    sync_creados: Optional[int] = None,
    sync_actualizados: Optional[int] = None,
    error: Optional[str] = None,
    clinic_session: Optional[str] = Cookie(None),
):
    sesion = obtener_sesion(clinic_session)
    if not sesion:
        return RedirectResponse("/clinic/login", status_code=303)
    clinica = await obtener_clinica(sesion["clinica_id"])

    def esc(s): return html.escape(s or "", quote=True)
    wa_conectado = bool(clinica.whatsapp_phone_id)
    ig_conectado = bool(clinica.instagram_account_id)
    sheets_conectado = bool(clinica.google_sheet_id)

    banner = ""
    if error:
        banner = f'<div style="background:#FEE2E2;border:1px solid #EF4444;color:#7F1D1D;padding:12px 16px;border-radius:10px;margin-bottom:16px;font-size:14px;">⚠ {html.escape(error)}</div>'
    elif sync_creados is not None or sync_actualizados is not None:
        banner = f'<div style="background:#ECFDF5;border:1px solid #10B981;color:#065F46;padding:12px 16px;border-radius:10px;margin-bottom:16px;font-size:14px;font-weight:600;">✓ Sincronización completa: <strong>{sync_creados or 0}</strong> nuevos pacientes · <strong>{sync_actualizados or 0}</strong> actualizados</div>'
    elif guardado:
        banner = '<div style="background:#ECFDF5;border:1px solid #10B981;color:#065F46;padding:12px 16px;border-radius:10px;margin-bottom:16px;font-size:14px;font-weight:600;">✓ Configuración guardada</div>'

    return HTMLResponse(f"""<!DOCTYPE html>
<html lang="es"><head><meta charset="UTF-8"><title>Configuración - Lapora Clinic</title>{CSS_CLINIC}</head>
<body>
  <div class="app-wrap">
    {sidebar_clinic("config", sesion, clinica)}
    <main class="main">
      <h1 style="font-size:26px;font-weight:800;margin-bottom:4px;">Configuración</h1>
      <p style="color:var(--text-soft);margin-bottom:24px;">Conecta tus canales y personaliza tu cuenta</p>
      {banner}

      <form method="post" action="/clinic/app/configuracion" style="display:flex;flex-direction:column;gap:18px;max-width:780px;">

        <!-- DATOS BASE -->
        <div class="card">
          <h2 style="font-size:16px;font-weight:700;margin-bottom:14px;">📋 Datos del consultorio</h2>
          <div style="display:grid;grid-template-columns:2fr 1fr;gap:14px;">
            <div>
              <label style="font-size:12px;font-weight:700;display:block;margin-bottom:5px;">Nombre</label>
              <input type="text" name="nombre" value="{esc(clinica.nombre)}" class="input">
            </div>
            <div>
              <label style="font-size:12px;font-weight:700;display:block;margin-bottom:5px;">Ciudad</label>
              <input type="text" name="ciudad" value="{esc(clinica.ciudad)}" class="input">
            </div>
          </div>
          <div style="margin-top:12px;">
            <label style="font-size:12px;font-weight:700;display:block;margin-bottom:5px;">Especialidad</label>
            <input type="text" name="especialidad" value="{esc(clinica.especialidad)}" class="input">
          </div>
        </div>

        <!-- WHATSAPP -->
        <div class="card">
          <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:14px;">
            <h2 style="font-size:16px;font-weight:700;">💬 WhatsApp Business Cloud API</h2>
            <span class="badge {'badge-pro' if wa_conectado else 'badge-free'}">{'CONECTADO' if wa_conectado else 'NO CONECTADO'}</span>
          </div>
          <p style="font-size:13px;color:var(--text-soft);margin-bottom:14px;">
            Conectá tu número de WhatsApp Business para recibir mensajes en el inbox. <br>
            Necesitás <a href="https://developers.facebook.com" target="_blank">credenciales de Meta for Developers</a>.
          </p>
          <div style="display:grid;grid-template-columns:1fr 1fr;gap:14px;">
            <div>
              <label style="font-size:12px;font-weight:700;display:block;margin-bottom:5px;">Phone Number ID</label>
              <input type="text" name="whatsapp_phone_id" value="{esc(clinica.whatsapp_phone_id)}" placeholder="123456789012345" class="input">
            </div>
            <div>
              <label style="font-size:12px;font-weight:700;display:block;margin-bottom:5px;">Access Token</label>
              <input type="password" name="whatsapp_token" value="{esc(clinica.whatsapp_token)}" placeholder="EAAm..." class="input">
            </div>
          </div>
        </div>

        <!-- INSTAGRAM -->
        <div class="card">
          <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:14px;">
            <h2 style="font-size:16px;font-weight:700;">📷 Instagram DMs</h2>
            <span class="badge {'badge-pro' if ig_conectado else 'badge-free'}">{'CONECTADO' if ig_conectado else 'NO CONECTADO'}</span>
          </div>
          <p style="font-size:13px;color:var(--text-soft);margin-bottom:14px;">
            Recibí mensajes directos de Instagram en el inbox unificado.
          </p>
          <div style="display:grid;grid-template-columns:1fr 1fr;gap:14px;">
            <div>
              <label style="font-size:12px;font-weight:700;display:block;margin-bottom:5px;">Instagram Account ID</label>
              <input type="text" name="instagram_account_id" value="{esc(clinica.instagram_account_id)}" class="input">
            </div>
            <div>
              <label style="font-size:12px;font-weight:700;display:block;margin-bottom:5px;">Access Token</label>
              <input type="password" name="instagram_token" value="{esc(clinica.instagram_token)}" class="input">
            </div>
          </div>
        </div>

        <!-- GOOGLE SHEETS -->
        <div class="card">
          <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:14px;">
            <h2 style="font-size:16px;font-weight:700;">📊 Google Sheets — Sync de pacientes</h2>
            <span class="badge {'badge-pro' if sheets_conectado else 'badge-free'}">{'CONECTADO' if sheets_conectado else 'NO CONECTADO'}</span>
          </div>
          <p style="font-size:13px;color:var(--text-soft);margin-bottom:14px;">
            Sincronizá tus pacientes desde una hoja de Google Sheets. La hoja debe tener columnas:
            <code>nombre, telefono, email, tratamiento, notas</code>.
          </p>
          <label style="font-size:12px;font-weight:700;display:block;margin-bottom:5px;">Sheet ID o URL completa</label>
          <input type="text" name="google_sheet_id" value="{esc(clinica.google_sheet_id)}" placeholder="https://docs.google.com/spreadsheets/d/..." class="input">
          <p style="font-size:12px;color:var(--text-soft);margin-top:8px;">
            📌 La hoja debe estar configurada como <strong>"Cualquiera con el enlace puede ver"</strong>.
          </p>
          {('<button type="button" onclick="syncSheets()" style="background:#3B82F6;color:white;border:none;padding:10px 18px;border-radius:8px;font-size:13px;font-weight:600;cursor:pointer;margin-top:12px;">↻ Sincronizar ahora</button>' if clinica.google_sheet_id else '')}
        </div>

        <!-- BRANDING (solo Pro y Studio) -->
        <div class="card">
          <h2 style="font-size:16px;font-weight:700;margin-bottom:6px;">🎨 Branding</h2>
          <p style="font-size:13px;color:var(--text-soft);margin-bottom:14px;">
            {('Plan Studio: tu logo + dominio propio.' if clinica.plan == 'studio' else
              'Plan Pro: personalizá colores y logo. <a href="#">Upgrade</a> para dominio propio.' if clinica.plan == 'pro' else
              'Plan Free: incluye marca Lapora. <a href="#">Upgrade a Pro</a> para personalizar.')}
          </p>
          <div style="display:grid;grid-template-columns:1fr 1fr;gap:14px;">
            <div>
              <label style="font-size:12px;font-weight:700;display:block;margin-bottom:5px;">URL del logo</label>
              <input type="url" name="logo_url" value="{esc(clinica.logo_url)}" placeholder="https://..." class="input" {'disabled' if clinica.plan == 'free' else ''}>
            </div>
            <div>
              <label style="font-size:12px;font-weight:700;display:block;margin-bottom:5px;">Color primario</label>
              <input type="color" name="color_primario" value="{esc(clinica.color_primario) or '#FF3B30'}" class="input" style="height:46px;" {'disabled' if clinica.plan == 'free' else ''}>
            </div>
          </div>
        </div>

        <div style="display:flex;justify-content:flex-end;gap:10px;">
          <a href="/clinic/app/" class="btn btn-ghost">Cancelar</a>
          <button type="submit" class="btn btn-primary">Guardar configuración</button>
        </div>
      </form>

      <script>
        function syncSheets() {{
          if (!confirm('¿Sincronizar pacientes desde Google Sheets ahora?')) return;
          fetch('/clinic/app/configuracion/sync-sheets', {{ method: 'POST', credentials: 'same-origin' }})
            .then(() => window.location.reload())
            .catch(e => alert('Error: ' + e));
        }}
      </script>
    </main>
  </div>
</body></html>""")


@router.post("/app/configuracion", response_class=HTMLResponse)
async def guardar_config(
    nombre: str = Form(""),
    ciudad: str = Form(""),
    especialidad: str = Form(""),
    whatsapp_phone_id: str = Form(""),
    whatsapp_token: str = Form(""),
    instagram_account_id: str = Form(""),
    instagram_token: str = Form(""),
    google_sheet_id: str = Form(""),
    logo_url: str = Form(""),
    color_primario: str = Form("#FF3B30"),
    clinic_session: Optional[str] = Cookie(None),
):
    sesion = obtener_sesion(clinic_session)
    if not sesion:
        return RedirectResponse("/clinic/login", status_code=303)

    async with async_session() as session:
        c = (await session.execute(
            select(Clinica).where(Clinica.id == sesion["clinica_id"])
        )).scalar_one_or_none()
        if c:
            if nombre.strip(): c.nombre = nombre.strip()
            c.ciudad = ciudad.strip()
            c.especialidad = especialidad.strip()
            # Solo guardar token nuevo si lo enviaron (no sobrescribir con vacío)
            if whatsapp_phone_id.strip(): c.whatsapp_phone_id = whatsapp_phone_id.strip()
            if whatsapp_token.strip(): c.whatsapp_token = whatsapp_token.strip()
            if instagram_account_id.strip(): c.instagram_account_id = instagram_account_id.strip()
            if instagram_token.strip(): c.instagram_token = instagram_token.strip()
            c.google_sheet_id = google_sheet_id.strip()
            if c.plan != "free":
                c.logo_url = logo_url.strip()
                c.color_primario = color_primario
            c.actualizado_en = datetime.utcnow()
            await session.commit()

    return RedirectResponse("/clinic/app/configuracion?guardado=1", status_code=303)


# ════════════════════════════════════════════════════════════
# 10) SYNC GOOGLE SHEETS — Import pacientes desde una hoja publica
# ════════════════════════════════════════════════════════════

@router.post("/app/configuracion/sync-sheets", response_class=HTMLResponse)
async def sync_google_sheets(clinic_session: Optional[str] = Cookie(None)):
    """Sincroniza pacientes desde la URL de Google Sheets configurada.

    La hoja debe estar publicada como CSV (Archivo > Compartir > Publicar en web > CSV).
    Columnas esperadas (case-insensitive): nombre, telefono, email, tratamiento, notas
    """
    sesion = obtener_sesion(clinic_session)
    if not sesion:
        return RedirectResponse("/clinic/login", status_code=303)

    async with async_session() as session:
        clinica = (await session.execute(
            select(Clinica).where(Clinica.id == sesion["clinica_id"])
        )).scalar_one_or_none()
        if not clinica or not clinica.google_sheet_id:
            return RedirectResponse(
                "/clinic/app/configuracion?error=Configura+primero+el+Sheet+ID",
                status_code=303,
            )

        # Convertir URL/ID a URL de export CSV
        import re as _re_sh
        sheet_input = clinica.google_sheet_id.strip()
        # Si es URL completa, extraer ID
        m = _re_sh.search(r"/d/([a-zA-Z0-9_-]+)", sheet_input)
        sheet_id = m.group(1) if m else sheet_input
        csv_url = f"https://docs.google.com/spreadsheets/d/{sheet_id}/export?format=csv"

        # Descargar
        try:
            import httpx as _httpx_sh
            async with _httpx_sh.AsyncClient(timeout=20.0, follow_redirects=True) as client:
                resp = await client.get(csv_url)
            if resp.status_code != 200:
                return RedirectResponse(
                    f"/clinic/app/configuracion?error=No+se+pudo+descargar+(HTTP+{resp.status_code}).+Hace+publica+la+hoja",
                    status_code=303,
                )
            contenido_csv = resp.text
        except Exception as e:
            return RedirectResponse(
                f"/clinic/app/configuracion?error=Error+descargando:+{html.escape(str(e)[:60])}",
                status_code=303,
            )

        # Parsear CSV y hacer upsert
        import csv as _csv
        from io import StringIO
        reader = _csv.DictReader(StringIO(contenido_csv))
        # Normalizar headers (lowercase, sin acentos)
        if reader.fieldnames:
            reader.fieldnames = [
                (h or "").lower().strip()
                .replace("é", "e").replace("ó", "o").replace("í", "i")
                .replace("á", "a").replace("ú", "u").replace("ñ", "n")
                for h in reader.fieldnames
            ]

        creados = actualizados = 0
        ahora = datetime.utcnow()
        for row in reader:
            nombre = (row.get("nombre") or row.get("name") or "").strip()
            if not nombre:
                continue
            telefono = (row.get("telefono") or row.get("teléfono") or row.get("phone") or "").strip()
            email = (row.get("email") or row.get("correo") or "").strip().lower()
            tratamiento = (row.get("tratamiento") or row.get("tratamiento_actual") or "").strip()
            notas = (row.get("notas") or row.get("notes") or "").strip()

            # Upsert por telefono o email
            existing = None
            if telefono:
                existing = (await session.execute(
                    select(Paciente)
                    .where(Paciente.clinica_id == clinica.id)
                    .where(Paciente.telefono == telefono)
                )).scalar_one_or_none()
            if not existing and email:
                existing = (await session.execute(
                    select(Paciente)
                    .where(Paciente.clinica_id == clinica.id)
                    .where(Paciente.email == email)
                )).scalar_one_or_none()

            if existing:
                existing.nombre = nombre
                if telefono: existing.telefono = telefono
                if email: existing.email = email
                if tratamiento: existing.tratamiento_actual = tratamiento
                if notas: existing.notas_basicas = notas
                existing.ultimo_contacto = ahora
                actualizados += 1
            else:
                session.add(Paciente(
                    clinica_id=clinica.id,
                    nombre=nombre,
                    telefono=telefono,
                    email=email,
                    tratamiento_actual=tratamiento,
                    notas_basicas=notas,
                    fuente="sheets",
                    estado="nuevo",
                    primer_contacto=ahora,
                    ultimo_contacto=ahora,
                ))
                creados += 1

        await session.commit()

    return RedirectResponse(
        f"/clinic/app/configuracion?guardado=1&sync_creados={creados}&sync_actualizados={actualizados}",
        status_code=303,
    )


# ════════════════════════════════════════════════════════════
# 11) WEBHOOK — Receptor de mensajes WhatsApp por clínica
# ════════════════════════════════════════════════════════════

@router.get("/webhook/whatsapp/{slug}")
async def webhook_whatsapp_verify(slug: str, request: Request):
    """Verificación inicial del webhook por Meta (hub.challenge)."""
    params = dict(request.query_params)
    mode = params.get("hub.mode")
    token = params.get("hub.verify_token")
    challenge = params.get("hub.challenge")

    async with async_session() as session:
        clinica = (await session.execute(
            select(Clinica).where(Clinica.slug == slug)
        )).scalar_one_or_none()

    # Verify token = el ID del WhatsApp Phone Number ID (simple y suficiente)
    if mode == "subscribe" and clinica and token == clinica.whatsapp_phone_id:
        from fastapi.responses import PlainTextResponse
        return PlainTextResponse(str(challenge or ""))
    return HTMLResponse("Forbidden", status_code=403)


@router.post("/webhook/whatsapp/{slug}")
async def webhook_whatsapp_recibir(slug: str, request: Request):
    """Recibe mensajes WhatsApp y los guarda en el inbox de la clínica."""
    try:
        payload = await request.json()
    except Exception:
        return {"status": "ignored"}

    async with async_session() as session:
        clinica = (await session.execute(
            select(Clinica).where(Clinica.slug == slug)
        )).scalar_one_or_none()
        if not clinica:
            return {"status": "clinica no encontrada"}

        # Parsear estructura Meta Cloud API
        for entry in payload.get("entry", []):
            for change in entry.get("changes", []):
                value = change.get("value", {})
                for msg in value.get("messages", []):
                    if msg.get("type") != "text":
                        continue
                    from_tel = msg.get("from", "")
                    texto = msg.get("text", {}).get("body", "")
                    msg_id = msg.get("id", "")
                    ts = datetime.utcnow()

                    # Buscar o crear paciente por teléfono
                    paciente = (await session.execute(
                        select(Paciente)
                        .where(Paciente.clinica_id == clinica.id)
                        .where(Paciente.telefono.contains(from_tel[-10:]))
                    )).scalar_one_or_none()
                    if not paciente:
                        paciente = Paciente(
                            clinica_id=clinica.id,
                            nombre=f"WhatsApp +{from_tel}",
                            telefono=f"+{from_tel}",
                            fuente="whatsapp",
                            estado="nuevo",
                            primer_contacto=ts,
                            ultimo_contacto=ts,
                        )
                        session.add(paciente)
                        await session.flush()

                    # Guardar mensaje
                    session.add(MensajeUnificado(
                        clinica_id=clinica.id,
                        paciente_id=paciente.id,
                        canal="whatsapp",
                        direccion="entrada",
                        contenido=texto,
                        canal_msg_id=msg_id,
                        leido=False,
                        timestamp=ts,
                    ))
                    paciente.ultimo_contacto = ts
                    paciente.total_mensajes = (paciente.total_mensajes or 0) + 1

        await session.commit()
    return {"status": "ok"}


# ════════════════════════════════════════════════════════════
# 12) LANDING PUBLICO — Marketing de Lapora Clinic
# ════════════════════════════════════════════════════════════

@router.get("/landing", response_class=HTMLResponse)
async def landing_publico():
    """Página de marketing pública de Lapora Clinic con pricing."""
    return HTMLResponse(f"""<!DOCTYPE html>
<html lang="es"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1.0">
<title>Lapora Clinic — El software que tu consultorio necesita</title>
<meta name="description" content="WhatsApp + Instagram + pacientes + IA en una sola pantalla. Desde gratis.">
{CSS_CLINIC}
<style>
  .hero {{ background: linear-gradient(135deg, #FFF1F0 0%, #FFFFFF 100%); padding: 80px 24px; text-align: center; }}
  .hero h1 {{ font-size: 56px; font-weight: 900; letter-spacing: -2px; line-height: 1.05; margin-bottom: 22px; }}
  .hero h1 span {{ color: var(--primary); }}
  .hero p {{ font-size: 19px; color: var(--text-soft); max-width: 640px; margin: 0 auto 32px; line-height: 1.5; }}
  .features {{ padding: 80px 24px; max-width: 1100px; margin: 0 auto; }}
  .features-grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(260px, 1fr)); gap: 24px; }}
  .feature-card {{
    background: white; padding: 28px; border-radius: 16px;
    border: 1px solid var(--border); transition: all 0.2s;
  }}
  .feature-card:hover {{ transform: translateY(-4px); box-shadow: var(--shadow-lg); }}
  .feature-icon {{ font-size: 36px; margin-bottom: 14px; }}
  .pricing {{ padding: 60px 24px; background: var(--bg); }}
  .pricing-grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(280px, 1fr)); gap: 20px; max-width: 1000px; margin: 0 auto; }}
  .price-card {{
    background: white; padding: 32px; border-radius: 18px;
    border: 1.5px solid var(--border); position: relative;
  }}
  .price-card.featured {{ border-color: var(--primary); border-width: 2px; transform: scale(1.03); }}
  .price-tag {{ font-size: 36px; font-weight: 900; margin: 14px 0; }}
  .price-tag small {{ font-size: 14px; color: var(--text-soft); font-weight: 600; }}
  .price-feat-list {{ list-style: none; padding: 0; margin: 20px 0; }}
  .price-feat-list li {{ padding: 6px 0; font-size: 14px; }}
  .price-feat-list li:before {{ content: "✓ "; color: var(--green); font-weight: 700; }}
  .nav-pub {{
    display: flex; justify-content: space-between; align-items: center;
    padding: 18px 32px; border-bottom: 1px solid var(--border); background: white;
  }}
</style>
</head>
<body>
  <nav class="nav-pub">
    <div style="display:flex;align-items:center;gap:10px;">
      <div class="brand-logo">L</div>
      <div>
        <div style="font-weight:800;font-size:16px;">Lapora Clinic</div>
        <div style="font-size:11px;color:var(--text-soft);">Marketing digital para médicos</div>
      </div>
    </div>
    <div style="display:flex;gap:10px;align-items:center;">
      <a href="/clinic/login" style="font-weight:600;color:var(--text);font-size:14px;">Iniciar sesión</a>
      <a href="/clinic/registro" class="btn btn-primary">Probar gratis</a>
    </div>
  </nav>

  <section class="hero">
    <h1>El cerebro digital<br>de <span>tu consultorio</span></h1>
    <p>WhatsApp, Instagram, pacientes, citas y reportes en una sola pantalla.
       Sin perder tiempo cambiando entre apps. Empezás <strong>gratis</strong>, sin tarjeta.</p>
    <div style="display:flex;gap:12px;justify-content:center;flex-wrap:wrap;">
      <a href="/clinic/registro" class="btn btn-primary" style="padding:14px 28px;font-size:15px;">Empezar gratis →</a>
      <a href="#features" class="btn btn-ghost" style="padding:14px 28px;font-size:15px;">Ver cómo funciona</a>
    </div>
    <p style="font-size:12px;color:var(--text-soft);margin-top:18px;">
      ✓ Sin tarjeta de crédito  ·  ✓ Setup en 5 minutos  ·  ✓ Cancelas cuando quieras
    </p>
  </section>

  <section class="features" id="features">
    <h2 style="text-align:center;font-size:36px;font-weight:900;margin-bottom:14px;letter-spacing:-1px;">
      Todo lo que un consultorio necesita
    </h2>
    <p style="text-align:center;color:var(--text-soft);max-width:560px;margin:0 auto 48px;font-size:15px;">
      Diseñado por médicos para médicos. Cada función nace de un dolor real de consultorios en Colombia.
    </p>
    <div class="features-grid">
      <div class="feature-card">
        <div class="feature-icon">📥</div>
        <h3 style="font-size:17px;font-weight:800;margin-bottom:6px;">Inbox unificado</h3>
        <p style="color:var(--text-soft);font-size:14px;line-height:1.5;">
          WhatsApp + Instagram + Email en una sola pantalla. Responde todo desde un único lugar.
        </p>
      </div>
      <div class="feature-card">
        <div class="feature-icon">🤖</div>
        <h3 style="font-size:17px;font-weight:800;margin-bottom:6px;">IA SofIA</h3>
        <p style="color:var(--text-soft);font-size:14px;line-height:1.5;">
          Responde sola, agenda citas, califica leads. Trabajas el 70% menos.
        </p>
      </div>
      <div class="feature-card">
        <div class="feature-icon">👥</div>
        <h3 style="font-size:17px;font-weight:800;margin-bottom:6px;">CRM de pacientes</h3>
        <p style="color:var(--text-soft);font-size:14px;line-height:1.5;">
          Historial completo, notas, tratamiento, llamadas. Todo en la ficha del paciente.
        </p>
      </div>
      <div class="feature-card">
        <div class="feature-icon">📊</div>
        <h3 style="font-size:17px;font-weight:800;margin-bottom:6px;">Sync Google Sheets</h3>
        <p style="color:var(--text-soft);font-size:14px;line-height:1.5;">
          Importas tus pacientes desde Excel/Sheets con un click. Sin perder lo que ya tienes.
        </p>
      </div>
      <div class="feature-card">
        <div class="feature-icon">📝</div>
        <h3 style="font-size:17px;font-weight:800;margin-bottom:6px;">Plantillas inteligentes</h3>
        <p style="color:var(--text-soft);font-size:14px;line-height:1.5;">
          Respuestas rápidas para preguntas frecuentes con variables personalizables.
        </p>
      </div>
      <div class="feature-card">
        <div class="feature-icon">📞</div>
        <h3 style="font-size:17px;font-weight:800;margin-bottom:6px;">Bitácora de llamadas</h3>
        <p style="color:var(--text-soft);font-size:14px;line-height:1.5;">
          Registra cada llamada y nunca pierdas el seguimiento de un paciente.
        </p>
      </div>
    </div>
  </section>

  <section class="pricing" id="pricing">
    <h2 style="text-align:center;font-size:36px;font-weight:900;margin-bottom:14px;letter-spacing:-1px;">
      Empezá gratis. Escala cuando quieras.
    </h2>
    <p style="text-align:center;color:var(--text-soft);max-width:540px;margin:0 auto 48px;font-size:15px;">
      Sin contratos. Sin permanencia. Sin sorpresas.
    </p>
    <div class="pricing-grid">

      <div class="price-card">
        <span class="badge badge-free">FREE</span>
        <div class="price-tag">$0<small>/mes</small></div>
        <p style="color:var(--text-soft);font-size:13px;">Perfecto para empezar y probar.</p>
        <ul class="price-feat-list">
          <li>Hasta 100 pacientes</li>
          <li>Inbox WhatsApp</li>
          <li>1 usuario</li>
          <li>Plantillas básicas</li>
          <li>Soporte por email</li>
        </ul>
        <a href="/clinic/registro" class="btn btn-ghost" style="width:100%;justify-content:center;">Empezar gratis</a>
      </div>

      <div class="price-card featured">
        <span class="badge badge-pro">PRO ⭐</span>
        <div class="price-tag">$190.000<small>/mes</small></div>
        <p style="color:var(--text-soft);font-size:13px;">Para consultorios que ya facturan.</p>
        <ul class="price-feat-list">
          <li>Pacientes ilimitados</li>
          <li>WhatsApp + Instagram + Email</li>
          <li>IA SofIA</li>
          <li>Sync Google Sheets</li>
          <li>5 usuarios</li>
          <li>Tu logo en la plataforma</li>
          <li>Soporte priority</li>
        </ul>
        <a href="/clinic/registro" class="btn btn-primary" style="width:100%;justify-content:center;">Probar 14 días gratis</a>
      </div>

      <div class="price-card">
        <span class="badge badge-studio">STUDIO</span>
        <div class="price-tag">$390.000<small>/mes</small></div>
        <p style="color:var(--text-soft);font-size:13px;">Para clínicas con varios profesionales.</p>
        <ul class="price-feat-list">
          <li>Todo lo de Pro</li>
          <li>Usuarios ilimitados</li>
          <li>Dominio propio (tudr.com)</li>
          <li>Analytics avanzado</li>
          <li>API custom</li>
          <li>Onboarding personalizado</li>
          <li>Soporte 24/7</li>
        </ul>
        <a href="https://wa.me/573228783019?text=Quiero+info+del+plan+Studio" class="btn btn-ghost" style="width:100%;justify-content:center;">Hablar con ventas</a>
      </div>

    </div>
  </section>

  <footer style="padding:40px 24px;text-align:center;color:var(--text-soft);font-size:13px;border-top:1px solid var(--border);">
    <p><strong>Lapora Clinic</strong> · El cerebro digital de tu consultorio</p>
    <p style="margin-top:8px;">
      <a href="https://lapora.studio" style="color:var(--text-soft);">lapora.studio</a> ·
      <a href="https://wa.me/573228783019" style="color:var(--text-soft);">+57 322 878 3019</a> ·
      <a href="mailto:laporamarketingdigital@gmail.com" style="color:var(--text-soft);">laporamarketingdigital@gmail.com</a>
    </p>
  </footer>
</body></html>""")


# ════════════════════════════════════════════════════════════
# 13) DEMO DATA — Cargar pacientes/mensajes/plantillas de ejemplo
# ════════════════════════════════════════════════════════════

@router.post("/app/demo-data", response_class=HTMLResponse)
async def cargar_demo(clinic_session: Optional[str] = Cookie(None)):
    """Carga 5 pacientes, 7 mensajes, 3 llamadas y 4 plantillas de ejemplo."""
    sesion = obtener_sesion(clinic_session)
    if not sesion:
        return RedirectResponse("/clinic/login", status_code=303)
    creados = await cargar_demo_data(sesion["clinica_id"])
    return RedirectResponse(
        f"/clinic/app/?demo={creados['pacientes']}",
        status_code=303,
    )


# ════════════════════════════════════════════════════════════
# 14) IMPORTAR / EXPORTAR CSV de pacientes
# ════════════════════════════════════════════════════════════

@router.get("/app/pacientes/importar", response_class=HTMLResponse)
async def importar_pacientes_form(clinic_session: Optional[str] = Cookie(None)):
    sesion = obtener_sesion(clinic_session)
    if not sesion:
        return RedirectResponse("/clinic/login", status_code=303)
    clinica = await obtener_clinica(sesion["clinica_id"])
    return HTMLResponse(f"""<!DOCTYPE html>
<html lang="es"><head><meta charset="UTF-8"><title>Importar pacientes</title>{CSS_CLINIC}</head>
<body>
  <div class="app-wrap">
    {sidebar_clinic("pacientes", sesion, clinica)}
    <main class="main">
      <a href="/clinic/app/pacientes" style="font-size:13px;color:var(--text-soft);">← Volver</a>
      <h1 style="font-size:26px;font-weight:800;margin:8px 0 24px;">Importar pacientes desde CSV</h1>

      <div class="card" style="max-width:680px;">
        <p style="margin-bottom:16px;font-size:14px;color:var(--text-soft);">
          Sube un archivo CSV con las columnas: <code>nombre, telefono, email, tratamiento, notas</code>.
          La primera fila debe ser el encabezado.
        </p>

        <details style="margin-bottom:18px;background:#fafaf9;padding:14px;border-radius:10px;border:1px solid var(--border);">
          <summary style="cursor:pointer;font-weight:600;font-size:13px;">📋 Ver ejemplo de CSV</summary>
          <pre style="background:white;padding:12px;border-radius:8px;margin-top:10px;font-size:12px;overflow-x:auto;">nombre,telefono,email,tratamiento,notas
María Pérez,+573001234567,maria@email.com,Ortodoncia,Control mensual
Carlos López,+573109876543,carlos@email.com,Limpieza,Primera consulta</pre>
        </details>

        <form method="post" action="/clinic/app/pacientes/importar" enctype="multipart/form-data"
              style="display:flex;flex-direction:column;gap:14px;">
          <div>
            <label style="font-size:12px;font-weight:700;display:block;margin-bottom:5px;">Archivo CSV</label>
            <input type="file" name="archivo" accept=".csv,text/csv" required class="input">
          </div>
          <div style="display:flex;gap:10px;">
            <button type="submit" class="btn btn-primary">↑ Importar pacientes</button>
            <a href="/clinic/app/pacientes" class="btn btn-ghost">Cancelar</a>
          </div>
        </form>

        <p style="margin-top:18px;font-size:12px;color:var(--text-soft);">
          💡 Tip: Si ya tienes Google Sheets, mejor usa la sincronización automática en
          <a href="/clinic/app/configuracion">Configuración</a>.
        </p>
      </div>
    </main>
  </div>
</body></html>""")


@router.post("/app/pacientes/importar", response_class=HTMLResponse)
async def importar_pacientes_procesar(
    archivo: UploadFile = File(...),
    clinic_session: Optional[str] = Cookie(None),
):
    sesion = obtener_sesion(clinic_session)
    if not sesion:
        return RedirectResponse("/clinic/login", status_code=303)

    contenido = (await archivo.read()).decode("utf-8", errors="replace")
    reader = _csv_mod.DictReader(StringIO(contenido))
    # Normalizar headers
    if reader.fieldnames:
        reader.fieldnames = [(h or "").lower().strip() for h in reader.fieldnames]

    creados = actualizados = 0
    async with async_session() as session:
        ahora = datetime.utcnow()
        for row in reader:
            nombre = (row.get("nombre") or row.get("name") or "").strip()
            if not nombre:
                continue
            telefono = (row.get("telefono") or row.get("teléfono") or "").strip()
            email = (row.get("email") or "").strip().lower()

            # Upsert por telefono o email
            existing = None
            if telefono:
                existing = (await session.execute(
                    select(Paciente).where(Paciente.clinica_id == sesion["clinica_id"])
                    .where(Paciente.telefono == telefono)
                )).scalar_one_or_none()
            if not existing and email:
                existing = (await session.execute(
                    select(Paciente).where(Paciente.clinica_id == sesion["clinica_id"])
                    .where(Paciente.email == email)
                )).scalar_one_or_none()

            datos = {
                "nombre": nombre,
                "telefono": telefono,
                "email": email,
                "tratamiento_actual": (row.get("tratamiento") or "").strip(),
                "notas_basicas": (row.get("notas") or "").strip(),
            }
            if existing:
                for k, v in datos.items():
                    if v:
                        setattr(existing, k, v)
                existing.ultimo_contacto = ahora
                actualizados += 1
            else:
                session.add(Paciente(
                    clinica_id=sesion["clinica_id"],
                    fuente="import_csv",
                    estado="nuevo",
                    primer_contacto=ahora,
                    ultimo_contacto=ahora,
                    **datos,
                ))
                creados += 1
        await session.commit()

    return RedirectResponse(
        f"/clinic/app/pacientes?creado=1&import_creados={creados}&import_actualizados={actualizados}",
        status_code=303,
    )


@router.get("/app/pacientes-export")
async def exportar_pacientes(clinic_session: Optional[str] = Cookie(None)):
    """Descarga un CSV con todos los pacientes de la clínica."""
    sesion = obtener_sesion(clinic_session)
    if not sesion:
        return RedirectResponse("/clinic/login", status_code=303)

    async with async_session() as session:
        pacientes = list((await session.execute(
            select(Paciente).where(Paciente.clinica_id == sesion["clinica_id"])
            .order_by(Paciente.nombre)
        )).scalars().all())

    output = StringIO()
    writer = _csv_mod.writer(output)
    writer.writerow(["nombre", "telefono", "email", "documento", "tratamiento",
                     "estado", "alergias", "notas", "fuente",
                     "primer_contacto", "ultimo_contacto"])
    for p in pacientes:
        writer.writerow([
            p.nombre or "", p.telefono or "", p.email or "",
            p.documento or "", p.tratamiento_actual or "",
            p.estado or "", p.alergias or "",
            p.notas_basicas or "", p.fuente or "",
            p.primer_contacto.strftime("%Y-%m-%d") if p.primer_contacto else "",
            p.ultimo_contacto.strftime("%Y-%m-%d") if p.ultimo_contacto else "",
        ])

    csv_content = output.getvalue()
    from fastapi.responses import Response
    nombre_archivo = f"pacientes_{datetime.now():%Y%m%d}.csv"
    return Response(
        content=csv_content,
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{nombre_archivo}"'},
    )


# ════════════════════════════════════════════════════════════
# 15) BUSQUEDA GLOBAL — Pacientes, mensajes, llamadas
# ════════════════════════════════════════════════════════════

@router.get("/app/buscar", response_class=HTMLResponse)
async def buscar_global(
    q: Optional[str] = None,
    clinic_session: Optional[str] = Cookie(None),
):
    sesion = obtener_sesion(clinic_session)
    if not sesion:
        return RedirectResponse("/clinic/login", status_code=303)
    clinica = await obtener_clinica(sesion["clinica_id"])

    pacientes_res = []
    mensajes_res = []
    llamadas_res = []
    if q and len(q.strip()) >= 2:
        patron = f"%{q.strip()}%"
        async with async_session() as session:
            pacientes_res = list((await session.execute(
                select(Paciente).where(Paciente.clinica_id == clinica.id).where(or_(
                    Paciente.nombre.ilike(patron),
                    Paciente.telefono.ilike(patron),
                    Paciente.email.ilike(patron),
                    Paciente.tratamiento_actual.ilike(patron),
                    Paciente.notas_basicas.ilike(patron),
                )).limit(20)
            )).scalars().all())
            mensajes_res = list((await session.execute(
                select(MensajeUnificado).where(MensajeUnificado.clinica_id == clinica.id)
                .where(MensajeUnificado.contenido.ilike(patron))
                .order_by(desc(MensajeUnificado.timestamp)).limit(20)
            )).scalars().all())
            llamadas_res = list((await session.execute(
                select(Llamada).where(Llamada.clinica_id == clinica.id)
                .where(Llamada.notas.ilike(patron))
                .order_by(desc(Llamada.timestamp)).limit(20)
            )).scalars().all())

    def render_pacientes():
        if not pacientes_res:
            return '<p style="color:var(--text-soft);font-size:13px;">Sin resultados en pacientes</p>'
        rows = ""
        for p in pacientes_res:
            rows += f"""
            <a href="/clinic/app/pacientes/{p.id}" style="display:block;padding:10px 14px;border-bottom:1px solid var(--border);color:var(--text);text-decoration:none;">
              <div style="font-weight:600;">{html.escape(p.nombre or '')}</div>
              <div style="font-size:12px;color:var(--text-soft);">{html.escape(p.telefono or '—')} · {html.escape(p.tratamiento_actual or 'Sin tratamiento')}</div>
            </a>"""
        return rows

    def render_mensajes():
        if not mensajes_res:
            return '<p style="color:var(--text-soft);font-size:13px;">Sin resultados en mensajes</p>'
        rows = ""
        for m in mensajes_res:
            ts = m.timestamp.strftime("%d/%m %H:%M") if m.timestamp else ""
            rows += f"""
            <a href="/clinic/app/inbox?paciente_id={m.paciente_id}" style="display:block;padding:10px 14px;border-bottom:1px solid var(--border);color:var(--text);text-decoration:none;">
              <div style="font-size:13px;line-height:1.4;">{html.escape((m.contenido or '')[:150])}</div>
              <div style="font-size:11px;color:var(--text-soft);margin-top:4px;">{html.escape(m.canal)} · {m.direccion} · {ts}</div>
            </a>"""
        return rows

    def render_llamadas():
        if not llamadas_res:
            return '<p style="color:var(--text-soft);font-size:13px;">Sin resultados en llamadas</p>'
        rows = ""
        for l in llamadas_res:
            ts = l.timestamp.strftime("%d/%m %H:%M") if l.timestamp else ""
            rows += f"""
            <a href="/clinic/app/pacientes/{l.paciente_id}" style="display:block;padding:10px 14px;border-bottom:1px solid var(--border);color:var(--text);text-decoration:none;">
              <div style="font-size:13px;line-height:1.4;">{html.escape((l.notas or '')[:150])}</div>
              <div style="font-size:11px;color:var(--text-soft);margin-top:4px;">{html.escape(l.direccion)} · {html.escape(l.resultado or '')} · {ts}</div>
            </a>"""
        return rows

    q_val = html.escape(q or "", quote=True)
    sin_resultados = q and not pacientes_res and not mensajes_res and not llamadas_res

    return HTMLResponse(f"""<!DOCTYPE html>
<html lang="es"><head><meta charset="UTF-8"><title>Buscar - Lapora Clinic</title>{CSS_CLINIC}</head>
<body>
  <div class="app-wrap">
    {sidebar_clinic("buscar", sesion, clinica)}
    <main class="main">
      <h1 style="font-size:26px;font-weight:800;margin-bottom:16px;">🔍 Búsqueda global</h1>
      <form method="get" action="/clinic/app/buscar" style="margin-bottom:24px;">
        <input type="text" name="q" value="{q_val}" autofocus
               placeholder="Buscar en pacientes, mensajes y llamadas..."
               class="input" style="font-size:16px;padding:14px 16px;">
      </form>

      {('<p style="text-align:center;color:var(--text-soft);padding:60px 20px;"><strong>Sin resultados para</strong> ' + html.escape(q or '') + '. Probá con otra palabra.</p>' if sin_resultados else '')}

      {('' if not q else f'''
      <div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(300px,1fr));gap:16px;">
        <div class="card" style="padding:0;overflow:hidden;">
          <div style="padding:12px 14px;background:#1c1917;color:white;font-size:11px;text-transform:uppercase;letter-spacing:1px;font-weight:700;">
            👥 Pacientes ({len(pacientes_res)})
          </div>
          {render_pacientes()}
        </div>
        <div class="card" style="padding:0;overflow:hidden;">
          <div style="padding:12px 14px;background:#1c1917;color:white;font-size:11px;text-transform:uppercase;letter-spacing:1px;font-weight:700;">
            💬 Mensajes ({len(mensajes_res)})
          </div>
          {render_mensajes()}
        </div>
        <div class="card" style="padding:0;overflow:hidden;">
          <div style="padding:12px 14px;background:#1c1917;color:white;font-size:11px;text-transform:uppercase;letter-spacing:1px;font-weight:700;">
            📞 Llamadas ({len(llamadas_res)})
          </div>
          {render_llamadas()}
        </div>
      </div>''')}
    </main>
  </div>
</body></html>""")


# ════════════════════════════════════════════════════════════
# 16) HEALTH CHECK para Railway
# ════════════════════════════════════════════════════════════

@router.get("/health")
async def health_clinic():
    """Health check del módulo Lapora Clinic."""
    try:
        async with async_session() as session:
            await session.execute(select(func.count(Clinica.id)))
        return {"status": "ok", "service": "lapora_clinic", "db": "ok"}
    except Exception as e:
        return {"status": "degraded", "service": "lapora_clinic", "error": str(e)[:100]}
