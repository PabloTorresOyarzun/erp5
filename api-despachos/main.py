from fastapi import FastAPI, HTTPException, Depends, Header
from pydantic import BaseModel
from sqlalchemy import create_engine, Column, String, Text, DateTime, Boolean, Integer, JSON
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, Session
import os
import requests
import json
from datetime import datetime
from typing import List, Optional, Dict, Any
import base64

app = FastAPI()

# Configuración de base de datos
DATABASE_URL = f"postgresql://{os.getenv('DESPACHOS_DB_USER')}:{os.getenv('DESPACHOS_DB_PASSWORD')}@{os.getenv('DESPACHOS_DB_HOST')}/{os.getenv('DESPACHOS_DB_NAME')}"
SGD_URL = os.getenv('SGD_URL')
SGD_AUTH_TOKEN = os.getenv('SGD_AUTH_TOKEN')

# SQLAlchemy
engine = create_engine(DATABASE_URL)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

# Modelos de base de datos
class Despacho(Base):
    __tablename__ = "despachos"
    
    numero_despacho = Column(String, primary_key=True)
    estado = Column(String, default="pendiente")
    fecha_creacion = Column(DateTime, default=datetime.now)
    fecha_actualizacion = Column(DateTime, default=datetime.now, onupdate=datetime.now)
    documentos_requeridos = Column(JSON)
    documentos_presentes = Column(JSON)
    datos_extraidos = Column(JSON)
    extra_metadata = Column(JSON)

class Documento(Base):
    __tablename__ = "documentos"
    
    id = Column(Integer, primary_key=True, index=True)
    numero_despacho = Column(String, index=True)
    tipo_documento = Column(String)
    nombre_archivo = Column(String)
    contenido_base64 = Column(Text)
    procesado = Column(Boolean, default=False)
    datos_extraidos = Column(JSON)
    fecha_carga = Column(DateTime, default=datetime.now)
    fecha_procesamiento = Column(DateTime, nullable=True)

class Procedimiento(Base):
    __tablename__ = "procedimientos"
    
    id = Column(Integer, primary_key=True, index=True)
    numero_despacho = Column(String, index=True)
    tipo_procedimiento = Column(String)
    estado = Column(String, default="pendiente")
    usuario_asignado = Column(String, nullable=True)
    fecha_inicio = Column(DateTime, nullable=True)
    fecha_fin = Column(DateTime, nullable=True)
    datos = Column(JSON)

# Crear tablas
Base.metadata.create_all(bind=engine)

# Dependencia para obtener la sesión de BD
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

# Modelos Pydantic
class DespachoCreate(BaseModel):
    numero_despacho: str
    documentos_requeridos: List[str] = [
        "factura_comercial",
        "conocimiento_transporte",
        "certificado_origen",
        "packing_list"
    ]
    extra_metadata: Optional[Dict[str, Any]] = {}

class DocumentoUpload(BaseModel):
    numero_despacho: str
    tipo_documento: str
    nombre_archivo: str
    contenido_base64: str

class DespachoStatus(BaseModel):
    numero_despacho: str
    estado: str
    documentos_requeridos: List[str]
    documentos_presentes: List[str]
    documentos_faltantes: List[str]
    porcentaje_completitud: float
    puede_procesar: bool
    procedimientos: List[Dict[str, Any]]

class ProcedimientoCreate(BaseModel):
    numero_despacho: str
    tipo_procedimiento: str
    usuario_asignado: Optional[str] = None

# Configuración de tipos de documentos requeridos por defecto
DOCUMENTOS_REQUERIDOS_DEFAULT = [
    "factura_comercial",
    "conocimiento_embarque", 
    "certificado_origen",
    "packing_list"
]

# Endpoints
@app.get("/")
async def root():
    return {"service": "Despachos Management API", "status": "running"}

@app.get("/health")
async def health():
    return {
        "status": "healthy",
        "service": "api-despachos",
        "database": "connected",
        "sgd_configured": bool(SGD_URL and SGD_AUTH_TOKEN)
    }

@app.post("/despachos/crear")
async def crear_despacho(
    despacho_data: DespachoCreate,
    db: Session = Depends(get_db)
):
    """Crear un nuevo despacho"""
    existing = db.query(Despacho).filter(
        Despacho.numero_despacho == despacho_data.numero_despacho
    ).first()
    
    if existing:
        raise HTTPException(status_code=400, detail="El despacho ya existe")
    
    nuevo_despacho = Despacho(
        numero_despacho=despacho_data.numero_despacho,
        documentos_requeridos=despacho_data.documentos_requeridos,
        documentos_presentes=[],
        datos_extraidos={},
        extra_metadata=despacho_data.extra_metadata  # CORREGIDO
    )
    
    db.add(nuevo_despacho)
    db.commit()
    db.refresh(nuevo_despacho)
    
    return {"message": "Despacho creado exitosamente", "numero_despacho": nuevo_despacho.numero_despacho}

@app.get("/despachos/{numero_despacho}/sgd")
async def obtener_documentos_sgd(
    numero_despacho: str,
    db: Session = Depends(get_db)
):
    """Obtener documentos desde SGD"""
    if not SGD_URL or not SGD_AUTH_TOKEN:
        raise HTTPException(status_code=500, detail="SGD no configurado")
    
    # Verificar/crear despacho
    despacho = db.query(Despacho).filter(
        Despacho.numero_despacho == numero_despacho
    ).first()
    
    if not despacho:
        despacho = Despacho(
            numero_despacho=numero_despacho,
            documentos_requeridos=DOCUMENTOS_REQUERIDOS_DEFAULT,
            documentos_presentes=[],
            datos_extraidos={},
            extra_metadata={}
        )
        db.add(despacho)
        db.commit()
    
    try:
        # Construir URL
        url = f"{SGD_URL.rstrip('/')}/{numero_despacho}"
        
        print(f"\n🔍 CONSULTANDO SGD:")
        print(f"   URL: {url}")
        print(f"   Token: Bearer {SGD_AUTH_TOKEN[:20]}...")
        
        headers = {
            "Authorization": f"Bearer {SGD_AUTH_TOKEN}",
            "Accept": "application/json"
        }
        
        # Hacer la petición
        response = requests.get(url, headers=headers, timeout=30)
        
        print(f"📥 RESPUESTA:")
        print(f"   Status: {response.status_code}")
        
        if response.status_code == 404:
            return {
                "message": "Despacho no encontrado en SGD",
                "total": 0
            }
        
        response.raise_for_status()
        
        # Parsear JSON
        json_response = response.json()
        
        # La respuesta debe tener una estructura como {"data": [...]}
        documentos = json_response.get('data', [])
        
        if not isinstance(documentos, list):
            print(f"⚠️ Respuesta no es una lista: {type(documentos)}")
            return {
                "message": "Formato de respuesta inesperado",
                "total": 0
            }
        
        print(f"📄 Documentos encontrados: {len(documentos)}")
        
        documentos_importados = []
        
        for idx, doc in enumerate(documentos):
            try:
                # Extraer el base64
                documento_base64 = doc.get('documento', '')
                
                # Si viene con prefijo data:, quitarlo
                if documento_base64.startswith("data:application/pdf;base64,"):
                    documento_base64 = documento_base64.split(",", 1)[1]
                
                # Obtener nombre
                nombre = doc.get('nombre_documento', f'documento_{idx+1}.pdf')
                
                # Determinar tipo por nombre
                tipo = 'general'
                nombre_lower = nombre.lower()
                
                # Mejorar detección
                if 'factura' in nombre_lower or 'invoice' in nombre_lower or 'facture' in nombre_lower:
                    tipo = 'factura_comercial'
                elif 'bl' in nombre_lower or 'awb' in nombre_lower or 'waybill' in nombre_lower or 'transporte' in nombre_lower or 'bill-of-lading' in nombre_lower:
                    tipo = 'conocimiento_transporte'
                elif 'packing' in nombre_lower or 'lista-empaque' in nombre_lower:
                    tipo = 'packing_list'
                elif 'certificado' in nombre_lower or 'certificate' in nombre_lower or 'origen' in nombre_lower:
                    tipo = 'certificado_origen'
                
                print(f"   - Documento {idx+1}: {nombre} ({tipo})")
                
                # Guardar en BD
                nuevo_doc = Documento(
                    numero_despacho=numero_despacho,
                    tipo_documento=tipo,
                    nombre_archivo=nombre,
                    contenido_base64=documento_base64,
                    procesado=False
                )
                db.add(nuevo_doc)
                documentos_importados.append(tipo)
                
            except Exception as e:
                print(f"   ❌ Error procesando documento {idx}: {e}")
                continue
        
        # Actualizar despacho
        if documentos_importados:
            documentos_actuales = despacho.documentos_presentes or []
            documentos_actuales.extend(documentos_importados)
            despacho.documentos_presentes = list(set(documentos_actuales))
            db.commit()
        
        print(f"✅ Importados: {len(documentos_importados)} documentos")
        
        return {
            "message": "Documentos importados desde SGD",
            "documentos_importados": documentos_importados,
            "total": len(documentos_importados)
        }
        
    except requests.exceptions.HTTPError as e:
        if e.response.status_code == 404:
            return {
                "message": "Despacho no encontrado en SGD",
                "total": 0
            }
        elif e.response.status_code == 401:
            raise HTTPException(status_code=401, detail="No autorizado en SGD")
        else:
            raise HTTPException(
                status_code=e.response.status_code,
                detail=f"Error SGD: {e.response.text}"
            )
    except requests.exceptions.RequestException as e:
        print(f"❌ Error de conexión: {e}")
        raise HTTPException(status_code=500, detail=f"Error conectando con SGD: {str(e)}")
    except Exception as e:
        print(f"❌ Error general: {e}")
        raise HTTPException(status_code=500, detail=f"Error procesando respuesta: {str(e)}")

@app.post("/despachos/documento/subir")
async def subir_documento(
    documento: DocumentoUpload,
    db: Session = Depends(get_db)
):
    """Subir un documento a un despacho"""
    despacho = db.query(Despacho).filter(
        Despacho.numero_despacho == documento.numero_despacho
    ).first()
    
    if not despacho:
        raise HTTPException(status_code=404, detail="Despacho no encontrado")
    
    nuevo_doc = Documento(
        numero_despacho=documento.numero_despacho,
        tipo_documento=documento.tipo_documento,
        nombre_archivo=documento.nombre_archivo,
        contenido_base64=documento.contenido_base64,
        procesado=False
    )
    
    db.add(nuevo_doc)
    
    documentos_presentes = despacho.documentos_presentes or []
    if documento.tipo_documento not in documentos_presentes:
        documentos_presentes.append(documento.tipo_documento)
        despacho.documentos_presentes = documentos_presentes
    
    db.commit()
    db.refresh(nuevo_doc)
    
    return {
        "message": "Documento subido exitosamente",
        "documento_id": nuevo_doc.id,
        "tipo": nuevo_doc.tipo_documento
    }

@app.get("/despachos/{numero_despacho}/estado")
async def obtener_estado_despacho(
    numero_despacho: str,
    db: Session = Depends(get_db)
):
    """Obtener el estado completo de un despacho"""
    despacho = db.query(Despacho).filter(
        Despacho.numero_despacho == numero_despacho
    ).first()
    
    if not despacho:
        raise HTTPException(status_code=404, detail="Despacho no encontrado")
    
    documentos_requeridos = despacho.documentos_requeridos or DOCUMENTOS_REQUERIDOS_DEFAULT
    documentos_presentes = despacho.documentos_presentes or []
    documentos_faltantes = [doc for doc in documentos_requeridos if doc not in documentos_presentes]
    
    porcentaje_completitud = (len(documentos_presentes) / len(documentos_requeridos) * 100) if documentos_requeridos else 0
    
    puede_procesar = len(documentos_faltantes) == 0
    
    procedimientos = db.query(Procedimiento).filter(
        Procedimiento.numero_despacho == numero_despacho
    ).all()
    
    procedimientos_data = []
    for proc in procedimientos:
        procedimientos_data.append({
            "id": proc.id,
            "tipo": proc.tipo_procedimiento,
            "estado": proc.estado,
            "usuario_asignado": proc.usuario_asignado,
            "fecha_inicio": proc.fecha_inicio.isoformat() if proc.fecha_inicio else None,
            "fecha_fin": proc.fecha_fin.isoformat() if proc.fecha_fin else None
        })
    
    return DespachoStatus(
        numero_despacho=numero_despacho,
        estado=despacho.estado,
        documentos_requeridos=documentos_requeridos,
        documentos_presentes=documentos_presentes,
        documentos_faltantes=documentos_faltantes,
        porcentaje_completitud=porcentaje_completitud,
        puede_procesar=puede_procesar,
        procedimientos=procedimientos_data
    )

@app.get("/despachos/{numero_despacho}/documentos")
async def listar_documentos_despacho(
    numero_despacho: str,
    db: Session = Depends(get_db)
):
    """Listar todos los documentos de un despacho"""
    documentos = db.query(Documento).filter(
        Documento.numero_despacho == numero_despacho
    ).all()
    
    documentos_data = []
    for doc in documentos:
        documentos_data.append({
            "id": doc.id,
            "tipo_documento": doc.tipo_documento,
            "nombre_archivo": doc.nombre_archivo,
            "procesado": doc.procesado,
            "fecha_carga": doc.fecha_carga.isoformat(),
            "fecha_procesamiento": doc.fecha_procesamiento.isoformat() if doc.fecha_procesamiento else None,
            "tiene_contenido": bool(doc.contenido_base64)
        })
    
    return documentos_data

@app.get("/despachos/{numero_despacho}/documento/{documento_id}/pdf")
async def obtener_documento_pdf(
    numero_despacho: str,
    documento_id: int,
    db: Session = Depends(get_db)
):
    """Obtener un documento en formato PDF"""
    documento = db.query(Documento).filter(
        Documento.id == documento_id,
        Documento.numero_despacho == numero_despacho
    ).first()
    
    if not documento:
        raise HTTPException(status_code=404, detail="Documento no encontrado")
    
    if not documento.contenido_base64:
        raise HTTPException(status_code=404, detail="El documento no tiene contenido")
    
    try:
        pdf_content = base64.b64decode(documento.contenido_base64)
        
        from fastapi.responses import Response
        return Response(
            content=pdf_content,
            media_type="application/pdf",
            headers={
                "Content-Disposition": f"inline; filename={documento.nombre_archivo}"
            }
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error decodificando PDF: {str(e)}")

@app.post("/despachos/{numero_despacho}/procesar")
async def procesar_despacho(
    numero_despacho: str,
    forzar: bool = False,
    db: Session = Depends(get_db),
    authorization: str = Header(None)
):
    """Procesar todos los documentos de un despacho"""
    despacho = db.query(Despacho).filter(
        Despacho.numero_despacho == numero_despacho
    ).first()
    
    if not despacho:
        raise HTTPException(status_code=404, detail="Despacho no encontrado")
    
    estado = await obtener_estado_despacho(numero_despacho, db)
    
    if not estado.puede_procesar and not forzar:
        raise HTTPException(
            status_code=400,
            detail=f"El despacho no está completo. Faltan: {', '.join(estado.documentos_faltantes)}"
        )
    
    documentos = db.query(Documento).filter(
        Documento.numero_despacho == numero_despacho,
        Documento.procesado == False
    ).all()
    
    if not documentos and not forzar:
        return {"message": "No hay documentos para procesar"}
    
    if forzar:
        documentos = db.query(Documento).filter(
            Documento.numero_despacho == numero_despacho
        ).all()
    
    despacho.estado = "procesando"
    db.commit()
    
    resultados = []
    datos_totales = {}
    
    for doc in documentos:
        try:
            if doc.contenido_base64:
                pdf_bytes = base64.b64decode(doc.contenido_base64)
                
                endpoint = "invoice" if "factura" in doc.tipo_documento.lower() else "transport"
                
                from io import BytesIO
                files = {
                    'file': (doc.nombre_archivo, BytesIO(pdf_bytes), 'application/pdf')
                }
                
                headers = {}
                if authorization:
                    headers['Authorization'] = authorization
                
                response = requests.post(
                    f"http://api-docs:8002/process/{endpoint}",
                    files=files,
                    headers=headers
                )
                
                if response.status_code == 200:
                    result = response.json()
                    
                    doc.datos_extraidos = result.get('extracted_data', {})
                    doc.procesado = True
                    doc.fecha_procesamiento = datetime.now()
                    
                    datos_totales[doc.tipo_documento] = doc.datos_extraidos
                    
                    resultados.append({
                        "documento_id": doc.id,
                        "tipo": doc.tipo_documento,
                        "estado": "procesado"
                    })
                else:
                    resultados.append({
                        "documento_id": doc.id,
                        "tipo": doc.tipo_documento,
                        "estado": "error",
                        "error": response.text
                    })
                    
        except Exception as e:
            resultados.append({
                "documento_id": doc.id,
                "tipo": doc.tipo_documento,
                "estado": "error",
                "error": str(e)
            })
    
    despacho.datos_extraidos = datos_totales
    despacho.estado = "completo"
    despacho.fecha_actualizacion = datetime.now()
    
    db.commit()
    
    return {
        "message": "Procesamiento completado",
        "resultados": resultados,
        "total_procesados": len([r for r in resultados if r["estado"] == "procesado"]),
        "total_errores": len([r for r in resultados if r["estado"] == "error"])
    }

@app.get("/despachos/{numero_despacho}/datos")
async def obtener_datos_despacho(
    numero_despacho: str,
    db: Session = Depends(get_db)
):
    """Obtener datos estructurados extraídos del despacho"""
    despacho = db.query(Despacho).filter(
        Despacho.numero_despacho == numero_despacho
    ).first()
    
    if not despacho:
        raise HTTPException(status_code=404, detail="Despacho no encontrado")
    
    return {
        "numero_despacho": numero_despacho,
        "estado": despacho.estado,
        "fecha_actualizacion": despacho.fecha_actualizacion.isoformat(),
        "datos_extraidos": despacho.datos_extraidos or {}
    }

@app.post("/despachos/{numero_despacho}/procedimiento")
async def crear_procedimiento(
    numero_despacho: str,
    procedimiento_data: ProcedimientoCreate,
    db: Session = Depends(get_db)
):
    """Crear un nuevo procedimiento para un despacho"""
    despacho = db.query(Despacho).filter(
        Despacho.numero_despacho == numero_despacho
    ).first()
    
    if not despacho:
        raise HTTPException(status_code=404, detail="Despacho no encontrado")
    
    nuevo_proc = Procedimiento(
        numero_despacho=numero_despacho,
        tipo_procedimiento=procedimiento_data.tipo_procedimiento,
        usuario_asignado=procedimiento_data.usuario_asignado,
        estado="pendiente",
        datos={}
    )
    
    db.add(nuevo_proc)
    db.commit()
    db.refresh(nuevo_proc)
    
    return {
        "message": "Procedimiento creado",
        "procedimiento_id": nuevo_proc.id,
        "tipo": nuevo_proc.tipo_procedimiento
    }

@app.put("/procedimiento/{procedimiento_id}/asignar/{usuario}")
async def asignar_procedimiento(
    procedimiento_id: int,
    usuario: str,
    db: Session = Depends(get_db)
):
    """Asignar un procedimiento a un usuario"""
    proc = db.query(Procedimiento).filter(
        Procedimiento.id == procedimiento_id
    ).first()
    
    if not proc:
        raise HTTPException(status_code=404, detail="Procedimiento no encontrado")
    
    proc.usuario_asignado = usuario
    proc.estado = "en_progreso"
    proc.fecha_inicio = datetime.now()
    
    db.commit()
    
    return {"message": f"Procedimiento asignado a {usuario}"}

@app.put("/procedimiento/{procedimiento_id}/completar")
async def completar_procedimiento(
    procedimiento_id: int,
    datos: Optional[Dict[str, Any]] = None,
    db: Session = Depends(get_db)
):
    """Marcar un procedimiento como completado"""
    proc = db.query(Procedimiento).filter(
        Procedimiento.id == procedimiento_id
    ).first()
    
    if not proc:
        raise HTTPException(status_code=404, detail="Procedimiento no encontrado")
    
    proc.estado = "completado"
    proc.fecha_fin = datetime.now()
    if datos:
        proc.datos = datos
    
    db.commit()
    
    return {"message": "Procedimiento completado"}

@app.get("/despachos")
async def listar_despachos(
    limit: int = 25,  # Cambio: era 50, ahora 25 por página
    offset: int = 0,
    search: Optional[str] = None,  # NUEVO: búsqueda por número
    db: Session = Depends(get_db)
):
    """Listar despachos con paginación y búsqueda"""
    query = db.query(Despacho)
    
    # Filtro de búsqueda si se proporciona
    if search:
        query = query.filter(
            Despacho.numero_despacho.ilike(f"%{search}%")
        )
    
    # Ordenar por fecha de actualización descendente (más recientes primero)
    query = query.order_by(Despacho.fecha_actualizacion.desc())
    
    # Obtener total para paginación
    total = query.count()
    
    # Aplicar paginación
    despachos = query.offset(offset).limit(limit).all()
    
    despachos_data = []
    for desp in despachos:
        documentos_requeridos = desp.documentos_requeridos or DOCUMENTOS_REQUERIDOS_DEFAULT
        documentos_presentes = desp.documentos_presentes or []
        porcentaje = (len(documentos_presentes) / len(documentos_requeridos) * 100) if documentos_requeridos else 0
        
        despachos_data.append({
            "numero_despacho": desp.numero_despacho,
            "estado": desp.estado,
            "fecha_creacion": desp.fecha_creacion.isoformat(),
            "fecha_actualizacion": desp.fecha_actualizacion.isoformat(),
            "porcentaje_completitud": round(porcentaje, 1),  # Redondear a 1 decimal
            "documentos_presentes": len(documentos_presentes),
            "documentos_requeridos": len(documentos_requeridos),
            "puede_procesar": len(documentos_presentes) == len(documentos_requeridos)
        })
    
    return {
        "despachos": despachos_data,
        "total": total,
        "limit": limit,
        "offset": offset,
        "total_pages": (total + limit - 1) // limit,  # Calcular páginas totales
        "current_page": (offset // limit) + 1,
        "has_next": offset + limit < total,
        "has_prev": offset > 0
    }

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8003)