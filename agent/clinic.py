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
from fastapi import APIRouter, Depends, Request, Form, HTTPException, Cookie
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import select, func, or_, desc

from agent.memory import async_session
from agent.clinic_models import (
    Clinica, UsuarioClinic, Paciente, MensajeUnificado,
    Llamada, CitaClinic, PlantillaRespuesta,
    crear_clinica, autenticar_usuario, obtener_clinica,
)


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
      <nav style="margin-top: 18px; flex: 1;">{links}</nav>
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
    clinic_session: Optional[str] = Cookie(None),
):
    sesion = obtener_sesion(clinic_session)
    if not sesion:
        return RedirectResponse("/clinic/login", status_code=303)

    clinica = await obtener_clinica(sesion["clinica_id"])
    if not clinica:
        return RedirectResponse("/clinic/login", status_code=303)

    # Stats reales
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

    bienvenida_html = ""
    if bienvenida:
        bienvenida_html = f"""
        <div style="background:#ECFDF5;border:1px solid #10B981;color:#065F46;padding:14px 18px;border-radius:12px;margin-bottom:24px;">
          🎉 <strong>¡Bienvenido a Lapora Clinic, {html.escape(sesion.get('nombre',''))}!</strong>
          Tu clínica <strong>{html.escape(clinica.nombre)}</strong> está lista. Empieza conectando WhatsApp en
          <a href="/clinic/app/configuracion" style="font-weight: 700;">Configuración</a>.
        </div>"""

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
      </div>
    </main>
  </div>
</body></html>""")


# ════════════════════════════════════════════════════════════
# 5) INBOX — Mockup MVP (se llena con datos reales en Mes 1)
# ════════════════════════════════════════════════════════════

@router.get("/app/inbox", response_class=HTMLResponse)
async def vista_inbox(clinic_session: Optional[str] = Cookie(None)):
    sesion = obtener_sesion(clinic_session)
    if not sesion:
        return RedirectResponse("/clinic/login", status_code=303)
    clinica = await obtener_clinica(sesion["clinica_id"])

    async with async_session() as session:
        mensajes = (await session.execute(
            select(MensajeUnificado)
            .where(MensajeUnificado.clinica_id == clinica.id)
            .order_by(desc(MensajeUnificado.timestamp))
            .limit(50)
        )).scalars().all()

    placeholder = """
    <div style="text-align: center; padding: 60px 20px; color: var(--text-soft);">
      <div style="font-size: 64px; margin-bottom: 16px;">📥</div>
      <h3 style="font-size: 18px; font-weight: 700; color: var(--text); margin-bottom: 8px;">Inbox vacío</h3>
      <p style="font-size: 14px; max-width: 400px; margin: 0 auto 24px;">
        Cuando conectes WhatsApp e Instagram, los mensajes de tus pacientes aparecerán aquí en tiempo real.
      </p>
      <a href="/clinic/app/configuracion" class="btn btn-primary">Conectar canales →</a>
    </div>""" if not mensajes else ""

    return HTMLResponse(f"""<!DOCTYPE html>
<html lang="es"><head><meta charset="UTF-8"><title>Inbox - Lapora Clinic</title>{CSS_CLINIC}</head>
<body>
  <div class="app-wrap">
    {sidebar_clinic("inbox", sesion, clinica)}
    <main class="main">
      <h1 style="font-size: 26px; font-weight: 800; margin-bottom: 4px;">Inbox unificado</h1>
      <p style="color: var(--text-soft); margin-bottom: 24px;">Todos tus canales en un solo lugar</p>
      <div class="card">{placeholder}</div>
    </main>
  </div>
</body></html>""")


# ════════════════════════════════════════════════════════════
# 6) PACIENTES
# ════════════════════════════════════════════════════════════

@router.get("/app/pacientes", response_class=HTMLResponse)
async def vista_pacientes(
    q: Optional[str] = None,
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
            ult = p.ultimo_contacto.strftime("%d/%m/%Y") if p.ultimo_contacto else "—"
            filas += f"""
              <tr>
                <td style="padding:14px;font-weight:600;">{nombre}</td>
                <td style="padding:14px;color:var(--text-soft);">{tel}</td>
                <td style="padding:14px;color:var(--text-soft);">{email}</td>
                <td style="padding:14px;color:var(--text-soft);">{ult}</td>
              </tr>"""
        contenido = f"""
        <table style="width:100%;border-collapse:collapse;">
          <thead><tr style="background:#1c1917;color:white;">
            <th style="padding:14px;text-align:left;font-size:11px;text-transform:uppercase;letter-spacing:1px;">Nombre</th>
            <th style="padding:14px;text-align:left;font-size:11px;text-transform:uppercase;letter-spacing:1px;">Teléfono</th>
            <th style="padding:14px;text-align:left;font-size:11px;text-transform:uppercase;letter-spacing:1px;">Email</th>
            <th style="padding:14px;text-align:left;font-size:11px;text-transform:uppercase;letter-spacing:1px;">Último contacto</th>
          </tr></thead>
          <tbody>{filas}</tbody>
        </table>"""
    else:
        contenido = """
        <div style="text-align:center;padding:60px 20px;color:var(--text-soft);">
          <div style="font-size:64px;margin-bottom:16px;">👥</div>
          <h3 style="font-size:18px;font-weight:700;color:var(--text);margin-bottom:8px;">Sin pacientes aún</h3>
          <p style="margin-bottom:24px;">Sincronizá con Google Sheets para importar todos tus pacientes existentes.</p>
          <a href="/clinic/app/configuracion" class="btn btn-primary">Conectar Google Sheets →</a>
        </div>"""

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
        <form method="get" action="/clinic/app/pacientes" style="display:flex;gap:10px;">
          <input type="text" name="q" value="{q_val}" placeholder="Buscar por nombre, tel, email..." class="input" style="width:280px;">
          <button type="submit" class="btn btn-ghost">Buscar</button>
        </form>
      </div>
      <div class="card" style="padding:0;overflow:hidden;">{contenido}</div>
    </main>
  </div>
</body></html>""")


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


@router.get("/app/llamadas", response_class=HTMLResponse)
async def vista_llamadas(clinic_session: Optional[str] = Cookie(None)):
    sesion = obtener_sesion(clinic_session)
    if not sesion:
        return RedirectResponse("/clinic/login", status_code=303)
    clinica = await obtener_clinica(sesion["clinica_id"])
    return _vista_simple("Llamadas", "Bitácora de llamadas con tus pacientes", "📞",
                          "/clinic/app/", "Volver al dashboard", sesion, clinica, "llamadas")


@router.get("/app/plantillas", response_class=HTMLResponse)
async def vista_plantillas(clinic_session: Optional[str] = Cookie(None)):
    sesion = obtener_sesion(clinic_session)
    if not sesion:
        return RedirectResponse("/clinic/login", status_code=303)
    clinica = await obtener_clinica(sesion["clinica_id"])
    return _vista_simple("Plantillas", "Respuestas rápidas para preguntas frecuentes", "📝",
                          "/clinic/app/", "Volver al dashboard", sesion, clinica, "plantillas")


@router.get("/app/configuracion", response_class=HTMLResponse)
async def vista_config(clinic_session: Optional[str] = Cookie(None)):
    sesion = obtener_sesion(clinic_session)
    if not sesion:
        return RedirectResponse("/clinic/login", status_code=303)
    clinica = await obtener_clinica(sesion["clinica_id"])
    return _vista_simple("Configuración",
                          "Conecta WhatsApp, Instagram, Google Sheets y personaliza tu cuenta", "⚙️",
                          "/clinic/app/", "Volver al dashboard", sesion, clinica, "config")
