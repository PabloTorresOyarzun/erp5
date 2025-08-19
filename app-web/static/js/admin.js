// Admin Panel JavaScript
// User management and database explorer functionality

// ==================== GLOBAL VARIABLES ====================
let allUsers = [];
let dbSchemas = [];
let currentTable = null;
let currentSchema = null;
let currentPage = 1;
let currentPageSize = 50;

// ==================== INITIALIZATION ====================
document.addEventListener('DOMContentLoaded', function() {
    loadUsers();
    
    // Event listener for tab changes
    const tabs = document.querySelectorAll('#adminTabs button[data-bs-toggle="tab"]');
    tabs.forEach(tab => {
        tab.addEventListener('shown.bs.tab', function(event) {
            const target = event.target.getAttribute('data-bs-target');
            
            // Show/hide buttons according to active tab
            if (target === '#users-pane') {
                document.getElementById('newUserBtn').style.display = 'block';
                document.getElementById('refreshDbBtn').style.display = 'none';
            } else if (target === '#database-pane') {
                document.getElementById('newUserBtn').style.display = 'none';
                document.getElementById('refreshDbBtn').style.display = 'block';
                
                // Load database explorer if not loaded
                if (dbSchemas.length === 0) {
                    loadDatabaseExplorer();
                }
            }
        });
    });
});

// ==================== USER MANAGEMENT ====================
async function loadUsers() {
    try {
        const response = await fetch('/api/admin/users');
        
        if (!response.ok) {
            throw new Error('Error cargando usuarios');
        }
        
        const users = await response.json();
        allUsers = users;
        
        displayUsers(users);
        updateStats(users);
        
    } catch (error) {
        console.error('Error:', error);
        showAlert('Error cargando usuarios. Por favor, recarga la página.', 'error');
        document.getElementById('usersTableBody').innerHTML = 
            '<tr><td colspan="5" class="text-center text-danger py-4">Error cargando usuarios</td></tr>';
    }
}

function displayUsers(users) {
    const tbody = document.getElementById('usersTableBody');
    
    if (users.length === 0) {
        tbody.innerHTML = '<tr><td colspan="5" class="text-center py-4">No hay usuarios</td></tr>';
        return;
    }
    
    tbody.innerHTML = users.map(user => `
        <tr>
            <td>
                <strong class="text-corporate-primary">${user.username}</strong>
                <div class="d-md-none">
                    <small class="text-muted">${user.email || 'N/A'}</small>
                </div>
                <div class="d-lg-none mt-1">
                    ${user.groups ? user.groups.map(group => 
                        `<span class="badge bg-secondary me-1">${group.split('/')[1] || group}</span>`
                    ).join(' ') : ''}
                </div>
            </td>
            <td class="d-none d-md-table-cell">${user.email || 'N/A'}</td>
            <td class="d-none d-lg-table-cell">
                ${user.groups ? user.groups.map(group => 
                    `<span class="badge bg-secondary me-1">${group}</span>`
                ).join(' ') : ''}
            </td>
            <td><span class="badge bg-success">Activo</span></td>
            <td>
                <div class="btn-group-corporate">
                    <button class="btn btn-sm btn-primary btn-sm-corporate me-1" onclick="editUser('${user.username}')" title="Editar">
                        <i class="bi bi-pencil"></i>
                    </button>
                    <button class="btn btn-sm btn-danger btn-sm-corporate" onclick="deleteUser('${user.username}')" title="Eliminar">
                        <i class="bi bi-trash"></i>
                    </button>
                </div>
            </td>
        </tr>
    `).join('');
}

function updateStats(users) {
    document.getElementById('totalUsers').textContent = users.length;
    document.getElementById('activeUsers').textContent = users.length;
}

function filterUsers() {
    const input = document.getElementById('searchInput');
    const filter = input.value.toLowerCase();
    
    const filteredUsers = allUsers.filter(user => {
        const searchText = `${user.username} ${user.email} ${(user.groups || []).join(' ')}`.toLowerCase();
        return searchText.includes(filter);
    });
    
    displayUsers(filteredUsers);
}

async function editUser(username) {
    try {
        const response = await fetch(`/api/admin/users/${username}`);
        
        if (!response.ok) {
            throw new Error('Error obteniendo datos del usuario');
        }
        
        const user = await response.json();
        
        document.getElementById('modalTitle').innerHTML = '<i class="bi bi-pencil me-2"></i>Editar Usuario';
        document.getElementById('editMode').value = 'true';
        document.getElementById('originalUsername').value = username;
        document.getElementById('username').value = user.username;
        document.getElementById('email').value = user.email || '';
        document.getElementById('firstName').value = user.firstName || '';
        document.getElementById('lastName').value = user.lastName || '';
        
        const groupsSelect = document.getElementById('groups');
        const userGroups = user.groups || [];
        
        Array.from(groupsSelect.options).forEach(option => {
            option.selected = userGroups.includes(option.value);
        });
        
        document.getElementById('password').required = false;
        document.getElementById('passwordHint').textContent = '(dejar en blanco para mantener la actual)';
        
        const modal = new bootstrap.Modal(document.getElementById('userModal'));
        modal.show();
        
    } catch (error) {
        showAlert('Error cargando datos del usuario', 'error');
    }
}

async function deleteUser(username) {
    if (!confirm(`¿Está seguro de eliminar al usuario ${username}?`)) {
        return;
    }
    
    try {
        const response = await fetch(`/api/admin/users/${username}`, {
            method: 'DELETE'
        });
        
        if (!response.ok) {
            const error = await response.json();
            throw new Error(error.error || 'Error eliminando usuario');
        }
        
        showAlert('Usuario eliminado exitosamente', 'success');
        loadUsers();
        
    } catch (error) {
        showAlert(error.message, 'error');
    }
}

// ==================== DATABASE EXPLORER ====================
async function loadDatabaseExplorer() {
    try {
        // Load statistics
        await loadDatabaseStats();
        
        // Load schemas and tables
        const response = await fetch('/api/db/schemas');
        
        if (!response.ok) {
            throw new Error('Error cargando esquemas de base de datos');
        }
        
        dbSchemas = await response.json();
        displayDatabaseTree(dbSchemas);
        
    } catch (error) {
        console.error('Error:', error);
        showAlert('Error cargando base de datos', 'error');
        document.getElementById('databaseTree').innerHTML = 
            '<div class="list-group-item text-center text-danger">Error cargando base de datos</div>';
    }
}

async function loadDatabaseStats() {
    try {
        const response = await fetch('/api/db/stats');
        
        if (response.ok) {
            const stats = await response.json();
            document.getElementById('dbSize').textContent = stats.database_size;
            document.getElementById('dbTables').textContent = stats.table_count;
            document.getElementById('dbConnections').textContent = stats.active_connections;
            document.getElementById('dbVersion').textContent = stats.postgresql_version.substring(0, 20);
        }
    } catch (error) {
        console.error('Error loading database stats:', error);
    }
}

function displayDatabaseTree(schemas) {
    const tree = document.getElementById('databaseTree');
    
    if (schemas.length === 0) {
        tree.innerHTML = '<div class="list-group-item text-center">No hay esquemas disponibles</div>';
        return;
    }
    
    let html = '';
    
    schemas.forEach(schema => {
        html += `
            <div class="list-group-item p-0">
                <div class="d-flex align-items-center p-2 fw-bold text-corporate-primary" 
                     style="cursor: pointer;" onclick="toggleSchema('${schema.name}')">
                    <i class="bi bi-chevron-right me-2 schema-toggle" id="toggle-${schema.name}"></i>
                    <i class="bi bi-database me-2"></i>
                    ${schema.name} (${schema.total_tables})
                </div>
                <div class="schema-tables" id="tables-${schema.name}" style="display: none;">
        `;
        
        schema.tables.forEach(table => {
            html += `
                <div class="list-group-item ps-5 py-2 table-item" 
                     style="cursor: pointer; border-left: 3px solid transparent;"
                     onclick="selectTable('${schema.name}', '${table}')"
                     onmouseover="this.style.borderLeftColor='var(--primary-color)'"
                     onmouseout="this.style.borderLeftColor='transparent'">
                    <i class="bi bi-table me-2 text-muted"></i>
                    ${table}
                </div>
            `;
        });
        
        html += '</div></div>';
    });
    
    tree.innerHTML = html;
}

function toggleSchema(schemaName) {
    const tablesDiv = document.getElementById(`tables-${schemaName}`);
    const toggleIcon = document.getElementById(`toggle-${schemaName}`);
    
    if (tablesDiv.style.display === 'none') {
        tablesDiv.style.display = 'block';
        toggleIcon.className = 'bi bi-chevron-down me-2 schema-toggle';
    } else {
        tablesDiv.style.display = 'none';
        toggleIcon.className = 'bi bi-chevron-right me-2 schema-toggle';
    }
}

async function selectTable(schema, tableName) {
    currentTable = tableName;
    currentSchema = schema;
    
    // Update UI
    document.getElementById('contentTitle').innerHTML = 
        `<i class="bi bi-table me-2"></i>${schema}.${tableName}`;
    document.getElementById('contentActions').style.display = 'block';
    
    // Highlight selected table
    document.querySelectorAll('.table-item').forEach(item => {
        item.style.backgroundColor = '';
        item.style.fontWeight = '';
    });
    
    event.target.style.backgroundColor = '#e3f2fd';
    event.target.style.fontWeight = 'bold';
    
    // Load data by default
    showTableData();
}

async function showTableData() {
    if (!currentTable || !currentSchema) return;
    
    // Hide other views
    document.getElementById('defaultView').style.display = 'none';
    document.getElementById('tableInfoView').style.display = 'none';
    document.getElementById('tableSchemaView').style.display = 'none';
    
    // Show data view
    document.getElementById('tableDataView').style.display = 'block';
    
    await loadTableData(currentPage, currentPageSize);
}

async function loadTableData(page = 1, pageSize = 50) {
    try {
        const response = await fetch(
            `/api/db/table/${currentSchema}/${currentTable}/data?page=${page}&page_size=${pageSize}`
        );
        
        if (!response.ok) {
            throw new Error('Error cargando datos de la tabla');
        }
        
        const data = await response.json();
        displayTableData(data);
        
    } catch (error) {
        console.error('Error:', error);
        showAlert('Error cargando datos de la tabla', 'error');
        document.getElementById('dataTable').innerHTML = 
            '<tr><td colspan="100%" class="text-center text-danger">Error cargando datos</td></tr>';
    }
}

function displayTableData(data) {
    const table = document.getElementById('dataTable');
    const thead = table.querySelector('thead');
    const tbody = table.querySelector('tbody');
    
    // Update records info
    const start = (data.page - 1) * data.page_size + 1;
    const end = Math.min(data.page * data.page_size, data.total_rows);
    document.getElementById('recordsInfo').textContent = 
        `${start}-${end} de ${data.total_rows}`;
    
    // Generate headers
    thead.innerHTML = `
        <tr>
            ${data.columns.map(col => `<th>${col}</th>`).join('')}
        </tr>
    `;
    
    // Generate rows
    if (data.rows.length === 0) {
        tbody.innerHTML = `
            <tr>
                <td colspan="${data.columns.length}" class="text-center text-muted py-4">
                    No hay datos en esta tabla
                </td>
            </tr>
        `;
    } else {
        tbody.innerHTML = data.rows.map(row => `
            <tr>
                ${row.map(cell => `
                    <td style="max-width: 200px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap;" 
                        title="${cell || ''}">${cell || '<em class="text-muted">null</em>'}</td>
                `).join('')}
            </tr>
        `).join('');
    }
    
    // Update pagination
    updateTablePagination(data);
}

function updateTablePagination(data) {
    const pagination = document.getElementById('tablePagination');
    
    if (data.total_pages <= 1) {
        pagination.innerHTML = '';
        return;
    }
    
    let html = '';
    
    // Previous button
    html += `
        <li class="page-item ${data.page <= 1 ? 'disabled' : ''}">
            <a class="page-link" href="#" onclick="changePage(${data.page - 1})">
                <i class="bi bi-chevron-left"></i>
            </a>
        </li>
    `;
    
    // Pages
    const startPage = Math.max(1, data.page - 2);
    const endPage = Math.min(data.total_pages, data.page + 2);
    
    for (let i = startPage; i <= endPage; i++) {
        html += `
            <li class="page-item ${i === data.page ? 'active' : ''}">
                <a class="page-link" href="#" onclick="changePage(${i})">${i}</a>
            </li>
        `;
    }
    
    // Next button
    html += `
        <li class="page-item ${data.page >= data.total_pages ? 'disabled' : ''}">
            <a class="page-link" href="#" onclick="changePage(${data.page + 1})">
                <i class="bi bi-chevron-right"></i>
            </a>
        </li>
    `;
    
    pagination.innerHTML = html;
}

function changePage(page) {
    currentPage = page;
    loadTableData(currentPage, currentPageSize);
}

function changePageSize() {
    currentPageSize = parseInt(document.getElementById('pageSizeSelect').value);
    currentPage = 1;
    loadTableData(currentPage, currentPageSize);
}

async function showTableInfo() {
    if (!currentTable || !currentSchema) return;
    
    // Hide other views
    document.getElementById('defaultView').style.display = 'none';
    document.getElementById('tableDataView').style.display = 'none';
    document.getElementById('tableSchemaView').style.display = 'none';
    
    try {
        const response = await fetch(`/api/db/table/${currentSchema}/${currentTable}`);
        
        if (!response.ok) {
            throw new Error('Error cargando información de la tabla');
        }
        
        const info = await response.json();
        displayTableInfo(info);
        
    } catch (error) {
        console.error('Error:', error);
        showAlert('Error cargando información de la tabla', 'error');
        document.getElementById('tableInfoView').innerHTML = 
            '<div class="text-center text-danger">Error cargando información</div>';
    }
    
    document.getElementById('tableInfoView').style.display = 'block';
}

function displayTableInfo(info) {
    const infoView = document.getElementById('tableInfoView');
    
    let html = `
        <div class="row mb-4">
            <div class="col-lg-6 mb-4">
                <div class="table-info-section">
                    <h5><i class="bi bi-info-circle me-2"></i>Información General</h5>
                    <table class="table table-sm">
                        <tr><td><strong>Nombre:</strong></td><td>${info.name}</td></tr>
                        <tr><td><strong>Esquema:</strong></td><td>${info.schema}</td></tr>
                        <tr><td><strong>Filas:</strong></td><td>${info.row_count.toLocaleString()}</td></tr>
                        <tr><td><strong>Columnas:</strong></td><td>${info.columns.length}</td></tr>
                    </table>
                </div>
            </div>
            <div class="col-lg-6">
                <div class="table-info-section">
                    <h5><i class="bi bi-list-columns me-2"></i>Columnas</h5>
                    <div style="max-height: 300px; overflow-y: auto;">
                        <table class="table table-sm">
                            <thead>
                                <tr>
                                    <th>Nombre</th>
                                    <th>Tipo</th>
                                    <th>Nulo</th>
                                    <th>PK</th>
                                </tr>
                            </thead>
                            <tbody>
    `;
    
    info.columns.forEach(col => {
        const isPrimaryKey = col.primary_key || false;
        const pkIcon = isPrimaryKey ? '<i class="bi bi-key text-warning" title="Primary Key"></i>' : '';
        
        html += `
            <tr ${isPrimaryKey ? 'class="table-warning"' : ''}>
                <td><code>${col.name}</code> ${pkIcon}</td>
                <td><span class="column-type-badge">${col.type}</span></td>
                <td>${col.nullable ? '<span class="nullable-badge">Sí</span>' : '<span class="not-null-badge">No</span>'}</td>
                <td>${isPrimaryKey ? '<i class="bi bi-check-circle text-success"></i>' : ''}</td>
            </tr>
        `;
    });
    
    html += `
                            </tbody>
                        </table>
                    </div>
                </div>
            </div>
        </div>
    `;
    
    if (info.indexes && info.indexes.length > 0) {
        html += `
            <div class="table-info-section">
                <h5><i class="bi bi-speedometer me-2"></i>Índices</h5>
                <div class="row">
                    ${info.indexes.map(idx => `
                        <div class="col-md-6 mb-2">
                            <div class="card card-body">
                                <small class="text-muted">Índice</small>
                                <strong>${idx}</strong>
                            </div>
                        </div>
                    `).join('')}
                </div>
            </div>
        `;
    }
    
    infoView.innerHTML = html;
}

async function showTableSchema() {
    if (!currentTable || !currentSchema) return;
    
    // Hide other views
    document.getElementById('defaultView').style.display = 'none';
    document.getElementById('tableDataView').style.display = 'none';
    document.getElementById('tableInfoView').style.display = 'none';
    
    try {
        const response = await fetch(`/api/db/table/${currentSchema}/${currentTable}/schema`);
        
        if (!response.ok) {
            throw new Error('Error cargando esquema de la tabla');
        }
        
        const schema = await response.json();
        document.getElementById('schemaCode').textContent = schema.sql_definition;
        
    } catch (error) {
        console.error('Error:', error);
        showAlert('Error cargando esquema de la tabla', 'error');
        document.getElementById('schemaCode').textContent = 'Error cargando esquema';
    }
    
    document.getElementById('tableSchemaView').style.display = 'block';
}

async function executeQuery() {
    const query = document.getElementById('sqlQuery').value.trim();
    
    if (!query) {
        showAlert('Por favor, ingrese una consulta SQL', 'warning');
        return;
    }
    
    try {
        const response = await fetch('/api/db/query', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({ query: query })
        });
        
        if (!response.ok) {
            const error = await response.json();
            throw new Error(error.detail || 'Error ejecutando consulta');
        }
        
        const result = await response.json();
        displayQueryResult(result);
        
    } catch (error) {
        showAlert('Error: ' + error.message, 'error');
    }
}

function displayQueryResult(result) {
    const resultDiv = document.getElementById('queryResult');
    const statsDiv = document.getElementById('queryStats');
    const table = document.getElementById('queryResultTable');
    
    // Show statistics
    statsDiv.textContent = `${result.affected_rows} filas - ${result.execution_time.toFixed(3)}s`;
    
    // Generate table
    const thead = table.querySelector('thead');
    const tbody = table.querySelector('tbody');
    
    if (result.columns.length === 0) {
        thead.innerHTML = '';
        tbody.innerHTML = '<tr><td class="text-center text-muted">No hay resultados</td></tr>';
    } else {
        thead.innerHTML = `
            <tr>
                ${result.columns.map(col => `<th>${col}</th>`).join('')}
            </tr>
        `;
        
        tbody.innerHTML = result.rows.map(row => `
            <tr>
                ${row.map(cell => `<td>${cell || '<em class="text-muted">null</em>'}</td>`).join('')}
            </tr>
        `).join('');
    }
    
    resultDiv.style.display = 'block';
}

function refreshDatabaseExplorer() {
    dbSchemas = [];
    loadDatabaseExplorer();
}

// ==================== EVENT LISTENERS ====================

// Reset form when modal opens for new user
document.getElementById('userModal').addEventListener('show.bs.modal', function (event) {
    if (!document.getElementById('editMode').value || document.getElementById('editMode').value === 'false') {
        document.getElementById('modalTitle').innerHTML = '<i class="bi bi-person-plus me-2"></i>Nuevo Usuario';
        document.getElementById('userForm').reset();
        document.getElementById('editMode').value = 'false';
        document.getElementById('password').required = true;
        document.getElementById('passwordHint').textContent = '';
    }
});

// Handle form submission
document.getElementById('userForm').addEventListener('submit', async function(e) {
    e.preventDefault();
    
    const isEditMode = document.getElementById('editMode').value === 'true';
    const originalUsername = document.getElementById('originalUsername').value;
    
    const formData = {
        username: document.getElementById('username').value,
        email: document.getElementById('email').value,
        firstName: document.getElementById('firstName').value,
        lastName: document.getElementById('lastName').value,
        groups: Array.from(document.getElementById('groups').selectedOptions).map(opt => opt.value)
    };
    
    if (!isEditMode || document.getElementById('password').value) {
        formData.password = document.getElementById('password').value;
    }
    
    try {
        const url = isEditMode 
            ? `/api/admin/users/${originalUsername}`
            : '/api/admin/users';
            
        const method = isEditMode ? 'PUT' : 'POST';
        
        const response = await fetch(url, {
            method: method,
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify(formData)
        });
        
        if (!response.ok) {
            const error = await response.json();
            throw new Error(error.error || 'Error guardando usuario');
        }
        
        showAlert(
            isEditMode ? 'Usuario actualizado exitosamente' : 'Usuario creado exitosamente',
            'success'
        );
        
        bootstrap.Modal.getInstance(document.getElementById('userModal')).hide();
        loadUsers();
        
    } catch (error) {
        showAlert(error.message, 'error');
    }
});