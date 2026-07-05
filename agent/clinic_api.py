# -*- coding: utf-8 -*-
# agent/clinic_api.py — REST API custom para clínicas Studio
# Lapora Marketing Digital

"""
API REST pública para clínicas con plan Studio.

Autenticación: header `X-API-Key: lpk_xxxxxxxxxxxxx`
Aislamiento: cada key está bound a una clínica → solo ve sus datos
Scopes:
  - read: GET endpoints
  - read,write: GET + POST
  - admin: todos + DELETE

Endpoints:
  GET  /api/v1/info           — info de la clínica (test rápido)
  GET  /api/v1/pacientes      — lista paginada
  POST /api/v1/pacientes      — crear paciente
  GET  /api/v1/pacientes/{id} — detalle
  GET  /api/v1/citas          — lista
  POST /api/v1/citas          — crear cita
  GET  /api/v1/mensajes       — últimos mensajes
  POST /api/v1/mensajes       — registrar mensaje de conversación
"""

from datetime import datetime
from typing import Optional
from fastapi import APIRouter, Header, HTTPException, Query
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from sqlalchemy import select, func, desc, and_

from agent.memory import async_session
from agent.clinic_models import (
    Clinica, Paciente, MensajeUnificado, CitaClinic,
    autenticar_api_key, ApiKey,
)


router = APIRouter(prefix="/api/v1", tags=["public-api"])


# ════════════════════════════════════════════════════════════
# AUTENTICACIÓN
# ════════════════════════════════════════════════════════════

async def _autenticar(
    x_api_key: Optional[str] = Header(None),
    requiere_write: bool = False,
) -> tuple[Clinica, ApiKey]:
    """Valida la API key y devuelve (clinica, api_key) o lanza 401/403."""
    if not x_api_key:
        raise HTTPException(
            status_code=401,
            detail="API key requerida en header X-API-Key",
        )

    ak = await autenticar_api_key(x_api_key)
    if not ak:
        raise HTTPException(status_code=401, detail="API key inválida o revocada")

    if requiere_write and "write" not in ak.scopes and "admin" not in ak.scopes:
        raise HTTPException(
            status_code=403,
            detail=f"Esta API key tiene scope '{ak.scopes}' — necesita 'write' o 'admin'",
        )

    async with async_session() as session:
        clinica = (await session.execute(
            select(Clinica).where(Clinica.id == ak.clinica_id)
        )).scalar_one_or_none()

    if not clinica:
        raise HTTPException(status_code=404, detail="Clínica asociada no encontrada")
    if clinica.congelada:
        raise HTTPException(status_code=402, detail="Clínica congelada por falta de pago")
    if not clinica.activo:
        raise HTTPException(status_code=410, detail="Clínica desactivada")

    # API solo disponible para plan Studio
    if not clinica.es_studio():
        raise HTTPException(
            status_code=402,
            detail="REST API es exclusiva del plan Studio. Sube de plan para acceder.",
        )

    return clinica, ak


# ════════════════════════════════════════════════════════════
# MODELOS PYDANTIC PARA RESPONSES Y REQUESTS
# ════════════════════════════════════════════════════════════

class PacienteIn(BaseModel):
    nombre: str = Field(..., min_length=2, max_length=200)
    telefono: str = Field(default="", max_length=50)
    email: str = Field(default="", max_length=200)
    tratamiento_actual: str = Field(default="", max_length=300)
    notas_basicas: str = Field(default="", max_length=2000)
    estado: str = Field(default="nuevo")


class PacienteOut(BaseModel):
    id: int
    nombre: str
    telefono: str
    email: str
    estado: str
    tratamiento_actual: str
    total_mensajes: int
    total_citas: int
    valor_total: int
    primer_contacto: datetime
    ultimo_contacto: datetime


class CitaIn(BaseModel):
    paciente_id: int
    fecha_hora: datetime
    duracion_min: int = Field(default=30, ge=5, le=480)
    motivo: str = Field(default="", max_length=300)
    estado: str = Field(default="agendada")


class CitaOut(BaseModel):
    id: int
    paciente_id: int
    fecha_hora: datetime
    duracion_min: int
    motivo: str
    estado: str


class MensajeIn(BaseModel):
    paciente_id: int
    contenido: str = Field(..., min_length=1, max_length=5000)
    canal: str = Field(default="instagram", max_length=30)
    direccion: str = Field(default="entrada")
    respondido_por: str = Field(default="", max_length=100)


# ════════════════════════════════════════════════════════════
# ENDPOINTS
# ════════════════════════════════════════════════════════════

@router.get("/info")
async def info(x_api_key: Optional[str] = Header(None)):
    """Info de la clínica autenticada (útil para probar la key)."""
    clinica, ak = await _autenticar(x_api_key)
    return {
        "clinica_id": clinica.id,
        "nombre": clinica.nombre,
        "plan": clinica.plan,
        "slug": clinica.slug,
        "api_key_scopes": ak.scopes,
        "api_key_requests": ak.requests_count,
    }


# ──── PACIENTES ────

@router.get("/pacientes")
async def list_pacientes(
    page: int = Query(1, ge=1),
    per_page: int = Query(50, ge=1, le=200),
    estado: Optional[str] = None,
    search: Optional[str] = None,
    x_api_key: Optional[str] = Header(None),
):
    clinica, _ = await _autenticar(x_api_key)
    offset = (page - 1) * per_page

    async with async_session() as session:
        q = select(Paciente).where(Paciente.clinica_id == clinica.id)
        if estado:
            q = q.where(Paciente.estado == estado)
        if search:
            q = q.where(Paciente.nombre.ilike(f"%{search[:100]}%"))

        total = (await session.execute(
            select(func.count()).select_from(q.subquery())
        )).scalar() or 0

        rows = list((await session.execute(
            q.order_by(desc(Paciente.ultimo_contacto)).limit(per_page).offset(offset)
        )).scalars().all())

    return {
        "data": [
            {
                "id": p.id, "nombre": p.nombre, "telefono": p.telefono or "",
                "email": p.email or "", "estado": p.estado or "",
                "tratamiento_actual": p.tratamiento_actual or "",
                "total_mensajes": p.total_mensajes or 0,
                "total_citas": p.total_citas or 0,
                "valor_total": p.valor_total or 0,
                "primer_contacto": p.primer_contacto.isoformat() if p.primer_contacto else None,
                "ultimo_contacto": p.ultimo_contacto.isoformat() if p.ultimo_contacto else None,
            }
            for p in rows
        ],
        "pagination": {
            "page": page, "per_page": per_page, "total": total,
            "total_pages": (total + per_page - 1) // per_page,
        },
    }


@router.post("/pacientes")
async def create_paciente(
    paciente: PacienteIn,
    x_api_key: Optional[str] = Header(None),
):
    clinica, _ = await _autenticar(x_api_key, requiere_write=True)

    estados_validos = {"nuevo", "activo", "inactivo", "dado_de_alta"}
    if paciente.estado not in estados_validos:
        raise HTTPException(
            status_code=400,
            detail=f"estado debe ser uno de: {sorted(estados_validos)}",
        )

    async with async_session() as session:
        p = Paciente(
            clinica_id=clinica.id,
            nombre=paciente.nombre.strip(),
            telefono=paciente.telefono.strip(),
            email=paciente.email.strip().lower(),
            tratamiento_actual=paciente.tratamiento_actual,
            notas_basicas=paciente.notas_basicas,
            estado=paciente.estado,
            fuente="api",
            primer_contacto=datetime.utcnow(),
            ultimo_contacto=datetime.utcnow(),
        )
        session.add(p)
        await session.commit()
        await session.refresh(p)

    return JSONResponse(
        status_code=201,
        content={"id": p.id, "nombre": p.nombre, "estado": p.estado},
    )


@router.get("/pacientes/{paciente_id}")
async def get_paciente(
    paciente_id: int,
    x_api_key: Optional[str] = Header(None),
):
    clinica, _ = await _autenticar(x_api_key)
    async with async_session() as session:
        p = (await session.execute(
            select(Paciente)
            .where(Paciente.id == paciente_id)
            .where(Paciente.clinica_id == clinica.id)  # aislamiento
        )).scalar_one_or_none()
    if not p:
        raise HTTPException(status_code=404, detail="Paciente no encontrado")

    return {
        "id": p.id, "nombre": p.nombre, "telefono": p.telefono or "",
        "email": p.email or "", "estado": p.estado,
        "tratamiento_actual": p.tratamiento_actual or "",
        "notas_basicas": p.notas_basicas or "",
        "total_mensajes": p.total_mensajes or 0,
        "total_citas": p.total_citas or 0,
        "valor_total": p.valor_total or 0,
        "primer_contacto": p.primer_contacto.isoformat() if p.primer_contacto else None,
        "ultimo_contacto": p.ultimo_contacto.isoformat() if p.ultimo_contacto else None,
    }


# ──── CITAS ────

@router.get("/citas")
async def list_citas(
    page: int = Query(1, ge=1),
    per_page: int = Query(50, ge=1, le=200),
    estado: Optional[str] = None,
    desde: Optional[datetime] = None,
    hasta: Optional[datetime] = None,
    x_api_key: Optional[str] = Header(None),
):
    clinica, _ = await _autenticar(x_api_key)
    offset = (page - 1) * per_page

    async with async_session() as session:
        q = select(CitaClinic).where(CitaClinic.clinica_id == clinica.id)
        if estado:
            q = q.where(CitaClinic.estado == estado)
        if desde:
            q = q.where(CitaClinic.fecha_hora >= desde)
        if hasta:
            q = q.where(CitaClinic.fecha_hora <= hasta)

        total = (await session.execute(
            select(func.count()).select_from(q.subquery())
        )).scalar() or 0

        rows = list((await session.execute(
            q.order_by(desc(CitaClinic.fecha_hora)).limit(per_page).offset(offset)
        )).scalars().all())

    return {
        "data": [
            {
                "id": c.id, "paciente_id": c.paciente_id,
                "fecha_hora": c.fecha_hora.isoformat(),
                "duracion_min": c.duracion_min or 30,
                "motivo": c.motivo or "",
                "estado": c.estado,
            }
            for c in rows
        ],
        "pagination": {
            "page": page, "per_page": per_page, "total": total,
            "total_pages": (total + per_page - 1) // per_page,
        },
    }


@router.post("/citas")
async def create_cita(
    cita: CitaIn,
    x_api_key: Optional[str] = Header(None),
):
    clinica, _ = await _autenticar(x_api_key, requiere_write=True)

    async with async_session() as session:
        # Verificar que el paciente pertenece a esta clínica (defense-in-depth)
        p_existe = (await session.execute(
            select(Paciente.id)
            .where(Paciente.id == cita.paciente_id)
            .where(Paciente.clinica_id == clinica.id)
        )).scalar_one_or_none()
        if not p_existe:
            raise HTTPException(status_code=404, detail="Paciente no encontrado en esta clínica")

        c = CitaClinic(
            clinica_id=clinica.id,
            paciente_id=cita.paciente_id,
            fecha_hora=cita.fecha_hora,
            duracion_min=cita.duracion_min,
            motivo=cita.motivo,
            estado=cita.estado if cita.estado in {"agendada", "confirmada"} else "agendada",
        )
        session.add(c)
        await session.commit()
        await session.refresh(c)

    return JSONResponse(
        status_code=201,
        content={"id": c.id, "paciente_id": c.paciente_id, "fecha_hora": c.fecha_hora.isoformat()},
    )


# ──── MENSAJES ────

@router.get("/mensajes")
async def list_mensajes(
    page: int = Query(1, ge=1),
    per_page: int = Query(50, ge=1, le=200),
    paciente_id: Optional[int] = None,
    canal: Optional[str] = None,
    x_api_key: Optional[str] = Header(None),
):
    clinica, _ = await _autenticar(x_api_key)
    offset = (page - 1) * per_page

    async with async_session() as session:
        q = select(MensajeUnificado).where(MensajeUnificado.clinica_id == clinica.id)
        if paciente_id:
            q = q.where(MensajeUnificado.paciente_id == paciente_id)
        if canal:
            q = q.where(MensajeUnificado.canal == canal)

        total = (await session.execute(
            select(func.count()).select_from(q.subquery())
        )).scalar() or 0

        rows = list((await session.execute(
            q.order_by(desc(MensajeUnificado.timestamp)).limit(per_page).offset(offset)
        )).scalars().all())

    return {
        "data": [
            {
                "id": m.id, "paciente_id": m.paciente_id,
                "canal": m.canal, "direccion": m.direccion,
                "contenido": m.contenido,
                "leido": bool(m.leido),
                "respondido_por": m.respondido_por or "",
                "timestamp": m.timestamp.isoformat(),
            }
            for m in rows
        ],
        "pagination": {
            "page": page, "per_page": per_page, "total": total,
            "total_pages": (total + per_page - 1) // per_page,
        },
    }


@router.post("/mensajes")
async def create_mensaje(
    mensaje: MensajeIn,
    x_api_key: Optional[str] = Header(None),
):
    """Registra un mensaje de conversación externa (ej: Instagram vía LaporaChat)."""
    clinica, _ = await _autenticar(x_api_key, requiere_write=True)

    if mensaje.direccion not in {"entrada", "salida"}:
        raise HTTPException(
            status_code=400,
            detail="direccion debe ser 'entrada' o 'salida'",
        )

    async with async_session() as session:
        paciente = (await session.execute(
            select(Paciente)
            .where(Paciente.id == mensaje.paciente_id)
            .where(Paciente.clinica_id == clinica.id)  # aislamiento
        )).scalar_one_or_none()
        if not paciente:
            raise HTTPException(status_code=404, detail="Paciente no encontrado en esta clínica")

        m = MensajeUnificado(
            clinica_id=clinica.id,
            paciente_id=paciente.id,
            canal=mensaje.canal,
            direccion=mensaje.direccion,
            contenido=mensaje.contenido,
            leido=mensaje.direccion == "salida",
            respondido_por=mensaje.respondido_por,
            timestamp=datetime.utcnow(),
        )
        session.add(m)
        paciente.ultimo_contacto = datetime.utcnow()
        paciente.total_mensajes = (paciente.total_mensajes or 0) + 1
        await session.commit()
        await session.refresh(m)

    return JSONResponse(
        status_code=201,
        content={"id": m.id, "paciente_id": m.paciente_id},
    )
