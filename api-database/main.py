from fastapi import FastAPI, HTTPException, Depends
from pydantic import BaseModel
from sqlalchemy import create_engine, text, inspect, MetaData, Table
from sqlalchemy.orm import sessionmaker, Session
import os
import json
from datetime import datetime
from typing import List, Dict, Any, Optional
import psycopg2
from psycopg2.extras import RealDictCursor

app = FastAPI()

# ConfiguraciÃ³n de base de datos
DATABASE_URL = f"postgresql://postgres:postgres@postgres/postgres"

# SQLAlchemy
engine = create_engine(DATABASE_URL)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

# Modelos Pydantic para respuestas
class DatabaseSchema(BaseModel):
    name: str
    tables: List[str]
    total_tables: int

class TableInfo(BaseModel):
    name: str
    schema: str
    row_count: int
    columns: List[Dict[str, Any]]
    indexes: List[str]
    constraints: List[str]

class TableData(BaseModel):
    table_name: str
    columns: List[str]
    rows: List[List[Any]]
    total_rows: int
    page: int
    page_size: int
    total_pages: int

class QueryResult(BaseModel):
    columns: List[str]
    rows: List[List[Any]]
    affected_rows: int
    execution_time: float
    query: str

# Endpoints bÃ¡sicos
@app.get("/")
async def root():
    return {"service": "Database Explorer API", "status": "running"}

@app.get("/health")
async def health():
    """Health check endpoint"""
    try:
        # Test database connection
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        
        return {
            "status": "healthy",
            "service": "api-database",
            "database": "connected",
            "timestamp": datetime.now().isoformat()
        }
    except Exception as e:
        return {
            "status": "unhealthy",
            "service": "api-database", 
            "database": "disconnected",
            "error": str(e),
            "timestamp": datetime.now().isoformat()
        }

# Endpoints del explorador de base de datos

@app.get("/db/schemas", response_model=List[DatabaseSchema])
async def get_database_schemas():
    """Obtener esquemas y tablas de la base de datos"""
    try:
        inspector = inspect(engine)
        schemas_info = []
        
        # Obtener esquemas
        schemas = inspector.get_schema_names()
        
        for schema in schemas:
            if schema not in ['information_schema', 'pg_catalog', 'pg_toast']:
                tables = inspector.get_table_names(schema=schema)
                
                schemas_info.append(DatabaseSchema(
                    name=schema,
                    tables=tables,
                    total_tables=len(tables)
                ))
        
        # Si no hay esquemas custom, usar el pÃºblico
        if not schemas_info:
            tables = inspector.get_table_names()
            schemas_info.append(DatabaseSchema(
                name="public",
                tables=tables,
                total_tables=len(tables)
            ))
        
        return schemas_info
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error obteniendo esquemas: {str(e)}")

@app.get("/db/table/{schema}/{table_name}", response_model=TableInfo)
async def get_table_info(schema: str, table_name: str):
    """Obtener informaciÃ³n detallada de una tabla"""
    try:
        inspector = inspect(engine)
        
        # InformaciÃ³n de columnas
        columns_raw = inspector.get_columns(table_name, schema=schema)
        
        # Convertir informaciÃ³n de columnas a formato serializable
        columns_info = []
        for col in columns_raw:
            column_dict = {
                'name': col['name'],
                'type': str(col['type']),
                'nullable': col['nullable'],
                'default': str(col['default']) if col['default'] is not None else None,
                'autoincrement': col.get('autoincrement', False),
                'primary_key': col.get('primary_key', False)
            }
            columns_info.append(column_dict)
        
        # Contar filas
        with engine.connect() as conn:
            if schema == "public":
                count_query = f"SELECT COUNT(*) FROM {table_name}"
            else:
                count_query = f"SELECT COUNT(*) FROM {schema}.{table_name}"
            
            result = conn.execute(text(count_query))
            row_count = result.scalar()
        
        # Ãndices
        indexes = inspector.get_indexes(table_name, schema=schema)
        index_names = [idx['name'] for idx in indexes]
        
        # Constraints
        pk_constraint = inspector.get_pk_constraint(table_name, schema=schema)
        fk_constraints = inspector.get_foreign_keys(table_name, schema=schema)
        check_constraints = inspector.get_check_constraints(table_name, schema=schema)
        
        constraints = []
        if pk_constraint and pk_constraint.get('constrained_columns'):
            constraints.append(f"PRIMARY KEY ({', '.join(pk_constraint['constrained_columns'])})")
        
        for fk in fk_constraints:
            constraints.append(f"FOREIGN KEY ({', '.join(fk['constrained_columns'])}) REFERENCES {fk['referred_table']}")
        
        for check in check_constraints:
            constraints.append(f"CHECK {check.get('name', 'unnamed')}")
        
        return TableInfo(
            name=table_name,
            schema=schema,
            row_count=row_count,
            columns=columns_info,
            indexes=index_names,
            constraints=constraints
        )
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error obteniendo informaciÃ³n de tabla: {str(e)}")

@app.get("/db/table/{schema}/{table_name}/data", response_model=TableData)
async def get_table_data(
    schema: str, 
    table_name: str, 
    page: int = 1, 
    page_size: int = 50,
    order_by: Optional[str] = None,
    order_direction: str = "ASC"
):
    """Obtener datos de una tabla con paginaciÃ³n"""
    try:
        # Validar parÃ¡metros
        if page < 1:
            page = 1
        if page_size < 1 or page_size > 1000:
            page_size = 50
        
        offset = (page - 1) * page_size
        
        with engine.connect() as conn:
            # Obtener columnas
            inspector = inspect(engine)
            columns_info = inspector.get_columns(table_name, schema=schema)
            column_names = [col['name'] for col in columns_info]
            
            # Construir consulta base
            table_ref = f"{schema}.{table_name}" if schema != "public" else table_name
            
            # Query para contar total de filas
            count_query = f"SELECT COUNT(*) FROM {table_ref}"
            total_result = conn.execute(text(count_query))
            total_rows = total_result.scalar()
            
            # Query para obtener datos
            base_query = f"SELECT * FROM {table_ref}"
            
            # Agregar ordenamiento si se especifica
            if order_by and order_by in column_names:
                direction = "DESC" if order_direction.upper() == "DESC" else "ASC"
                base_query += f" ORDER BY {order_by} {direction}"
            
            # Agregar paginaciÃ³n
            data_query = f"{base_query} LIMIT {page_size} OFFSET {offset}"
            
            # Ejecutar consulta
            result = conn.execute(text(data_query))
            rows = result.fetchall()
            
            # Convertir filas a lista de listas
            rows_data = []
            for row in rows:
                row_list = []
                for value in row:
                    if isinstance(value, datetime):
                        row_list.append(value.isoformat())
                    elif isinstance(value, dict):
                        row_list.append(json.dumps(value, ensure_ascii=False))
                    elif value is None:
                        row_list.append(None)
                    else:
                        row_list.append(str(value))
                rows_data.append(row_list)
            
            # Calcular pÃ¡ginas
            total_pages = (total_rows + page_size - 1) // page_size
            
            return TableData(
                table_name=table_name,
                columns=column_names,
                rows=rows_data,
                total_rows=total_rows,
                page=page,
                page_size=page_size,
                total_pages=total_pages
            )
            
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error obteniendo datos de tabla: {str(e)}")

@app.post("/db/query", response_model=QueryResult)
async def execute_query(query_data: dict):
    """Ejecutar consulta SQL personalizada (solo SELECT para seguridad)"""
    try:
        query = query_data.get('query', '').strip()
        
        if not query:
            raise HTTPException(status_code=400, detail="Query vacÃ­o")
        
        # ValidaciÃ³n bÃ¡sica de seguridad - solo permitir SELECT
        query_upper = query.upper()
        if not query_upper.startswith('SELECT'):
            raise HTTPException(status_code=400, detail="Solo se permiten consultas SELECT")
        
        # Palabras prohibidas para mayor seguridad
        prohibited_words = ['DROP', 'DELETE', 'UPDATE', 'INSERT', 'ALTER', 'CREATE', 'TRUNCATE', 'EXEC']
        for word in prohibited_words:
            if word in query_upper:
                raise HTTPException(status_code=400, detail=f"OperaciÃ³n '{word}' no permitida")
        
        start_time = datetime.now()
        
        with engine.connect() as conn:
            result = conn.execute(text(query))
            rows = result.fetchall()
            
            # Obtener nombres de columnas
            column_names = list(result.keys()) if result.keys() else []
            
            # Convertir filas
            rows_data = []
            for row in rows:
                row_list = []
                for value in row:
                    if isinstance(value, datetime):
                        row_list.append(value.isoformat())
                    elif isinstance(value, dict):
                        row_list.append(json.dumps(value, ensure_ascii=False))
                    elif value is None:
                        row_list.append(None)
                    else:
                        row_list.append(str(value))
                rows_data.append(row_list)
        
        end_time = datetime.now()
        execution_time = (end_time - start_time).total_seconds()
        
        return QueryResult(
            columns=column_names,
            rows=rows_data,
            affected_rows=len(rows_data),
            execution_time=execution_time,
            query=query
        )
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error ejecutando consulta: {str(e)}")

@app.get("/db/stats")
async def get_database_stats():
    """Obtener estadÃ­sticas generales de la base de datos"""
    try:
        with engine.connect() as conn:
            # InformaciÃ³n general de la base de datos
            db_size_query = """
                SELECT pg_size_pretty(pg_database_size(current_database())) as database_size
            """
            db_size_result = conn.execute(text(db_size_query))
            database_size = db_size_result.scalar()
            
            # NÃºmero total de tablas
            tables_query = """
                SELECT COUNT(*) as table_count
                FROM information_schema.tables 
                WHERE table_schema = 'public'
            """
            tables_result = conn.execute(text(tables_query))
            table_count = tables_result.scalar()
            
            # Actividad de conexiones
            connections_query = """
                SELECT count(*) as active_connections
                FROM pg_stat_activity 
                WHERE state = 'active'
            """
            connections_result = conn.execute(text(connections_query))
            active_connections = connections_result.scalar()
            
            # InformaciÃ³n de versiÃ³n
            version_query = "SELECT version()"
            version_result = conn.execute(text(version_query))
            pg_version = version_result.scalar()
            
            return {
                "database_size": database_size,
                "table_count": table_count,
                "active_connections": active_connections,
                "postgresql_version": pg_version.split(',')[0] if pg_version else "Desconocida",
                "current_database": os.getenv('DESPACHOS_DB_NAME', 'despachos'),
                "timestamp": datetime.now().isoformat()
            }
            
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error obteniendo estadÃ­sticas: {str(e)}")

@app.get("/db/table/{schema}/{table_name}/schema")
async def get_table_schema(schema: str, table_name: str):
    """Obtener el esquema SQL de una tabla"""
    try:
        with engine.connect() as conn:
            # Query para obtener la definiciÃ³n de la tabla
            schema_query = """
                SELECT column_name, data_type, is_nullable, column_default, character_maximum_length
                FROM information_schema.columns 
                WHERE table_schema = :schema AND table_name = :table_name
                ORDER BY ordinal_position
            """
            
            result = conn.execute(text(schema_query), {"schema": schema, "table_name": table_name})
            columns = result.fetchall()
            
            # Construir definiciÃ³n SQL
            sql_definition = f"CREATE TABLE {schema}.{table_name} (\n"
            column_definitions = []
            
            for col in columns:
                col_def = f"    {col.column_name} {col.data_type}"
                
                if col.character_maximum_length:
                    col_def += f"({col.character_maximum_length})"
                
                if col.is_nullable == 'NO':
                    col_def += " NOT NULL"
                
                if col.column_default:
                    col_def += f" DEFAULT {col.column_default}"
                
                column_definitions.append(col_def)
            
            sql_definition += ",\n".join(column_definitions)
            sql_definition += "\n);"
            
            return {
                "table_name": table_name,
                "schema": schema,
                "sql_definition": sql_definition,
                "columns": [dict(col._mapping) for col in columns]
            }
            
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error obteniendo esquema: {str(e)}")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8004)