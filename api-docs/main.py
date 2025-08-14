from fastapi import FastAPI, UploadFile, File, HTTPException, Depends, Header
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from azure.ai.formrecognizer import DocumentAnalysisClient
from azure.core.credentials import AzureKeyCredential
import os
import json
import io
import openpyxl
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
from datetime import datetime
from typing import Optional, Dict, List, Any
import uuid
import asyncio
import re
import psycopg2
from psycopg2.extras import Json
import base64

app = FastAPI()

# Configuración Azure
ENDPOINT = os.getenv('AZURE_FORM_RECOGNIZER_ENDPOINT', '')
API_KEY = os.getenv('AZURE_FORM_RECOGNIZER_KEY', '')
INVOICE_MODEL_ID = os.getenv('INVOICE_MODEL_ID', 'prebuilt-invoice')
TRANSPORT_MODEL_ID = os.getenv('TRANSPORT_MODEL_ID', 'prebuilt-document')

# Cliente Azure Document Intelligence
document_analysis_client = None
if ENDPOINT and API_KEY:
    document_analysis_client = DocumentAnalysisClient(
        endpoint=ENDPOINT,
        credential=AzureKeyCredential(API_KEY)
    )

# Base de datos en memoria para el historial (en producción usar una DB real)
processing_history = {}

# Conexión a base de datos
def get_db_connection():
    return psycopg2.connect(
        host=os.getenv('DESPACHOS_DB_HOST', 'postgres-despachos'),
        database=os.getenv('DESPACHOS_DB_NAME', 'despachos'),
        user=os.getenv('DESPACHOS_DB_USER', 'despachos'),
        password=os.getenv('DESPACHOS_DB_PASSWORD', 'despachos123')
    )

def save_to_despacho_db(numero_despacho: str, tipo_documento: str, datos_extraidos: dict):
    """Guardar datos extraídos en la base de datos del despacho"""
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        
        # Actualizar documento como procesado
        cur.execute("""
            UPDATE documentos 
            SET procesado = true, 
                datos_extraidos = %s,
                fecha_procesamiento = NOW()
            WHERE numero_despacho = %s AND tipo_documento = %s
        """, (Json(datos_extraidos), numero_despacho, tipo_documento))
        
        # Actualizar datos del despacho
        cur.execute("""
            UPDATE despachos 
            SET datos_extraidos = 
                COALESCE(datos_extraidos, '{}'::jsonb) || %s::jsonb,
                fecha_actualizacion = NOW()
            WHERE numero_despacho = %s
        """, (Json({tipo_documento: datos_extraidos}), numero_despacho))
        
        conn.commit()
        cur.close()
        conn.close()
        return True
    except Exception as e:
        print(f"Error guardando en BD: {e}")
        return False

# Modelos Pydantic
class ProcessingResult(BaseModel):
    id: str
    username: str
    filename: str
    document_type: str
    status: str
    processed_at: datetime
    extracted_data: Optional[Dict[str, Any]] = None
    excel_url: Optional[str] = None
    json_url: Optional[str] = None
    error_message: Optional[str] = None

class ProcessingHistory(BaseModel):
    results: List[ProcessingResult]
    total: int

# Funciones auxiliares
def get_username_from_header(authorization: str = Header(None)) -> str:
    """Extraer username del header de autorización"""
    if not authorization:
        return "anonymous"
    
    try:
        # Si es un token Bearer
        if authorization.startswith("Bearer "):
            token = authorization.replace("Bearer ", "")
            
            # Decodificar JWT (sin verificar firma por ahora)
            import base64
            parts = token.split('.')
            if len(parts) >= 2:
                payload = parts[1]
                # Agregar padding si es necesario
                payload += '=' * (4 - len(payload) % 4)
                decoded = base64.urlsafe_b64decode(payload)
                token_data = json.loads(decoded)
                
                # Buscar username en diferentes campos posibles
                username = token_data.get('preferred_username') or \
                          token_data.get('username') or \
                          token_data.get('sub') or \
                          "user"
                
                return username
    except Exception as e:
        pass
    
    return "anonymous"

def extract_invoice_data(result):
    """Extraer datos estructurados de una factura"""
    invoice_data = {
        "metadata": {
            "pages": len(result.pages) if hasattr(result, 'pages') else 0,
            "model_id": result.model_id if hasattr(result, 'model_id') else 'unknown',
            "processed_at": datetime.now().isoformat()
        },
        "vendor_information": {},
        "customer_information": {},
        "invoice_details": {},
        "line_items": [],
        "totals": {},
        "all_fields": {}  # Para debug - guardar todos los campos encontrados
    }
    
    # Intentar múltiples formas de acceder a los datos
    fields = {}
    
    # Opción 1: Modelo prebuilt-invoice
    if hasattr(result, 'documents') and result.documents:
        doc = result.documents[0]
        
        if hasattr(doc, 'fields'):
            fields = doc.fields
            
            # Guardar todos los campos para debug
            for field_name, field_value in fields.items():
                if hasattr(field_value, 'value') and field_value.value is not None:
                    invoice_data["all_fields"][field_name] = str(field_value.value)
    
    # Opción 2: Si es un modelo custom, los campos pueden estar directamente en result
    elif hasattr(result, 'fields'):
        fields = result.fields
    
    # Opción 3: Buscar en key_value_pairs
    elif hasattr(result, 'key_value_pairs'):
        for kv_pair in result.key_value_pairs:
            if kv_pair.key and kv_pair.value:
                key = kv_pair.key.content
                value = kv_pair.value.content
                invoice_data["all_fields"][key] = value
                
                # Intentar clasificar por palabras clave
                key_lower = key.lower()
                if any(term in key_lower for term in ['vendor', 'seller', 'proveedor', 'emisor']):
                    if 'name' in key_lower or 'nombre' in key_lower:
                        invoice_data["vendor_information"]["name"] = value
                    elif 'address' in key_lower or 'direccion' in key_lower:
                        invoice_data["vendor_information"]["address"] = value
                    elif 'tax' in key_lower or 'rut' in key_lower or 'nit' in key_lower:
                        invoice_data["vendor_information"]["tax_id"] = value
                elif any(term in key_lower for term in ['customer', 'client', 'buyer', 'comprador']):
                    if 'name' in key_lower or 'nombre' in key_lower:
                        invoice_data["customer_information"]["name"] = value
                    elif 'address' in key_lower or 'direccion' in key_lower:
                        invoice_data["customer_information"]["address"] = value
                elif any(term in key_lower for term in ['invoice', 'factura', 'number', 'numero', 'folio']):
                    invoice_data["invoice_details"]["invoice_number"] = value
                elif any(term in key_lower for term in ['date', 'fecha']) and 'due' not in key_lower:
                    invoice_data["invoice_details"]["date"] = value
                elif any(term in key_lower for term in ['total', 'amount', 'monto']):
                    invoice_data["totals"]["total"] = value
    
    # Procesar campos si se encontraron
    if fields:
        # Mapeo de campos comunes (prebuilt-invoice y variaciones)
        field_mappings = {
            # Vendedor
            'VendorName': ('vendor_information', 'name'),
            'RemitToName': ('vendor_information', 'name'),
            'VendorAddress': ('vendor_information', 'address'),
            'RemitToAddress': ('vendor_information', 'address'),
            'VendorTaxId': ('vendor_information', 'tax_id'),
            'VendorAddressRecipient': ('vendor_information', 'recipient'),
            
            # Cliente
            'CustomerName': ('customer_information', 'name'),
            'BillToName': ('customer_information', 'name'),
            'ShipToName': ('customer_information', 'ship_to_name'),
            'CustomerAddress': ('customer_information', 'address'),
            'BillToAddress': ('customer_information', 'address'),
            'CustomerTaxId': ('customer_information', 'tax_id'),
            'CustomerId': ('customer_information', 'id'),
            
            # Detalles de factura
            'InvoiceId': ('invoice_details', 'invoice_number'),
            'InvoiceDate': ('invoice_details', 'date'),
            'DueDate': ('invoice_details', 'due_date'),
            'PurchaseOrderNumber': ('invoice_details', 'purchase_order'),
            'PaymentTerm': ('invoice_details', 'payment_term'),
            
            # Totales
            'SubTotal': ('totals', 'subtotal'),
            'TotalTax': ('totals', 'tax'),
            'InvoiceTotal': ('totals', 'total'),
            'AmountDue': ('totals', 'amount_due'),
            'PreviousUnpaidBalance': ('totals', 'previous_balance')
        }
        
        # Procesar campos mapeados
        for field_name, (section, key) in field_mappings.items():
            if field_name in fields:
                field_value = fields[field_name]
                if hasattr(field_value, 'value') and field_value.value is not None:
                    value = field_value.value
                    # Convertir fechas a string
                    if hasattr(value, 'isoformat'):
                        value = value.isoformat()
                    invoice_data[section][key] = str(value)
        
        # Procesar items/líneas
        if "Items" in fields:
            items_field = fields["Items"]
            if hasattr(items_field, 'value') and items_field.value:
                for idx, item in enumerate(items_field.value):
                    line_item = {"line_number": idx + 1}
                    
                    # El item puede ser un objeto con campos
                    if hasattr(item, 'value') and hasattr(item.value, 'fields'):
                        item_fields = item.value.fields
                        
                        item_field_mappings = {
                            'Description': 'description',
                            'ProductCode': 'product_code',
                            'Quantity': 'quantity',
                            'Unit': 'unit',
                            'UnitPrice': 'unit_price',
                            'Tax': 'tax',
                            'Amount': 'amount',
                            'Date': 'date'
                        }
                        
                        for field_name, key in item_field_mappings.items():
                            if field_name in item_fields:
                                field_value = item_fields[field_name]
                                if hasattr(field_value, 'value') and field_value.value is not None:
                                    line_item[key] = str(field_value.value)
                    
                    # Solo agregar si tiene al menos descripción o monto
                    if line_item.get('description') or line_item.get('amount'):
                        invoice_data["line_items"].append(line_item)
    
    # Si no se encontraron datos estructurados, extraer texto de las páginas
    if not any([invoice_data["vendor_information"], invoice_data["customer_information"], 
                invoice_data["invoice_details"], invoice_data["totals"]]):
        
        if hasattr(result, 'pages'):
            all_text = []
            for page in result.pages:
                if hasattr(page, 'lines'):
                    for line in page.lines:
                        if hasattr(line, 'content'):
                            all_text.append(line.content)
            
            invoice_data["extracted_text"] = "\n".join(all_text)
            
            # Intentar extraer datos básicos del texto
            text_content = " ".join(all_text).lower()
            
            # Buscar patrones comunes
            import re
            
            # Buscar números de factura
            invoice_patterns = [
                r'factura\s*[:№#]?\s*(\S+)',
                r'invoice\s*[:№#]?\s*(\S+)',
                r'folio\s*[:№#]?\s*(\S+)',
                r'n[úu]mero\s*[:№#]?\s*(\S+)'
            ]
            
            for pattern in invoice_patterns:
                match = re.search(pattern, text_content, re.IGNORECASE)
                if match:
                    invoice_data["invoice_details"]["invoice_number"] = match.group(1)
                    break
            
            # Buscar totales
            total_patterns = [
                r'total\s*[:$]?\s*([\d,.\s]+)',
                r'monto\s*total\s*[:$]?\s*([\d,.\s]+)',
                r'importe\s*total\s*[:$]?\s*([\d,.\s]+)'
            ]
            
            for pattern in total_patterns:
                match = re.search(pattern, text_content, re.IGNORECASE)
                if match:
                    invoice_data["totals"]["total"] = match.group(1).strip()
                    break
    
    return invoice_data

def extract_transport_data(result):
    """Extraer datos estructurados de un documento de transporte"""
    transport_data = {
        "metadata": {
            "pages": len(result.pages) if hasattr(result, 'pages') else 0,
            "model_id": result.model_id if hasattr(result, 'model_id') else 'unknown',
            "processed_at": datetime.now().isoformat()
        },
        "document_info": {},
        "shipper": {},
        "consignee": {},
        "transport_details": {},
        "goods": [],
        "extracted_text": {},
        "all_fields": {}  # Para debug
    }
    
    # Extraer pares clave-valor
    if hasattr(result, 'key_value_pairs') and result.key_value_pairs:
        
        for kv_pair in result.key_value_pairs:
            if kv_pair.key and kv_pair.value:
                key = kv_pair.key.content if hasattr(kv_pair.key, 'content') else str(kv_pair.key)
                value = kv_pair.value.content if hasattr(kv_pair.value, 'content') else str(kv_pair.value)
                
                # Guardar todos los campos
                transport_data["all_fields"][key] = value
                
                # Clasificar información según el tipo de campo
                key_lower = key.lower()
                
                # Patrones para clasificar campos
                if any(term in key_lower for term in ['shipper', 'sender', 'remitente', 'exportador', 'consignor']):
                    transport_data["shipper"][key] = value
                elif any(term in key_lower for term in ['consignee', 'receiver', 'destinatario', 'importador', 'recipient']):
                    transport_data["consignee"][key] = value
                elif any(term in key_lower for term in ['transport', 'carrier', 'vessel', 'flight', 'truck', 'container', 'bl', 'awb', 'booking']):
                    transport_data["transport_details"][key] = value
                elif any(term in key_lower for term in ['date', 'fecha']):
                    transport_data["document_info"][key] = value
                elif any(term in key_lower for term in ['number', 'numero', 'no.', 'ref', 'reference']):
                    transport_data["document_info"][key] = value
                else:
                    # Clasificación adicional por contenido
                    if '@' in value or any(term in value.lower() for term in ['street', 'avenue', 'city', 'country']):
                        # Probablemente es información de contacto/dirección
                        if not transport_data["shipper"] and not transport_data["consignee"]:
                            transport_data["document_info"][key] = value
                    else:
                        transport_data["document_info"][key] = value
    
    # Si el modelo devuelve documentos estructurados (modelos custom)
    if hasattr(result, 'documents') and result.documents:
        
        for doc_idx, doc in enumerate(result.documents):
            if hasattr(doc, 'fields'):
                fields = doc.fields
                
                # Procesar cada campo
                for field_name, field_value in fields.items():
                    if hasattr(field_value, 'value') and field_value.value is not None:
                        value = str(field_value.value)
                        transport_data["all_fields"][field_name] = value
                        
                        # Clasificar por nombre de campo
                        field_lower = field_name.lower()
                        if 'shipper' in field_lower or 'sender' in field_lower:
                            transport_data["shipper"][field_name] = value
                        elif 'consignee' in field_lower or 'receiver' in field_lower:
                            transport_data["consignee"][field_name] = value
                        elif any(term in field_lower for term in ['transport', 'vessel', 'container']):
                            transport_data["transport_details"][field_name] = value
                        else:
                            transport_data["document_info"][field_name] = value
    
    # Extraer tablas
    if hasattr(result, 'tables') and result.tables:
        
        for table_idx, table in enumerate(result.tables):
            if table.row_count > 0:
                
                # Obtener encabezados
                headers = []
                header_cells = []
                
                # Recopilar todas las celdas primero
                all_cells = []
                if hasattr(table, 'cells'):
                    for cell in table.cells:
                        all_cells.append({
                            'row': cell.row_index,
                            'col': cell.column_index,
                            'content': cell.content if hasattr(cell, 'content') else ''
                        })
                
                # Ordenar celdas por fila y columna
                all_cells.sort(key=lambda x: (x['row'], x['col']))
                
                # Extraer encabezados (primera fila)
                for cell in all_cells:
                    if cell['row'] == 0:
                        headers.append(cell['content'])
                
                # Procesar filas de datos
                current_row = -1
                current_item = {}
                
                for cell in all_cells:
                    if cell['row'] > 0:  # Saltar encabezados
                        if cell['row'] != current_row:
                            # Nueva fila
                            if current_item and any(current_item.values()):
                                transport_data["goods"].append(current_item)
                            current_item = {}
                            current_row = cell['row']
                        
                        # Asignar valor a la columna correspondiente
                        if cell['col'] < len(headers):
                            header = headers[cell['col']]
                            current_item[header] = cell['content']
                        else:
                            current_item[f"column_{cell['col']}"] = cell['content']
                
                # Agregar el último item
                if current_item and any(current_item.values()):
                    transport_data["goods"].append(current_item)
    
    # Extraer texto completo por página
    if hasattr(result, 'pages'):
        
        all_text_lines = []
        for page_idx, page in enumerate(result.pages):
            page_text = []
            
            if hasattr(page, 'lines'):
                for line in page.lines:
                    if hasattr(line, 'content'):
                        page_text.append(line.content)
                        all_text_lines.append(line.content)
            
            transport_data["extracted_text"][f"page_{page_idx + 1}"] = "\n".join(page_text)
        
        # Si no se encontraron datos estructurados, intentar extraer del texto
        if not any([transport_data["shipper"], transport_data["consignee"], transport_data["transport_details"]]):
            
            full_text = " ".join(all_text_lines)
            
            # Buscar patrones comunes en documentos de transporte
            import re
            
            # Patrones para BL/AWB numbers
            transport_patterns = [
                (r'B/?L\s*[:№#]?\s*(\S+)', 'bl_number'),
                (r'AWB\s*[:№#]?\s*(\S+)', 'awb_number'),
                (r'Booking\s*[:№#]?\s*(\S+)', 'booking_number'),
                (r'Container\s*[:№#]?\s*(\S+)', 'container_number'),
                (r'Vessel\s*[:№#]?\s*([^\n]+)', 'vessel_name'),
                (r'Flight\s*[:№#]?\s*(\S+)', 'flight_number')
            ]
            
            for pattern, field_name in transport_patterns:
                match = re.search(pattern, full_text, re.IGNORECASE)
                if match:
                    transport_data["transport_details"][field_name] = match.group(1).strip()
            
            # Buscar fechas
            date_patterns = [
                r'\b(\d{1,2}[-/]\d{1,2}[-/]\d{2,4})\b',
                r'\b(\d{4}[-/]\d{1,2}[-/]\d{1,2})\b'
            ]
            
            for pattern in date_patterns:
                matches = re.findall(pattern, full_text)
                if matches:
                    transport_data["document_info"]["dates_found"] = matches[:3]  # Primeras 3 fechas
                    break
    
    return transport_data

def create_invoice_excel(invoice_data: dict) -> io.BytesIO:
    """Crear un archivo Excel con formato corporativo para facturas"""
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Factura"
    
    # Estilos
    header_font = Font(name='Arial', size=16, bold=True, color="FFFFFF")
    section_font = Font(name='Arial', size=12, bold=True, color="FFFFFF")
    subsection_font = Font(name='Arial', size=11, bold=True)
    normal_font = Font(name='Arial', size=10)
    
    header_fill = PatternFill(start_color="2C3E50", end_color="2C3E50", fill_type="solid")
    section_fill = PatternFill(start_color="3498DB", end_color="3498DB", fill_type="solid")
    alt_row_fill = PatternFill(start_color="F8F9FA", end_color="F8F9FA", fill_type="solid")
    
    thin_border = Border(
        left=Side(style='thin'),
        right=Side(style='thin'),
        top=Side(style='thin'),
        bottom=Side(style='thin')
    )
    
    # Encabezado principal
    ws.merge_cells('A1:F1')
    ws['A1'] = 'FACTURA - DATOS EXTRAÍDOS'
    ws['A1'].font = header_font
    ws['A1'].fill = header_fill
    ws['A1'].alignment = Alignment(horizontal='center', vertical='center')
    ws.row_dimensions[1].height = 30
    
    current_row = 3
    
    # Extraer datos principales de all_fields
    all_fields = invoice_data.get('all_fields', {})
    
    # INFORMACIÓN BÁSICA DE LA FACTURA
    ws[f'A{current_row}'] = 'INFORMACIÓN DE LA FACTURA'
    ws[f'A{current_row}'].font = section_font
    ws[f'A{current_row}'].fill = section_fill
    ws.merge_cells(f'A{current_row}:F{current_row}')
    current_row += 1
    
    # Campos básicos
    basic_fields = {
        'Tipo': all_fields.get('Tipo', ''),
        'Número de Factura': all_fields.get('NumeroFactura', invoice_data.get('invoice_details', {}).get('invoice_number', '')),
        'Fecha': all_fields.get('Fecha', ''),
        'Fecha Vencimiento': all_fields.get('FechaVencimiento', ''),
        'Referencia': all_fields.get('Referencia', ''),
        'Orden': all_fields.get('Orden', '')
    }
    
    for label, value in basic_fields.items():
        if value:
            ws[f'A{current_row}'] = label
            ws[f'B{current_row}'] = str(value)
            ws[f'A{current_row}'].font = normal_font
            ws[f'B{current_row}'].font = normal_font
            ws.merge_cells(f'B{current_row}:F{current_row}')
            current_row += 1
    current_row += 1
    
    # INFORMACIÓN DEL EMISOR
    ws[f'A{current_row}'] = 'INFORMACIÓN DEL EMISOR'
    ws[f'A{current_row}'].font = section_font
    ws[f'A{current_row}'].fill = section_fill
    ws.merge_cells(f'A{current_row}:F{current_row}')
    current_row += 1
    
    emisor_fields = {
        'Nombre': all_fields.get('EmisorNombre', ''),
        'RUT/Tax ID': all_fields.get('EmisorRUT', ''),
        'Giro': all_fields.get('EmisorGiro', ''),
        'Dirección': all_fields.get('EmisorDireccion', ''),
        'Teléfono': all_fields.get('EmisorFono', ''),
        'Email': all_fields.get('EmisorEmail', '')
    }
    
    for label, value in emisor_fields.items():
        if value:
            ws[f'A{current_row}'] = label
            ws[f'B{current_row}'] = str(value)
            ws[f'A{current_row}'].font = normal_font
            ws[f'B{current_row}'].font = normal_font
            ws.merge_cells(f'B{current_row}:F{current_row}')
            current_row += 1
    current_row += 1
    
    # INFORMACIÓN DEL CLIENTE
    ws[f'A{current_row}'] = 'INFORMACIÓN DEL CLIENTE'
    ws[f'A{current_row}'].font = section_font
    ws[f'A{current_row}'].fill = section_fill
    ws.merge_cells(f'A{current_row}:F{current_row}')
    current_row += 1
    
    cliente_fields = {
        'Nombre': all_fields.get('ClienteNombre', ''),
        'RUT/Tax ID': all_fields.get('ClienteRUT', ''),
        'Giro': all_fields.get('ClienteGiro', ''),
        'Dirección': all_fields.get('ClienteDireccion', ''),
        'Teléfono': all_fields.get('ClienteFono', ''),
        'Email': all_fields.get('ClienteEmail', '')
    }
    
    for label, value in cliente_fields.items():
        if value:
            ws[f'A{current_row}'] = label
            ws[f'B{current_row}'] = str(value)
            ws[f'A{current_row}'].font = normal_font
            ws[f'B{current_row}'].font = normal_font
            ws.merge_cells(f'B{current_row}:F{current_row}')
            current_row += 1
    current_row += 1
    
    # ITEMS DE LA FACTURA
    if any([all_fields.get('Descripcion'), all_fields.get('CodigoItem')]):
        ws[f'A{current_row}'] = 'DETALLE DE ITEMS'
        ws[f'A{current_row}'].font = section_font
        ws[f'A{current_row}'].fill = section_fill
        ws.merge_cells(f'A{current_row}:F{current_row}')
        current_row += 1
        
        # Procesar items desde all_fields
        descripciones = str(all_fields.get('Descripcion', '')).split('\n') if all_fields.get('Descripcion') else []
        cantidades = str(all_fields.get('Cantidad', '')).split('\n') if all_fields.get('Cantidad') else []
        codigos = str(all_fields.get('CodigoItem', '')).split('\n') if all_fields.get('CodigoItem') else []
        precios = str(all_fields.get('PrecioUnitario', '')).split('\n') if all_fields.get('PrecioUnitario') else []
        totales = str(all_fields.get('TotalItem', '')).split('\n') if all_fields.get('TotalItem') else []
        
        # Encabezados
        headers = ['Código', 'Descripción', 'Cantidad', 'P. Unitario', 'Total']
        for idx, header in enumerate(headers):
            col = chr(65 + idx)  # A, B, C, D, E
            ws[f'{col}{current_row}'] = header
            ws[f'{col}{current_row}'].font = Font(bold=True)
            ws[f'{col}{current_row}'].fill = alt_row_fill
            ws[f'{col}{current_row}'].border = thin_border
            ws[f'{col}{current_row}'].alignment = Alignment(horizontal='center')
        current_row += 1
        
        # Datos
        max_items = max(len(descripciones), len(cantidades), len(codigos), len(precios), len(totales))
        for i in range(max_items):
            ws[f'A{current_row}'] = codigos[i] if i < len(codigos) else ''
            ws[f'B{current_row}'] = descripciones[i] if i < len(descripciones) else ''
            ws[f'C{current_row}'] = cantidades[i] if i < len(cantidades) else ''
            ws[f'D{current_row}'] = precios[i] if i < len(precios) else ''
            ws[f'E{current_row}'] = totales[i] if i < len(totales) else ''
            
            for col in ['A', 'B', 'C', 'D', 'E']:
                ws[f'{col}{current_row}'].border = thin_border
                ws[f'{col}{current_row}'].font = normal_font
            
            current_row += 1
        current_row += 1
    
    # TOTALES
    ws[f'A{current_row}'] = 'TOTALES'
    ws[f'A{current_row}'].font = section_font
    ws[f'A{current_row}'].fill = section_fill
    ws.merge_cells(f'A{current_row}:F{current_row}')
    current_row += 1
    
    totales_fields = {
        'Subtotal': all_fields.get('SubtotalCLP', all_fields.get('SubtotalUSD', '')),
        'Impuesto/IVA': all_fields.get('ImpuestoCLP', all_fields.get('ImpuestoUSD', '')),
        'Total': all_fields.get('TotalCLP', all_fields.get('TotalUSD', invoice_data.get('totals', {}).get('total', '')))
    }
    
    for label, value in totales_fields.items():
        if value:
            ws[f'C{current_row}'] = label
            ws[f'D{current_row}'] = str(value)
            ws[f'C{current_row}'].font = Font(bold=True)
            ws[f'D{current_row}'].font = Font(bold=True)
            ws[f'D{current_row}'].alignment = Alignment(horizontal='right')
            current_row += 1
    current_row += 1
    
    # INFORMACIÓN ADICIONAL
    if any([all_fields.get('Banco'), all_fields.get('FormaPago'), all_fields.get('SWIFT')]):
        ws[f'A{current_row}'] = 'INFORMACIÓN BANCARIA Y PAGO'
        ws[f'A{current_row}'].font = section_font
        ws[f'A{current_row}'].fill = section_fill
        ws.merge_cells(f'A{current_row}:F{current_row}')
        current_row += 1
        
        bank_fields = {
            'Banco': all_fields.get('Banco', ''),
            'Dirección Banco': all_fields.get('BancoDireccion', ''),
            'SWIFT': all_fields.get('SWIFT', ''),
            'Forma de Pago': all_fields.get('FormaPago', '')
        }
        
        for label, value in bank_fields.items():
            if value:
                ws[f'A{current_row}'] = label
                ws[f'B{current_row}'] = str(value)
                ws[f'A{current_row}'].font = normal_font
                ws[f'B{current_row}'].font = normal_font
                ws.merge_cells(f'B{current_row}:F{current_row}')
                current_row += 1
    
    # Ajustar anchos de columna
    ws.column_dimensions['A'].width = 20
    ws.column_dimensions['B'].width = 40
    ws.column_dimensions['C'].width = 15
    ws.column_dimensions['D'].width = 15
    ws.column_dimensions['E'].width = 15
    ws.column_dimensions['F'].width = 15
    
    # Guardar en memoria
    excel_file = io.BytesIO()
    wb.save(excel_file)
    excel_file.seek(0)
    
    return excel_file

def create_transport_excel(transport_data: dict) -> io.BytesIO:
    """Crear un archivo Excel con formato corporativo para documentos de transporte"""
    wb = openpyxl.Workbook()
    
    # Hoja principal
    ws = wb.active
    ws.title = "Resumen"
    
    # Estilos (mismo estilo corporativo)
    header_font = Font(name='Arial', size=16, bold=True, color="FFFFFF")
    section_font = Font(name='Arial', size=12, bold=True, color="FFFFFF")
    normal_font = Font(name='Arial', size=10)
    
    header_fill = PatternFill(start_color="2C3E50", end_color="2C3E50", fill_type="solid")
    section_fill = PatternFill(start_color="3498DB", end_color="3498DB", fill_type="solid")
    
    # Encabezado
    ws.merge_cells('A1:F1')
    ws['A1'] = 'DOCUMENTO DE TRANSPORTE - DATOS EXTRAÍDOS'
    ws['A1'].font = header_font
    ws['A1'].fill = header_fill
    ws['A1'].alignment = Alignment(horizontal='center', vertical='center')
    ws.row_dimensions[1].height = 30
    
    current_row = 3
    
    # Función auxiliar para escribir secciones
    def write_section(sheet, title, data, row):
        if data:
            sheet[f'A{row}'] = title
            sheet[f'A{row}'].font = section_font
            sheet[f'A{row}'].fill = section_fill
            sheet.merge_cells(f'A{row}:F{row}')
            row += 1
            
            for key, value in data.items():
                sheet[f'A{row}'] = str(key).replace('_', ' ').title()
                sheet[f'B{row}'] = str(value)
                sheet[f'A{row}'].font = normal_font
                sheet[f'B{row}'].font = normal_font
                sheet.merge_cells(f'B{row}:F{row}')
                row += 1
            row += 1
        return row
    
    # Si hay all_fields, procesar primero esos datos
    all_fields = transport_data.get('all_fields', {})
    if all_fields:
        current_row = write_section(ws, 'INFORMACIÓN GENERAL DEL DOCUMENTO', all_fields, current_row)
    
    # Escribir secciones de datos estructurados
    current_row = write_section(ws, 'INFORMACIÓN DEL DOCUMENTO', transport_data.get('document_info', {}), current_row)
    current_row = write_section(ws, 'REMITENTE', transport_data.get('shipper', {}), current_row)
    current_row = write_section(ws, 'DESTINATARIO', transport_data.get('consignee', {}), current_row)
    current_row = write_section(ws, 'DETALLES DE TRANSPORTE', transport_data.get('transport_details', {}), current_row)
    
    # Hoja de mercancías si hay datos
    if transport_data.get('goods'):
        ws_goods = wb.create_sheet(title="Mercancías")
        
        # Encabezado
        ws_goods.merge_cells('A1:H1')
        ws_goods['A1'] = 'LISTA DE MERCANCÍAS'
        ws_goods['A1'].font = header_font
        ws_goods['A1'].fill = header_fill
        ws_goods['A1'].alignment = Alignment(horizontal='center', vertical='center')
        
        # Obtener todas las claves únicas
        all_keys = set()
        for item in transport_data['goods']:
            all_keys.update(item.keys())
        
        # Escribir encabezados
        col_idx = 1
        for key in all_keys:
            cell = ws_goods.cell(row=3, column=col_idx, value=key.title())
            cell.font = Font(bold=True)
            cell.fill = PatternFill(start_color="E3F2FD", end_color="E3F2FD", fill_type="solid")
            col_idx += 1
        
        # Escribir datos
        row_idx = 4
        for item in transport_data['goods']:
            col_idx = 1
            for key in all_keys:
                value = item.get(key, '')
                ws_goods.cell(row=row_idx, column=col_idx, value=str(value))
                col_idx += 1
            row_idx += 1
        
        # Ajustar anchos de columna
        for col in ws_goods.columns:
            max_length = 0
            column = col[0].column_letter
            for cell in col:
                try:
                    if len(str(cell.value)) > max_length:
                        max_length = len(str(cell.value))
                except:
                    pass
            adjusted_width = min(max_length + 2, 40)
            ws_goods.column_dimensions[column].width = adjusted_width
    
    # Hoja de texto extraído si existe
    if transport_data.get('extracted_text'):
        ws_text = wb.create_sheet(title="Texto Extraído")
        
        # Encabezado
        ws_text.merge_cells('A1:D1')
        ws_text['A1'] = 'TEXTO COMPLETO EXTRAÍDO'
        ws_text['A1'].font = header_font
        ws_text['A1'].fill = header_fill
        ws_text['A1'].alignment = Alignment(horizontal='center', vertical='center')
        
        row_idx = 3
        for page_key, page_text in transport_data['extracted_text'].items():
            # Título de página
            ws_text[f'A{row_idx}'] = page_key.upper().replace('_', ' ')
            ws_text[f'A{row_idx}'].font = Font(bold=True)
            ws_text[f'A{row_idx}'].fill = PatternFill(start_color="E3F2FD", end_color="E3F2FD", fill_type="solid")
            ws_text.merge_cells(f'A{row_idx}:D{row_idx}')
            row_idx += 1
            
            # Texto de la página
            lines = page_text.split('\n')
            for line in lines:
                if line.strip():
                    ws_text[f'A{row_idx}'] = line
                    ws_text.merge_cells(f'A{row_idx}:D{row_idx}')
                    row_idx += 1
            row_idx += 1
        
        # Ajustar ancho de columna
        ws_text.column_dimensions['A'].width = 100
    
    # Ajustar anchos de columna de la hoja principal
    ws.column_dimensions['A'].width = 30
    ws.column_dimensions['B'].width = 40
    
    # Guardar en memoria
    excel_file = io.BytesIO()
    wb.save(excel_file)
    excel_file.seek(0)
    
    return excel_file

# Endpoints
@app.get("/")
async def root():
    return {"service": "Document Processing API", "status": "running"}

@app.get("/health")
async def health():
    health_status = {
        "status": "healthy",
        "service": "api-docs",
        "azure_configured": bool(document_analysis_client),
        "timestamp": datetime.now().isoformat(),
        "configuration": {
            "endpoint_set": bool(ENDPOINT),
            "api_key_set": bool(API_KEY),
            "invoice_model": INVOICE_MODEL_ID,
            "transport_model": TRANSPORT_MODEL_ID,
            "using_custom_models": {
                "invoice": INVOICE_MODEL_ID != "prebuilt-invoice",
                "transport": TRANSPORT_MODEL_ID != "prebuilt-document"
            }
        }
    }
    
    # Verificar conexión con Azure si está configurado
    if document_analysis_client and ENDPOINT and API_KEY:
        try:
            # Intentar una operación simple para verificar conectividad
            # Nota: esto no consume recursos significativos
            health_status["azure_connection"] = "OK"
        except Exception as e:
            health_status["azure_connection"] = f"Error: {str(e)}"
            health_status["status"] = "degraded"
    
    return health_status

@app.post("/process/invoice")
async def process_invoice(
    file: UploadFile = File(...),
    numero_despacho: Optional[str] = None,
    tipo_documento: Optional[str] = "factura_comercial",
    authorization: str = Header(None)
):
    """Procesar una factura usando Azure Document Intelligence"""
    if not document_analysis_client:
        raise HTTPException(status_code=500, detail="Azure Document Intelligence no configurado")
    
    username = get_username_from_header(authorization)
    process_id = str(uuid.uuid4())
    
    # Inicializar resultado
    result_data = ProcessingResult(
        id=process_id,
        username=username,
        filename=file.filename,
        document_type="invoice",
        status="processing",
        processed_at=datetime.now()
    )
    
    # Guardar en historial
    if username not in processing_history:
        processing_history[username] = []
    processing_history[username].append(result_data)
    
    try:
        # Leer archivo
        contents = await file.read()
        
        # Verificar que es un PDF
        if not contents.startswith(b'%PDF'):
            raise HTTPException(status_code=400, detail="El archivo no es un PDF válido")
        
        # Analizar con Azure
        poller = document_analysis_client.begin_analyze_document(
            INVOICE_MODEL_ID,
            document=contents
        )
        
        result = poller.result()
        
        # Extraer datos
        invoice_data = extract_invoice_data(result)
        
        # Verificar si se extrajeron datos
        has_data = any([
            invoice_data.get("vendor_information"),
            invoice_data.get("customer_information"),
            invoice_data.get("invoice_details"),
            invoice_data.get("totals"),
            invoice_data.get("line_items"),
            invoice_data.get("extracted_text"),
            invoice_data.get("all_fields")
        ])
        
        if not has_data:
            # Agregar información de debug
            invoice_data["debug_info"] = {
                "model_used": INVOICE_MODEL_ID,
                "pages_processed": invoice_data["metadata"]["pages"],
                "message": "No se pudieron extraer datos estructurados. Verifique que el modelo esté configurado correctamente."
            }
        
        # Guardar en base de datos si se especificó despacho
        if numero_despacho:
            save_to_despacho_db(numero_despacho, tipo_documento, invoice_data)
        
        # Actualizar resultado
        result_data.status = "completed"
        result_data.extracted_data = invoice_data
        result_data.json_url = f"/download/{process_id}/json"
        result_data.excel_url = f"/download/{process_id}/excel"
        
        # Guardar datos para descarga
        if not hasattr(app.state, 'processed_documents'):
            app.state.processed_documents = {}
        
        app.state.processed_documents[process_id] = {
            'data': invoice_data,
            'type': 'invoice',
            'filename': file.filename
        }
        
        return result_data
        
    except Exception as e:
        import traceback
        traceback.print_exc()
        
        result_data.status = "error"
        result_data.error_message = f"Error: {str(e)}"
        
        # Si es un error de Azure, intentar dar más detalles
        if "InvalidRequest" in str(e):
            result_data.error_message = "Error de configuración: Verifique que el modelo de Azure esté correctamente configurado"
        elif "AuthenticationFailed" in str(e):
            result_data.error_message = "Error de autenticación: Verifique las credenciales de Azure"
        
        raise HTTPException(status_code=500, detail=result_data.error_message)

@app.post("/process/transport")
async def process_transport(
    file: UploadFile = File(...),
    numero_despacho: Optional[str] = None,
    tipo_documento: Optional[str] = "conocimiento_transporte",  # CAMBIO: era "conocimiento_embarque"
    authorization: str = Header(None)
):
    """Procesar un documento de transporte usando Azure Document Intelligence"""
    if not document_analysis_client:
        raise HTTPException(status_code=500, detail="Azure Document Intelligence no configurado")
    
    username = get_username_from_header(authorization)
    process_id = str(uuid.uuid4())
    
    # Inicializar resultado
    result_data = ProcessingResult(
        id=process_id,
        username=username,
        filename=file.filename,
        document_type="transport",
        status="processing",
        processed_at=datetime.now()
    )
    
    # Guardar en historial
    if username not in processing_history:
        processing_history[username] = []
    processing_history[username].append(result_data)
    
    try:
        # Leer archivo
        contents = await file.read()
        
        # Verificar que es un PDF
        if not contents.startswith(b'%PDF'):
            raise HTTPException(status_code=400, detail="El archivo no es un PDF válido")
        
        # Analizar con Azure
        poller = document_analysis_client.begin_analyze_document(
            TRANSPORT_MODEL_ID,
            document=contents
        )
        
        result = poller.result()
        
        # Extraer datos
        transport_data = extract_transport_data(result)
        
        # Verificar si se extrajeron datos
        has_data = any([
            transport_data.get("shipper"),
            transport_data.get("consignee"),
            transport_data.get("transport_details"),
            transport_data.get("goods"),
            transport_data.get("extracted_text"),
            transport_data.get("all_fields")
        ])
        
        if not has_data:
            # Agregar información de debug
            transport_data["debug_info"] = {
                "model_used": TRANSPORT_MODEL_ID,
                "pages_processed": transport_data["metadata"]["pages"],
                "message": "No se pudieron extraer datos estructurados. Verifique que el modelo esté configurado correctamente."
            }
        
        # Guardar en base de datos si se especificó despacho
        if numero_despacho:
            save_to_despacho_db(numero_despacho, tipo_documento, transport_data)
        
        # Actualizar resultado
        result_data.status = "completed"
        result_data.extracted_data = transport_data
        result_data.json_url = f"/download/{process_id}/json"
        result_data.excel_url = f"/download/{process_id}/excel"
        
        # Guardar datos para descarga
        if not hasattr(app.state, 'processed_documents'):
            app.state.processed_documents = {}
        
        app.state.processed_documents[process_id] = {
            'data': transport_data,
            'type': 'transport',
            'filename': file.filename
        }
        
        return result_data
        
    except Exception as e:
        import traceback
        traceback.print_exc()
        
        result_data.status = "error"
        result_data.error_message = f"Error: {str(e)}"
        
        # Si es un error de Azure, intentar dar más detalles
        if "InvalidRequest" in str(e):
            result_data.error_message = "Error de configuración: Verifique que el modelo de Azure esté correctamente configurado"
        elif "AuthenticationFailed" in str(e):
            result_data.error_message = "Error de autenticación: Verifique las credenciales de Azure"
        
        raise HTTPException(status_code=500, detail=result_data.error_message)

@app.get("/history")
async def get_history(
    authorization: str = Header(None),
    limit: int = 50,
    offset: int = 0
):
    """Obtener historial de procesamiento del usuario"""
    username = get_username_from_header(authorization)
    
    user_history = processing_history.get(username, [])
    
    # Ordenar por fecha descendente
    sorted_history = sorted(user_history, key=lambda x: x.processed_at, reverse=True)
    
    # Paginar
    paginated = sorted_history[offset:offset + limit]
    
    return ProcessingHistory(
        results=paginated,
        total=len(user_history)
    )

@app.get("/download/{process_id}/{format}")
async def download_result(
    process_id: str,
    format: str,
    authorization: str = Header(None)
):
    """Descargar resultado en formato JSON o Excel"""
    if format not in ["json", "excel"]:
        raise HTTPException(status_code=400, detail="Formato no válido. Use 'json' o 'excel'")
    
    if not hasattr(app.state, 'processed_documents') or process_id not in app.state.processed_documents:
        raise HTTPException(status_code=404, detail="Documento no encontrado")
    
    doc_info = app.state.processed_documents[process_id]
    
    if format == "json":
        # Devolver JSON
        json_data = json.dumps(doc_info['data'], indent=2, ensure_ascii=False)
        return StreamingResponse(
            io.BytesIO(json_data.encode('utf-8')),
            media_type="application/json",
            headers={
                "Content-Disposition": f"attachment; filename={doc_info['filename']}.json"
            }
        )
    
    else:  # excel
        # Crear Excel según el tipo
        if doc_info['type'] == 'invoice':
            excel_file = create_invoice_excel(doc_info['data'])
        else:
            excel_file = create_transport_excel(doc_info['data'])
        
        return StreamingResponse(
            excel_file,
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            headers={
                "Content-Disposition": f"attachment; filename={doc_info['filename']}.xlsx"
            }
        )

@app.delete("/history/{process_id}")
async def delete_from_history(
    process_id: str,
    authorization: str = Header(None)
):
    """Eliminar un documento del historial"""
    username = get_username_from_header(authorization)
    
    if username in processing_history:
        processing_history[username] = [
            r for r in processing_history[username] if r.id != process_id
        ]
    
    # También eliminar los datos almacenados
    if hasattr(app.state, 'processed_documents') and process_id in app.state.processed_documents:
        del app.state.processed_documents[process_id]
    
    return {"message": "Documento eliminado del historial"}

@app.get("/debug/config")
async def debug_config():
    """Endpoint de debug para verificar configuración"""
    return {
        "azure_configured": bool(document_analysis_client),
        "endpoint_configured": bool(ENDPOINT),
        "api_key_configured": bool(API_KEY),
        "invoice_model_id": INVOICE_MODEL_ID,
        "transport_model_id": TRANSPORT_MODEL_ID,
        "models_are_custom": {
            "invoice": INVOICE_MODEL_ID != "prebuilt-invoice",
            "transport": TRANSPORT_MODEL_ID != "prebuilt-document"
        },
        "message": "Si está usando modelos custom, asegúrese de que los IDs coincidan con los modelos entrenados en Azure"
    }

@app.post("/debug/test-extraction")
async def test_extraction(
    file: UploadFile = File(...),
    model_type: str = "invoice"
):
    """Endpoint de debug para probar extracción sin guardar en historial"""
    if not document_analysis_client:
        raise HTTPException(status_code=500, detail="Azure Document Intelligence no configurado")
    
    try:
        contents = await file.read()
        
        model_id = INVOICE_MODEL_ID if model_type == "invoice" else TRANSPORT_MODEL_ID
        
        poller = document_analysis_client.begin_analyze_document(
            model_id,
            document=contents
        )
        result = poller.result()
        
        # Información de debug detallada
        debug_info = {
            "model_id": model_id,
            "api_version": result.api_version if hasattr(result, 'api_version') else 'unknown',
            "model_id_used": result.model_id if hasattr(result, 'model_id') else 'unknown',
            "pages_count": len(result.pages) if hasattr(result, 'pages') else 0,
            "has_documents": hasattr(result, 'documents') and bool(result.documents),
            "has_tables": hasattr(result, 'tables') and bool(result.tables),
            "has_key_value_pairs": hasattr(result, 'key_value_pairs') and bool(result.key_value_pairs),
        }
        
        # Si hay documentos, mostrar campos disponibles
        if hasattr(result, 'documents') and result.documents:
            debug_info["document_fields"] = list(result.documents[0].fields.keys()) if hasattr(result.documents[0], 'fields') else []
        
        # Si hay key-value pairs, mostrar algunos ejemplos
        if hasattr(result, 'key_value_pairs') and result.key_value_pairs:
            sample_kvs = []
            for i, kv in enumerate(result.key_value_pairs[:5]):  # Primeros 5
                if kv.key and kv.value:
                    sample_kvs.append({
                        "key": kv.key.content if hasattr(kv.key, 'content') else str(kv.key),
                        "value": kv.value.content if hasattr(kv.value, 'content') else str(kv.value)
                    })
            debug_info["sample_key_value_pairs"] = sample_kvs
        
        # Extraer datos según el tipo
        if model_type == "invoice":
            extracted_data = extract_invoice_data(result)
        else:
            extracted_data = extract_transport_data(result)
        
        return {
            "debug_info": debug_info,
            "extracted_data": extracted_data
        }
        
    except Exception as e:
        import traceback
        return {
            "error": str(e),
            "traceback": traceback.format_exc(),
            "model_id": INVOICE_MODEL_ID if model_type == "invoice" else TRANSPORT_MODEL_ID
        }

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8002)