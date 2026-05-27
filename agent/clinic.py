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
        <div style="display:flex;gap:10px;align-items:center;">
          <form method="get" action="/clinic/app/pacientes" style="display:flex;gap:8px;">
            <input type="text" name="q" value="{q_val}" placeholder="Buscar..." class="input" style="width:240px;">
            <button type="submit" class="btn btn-ghost">Buscar</button>
          </form>
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
    if guardado:
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


# Eliminar el helper _vista_simple que ya no se usa
def _vista_simple(*args, **kwargs):
    """Helper deprecated — ya no se usa, todos los endpoints son reales."""
    pass
