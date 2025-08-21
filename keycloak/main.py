from fastapi import FastAPI, HTTPException, Header
from pydantic import BaseModel
import requests
import os
import base64
import json
import time
import asyncio
from typing import Optional

app = FastAPI()

# Variables de entorno
KEYCLOAK_URL = os.getenv('KEYCLOAK_URL', 'http://keycloak:8080')
KEYCLOAK_ADMIN = os.getenv('KEYCLOAK_ADMIN', 'admin')
KEYCLOAK_ADMIN_PASSWORD = os.getenv('KEYCLOAK_ADMIN_PASSWORD', 'admin')
REALM = os.getenv('REALM', 'myrealm')
CLIENT_ID = os.getenv('CLIENT_ID', 'flask-app')
CLIENT_SECRET = os.getenv('CLIENT_SECRET', 'secret')
TEST_USERNAME = os.getenv('TEST_USERNAME', 'test')
TEST_PASSWORD = os.getenv('TEST_PASSWORD', 'test123')
TEST_EMAIL = os.getenv('TEST_EMAIL', 'test@example.com')

# Definición de estructura organizacional
ROLES = ['read', 'write', 'update', 'delete', 'approve']

GROUPS_STRUCTURE = {
    'Agencia': [
        'gerencia',
        'informatico',
        'recursos humanos',
        'finanzas',
        'facturacion',
        'exportacion',
        'importacion',
        'operaciones'
    ],
    'Clientes': [
        'clientePrueba'
    ]
}

# Modelos Pydantic
class LoginRequest(BaseModel):
    username: str
    password: str

class TokenRequest(BaseModel):
    code: str
    redirect_uri: str

class UserInfo(BaseModel):
    username: str
    email: str
    roles: list
    groups: list

# ==================== FUNCIONES DE INICIALIZACIÓN ====================

def wait_for_keycloak():
    """Esperar a que Keycloak esté listo"""
    print("Esperando a Keycloak...")
    for i in range(120):  # Esperar hasta 4 minutos
        try:
            r = requests.get(f'{KEYCLOAK_URL}/')
            if r.status_code == 200:
                print("Keycloak listo!")
                time.sleep(5)  # Esperar un poco más para asegurar que esté completamente listo
                return True
        except:
            pass
        time.sleep(2)
    return False

def get_admin_token():
    """Obtener token de administrador"""
    token_url = f'{KEYCLOAK_URL}/realms/master/protocol/openid-connect/token'
    token_data = {
        'username': KEYCLOAK_ADMIN,
        'password': KEYCLOAK_ADMIN_PASSWORD,
        'grant_type': 'password',
        'client_id': 'admin-cli'
    }
    
    try:
        response = requests.post(token_url, data=token_data)
        if response.status_code == 200:
            return response.json()['access_token']
        else:
            print(f"Error obteniendo token admin: {response.status_code} - {response.text}")
    except Exception as e:
        print(f"Excepción obteniendo token admin: {e}")
    return None

def create_realm(headers):
    """Crear realm si no existe"""
    realm_check = requests.get(f'{KEYCLOAK_URL}/admin/realms/{REALM}', headers=headers)
    if realm_check.status_code == 404:
        realm_data = {
            'realm': REALM, 
            'enabled': True,
            'ssoSessionIdleTimeout': 36000,  # 10 horas
            'ssoSessionMaxLifespan': 36000,  # 10 horas
            'accessTokenLifespan': 3600,  # 1 hora
            'registrationAllowed': False,
            'loginWithEmailAllowed': True,
            'duplicateEmailsAllowed': False,
            'resetPasswordAllowed': False,
            'editUsernameAllowed': False,
            'bruteForceProtected': True
        }
        response = requests.post(f'{KEYCLOAK_URL}/admin/realms', json=realm_data, headers=headers)
        if response.status_code in [201, 204]:
            print(f"✅ Realm '{REALM}' creado")
            return True
        else:
            print(f"❌ Error creando realm: {response.status_code} - {response.text}")
    else:
        print(f"✅ Realm '{REALM}' ya existe")
    return True

def create_client(headers):
    """Crear cliente si no existe"""
    clients = requests.get(f'{KEYCLOAK_URL}/admin/realms/{REALM}/clients', headers=headers)
    if clients.status_code == 200:
        client_exists = False
        client_id = None
        
        for client in clients.json():
            if client['clientId'] == CLIENT_ID:
                client_exists = True
                client_id = client['id']
                break
        
        if not client_exists:
            client_data = {
                'clientId': CLIENT_ID,
                'secret': CLIENT_SECRET,
                'redirectUris': ['http://localhost:5000/*'],
                'webOrigins': ['http://localhost:5000'],
                'publicClient': False,
                'protocol': 'openid-connect',
                'enabled': True,
                'directAccessGrantsEnabled': True,
                'standardFlowEnabled': True,
                'attributes': {
                    'post.logout.redirect.uris': 'http://localhost:5000/*'
                }
            }
            response = requests.post(f'{KEYCLOAK_URL}/admin/realms/{REALM}/clients', 
                                   json=client_data, headers=headers)
            if response.status_code in [201, 204]:
                print(f"✅ Cliente '{CLIENT_ID}' creado")
                # Obtener el ID del cliente recién creado
                clients = requests.get(f'{KEYCLOAK_URL}/admin/realms/{REALM}/clients', headers=headers)
                for client in clients.json():
                    if client['clientId'] == CLIENT_ID:
                        client_id = client['id']
                        break
            else:
                print(f"❌ Error creando cliente: {response.status_code} - {response.text}")
        else:
            print(f"✅ Cliente '{CLIENT_ID}' ya existe")
        
        # Configurar mappers para el cliente (nuevo o existente)
        if client_id:
            time.sleep(2)  # Esperar un momento para que Keycloak propague los cambios
            configure_client_mappers(headers, client_id)
            
    return True

def configure_client_mappers(headers, client_id):
    """Configurar protocol mappers para incluir grupos y roles en el token"""
    # Obtener mappers existentes
    mappers_url = f'{KEYCLOAK_URL}/admin/realms/{REALM}/clients/{client_id}/protocol-mappers/models'
    existing_mappers = requests.get(mappers_url, headers=headers)
    
    existing_mapper_names = []
    if existing_mappers.status_code == 200:
        existing_mapper_names = [m['name'] for m in existing_mappers.json()]
    
    # Mapper para grupos
    if 'groups' not in existing_mapper_names:
        groups_mapper = {
            'name': 'groups',
            'protocol': 'openid-connect',
            'protocolMapper': 'oidc-group-membership-mapper',
            'consentRequired': False,
            'config': {
                'full.path': 'true',
                'id.token.claim': 'true',
                'access.token.claim': 'true',
                'claim.name': 'groups',
                'userinfo.token.claim': 'true'
            }
        }
        response = requests.post(mappers_url, json=groups_mapper, headers=headers)
        if response.status_code in [201, 204]:
            print("✅ Mapper de grupos configurado")
        else:
            print(f"❌ Error configurando mapper de grupos: {response.status_code}")
    
    # Mapper para roles del cliente
    if 'client-roles' not in existing_mapper_names:
        client_roles_mapper = {
            'name': 'client-roles',
            'protocol': 'openid-connect',
            'protocolMapper': 'oidc-usermodel-client-role-mapper',
            'consentRequired': False,
            'config': {
                'multivalued': 'true',
                'usermodel.clientRoleMapping.clientId': CLIENT_ID,
                'id.token.claim': 'true',
                'access.token.claim': 'true',
                'claim.name': 'roles',
                'userinfo.token.claim': 'true'
            }
        }
        response = requests.post(mappers_url, json=client_roles_mapper, headers=headers)
        if response.status_code in [201, 204]:
            print("✅ Mapper de roles del cliente configurado")
        else:
            print(f"❌ Error configurando mapper de roles: {response.status_code}")

def create_client_roles(headers):
    """Crear roles en el cliente"""
    # Obtener ID del cliente
    clients = requests.get(f'{KEYCLOAK_URL}/admin/realms/{REALM}/clients', headers=headers)
    client_id = None
    for client in clients.json():
        if client['clientId'] == CLIENT_ID:
            client_id = client['id']
            break
    
    if not client_id:
        print("❌ No se encontró el cliente")
        return False
    
    # Verificar y crear roles
    for role in ROLES:
        # Verificar si el rol existe
        role_check = requests.get(
            f'{KEYCLOAK_URL}/admin/realms/{REALM}/clients/{client_id}/roles/{role}', 
            headers=headers
        )
        
        if role_check.status_code == 404:
            role_data = {
                'name': role,
                'description': f'Permiso para {role}'
            }
            response = requests.post(
                f'{KEYCLOAK_URL}/admin/realms/{REALM}/clients/{client_id}/roles', 
                json=role_data, 
                headers=headers
            )
            if response.status_code in [201, 204]:
                print(f"✅ Rol '{role}' creado en cliente")
            else:
                print(f"❌ Error creando rol '{role}': {response.status_code}")
        else:
            print(f"✅ Rol '{role}' ya existe en cliente")
    
    return True

def create_groups(headers):
    """Crear estructura de grupos y subgrupos"""
    created_groups = {}
    
    for parent_group, subgroups in GROUPS_STRUCTURE.items():
        # Verificar si el grupo padre existe
        groups = requests.get(f'{KEYCLOAK_URL}/admin/realms/{REALM}/groups', headers=headers)
        parent_id = None
        
        if groups.status_code == 200:
            for group in groups.json():
                if group['name'] == parent_group:
                    parent_id = group['id']
                    break
        
        # Crear grupo padre si no existe
        if not parent_id:
            group_data = {'name': parent_group}
            response = requests.post(
                f'{KEYCLOAK_URL}/admin/realms/{REALM}/groups', 
                json=group_data, 
                headers=headers
            )
            if response.status_code in [201, 204]:
                print(f"✅ Grupo padre '{parent_group}' creado")
                # Obtener el ID del grupo recién creado
                time.sleep(2)  # Aumentar pausa para asegurar la creación
                groups = requests.get(f'{KEYCLOAK_URL}/admin/realms/{REALM}/groups', headers=headers)
                if groups.status_code == 200:
                    for group in groups.json():
                        if group['name'] == parent_group:
                            parent_id = group['id']
                            break
            else:
                print(f"❌ Error creando grupo '{parent_group}': {response.status_code}")
                continue
        else:
            print(f"✅ Grupo padre '{parent_group}' ya existe")
        
        created_groups[parent_group] = parent_id
        
        # Crear subgrupos
        if parent_id:
            for subgroup in subgroups:
                # Pausa entre creación de subgrupos
                time.sleep(0.5)
                
                # Verificar si el subgrupo existe
                parent_details = requests.get(
                    f'{KEYCLOAK_URL}/admin/realms/{REALM}/groups/{parent_id}', 
                    headers=headers
                )
                
                subgroup_exists = False
                if parent_details.status_code == 200:
                    subgroups_list = parent_details.json().get('subGroups', [])
                    subgroup_exists = any(sg['name'] == subgroup for sg in subgroups_list)
                
                if not subgroup_exists:
                    subgroup_data = {'name': subgroup}
                    response = requests.post(
                        f'{KEYCLOAK_URL}/admin/realms/{REALM}/groups/{parent_id}/children', 
                        json=subgroup_data, 
                        headers=headers
                    )
                    if response.status_code in [201, 204]:
                        print(f"✅ Subgrupo '{subgroup}' creado en '{parent_group}'")
                    else:
                        print(f"❌ Error creando subgrupo '{subgroup}': {response.status_code}")
                else:
                    print(f"✅ Subgrupo '{subgroup}' ya existe en '{parent_group}'")
    
    # Verificar que todos los subgrupos se crearon correctamente
    time.sleep(3)
    print("🔍 Verificando creación de grupos...")
    
    for parent_group, parent_id in created_groups.items():
        if parent_id:
            parent_details = requests.get(
                f'{KEYCLOAK_URL}/admin/realms/{REALM}/groups/{parent_id}', 
                headers=headers
            )
            if parent_details.status_code == 200:
                subgroups = parent_details.json().get('subGroups', [])
                print(f"  ✓ Grupo '{parent_group}' tiene {len(subgroups)} subgrupos")
    
    return True

def get_group_id_by_path(headers, group_path):
    """Obtener ID de un grupo por su path (ej: 'Agencia/informatico')"""
    parts = group_path.split('/')
    
    # Primero intentar obtener todos los grupos con search
    search_url = f'{KEYCLOAK_URL}/admin/realms/{REALM}/groups?search={parts[0]}&briefRepresentation=false'
    groups_response = requests.get(search_url, headers=headers)
    
    if groups_response.status_code != 200:
        # Si falla, intentar sin search
        groups_response = requests.get(
            f'{KEYCLOAK_URL}/admin/realms/{REALM}/groups?briefRepresentation=false', 
            headers=headers
        )
        
    if groups_response.status_code != 200:
        print(f"❌ Error obteniendo grupos: {groups_response.status_code}")
        return None
    
    groups = groups_response.json()
    
    # Buscar grupo padre
    parent_group = None
    parent_id = None
    
    for group in groups:
        if group['name'] == parts[0]:
            parent_group = group
            parent_id = group['id']
            break
    
    if not parent_id:
        print(f"❌ Grupo padre '{parts[0]}' no encontrado")
        return None
    
    # Si solo hay un nivel (ej: 'Agencia'), devolver el ID del grupo padre
    if len(parts) == 1:
        return parent_id
    
    # Para subgrupos, hacer múltiples intentos con diferentes estrategias
    print(f"🔍 Buscando subgrupo '{parts[1]}' en '{parts[0]}'...")
    
    # Estrategia 1: Obtener detalles del grupo padre específicamente
    parent_url = f'{KEYCLOAK_URL}/admin/realms/{REALM}/groups/{parent_id}'
    parent_response = requests.get(parent_url, headers=headers)
    
    if parent_response.status_code == 200:
        parent_data = parent_response.json()
        subgroups = parent_data.get('subGroups', [])
        
        for subgroup in subgroups:
            if subgroup['name'] == parts[1]:
                print(f"✅ Subgrupo encontrado con ID: {subgroup['id']}")
                return subgroup['id']
    
    # Estrategia 2: Obtener subgrupos directamente
    subgroups_url = f'{KEYCLOAK_URL}/admin/realms/{REALM}/groups/{parent_id}/children'
    subgroups_response = requests.get(subgroups_url, headers=headers)
    
    if subgroups_response.status_code == 200:
        subgroups = subgroups_response.json()
        for subgroup in subgroups:
            if subgroup['name'] == parts[1]:
                print(f"✅ Subgrupo encontrado (children) con ID: {subgroup['id']}")
                return subgroup['id']
    
    # Estrategia 3: Buscar en toda la estructura de grupos
    all_groups_detailed = requests.get(
        f'{KEYCLOAK_URL}/admin/realms/{REALM}/groups?briefRepresentation=false&max=100',
        headers=headers
    )
    
    if all_groups_detailed.status_code == 200:
        for group in all_groups_detailed.json():
            if group['name'] == parts[0] and 'subGroups' in group:
                for subgroup in group['subGroups']:
                    if subgroup['name'] == parts[1]:
                        print(f"✅ Subgrupo encontrado (búsqueda completa) con ID: {subgroup['id']}")
                        return subgroup['id']
    
    print(f"❌ Subgrupo '{parts[1]}' no encontrado en '{parts[0]}' después de múltiples intentos")
    return None

def assign_roles_to_subgroups(headers):
    """Asignar roles a subgrupos específicos"""
    # Obtener ID del cliente
    clients = requests.get(f'{KEYCLOAK_URL}/admin/realms/{REALM}/clients', headers=headers)
    client_id = None
    if clients.status_code == 200:
        for client in clients.json():
            if client['clientId'] == CLIENT_ID:
                client_id = client['id']
                break
    
    if not client_id:
        print("❌ Cliente no encontrado para asignación de roles")
        return False
    
    # Definir asignaciones de roles por subgrupo
    role_assignments = {
        'gerencia': ['read', 'write', 'update', 'delete', 'approve'],
        'informatico': ['read', 'write', 'update', 'delete'],
        'recursos humanos': ['read', 'write', 'update'],
        'finanzas': ['read', 'write', 'update', 'approve'],
        'facturacion': ['read', 'write'],
        'exportacion': ['read', 'write'],
        'importacion': ['read', 'write'],
        'operaciones': ['read', 'write', 'update'],
        'clientePrueba': ['read']
    }
    
    # Asignar roles a cada subgrupo
    for subgroup_name, role_names in role_assignments.items():
        # Buscar el path completo del subgrupo
        group_path = None
        for parent, subgroups in GROUPS_STRUCTURE.items():
            if subgroup_name in subgroups:
                group_path = f"{parent}/{subgroup_name}"
                break
        
        if not group_path:
            print(f"❌ No se encontró path para subgrupo '{subgroup_name}'")
            continue
        
        # Pequeña pausa para evitar problemas de timing
        time.sleep(0.5)
        
        subgroup_id = get_group_id_by_path(headers, group_path)
        if not subgroup_id:
            print(f"❌ ID no encontrado para subgrupo '{group_path}'")
            continue
        
        # Obtener roles ya asignados al grupo
        existing_roles_url = f'{KEYCLOAK_URL}/admin/realms/{REALM}/groups/{subgroup_id}/role-mappings/clients/{client_id}'
        existing_roles_response = requests.get(existing_roles_url, headers=headers)
        existing_role_names = []
        if existing_roles_response.status_code == 200:
            existing_role_names = [r['name'] for r in existing_roles_response.json()]
        
        # Preparar roles para asignar
        roles_to_assign = []
        for role_name in role_names:
            if role_name not in existing_role_names:
                # Obtener detalles del rol
                role_response = requests.get(
                    f'{KEYCLOAK_URL}/admin/realms/{REALM}/clients/{client_id}/roles/{role_name}',
                    headers=headers
                )
                
                if role_response.status_code == 200:
                    role = role_response.json()
                    roles_to_assign.append(role)
                else:
                    print(f"❌ Error obteniendo rol '{role_name}': {role_response.status_code}")
        
        # Asignar roles al grupo si hay roles nuevos
        if roles_to_assign:
            response = requests.post(
                f'{KEYCLOAK_URL}/admin/realms/{REALM}/groups/{subgroup_id}/role-mappings/clients/{client_id}',
                json=roles_to_assign,
                headers=headers
            )
            
            if response.status_code in [201, 204]:
                role_names_assigned = [r['name'] for r in roles_to_assign]
                print(f"✅ Roles {role_names_assigned} asignados a '{group_path}'")
            else:
                print(f"❌ Error asignando roles a '{group_path}': {response.status_code} - {response.text}")
        else:
            print(f"✅ Subgrupo '{group_path}' ya tiene todos los roles asignados")
    
    return True

def assign_user_to_group(headers, user_id, group_path):
    """Asignar usuario a un grupo/subgrupo"""
    print(f"🔄 Asignando usuario al grupo '{group_path}'")
    
    # Pequeña pausa para evitar problemas de timing
    time.sleep(0.5)
    
    group_id = get_group_id_by_path(headers, group_path)
    if not group_id:
        print(f"❌ No se pudo obtener ID para grupo '{group_path}'")
        return False
    
    response = requests.put(
        f'{KEYCLOAK_URL}/admin/realms/{REALM}/users/{user_id}/groups/{group_id}',
        headers=headers
    )
    
    if response.status_code in [201, 204]:
        print(f"✅ Usuario asignado al grupo '{group_path}'")
        return True
    else:
        print(f"❌ Error asignando usuario al grupo '{group_path}': {response.status_code} - {response.text}")
        return False

def create_user(headers, username, password, email, first_name, last_name, group_path):
    """Crear usuario y asignarlo a un grupo"""
    print(f"🔄 Creando usuario '{username}'")
    
    # Verificar si el usuario existe
    users = requests.get(f'{KEYCLOAK_URL}/admin/realms/{REALM}/users?username={username}', 
                        headers=headers)
    if users.status_code == 200 and users.json():
        print(f"✅ Usuario '{username}' ya existe")
        # Si ya existe, intentar asignarlo al grupo
        user_id = users.json()[0]['id']
        assign_user_to_group(headers, user_id, group_path)
        return True
    
    # Crear usuario si no existe
    user_data = {
        'username': username,
        'email': email,
        'enabled': True,
        'emailVerified': True,
        'firstName': first_name,
        'lastName': last_name,
        'credentials': [{
            'type': 'password',
            'value': password,
            'temporary': False
        }],
        'requiredActions': []
    }
    response = requests.post(f'{KEYCLOAK_URL}/admin/realms/{REALM}/users', 
                           json=user_data, headers=headers)
    if response.status_code in [201, 204]:
        print(f"✅ Usuario '{username}' creado")
        
        # Obtener ID del usuario recién creado
        time.sleep(1)  # Pequeña pausa para asegurar la creación
        users = requests.get(f'{KEYCLOAK_URL}/admin/realms/{REALM}/users?username={username}', 
                           headers=headers)
        if users.status_code == 200 and users.json():
            user_id = users.json()[0]['id']
            
            # Asignar usuario al grupo
            success = assign_user_to_group(headers, user_id, group_path)
            return success
        else:
            print(f"❌ Error obteniendo ID del usuario '{username}' después de crearlo")
    else:
        print(f"❌ Error creando usuario '{username}': {response.status_code} - {response.text}")
    
    return False

def initialize_keycloak():
    """Función principal de inicialización"""
    print("🚀 Iniciando configuración de Keycloak...")
    time.sleep(20)  # Esperar más tiempo para que PostgreSQL y Keycloak estén completamente listos
    
    if not wait_for_keycloak():
        print("❌ Error: Keycloak no respondió")
        return False
    
    token = get_admin_token()
    if not token:
        print("❌ Error: No se pudo obtener token de admin")
        return False
    
    headers = {'Authorization': f'Bearer {token}', 'Content-Type': 'application/json'}
    
    # Crear recursos en orden
    try:
        if not create_realm(headers):
            return False
        
        if not create_client(headers):
            return False
            
        if not create_client_roles(headers):
            return False
            
        if not create_groups(headers):
            return False
            
        # Pausa más larga antes de asignar roles para asegurar que todos los grupos estén creados
        print("⏳ Esperando para asegurar propagación completa de grupos...")
        time.sleep(10)  # Aumentar tiempo de espera
        
        # Verificar que los grupos se pueden recuperar antes de continuar
        print("🔍 Verificando acceso a grupos antes de asignar roles...")
        test_paths = ['Agencia/gerencia', 'Agencia/informatico', 'Clientes/clientePrueba']
        all_found = True
        
        for path in test_paths:
            group_id = get_group_id_by_path(headers, path)
            if not group_id:
                print(f"⚠️ No se pudo verificar el grupo '{path}'")
                all_found = False
            else:
                print(f"✅ Grupo '{path}' verificado con ID: {group_id}")
        
        if not all_found:
            print("⚠️ Algunos grupos no se pudieron verificar, esperando más tiempo...")
            time.sleep(10)
        
        if not assign_roles_to_subgroups(headers):
            print("⚠️ Hubo errores asignando roles, pero continuando...")
        
        # Otra pausa antes de crear usuarios
        print("⏳ Esperando para asegurar propagación de roles...")
        time.sleep(5)
        
        # Crear usuarios de prueba
        print("👥 Creando usuarios de prueba...")
        
        create_user(headers, TEST_USERNAME, TEST_PASSWORD, TEST_EMAIL, 
                  'Test', 'User', 'Agencia/informatico')
        
        create_user(headers, 'gerente', 'gerente123', 'gerente@example.com',
                  'Gerente', 'General', 'Agencia/gerencia')
        
        create_user(headers, 'cliente', 'cliente123', 'cliente@example.com',
                  'Cliente', 'Prueba', 'Clientes/clientePrueba')
        
        print("✅ Keycloak configurado exitosamente")
        return True
        
    except Exception as e:
        print(f"❌ Error durante la inicialización: {e}")
        import traceback
        traceback.print_exc()
        return False

def get_user_details(access_token: str) -> dict:
    """Extraer roles y grupos del access token"""
    try:
        parts = access_token.split('.')
        if len(parts) < 2:
            return {"roles": [], "groups": []}
        
        payload = parts[1]
        payload += '=' * (4 - len(payload) % 4)
        decoded = base64.urlsafe_b64decode(payload)
        token_data = json.loads(decoded)
        
        # Extraer roles
        all_roles = []
        if 'roles' in token_data:
            roles_from_claim = token_data.get('roles', [])
            if isinstance(roles_from_claim, list):
                all_roles.extend(roles_from_claim)
        
        resource_access = token_data.get('resource_access', {})
        if CLIENT_ID in resource_access:
            client_roles = resource_access[CLIENT_ID].get('roles', [])
            all_roles.extend(client_roles)
        
        realm_roles = token_data.get('realm_access', {}).get('roles', [])
        all_roles.extend(realm_roles)
        
        # Filtrar solo roles definidos
        filtered_roles = [r for r in set(all_roles) if r in ROLES]
        
        # Extraer y limpiar grupos
        groups = token_data.get('groups', [])
        cleaned_groups = [g.lstrip('/') for g in groups if isinstance(g, str)]
        
        return {
            "roles": filtered_roles,
            "groups": cleaned_groups
        }
    except Exception as e:
        print(f"Error decodificando token: {e}")
        return {"roles": [], "groups": []}

# ==================== EVENTOS DE APLICACIÓN ====================

@app.on_event("startup")
async def startup_event():
    """Inicializar Keycloak al arrancar"""
    print("🚀 Iniciando servicio de autenticación...")
    # No bloquear el startup con la inicialización
    import asyncio
    asyncio.create_task(run_initialization())
    print("✅ Servicio de autenticación iniciado, configuración en proceso...")

async def run_initialization():
    """Ejecutar inicialización en background"""
    await asyncio.sleep(5)  # Pequeña pausa para asegurar que FastAPI esté listo
    success = initialize_keycloak()
    if success:
        print("✅ Keycloak configurado completamente")
    else:
        print("❌ Error en la configuración de Keycloak")

# ==================== ENDPOINTS DE API ====================

@app.get("/")
async def root():
    return {"service": "Keycloak Authentication API", "status": "running"}

@app.get("/health")
async def health():
    """Health check endpoint - siempre responde OK para que el contenedor se considere healthy"""
    return {
        "status": "healthy",
        "service": "api-keycloak",
        "timestamp": time.time()
    }

@app.get("/auth/login-url")
async def get_login_url(redirect_uri: str, state: str):
    """Obtener URL de login de Keycloak"""
    auth_url = f"{KEYCLOAK_URL.replace('keycloak:8080', 'localhost:8080')}/realms/{REALM}/protocol/openid-connect/auth"
    params = {
        'client_id': CLIENT_ID,
        'redirect_uri': redirect_uri,
        'response_type': 'code',
        'scope': 'openid email profile',
        'state': state
    }
    
    query_string = '&'.join([f"{k}={v}" for k, v in params.items()])
    login_url = f"{auth_url}?{query_string}"
    
    return {"login_url": login_url}

@app.post("/auth/exchange-code")
async def exchange_code(request: TokenRequest):
    """Intercambiar código de autorización por tokens"""
    token_url = f"{KEYCLOAK_URL}/realms/{REALM}/protocol/openid-connect/token"
    token_data = {
        'grant_type': 'authorization_code',
        'code': request.code,
        'redirect_uri': request.redirect_uri,
        'client_id': CLIENT_ID,
        'client_secret': CLIENT_SECRET
    }
    
    try:
        response = requests.post(token_url, data=token_data)
        if response.status_code != 200:
            raise HTTPException(status_code=response.status_code, 
                              detail=f"Error obteniendo token: {response.text}")
        
        tokens = response.json()
        
        # Decodificar ID token
        id_token = tokens.get('id_token', '')
        if not id_token:
            raise HTTPException(status_code=500, detail="No se recibió ID token")
        
        parts = id_token.split('.')
        if len(parts) < 2:
            raise HTTPException(status_code=500, detail="Token inválido")
        
        payload = parts[1]
        payload += '=' * (4 - len(payload) % 4)
        decoded = base64.urlsafe_b64decode(payload)
        user_info = json.loads(decoded)
        
        # Obtener información adicional del usuario (roles y grupos)
        user_details = get_user_details(tokens['access_token'])
        
        return {
            "user_info": {
                "username": user_info.get('preferred_username'),
                "email": user_info.get('email'),
                "name": user_info.get('name'),
                "roles": user_details.get('roles', []),
                "groups": user_details.get('groups', [])
            },
            "tokens": tokens
        }
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/auth/direct-login")
async def direct_login(credentials: LoginRequest):
    """Login directo con usuario y contraseña"""
    token_url = f"{KEYCLOAK_URL}/realms/{REALM}/protocol/openid-connect/token"
    token_data = {
        'grant_type': 'password',
        'username': credentials.username,
        'password': credentials.password,
        'client_id': CLIENT_ID,
        'client_secret': CLIENT_SECRET,
        'scope': 'openid email profile'
    }
    
    try:
        response = requests.post(token_url, data=token_data)
        if response.status_code != 200:
            raise HTTPException(status_code=401, detail="Credenciales inválidas")
        
        tokens = response.json()
        
        # Decodificar ID token
        id_token = tokens.get('id_token', '')
        parts = id_token.split('.')
        payload = parts[1]
        payload += '=' * (4 - len(payload) % 4)
        decoded = base64.urlsafe_b64decode(payload)
        user_info = json.loads(decoded)
        
        # Obtener información adicional del usuario
        user_details = get_user_details(tokens['access_token'])
        
        return {
            "user_info": {
                "username": user_info.get('preferred_username'),
                "email": user_info.get('email'),
                "name": user_info.get('name'),
                "roles": user_details.get('roles', []),
                "groups": user_details.get('groups', [])
            },
            "tokens": tokens
        }
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/auth/logout-url")
async def get_logout_url(redirect_uri: str):
    """Obtener URL de logout de Keycloak"""
    logout_url = f"{KEYCLOAK_URL.replace('keycloak:8080', 'localhost:8080')}/realms/{REALM}/protocol/openid-connect/logout"
    params = {
        'post_logout_redirect_uri': redirect_uri,
        'client_id': CLIENT_ID
    }
    
    query_string = '&'.join([f"{k}={v}" for k, v in params.items()])
    full_logout_url = f"{logout_url}?{query_string}"
    
    return {"logout_url": full_logout_url}

@app.post("/auth/validate-token")
async def validate_token(token: str):
    """Validar un access token"""
    introspect_url = f"{KEYCLOAK_URL}/realms/{REALM}/protocol/openid-connect/token/introspect"
    data = {
        'token': token,
        'client_id': CLIENT_ID,
        'client_secret': CLIENT_SECRET
    }
    
    try:
        response = requests.post(introspect_url, data=data)
        if response.status_code == 200:
            result = response.json()
            return {"valid": result.get('active', False), "token_info": result}
        else:
            return {"valid": False}
    except:
        return {"valid": False}

@app.post("/auth/debug-token")
async def debug_token(token: str):
    """Debug: Ver contenido del token (solo para desarrollo)"""
    try:
        parts = token.split('.')
        if len(parts) >= 2:
            payload = parts[1]
            payload += '=' * (4 - len(payload) % 4)
            decoded = base64.urlsafe_b64decode(payload)
            token_data = json.loads(decoded)
            
            # Obtener detalles del usuario
            user_details = get_user_details(token)
            
            return {
                "token_claims": token_data,
                "extracted_details": user_details
            }
    except Exception as e:
        return {"error": str(e)}

# ==================== ENDPOINTS DE ADMINISTRACIÓN ====================

@app.get("/admin/users")
async def get_all_users(authorization: str = Header(None)):
    """Obtener lista de todos los usuarios"""
    try:
        # Obtener token de admin fresco
        admin_token = get_admin_token()
        if not admin_token:
            raise HTTPException(status_code=500, detail="No se pudo obtener token de administrador")
        
        headers = {'Authorization': f'Bearer {admin_token}'}
        
        # Obtener usuarios
        response = requests.get(
            f'{KEYCLOAK_URL}/admin/realms/{REALM}/users',
            headers=headers
        )
        
        if response.status_code != 200:
            raise HTTPException(status_code=response.status_code, detail="Error obteniendo usuarios")
        
        users = response.json()
        
        # Para cada usuario, obtener sus grupos
        users_with_details = []
        for user in users:
            user_id = user['id']
            
            # Obtener grupos del usuario
            groups_response = requests.get(
                f'{KEYCLOAK_URL}/admin/realms/{REALM}/users/{user_id}/groups',
                headers=headers
            )
            
            groups = []
            if groups_response.status_code == 200:
                for group in groups_response.json():
                    # Construir el path completo del grupo
                    group_path = group['path'].lstrip('/')
                    groups.append(group_path)
            
            users_with_details.append({
                'id': user['id'],
                'username': user.get('username'),
                'email': user.get('email'),
                'firstName': user.get('firstName'),
                'lastName': user.get('lastName'),
                'enabled': user.get('enabled', True),
                'groups': groups
            })
        
        return users_with_details
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/admin/users/{username}")
async def get_user_by_username(username: str, authorization: str = Header(None)):
    """Obtener detalles de un usuario específico"""
    try:
        admin_token = get_admin_token()
        if not admin_token:
            raise HTTPException(status_code=500, detail="No se pudo obtener token de administrador")
        
        headers = {'Authorization': f'Bearer {admin_token}'}
        
        # Buscar usuario por username
        response = requests.get(
            f'{KEYCLOAK_URL}/admin/realms/{REALM}/users?username={username}',
            headers=headers
        )
        
        if response.status_code != 200:
            raise HTTPException(status_code=response.status_code, detail="Error buscando usuario")
        
        users = response.json()
        if not users:
            raise HTTPException(status_code=404, detail="Usuario no encontrado")
        
        user = users[0]
        user_id = user['id']
        
        # Obtener grupos del usuario
        groups_response = requests.get(
            f'{KEYCLOAK_URL}/admin/realms/{REALM}/users/{user_id}/groups',
            headers=headers
        )
        
        groups = []
        if groups_response.status_code == 200:
            for group in groups_response.json():
                group_path = group['path'].lstrip('/')
                groups.append(group_path)
        
        return {
            'id': user['id'],
            'username': user.get('username'),
            'email': user.get('email'),
            'firstName': user.get('firstName'),
            'lastName': user.get('lastName'),
            'enabled': user.get('enabled', True),
            'groups': groups
        }
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

class UserCreate(BaseModel):
    username: str
    email: str
    password: str
    firstName: str
    lastName: str
    groups: list[str] = []

@app.post("/admin/users")
async def create_new_user(user_data: UserCreate, authorization: str = Header(None)):
    """Crear un nuevo usuario"""
    try:
        admin_token = get_admin_token()
        if not admin_token:
            raise HTTPException(status_code=500, detail="No se pudo obtener token de administrador")
        
        headers = {'Authorization': f'Bearer {admin_token}', 'Content-Type': 'application/json'}
        
        # Verificar si el usuario ya existe
        existing_user = requests.get(
            f'{KEYCLOAK_URL}/admin/realms/{REALM}/users?username={user_data.username}',
            headers=headers
        )
        
        if existing_user.status_code == 200 and existing_user.json():
            raise HTTPException(status_code=400, detail="Usuario ya existe")
        
        # Crear usuario
        new_user = {
            'username': user_data.username,
            'email': user_data.email,
            'enabled': True,
            'emailVerified': True,
            'firstName': user_data.firstName,
            'lastName': user_data.lastName,
            'credentials': [{
                'type': 'password',
                'value': user_data.password,
                'temporary': False
            }],
            'requiredActions': []
        }
        
        response = requests.post(
            f'{KEYCLOAK_URL}/admin/realms/{REALM}/users',
            json=new_user,
            headers=headers
        )
        
        if response.status_code not in [201, 204]:
            error_detail = "Error creando usuario"
            try:
                error_response = response.json()
                if 'errorMessage' in error_response:
                    error_detail = error_response['errorMessage']
            except:
                pass
            raise HTTPException(status_code=400, detail=error_detail)
        
        # Obtener ID del usuario creado
        time.sleep(1)  # Pequeña pausa para asegurar la creación
        users = requests.get(
            f'{KEYCLOAK_URL}/admin/realms/{REALM}/users?username={user_data.username}',
            headers=headers
        )
        
        if users.status_code == 200 and users.json():
            user_id = users.json()[0]['id']
            
            # Asignar grupos
            failed_groups = []
            for group_path in user_data.groups:
                success = assign_user_to_group(headers, user_id, group_path)
                if not success:
                    failed_groups.append(group_path)
            
            if failed_groups:
                print(f"⚠️ Error asignando grupos: {failed_groups}")
        
        return {"message": "Usuario creado exitosamente", "username": user_data.username}
        
    except HTTPException:
        raise
    except Exception as e:
        print(f"❌ Error en create_new_user: {e}")
        raise HTTPException(status_code=500, detail=str(e))

class UserUpdate(BaseModel):
    email: Optional[str] = None
    password: Optional[str] = None
    firstName: Optional[str] = None
    lastName: Optional[str] = None
    groups: Optional[list[str]] = None

@app.put("/admin/users/{username}")
async def update_user(username: str, user_data: UserUpdate, authorization: str = Header(None)):
    """Actualizar un usuario existente"""
    try:
        admin_token = get_admin_token()
        if not admin_token:
            raise HTTPException(status_code=500, detail="No se pudo obtener token de administrador")
        
        headers = {'Authorization': f'Bearer {admin_token}', 'Content-Type': 'application/json'}
        
        # Buscar usuario
        response = requests.get(
            f'{KEYCLOAK_URL}/admin/realms/{REALM}/users?username={username}',
            headers=headers
        )
        
        if response.status_code != 200 or not response.json():
            raise HTTPException(status_code=404, detail="Usuario no encontrado")
        
        user = response.json()[0]
        user_id = user['id']
        
        # Preparar datos de actualización
        update_data = {}
        if user_data.email is not None:
            update_data['email'] = user_data.email
        if user_data.firstName is not None:
            update_data['firstName'] = user_data.firstName
        if user_data.lastName is not None:
            update_data['lastName'] = user_data.lastName
        
        # Actualizar usuario
        if update_data:
            response = requests.put(
                f'{KEYCLOAK_URL}/admin/realms/{REALM}/users/{user_id}',
                json=update_data,
                headers=headers
            )
            
            if response.status_code not in [200, 204]:
                raise HTTPException(status_code=response.status_code, detail="Error actualizando usuario")
        
        # Actualizar contraseña si se proporciona
        if user_data.password:
            password_data = {
                'type': 'password',
                'value': user_data.password,
                'temporary': False
            }
            response = requests.put(
                f'{KEYCLOAK_URL}/admin/realms/{REALM}/users/{user_id}/reset-password',
                json=password_data,
                headers=headers
            )
            
            if response.status_code not in [200, 204]:
                raise HTTPException(status_code=response.status_code, detail="Error actualizando contraseña")
        
        # Actualizar grupos si se proporcionan
        if user_data.groups is not None:
            # Obtener grupos actuales
            current_groups_response = requests.get(
                f'{KEYCLOAK_URL}/admin/realms/{REALM}/users/{user_id}/groups',
                headers=headers
            )
            
            if current_groups_response.status_code == 200:
                current_groups = current_groups_response.json()
                
                # Remover de todos los grupos actuales
                for group in current_groups:
                    remove_response = requests.delete(
                        f'{KEYCLOAK_URL}/admin/realms/{REALM}/users/{user_id}/groups/{group["id"]}',
                        headers=headers
                    )
                    if remove_response.status_code not in [200, 204]:
                        print(f"⚠️ Error removiendo usuario del grupo {group['name']}: {remove_response.status_code}")
                
                # Pequeña pausa antes de asignar nuevos grupos
                time.sleep(1)
                
                # Asignar nuevos grupos
                failed_groups = []
                for group_path in user_data.groups:
                    success = assign_user_to_group(headers, user_id, group_path)
                    if not success:
                        failed_groups.append(group_path)
                
                if failed_groups:
                    print(f"⚠️ Error asignando grupos: {failed_groups}")
        
        return {"message": "Usuario actualizado exitosamente"}
        
    except HTTPException:
        raise
    except Exception as e:
        print(f"❌ Error en update_user: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.delete("/admin/users/{username}")
async def delete_user(username: str, authorization: str = Header(None)):
    """Eliminar un usuario"""
    try:
        admin_token = get_admin_token()
        if not admin_token:
            raise HTTPException(status_code=500, detail="No se pudo obtener token de administrador")
        
        headers = {'Authorization': f'Bearer {admin_token}'}
        
        # Buscar usuario
        response = requests.get(
            f'{KEYCLOAK_URL}/admin/realms/{REALM}/users?username={username}',
            headers=headers
        )
        
        if response.status_code != 200 or not response.json():
            raise HTTPException(status_code=404, detail="Usuario no encontrado")
        
        user_id = response.json()[0]['id']
        
        # Eliminar usuario
        response = requests.delete(
            f'{KEYCLOAK_URL}/admin/realms/{REALM}/users/{user_id}',
            headers=headers
        )
        
        if response.status_code not in [200, 204]:
            raise HTTPException(status_code=response.status_code, detail="Error eliminando usuario")
        
        return {"message": "Usuario eliminado exitosamente"}
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/admin/groups")
async def get_all_groups(authorization: str = Header(None)):
    """Obtener lista de todos los grupos con su estructura"""
    try:
        admin_token = get_admin_token()
        if not admin_token:
            raise HTTPException(status_code=500, detail="No se pudo obtener token de administrador")
        
        headers = {'Authorization': f'Bearer {admin_token}'}
        
        # Obtener grupos con detalles completos
        response = requests.get(
            f'{KEYCLOAK_URL}/admin/realms/{REALM}/groups?briefRepresentation=false',
            headers=headers
        )
        
        if response.status_code != 200:
            raise HTTPException(status_code=response.status_code, detail="Error obteniendo grupos")
        
        groups = response.json()
        
        # Formatear grupos en estructura plana
        flat_groups = []
        for group in groups:
            flat_groups.append({
                'id': group['id'],
                'name': group['name'],
                'path': group['path'].lstrip('/')
            })
            
            # Agregar subgrupos
            if 'subGroups' in group:
                for subgroup in group['subGroups']:
                    flat_groups.append({
                        'id': subgroup['id'],
                        'name': subgroup['name'],
                        'path': subgroup['path'].lstrip('/')
                    })
        
        return flat_groups
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# Endpoint adicional para debug de grupos y roles
@app.get("/admin/debug/groups-roles")
async def debug_groups_roles(authorization: str = Header(None)):
    """Debug: Ver asignación de roles a grupos"""
    try:
        admin_token = get_admin_token()
        if not admin_token:
            raise HTTPException(status_code=500, detail="No se pudo obtener token de administrador")
        
        headers = {'Authorization': f'Bearer {admin_token}'}
        
        # Obtener cliente
        clients = requests.get(f'{KEYCLOAK_URL}/admin/realms/{REALM}/clients', headers=headers)
        client_id = None
        for client in clients.json():
            if client['clientId'] == CLIENT_ID:
                client_id = client['id']
                break
        
        if not client_id:
            return {"error": "Cliente no encontrado"}
        
        # Obtener grupos con detalles
        groups_response = requests.get(
            f'{KEYCLOAK_URL}/admin/realms/{REALM}/groups?briefRepresentation=false',
            headers=headers
        )
        
        groups_data = []
        if groups_response.status_code == 200:
            for group in groups_response.json():
                # Obtener detalles del grupo principal
                group_info = {
                    'name': group['name'],
                    'path': group['path'],
                    'subgroups': []
                }
                
                # Procesar subgrupos
                if 'subGroups' in group:
                    for subgroup in group['subGroups']:
                        # Obtener roles del subgrupo
                        roles_response = requests.get(
                            f'{KEYCLOAK_URL}/admin/realms/{REALM}/groups/{subgroup["id"]}/role-mappings/clients/{client_id}',
                            headers=headers
                        )
                        
                        roles = []
                        if roles_response.status_code == 200:
                            roles = [r['name'] for r in roles_response.json()]
                        
                        group_info['subgroups'].append({
                            'name': subgroup['name'],
                            'path': subgroup['path'],
                            'roles': roles
                        })
                
                groups_data.append(group_info)
        
        return {
            "client_id": client_id,
            "groups": groups_data
        }
        
    except Exception as e:
        return {"error": str(e)}

# Endpoint para reintentar asignación de roles y usuarios
@app.post("/admin/retry-setup")
async def retry_setup(authorization: str = Header(None)):
    """Reintentar asignación de roles a grupos y usuarios"""
    try:
        admin_token = get_admin_token()
        if not admin_token:
            raise HTTPException(status_code=500, detail="No se pudo obtener token de administrador")
        
        headers = {'Authorization': f'Bearer {admin_token}', 'Content-Type': 'application/json'}
        
        print("🔄 Reintentando configuración...")
        
        # Esperar un momento
        time.sleep(2)
        
        # Reintentar asignación de roles
        success_roles = assign_roles_to_subgroups(headers)
        
        # Esperar antes de asignar usuarios
        time.sleep(2)
        
        # Reintentar asignación de usuarios a grupos
        results = []
        
        # Obtener usuarios existentes
        users_response = requests.get(f'{KEYCLOAK_URL}/admin/realms/{REALM}/users', headers=headers)
        if users_response.status_code == 200:
            users = users_response.json()
            
            user_group_mapping = {
                'test': 'Agencia/informatico',
                'gerente': 'Agencia/gerencia',
                'cliente': 'Clientes/clientePrueba'
            }
            
            for user in users:
                username = user.get('username')
                if username in user_group_mapping:
                    user_id = user['id']
                    group_path = user_group_mapping[username]
                    
                    # Verificar si ya está en el grupo
                    user_groups = requests.get(
                        f'{KEYCLOAK_URL}/admin/realms/{REALM}/users/{user_id}/groups',
                        headers=headers
                    )
                    
                    already_in_group = False
                    if user_groups.status_code == 200:
                        for group in user_groups.json():
                            if group['path'].lstrip('/') == group_path:
                                already_in_group = True
                                break
                    
                    if not already_in_group:
                        success = assign_user_to_group(headers, user_id, group_path)
                        results.append({
                            'username': username,
                            'group': group_path,
                            'success': success
                        })
                    else:
                        results.append({
                            'username': username,
                            'group': group_path,
                            'success': True,
                            'note': 'Ya estaba en el grupo'
                        })
        
        return {
            "roles_assignment": "success" if success_roles else "partial",
            "users_assignment": results
        }
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# Endpoint para verificar la configuración completa
@app.get("/admin/verify-setup")
async def verify_setup(authorization: str = Header(None)):
    """Verificar que toda la configuración esté correcta"""
    try:
        admin_token = get_admin_token()
        if not admin_token:
            raise HTTPException(status_code=500, detail="No se pudo obtener token de administrador")
        
        headers = {'Authorization': f'Bearer {admin_token}'}
        
        verification = {
            "realm": False,
            "client": False,
            "roles": [],
            "groups": [],
            "users": []
        }
        
        # Verificar realm
        realm_response = requests.get(f'{KEYCLOAK_URL}/admin/realms/{REALM}', headers=headers)
        verification["realm"] = realm_response.status_code == 200
        
        # Verificar cliente y roles
        clients_response = requests.get(f'{KEYCLOAK_URL}/admin/realms/{REALM}/clients', headers=headers)
        if clients_response.status_code == 200:
            for client in clients_response.json():
                if client['clientId'] == CLIENT_ID:
                    verification["client"] = True
                    client_id = client['id']
                    
                    # Verificar roles
                    roles_response = requests.get(
                        f'{KEYCLOAK_URL}/admin/realms/{REALM}/clients/{client_id}/roles',
                        headers=headers
                    )
                    if roles_response.status_code == 200:
                        verification["roles"] = [r['name'] for r in roles_response.json()]
                    break
        
        # Verificar grupos
        groups_response = requests.get(
            f'{KEYCLOAK_URL}/admin/realms/{REALM}/groups?briefRepresentation=false',
            headers=headers
        )
        if groups_response.status_code == 200:
            for group in groups_response.json():
                group_info = {
                    'name': group['name'],
                    'subgroups': []
                }
                if 'subGroups' in group:
                    group_info['subgroups'] = [sg['name'] for sg in group['subGroups']]
                verification["groups"].append(group_info)
        
        # Verificar usuarios
        users_response = requests.get(f'{KEYCLOAK_URL}/admin/realms/{REALM}/users', headers=headers)
        if users_response.status_code == 200:
            for user in users_response.json():
                user_info = {
                    'username': user.get('username'),
                    'groups': []
                }
                
                # Obtener grupos del usuario
                user_groups = requests.get(
                    f'{KEYCLOAK_URL}/admin/realms/{REALM}/users/{user["id"]}/groups',
                    headers=headers
                )
                if user_groups.status_code == 200:
                    user_info['groups'] = [g['path'].lstrip('/') for g in user_groups.json()]
                
                verification["users"].append(user_info)
        
        return verification
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))