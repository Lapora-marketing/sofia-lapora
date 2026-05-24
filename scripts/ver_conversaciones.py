#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# scripts/ver_conversaciones.py — Ver historial de conversaciones
# Generado por AgentKit

"""
Dashboard para visualizar todas las conversaciones almacenadas en la base de datos.
Muestra:
- Historial completo por número de teléfono
- Timestamps de cada mensaje
- Estadísticas (total mensajes, conversaciones únicas)
"""

import asyncio
import sys
import os
from datetime import datetime
from sqlalchemy import select, func

# Configurar encoding para Windows
if sys.platform == "win32":
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8')

# Agregar el directorio raíz al path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv
from agent.memory import inicializar_db, async_session, Mensaje

load_dotenv()


async def get_estadisticas():
    """Obtiene estadísticas generales del sistema."""
    async with async_session() as session:
        # Total de mensajes
        total_mensajes = await session.execute(select(func.count(Mensaje.id)))
        total = total_mensajes.scalar() or 0

        # Teléfonos únicos (conversaciones)
        telefonos_query = await session.execute(
            select(func.count(func.distinct(Mensaje.telefono)))
        )
        total_conversaciones = telefonos_query.scalar() or 0

        # Breakdown user vs assistant
        user_query = await session.execute(
            select(func.count(Mensaje.id)).where(Mensaje.role == "user")
        )
        mensajes_usuario = user_query.scalar() or 0

        asistente_query = await session.execute(
            select(func.count(Mensaje.id)).where(Mensaje.role == "assistant")
        )
        mensajes_asistente = asistente_query.scalar() or 0

        return {
            "total_mensajes": total,
            "total_conversaciones": total_conversaciones,
            "mensajes_usuario": mensajes_usuario,
            "mensajes_asistente": mensajes_asistente,
        }


async def get_conversaciones():
    """Obtiene todas las conversaciones agrupadas por teléfono."""
    async with async_session() as session:
        resultado = await session.execute(
            select(Mensaje)
            .order_by(Mensaje.telefono, Mensaje.timestamp)
        )
        mensajes = resultado.scalars().all()

        # Agrupar por teléfono
        conversaciones = {}
        for msg in mensajes:
            if msg.telefono not in conversaciones:
                conversaciones[msg.telefono] = []
            conversaciones[msg.telefono].append({
                "role": msg.role,
                "content": msg.content,
                "timestamp": msg.timestamp,
            })

        return conversaciones


def formatear_timestamp(dt):
    """Formatea un datetime para visualización."""
    if dt is None:
        return "N/A"
    return dt.strftime("%d/%m/%Y %H:%M:%S")


async def mostrar_conversacion(telefono, mensajes):
    """Muestra una conversación individual."""
    print(f"\n{'=' * 80}")
    print(f"📱 Teléfono: {telefono}")
    print(f"   Total mensajes: {len(mensajes)}")
    print(f"{'=' * 80}\n")

    for i, msg in enumerate(mensajes, 1):
        emoji = "👤" if msg["role"] == "user" else "🤖"
        timestamp = formatear_timestamp(msg["timestamp"])

        # Limitar el contenido mostrado si es muy largo
        contenido = msg["content"]
        if len(contenido) > 200:
            contenido = contenido[:197] + "..."

        print(f"{i}. {emoji} [{msg['role'].upper()}] {timestamp}")
        print(f"   {contenido}\n")


async def mostrar_resumen():
    """Muestra un resumen general."""
    print("\n" + "=" * 80)
    print("  📊 RESUMEN DE CONVERSACIONES")
    print("=" * 80 + "\n")

    stats = await get_estadisticas()

    print(f"Total de mensajes:        {stats['total_mensajes']}")
    print(f"Conversaciones únicas:    {stats['total_conversaciones']}")
    print(f"  ├─ Mensajes de usuario: {stats['mensajes_usuario']}")
    print(f"  └─ Respuestas de SofIA: {stats['mensajes_asistente']}\n")


async def main():
    """Menú principal."""
    await inicializar_db()

    # Mostrar resumen
    await mostrar_resumen()

    # Obtener conversaciones
    conversaciones = await get_conversaciones()

    if not conversaciones:
        print("❌ No hay conversaciones registradas aún.\n")
        return

    # Listar teléfonos únicos
    print("Conversaciones disponibles:\n")
    telefonos_lista = sorted(conversaciones.keys())
    for idx, telefono in enumerate(telefonos_lista, 1):
        count = len(conversaciones[telefono])
        print(f"  {idx}. {telefono} — {count} mensajes")

    print(f"\nTotal de conversaciones: {len(telefonos_lista)}\n")

    # Opción: mostrar detalle
    while True:
        opcion = input("¿Ver detalles de cuál conversación? (número, 'todo', o 'salir'): ").strip()

        if opcion.lower() == "salir":
            print("\n¡Hasta luego!\n")
            break

        if opcion.lower() == "todo":
            for telefono in telefonos_lista:
                await mostrar_conversacion(telefono, conversaciones[telefono])
            continue

        try:
            idx = int(opcion) - 1
            if 0 <= idx < len(telefonos_lista):
                telefono = telefonos_lista[idx]
                await mostrar_conversacion(telefono, conversaciones[telefono])
            else:
                print("❌ Opción inválida\n")
        except ValueError:
            print("❌ Ingresa un número válido\n")


if __name__ == "__main__":
    print("\n" + "=" * 80)
    print("  🗂️  HISTORIAL DE CONVERSACIONES DE SofIA")
    print("=" * 80)

    asyncio.run(main())
