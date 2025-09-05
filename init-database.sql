-- ==========================================
-- INICIALIZACIÓN BASE DE DATOS AGENCIA DE ADUANAS
-- Script para ejecución automática en Docker Compose
-- PostgreSQL UNIFICADO - Keycloak + Operaciones
-- ==========================================

-- 0. CREAR BASE DE DATOS PARA KEYCLOAK
-- ==========================================
CREATE DATABASE keycloak WITH OWNER = postgres;

-- 1. CREAR ESQUEMAS EN BASE DE DATOS PRINCIPAL
-- ==========================================
CREATE SCHEMA IF NOT EXISTS sna;
CREATE SCHEMA IF NOT EXISTS entidades;
CREATE SCHEMA IF NOT EXISTS operaciones;

-- 2. ESQUEMA SNA - CÓDIGOS OFICIALES
-- ==========================================

-- Códigos de aduanas (Anexo 51-1)
CREATE TABLE sna.codigos_aduanas (
    codigo VARCHAR(10) PRIMARY KEY,
    glosa VARCHAR(255) NOT NULL,
    activo BOOLEAN DEFAULT true,
    fecha_creacion TIMESTAMP DEFAULT NOW()
);

-- Países (Anexo 51-9)
CREATE TABLE sna.paises (
    codigo_pais VARCHAR(10) PRIMARY KEY,
    nombre VARCHAR(100) NOT NULL,
    continente VARCHAR(50),
    activo BOOLEAN DEFAULT true,
    fecha_creacion TIMESTAMP DEFAULT NOW()
);

-- Monedas (Anexo 51-20)
CREATE TABLE sna.monedas (
    codigo_moneda VARCHAR(10) PRIMARY KEY,
    nombre VARCHAR(50) NOT NULL,
    pais_moneda VARCHAR(100),
    simbolo VARCHAR(5),
    activo BOOLEAN DEFAULT true,
    fecha_creacion TIMESTAMP DEFAULT NOW()
);

-- Vías de transporte (Anexo 51-13)
CREATE TABLE sna.vias_transporte (
    codigo VARCHAR(2) PRIMARY KEY,
    descripcion VARCHAR(100) NOT NULL,
    activo BOOLEAN DEFAULT true,
    fecha_creacion TIMESTAMP DEFAULT NOW()
);

-- Tipos de carga
CREATE TABLE sna.tipos_carga (
    codigo VARCHAR(2) PRIMARY KEY,
    descripcion VARCHAR(50) NOT NULL,
    activo BOOLEAN DEFAULT true,
    fecha_creacion TIMESTAMP DEFAULT NOW()
);

-- Códigos arancelarios
CREATE TABLE sna.codigos_arancelarios (
    codigo_arancel VARCHAR(20) PRIMARY KEY,
    glosa TEXT NOT NULL,
    arancel_ad_valorem DECIMAL(5,2),
    unidad_medida VARCHAR(10),
    capitulo VARCHAR(10),
    activo BOOLEAN DEFAULT true,
    fecha_creacion TIMESTAMP DEFAULT NOW()
);

-- Tipos de operación
CREATE TABLE sna.tipos_operacion (
    codigo VARCHAR(2) PRIMARY KEY,
    descripcion VARCHAR(100) NOT NULL,
    activo BOOLEAN DEFAULT true
);

-- Regímenes de importación
CREATE TABLE sna.regimenes_importacion (
    codigo VARCHAR(2) PRIMARY KEY,
    descripcion VARCHAR(100) NOT NULL,
    activo BOOLEAN DEFAULT true
);

-- Formas de pago
CREATE TABLE sna.formas_pago (
    codigo VARCHAR(2) PRIMARY KEY,
    descripcion VARCHAR(50) NOT NULL,
    activo BOOLEAN DEFAULT true
);

-- Cláusulas de compra venta (INCOTERMS)
CREATE TABLE sna.clausulas_compra_venta (
    codigo VARCHAR(3) PRIMARY KEY,
    descripcion VARCHAR(100) NOT NULL,
    activo BOOLEAN DEFAULT true
);

-- Unidades de medida
CREATE TABLE sna.unidades_medida (
    codigo VARCHAR(3) PRIMARY KEY,
    descripcion VARCHAR(50) NOT NULL,
    tipo VARCHAR(20),
    activo BOOLEAN DEFAULT true
);

-- Puertos
CREATE TABLE sna.puertos (
    codigo VARCHAR(3) PRIMARY KEY,
    nombre VARCHAR(100) NOT NULL,
    region VARCHAR(3),
    tipo VARCHAR(20),
    activo BOOLEAN DEFAULT true
);

-- Regiones de Chile
CREATE TABLE sna.regiones (
    codigo VARCHAR(5) PRIMARY KEY,
    nombre VARCHAR(100) NOT NULL,
    activo BOOLEAN DEFAULT true
);

-- 3. ESQUEMA ENTIDADES - CLIENTES Y PROVEEDORES
-- ==========================================

-- Clientes (importadores/exportadores)
CREATE TABLE entidades.clientes (
    id SERIAL PRIMARY KEY,
    rut VARCHAR(12) UNIQUE NOT NULL,
    razon_social VARCHAR(255) NOT NULL,
    tipo_cliente VARCHAR(20) CHECK (tipo_cliente IN ('importador', 'exportador')),
    
    -- DATOS EMPRESA
    direccion TEXT,
    comuna VARCHAR(100),
    ciudad VARCHAR(100),
    codigo_pais VARCHAR(10) REFERENCES sna.paises(codigo_pais),
    telefono VARCHAR(20),
    email VARCHAR(100),
    
    -- REPRESENTANTE LEGAL
    representante_rut VARCHAR(12),
    representante_nombres VARCHAR(100),
    representante_apellidos VARCHAR(100),
    representante_cargo VARCHAR(100),
    
    activo BOOLEAN DEFAULT true,
    fecha_creacion TIMESTAMP DEFAULT NOW()
);

-- Proveedores (despachadores, transportistas, etc)
CREATE TABLE entidades.proveedores (
    id SERIAL PRIMARY KEY,
    rut VARCHAR(12) UNIQUE NOT NULL,
    razon_social VARCHAR(255) NOT NULL,
    tipo_proveedor VARCHAR(20) CHECK (tipo_proveedor IN ('despachador', 'transportista', 'almacenista')),
    
    -- DATOS EMPRESA
    direccion TEXT,
    comuna VARCHAR(100),
    ciudad VARCHAR(100),
    codigo_pais VARCHAR(10) REFERENCES sna.paises(codigo_pais),
    telefono VARCHAR(20),
    email VARCHAR(100),
    
    -- REPRESENTANTE LEGAL
    representante_rut VARCHAR(12),
    representante_nombres VARCHAR(100),
    representante_apellidos VARCHAR(100),
    representante_cargo VARCHAR(100),
    
    activo BOOLEAN DEFAULT true,
    fecha_creacion TIMESTAMP DEFAULT NOW()
);

-- 4. ESQUEMA OPERACIONES - PROCESOS ADUANEROS
-- ==========================================

-- Despachos con campos de usuario
CREATE TABLE operaciones.despachos (
    numero_despacho VARCHAR(50) PRIMARY KEY,
    estado VARCHAR(20) DEFAULT 'pendiente',
    fecha_creacion TIMESTAMP DEFAULT NOW(),
    fecha_actualizacion TIMESTAMP DEFAULT NOW(),
    documentos_requeridos JSONB,
    documentos_presentes JSONB,
    datos_extraidos JSONB,
    extra_metadata JSONB,
    
    -- REFERENCIAS
    importador_id INTEGER REFERENCES entidades.clientes(id),
    despachador_id INTEGER REFERENCES entidades.proveedores(id),
    consignante_id INTEGER REFERENCES entidades.clientes(id),
    
    -- CAMPOS DE USUARIO
    usuario_creador VARCHAR(100),
    usuario_actualizacion VARCHAR(100)
);

-- Documentos
CREATE TABLE operaciones.documentos (
    id SERIAL PRIMARY KEY,
    numero_despacho VARCHAR(50) REFERENCES operaciones.despachos(numero_despacho),
    tipo_documento VARCHAR(50),
    nombre_archivo VARCHAR(255),
    contenido_base64 TEXT,
    procesado BOOLEAN DEFAULT false,
    datos_extraidos JSONB,
    fecha_carga TIMESTAMP DEFAULT NOW(),
    fecha_procesamiento TIMESTAMP
);

-- Declaraciones de ingreso (DIN) con campos de usuario
CREATE TABLE operaciones.declaraciones_ingreso (
    id SERIAL PRIMARY KEY,
    numero_identificacion VARCHAR(20) UNIQUE NOT NULL,
    numero_despacho VARCHAR(50) REFERENCES operaciones.despachos(numero_despacho),
    fecha_vencimiento DATE,
    
    -- IDENTIFICACIÓN
    aduana_codigo VARCHAR(10) REFERENCES sna.codigos_aduanas(codigo),
    despachador_id INTEGER REFERENCES entidades.proveedores(id),
    tipo_operacion VARCHAR(2) REFERENCES sna.tipos_operacion(codigo),
    
    -- CONSIGNATARIO/IMPORTADOR
    consignatario_id INTEGER REFERENCES entidades.clientes(id),
    
    -- CONSIGNANTE
    consignante_id INTEGER REFERENCES entidades.clientes(id),
    
    -- ORIGEN, TRANSPORTE Y ALMACENAJE
    pais_origen VARCHAR(10) REFERENCES sna.paises(codigo_pais),
    pais_adquisicion VARCHAR(10) REFERENCES sna.paises(codigo_pais),
    via_transporte VARCHAR(2) REFERENCES sna.vias_transporte(codigo),
    direccion_almacen TEXT,
    comuna_almacen VARCHAR(100),
    puerto_embarque VARCHAR(100),
    puerto_descarga VARCHAR(100),
    tipo_carga VARCHAR(2) REFERENCES sna.tipos_carga(codigo),
    
    -- TRANSPORTE
    codigo_transportista VARCHAR(20),
    codigo_pais_transportista VARCHAR(10) REFERENCES sna.paises(codigo_pais),
    rut_transportista VARCHAR(12),
    numero_manifiesto VARCHAR(50),
    fecha_manifiesto DATE,
    documento_transporte VARCHAR(50),
    fecha_documento_transporte DATE,
    emisor_documento_transporte VARCHAR(255),
    rut_emisor_transporte VARCHAR(12),
    
    -- ALMACENAJE
    almacen_codigo VARCHAR(10),
    fecha_recepcion DATE,
    fecha_retiro DATE,
    
    -- RÉGIMEN SUSPENSIVO
    regimen_suspensivo VARCHAR(2) REFERENCES sna.regimenes_importacion(codigo),
    plazo_suspensivo INTEGER,
    parcialidad VARCHAR(2),
    hora_instalacion TIME,
    tipo_instalacion VARCHAR(2),
    almacen_regimen VARCHAR(10),
    
    -- ANTECEDENTES FINANCIEROS
    registro_importacion VARCHAR(50),
    banco_comercial VARCHAR(100),
    codigo_divisas VARCHAR(3),
    forma_pago VARCHAR(2) REFERENCES sna.formas_pago(codigo),
    dias_pago INTEGER,
    valor_ex_fabrica DECIMAL(15,2),
    moneda VARCHAR(10) REFERENCES sna.monedas(codigo_moneda),
    gastos_hasta_fob DECIMAL(15,2),
    clase_compra VARCHAR(2),
    pago_gravamen VARCHAR(2),
    
    -- VALORES TOTALES
    valor_fob_total DECIMAL(15,2),
    valor_flete_total DECIMAL(15,2),
    valor_seguro_total DECIMAL(15,2),
    valor_cif_total DECIMAL(15,2),
    peso_bruto_total DECIMAL(10,3),
    total_bultos INTEGER,
    
    -- ESTADO Y FECHAS
    estado VARCHAR(20) DEFAULT 'borrador',
    fecha_creacion TIMESTAMP DEFAULT NOW(),
    fecha_aceptacion TIMESTAMP,
    fecha_fiscalizacion TIMESTAMP,
    usuario_creacion VARCHAR(100),
    fiscalizador VARCHAR(100),
    
    -- CAMPOS DE USUARIO ADICIONALES
    usuario_creador VARCHAR(100),
    usuario_actualizacion VARCHAR(100),
    usuario_responsable VARCHAR(100)
);

-- Ítems de la declaración
CREATE TABLE operaciones.din_items (
    id SERIAL PRIMARY KEY,
    declaracion_id INTEGER REFERENCES operaciones.declaraciones_ingreso(id),
    numero_item INTEGER NOT NULL,
    nombre_mercancia TEXT NOT NULL,
    codigo_arancel VARCHAR(20) REFERENCES sna.codigos_arancelarios(codigo_arancel),
    cantidad_mercancia DECIMAL(15,3),
    unidad_medida VARCHAR(10) REFERENCES sna.unidades_medida(codigo),
    valor_fob_unitario DECIMAL(15,2),
    valor_fob_item DECIMAL(15,2),
    valor_cif_item DECIMAL(15,2),
    
    -- TRIBUTOS
    ad_valorem_codigo VARCHAR(10),
    ad_valorem_tasa DECIMAL(5,2),
    ad_valorem_monto DECIMAL(15,2),
    otro1_codigo VARCHAR(10),
    otro1_tasa DECIMAL(5,2),
    otro1_monto DECIMAL(15,2),
    otro2_codigo VARCHAR(10),
    otro2_tasa DECIMAL(5,2),
    otro2_monto DECIMAL(15,2),
    otro3_codigo VARCHAR(10),
    otro3_tasa DECIMAL(5,2),
    otro3_monto DECIMAL(15,2),
    otro4_codigo VARCHAR(10),
    otro4_tasa DECIMAL(5,2),
    otro4_monto DECIMAL(15,2),
    
    -- AJUSTES Y OBSERVACIONES
    ajuste_monto DECIMAL(15,2),
    categoria_ajuste VARCHAR(10),
    acuerdo_comercial VARCHAR(10),
    observaciones TEXT,
    
    UNIQUE(declaracion_id, numero_item)
);

-- Bultos
CREATE TABLE operaciones.din_bultos (
    id SERIAL PRIMARY KEY,
    declaracion_id INTEGER REFERENCES operaciones.declaraciones_ingreso(id),
    item_id INTEGER REFERENCES operaciones.din_items(id),
    tipo_bulto VARCHAR(10),
    codigo_bulto VARCHAR(10),
    cantidad_bultos INTEGER,
    peso_bruto DECIMAL(10,3),
    identificacion_bulto TEXT
);

-- Observaciones
CREATE TABLE operaciones.din_observaciones (
    id SERIAL PRIMARY KEY,
    declaracion_id INTEGER REFERENCES operaciones.declaraciones_ingreso(id),
    tipo_observacion VARCHAR(20), -- 'general', 'banco_central', 'operaciones'
    codigo_observacion VARCHAR(10),
    descripcion TEXT,
    fecha_observacion TIMESTAMP DEFAULT NOW()
);

-- Historial de cambios
CREATE TABLE operaciones.din_historial (
    id SERIAL PRIMARY KEY,
    declaracion_id INTEGER REFERENCES operaciones.declaraciones_ingreso(id),
    estado_anterior VARCHAR(20),
    estado_nuevo VARCHAR(20),
    usuario VARCHAR(100),
    comentarios TEXT,
    fecha_cambio TIMESTAMP DEFAULT NOW()
);

-- Procedimientos con campos de usuario
CREATE TABLE operaciones.procedimientos (
    id SERIAL PRIMARY KEY,
    numero_despacho VARCHAR(50) REFERENCES operaciones.despachos(numero_despacho),
    declaracion_id INTEGER REFERENCES operaciones.declaraciones_ingreso(id),
    tipo_procedimiento VARCHAR(50),
    estado VARCHAR(20) DEFAULT 'pendiente',
    usuario_asignado VARCHAR(100),
    fecha_inicio TIMESTAMP,
    fecha_fin TIMESTAMP,
    datos JSONB,
    
    -- CAMPOS DE USUARIO ADICIONALES
    usuario_creador VARCHAR(100),
    fecha_creacion TIMESTAMP DEFAULT NOW()
);

-- TABLA DE AUDITORÍA DE OPERACIONES (NUEVA)
CREATE TABLE operaciones.auditoria_operaciones (
    id SERIAL PRIMARY KEY,
    tabla_afectada VARCHAR(100) NOT NULL,
    operacion VARCHAR(20) NOT NULL, -- INSERT, UPDATE, DELETE
    registro_id VARCHAR(100),
    usuario_keycloak VARCHAR(100) NOT NULL,
    datos_anteriores JSONB,
    datos_nuevos JSONB,
    fecha_operacion TIMESTAMP DEFAULT NOW(),
    ip_origen VARCHAR(45),
    user_agent TEXT
);

-- 5. ÍNDICES PARA PERFORMANCE
-- ==========================================

-- Índices en despachos
CREATE INDEX idx_despachos_importador ON operaciones.despachos(importador_id);
CREATE INDEX idx_despachos_despachador ON operaciones.despachos(despachador_id);
CREATE INDEX idx_despachos_estado ON operaciones.despachos(estado);
CREATE INDEX idx_despachos_fecha_creacion ON operaciones.despachos(fecha_creacion);
CREATE INDEX idx_despachos_usuario_creador ON operaciones.despachos(usuario_creador);

-- Índices en declaraciones
CREATE INDEX idx_din_numero_despacho ON operaciones.declaraciones_ingreso(numero_despacho);
CREATE INDEX idx_din_estado ON operaciones.declaraciones_ingreso(estado);
CREATE INDEX idx_din_fecha_creacion ON operaciones.declaraciones_ingreso(fecha_creacion);
CREATE INDEX idx_din_consignatario ON operaciones.declaraciones_ingreso(consignatario_id);
CREATE INDEX idx_din_usuario_responsable ON operaciones.declaraciones_ingreso(usuario_responsable);

-- Índices en items
CREATE INDEX idx_din_items_declaracion ON operaciones.din_items(declaracion_id);
CREATE INDEX idx_din_items_arancel ON operaciones.din_items(codigo_arancel);

-- Índices en entidades
CREATE INDEX idx_clientes_rut ON entidades.clientes(rut);
CREATE INDEX idx_clientes_tipo ON entidades.clientes(tipo_cliente);
CREATE INDEX idx_proveedores_rut ON entidades.proveedores(rut);
CREATE INDEX idx_proveedores_tipo ON entidades.proveedores(tipo_proveedor);

-- Índices para auditoría
CREATE INDEX idx_auditoria_usuario ON operaciones.auditoria_operaciones(usuario_keycloak);
CREATE INDEX idx_auditoria_fecha ON operaciones.auditoria_operaciones(fecha_operacion);
CREATE INDEX idx_auditoria_tabla ON operaciones.auditoria_operaciones(tabla_afectada);

-- 6. POBLAR DATOS MAESTROS
-- ==========================================

-- Códigos de aduanas
INSERT INTO sna.codigos_aduanas (codigo, glosa) VALUES
('3', 'Arica'),
('7', 'Iquique'),
('10', 'Tocopilla'),
('14', 'Antofagasta'),
('17', 'Chañaral'),
('25', 'Coquimbo'),
('33', 'Los Andes'),
('34', 'Valparaíso'),
('39', 'San Antonio'),
('48', 'Metropolitana'),
('55', 'Talcahuano'),
('67', 'Osorno'),
('69', 'Puerto Montt'),
('83', 'Coyhaique'),
('90', 'Puerto Aysén'),
('92', 'Punta Arenas')
ON CONFLICT (codigo) DO NOTHING;

-- Países principales
INSERT INTO sna.paises (codigo_pais, nombre, continente) VALUES
('0', 'Otros Orígenes Desconocidos', 'Otros'),
('152', 'Chile', 'América del Sur'),
('220', 'Brasil', 'América del Sur'),
('221', 'Estados Unidos', 'América del Norte'),
('224', 'Argentina', 'América del Sur'),
('225', 'Estados Unidos de América', 'América del Norte'),
('226', 'Canadá', 'América del Norte'),
('216', 'México', 'América del Norte'),
('219', 'Perú', 'América del Sur'),
('218', 'Ecuador', 'América del Sur'),
('202', 'Colombia', 'América del Sur'),
('275', 'China', 'Asia'),
('279', 'Japón', 'Asia'),
('278', 'Corea del Sur', 'Asia'),
('300', 'Alemania', 'Europa'),
('303', 'España', 'Europa'),
('305', 'Francia', 'Europa'),
('309', 'Italia', 'Europa'),
('312', 'Reino Unido', 'Europa')
ON CONFLICT (codigo_pais) DO NOTHING;

-- Monedas principales
INSERT INTO sna.monedas (codigo_moneda, nombre, pais_moneda, simbolo) VALUES
('152', 'PESO', 'CHILE', '$'),
('13', 'DÓLAR', 'ESTADOS UNIDOS', 'USD$'),
('40', 'EURO', 'UNIÓN EUROPEA', '€'),
('1', 'PESO', 'ARGENTINA', '$'),
('5', 'REAL', 'BRASIL', 'R$'),
('6', 'DÓLAR', 'CANADÁ', 'CAD$'),
('35', 'YUAN', 'CHINA', '¥'),
('29', 'YEN', 'JAPÓN', '¥'),
('36', 'WON', 'COREA DEL SUR', '₩'),
('24', 'SOL', 'PERÚ', 'S/.')
ON CONFLICT (codigo_moneda) DO NOTHING;

-- Vías de transporte
INSERT INTO sna.vias_transporte (codigo, descripcion) VALUES
('1', 'MARÍTIMA, FLUVIAL Y LACUSTRE'),
('2', 'FERROVIARIO Y CARRETERO'),
('3', 'CARRETERO'),
('4', 'AÉREO'),
('5', 'POSTAL'),
('6', 'FERROVIARIO'),
('7', 'CARRETERO / TERRESTRE'),
('8', 'OLEODUCTOS, GASODUCTOS'),
('9', 'INSTALACIONES FIJAS DE TRANSPORTE')
ON CONFLICT (codigo) DO NOTHING;

-- Tipos de carga
INSERT INTO sna.tipos_carga (codigo, descripcion) VALUES
('01', 'GENERAL'),
('02', 'GRANEL SÓLIDO'),
('03', 'GRANEL LÍQUIDO'),
('04', 'FRIGORÍFICOS'),
('05', 'CONTENEDORES'),
('06', 'CARGA PELIGROSA'),
('07', 'GANADO'),
('08', 'AUTOMÓVILES'),
('09', 'GRANELES ESPECIALES'),
('10', 'OTROS')
ON CONFLICT (codigo) DO NOTHING;

-- Tipos de operación
INSERT INTO sna.tipos_operacion (codigo, descripcion) VALUES
('01', 'IMPORTACIÓN DEFINITIVA'),
('02', 'REIMPORTACIÓN'),
('03', 'IMPORTACIÓN TEMPORAL'),
('04', 'ADMISIÓN TEMPORAL'),
('05', 'TRÁNSITO'),
('06', 'DEPÓSITO'),
('07', 'ZONA FRANCA')
ON CONFLICT (codigo) DO NOTHING;

-- Regímenes de importación
INSERT INTO sna.regimenes_importacion (codigo, descripcion) VALUES
('01', 'NORMAL'),
('02', 'TEMPORAL'),
('03', 'PERFECCIONAMIENTO ACTIVO'),
('04', 'PERFECCIONAMIENTO PASIVO'),
('05', 'TRÁNSITO'),
('06', 'DEPÓSITO ADUANERO'),
('07', 'ZONA FRANCA'),
('08', 'REIMPORTACIÓN')
ON CONFLICT (codigo) DO NOTHING;

-- Formas de pago
INSERT INTO sna.formas_pago (codigo, descripcion) VALUES
('01', 'CONTADO'),
('02', 'CRÉDITO'),
('03', 'COBRANZA'),
('04', 'CARTA DE CRÉDITO'),
('05', 'REMESA'),
('06', 'CUENTA ABIERTA'),
('07', 'CONSIGNACIÓN'),
('08', 'OTROS')
ON CONFLICT (codigo) DO NOTHING;

-- Cláusulas de compra venta
INSERT INTO sna.clausulas_compra_venta (codigo, descripcion) VALUES
('EXW', 'EX WORKS'),
('FCA', 'FREE CARRIER'),
('FAS', 'FREE ALONGSIDE SHIP'),
('FOB', 'FREE ON BOARD'),
('CFR', 'COST AND FREIGHT'),
('CIF', 'COST, INSURANCE AND FREIGHT'),
('CPT', 'CARRIAGE PAID TO'),
('CIP', 'CARRIAGE AND INSURANCE PAID TO'),
('DAT', 'DELIVERED AT TERMINAL'),
('DAP', 'DELIVERED AT PLACE'),
('DDP', 'DELIVERED DUTY PAID')
ON CONFLICT (codigo) DO NOTHING;

-- Unidades de medida
INSERT INTO sna.unidades_medida (codigo, descripcion, tipo) VALUES
('KG', 'KILOGRAMOS', 'PESO'),
('TN', 'TONELADAS', 'PESO'),
('LT', 'LITROS', 'VOLUMEN'),
('M3', 'METROS CÚBICOS', 'VOLUMEN'),
('UN', 'UNIDADES', 'CANTIDAD'),
('PR', 'PARES', 'CANTIDAD'),
('DZ', 'DOCENAS', 'CANTIDAD'),
('MT', 'METROS', 'LONGITUD'),
('M2', 'METROS CUADRADOS', 'SUPERFICIE'),
('CT', 'QUILATES', 'PESO ESPECIAL')
ON CONFLICT (codigo) DO NOTHING;

-- Regiones de Chile
INSERT INTO sna.regiones (codigo, nombre) VALUES
('XV', 'Arica y Parinacota'),
('I', 'Tarapacá'),
('II', 'Antofagasta'),
('III', 'Atacama'),
('IV', 'Coquimbo'),
('V', 'Valparaíso'),
('RM', 'Región Metropolitana'),
('VI', 'O''Higgins'),
('VII', 'Maule'),
('VIII', 'Biobío'),
('IX', 'La Araucanía'),
('XIV', 'Los Ríos'),
('X', 'Los Lagos'),
('XI', 'Aysén'),
('XII', 'Magallanes y Antártica Chilena')
ON CONFLICT (codigo) DO NOTHING;

-- Códigos arancelarios principales (muestra)
INSERT INTO sna.codigos_arancelarios (codigo_arancel, glosa, arancel_ad_valorem, unidad_medida, capitulo) VALUES
('0101.10.00', 'Caballos reproductores de raza pura', 0.00, 'UN', '01'),
('0101.90.00', 'Los demás caballos', 6.00, 'UN', '01'),
('0102.10.00', 'Bovinos reproductores de raza pura', 0.00, 'UN', '01'),
('0102.90.00', 'Los demás bovinos', 6.00, 'UN', '01'),
('0201.10.00', 'Canales o medias canales de bovino', 6.00, 'KG', '02'),
('0201.20.00', 'Los demás cortes de bovino con hueso', 6.00, 'KG', '02'),
('0301.10.00', 'Peces ornamentales vivos', 6.00, 'KG', '03'),
('0301.91.00', 'Truchas vivas', 6.00, 'KG', '03'),
('0401.10.00', 'Leche con contenido de materias grasas inferior o igual al 1%', 6.00, 'LT', '04'),
('0401.20.00', 'Leche con contenido de materias grasas superior al 1% pero inferior o igual al 6%', 6.00, 'LT', '04')
ON CONFLICT (codigo_arancel) DO NOTHING;

-- 7. DATOS DE EJEMPLO PARA TESTING
-- ==========================================

-- Clientes de ejemplo
INSERT INTO entidades.clientes (rut, razon_social, tipo_cliente, direccion, comuna, ciudad, codigo_pais, representante_rut, representante_nombres, representante_apellidos) VALUES
('96521450-0', 'IMPORTADORA EXAMPLE S.A.', 'importador', 'Av. Libertador 1234', 'Las Condes', 'Santiago', '152', '12345678-9', 'Juan Carlos', 'Pérez Rodríguez'),
('12345678-K', 'EXPORTADORA FRUTAS DEL SUR', 'exportador', 'Camino Rural 890', 'Puerto Montt', 'Puerto Montt', '152', '98765432-1', 'María Elena', 'González Silva')
ON CONFLICT (rut) DO NOTHING;

-- Proveedores de ejemplo
INSERT INTO entidades.proveedores (rut, razon_social, tipo_proveedor, direccion, comuna, ciudad, codigo_pais, representante_rut, representante_nombres, representante_apellidos) VALUES
('76543210-9', 'DESPACHADORA ADUANERA LTDA.', 'despachador', 'Puerto 567', 'Valparaíso', 'Valparaíso', '152', '11111111-1', 'Carlos Eduardo', 'Morales López'),
('87654321-3', 'TRANSPORTES LOGÍSTICA S.A.', 'transportista', 'Ruta 5 Norte Km 45', 'La Serena', 'La Serena', '152', '22222222-2', 'Ana Patricia', 'Fernández Ruiz')
ON CONFLICT (rut) DO NOTHING;

-- 8. VISTAS PARA FACILITAR CONSULTAS
-- ==========================================

-- Vista para declaraciones completas
CREATE OR REPLACE VIEW operaciones.vista_declaraciones_completas AS
SELECT 
    di.id,
    di.numero_identificacion,
    di.numero_despacho,
    di.estado,
    di.fecha_creacion,
    di.usuario_responsable,
    
    -- Información del importador
    cli_imp.razon_social as importador_nombre,
    cli_imp.rut as importador_rut,
    
    -- Información del despachador
    prov_desp.razon_social as despachador_nombre,
    prov_desp.rut as despachador_rut,
    
    -- Información de origen
    p_origen.nombre as pais_origen_nombre,
    p_adq.nombre as pais_adquisicion_nombre,
    vt.descripcion as via_transporte_desc,
    
    -- Totales
    di.valor_fob_total,
    di.valor_cif_total,
    di.total_bultos,
    di.peso_bruto_total,
    
    -- Información de aduana
    ca.glosa as aduana_nombre
    
FROM operaciones.declaraciones_ingreso di
LEFT JOIN entidades.clientes cli_imp ON di.consignatario_id = cli_imp.id
LEFT JOIN entidades.proveedores prov_desp ON di.despachador_id = prov_desp.id
LEFT JOIN sna.paises p_origen ON di.pais_origen = p_origen.codigo_pais
LEFT JOIN sna.paises p_adq ON di.pais_adquisicion = p_adq.codigo_pais
LEFT JOIN sna.vias_transporte vt ON di.via_transporte = vt.codigo
LEFT JOIN sna.codigos_aduanas ca ON di.aduana_codigo = ca.codigo;

-- Vista para resumen de ítems por declaración
CREATE OR REPLACE VIEW operaciones.vista_din_items_resumen AS
SELECT 
    declaracion_id,
    COUNT(*) as total_items,
    SUM(valor_fob_item) as total_fob,
    SUM(valor_cif_item) as total_cif,
    SUM(cantidad_mercancia) as total_cantidad
FROM operaciones.din_items 
GROUP BY declaracion_id;

-- Vista para operaciones por usuario (NUEVA)
CREATE OR REPLACE VIEW operaciones.vista_operaciones_usuario AS
SELECT 
    d.numero_despacho,
    d.estado,
    d.fecha_creacion,
    d.usuario_creador,
    d.usuario_actualizacion,
    di.numero_identificacion as din_numero,
    di.usuario_responsable,
    COUNT(p.id) as procedimientos_activos
FROM operaciones.despachos d
LEFT JOIN operaciones.declaraciones_ingreso di ON d.numero_despacho = di.numero_despacho
LEFT JOIN operaciones.procedimientos p ON d.numero_despacho = p.numero_despacho AND p.estado != 'completado'
GROUP BY d.numero_despacho, d.estado, d.fecha_creacion, d.usuario_creador, 
         d.usuario_actualizacion, di.numero_identificacion, di.usuario_responsable;

-- 9. COMENTARIOS EN TABLAS
-- ==========================================

COMMENT ON SCHEMA sna IS 'Códigos y catálogos oficiales del Servicio Nacional de Aduanas';
COMMENT ON SCHEMA entidades IS 'Clientes, proveedores y representantes legales';
COMMENT ON SCHEMA operaciones IS 'Procesos aduaneros: despachos, declaraciones DIN, procedimientos';

COMMENT ON TABLE operaciones.declaraciones_ingreso IS 'Formularios DIN (Declaración de Ingreso Nacional)';
COMMENT ON TABLE operaciones.din_items IS 'Ítems/mercancías de cada declaración de ingreso';
COMMENT ON TABLE operaciones.auditoria_operaciones IS 'Registro de auditoría de todas las operaciones realizadas';
COMMENT ON TABLE sna.codigos_aduanas IS 'Códigos oficiales de aduanas según Anexo 51-1';
COMMENT ON TABLE sna.codigos_arancelarios IS 'Códigos del Arancel Aduanero Nacional';
COMMENT ON TABLE entidades.clientes IS 'Importadores y exportadores (clientes de la agencia)';
COMMENT ON TABLE entidades.proveedores IS 'Despachadores, transportistas y almacenistas';

-- Fin del script de inicialización
