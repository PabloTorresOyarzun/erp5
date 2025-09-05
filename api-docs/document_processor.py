# api-docs/document_processor.py
import fitz  # pymupdf
import os
import base64
from typing import List, Dict, Tuple
from azure.ai.formrecognizer import DocumentAnalysisClient
from azure.core.credentials import AzureKeyCredential
import json
from datetime import datetime

# Configuración modelos custom
ENDPOINT = os.getenv('AZURE_FORM_RECOGNIZER_ENDPOINT', '')
API_KEY = os.getenv('AZURE_FORM_RECOGNIZER_KEY', '')
DOCTYPE_MODEL_ID = os.getenv('DOCTYPE_MODEL_ID', 'doctype_01')
INVOICE_MODEL_ID = os.getenv('INVOICE_MODEL_ID', 'invoice_01')
TRANSPORT_MODEL_ID = os.getenv('TRANSPORT_MODEL_ID', 'transport_01')

document_analysis_client = DocumentAnalysisClient(
    endpoint=ENDPOINT,
    credential=AzureKeyCredential(API_KEY)
) if ENDPOINT and API_KEY else None

class DocumentProcessor:
    def __init__(self):
        self.client = document_analysis_client
    
    def separate_pages(self, pdf_bytes: bytes) -> List[bytes]:
        """Separar PDF en páginas individuales"""
        doc = fitz.open("pdf", pdf_bytes)
        pages = []
        
        for page_num in range(len(doc)):
            new_doc = fitz.open()
            new_doc.insert_pdf(doc, from_page=page_num, to_page=page_num)
            page_bytes = new_doc.write()
            pages.append(page_bytes)
            new_doc.close()
        
        doc.close()
        return pages
    
    def classify_page(self, page_bytes: bytes) -> str:
        """Clasificar una página usando doctype_01"""
        if not self.client:
            print("   ⚠️ Cliente Azure no configurado, usando clasificación por defecto")
            return "general"
        
        try:
            print(f"   🔍 Clasificando con modelo: {DOCTYPE_MODEL_ID}")
            
            # Usar begin_classify_document para modelos de clasificación
            poller = self.client.begin_classify_document(
                DOCTYPE_MODEL_ID,
                document=page_bytes
            )
            result = poller.result()
            
            # Extraer tipo de documento desde el resultado de clasificación
            if hasattr(result, 'documents') and result.documents:
                for doc in result.documents:
                    # Para modelos de clasificación, el tipo está en doc_type
                    if hasattr(doc, 'doc_type'):
                        doc_type = doc.doc_type
                        confidence = doc.confidence if hasattr(doc, 'confidence') else 0
                        print(f"   ✅ Clasificación: {doc_type} (confianza: {confidence:.2%})")
                        
                        # Normalizar el tipo de documento
                        doc_type_lower = doc_type.lower()
                        
                        # Mapeo de tipos detectados a tipos internos
                        if 'invoice' in doc_type_lower or 'factura' in doc_type_lower:
                            return "factura"
                        elif any(t in doc_type_lower for t in ['transport', 'transporte', 'awb', 'bl', 'bill_of_lading', 'air_waybill']):
                            return "transporte"
                        elif 'packing' in doc_type_lower or 'lista_empaque' in doc_type_lower:
                            return "packing_list"
                        elif 'certificate' in doc_type_lower or 'certificado' in doc_type_lower:
                            return "certificado"
                        else:
                            # Si el modelo devuelve un tipo específico, usarlo
                            print(f"   ℹ️ Tipo no mapeado, usando: {doc_type}")
                            return doc_type
            
            # Si no se detectó tipo específico
            print("   ⚠️ No se pudo clasificar, usando tipo general")
            return "general"
            
        except Exception as e:
            print(f"   ❌ Error clasificando página: {e}")
            import traceback
            traceback.print_exc()
            return "general"
    
    def group_consecutive_pages(self, page_classifications: List[Tuple[int, str]]) -> List[Dict]:
        """Agrupar páginas consecutivas del mismo tipo"""
        if not page_classifications:
            return []
        
        groups = []
        current_group = {
            'start_page': page_classifications[0][0],
            'end_page': page_classifications[0][0],
            'doc_type': page_classifications[0][1],
            'pages': [page_classifications[0][0]]
        }
        
        for i in range(1, len(page_classifications)):
            page_num, doc_type = page_classifications[i]
            
            if doc_type == current_group['doc_type'] and page_num == current_group['end_page'] + 1:
                current_group['end_page'] = page_num
                current_group['pages'].append(page_num)
            else:
                groups.append(current_group)
                current_group = {
                    'start_page': page_num,
                    'end_page': page_num,
                    'doc_type': doc_type,
                    'pages': [page_num]
                }
        
        groups.append(current_group)
        return groups
    
    def create_pdf_from_pages(self, original_pdf: bytes, page_numbers: List[int]) -> bytes:
        """Crear PDF desde páginas específicas"""
        doc = fitz.open("pdf", original_pdf)
        new_doc = fitz.open()
        
        for page_num in page_numbers:
            new_doc.insert_pdf(doc, from_page=page_num, to_page=page_num)
        
        pdf_bytes = new_doc.write()
        new_doc.close()
        doc.close()
        
        return pdf_bytes
    
    def process_with_model(self, doc_bytes: bytes, doc_type: str) -> Dict:
        """Procesar documento con modelo específico"""
        if not self.client:
            return {"error": "Azure client no configurado"}
        
        try:
            # Mapear tipo de documento a modelo
            model_map = {
                "factura": INVOICE_MODEL_ID,
                "invoice": INVOICE_MODEL_ID,
                "transporte": TRANSPORT_MODEL_ID,
                "transport": TRANSPORT_MODEL_ID,
                "awb": TRANSPORT_MODEL_ID,
                "bl": TRANSPORT_MODEL_ID,
                "bill_of_lading": TRANSPORT_MODEL_ID,
                "air_waybill": TRANSPORT_MODEL_ID
            }
            
            model_id = model_map.get(doc_type.lower())
            
            if not model_id:
                print(f"   ℹ️ No hay modelo específico para tipo: {doc_type}")
                return {"doc_type": doc_type, "message": "Tipo sin modelo específico"}
            
            print(f"   📄 Procesando con modelo: {model_id}")
            
            # Usar begin_analyze_document para modelos de extracción
            poller = self.client.begin_analyze_document(model_id, document=doc_bytes)
            result = poller.result()
            
            # Extraer datos según el modelo usado
            if INVOICE_MODEL_ID in model_id:
                data = self._extract_invoice_data(result)
            elif TRANSPORT_MODEL_ID in model_id:
                data = self._extract_transport_data(result)
            else:
                data = {"message": "Modelo no reconocido"}
            
            data["model_used"] = model_id
            data["doc_type_original"] = doc_type
            return data
            
        except Exception as e:
            print(f"   ❌ Error procesando con modelo: {e}")
            return {"error": f"Error procesando: {e}", "doc_type": doc_type}
    
    def _extract_invoice_data(self, result) -> Dict:
        """Extraer datos de factura"""
        data = {
            "vendor_information": {},
            "customer_information": {},
            "invoice_details": {},
            "totals": {},
            "line_items": []
        }
        
        # Primero intentar con campos del modelo custom
        if hasattr(result, 'documents') and result.documents:
            for doc in result.documents:
                if hasattr(doc, 'fields'):
                    for field_name, field_value in doc.fields.items():
                        if hasattr(field_value, 'value') and field_value.value:
                            value = str(field_value.value)
                            field_lower = field_name.lower()
                            
                            if any(t in field_lower for t in ['vendor', 'supplier', 'seller']):
                                data["vendor_information"][field_name] = value
                            elif any(t in field_lower for t in ['customer', 'buyer', 'client']):
                                data["customer_information"][field_name] = value
                            elif any(t in field_lower for t in ['total', 'amount', 'subtotal', 'tax']):
                                data["totals"][field_name] = value
                            elif any(t in field_lower for t in ['item', 'line', 'product']):
                                data["line_items"].append({field_name: value})
                            else:
                                data["invoice_details"][field_name] = value
        
        # Si no hay campos, intentar con key-value pairs
        if not any([data["vendor_information"], data["customer_information"], data["totals"]]):
            if hasattr(result, 'key_value_pairs') and result.key_value_pairs:
                for kv_pair in result.key_value_pairs:
                    if kv_pair.key and kv_pair.value:
                        key = kv_pair.key.content if hasattr(kv_pair.key, 'content') else str(kv_pair.key)
                        value = kv_pair.value.content if hasattr(kv_pair.value, 'content') else str(kv_pair.value)
                        
                        key_lower = key.lower()
                        if any(t in key_lower for t in ['vendor', 'supplier']):
                            data["vendor_information"][key] = value
                        elif any(t in key_lower for t in ['customer', 'buyer']):
                            data["customer_information"][key] = value
                        elif any(t in key_lower for t in ['total', 'amount']):
                            data["totals"][key] = value
        
        return data
    
    def _extract_transport_data(self, result) -> Dict:
        """Extraer datos de documento de transporte"""
        data = {
            "shipper": {},
            "consignee": {},
            "transport_details": {},
            "goods": []
        }
        
        # Intentar con campos del modelo custom
        if hasattr(result, 'documents') and result.documents:
            for doc in result.documents:
                if hasattr(doc, 'fields'):
                    for field_name, field_value in doc.fields.items():
                        if hasattr(field_value, 'value') and field_value.value:
                            value = str(field_value.value)
                            field_lower = field_name.lower()
                            
                            if any(t in field_lower for t in ['shipper', 'sender', 'remitente', 'exportador']):
                                data["shipper"][field_name] = value
                            elif any(t in field_lower for t in ['consignee', 'receiver', 'destinatario', 'importador']):
                                data["consignee"][field_name] = value
                            elif any(t in field_lower for t in ['goods', 'cargo', 'mercancia', 'descripcion']):
                                data["goods"].append({field_name: value})
                            else:
                                data["transport_details"][field_name] = value
        
        # Si no hay campos, intentar con key-value pairs
        if not any([data["shipper"], data["consignee"], data["transport_details"]]):
            if hasattr(result, 'key_value_pairs') and result.key_value_pairs:
                for kv_pair in result.key_value_pairs:
                    if kv_pair.key and kv_pair.value:
                        key = kv_pair.key.content if hasattr(kv_pair.key, 'content') else str(kv_pair.key)
                        value = kv_pair.value.content if hasattr(kv_pair.value, 'content') else str(kv_pair.value)
                        
                        key_lower = key.lower()
                        if any(t in key_lower for t in ['shipper', 'sender']):
                            data["shipper"][key] = value
                        elif any(t in key_lower for t in ['consignee', 'receiver']):
                            data["consignee"][key] = value
                        else:
                            data["transport_details"][key] = value
        
        return data

def process_dispatch_workflow(pdf_bytes: bytes, numero_despacho: str) -> Dict:
    """Workflow completo de procesamiento de despacho"""
    processor = DocumentProcessor()
    resultado = {
        "numero_despacho": numero_despacho,
        "timestamp": datetime.now().isoformat(),
        "documentos_procesados": [],
        "resumen": {}
    }
    
    try:
        # 1. IDENTIFICACIÓN
        print(f"[1/4] Separando páginas del PDF...")
        pages = processor.separate_pages(pdf_bytes)
        resultado["total_paginas"] = len(pages)
        print(f"   Total: {len(pages)} páginas")
        
        print(f"[2/4] Clasificando {len(pages)} páginas...")
        page_classifications = []
        for i, page_bytes in enumerate(pages):
            doc_type = processor.classify_page(page_bytes)
            page_classifications.append((i, doc_type))
            print(f"   Página {i+1}: {doc_type}")
        
        # 2. AGRUPACIÓN
        print(f"[3/4] Agrupando páginas consecutivas...")
        groups = processor.group_consecutive_pages(page_classifications)
        resultado["total_documentos"] = len(groups)
        print(f"   Resultado: {len(groups)} documento(s)")
        
        # 3. ALMACENAMIENTO Y PROCESAMIENTO
        print(f"[4/4] Procesando {len(groups)} documentos...")
        documentos = []
        
        for idx, group in enumerate(groups):
            print(f"   Documento {idx+1}: {group['doc_type']} (páginas {group['start_page']+1}-{group['end_page']+1})")
            
            # Crear PDF del grupo
            doc_pdf = processor.create_pdf_from_pages(pdf_bytes, group['pages'])
            
            # Procesar con modelo específico
            extracted_data = processor.process_with_model(doc_pdf, group['doc_type'])
            
            # Preparar documento
            documento = {
                "id": f"{numero_despacho}_{idx+1}",
                "tipo": group['doc_type'],
                "paginas": f"{group['start_page']+1}-{group['end_page']+1}",
                "total_paginas": len(group['pages']),
                "pdf_base64": base64.b64encode(doc_pdf).decode('utf-8'),
                "datos_extraidos": extracted_data,
                "procesado": not extracted_data.get("error"),
                "timestamp": datetime.now().isoformat()
            }
            
            documentos.append(documento)
            resultado["documentos_procesados"].append({
                "id": documento["id"],
                "tipo": documento["tipo"],
                "paginas": documento["paginas"],
                "procesado": documento["procesado"]
            })
        
        # Generar resumen con conteo por tipo
        tipos_contador = {}
        for doc in documentos:
            tipo = doc["tipo"]
            tipos_contador[tipo] = tipos_contador.get(tipo, 0) + 1
        
        resultado["resumen"] = tipos_contador
        resultado["documentos"] = documentos
        
        print(f"✅ Procesamiento completado")
        print(f"   Resumen: {tipos_contador}")
        
        return resultado
        
    except Exception as e:
        print(f"❌ Error en workflow: {e}")
        import traceback
        traceback.print_exc()
        resultado["error"] = str(e)
        return resultado