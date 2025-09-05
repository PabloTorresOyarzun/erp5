# Actualizar el modelo Documento en api-despachos/database.py

from sqlalchemy import Column, Integer, String, Boolean, DateTime, Text, JSON
from sqlalchemy.ext.declarative import declarative_base
from datetime import datetime

Base = declarative_base()

class Documento(Base):
    __tablename__ = "documentos"
    
    id = Column(Integer, primary_key=True, index=True)
    numero_despacho = Column(String, index=True)
    tipo_documento = Column(String)
    nombre_archivo = Column(String)
    contenido_base64 = Column(Text)
    procesado = Column(Boolean, default=False)
    fecha_subida = Column(DateTime, default=datetime.now)
    # Nuevo campo para almacenar datos extraídos
    datos_extraidos = Column(JSON, nullable=True)
    
class Despacho(Base):
    __tablename__ = "despachos"
    
    id = Column(Integer, primary_key=True, index=True)
    numero_despacho = Column(String, unique=True, index=True)
    estado = Column(String, default="nuevo")
    fecha_creacion = Column(DateTime, default=datetime.now)
    documentos_presentes = Column(JSON, default=list)
    extra_metadata = Column(JSON, default=dict)