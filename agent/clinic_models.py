# -*- coding: utf-8 -*-
# agent/clinic_models.py — Modelos multi-tenant de Lapora Clinic
# Lapora Marketing Digital

"""
Modelos SQLAlchemy para Lapora Clinic (SaaS multi-tenant).
Cada Clinica es un tenant aislado. Todos los datos de pacientes/mensajes/etc.
llevan clinica_id para garantizar separación.

Convive con los modelos de SofIA (Mensaje, Contacto, Prospecto) en memory.py.
"""

import hashlib
import secrets
from datetime import datetime
from typing import Optional
from sqlalchemy import (
    String, Text, DateTime, Integer, Boolean, ForeignKey, select, or_, func
)
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.ext.asyncio import AsyncSession

# Reutilizamos la Base y session del archivo memory.py existente
from agent.memory import Base, async_session


# ════════════════════════════════════════════════════════════
# CLINICA — Tenant (cliente que paga Lapora Clinic)
# ════════════════════════════════════════════════════════════

class Clinica(Base):
    """Una clínica = un tenant. Aislamiento total de datos por clinica_id."""
    __tablename__ = "clinic_clinicas"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

    # Identificación
    nombre:     Mapped[str] = mapped_column(String(200))
    slug:       Mapped[str] = mapped_column(String(80), unique=True, index=True)  # ej: clinica-tolima
    especialidad: Mapped[str] = mapped_column(String(100), default="", nullable=True)
    ciudad:     Mapped[str] = mapped_column(String(100), default="", nullable=True)

    # Plan / pricing
    # free | pro | studio
    plan:       Mapped[str] = mapped_column(String(20), default="free", index=True)
    activo:     Mapped[bool] = mapped_column(Boolean, default=True)

    # Branding (white-label en plan studio)
    logo_url:   Mapped[str] = mapped_column(String(500), default="", nullable=True)
    color_primario: Mapped[str] = mapped_column(String(20), default="#FF3B30", nullable=True)
    dominio_personalizado: Mapped[str] = mapped_column(String(200), default="", nullable=True)

    # Integraciones (encriptado en producción — por ahora plano para MVP)
    whatsapp_phone_id: Mapped[str] = mapped_column(String(50), default="", nullable=True)
    whatsapp_token:    Mapped[str] = mapped_column(String(500), default="", nullable=True)
    instagram_account_id: Mapped[str] = mapped_column(String(50), default="", nullable=True)
    instagram_token:   Mapped[str] = mapped_column(String(500), default="", nullable=True)
    google_sheet_id:   Mapped[str] = mapped_column(String(200), default="", nullable=True)
    google_calendar_id: Mapped[str] = mapped_column(String(200), default="", nullable=True)

    # IA SofIA per-tenant
    ia_activa: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    ia_saludo: Mapped[str] = mapped_column(String(500), default="", nullable=True)
    ia_servicios: Mapped[Text] = mapped_column(Text, default="", nullable=True)
    ia_horario: Mapped[str] = mapped_column(String(300), default="", nullable=True)
    ia_precios_basicos: Mapped[Text] = mapped_column(Text, default="", nullable=True)
    ia_instrucciones_extra: Mapped[Text] = mapped_column(Text, default="", nullable=True)

    # Voice Bot per-tenant — confirmación automática de citas por llamada
    voz_confirmar_citas_activa: Mapped[bool] = mapped_column(Boolean, default=False, index=True)

    # Suspensión / billing
    congelada: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    motivo_suspension: Mapped[str] = mapped_column(String(300), default="", nullable=True)
    fecha_suspension: Mapped[datetime] = mapped_column(DateTime, nullable=True)
    fecha_proximo_pago: Mapped[datetime] = mapped_column(DateTime, nullable=True)
    monto_mensual_usd: Mapped[int] = mapped_column(Integer, default=0)

    # Timestamps
    creado_en:  Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    actualizado_en: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


# ════════════════════════════════════════════════════════════
# USUARIO — Login para entrar a la clínica
# ════════════════════════════════════════════════════════════

class UsuarioClinic(Base):
    """Usuario que entra a una clínica. Rol: owner | recepcionista | asistente."""
    __tablename__ = "clinic_usuarios"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    clinica_id: Mapped[int] = mapped_column(ForeignKey("clinic_clinicas.id"), index=True)

    nombre:        Mapped[str] = mapped_column(String(200))
    email:         Mapped[str] = mapped_column(String(200), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(200))  # hash con salt
    rol:           Mapped[str] = mapped_column(String(30), default="owner")

    activo:        Mapped[bool] = mapped_column(Boolean, default=True)
    ultimo_login:  Mapped[datetime] = mapped_column(DateTime, nullable=True)
    creado_en:     Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


# ════════════════════════════════════════════════════════════
# INVITACION DE USUARIO — Link que el owner comparte con su equipo
# ════════════════════════════════════════════════════════════

class InvitacionUsuario(Base):
    """Invitación pendiente para agregar usuario a una clínica.

    El owner genera una invitación → comparte el link → el invitado
    pone su nombre + password → se crea UsuarioClinic.
    """
    __tablename__ = "clinic_invitaciones"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    clinica_id: Mapped[int] = mapped_column(ForeignKey("clinic_clinicas.id"), index=True)

    token: Mapped[str] = mapped_column(String(80), unique=True, index=True)
    email_invitado: Mapped[str] = mapped_column(String(200), default="", nullable=True)
    rol: Mapped[str] = mapped_column(String(30), default="staff")  # owner | admin | staff

    # Estado
    usada:        Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    invitado_por: Mapped[int] = mapped_column(ForeignKey("clinic_usuarios.id"), nullable=True)
    fecha_uso:    Mapped[datetime] = mapped_column(DateTime, nullable=True)
    expira_en:    Mapped[datetime] = mapped_column(DateTime, index=True)
    creado_en:    Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


# ════════════════════════════════════════════════════════════
# PACIENTE — El cliente final del consultorio
# ════════════════════════════════════════════════════════════

class Paciente(Base):
    """Paciente del consultorio. Aislado por clinica_id."""
    __tablename__ = "clinic_pacientes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    clinica_id: Mapped[int] = mapped_column(ForeignKey("clinic_clinicas.id"), index=True)

    # Datos básicos
    nombre:    Mapped[str] = mapped_column(String(200), index=True)
    telefono:  Mapped[str] = mapped_column(String(50), default="", index=True)
    email:     Mapped[str] = mapped_column(String(200), default="", nullable=True)
    fecha_nacimiento: Mapped[datetime] = mapped_column(DateTime, nullable=True)
    genero:    Mapped[str] = mapped_column(String(20), default="", nullable=True)
    documento: Mapped[str] = mapped_column(String(50), default="", nullable=True)

    # Notas básicas (NO HCE completa por tema legal)
    notas_basicas: Mapped[Text] = mapped_column(Text, default="", nullable=True)
    tratamiento_actual: Mapped[str] = mapped_column(String(300), default="", nullable=True)
    alergias:  Mapped[str] = mapped_column(String(300), default="", nullable=True)

    # Estado del paciente en el consultorio
    # nuevo | activo | inactivo | dado_de_alta
    estado:    Mapped[str] = mapped_column(String(30), default="nuevo", index=True)
    fuente:    Mapped[str] = mapped_column(String(50), default="manual", nullable=True)  # whatsapp / ig / sheets / manual
    tags:      Mapped[str] = mapped_column(String(300), default="", nullable=True)

    # Métricas
    total_mensajes: Mapped[int] = mapped_column(Integer, default=0)
    total_citas:    Mapped[int] = mapped_column(Integer, default=0)
    valor_total:    Mapped[int] = mapped_column(Integer, default=0)  # COP

    # Timestamps
    primer_contacto: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)
    ultimo_contacto: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)
    ultima_cita:     Mapped[datetime] = mapped_column(DateTime, nullable=True)


# ════════════════════════════════════════════════════════════
# MENSAJE UNIFICADO — Inbox WhatsApp + Instagram + Email
# ════════════════════════════════════════════════════════════

class MensajeUnificado(Base):
    """Mensaje de cualquier canal (WhatsApp, IG, Email). Inbox unificado."""
    __tablename__ = "clinic_mensajes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    clinica_id:  Mapped[int] = mapped_column(ForeignKey("clinic_clinicas.id"), index=True)
    paciente_id: Mapped[int] = mapped_column(ForeignKey("clinic_pacientes.id"), nullable=True, index=True)

    # whatsapp | instagram | email | sms | llamada
    canal:       Mapped[str] = mapped_column(String(20), index=True)
    direccion:   Mapped[str] = mapped_column(String(10))  # entrada | salida
    contenido:   Mapped[Text] = mapped_column(Text)
    leido:       Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    respondido_por: Mapped[str] = mapped_column(String(30), default="", nullable=True)  # ia | usuario | nadie

    # Metadata del canal externo
    canal_msg_id: Mapped[str] = mapped_column(String(200), default="", nullable=True)
    adjunto_url:  Mapped[str] = mapped_column(String(500), default="", nullable=True)

    timestamp: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)


# ════════════════════════════════════════════════════════════
# LLAMADA — Bitácora manual de llamadas
# ════════════════════════════════════════════════════════════

class Llamada(Base):
    """Registro de llamada telefónica."""
    __tablename__ = "clinic_llamadas"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    clinica_id:  Mapped[int] = mapped_column(ForeignKey("clinic_clinicas.id"), index=True)
    paciente_id: Mapped[int] = mapped_column(ForeignKey("clinic_pacientes.id"), index=True)

    direccion:   Mapped[str] = mapped_column(String(10))  # entrada | salida | perdida
    duracion_seg: Mapped[int] = mapped_column(Integer, default=0)
    notas:       Mapped[Text] = mapped_column(Text, default="", nullable=True)
    # interesado | no_interesado | agendado | volver_a_llamar
    resultado:   Mapped[str] = mapped_column(String(30), default="", nullable=True)

    timestamp: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)


# ════════════════════════════════════════════════════════════
# CITA — Agenda médica
# ════════════════════════════════════════════════════════════

class CitaClinic(Base):
    """Cita agendada del paciente."""
    __tablename__ = "clinic_citas"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    clinica_id:  Mapped[int] = mapped_column(ForeignKey("clinic_clinicas.id"), index=True)
    paciente_id: Mapped[int] = mapped_column(ForeignKey("clinic_pacientes.id"), index=True)

    fecha_hora:  Mapped[datetime] = mapped_column(DateTime, index=True)
    duracion_min: Mapped[int] = mapped_column(Integer, default=30)
    motivo:      Mapped[str] = mapped_column(String(300), default="", nullable=True)
    # agendada | confirmada | completada | no_show | cancelada
    estado:      Mapped[str] = mapped_column(String(30), default="agendada", index=True)
    notas:       Mapped[Text] = mapped_column(Text, default="", nullable=True)
    google_event_id: Mapped[str] = mapped_column(String(200), default="", nullable=True)

    # Recordatorios automáticos (Sprint Opción B Día 3)
    recordatorio_24h_enviado: Mapped[bool] = mapped_column(Boolean, default=False)
    recordatorio_2h_enviado:  Mapped[bool] = mapped_column(Boolean, default=False)

    # Voice Bot Day 5 — flag idempotente para no duplicar encolado
    voz_confirmacion_encolada: Mapped[bool] = mapped_column(Boolean, default=False)

    creado_en: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


# ════════════════════════════════════════════════════════════
# PLANTILLA — Respuestas rápidas
# ════════════════════════════════════════════════════════════

class PlantillaRespuesta(Base):
    """Plantillas de respuesta rápida por clínica."""
    __tablename__ = "clinic_plantillas"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    clinica_id: Mapped[int] = mapped_column(ForeignKey("clinic_clinicas.id"), index=True)

    titulo:    Mapped[str] = mapped_column(String(150))
    contenido: Mapped[Text] = mapped_column(Text)
    categoria: Mapped[str] = mapped_column(String(50), default="general", nullable=True)
    usos:      Mapped[int] = mapped_column(Integer, default=0)

    creado_en: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


# ════════════════════════════════════════════════════════════
# FOTO ANTES/DESPUÉS — Para estética
# ════════════════════════════════════════════════════════════

class FotoTratamiento(Base):
    """Foto antes/después con consentimiento."""
    __tablename__ = "clinic_fotos"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    clinica_id:  Mapped[int] = mapped_column(ForeignKey("clinic_clinicas.id"), index=True)
    paciente_id: Mapped[int] = mapped_column(ForeignKey("clinic_pacientes.id"), index=True)

    tratamiento: Mapped[str] = mapped_column(String(200))
    foto_antes:  Mapped[str] = mapped_column(String(500), default="", nullable=True)
    foto_despues: Mapped[str] = mapped_column(String(500), default="", nullable=True)
    consentimiento: Mapped[bool] = mapped_column(Boolean, default=False)
    notas:       Mapped[Text] = mapped_column(Text, default="", nullable=True)

    fecha: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


# ════════════════════════════════════════════════════════════
# UTILIDADES — Hash password, slug, etc.
# ════════════════════════════════════════════════════════════

def hash_password(password: str) -> str:
    """Hash con salt para passwords (PBKDF2)."""
    salt = secrets.token_hex(16)
    pwhash = hashlib.pbkdf2_hmac(
        "sha256", password.encode("utf-8"), salt.encode("utf-8"), 100000
    )
    return f"{salt}${pwhash.hex()}"


def verify_password(password: str, stored_hash: str) -> bool:
    """Verifica password contra hash almacenado."""
    try:
        salt, pwhash = stored_hash.split("$", 1)
        new_hash = hashlib.pbkdf2_hmac(
            "sha256", password.encode("utf-8"), salt.encode("utf-8"), 100000
        ).hex()
        return secrets.compare_digest(new_hash, pwhash)
    except (ValueError, AttributeError):
        return False


def slugify(texto: str) -> str:
    """Convierte 'Clínica Tolima' → 'clinica-tolima'."""
    import re
    import unicodedata
    s = unicodedata.normalize("NFKD", texto).encode("ascii", "ignore").decode()
    s = re.sub(r"[^\w\s-]", "", s).strip().lower()
    s = re.sub(r"[\s_-]+", "-", s)
    return s


# ════════════════════════════════════════════════════════════
# QUERIES HELPERS — Operaciones comunes
# ════════════════════════════════════════════════════════════

async def crear_clinica(nombre: str, email_admin: str, password_admin: str,
                         nombre_admin: str = "Admin", especialidad: str = "",
                         ciudad: str = "Ibagué") -> tuple[Clinica, UsuarioClinic]:
    """Crea una nueva clínica + su primer usuario admin."""
    async with async_session() as session:
        slug = slugify(nombre)
        # Asegurar unicidad
        existing = (await session.execute(
            select(Clinica).where(Clinica.slug == slug)
        )).scalar_one_or_none()
        contador = 1
        slug_final = slug
        while existing:
            contador += 1
            slug_final = f"{slug}-{contador}"
            existing = (await session.execute(
                select(Clinica).where(Clinica.slug == slug_final)
            )).scalar_one_or_none()

        clinica = Clinica(
            nombre=nombre,
            slug=slug_final,
            especialidad=especialidad,
            ciudad=ciudad,
            plan="free",
        )
        session.add(clinica)
        await session.flush()  # Para obtener clinica.id

        usuario = UsuarioClinic(
            clinica_id=clinica.id,
            nombre=nombre_admin,
            email=email_admin.lower(),
            password_hash=hash_password(password_admin),
            rol="owner",
        )
        session.add(usuario)
        await session.commit()
        await session.refresh(clinica)
        await session.refresh(usuario)
        return clinica, usuario


async def autenticar_usuario(email: str, password: str) -> UsuarioClinic | None:
    """Login: retorna el usuario si las credenciales son válidas."""
    async with async_session() as session:
        usuario = (await session.execute(
            select(UsuarioClinic).where(UsuarioClinic.email == email.lower())
        )).scalar_one_or_none()
        if not usuario or not usuario.activo:
            return None
        if not verify_password(password, usuario.password_hash):
            return None
        usuario.ultimo_login = datetime.utcnow()
        await session.commit()
        return usuario


async def obtener_clinica(clinica_id: int) -> Clinica | None:
    async with async_session() as session:
        return (await session.execute(
            select(Clinica).where(Clinica.id == clinica_id)
        )).scalar_one_or_none()


# ════════════════════════════════════════════════════════════
# LÍMITES POR PLAN — Cuántos usuarios puede tener cada clínica
# ════════════════════════════════════════════════════════════

LIMITE_USUARIOS_POR_PLAN = {
    "free":   1,           # Solo el owner
    "pro":    5,           # 5 usuarios (Pro $100 USD/mes)
    "studio": 9999,        # Ilimitado (Studio $250 USD/mes)
}


def limite_usuarios(plan: str) -> int:
    """Retorna cuántos usuarios totales puede tener una clínica según su plan."""
    return LIMITE_USUARIOS_POR_PLAN.get((plan or "free").lower(), 1)


async def contar_usuarios_clinica(clinica_id: int) -> int:
    """Cuántos usuarios activos tiene la clínica actualmente."""
    from sqlalchemy import func
    async with async_session() as session:
        n = (await session.execute(
            select(func.count(UsuarioClinic.id))
            .where(UsuarioClinic.clinica_id == clinica_id)
            .where(UsuarioClinic.activo == True)  # noqa: E712
        )).scalar() or 0
    return int(n)


async def puede_invitar_usuario(clinica: Clinica) -> tuple[bool, str]:
    """Verifica si la clínica puede invitar un usuario más.

    Returns: (puede, motivo_si_no)
    """
    limite = limite_usuarios(clinica.plan)
    actuales = await contar_usuarios_clinica(clinica.id)

    # Contar invitaciones pendientes (no usadas, no expiradas) también
    from sqlalchemy import and_
    async with async_session() as session:
        n_pendientes = (await session.execute(
            select(func.count(InvitacionUsuario.id))
            .where(InvitacionUsuario.clinica_id == clinica.id)
            .where(InvitacionUsuario.usada == False)  # noqa: E712
            .where(InvitacionUsuario.expira_en > datetime.utcnow())
        )).scalar() or 0

    total = actuales + int(n_pendientes)
    if total >= limite:
        plan_nombre = (clinica.plan or "free").lower()
        if plan_nombre == "free":
            return False, f"Plan Free solo permite 1 usuario. Sube a Pro ($100/mes) para invitar hasta 5."
        elif plan_nombre == "pro":
            return False, f"Plan Pro permite 5 usuarios y ya tienes {total}. Sube a Studio ($250/mes) para usuarios ilimitados."
        else:
            return False, f"Ya alcanzaste el límite de {limite} usuarios."
    return True, ""


async def crear_invitacion(
    clinica_id: int,
    invitado_por_id: int,
    email_invitado: str = "",
    rol: str = "staff",
    dias_validez: int = 7,
) -> InvitacionUsuario:
    """Crea una invitación con token único. El owner comparte el link."""
    from datetime import timedelta
    token = secrets.token_urlsafe(32)
    expira = datetime.utcnow() + timedelta(days=dias_validez)

    async with async_session() as session:
        invitacion = InvitacionUsuario(
            clinica_id=clinica_id,
            token=token,
            email_invitado=(email_invitado or "").lower().strip(),
            rol=rol if rol in ("owner", "admin", "staff") else "staff",
            invitado_por=invitado_por_id,
            expira_en=expira,
        )
        session.add(invitacion)
        await session.commit()
        await session.refresh(invitacion)
    return invitacion


async def consumir_invitacion(
    token: str,
    nombre: str,
    email: str,
    password: str,
) -> tuple[UsuarioClinic | None, str]:
    """Acepta una invitación: crea el UsuarioClinic asociado.

    Returns: (usuario_creado | None, mensaje_error)
    """
    if not nombre or not email or not password or len(password) < 6:
        return None, "Faltan datos o la contraseña es muy corta (mín 6)"

    async with async_session() as session:
        inv = (await session.execute(
            select(InvitacionUsuario).where(InvitacionUsuario.token == token)
        )).scalar_one_or_none()

        if not inv:
            return None, "Invitación no encontrada o inválida"
        if inv.usada:
            return None, "Esta invitación ya fue usada"
        if inv.expira_en < datetime.utcnow():
            return None, "Esta invitación expiró. Pide al admin generar una nueva."

        # Verificar que no exista ya un usuario con ese email
        existente = (await session.execute(
            select(UsuarioClinic).where(UsuarioClinic.email == email.lower())
        )).scalar_one_or_none()
        if existente:
            return None, f"Ya existe un usuario con el email {email}"

        # Validar límite del plan otra vez (por si llegamos al límite mientras existía la invitación)
        clinica = (await session.execute(
            select(Clinica).where(Clinica.id == inv.clinica_id)
        )).scalar_one_or_none()
        if not clinica:
            return None, "Clínica no encontrada"
        actuales = (await session.execute(
            select(func.count(UsuarioClinic.id))
            .where(UsuarioClinic.clinica_id == clinica.id)
            .where(UsuarioClinic.activo == True)  # noqa: E712
        )).scalar() or 0
        if actuales >= limite_usuarios(clinica.plan):
            return None, "La clínica ya alcanzó el límite de usuarios de su plan"

        # Crear el usuario
        usuario = UsuarioClinic(
            clinica_id=inv.clinica_id,
            nombre=nombre.strip()[:200],
            email=email.lower().strip()[:200],
            password_hash=hash_password(password),
            rol=inv.rol,
            activo=True,
        )
        session.add(usuario)

        # Marcar invitación como usada
        inv.usada = True
        inv.fecha_uso = datetime.utcnow()

        await session.commit()
        await session.refresh(usuario)

    return usuario, ""


async def aplicar_migraciones():
    """Aplica migraciones idempotentes a tablas existentes.

    SQLAlchemy create_all() solo crea tablas nuevas pero NO agrega columnas
    a tablas existentes. Esta función agrega columnas faltantes manualmente
    con ALTER TABLE IF NOT EXISTS.

    Se ejecuta al arrancar la app (después de inicializar_db).
    """
    from sqlalchemy import text
    from agent.memory import engine
    import os as _os

    # Detectar si es Postgres (Railway) o SQLite (local)
    db_url = _os.getenv("DATABASE_URL", "")
    es_postgres = "postgres" in db_url.lower()

    if es_postgres:
        # Postgres soporta ADD COLUMN IF NOT EXISTS
        migraciones = [
            "ALTER TABLE clinic_clinicas ADD COLUMN IF NOT EXISTS congelada BOOLEAN DEFAULT FALSE",
            "ALTER TABLE clinic_clinicas ADD COLUMN IF NOT EXISTS motivo_suspension VARCHAR(300) DEFAULT ''",
            "ALTER TABLE clinic_clinicas ADD COLUMN IF NOT EXISTS fecha_suspension TIMESTAMP",
            "ALTER TABLE clinic_clinicas ADD COLUMN IF NOT EXISTS fecha_proximo_pago TIMESTAMP",
            "ALTER TABLE clinic_clinicas ADD COLUMN IF NOT EXISTS monto_mensual_usd INTEGER DEFAULT 0",
            "ALTER TABLE clinic_clinicas ADD COLUMN IF NOT EXISTS google_calendar_id VARCHAR(200) DEFAULT ''",
            # IA SofIA per-tenant (Sprint Opcion B)
            "ALTER TABLE clinic_clinicas ADD COLUMN IF NOT EXISTS ia_activa BOOLEAN DEFAULT FALSE",
            "ALTER TABLE clinic_clinicas ADD COLUMN IF NOT EXISTS ia_saludo VARCHAR(500) DEFAULT ''",
            "ALTER TABLE clinic_clinicas ADD COLUMN IF NOT EXISTS ia_servicios TEXT DEFAULT ''",
            "ALTER TABLE clinic_clinicas ADD COLUMN IF NOT EXISTS ia_horario VARCHAR(300) DEFAULT ''",
            "ALTER TABLE clinic_clinicas ADD COLUMN IF NOT EXISTS ia_precios_basicos TEXT DEFAULT ''",
            "ALTER TABLE clinic_clinicas ADD COLUMN IF NOT EXISTS ia_instrucciones_extra TEXT DEFAULT ''",
            # Recordatorios automáticos (Sprint Opcion B Día 3)
            "ALTER TABLE clinic_citas ADD COLUMN IF NOT EXISTS recordatorio_24h_enviado BOOLEAN DEFAULT FALSE",
            "ALTER TABLE clinic_citas ADD COLUMN IF NOT EXISTS recordatorio_2h_enviado BOOLEAN DEFAULT FALSE",
            # Voice Bot per-tenant (Sprint Voice Bot Día 5)
            "ALTER TABLE clinic_clinicas ADD COLUMN IF NOT EXISTS voz_confirmar_citas_activa BOOLEAN DEFAULT FALSE",
            "ALTER TABLE clinic_citas ADD COLUMN IF NOT EXISTS voz_confirmacion_encolada BOOLEAN DEFAULT FALSE",
            # Voice Bot Mock Mode
            "ALTER TABLE voice_config ADD COLUMN IF NOT EXISTS mock_mode BOOLEAN DEFAULT FALSE",
        ]
    else:
        # SQLite NO soporta IF NOT EXISTS para columnas, hay que verificar manualmente
        migraciones = []
        async with engine.connect() as conn:
            try:
                result = await conn.execute(text("PRAGMA table_info(clinic_clinicas)"))
                columnas_existentes = {row[1] for row in result.fetchall()}
                if "congelada" not in columnas_existentes:
                    migraciones.append("ALTER TABLE clinic_clinicas ADD COLUMN congelada BOOLEAN DEFAULT 0")
                if "motivo_suspension" not in columnas_existentes:
                    migraciones.append("ALTER TABLE clinic_clinicas ADD COLUMN motivo_suspension VARCHAR(300) DEFAULT ''")
                if "fecha_suspension" not in columnas_existentes:
                    migraciones.append("ALTER TABLE clinic_clinicas ADD COLUMN fecha_suspension DATETIME")
                if "fecha_proximo_pago" not in columnas_existentes:
                    migraciones.append("ALTER TABLE clinic_clinicas ADD COLUMN fecha_proximo_pago DATETIME")
                if "monto_mensual_usd" not in columnas_existentes:
                    migraciones.append("ALTER TABLE clinic_clinicas ADD COLUMN monto_mensual_usd INTEGER DEFAULT 0")
                if "google_calendar_id" not in columnas_existentes:
                    migraciones.append("ALTER TABLE clinic_clinicas ADD COLUMN google_calendar_id VARCHAR(200) DEFAULT ''")
                # IA SofIA per-tenant (Sprint Opcion B)
                if "ia_activa" not in columnas_existentes:
                    migraciones.append("ALTER TABLE clinic_clinicas ADD COLUMN ia_activa BOOLEAN DEFAULT 0")
                if "ia_saludo" not in columnas_existentes:
                    migraciones.append("ALTER TABLE clinic_clinicas ADD COLUMN ia_saludo VARCHAR(500) DEFAULT ''")
                if "ia_servicios" not in columnas_existentes:
                    migraciones.append("ALTER TABLE clinic_clinicas ADD COLUMN ia_servicios TEXT DEFAULT ''")
                if "ia_horario" not in columnas_existentes:
                    migraciones.append("ALTER TABLE clinic_clinicas ADD COLUMN ia_horario VARCHAR(300) DEFAULT ''")
                if "ia_precios_basicos" not in columnas_existentes:
                    migraciones.append("ALTER TABLE clinic_clinicas ADD COLUMN ia_precios_basicos TEXT DEFAULT ''")
                if "ia_instrucciones_extra" not in columnas_existentes:
                    migraciones.append("ALTER TABLE clinic_clinicas ADD COLUMN ia_instrucciones_extra TEXT DEFAULT ''")

                # Recordatorios automáticos (Sprint Opcion B Día 3) — tabla clinic_citas
                try:
                    result_citas = await conn.execute(text("PRAGMA table_info(clinic_citas)"))
                    columnas_citas = {row[1] for row in result_citas.fetchall()}
                    if "recordatorio_24h_enviado" not in columnas_citas:
                        migraciones.append("ALTER TABLE clinic_citas ADD COLUMN recordatorio_24h_enviado BOOLEAN DEFAULT 0")
                    if "recordatorio_2h_enviado" not in columnas_citas:
                        migraciones.append("ALTER TABLE clinic_citas ADD COLUMN recordatorio_2h_enviado BOOLEAN DEFAULT 0")
                    # Voice Bot Día 5
                    if "voz_confirmacion_encolada" not in columnas_citas:
                        migraciones.append("ALTER TABLE clinic_citas ADD COLUMN voz_confirmacion_encolada BOOLEAN DEFAULT 0")
                except Exception:
                    pass
                # Voice Bot Día 5: campo en clinic_clinicas
                if "voz_confirmar_citas_activa" not in columnas_existentes:
                    migraciones.append("ALTER TABLE clinic_clinicas ADD COLUMN voz_confirmar_citas_activa BOOLEAN DEFAULT 0")
                # Voice Bot mock_mode en voice_config
                try:
                    result_vc = await conn.execute(text("PRAGMA table_info(voice_config)"))
                    columnas_vc = {row[1] for row in result_vc.fetchall()}
                    if columnas_vc and "mock_mode" not in columnas_vc:
                        migraciones.append("ALTER TABLE voice_config ADD COLUMN mock_mode BOOLEAN DEFAULT 0")
                except Exception:
                    pass
            except Exception:
                pass  # Tabla no existe todavía, create_all la creará completa

    if migraciones:
        async with engine.begin() as conn:
            for sql in migraciones:
                try:
                    await conn.execute(text(sql))
                    print(f"[migración OK] {sql[:80]}")
                except Exception as e:
                    print(f"[migración skip] {sql[:80]} -> {str(e)[:80]}")


# ════════════════════════════════════════════════════════════
# SEED DE DEMO — Datos de ejemplo para nuevos usuarios
# ════════════════════════════════════════════════════════════

async def cargar_demo_data(clinica_id: int) -> dict:
    """Carga pacientes, mensajes, llamadas y plantillas de ejemplo."""
    from datetime import timedelta
    ahora = datetime.utcnow()
    creados = {"pacientes": 0, "mensajes": 0, "llamadas": 0, "plantillas": 0}

    pacientes_demo = [
        {"nombre": "María Camila Rojas", "telefono": "+573201234567", "email": "maria.rojas@email.com",
         "estado": "activo", "tratamiento_actual": "Ortodoncia", "notas_basicas": "Tratamiento de 18 meses con brackets metálicos. Próximo control en 30 días."},
        {"nombre": "Carlos Andrés Pérez", "telefono": "+573109876543", "email": "carlos.perez@email.com",
         "estado": "nuevo", "tratamiento_actual": "Limpieza dental", "notas_basicas": "Primera consulta. Mencionó sensibilidad en muela superior derecha."},
        {"nombre": "Laura Sofía Méndez", "telefono": "+573157654321", "email": "laura.mendez@email.com",
         "estado": "activo", "tratamiento_actual": "Blanqueamiento", "notas_basicas": "Tercera sesión completada. Resultados muy buenos."},
        {"nombre": "Jorge Luis Castro", "telefono": "+573002468135", "email": "jorge.castro@email.com",
         "estado": "inactivo", "tratamiento_actual": "Periodoncia", "notas_basicas": "No volvió a control después de 6 meses. Llamar para reactivar."},
        {"nombre": "Andrea Patricia Gómez", "telefono": "+573225556677", "email": "andrea.gomez@email.com",
         "estado": "dado_de_alta", "tratamiento_actual": "Implante", "notas_basicas": "Implante exitoso. Control anual programado."},
    ]

    mensajes_demo = [
        # (paciente_idx, dir, canal, contenido, hours_ago)
        (0, "entrada", "whatsapp", "Hola doctor, ¿a qué hora puedo ir mañana?", 2),
        (0, "salida",  "whatsapp", "Hola María, tenemos disponibilidad a las 3pm o 5pm. ¿Cuál te queda mejor?", 1),
        (0, "entrada", "whatsapp", "A las 5pm está perfecto, gracias!", 0.5),
        (1, "entrada", "whatsapp", "Buenos días, quería preguntar precios de limpieza", 8),
        (1, "salida",  "whatsapp", "Buenos días Carlos. La limpieza profesional cuesta $150.000 e incluye fluorización.", 7),
        (2, "entrada", "instagram", "Vi sus historias del blanqueamiento, me interesa. ¿Cómo funciona?", 24),
        (3, "salida",  "whatsapp", "Hola Jorge, ¿cómo va todo? Hace tiempo no sabemos de ti. ¿Agendamos un control?", 72),
    ]

    llamadas_demo = [
        # (paciente_idx, direccion, duracion_min, resultado, notas, days_ago)
        (3, "salida",  5, "volver_a_llamar", "No contestó. Reintentar mañana.", 1),
        (1, "entrada", 8, "agendado", "Pregunta precios. Agendó limpieza para el viernes.", 0),
        (0, "salida",  3, "agendado", "Confirmé cita de mañana 5pm.", 0),
    ]

    plantillas_demo = [
        ("Saludo inicial", "saludo", "¡Hola {nombre}! Soy del consultorio. ¿En qué puedo ayudarte hoy?"),
        ("Confirmación de cita", "confirmacion", "Hola {nombre}, te confirmo tu cita de {tratamiento} para mañana. Te esperamos!"),
        ("Recordatorio control", "seguimiento", "Hola {nombre}, ya pasó tu tiempo de control. ¿Agendamos esta semana?"),
        ("Horarios de atención", "horarios", "Atendemos de lunes a viernes de 8am a 6pm, y sábados de 9am a 1pm."),
    ]

    async with async_session() as session:
        pacientes_creados = []
        for p_data in pacientes_demo:
            p = Paciente(
                clinica_id=clinica_id,
                fuente="demo",
                primer_contacto=ahora - timedelta(days=30),
                ultimo_contacto=ahora,
                total_mensajes=2,
                **p_data,
            )
            session.add(p)
            pacientes_creados.append(p)
            creados["pacientes"] += 1
        await session.flush()

        from agent.clinic_models import MensajeUnificado, Llamada, PlantillaRespuesta
        for idx, dir_, canal, contenido, hours_ago in mensajes_demo:
            ts = ahora - timedelta(hours=hours_ago)
            session.add(MensajeUnificado(
                clinica_id=clinica_id,
                paciente_id=pacientes_creados[idx].id,
                canal=canal, direccion=dir_, contenido=contenido,
                leido=(dir_ == "salida"),
                timestamp=ts,
            ))
            creados["mensajes"] += 1

        for idx, dir_, dur_min, resultado, notas, days_ago in llamadas_demo:
            session.add(Llamada(
                clinica_id=clinica_id,
                paciente_id=pacientes_creados[idx].id,
                direccion=dir_, duracion_seg=dur_min * 60,
                resultado=resultado, notas=notas,
                timestamp=ahora - timedelta(days=days_ago),
            ))
            creados["llamadas"] += 1

        for titulo, cat, contenido in plantillas_demo:
            session.add(PlantillaRespuesta(
                clinica_id=clinica_id, titulo=titulo,
                categoria=cat, contenido=contenido,
            ))
            creados["plantillas"] += 1

        await session.commit()
    return creados
