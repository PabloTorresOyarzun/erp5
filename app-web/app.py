from flask import Flask, redirect, url_for, session, render_template, request, jsonify, Response
import requests
import os
from datetime import timedelta
from functools import wraps

app = Flask(__name__, static_folder='static', static_url_path='/static')
app.secret_key = os.getenv('FLASK_SECRET_KEY', 'dev-secret-key')
app.permanent_session_lifetime = timedelta(hours=10)

# Configurar sesiones más seguras
app.config['SESSION_COOKIE_SECURE'] = False  # True en producción con HTTPS
app.config['SESSION_COOKIE_HTTPONLY'] = True
app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'

# URL de las APIs
AUTH_API_URL = 'http://api-keycloak:8000'
DOC_API_URL = 'http://api-docs:8002'
DESPACHOS_API_URL = os.getenv('DESPACHOS_API_URL', 'http://api-despachos:8003')
DB_API_URL = "http://api-database:8004"

# ==================== MANEJADORES DE ERRORES ====================

@app.errorhandler(404)
def handle_404(e):
    """Manejar páginas no encontradas - redirigir al index"""
    # Si la ruta es una API, devolver JSON
    if request.path.startswith('/api/'):
        return jsonify({"error": "Endpoint no encontrado"}), 404
    
    # Para rutas web, redirigir al index
    return redirect(url_for('index'))

@app.errorhandler(403)
def handle_403(e):
    """Manejar acceso denegado"""
    if request.path.startswith('/api/'):
        return jsonify({"error": "Acceso denegado"}), 403
    
    return render_template('error.html', 
                         error="No tienes permisos para acceder a esta página",
                         code=403), 403

@app.errorhandler(500)
def handle_500(e):
    """Manejar errores internos del servidor"""
    if request.path.startswith('/api/'):
        return jsonify({"error": "Error interno del servidor"}), 500
    
    return render_template('error.html', 
                         error="Ha ocurrido un error interno. Por favor, intenta nuevamente más tarde.",
                         code=500), 500

@app.errorhandler(Exception)
def handle_exception(e):
    """Manejar excepciones no capturadas"""
    # Log del error para debugging
    app.logger.error(f'Excepción no manejada: {e}', exc_info=True)
    
    if request.path.startswith('/api/'):
        return jsonify({"error": "Error inesperado"}), 500
    
    # Para rutas web que no sean críticas, redirigir al index
    if request.path not in ['/login', '/callback', '/logout']:
        return redirect(url_for('index'))
    
    return render_template('error.html', 
                         error="Ha ocurrido un error inesperado",
                         code=500), 500

# ==================== DECORADORES ====================

def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user' not in session:
            return redirect(url_for('index'))
        return f(*args, **kwargs)
    return decorated_function

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

def group_required(*groups):
    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            if 'user' not in session:
                return redirect(url_for('index'))
            
            user_groups = session.get('user', {}).get('groups', [])
            allowed = False
            for user_group in user_groups:
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

# ==================== RUTAS PRINCIPALES ====================

@app.route('/')
def index():
    """Página de presentación principal"""
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

# ==================== API ENDPOINTS - DESPACHOS ====================

@app.route('/api/despachos')
@login_required
def api_listar_despachos():
    """API: Listar despachos con paginación"""
    try:
        limit = request.args.get('limit', 25, type=int)
        offset = request.args.get('offset', 0, type=int)
        search = request.args.get('search', '')
        
        params = {
            'limit': limit,
            'offset': offset
        }
        
        if search:
            params['search'] = search
        
        response = requests.get(
            f"{DESPACHOS_API_URL}/despachos",
            params=params,
            timeout=30
        )
        
        if response.status_code == 200:
            return jsonify(response.json())
        else:
            return jsonify({"error": "Error obteniendo despachos"}), response.status_code
            
    except requests.exceptions.RequestException as e:
        app.logger.error(f'Error conectando con API despachos: {e}')
        return jsonify({"error": "Error de conexión con el servicio"}), 503
    except Exception as e:
        app.logger.error(f'Error en api_listar_despachos: {e}')
        return jsonify({"error": "Error interno"}), 500

@app.route('/api/despachos/<numero>/estado')
@login_required
def api_despacho_estado(numero):
    """Obtener estado de un despacho"""
    try:
        response = requests.get(f"{DESPACHOS_API_URL}/despachos/{numero}/estado", timeout=30)
        
        if response.status_code == 200:
            return jsonify(response.json())
        else:
            return jsonify({"error": "Despacho no encontrado"}), response.status_code
            
    except requests.exceptions.RequestException as e:
        app.logger.error(f'Error conectando con API despachos: {e}')
        return jsonify({"error": "Error de conexión"}), 503
    except Exception as e:
        app.logger.error(f'Error en api_despacho_estado: {e}')
        return jsonify({"error": "Error interno"}), 500

@app.route('/api/despachos/<numero>/documentos')
@login_required
def api_despacho_documentos(numero):
    """Obtener documentos de un despacho"""
    try:
        response = requests.get(f"{DESPACHOS_API_URL}/despachos/{numero}/documentos", timeout=30)
        
        if response.status_code == 200:
            return jsonify(response.json())
        else:
            return jsonify({"error": "Error obteniendo documentos"}), response.status_code
            
    except requests.exceptions.RequestException as e:
        app.logger.error(f'Error conectando con API despachos: {e}')
        return jsonify({"error": "Error de conexión"}), 503
    except Exception as e:
        return jsonify({"error": "Error interno"}), 500

@app.route('/api/despachos/<numero>/datos')
@login_required
def api_despacho_datos(numero):
    """Obtener datos estructurados del despacho"""
    try:
        response = requests.get(f"{DESPACHOS_API_URL}/despachos/{numero}/datos", timeout=30)
        
        if response.status_code == 200:
            return jsonify(response.json())
        else:
            return jsonify({"error": "Error obteniendo datos"}), response.status_code
            
    except requests.exceptions.RequestException as e:
        return jsonify({"error": "Error de conexión"}), 503
    except Exception as e:
        return jsonify({"error": "Error interno"}), 500

@app.route('/api/despachos/<numero>/sgd')
@login_required
def api_despacho_sgd(numero):
    """Sincronizar con SGD"""
    try:
        response = requests.get(f"{DESPACHOS_API_URL}/despachos/{numero}/sgd", timeout=60)
        
        if response.status_code == 200:
            return jsonify(response.json())
        else:
            return jsonify(response.json()), response.status_code
            
    except requests.exceptions.RequestException as e:
        return jsonify({"error": "Error de conexión con SGD"}), 503
    except Exception as e:
        return jsonify({"error": "Error interno"}), 500

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
            headers=headers,
            timeout=300  # 5 minutos para procesamiento
        )
        
        if response.status_code == 200:
            return jsonify(response.json())
        else:
            return jsonify(response.json()), response.status_code
            
    except requests.exceptions.RequestException as e:
        return jsonify({"error": "Error de conexión"}), 503
    except Exception as e:
        return jsonify({"error": "Error interno"}), 500

@app.route('/api/despachos/<numero>/documento/<int:doc_id>/pdf')
@login_required
def api_documento_pdf(numero, doc_id):
    """Obtener PDF de un documento"""
    try:
        response = requests.get(
            f"{DESPACHOS_API_URL}/despachos/{numero}/documento/{doc_id}/pdf",
            stream=True,
            timeout=30
        )
        
        if response.status_code == 200:
            return Response(
                response.iter_content(chunk_size=8192),
                headers=dict(response.headers),
                status=response.status_code
            )
        else:
            return jsonify({"error": "Documento no encontrado"}), 404
            
    except requests.exceptions.RequestException as e:
        return jsonify({"error": "Error de conexión"}), 503
    except Exception as e:
        return jsonify({"error": "Error interno"}), 500

@app.route('/api/despachos/crear', methods=['POST'])
@login_required
def api_crear_despacho():
    """Crear nuevo despacho"""
    try:
        data = request.json
        
        response = requests.post(
            f"{DESPACHOS_API_URL}/despachos/crear",
            json=data,
            timeout=30
        )
        
        if response.status_code == 200:
            return jsonify(response.json())
        else:
            return jsonify(response.json()), response.status_code
            
    except requests.exceptions.RequestException as e:
        return jsonify({"error": "Error de conexión"}), 503
    except Exception as e:
        return jsonify({"error": "Error interno"}), 500

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
        
        # Leer el archivo en memoria
        file_content = file.read()
        
        # Crear los archivos y datos para enviar
        files = {'file': (file.filename, file_content, file.mimetype)}
        data = {'tipo_documento': tipo_documento}
        
        # IMPORTANTE: La URL debe tener el número de despacho en la ruta, NO como query parameter
        response = requests.post(
            f"{DESPACHOS_API_URL}/despachos/{numero}/documento/subir",
            files=files,
            data=data,
            timeout=120
        )
        
        if response.status_code == 200:
            return jsonify(response.json())
        else:
            try:
                error_detail = response.json()
                return jsonify(error_detail), response.status_code
            except:
                return jsonify({"error": f"Error subiendo documento: {response.status_code}"}), response.status_code
            
    except requests.exceptions.RequestException as e:
        app.logger.error(f"Error de conexión: {str(e)}")
        return jsonify({"error": "Error de conexión con el servidor"}), 503
    except Exception as e:
        app.logger.error(f"Error interno: {str(e)}")
        return jsonify({"error": f"Error interno: {str(e)}"}), 500

@app.route('/api/despachos/<numero>/documento/<int:doc_id>/procesar', methods=['POST'])
@login_required
def api_procesar_documento_individual(numero, doc_id):
    """Procesar documento individual"""
    try:
        token = session.get('tokens', {}).get('access_token')
        headers = {'Authorization': f'Bearer {token}'}
        
        response = requests.post(
            f"{DESPACHOS_API_URL}/despachos/{numero}/documento/{doc_id}/procesar",
            headers=headers,
            timeout=120  # 2 minutos para procesamiento
        )
        
        if response.status_code == 200:
            return jsonify(response.json())
        else:
            return jsonify(response.json()), response.status_code
            
    except requests.exceptions.RequestException as e:
        return jsonify({"error": "Error de conexión"}), 503
    except Exception as e:
        return jsonify({"error": "Error interno"}), 500

# ==================== AUTENTICACIÓN ====================

@app.route('/login')
def login():
    """Iniciar proceso de login con Keycloak"""
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
            },
            timeout=30
        )
        
        if response.status_code == 200:
            login_url = response.json()['login_url']
            return redirect(login_url)
        else:
            return render_template('error.html', 
                                 error="Error obteniendo URL de login",
                                 code=500), 500
            
    except requests.exceptions.RequestException as e:
        app.logger.error(f'Error conectando con servicio de autenticación: {e}')
        return render_template('error.html', 
                             error="Error conectando con el servicio de autenticación",
                             code=503), 503
    except Exception as e:
        app.logger.error(f'Error en login: {e}')
        return render_template('error.html', 
                             error="Error inesperado en login",
                             code=500), 500

@app.route('/callback')
def callback():
    """Procesar callback de Keycloak"""
    state = request.args.get('state')
    if state != session.get('oauth_state'):
        return render_template('error.html', 
                             error="Estado de autenticación inválido",
                             code=400), 400
    
    session.pop('oauth_state', None)
    
    code = request.args.get('code')
    if not code:
        return render_template('error.html', 
                             error="Código de autorización no encontrado",
                             code=400), 400
    
    try:
        response = requests.post(
            f"{AUTH_API_URL}/auth/exchange-code",
            json={
                'code': code,
                'redirect_uri': 'http://localhost:5000/callback'
            },
            timeout=30
        )
        
        if response.status_code == 200:
            data = response.json()
            
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
            
    except requests.exceptions.RequestException as e:
        app.logger.error(f'Error en callback: {e}')
        return render_template('error.html', 
                             error="Error conectando con el servicio de autenticación",
                             code=503), 503
    except Exception as e:
        app.logger.error(f'Error procesando callback: {e}')
        return render_template('error.html', 
                             error="Error procesando autenticación",
                             code=500), 500

@app.route('/logout')
def logout():
    """Cerrar sesión"""
    session.clear()
    session.permanent = False
    session.modified = True
    
    try:
        response = requests.get(
            f"{AUTH_API_URL}/auth/logout-url",
            params={'redirect_uri': 'http://localhost:5000/'},
            timeout=10
        )
        
        if response.status_code == 200:
            logout_url = response.json()['logout_url']
            return redirect(logout_url)
    except:
        pass
    
    return redirect(url_for('index'))

# ==================== API ENDPOINTS - USUARIOS ====================

@app.route('/api/admin/users')
@group_required('gerencia', 'informatico')
def api_get_users():
    """API: Obtener lista de usuarios"""
    try:
        admin_token = session.get('tokens', {}).get('access_token')
        
        response = requests.get(
            f"{AUTH_API_URL}/admin/users",
            headers={'Authorization': f'Bearer {admin_token}'},
            timeout=30
        )
        
        if response.status_code == 200:
            return jsonify(response.json())
        else:
            return jsonify({"error": "Error obteniendo usuarios"}), response.status_code
            
    except requests.exceptions.RequestException as e:
        return jsonify({"error": "Error de conexión"}), 503
    except Exception as e:
        return jsonify({"error": "Error interno"}), 500

@app.route('/api/admin/users/<username>')
@group_required('gerencia', 'informatico')
def api_get_user(username):
    """API: Obtener detalles de un usuario"""
    try:
        admin_token = session.get('tokens', {}).get('access_token')
        
        response = requests.get(
            f"{AUTH_API_URL}/admin/users/{username}",
            headers={'Authorization': f'Bearer {admin_token}'},
            timeout=30
        )
        
        if response.status_code == 200:
            return jsonify(response.json())
        else:
            return jsonify({"error": "Usuario no encontrado"}), 404
            
    except requests.exceptions.RequestException as e:
        return jsonify({"error": "Error de conexión"}), 503
    except Exception as e:
        return jsonify({"error": "Error interno"}), 500

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
            headers={'Authorization': f'Bearer {admin_token}'},
            timeout=30
        )
        
        if response.status_code in [200, 201]:
            return jsonify({"message": "Usuario creado exitosamente", "data": response.json()})
        else:
            return jsonify({"error": response.json().get('detail', 'Error creando usuario')}), response.status_code
            
    except requests.exceptions.RequestException as e:
        return jsonify({"error": "Error de conexión"}), 503
    except Exception as e:
        return jsonify({"error": "Error interno"}), 500

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
            headers={'Authorization': f'Bearer {admin_token}'},
            timeout=30
        )
        
        if response.status_code == 200:
            return jsonify({"message": "Usuario actualizado exitosamente"})
        else:
            return jsonify({"error": response.json().get('detail', 'Error actualizando usuario')}), response.status_code
            
    except requests.exceptions.RequestException as e:
        return jsonify({"error": "Error de conexión"}), 503
    except Exception as e:
        return jsonify({"error": "Error interno"}), 500

@app.route('/api/admin/users/<username>', methods=['DELETE'])
@group_required('gerencia', 'informatico')
def api_delete_user(username):
    """API: Eliminar usuario - solo gerencia puede eliminar"""
    user = session.get('user')
    user_groups = user.get('groups', [])
    
    is_gerencia = any('gerencia' in group for group in user_groups)
    if not is_gerencia:
        return jsonify({"error": "Solo el grupo de gerencia puede eliminar usuarios"}), 403
    
    try:
        admin_token = session.get('tokens', {}).get('access_token')
        
        response = requests.delete(
            f"{AUTH_API_URL}/admin/users/{username}",
            headers={'Authorization': f'Bearer {admin_token}'},
            timeout=30
        )
        
        if response.status_code in [200, 204]:
            return jsonify({"message": "Usuario eliminado exitosamente"})
        else:
            return jsonify({"error": response.json().get('detail', 'Error eliminando usuario')}), response.status_code
            
    except requests.exceptions.RequestException as e:
        return jsonify({"error": "Error de conexión"}), 503
    except Exception as e:
        return jsonify({"error": "Error interno"}), 500

# ==================== API ENDPOINTS - BASE DE DATOS ====================

@app.route('/api/db/schemas')
@group_required('gerencia', 'informatico')
def api_db_schemas():
    """API: Obtener esquemas de la base de datos"""
    try:
        response = requests.get(f"{DB_API_URL}/db/schemas", timeout=30)
        
        if response.status_code == 200:
            return jsonify(response.json())
        else:
            return jsonify({"error": "Error obteniendo esquemas"}), response.status_code
            
    except requests.exceptions.RequestException as e:
        return jsonify({"error": "Error de conexión con base de datos"}), 503
    except Exception as e:
        return jsonify({"error": "Error interno"}), 500

@app.route('/api/db/table/<schema>/<table_name>')
@group_required('gerencia', 'informatico')
def api_db_table_info(schema, table_name):
    """API: Obtener información de una tabla"""
    try:
        response = requests.get(f"{DB_API_URL}/db/table/{schema}/{table_name}", timeout=30)
        
        if response.status_code == 200:
            return jsonify(response.json())
        else:
            return jsonify({"error": "Error obteniendo información de tabla"}), response.status_code
            
    except requests.exceptions.RequestException as e:
        return jsonify({"error": "Error de conexión"}), 503
    except Exception as e:
        return jsonify({"error": "Error interno"}), 500

@app.route('/api/db/table/<schema>/<table_name>/data')
@group_required('gerencia', 'informatico')
def api_db_table_data(schema, table_name):
    """API: Obtener datos de una tabla"""
    try:
        params = {
            'page': request.args.get('page', 1, type=int),
            'page_size': request.args.get('page_size', 50, type=int),
            'order_by': request.args.get('order_by'),
            'order_direction': request.args.get('order_direction', 'ASC')
        }
        
        response = requests.get(
            f"{DB_API_URL}/db/table/{schema}/{table_name}/data",
            params=params,
            timeout=60
        )
        
        if response.status_code == 200:
            return jsonify(response.json())
        else:
            return jsonify({"error": "Error obteniendo datos de tabla"}), response.status_code
            
    except requests.exceptions.RequestException as e:
        return jsonify({"error": "Error de conexión"}), 503
    except Exception as e:
        return jsonify({"error": "Error interno"}), 500

@app.route('/api/db/table/<schema>/<table_name>/schema')
@group_required('gerencia', 'informatico')
def api_db_table_schema(schema, table_name):
    """API: Obtener esquema SQL de una tabla"""
    try:
        response = requests.get(f"{DB_API_URL}/db/table/{schema}/{table_name}/schema", timeout=30)
        
        if response.status_code == 200:
            return jsonify(response.json())
        else:
            return jsonify({"error": "Error obteniendo esquema de tabla"}), response.status_code
            
    except requests.exceptions.RequestException as e:
        return jsonify({"error": "Error de conexión"}), 503
    except Exception as e:
        return jsonify({"error": "Error interno"}), 500

@app.route('/api/db/query', methods=['POST'])
@group_required('gerencia', 'informatico')
def api_db_query():
    """API: Ejecutar consulta SQL personalizada"""
    try:
        query_data = request.json
        
        response = requests.post(
            f"{DB_API_URL}/db/query",
            json=query_data,
            timeout=120
        )
        
        if response.status_code == 200:
            return jsonify(response.json())
        else:
            error_data = response.json()
            return jsonify({"error": error_data.get('detail', 'Error ejecutando consulta')}), response.status_code
            
    except requests.exceptions.RequestException as e:
        return jsonify({"error": "Error de conexión"}), 503
    except Exception as e:
        return jsonify({"error": "Error interno"}), 500

@app.route('/api/db/stats')
@group_required('gerencia', 'informatico')
def api_db_stats():
    """API: Obtener estadísticas de la base de datos"""
    try:
        response = requests.get(f"{DB_API_URL}/db/stats", timeout=30)
        
        if response.status_code == 200:
            return jsonify(response.json())
        else:
            return jsonify({"error": "Error obteniendo estadísticas"}), response.status_code
            
    except requests.exceptions.RequestException as e:
        return jsonify({"error": "Error de conexión"}), 503
    except Exception as e:
        return jsonify({"error": "Error interno"}), 500

# ==================== FUNCIONES AUXILIARES ====================

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

# ==================== CONTEXT PROCESSORS ====================

@app.context_processor
def inject_user():
    user = session.get('user')
    return dict(
        current_user=user,
        is_admin_group=is_admin_group(user) if user else False,
        request=request
    )

@app.after_request
def after_request(response):
    """Prevenir caché en páginas dinámicas"""
    if request.endpoint not in ['static']:
        response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate, private"
        response.headers["Pragma"] = "no-cache"
        response.headers["Expires"] = "0"
    return response

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=int(os.getenv('FLASK_PORT', 5000)), debug=True)