from flask import Flask, redirect, url_for, session, render_template, request, jsonify, Response
import requests
import os
from datetime import timedelta
from functools import wraps

app = Flask(__name__)
app = Flask(__name__, static_folder='static', static_url_path='/static')
app.secret_key = os.getenv('FLASK_SECRET_KEY', 'dev-secret-key')
app.permanent_session_lifetime = timedelta(hours=10)

# Configurar sesiones más seguras
app.config['SESSION_COOKIE_SECURE'] = False  # True en producción con HTTPS
app.config['SESSION_COOKIE_HTTPONLY'] = True
app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'

# URL de las APIs
AUTH_API_URL = 'http://keycloak-init:8000'
DOC_API_URL = 'http://api-docs:8002'
DESPACHOS_API_URL = os.getenv('DESPACHOS_API_URL', 'http://api-despachos:8003')

# Decorador para requerir autenticación
def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user' not in session:
            return redirect(url_for('index'))
        return f(*args, **kwargs)
    return decorated_function

# Decorador para requerir roles específicos
def role_required(*roles):
    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            if 'user' not in session:
                return redirect(url_for('index'))
            
            user_roles = session.get('user', {}).get('roles', [])
            if not any(role in user_roles for role in roles):
                return render_template('error.html', 
                                     error="No tienes permisos para acceder a esta página",
                                     code=403), 403
            return f(*args, **kwargs)
        return decorated_function
    return decorator

# Decorador para requerir grupos específicos
def group_required(*groups):
    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            if 'user' not in session:
                return redirect(url_for('index'))
            
            user_groups = session.get('user', {}).get('groups', [])
            # Verificar si el usuario pertenece a alguno de los grupos permitidos
            # Los grupos vienen como "Agencia/gerencia", "Agencia/informatico", etc.
            allowed = False
            for user_group in user_groups:
                # Extraer el subgrupo del path completo
                if '/' in user_group:
                    _, subgroup = user_group.split('/', 1)
                    if subgroup in groups:
                        allowed = True
                        break
            
            if not allowed:
                return render_template('error.html', 
                                     error="No tienes permisos para acceder a esta página. Solo los grupos de gerencia e informático tienen acceso.",
                                     code=403), 403
            
            return f(*args, **kwargs)
        return decorated_function
    return decorator

@app.route('/')
def index():
    """Página de presentación principal"""
    # Asegurar que no haya sesión residual en la página de presentación
    # a menos que el usuario haya navegado intencionalmente aquí estando logueado
    return render_template('index.html')

@app.route('/dashboard')
@login_required
def dashboard():
    """Dashboard principal para usuarios autenticados"""
    user = session.get('user')
    return render_template('dashboard.html', user=user)

@app.route('/admin')
@group_required('gerencia', 'informatico')
def admin():
    """Panel de administración solo para gerencia e informático"""
    user = session.get('user')
    return render_template('admin.html', user=user)

@app.route('/user')
@login_required
def user_profile():
    """Perfil del usuario"""
    user = session.get('user')
    return render_template('user.html', user=user)

@app.route('/despachos')
@login_required
def despachos():
    """Vista de gestión de despachos"""
    user = session.get('user')
    return render_template('despachos.html', user=user)


@app.route('/api/despachos')
@login_required
def api_listar_despachos():
    """API: Listar despachos con paginación"""
    try:
        # Obtener parámetros de query
        limit = request.args.get('limit', 25, type=int)
        offset = request.args.get('offset', 0, type=int)
        search = request.args.get('search', '')
        
        # Construir URL con parámetros
        params = {
            'limit': limit,
            'offset': offset
        }
        
        if search:
            params['search'] = search
        
        response = requests.get(
            f"{DESPACHOS_API_URL}/despachos",
            params=params
        )
        
        if response.status_code == 200:
            return jsonify(response.json())
        else:
            return jsonify({"error": "Error obteniendo despachos"}), response.status_code
            
    except Exception as e:
        return jsonify({"error": str(e)}), 500
 
# API endpoints para despachos
@app.route('/api/despachos/<numero>/estado')
@login_required
def api_despacho_estado(numero):
    """Obtener estado de un despacho"""
    try:
        response = requests.get(f"{DESPACHOS_API_URL}/despachos/{numero}/estado")
        
        if response.status_code == 200:
            return jsonify(response.json())
        else:
            return jsonify({"error": "Despacho no encontrado"}), response.status_code
            
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/api/despachos/<numero>/documentos')
@login_required
def api_despacho_documentos(numero):
    """Obtener documentos de un despacho"""
    try:
        response = requests.get(f"{DESPACHOS_API_URL}/despachos/{numero}/documentos")
        
        if response.status_code == 200:
            return jsonify(response.json())
        else:
            return jsonify({"error": "Error obteniendo documentos"}), response.status_code
            
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/api/despachos/<numero>/datos')
@login_required
def api_despacho_datos(numero):
    """Obtener datos estructurados del despacho"""
    try:
        response = requests.get(f"{DESPACHOS_API_URL}/despachos/{numero}/datos")
        
        if response.status_code == 200:
            return jsonify(response.json())
        else:
            return jsonify({"error": "Error obteniendo datos"}), response.status_code
            
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/api/despachos/<numero>/sgd')
@login_required
def api_despacho_sgd(numero):
    """Sincronizar con SGD"""
    try:
        response = requests.get(f"{DESPACHOS_API_URL}/despachos/{numero}/sgd")
        
        if response.status_code == 200:
            return jsonify(response.json())
        else:
            return jsonify(response.json()), response.status_code
            
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/api/despachos/<numero>/procesar', methods=['POST'])
@login_required
def api_procesar_despacho(numero):
    """Procesar documentos del despacho"""
    try:
        forzar = request.args.get('forzar', 'false').lower() == 'true'
        token = session.get('tokens', {}).get('access_token')
        
        headers = {'Authorization': f'Bearer {token}'}
        
        response = requests.post(
            f"{DESPACHOS_API_URL}/despachos/{numero}/procesar?forzar={forzar}",
            headers=headers
        )
        
        if response.status_code == 200:
            return jsonify(response.json())
        else:
            return jsonify(response.json()), response.status_code
            
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/api/despachos/<numero>/documento/<int:doc_id>/pdf')
@login_required
def api_documento_pdf(numero, doc_id):
    """Obtener PDF de un documento"""
    try:
        response = requests.get(
            f"{DESPACHOS_API_URL}/despachos/{numero}/documento/{doc_id}/pdf",
            stream=True
        )
        
        if response.status_code == 200:
            return Response(
                response.iter_content(chunk_size=8192),
                headers=dict(response.headers),
                status=response.status_code
            )
        else:
            return jsonify({"error": "Documento no encontrado"}), 404
            
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/api/despachos/crear', methods=['POST'])
@login_required
def api_crear_despacho():
    """Crear nuevo despacho"""
    try:
        data = request.json
        
        response = requests.post(
            f"{DESPACHOS_API_URL}/despachos/crear",
            json=data
        )
        
        if response.status_code == 200:
            return jsonify(response.json())
        else:
            return jsonify(response.json()), response.status_code
            
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/api/despachos/documento/subir', methods=['POST'])
@login_required
def api_subir_documento():
    """Subir documento a un despacho"""
    try:
        data = request.json
        
        response = requests.post(
            f"{DESPACHOS_API_URL}/despachos/documento/subir",
            json=data
        )
        
        if response.status_code == 200:
            return jsonify(response.json())
        else:
            return jsonify(response.json()), response.status_code
            
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/api/despachos/<numero>/documento/subir', methods=['POST'])
@login_required
def api_subir_documento_file(numero):
    """Subir documento con archivo"""
    try:
        if 'file' not in request.files:
            return jsonify({"error": "No se encontró archivo"}), 400
        
        file = request.files['file']
        tipo_documento = request.form.get('tipo_documento', 'general')
        
        if file.filename == '':
            return jsonify({"error": "No se seleccionó archivo"}), 400
        
        # Preparar para enviar
        files = {'file': (file.filename, file.stream, file.mimetype)}
        
        response = requests.post(
            f"{DESPACHOS_API_URL}/despachos/documento/subir",
            files=files,
            params={
                'numero_despacho': numero,
                'tipo_documento': tipo_documento
            }
        )
        
        if response.status_code == 200:
            return jsonify(response.json())
        else:
            return jsonify({"error": "Error subiendo documento"}), response.status_code
            
    except Exception as e:
        return jsonify({"error": str(e)}), 500

# API endpoints para documentos (legacy - mantener por compatibilidad)
@app.route('/api/documents/process/<doc_type>', methods=['POST'])
@login_required
def api_process_document(doc_type):
    """API: Procesar documento (factura o transporte)"""
    if doc_type not in ['invoice', 'transport']:
        return jsonify({"error": "Tipo de documento inválido"}), 400
    
    if 'file' not in request.files:
        return jsonify({"error": "No se encontró archivo"}), 400
    
    file = request.files['file']
    if file.filename == '':
        return jsonify({"error": "No se seleccionó archivo"}), 400
    
    try:
        # Obtener token del usuario
        token = session.get('tokens', {}).get('access_token')
        
        # Preparar archivo para enviar
        files = {'file': (file.filename, file.stream, file.mimetype)}
        headers = {'Authorization': f'Bearer {token}'}
        
        # Enviar a API de procesamiento
        response = requests.post(
            f"{DOC_API_URL}/process/{doc_type}",
            files=files,
            headers=headers
        )
        
        if response.status_code == 200:
            return jsonify(response.json())
        else:
            return jsonify({"error": response.json().get('detail', 'Error procesando documento')}), response.status_code
            
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/api/documents/history')
@login_required
def api_documents_history():
    """API: Obtener historial de documentos procesados"""
    try:
        token = session.get('tokens', {}).get('access_token')
        headers = {'Authorization': f'Bearer {token}'}
        
        # Obtener parámetros de paginación
        limit = request.args.get('limit', 50, type=int)
        offset = request.args.get('offset', 0, type=int)
        
        response = requests.get(
            f"{DOC_API_URL}/history",
            params={'limit': limit, 'offset': offset},
            headers=headers
        )
        
        if response.status_code == 200:
            return jsonify(response.json())
        else:
            return jsonify({"error": "Error obteniendo historial"}), response.status_code
            
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/api/documents/download/<process_id>/<format>')
@login_required
def api_download_document(process_id, format):
    """API: Descargar documento procesado"""
    if format not in ['json', 'excel']:
        return jsonify({"error": "Formato inválido"}), 400
    
    try:
        token = session.get('tokens', {}).get('access_token')
        headers = {'Authorization': f'Bearer {token}'}
        
        response = requests.get(
            f"{DOC_API_URL}/download/{process_id}/{format}",
            headers=headers,
            stream=True
        )
        
        if response.status_code == 200:
            # Reenviar la respuesta al cliente
            return Response(
                response.iter_content(chunk_size=8192),
                headers=dict(response.headers),
                status=response.status_code
            )
        else:
            return jsonify({"error": "Documento no encontrado"}), 404
            
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/api/documents/delete/<process_id>', methods=['DELETE'])
@login_required
def api_delete_document(process_id):
    """API: Eliminar documento del historial"""
    try:
        token = session.get('tokens', {}).get('access_token')
        headers = {'Authorization': f'Bearer {token}'}
        
        response = requests.delete(
            f"{DOC_API_URL}/history/{process_id}",
            headers=headers
        )
        
        if response.status_code == 200:
            return jsonify({"message": "Documento eliminado exitosamente"})
        else:
            return jsonify({"error": "Error eliminando documento"}), response.status_code
            
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/login')
def login():
    """Iniciar proceso de login con Keycloak"""
    # Si ya está logueado, redirigir al dashboard
    if 'user' in session:
        return redirect(url_for('dashboard'))
    
    import secrets
    state = secrets.token_urlsafe(32)
    session['oauth_state'] = state
    
    try:
        response = requests.get(
            f"{AUTH_API_URL}/auth/login-url",
            params={
                'redirect_uri': 'http://localhost:5000/callback',
                'state': state
            }
        )
        
        if response.status_code == 200:
            login_url = response.json()['login_url']
            return redirect(login_url)
        else:
            return render_template('error.html', 
                                 error="Error obteniendo URL de login",
                                 code=500), 500
            
    except Exception as e:
        return render_template('error.html', 
                             error=f"Error conectando con el servicio de autenticación: {str(e)}",
                             code=500), 500

@app.route('/callback')
def callback():
    """Procesar callback de Keycloak"""
    state = request.args.get('state')
    if state != session.get('oauth_state'):
        return render_template('error.html', 
                             error="Estado inválido",
                             code=400), 400
    
    # Limpiar estado OAuth
    session.pop('oauth_state', None)
    
    code = request.args.get('code')
    if not code:
        return render_template('error.html', 
                             error="Código no encontrado",
                             code=400), 400
    
    try:
        response = requests.post(
            f"{AUTH_API_URL}/auth/exchange-code",
            json={
                'code': code,
                'redirect_uri': 'http://localhost:5000/callback'
            }
        )
        
        if response.status_code == 200:
            data = response.json()
            
            # Limpiar cualquier sesión previa antes de establecer la nueva
            session.clear()
            
            session.permanent = True
            session['user'] = data['user_info']
            session['tokens'] = data['tokens']
            
            return redirect(url_for('dashboard'))
        else:
            error_detail = response.json().get('detail', 'Error desconocido')
            return render_template('error.html', 
                                 error=f"Error en autenticación: {error_detail}",
                                 code=500), 500
            
    except Exception as e:
        return render_template('error.html', 
                             error=f"Error: {str(e)}",
                             code=500), 500

@app.route('/logout')
def logout():
    """Cerrar sesión"""
    # Limpiar completamente la sesión
    session.clear()
    session.permanent = False
    
    # Forzar nueva sesión
    session.modified = True
    
    try:
        response = requests.get(
            f"{AUTH_API_URL}/auth/logout-url",
            params={'redirect_uri': 'http://localhost:5000/'}
        )
        
        if response.status_code == 200:
            logout_url = response.json()['logout_url']
            return redirect(logout_url)
    except:
        pass
    
    # Si falla, al menos redirigir al inicio
    return redirect(url_for('index'))

# API endpoints
@app.route('/api/user-info')
@login_required
def api_user_info():
    """API: Información del usuario actual"""
    user = session.get('user')
    return jsonify({
        "username": user.get('username'),
        "email": user.get('email'),
        "roles": user.get('roles', []),
        "groups": user.get('groups', [])
    })

@app.route('/api/validate-permission/<permission>')
@login_required
def api_validate_permission(permission):
    """API: Validar si el usuario tiene un permiso específico"""
    user = session.get('user')
    user_roles = user.get('roles', [])
    has_permission = permission in user_roles
    
    return jsonify({
        "permission": permission,
        "granted": has_permission,
        "user_roles": user_roles
    })

# Helper function para verificar si el usuario pertenece a grupos de administración
def is_admin_group(user):
    """Verificar si el usuario pertenece a grupos con acceso administrativo"""
    if not user:
        return False
    
    user_groups = user.get('groups', [])
    admin_groups = ['gerencia', 'informatico']
    
    for user_group in user_groups:
        if '/' in user_group:
            _, subgroup = user_group.split('/', 1)
            if subgroup in admin_groups:
                return True
    return False

# CRUD de usuarios - todos requieren pertenecer a grupos administrativos
@app.route('/api/admin/users')
@group_required('gerencia', 'informatico')
def api_get_users():
    """API: Obtener lista de usuarios"""
    try:
        # Obtener token de administrador
        admin_token = session.get('tokens', {}).get('access_token')
        
        response = requests.get(
            f"{AUTH_API_URL}/admin/users",
            headers={'Authorization': f'Bearer {admin_token}'}
        )
        
        if response.status_code == 200:
            return jsonify(response.json())
        else:
            return jsonify({"error": "Error obteniendo usuarios"}), response.status_code
            
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/api/admin/users/<username>')
@group_required('gerencia', 'informatico')
def api_get_user(username):
    """API: Obtener detalles de un usuario"""
    try:
        admin_token = session.get('tokens', {}).get('access_token')
        
        response = requests.get(
            f"{AUTH_API_URL}/admin/users/{username}",
            headers={'Authorization': f'Bearer {admin_token}'}
        )
        
        if response.status_code == 200:
            return jsonify(response.json())
        else:
            return jsonify({"error": "Usuario no encontrado"}), 404
            
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/api/admin/users', methods=['POST'])
@group_required('gerencia', 'informatico')
def api_create_user():
    """API: Crear nuevo usuario"""
    try:
        admin_token = session.get('tokens', {}).get('access_token')
        user_data = request.json
        
        response = requests.post(
            f"{AUTH_API_URL}/admin/users",
            json=user_data,
            headers={'Authorization': f'Bearer {admin_token}'}
        )
        
        if response.status_code in [200, 201]:
            return jsonify({"message": "Usuario creado exitosamente", "data": response.json()})
        else:
            return jsonify({"error": response.json().get('detail', 'Error creando usuario')}), response.status_code
            
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/api/admin/users/<username>', methods=['PUT'])
@group_required('gerencia', 'informatico')
def api_update_user(username):
    """API: Actualizar usuario"""
    try:
        admin_token = session.get('tokens', {}).get('access_token')
        user_data = request.json
        
        response = requests.put(
            f"{AUTH_API_URL}/admin/users/{username}",
            json=user_data,
            headers={'Authorization': f'Bearer {admin_token}'}
        )
        
        if response.status_code == 200:
            return jsonify({"message": "Usuario actualizado exitosamente"})
        else:
            return jsonify({"error": response.json().get('detail', 'Error actualizando usuario')}), response.status_code
            
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/api/admin/users/<username>', methods=['DELETE'])
@group_required('gerencia', 'informatico')
def api_delete_user(username):
    """API: Eliminar usuario - solo gerencia puede eliminar"""
    user = session.get('user')
    user_groups = user.get('groups', [])
    
    # Solo gerencia puede eliminar usuarios
    is_gerencia = any('gerencia' in group for group in user_groups)
    if not is_gerencia:
        return jsonify({"error": "Solo el grupo de gerencia puede eliminar usuarios"}), 403
    
    try:
        admin_token = session.get('tokens', {}).get('access_token')
        
        response = requests.delete(
            f"{AUTH_API_URL}/admin/users/{username}",
            headers={'Authorization': f'Bearer {admin_token}'}
        )
        
        if response.status_code in [200, 204]:
            return jsonify({"message": "Usuario eliminado exitosamente"})
        else:
            return jsonify({"error": response.json().get('detail', 'Error eliminando usuario')}), response.status_code
            
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/api/admin/groups')
@group_required('gerencia', 'informatico')
def api_get_groups():
    """API: Obtener lista de grupos"""
    try:
        admin_token = session.get('tokens', {}).get('access_token')
        
        response = requests.get(
            f"{AUTH_API_URL}/admin/groups",
            headers={'Authorization': f'Bearer {admin_token}'}
        )
        
        if response.status_code == 200:
            return jsonify(response.json())
        else:
            return jsonify({"error": "Error obteniendo grupos"}), response.status_code
            
    except Exception as e:
        return jsonify({"error": str(e)}), 500

# Context processor para inyectar user en todos los templates
@app.context_processor
def inject_user():
    user = session.get('user')
    return dict(
        current_user=user,
        is_admin_group=is_admin_group(user) if user else False,
        request=request
    )

# Asegurar que las sesiones se manejen correctamente
@app.after_request
def after_request(response):
    # Prevenir caché en páginas dinámicas
    if request.endpoint not in ['static']:
        response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate, private"
        response.headers["Pragma"] = "no-cache"
        response.headers["Expires"] = "0"
    return response

# ==================== API ENDPOINTS PARA EXPLORADOR DE BASE DE DATOS ====================

# URL de la API de base de datos
DB_API_URL = "http://api-database:8004"

@app.route('/api/db/schemas')
@group_required('gerencia', 'informatico')
def api_db_schemas():
    """API: Obtener esquemas de la base de datos"""
    try:
        response = requests.get(f"{DB_API_URL}/db/schemas")
        
        if response.status_code == 200:
            return jsonify(response.json())
        else:
            return jsonify({"error": "Error obteniendo esquemas"}), response.status_code
            
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/api/db/table/<schema>/<table_name>')
@group_required('gerencia', 'informatico')
def api_db_table_info(schema, table_name):
    """API: Obtener información de una tabla"""
    try:
        response = requests.get(f"{DB_API_URL}/db/table/{schema}/{table_name}")
        
        if response.status_code == 200:
            return jsonify(response.json())
        else:
            return jsonify({"error": "Error obteniendo información de tabla"}), response.status_code
            
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/api/db/table/<schema>/<table_name>/data')
@group_required('gerencia', 'informatico')
def api_db_table_data(schema, table_name):
    """API: Obtener datos de una tabla"""
    try:
        # Pasar todos los parámetros de query
        params = {
            'page': request.args.get('page', 1, type=int),
            'page_size': request.args.get('page_size', 50, type=int),
            'order_by': request.args.get('order_by'),
            'order_direction': request.args.get('order_direction', 'ASC')
        }
        
        response = requests.get(
            f"{DB_API_URL}/db/table/{schema}/{table_name}/data",
            params=params
        )
        
        if response.status_code == 200:
            return jsonify(response.json())
        else:
            return jsonify({"error": "Error obteniendo datos de tabla"}), response.status_code
            
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/api/db/table/<schema>/<table_name>/schema')
@group_required('gerencia', 'informatico')
def api_db_table_schema(schema, table_name):
    """API: Obtener esquema SQL de una tabla"""
    try:
        response = requests.get(f"{DB_API_URL}/db/table/{schema}/{table_name}/schema")
        
        if response.status_code == 200:
            return jsonify(response.json())
        else:
            return jsonify({"error": "Error obteniendo esquema de tabla"}), response.status_code
            
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/api/db/query', methods=['POST'])
@group_required('gerencia', 'informatico')
def api_db_query():
    """API: Ejecutar consulta SQL personalizada"""
    try:
        query_data = request.json
        
        response = requests.post(
            f"{DB_API_URL}/db/query",
            json=query_data
        )
        
        if response.status_code == 200:
            return jsonify(response.json())
        else:
            error_data = response.json()
            return jsonify({"error": error_data.get('detail', 'Error ejecutando consulta')}), response.status_code
            
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/api/db/stats')
@group_required('gerencia', 'informatico')
def api_db_stats():
    """API: Obtener estadísticas de la base de datos"""
    try:
        response = requests.get(f"{DB_API_URL}/db/stats")
        
        if response.status_code == 200:
            return jsonify(response.json())
        else:
            return jsonify({"error": "Error obteniendo estadísticas"}), response.status_code
            
    except Exception as e:
        return jsonify({"error": str(e)}), 500

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=int(os.getenv('FLASK_PORT', 5000)), debug=True)