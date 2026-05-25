# agent/memory.py — Memoria de conversaciones con SQLite
# Generado por AgentKit

"""
Sistema de memoria de SofIA. Guarda el historial de conversaciones
por numero de telefono usando SQLite (local) o PostgreSQL (produccion).
"""

import os
from datetime import datetime
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy import String, Text, DateTime, select, Integer
from dotenv import load_dotenv

load_dotenv(override=True)

# Configuracion de base de datos
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite+aiosqlite:///./agentkit.db")

# Si es PostgreSQL en produccion, ajustar el esquema de URL
if DATABASE_URL.startswith("postgresql://"):
    DATABASE_URL = DATABASE_URL.replace("postgresql://", "postgresql+asyncpg://", 1)

engine = create_async_engine(DATABASE_URL, echo=False)
async_session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


class Mensaje(Base):
    """Modelo de mensaje en la base de datos."""
    __tablename__ = "mensajes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    telefono: Mapped[str] = mapped_column(String(50), index=True)
    role: Mapped[str] = mapped_column(String(20))  # "user" o "assistant"
    content: Mapped[str] = mapped_column(Text)
    timestamp: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class Recordatorio(Base):
    """
    Modelo de recordatorio de cita en la base de datos.
    Se programa cuando SofIA agenda una cita y se envia 1 hora antes
    automaticamente por el scheduler.
    """
    __tablename__ = "recordatorios"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    telefono: Mapped[str] = mapped_column(String(50), index=True)
    nombre_doctor: Mapped[str] = mapped_column(String(200))
    evento_id: Mapped[str] = mapped_column(String(200))
    fecha_cita: Mapped[datetime] = mapped_column(DateTime, index=True)
    enviar_en: Mapped[datetime] = mapped_column(DateTime, index=True)  # fecha_cita - 1h
    enviado: Mapped[int] = mapped_column(Integer, default=0)  # 0=pendiente, 1=enviado, -1=error
    creado_en: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class Contacto(Base):
    """
    Modelo de contacto / lead en el CRM.
    Se crea automaticamente cuando alguien escribe por primera vez a SofIA.
    """
    __tablename__ = "contactos"

    telefono: Mapped[str] = mapped_column(String(50), primary_key=True)

    # Info personal
    nombre: Mapped[str] = mapped_column(String(200), default="", nullable=True)
    email: Mapped[str] = mapped_column(String(200), default="", nullable=True)

    # Info profesional (medico)
    especialidad: Mapped[str] = mapped_column(String(100), default="", nullable=True)
    ciudad: Mapped[str] = mapped_column(String(100), default="", nullable=True)
    presencia_digital: Mapped[str] = mapped_column(String(50), default="", nullable=True)
    volumen_pacientes: Mapped[str] = mapped_column(String(50), default="", nullable=True)
    reto_principal: Mapped[Text] = mapped_column(Text, default="", nullable=True)
    perdida_mensual: Mapped[str] = mapped_column(String(50), default="", nullable=True)

    # Estado del lead
    # nuevo | contactado | calificado | agendado | cliente | perdido
    estado: Mapped[str] = mapped_column(String(50), default="nuevo", index=True)
    fuente: Mapped[str] = mapped_column(String(100), default="whatsapp", nullable=True)
    tags: Mapped[str] = mapped_column(Text, default="", nullable=True)  # separados por coma
    notas: Mapped[Text] = mapped_column(Text, default="", nullable=True)

    # Metricas
    total_mensajes: Mapped[int] = mapped_column(Integer, default=0)
    citas_agendadas: Mapped[int] = mapped_column(Integer, default=0)

    # Timestamps
    primer_contacto: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)
    ultimo_contacto: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)


class Prospecto(Base):
    """
    Modelo de prospecto de outreach (clinicas/consultorios a los que enviamos email).
    Diferente de Contacto (que es WhatsApp). Se cruza con Contacto via telefono.
    """
    __tablename__ = "prospectos"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

    # Datos base
    nombre_negocio:   Mapped[str] = mapped_column(String(200), index=True)
    nombre_doctor:    Mapped[str] = mapped_column(String(200), default="", nullable=True)
    especialidad:     Mapped[str] = mapped_column(String(150), default="", index=True)
    email:            Mapped[str] = mapped_column(String(200), default="", index=True)
    telefono:         Mapped[str] = mapped_column(String(50), default="", index=True)
    direccion:        Mapped[str] = mapped_column(String(300), default="", nullable=True)
    tipo:             Mapped[str] = mapped_column(String(50), default="", nullable=True)
    prioridad:        Mapped[str] = mapped_column(String(20), default="media", nullable=True)
    website:          Mapped[str] = mapped_column(String(300), default="", nullable=True)
    email_verificado: Mapped[str] = mapped_column(String(20), default="PENDIENTE")  # SI / PENDIENTE

    # Estado de la campaña
    # no_enviado | enviado_sin_respuesta | respondido | interesado | cliente | rebotado
    estado:           Mapped[str] = mapped_column(String(40), default="no_enviado", index=True)
    cupon:            Mapped[str] = mapped_column(String(30), default="", nullable=True)
    fecha_envio:      Mapped[datetime] = mapped_column(DateTime, nullable=True)
    fecha_respuesta:  Mapped[datetime] = mapped_column(DateTime, nullable=True)
    tipo_respuesta:   Mapped[str] = mapped_column(String(20), default="", nullable=True)  # email | whatsapp
    asunto_respuesta: Mapped[str] = mapped_column(String(300), default="", nullable=True)
    preview_respuesta: Mapped[str] = mapped_column(Text, default="", nullable=True)
    notas:            Mapped[Text] = mapped_column(Text, default="", nullable=True)

    # Timestamps
    creado_en:        Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    actualizado_en:   Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


async def upsert_prospecto(datos: dict) -> Prospecto:
    """Crea o actualiza un prospecto. Hace match por email o telefono."""
    async with async_session() as session:
        prospecto = None
        if datos.get("email"):
            q = select(Prospecto).where(Prospecto.email == datos["email"])
            prospecto = (await session.execute(q)).scalar_one_or_none()
        if not prospecto and datos.get("telefono"):
            q = select(Prospecto).where(Prospecto.telefono == datos["telefono"])
            prospecto = (await session.execute(q)).scalar_one_or_none()

        ahora = datetime.utcnow()
        if prospecto is None:
            prospecto = Prospecto(creado_en=ahora, actualizado_en=ahora)
            for k, v in datos.items():
                if hasattr(prospecto, k) and v is not None:
                    setattr(prospecto, k, v)
            session.add(prospecto)
        else:
            for k, v in datos.items():
                if hasattr(prospecto, k) and v is not None:
                    setattr(prospecto, k, v)
            prospecto.actualizado_en = ahora

        await session.commit()
        await session.refresh(prospecto)
        return prospecto


async def listar_prospectos(estado: str | None = None,
                             buscar: str | None = None,
                             solo_verificados: bool = True) -> list[Prospecto]:
    """Lista prospectos con filtros opcionales."""
    from sqlalchemy import or_
    async with async_session() as session:
        q = select(Prospecto)
        if solo_verificados:
            q = q.where(Prospecto.email_verificado == "SI")
        if estado and estado != "todos":
            q = q.where(Prospecto.estado == estado)
        if buscar:
            p = f"%{buscar}%"
            q = q.where(or_(
                Prospecto.nombre_negocio.ilike(p),
                Prospecto.email.ilike(p),
                Prospecto.especialidad.ilike(p),
            ))
        q = q.order_by(Prospecto.estado.asc(), Prospecto.nombre_negocio.asc())
        return list((await session.execute(q)).scalars().all())


async def contar_prospectos_por_estado() -> dict[str, int]:
    """Devuelve {estado: count} para todos los prospectos verificados."""
    from sqlalchemy import func
    async with async_session() as session:
        q = (
            select(Prospecto.estado, func.count(Prospecto.id))
            .where(Prospecto.email_verificado == "SI")
            .group_by(Prospecto.estado)
        )
        rows = (await session.execute(q)).all()
        return {estado: count for estado, count in rows}


async def upsert_contacto(telefono: str, datos: dict | None = None):
    """
    Crea o actualiza un contacto. Se llama automaticamente cuando llega un mensaje.

    Args:
        telefono: Numero de WhatsApp (clave primaria)
        datos: Diccionario con campos a actualizar (opcional)
    """
    async with async_session() as session:
        # Buscar contacto existente
        query = select(Contacto).where(Contacto.telefono == telefono)
        result = await session.execute(query)
        contacto = result.scalar_one_or_none()

        ahora = datetime.utcnow()

        if contacto is None:
            # Crear nuevo contacto
            contacto = Contacto(
                telefono=telefono,
                primer_contacto=ahora,
                ultimo_contacto=ahora,
                total_mensajes=1,
                estado="nuevo",
                fuente="whatsapp",
            )
            if datos:
                for key, value in datos.items():
                    if hasattr(contacto, key) and value:
                        setattr(contacto, key, value)
            session.add(contacto)
        else:
            # Actualizar contacto existente
            contacto.ultimo_contacto = ahora
            contacto.total_mensajes = (contacto.total_mensajes or 0) + 1
            if datos:
                for key, value in datos.items():
                    if hasattr(contacto, key) and value:
                        setattr(contacto, key, value)

        await session.commit()


async def actualizar_contacto(telefono: str, datos: dict):
    """Actualiza campos especificos de un contacto sin incrementar mensajes."""
    async with async_session() as session:
        query = select(Contacto).where(Contacto.telefono == telefono)
        result = await session.execute(query)
        contacto = result.scalar_one_or_none()

        if contacto is None:
            return False

        for key, value in datos.items():
            if hasattr(contacto, key):
                setattr(contacto, key, value)

        await session.commit()
        return True


async def incrementar_citas_agendadas(telefono: str):
    """Incrementa el contador de citas agendadas y cambia estado a 'agendado'."""
    async with async_session() as session:
        query = select(Contacto).where(Contacto.telefono == telefono)
        result = await session.execute(query)
        contacto = result.scalar_one_or_none()

        if contacto is None:
            # Crear contacto si no existe
            contacto = Contacto(
                telefono=telefono,
                citas_agendadas=1,
                estado="agendado",
                total_mensajes=1,
            )
            session.add(contacto)
        else:
            contacto.citas_agendadas = (contacto.citas_agendadas or 0) + 1
            contacto.estado = "agendado"

        await session.commit()


async def inicializar_db():
    """Crea las tablas si no existen."""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


async def guardar_mensaje(telefono: str, role: str, content: str):
    """Guarda un mensaje en el historial de conversacion."""
    async with async_session() as session:
        mensaje = Mensaje(
            telefono=telefono,
            role=role,
            content=content,
            timestamp=datetime.utcnow(),
        )
        session.add(mensaje)
        await session.commit()


async def obtener_historial(telefono: str, limite: int = 50) -> list[dict]:
    """
    Recupera los ultimos N mensajes de una conversacion.

    Args:
        telefono: Numero de telefono del cliente
        limite: Maximo de mensajes a recuperar (default: 50)

    Returns:
        Lista de diccionarios con role y content (orden cronologico)
    """
    async with async_session() as session:
        query = (
            select(Mensaje)
            .where(Mensaje.telefono == telefono)
            .order_by(Mensaje.timestamp.desc())
            .limit(limite)
        )
        result = await session.execute(query)
        mensajes = result.scalars().all()

        # Invertir para orden cronologico (los mas recientes estan primero)
        mensajes = list(mensajes)
        mensajes.reverse()

        return [
            {"role": msg.role, "content": msg.content}
            for msg in mensajes
        ]


async def limpiar_historial(telefono: str):
    """Borra todo el historial de una conversacion."""
    async with async_session() as session:
        query = select(Mensaje).where(Mensaje.telefono == telefono)
        result = await session.execute(query)
        mensajes = result.scalars().all()
        for msg in mensajes:
            await session.delete(msg)
        await session.commit()
