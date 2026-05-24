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


async def obtener_historial(telefono: str, limite: int = 20) -> list[dict]:
    """
    Recupera los ultimos N mensajes de una conversacion.

    Args:
        telefono: Numero de telefono del cliente
        limite: Maximo de mensajes a recuperar (default: 20)

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
