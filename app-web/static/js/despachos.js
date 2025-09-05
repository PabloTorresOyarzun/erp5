// Despachos Management JavaScript
// Functionality for managing shipping operations

// ==================== GLOBAL VARIABLES ====================
let currentPage = 1;
let totalPages = 1;
let pageSize = 25;
let despachoSeleccionado = null;
let archivoSeleccionado = null;

// ==================== INITIALIZATION ====================
document.addEventListener('DOMContentLoaded', function() {
    cargarDespachos();
    setupDragAndDrop();
});

function setupDragAndDrop() {
    const uploadZone = document.getElementById('uploadZone');
    const fileInput = document.getElementById('fileInput');
    
    uploadZone.addEventListener('dragover', (e) => {
        e.preventDefault();
        uploadZone.classList.add('dragover');
    });
    
    uploadZone.addEventListener('dragleave', (e) => {
        e.preventDefault();
        uploadZone.classList.remove('dragover');
    });
    
    uploadZone.addEventListener('drop', (e) => {
        e.preventDefault();
        uploadZone.classList.remove('dragover');
        if (e.dataTransfer.files.length > 0) {
            handleFileSelection(e.dataTransfer.files[0]);
        }
    });
    
    fileInput.addEventListener('change', (e) => {
        if (e.target.files.length > 0) {
            handleFileSelection(e.target.files[0]);
        }
    });
}

function handleFileSelection(file) {
    if (file.type !== 'application/pdf') {
        showAlert('Solo se permiten archivos PDF', 'warning');
        return;
    }
    
    if (file.size > 10 * 1024 * 1024) {
        showAlert('El archivo no puede ser mayor a 10MB', 'warning');
        return;
    }
    
    archivoSeleccionado = file;
    document.getElementById('fileName').textContent = file.name;
    document.getElementById('fileSize').textContent = formatFileSize(file.size);
    document.getElementById('filePreview').classList.remove('d-none');
    document.getElementById('uploadBtn').disabled = false;
}

// ==================== DESPACHOS LISTING ====================
async function cargarDespachos(page = 1) {
    try {
        const offset = (page - 1) * pageSize;
        const response = await fetch(`/api/despachos?limit=${pageSize}&offset=${offset}`);
        const data = await response.json();
        
        mostrarDespachos(data.despachos);
        actualizarPaginacion(data.total, page);
        document.getElementById('totalDespachos').textContent = `Total: ${data.total}`;
        
    } catch (error) {
        console.error('Error:', error);
        showAlert('Error cargando despachos', 'error');
        mostrarError('Error cargando despachos');
    }
}

function mostrarDespachos(despachos) {
    const tbody = document.getElementById('despachosTableBody');
    
    if (despachos.length === 0) {
        tbody.innerHTML = '<tr><td colspan="7" class="text-center py-4">No hay despachos</td></tr>';
        return;
    }
    
    tbody.innerHTML = despachos.map(despacho => `
        <tr onclick="seleccionarDespacho('${despacho.numero_despacho}')" style="cursor: pointer;" class="table-row-hover">
            <td>
                <strong class="text-corporate-primary">${despacho.numero_despacho}</strong>
                <div class="d-md-none">
                    <small class="text-muted">
                        <span class="badge status-${despacho.estado}">${despacho.estado.toUpperCase()}</span>
                    </small>
                </div>
            </td>
            <td class="d-none d-md-table-cell">
                <span class="badge status-${despacho.estado}">${despacho.estado.toUpperCase()}</span>
            </td>
            <td>
                <div class="d-flex align-items-center gap-2">
                    <div class="progress progress-mini">
                        <div class="progress-bar progress-mini-fill" style="width: ${despacho.porcentaje_completitud}%"></div>
                    </div>
                    <small class="text-corporate-secondary">${despacho.porcentaje_completitud.toFixed(0)}%</small>
                </div>
                <div class="d-lg-none">
                    <small class="text-muted">${despacho.documentos_presentes}/${despacho.documentos_requeridos} docs</small>
                </div>
            </td>
            <td class="d-none d-lg-table-cell">
                <span class="badge bg-light text-dark">${despacho.documentos_presentes}/${despacho.documentos_requeridos}</span>
            </td>
            <td class="d-none d-xl-table-cell">
                <small class="text-muted">${new Date(despacho.fecha_creacion).toLocaleDateString()}</small>
            </td>
            <td class="d-none d-xl-table-cell">
                <small class="text-muted">${new Date(despacho.fecha_actualizacion).toLocaleDateString()}</small>
            </td>
            <td>
                <button class="btn btn-sm btn-primary btn-sm-corporate" onclick="event.stopPropagation(); verDespacho('${despacho.numero_despacho}')" title="Ver detalles">
                    <i class="bi bi-eye"></i>
                </button>
            </td>
        </tr>
    `).join('');
}

function actualizarPaginacion(total, currentPageNum) {
    totalPages = Math.ceil(total / pageSize);
    currentPage = currentPageNum;
    
    const pagination = document.getElementById('pagination');
    let html = '';
    
    if (totalPages <= 1) {
        pagination.innerHTML = '';
        return;
    }
    
    html += `<li class="page-item ${currentPage <= 1 ? 'disabled' : ''}">
        <a class="page-link" href="#" onclick="cargarDespachos(${currentPage - 1})">
            <i class="bi bi-chevron-left"></i>
            <span class="d-none d-sm-inline ms-1">Anterior</span>
        </a>
    </li>`;
    
    const startPage = Math.max(1, currentPage - 2);
    const endPage = Math.min(totalPages, currentPage + 2);
    
    for (let i = startPage; i <= endPage; i++) {
        html += `<li class="page-item ${i === currentPage ? 'active' : ''}">
            <a class="page-link" href="#" onclick="cargarDespachos(${i})">${i}</a>
        </li>`;
    }
    
    html += `<li class="page-item ${currentPage >= totalPages ? 'disabled' : ''}">
        <a class="page-link" href="#" onclick="cargarDespachos(${currentPage + 1})">
            <span class="d-none d-sm-inline me-1">Siguiente</span>
            <i class="bi bi-chevron-right"></i>
        </a>
    </li>`;
    
    pagination.innerHTML = html;
}

// ==================== DESPACHO DETAILS ====================
async function seleccionarDespacho(numero) {
    despachoSeleccionado = numero;
    
    try {
        await cargarDetalleDespacho(numero);
        
        document.getElementById('despachosList').classList.add('d-none');
        document.getElementById('despachoDetail').classList.remove('d-none');
        document.getElementById('btnVolver').classList.remove('d-none');
        
    } catch (error) {
        console.error('Error:', error);
        showAlert('Error cargando el despacho: ' + error.message, 'error');
    }
}

async function cargarDetalleDespacho(numero) {
    try {
        const [estado, documentos, datos] = await Promise.all([
            fetch(`/api/despachos/${numero}/estado`).then(r => r.json()),
            fetch(`/api/despachos/${numero}/documentos`).then(r => r.json()),
            fetch(`/api/despachos/${numero}/datos`).then(r => r.json())
        ]);
        
        mostrarDetalleResumen(estado);
        mostrarDetalleDocumentos(documentos);
        mostrarDetalleDatos(datos);
    } catch (error) {
        throw new Error('Error cargando detalles del despacho');
    }
}

function mostrarDetalleResumen(estado) {
    document.getElementById('resumen').innerHTML = `
        <div class="row mb-4">
            <div class="col">
                <h3 class="text-corporate-secondary mb-0">
                    <i class="bi bi-box-seam me-2"></i>Despacho: ${estado.numero_despacho}
                </h3>
            </div>
        </div>
        
        <div class="row g-3 stats-mobile">
            <div class="col-md-4">
                <div class="card stat-card shadow-corporate">
                    <div class="card-body text-center stat-card-mobile">
                        <h6 class="text-muted mb-3">Estado</h6>
                        <span class="badge status-${estado.estado} fs-6">${estado.estado.toUpperCase()}</span>
                    </div>
                </div>
            </div>
            <div class="col-md-4">
                <div class="card stat-card shadow-corporate">
                    <div class="card-body text-center stat-card-mobile">
                        <h6 class="text-muted mb-3">Completitud</h6>
                        <h2 class="text-corporate-primary">${estado.porcentaje_completitud.toFixed(0)}%</h2>
                    </div>
                </div>
            </div>
            <div class="col-md-4">
                <div class="card stat-card shadow-corporate">
                    <div class="card-body text-center stat-card-mobile">
                        <h6 class="text-muted mb-3">Documentos</h6>
                        <h2 class="text-corporate-secondary">${estado.documentos_presentes.length}/${estado.documentos_requeridos.length}</h2>
                    </div>
                </div>
            </div>
        </div>
        
        <div class="mt-4 actions-mobile">
            <div class="btn-group-corporate d-flex gap-2 flex-wrap">
                <button class="btn btn-primary btn-corporate" onclick="sincronizarSGD()">
                    <i class="bi bi-arrow-repeat me-2"></i>Sincronizar SGD
                </button>
                <button class="btn btn-success btn-corporate" onclick="procesarDespacho()">
                    <i class="bi bi-gear me-2"></i>Procesar
                </button>
            </div>
        </div>
    `;
}

function mostrarDetalleDocumentos(documentos) {
    let html = `
        <div class="d-flex justify-content-between align-items-center mb-3 flex-wrap gap-2">
            <h4 class="text-corporate-secondary mb-0">
                <i class="bi bi-file-text me-2"></i>Documentos del Despacho
            </h4>
            <button class="btn btn-success btn-corporate" data-bs-toggle="modal" data-bs-target="#uploadModal">
                <i class="bi bi-cloud-upload me-2"></i>
                <span class="d-none d-sm-inline">Subir Documentos</span>
                <span class="d-inline d-sm-none">Subir</span>
            </button>
        </div>
    `;
    
    if (documentos.length === 0) {
        html += `
            <div class="text-center py-5">
                <i class="bi bi-file-text fs-1 text-muted"></i>
                <p class="text-muted mt-2">No hay documentos cargados</p>
            </div>
        `;
    } else {
        html += '<div class="row">';
        documentos.forEach(doc => {
            html += `
                <div class="col-md-6 mb-3">
                    <div class="card card-responsive shadow-corporate">
                        <div class="card-body">
                            <div class="d-flex justify-content-between align-items-start mb-2">
                                <h6 class="text-corporate-secondary mb-0">${doc.tipo_documento.replace(/_/g, ' ').toUpperCase()}</h6>
                                <span class="badge ${doc.procesado ? 'bg-success' : 'bg-warning'}">
                                    ${doc.procesado ? 'Procesado' : 'Pendiente'}
                                </span>
                            </div>
                            <p class="text-muted small mb-3">${doc.nombre_archivo}</p>
                            <div class="btn-group-corporate d-flex gap-2 flex-wrap">
                                <button class="btn btn-sm btn-primary btn-sm-corporate" onclick="verDocumento(${doc.id})">
                                    <i class="bi bi-eye me-1"></i>Ver PDF
                                </button>
                                ${!doc.procesado ? `
                                    <button class="btn btn-sm btn-success btn-sm-corporate" onclick="procesarDocumentoIndividual(${doc.id})">
                                        <i class="bi bi-gear me-1"></i>Procesar
                                    </button>
                                ` : `
                                    <button class="btn btn-sm btn-info btn-sm-corporate" onclick="procesarDocumentoIndividual(${doc.id})">
                                        <i class="bi bi-arrow-repeat me-1"></i>Reprocesar
                                    </button>
                                `}
                            </div>
                        </div>
                    </div>
                </div>
            `;
        });
        html += '</div>';
    }
    
    document.getElementById('documentos').innerHTML = html;
}

function mostrarDetalleDatos(datos) {
    if (!datos.datos_extraidos || Object.keys(datos.datos_extraidos).length === 0) {
        document.getElementById('datos').innerHTML = `
            <div class="text-center py-5">
                <i class="bi bi-database fs-1 text-muted"></i>
                <p class="text-muted mt-2">No hay datos procesados</p>
            </div>
        `;
        return;
    }
    
    let html = '<div class="accordion" id="datosAccordion">';
    let index = 0;
    
    for (const [tipo, datosDoc] of Object.entries(datos.datos_extraidos)) {
        html += `
            <div class="accordion-item border-radius-corporate mb-2">
                <h2 class="accordion-header">
                    <button class="accordion-button ${index > 0 ? 'collapsed' : ''}" type="button" 
                            data-bs-toggle="collapse" data-bs-target="#collapse${index}">
                        <i class="bi bi-file-text me-2"></i>
                        ${tipo.replace(/_/g, ' ').toUpperCase()}
                    </button>
                </h2>
                <div id="collapse${index}" class="accordion-collapse collapse ${index === 0 ? 'show' : ''}" 
                     data-bs-parent="#datosAccordion">
                    <div class="accordion-body">
        `;
        
        if (datosDoc.all_fields) {
            html += '<div class="table-responsive table-responsive-mobile">';
            html += '<table class="table table-sm table-mobile">';
            for (const [key, value] of Object.entries(datosDoc.all_fields)) {
                if (value) {
                    html += `<tr><td class="fw-bold">${key}:</td><td>${value}</td></tr>`;
                }
            }
            html += '</table></div>';
        }
        
        html += '</div></div></div>';
        index++;
    }
    
    html += '</div>';
    document.getElementById('datos').innerHTML = html;
}

// ==================== ACTIONS ====================
function volverALista() {
    document.getElementById('despachosList').classList.remove('d-none');
    document.getElementById('despachoDetail').classList.add('d-none');
    document.getElementById('btnVolver').classList.add('d-none');
    despachoSeleccionado = null;
    document.getElementById('searchInput').value = '';
}

function verDespacho(numero) {
    seleccionarDespacho(numero);
}

function verDocumento(docId) {
    window.open(`/api/despachos/${despachoSeleccionado}/documento/${docId}/pdf`, '_blank');
}

async function procesarDocumentoIndividual(docId) {
    if (!despachoSeleccionado) return;
    
    try {
        showAlert('Procesando documento...', 'info');
        
        const response = await fetch(`/api/despachos/${despachoSeleccionado}/documento/${docId}/procesar`, {
            method: 'POST'
        });
        
        if (!response.ok) {
            const error = await response.json();
            throw new Error(error.error || 'Error procesando documento');
        }
        
        const result = await response.json();
        showAlert('Documento procesado exitosamente', 'success');
        
        // Reload despacho details to show updated state
        await cargarDetalleDespacho(despachoSeleccionado);
        
    } catch (error) {
        console.error('Error:', error);
        showAlert('Error procesando documento: ' + error.message, 'error');
    }
}

async function sincronizarSGD() {
    if (!despachoSeleccionado) return;
    
    try {
        showAlert('Sincronizando con SGD...', 'info');
        const response = await fetch(`/api/despachos/${despachoSeleccionado}/sgd`);
        const result = await response.json();
        
        showAlert(`Sincronización completada. ${result.total || 0} documentos importados.`, 'success');
        await cargarDetalleDespacho(despachoSeleccionado);
    } catch (error) {
        showAlert('Error en la sincronización: ' + error.message, 'error');
    }
}

async function procesarDespacho() {
    if (!despachoSeleccionado) return;
    
    try {
        showAlert('Procesando documentos...', 'info');
        const response = await fetch(`/api/despachos/${despachoSeleccionado}/procesar`, { method: 'POST' });
        const result = await response.json();
        
        showAlert(`Procesamiento completado. ${result.total_procesados} documentos procesados.`, 'success');
        await cargarDetalleDespacho(despachoSeleccionado);
    } catch (error) {
        showAlert('Error en el procesamiento: ' + error.message, 'error');
    }
}

async function buscarDespachoEspecifico() {
    const numero = document.getElementById('searchInput').value.trim();
    if (!numero) {
        showAlert('Ingrese un número de despacho', 'warning');
        return;
    }
    
    try {
        const response = await fetch(`/api/despachos/${numero}/estado`);
        
        if (response.status === 404) {
            if (confirm(`El despacho ${numero} no existe. ¿Desea importarlo desde SGD?`)) {
                showAlert('Importando desde SGD...', 'info');
                const sgdResponse = await fetch(`/api/despachos/${numero}/sgd`);
                
                if (sgdResponse.ok) {
                    const result = await sgdResponse.json();
                    showAlert(`Importación completada. ${result.total || 0} documentos importados.`, 'success');
                    await cargarDespachos(currentPage);
                    await seleccionarDespacho(numero);
                } else {
                    showAlert('Error importando desde SGD', 'error');
                }
            }
            return;
        }
        
        if (response.ok) {
            await seleccionarDespacho(numero);
        }
        
    } catch (error) {
        showAlert('Error: ' + error.message, 'error');
    }
}

function nuevoDespacho() {
    const modal = new bootstrap.Modal(document.getElementById('nuevoDespachoModal'));
    modal.show();
}

async function subirArchivo() {
    if (!archivoSeleccionado || !despachoSeleccionado) {
        showAlert('Selecciona un archivo primero', 'warning');
        return;
    }
    
    const tipoDocumento = document.getElementById('tipoDocumento').value;
    const formData = new FormData();
    formData.append('file', archivoSeleccionado);
    formData.append('tipo_documento', tipoDocumento);
    
    try {
        document.getElementById('uploadProgress').style.width = '50%';
        document.getElementById('uploadBtn').disabled = true;
        
        // Cambiar texto del botón según tipo
        if (tipoDocumento === 'automatico') {
            document.getElementById('uploadBtn').innerHTML = 
                '<i class="bi bi-cpu me-2"></i>Procesando con AI...';
        } else {
            document.getElementById('uploadBtn').innerHTML = 
                '<i class="bi bi-clock me-2"></i>Subiendo...';
        }
        
        const response = await fetch(`/api/despachos/${despachoSeleccionado}/documento/subir`, {
            method: 'POST',
            body: formData
        });
        
        document.getElementById('uploadProgress').style.width = '100%';
        
        if (response.ok) {
            const result = await response.json();
            
            if (tipoDocumento === 'automatico') {
                // Mostrar resultados del procesamiento automático
                let mensaje = `Procesamiento automático completado.<br>`;
                mensaje += `Se identificaron ${result.total_documentos} documento(s):<br>`;
                
                if (result.documentos) {
                    result.documentos.forEach(doc => {
                        mensaje += `• ${doc.tipo} (páginas ${doc.paginas})<br>`;
                    });
                }
                
                showAlert(mensaje, 'success', 5000); // Mostrar por más tiempo
            } else {
                showAlert('Documento subido exitosamente', 'success');
            }
            
            bootstrap.Modal.getInstance(document.getElementById('uploadModal')).hide();
            await cargarDetalleDespacho(despachoSeleccionado);
        } else {
            const error = await response.text();
            showAlert('Error: ' + error, 'error');
        }
        
    } catch (error) {
        showAlert('Error: ' + error.message, 'error');
    } finally {
        document.getElementById('uploadBtn').disabled = false;
        document.getElementById('uploadBtn').innerHTML = '<i class="bi bi-upload me-2"></i>Subir Documento';
        document.getElementById('uploadProgress').style.width = '0%';
        document.getElementById('filePreview').classList.add('d-none');
        document.getElementById('fileInput').value = '';
        archivoSeleccionado = null;
    }
}

// Agregar funciones para exportar datos
async function exportarJSON() {
    if (!despachoSeleccionado) return;
    
    try {
        const response = await fetch(`/api/despachos/${despachoSeleccionado}/exportar/json`);
        
        if (response.ok) {
            const data = await response.json();
            
            // Crear blob y descargar
            const blob = new Blob([JSON.stringify(data, null, 2)], 
                                 { type: 'application/json' });
            const url = window.URL.createObjectURL(blob);
            const a = document.createElement('a');
            a.href = url;
            a.download = `despacho_${despachoSeleccionado}.json`;
            document.body.appendChild(a);
            a.click();
            document.body.removeChild(a);
            window.URL.revokeObjectURL(url);
            
            showAlert('JSON exportado exitosamente', 'success');
        } else {
            showAlert('Error exportando JSON', 'error');
        }
    } catch (error) {
        showAlert('Error: ' + error.message, 'error');
    }
}

async function exportarExcel() {
    if (!despachoSeleccionado) return;
    
    try {
        showAlert('Generando Excel...', 'info');
        
        const response = await fetch(`/api/despachos/${despachoSeleccionado}/exportar/excel`);
        
        if (response.ok) {
            const blob = await response.blob();
            const url = window.URL.createObjectURL(blob);
            const a = document.createElement('a');
            a.href = url;
            a.download = `DIN_${despachoSeleccionado}.xlsx`;
            document.body.appendChild(a);
            a.click();
            document.body.removeChild(a);
            window.URL.revokeObjectURL(url);
            
            showAlert('Excel exportado exitosamente', 'success');
        } else {
            showAlert('Error exportando Excel', 'error');
        }
    } catch (error) {
        showAlert('Error: ' + error.message, 'error');
    }
}

function mostrarError(mensaje) {
    document.getElementById('despachosTableBody').innerHTML = 
        `<tr><td colspan="7" class="text-center text-danger py-4">${mensaje}</td></tr>`;
}

// ==================== EVENT LISTENERS ====================

// New despacho form submission
document.getElementById('nuevoDespachoForm').addEventListener('submit', async function(e) {
    e.preventDefault();
    
    const numero = document.getElementById('nuevoNumero').value;
    
    try {
        const response = await fetch('/api/despachos/crear', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                numero_despacho: numero,
                extra_metadata: {}
            })
        });
        
        if (!response.ok) throw new Error('Error creando despacho');
        
        bootstrap.Modal.getInstance(document.getElementById('nuevoDespachoModal')).hide();
        document.getElementById('nuevoDespachoForm').reset();
        
        showAlert('Despacho creado exitosamente', 'success');
        
        await cargarDespachos(currentPage);
        await seleccionarDespacho(numero);
        
    } catch (error) {
        showAlert('Error: ' + error.message, 'error');
    }
});

function showAlert(message, type = 'info', duration = 3000) {
    const alertDiv = document.createElement('div');
    alertDiv.className = `alert alert-${type === 'error' ? 'danger' : type} alert-dismissible fade show position-fixed top-0 start-50 translate-middle-x mt-3`;
    alertDiv.style.zIndex = '9999';
    alertDiv.innerHTML = `
        ${message}
        <button type="button" class="btn-close" data-bs-dismiss="alert"></button>
    `;
    
    document.body.appendChild(alertDiv);
    
    setTimeout(() => {
        alertDiv.remove();
    }, duration);
}

// Enter key for search
document.getElementById('searchInput').addEventListener('keypress', function(e) {
    if (e.key === 'Enter') buscarDespachoEspecifico();
});