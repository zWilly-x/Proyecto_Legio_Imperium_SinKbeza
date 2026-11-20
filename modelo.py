"""
modelo.py — MODELO (la "M" de MVC) y CAPA DE LÓGICA DE NEGOCIO.

Aquí están las 14 clases del diagrama de clases del informe (Senado, Consul,
Legatus, Legion, TipoUnidad, Unidad, EstrategiaTactica, MotorCombate, Combate,
Turno, EtapaCombate, Campania, Bitacora y EventoBitacora) y todas las reglas
del enunciado: contratación, estrategias, daño, mantenimiento y conversiones.

Este archivo NO conoce Flask ni la base de datos: solo recibe datos, aplica
reglas y lanza ErrorDominio cuando algo no está permitido.

Índice del archivo:
    1. Constantes de las reglas (cambiar valores aquí)
    2. Utilidades de validación
    3. Catálogo de unidades: TipoUnidad y Unidad
    4. Estrategias tácticas
    5. Jerarquía: Senado, Consul, Legatus y Legion
    6. Bitácora: Bitacora y EventoBitacora
    7. Motor de combate
    8. Combate, Turno y EtapaCombate
    9. Campania (incluye guardar y cargar como diccionario)
"""

import math
import random
import re
import unicodedata


# =============================================================================
# 1. CONSTANTES DE LAS REGLAS
#    Si el profesor pide cambiar un precio o un porcentaje, se cambia aquí.
# =============================================================================

LIMITE_BONIFICACION_LEGATUS = 25        # %ATK y %DEF deben estar entre -25 y +25
PRESUPUESTO_MAXIMO = 1_000_000_000      # tope para evitar números absurdos
MAX_UNIDADES_POR_TIPO = 10_000          # tope para que el combate no se vuelva lento
LARGO_MAXIMO_NOMBRE = 40

# Sinergias y habilidades especiales (en tanto por uno: 0.20 = 20 %)
REDUCCION_DANIO_LEGIONARIO = 0.20       # Legionario en Triplex Acies u Orbis
BONO_CABALLERIA_VS_LEGIONARIO = 0.20    # carga de la Caballería
BONO_BALLESTA_VS_CABALLERIA = 0.50      # artillería contra Caballería
DEF_POR_GRUPO_INGENIEROS = 0.01         # +1 % DEF global por cada 10 ingenieros
DANIO_BALLESTA_POR_GRUPO_INGENIEROS = 0.02  # +2 % daño de Ballesta por cada 10
TAMANO_GRUPO_INGENIEROS = 10
REDUCCION_MANTENIMIENTO_ESCLAVOS = 0.15  # -15 % mantenimiento por cada 50 esclavos
TAMANO_GRUPO_ESCLAVOS = 50

# Identificadores internos de los tipos (sin tildes) en el orden en que se muestran.
ORDEN_TIPOS = ['Legionario', 'Caballeria', 'Ballesta', 'Ingeniero', 'Esclavo']

# Tipos que pueden recibir la conversión de esclavos.
TIPOS_CONVERTIBLES = ['Legionario', 'Caballeria']

# Tipos capaces de atacar (Ingenieros y Esclavos no atacan, CA074).
TIPOS_QUE_ATACAN = ['Legionario', 'Caballeria', 'Ballesta']

# Si pasan estos turnos seguidos sin que ninguna legión pierda HP, el combate termina
# en empate por estancamiento (si no, podría no terminar nunca).
TURNOS_SIN_DANIO_PARA_EMPATE = 3


# =============================================================================
# 2. UTILIDADES DE VALIDACIÓN
# =============================================================================

class ErrorDominio(Exception):
    """Error de una regla de la simulación. Su mensaje se muestra tal cual al usuario."""


def redondear(valor):
    """Redondea al entero más cercano; 0,5 sube (CA085). round() de Python no sirve
    porque redondea 2,5 a 2."""
    return int(math.floor(valor + 0.5))


# Números escritos como texto: solo dígitos 0-9, con signo y decimales opcionales.
# Así se rechazan formas que Python sí aceptaría, como "1_000", "1e3" o dígitos de otros alfabetos.
PATRON_NUMERO = re.compile(r'[+-]?[0-9]+(\.[0-9]+)?')


def leer_entero(valor, campo, minimo, maximo):
    """Convierte lo que escribió el usuario en un entero válido o lanza ErrorDominio."""
    if isinstance(valor, bool):  # True/False también son enteros en Python
        raise ErrorDominio(f'{campo}: debe ser un número entero.')
    if isinstance(valor, str):
        valor = valor.strip()
        if valor == '':
            raise ErrorDominio(f'{campo}: es obligatorio.')
        if not PATRON_NUMERO.fullmatch(valor):
            raise ErrorDominio(f'{campo}: debe ser un número entero.')
    try:
        numero = float(valor)
    except (TypeError, ValueError):
        raise ErrorDominio(f'{campo}: debe ser un número entero.')
    if not math.isfinite(numero) or numero != int(numero):
        raise ErrorDominio(f'{campo}: debe ser un número entero.')
    numero = int(numero)
    if numero < minimo or numero > maximo:
        raise ErrorDominio(f'{campo}: debe estar entre {minimo} y {maximo}.')
    return numero


def leer_decimal(valor, campo, minimo, maximo):
    """Igual que leer_entero, pero acepta decimales (por ejemplo 12,5)."""
    if isinstance(valor, bool):
        raise ErrorDominio(f'{campo}: debe ser un número.')
    if isinstance(valor, str):
        valor = valor.strip().replace(',', '.')
        if valor == '':
            raise ErrorDominio(f'{campo}: es obligatorio.')
        if not PATRON_NUMERO.fullmatch(valor):
            raise ErrorDominio(f'{campo}: debe ser un número.')
    try:
        numero = float(valor)
    except (TypeError, ValueError):
        raise ErrorDominio(f'{campo}: debe ser un número.')
    if not math.isfinite(numero) or numero < minimo or numero > maximo:
        raise ErrorDominio(f'{campo}: debe estar entre {minimo} y {maximo}.')
    return numero


def leer_nombre(valor, campo):
    """Valida un nombre de texto: obligatorio y no demasiado largo."""
    if not isinstance(valor, str) or valor.strip() == '':
        raise ErrorDominio(f'{campo}: es obligatorio.')
    valor = ' '.join(valor.split())  # quita espacios repetidos
    # Rechaza caracteres invisibles o de control (por ejemplo el carácter nulo o el que invierte el texto).
    if any(unicodedata.category(letra) in ('Cc', 'Cf', 'Co', 'Cs') for letra in valor):
        raise ErrorDominio(f'{campo}: contiene caracteres invisibles o no permitidos.')
    if len(valor) > LARGO_MAXIMO_NOMBRE:
        raise ErrorDominio(f'{campo}: máximo {LARGO_MAXIMO_NOMBRE} caracteres.')
    return valor


# =============================================================================
# 3. CATÁLOGO DE UNIDADES (Tabla 2 del enunciado)
# =============================================================================

class TipoUnidad:
    """Datos fijos de un tipo de unidad: lo que dice la Tabla 2."""

    def __init__(self, nombre, hp_base, atk_base, def_base, costo, descripcion, habilidad_especial):
        self.nombre = nombre
        self.hp_base = hp_base
        self.atk_base = atk_base
        self.def_base = def_base
        self.costo = costo
        self.descripcion = descripcion
        self.habilidad_especial = habilidad_especial

    def obtener_atributos_base(self):
        return {'hp': self.hp_base, 'atk': self.atk_base, 'def': self.def_base}

    def obtener_costo(self):
        return self.costo


# Clave interna -> TipoUnidad. Tabla 2: HP, ATK, DEF y costo en denarios.
CATALOGO = {
    'Legionario': TipoUnidad('Legionario', 20, 25, 35, 5, 'Infantería pesada disciplinada.',
                             'Ignora 20 % del daño en Triplex Acies y Orbis.'),
    'Caballeria': TipoUnidad('Caballería', 50, 45, 15, 12, 'Fuerza de choque y flanqueo.',
                             'Causa 20 % de daño adicional a Legionarios.'),
    'Ballesta': TipoUnidad('Ballesta', 15, 60, 5, 20, 'Artillería a distancia.',
                           'Causa 50 % de daño extra a Caballería.'),
    'Ingeniero': TipoUnidad('Ingeniero', 2, 5, 20, 10, 'Unidad técnica.',
                            '+1 % DEF global y +2 % daño de Ballestas por cada 10.'),
    'Esclavo': TipoUnidad('Esclavo / Auxiliar', 5, 2, 5, 1, 'Logística y acarreo.',
                          '-15 % de mantenimiento por cada 50.'),
}


class Unidad:
    """Un soldado concreto: tiene su propio HP actual."""

    def __init__(self, id_unidad, clave_tipo, hp_actual=None):
        self.id_unidad = id_unidad
        self.clave_tipo = clave_tipo          # 'Legionario', 'Caballeria', ...
        self.tipo = CATALOGO[clave_tipo]      # el TipoUnidad con sus valores base
        self.hp_actual = self.tipo.hp_base if hp_actual is None else hp_actual
        self._viva = self.hp_actual > 0

    def recibir_danio(self, cantidad):
        """Resta HP. Devuelve True si la unidad murió con este golpe."""
        self.hp_actual -= cantidad
        if self._viva and self.hp_actual <= 0:
            self._viva = False
            return True
        return False

    def esta_viva(self):
        return self._viva

    def obtener_ataque_base(self):
        return self.tipo.atk_base

    def obtener_defensa_base(self):
        return self.tipo.def_base

    def convertir_tipo(self, nueva_clave):
        """Convierte (un esclavo) en otro tipo, con HP completo del nuevo tipo (CA146)."""
        self.clave_tipo = nueva_clave
        self.tipo = CATALOGO[nueva_clave]
        self.hp_actual = self.tipo.hp_base
        self._viva = True


# =============================================================================
# 4. ESTRATEGIAS TÁCTICAS (Tabla 3 del enunciado)
# =============================================================================

class EstrategiaTactica:
    """Una formación: modificadores de ATK/DEF, condición y sinergia."""

    def __init__(self, nombre, modificador_atk, modificador_def, condicion_aplicacion, descripcion_sinergia):
        self.nombre = nombre
        self.modificador_atk = modificador_atk
        self.modificador_def = modificador_def
        self.condicion_aplicacion = condicion_aplicacion
        self.descripcion_sinergia = descripcion_sinergia

    def validar_aplicabilidad(self, legion, legionarios_extra=0, caballeria_extra=0):
        """Comprueba si la legión puede usar esta estrategia.
        Los 'extra' permiten contar unidades que se van a convertir en la reagrupación."""
        if self.nombre == 'Cuneus':
            if legion.contar_unidades_vivas('Caballeria') + caballeria_extra < 1:
                raise ErrorDominio(f'{legion.nombre}: Cuneus requiere al menos una Caballería viva.')
        if self.nombre == 'Orbis':
            if legion.contar_unidades_vivas('Legionario') + legionarios_extra < 1:
                raise ErrorDominio(f'{legion.nombre}: Orbis requiere al menos un Legionario vivo.')

    def obtener_modificador_ataque(self):
        return self.modificador_atk

    def obtener_modificador_defensa(self):
        return self.modificador_def

    def calcular_sinergias(self, legion):
        """Bonos que dependen de la composición. Se evalúan al inicio de cada etapa."""
        sinergia = {'def_global': 0.0, 'danio_ballesta': 0.0}
        if self.nombre == 'Triplex Acies':
            vivas = legion.contar_unidades_vivas()
            if vivas > 0 and legion.contar_unidades_vivas('Legionario') / vivas >= 0.5:
                sinergia['def_global'] = 0.35
                sinergia['danio_ballesta'] = 0.15
        return sinergia

    def aplicar_reglas_especiales(self):
        """Reglas fijas de cada formación, como diccionario fácil de consultar."""
        return {
            'tipos_que_atacan': ['Legionario', 'Ballesta'] if self.nombre == 'Orbis'
                                else ['Legionario', 'Caballeria', 'Ballesta'],
            'protegidos': ['Ballesta', 'Ingeniero'] if self.nombre == 'Orbis' else [],
            'reduce_danio_legionario': self.nombre in ('Triplex Acies', 'Orbis'),
            'caballeria_ataca_esclavos': self.nombre == 'Cuneus',
            'bono_danio_caballeria': 0.50 if self.nombre == 'Cuneus' else 0.0,
            'danio_recibido_extra': 0.50 if self.nombre == 'Cuneus' else 0.0,
        }


ESTRATEGIAS = {
    'Triplex Acies': EstrategiaTactica('Triplex Acies', 0.10, 0.10, 'Siempre disponible.',
                                       'Si al menos 50 % son Legionarios: +35 % DEF global y +15 % daño de Ballestas.'),
    'Cuneus': EstrategiaTactica('Cuneus', 0.45, -0.25, 'Requiere al menos una Caballería viva.',
                                '+50 % daño de Caballería, pero recibe +50 % de daño.'),
    'Orbis': EstrategiaTactica('Orbis', -0.35, 0.60, 'Requiere al menos un Legionario vivo.',
                               'La Caballería no ataca; Ballestas e Ingenieros no reciben daño.'),
}

ESTRATEGIA_INICIAL = 'Triplex Acies'


# =============================================================================
# 5. JERARQUÍA: SENADO -> CÓNSUL -> LEGATUS -> LEGIÓN
# =============================================================================

class Senado:
    """Nivel superior: representado por dos cónsules."""

    def __init__(self, nombre='Senatus Populusque Romanus'):
        self.nombre = nombre
        self.consules = []
        self.asignar_consul(Consul('Cónsul I'))
        self.asignar_consul(Consul('Cónsul II'))

    def asignar_consul(self, consul):
        self.consules.append(consul)

    def obtener_consules(self):
        return self.consules


class Consul:
    def __init__(self, nombre):
        self.nombre = nombre
        self.legatus = []

    def asignar_legatus(self, legatus):
        self.legatus.append(legatus)

    def obtener_legatus(self):
        return self.legatus


class Legatus:
    """Comandante de una legión: bonificaciones y presupuesto."""

    def __init__(self, nombre, porcentaje_atk, porcentaje_def, presupuesto, indice_consul):
        self.nombre = leer_nombre(nombre, 'Nombre del Legatus')
        self.indice_consul = leer_entero(indice_consul, 'Cónsul', 0, 1)
        self.configurar_bonificaciones(porcentaje_atk, porcentaje_def)
        self.presupuesto = leer_entero(presupuesto, 'Presupuesto', 0, PRESUPUESTO_MAXIMO)
        self.legion = None

    def configurar_bonificaciones(self, porcentaje_atk, porcentaje_def):
        self.porcentaje_atk, self.porcentaje_def = self.validar_bonificaciones(porcentaje_atk, porcentaje_def)
        self._porcentaje_costo = self.calcular_porcentaje_costo()

    @staticmethod
    def validar_bonificaciones(porcentaje_atk, porcentaje_def):
        limite = LIMITE_BONIFICACION_LEGATUS
        atk = leer_decimal(porcentaje_atk, '%ATK del Legatus', -limite, limite)
        defensa = leer_decimal(porcentaje_def, '%DEF del Legatus', -limite, limite)
        return atk, defensa

    def calcular_porcentaje_costo(self):
        """%Costo = %ATK + %DEF. Solo afecta el mantenimiento, no la contratación."""
        return self.porcentaje_atk + self.porcentaje_def

    def verificar_presupuesto(self, monto):
        return monto <= self.presupuesto

    def descontar_presupuesto(self, monto):
        if not self.verificar_presupuesto(monto):
            raise ErrorDominio(f'Presupuesto insuficiente: faltan {monto - self.presupuesto} denarios.')
        self.presupuesto -= monto


class Legion:
    """Una legión: su Legatus, sus unidades y la estrategia vigente."""

    def __init__(self, nombre, legatus):
        self.nombre = leer_nombre(nombre, 'Nombre de la Legión')
        self.legatus = legatus
        legatus.legion = self
        self.unidades = []
        self.estrategia = ESTRATEGIAS[ESTRATEGIA_INICIAL]
        self._ataque_total = 0.0
        self._defensa_total = 0.0
        self._costo_mantenimiento = 0
        self._siguiente_id = 1

    # ---------- Consultas sobre la composición ----------

    def unidades_vivas(self, clave_tipo=None):
        return [u for u in self.unidades
                if u.esta_viva() and (clave_tipo is None or u.clave_tipo == clave_tipo)]

    def contar_unidades_vivas(self, clave_tipo=None):
        return len(self.unidades_vivas(clave_tipo))

    def tiene_unidades_combatientes(self):
        """True si queda alguien vivo que no sea Esclavo (condición de término)."""
        return any(u.esta_viva() and u.clave_tipo != 'Esclavo' for u in self.unidades)

    # ---------- Contratación ----------

    @staticmethod
    def leer_cantidades(cantidades):
        """Convierte {'Legionario': '10', ...} en {'Legionario': 10, ...} validado."""
        if not isinstance(cantidades, dict):
            raise ErrorDominio('Cantidades inválidas.')
        resultado = {}
        for clave in ORDEN_TIPOS:
            nombre = CATALOGO[clave].nombre
            resultado[clave] = leer_entero(cantidades.get(clave, 0) or 0, f'Cantidad de {nombre}',
                                           0, MAX_UNIDADES_POR_TIPO)
        return resultado

    @staticmethod
    def calcular_costo_contratacion(cantidades):
        """Suma de cantidad × costo. El %Costo del Legatus NO se aplica aquí (CA027)."""
        return sum(cantidades[clave] * CATALOGO[clave].costo for clave in ORDEN_TIPOS)

    def agregar_unidades(self, cantidades):
        """Contrata unidades: valida, cobra y las crea con HP completo (CA028-CA032)."""
        cantidades = self.leer_cantidades(cantidades)
        if sum(cantidades.values()) == 0:
            raise ErrorDominio('Debe contratar al menos una unidad.')
        # Sin Legionarios, Caballería ni Ballestas la legión nunca podría atacar (CA036, CA074).
        if not any(cantidades[t] + self.contar_unidades_vivas(t) for t in TIPOS_QUE_ATACAN):
            raise ErrorDominio('Contrate al menos un Legionario, una Caballería o una Ballesta: '
                               'Ingenieros y Esclavos no atacan.')
        for clave in ORDEN_TIPOS:
            if self.contar_unidades_vivas(clave) + cantidades[clave] > MAX_UNIDADES_POR_TIPO:
                raise ErrorDominio(f'Máximo {MAX_UNIDADES_POR_TIPO} unidades de {CATALOGO[clave].nombre} por legión.')
        costo = self.calcular_costo_contratacion(cantidades)
        if not self.legatus.verificar_presupuesto(costo):
            raise ErrorDominio(f'El costo ({costo}) supera el presupuesto ({self.legatus.presupuesto}). '
                               f'Faltan {costo - self.legatus.presupuesto} denarios.')
        self.legatus.descontar_presupuesto(costo)
        for clave in ORDEN_TIPOS:
            for _ in range(cantidades[clave]):
                self.unidades.append(Unidad(self._siguiente_id, clave))
                self._siguiente_id += 1
        return costo

    # ---------- Atributos de combate ----------

    def calcular_modificadores(self):
        """Multiplicadores vigentes. Se aplican de forma multiplicativa (CA060, CA061)."""
        reglas = self.estrategia.aplicar_reglas_especiales()
        sinergia = self.estrategia.calcular_sinergias(self)
        grupos_ingenieros = self.contar_unidades_vivas('Ingeniero') // TAMANO_GRUPO_INGENIEROS
        multiplicador_atk = (1 + self.legatus.porcentaje_atk / 100) * (1 + self.estrategia.modificador_atk)
        multiplicador_def = ((1 + self.legatus.porcentaje_def / 100)
                             * (1 + self.estrategia.modificador_def)
                             * (1 + sinergia['def_global'])
                             * (1 + DEF_POR_GRUPO_INGENIEROS * grupos_ingenieros))
        bono_ballesta = ((1 + sinergia['danio_ballesta'])
                         * (1 + DANIO_BALLESTA_POR_GRUPO_INGENIEROS * grupos_ingenieros))
        return {'atk': multiplicador_atk, 'def': multiplicador_def,
                'bono_ballesta': bono_ballesta, 'reglas': reglas}

    def calcular_ataque_total(self):
        """Suma del ATK de las unidades vivas que pueden atacar, con modificadores."""
        modificadores = self.calcular_modificadores()
        tipos = modificadores['reglas']['tipos_que_atacan']
        suma = sum(u.obtener_ataque_base() for u in self.unidades_vivas() if u.clave_tipo in tipos)
        self._ataque_total = suma * modificadores['atk']
        return self._ataque_total

    def calcular_defensa_total(self):
        """Suma de la DEF de todas las unidades vivas, con modificadores."""
        modificadores = self.calcular_modificadores()
        suma = sum(u.obtener_defensa_base() for u in self.unidades_vivas())
        self._defensa_total = suma * modificadores['def']
        return self._defensa_total

    def calcular_mantenimiento(self):
        """Sueldos: costo de las unidades vivas, con %Costo del Legatus y descuento
        por grupos de 50 esclavos (máximo 100 % de descuento)."""
        base = sum(u.tipo.costo for u in self.unidades_vivas())
        con_legatus = base * (1 + self.legatus.calcular_porcentaje_costo() / 100)
        grupos_esclavos = self.contar_unidades_vivas('Esclavo') // TAMANO_GRUPO_ESCLAVOS
        factor = max(0.0, 1 - REDUCCION_MANTENIMIENTO_ESCLAVOS * grupos_esclavos)
        self._costo_mantenimiento = max(0, redondear(con_legatus * factor))
        return self._costo_mantenimiento

    # ---------- Reagrupación ----------

    def validar_conversion(self, a_legionarios, a_caballeria):
        """Revisa una conversión sin aplicarla. Devuelve (cantidades, costo)."""
        a_legionarios = leer_entero(a_legionarios or 0, f'{self.nombre}: esclavos a Legionarios', 0, MAX_UNIDADES_POR_TIPO)
        a_caballeria = leer_entero(a_caballeria or 0, f'{self.nombre}: esclavos a Caballería', 0, MAX_UNIDADES_POR_TIPO)
        disponibles = self.contar_unidades_vivas('Esclavo')
        if a_legionarios + a_caballeria > disponibles:
            raise ErrorDominio(f'{self.nombre}: solo tiene {disponibles} esclavos vivos para convertir.')
        costo = (a_legionarios * CATALOGO['Legionario'].costo
                 + a_caballeria * CATALOGO['Caballeria'].costo)
        if not self.legatus.verificar_presupuesto(costo):
            raise ErrorDominio(f'{self.nombre}: la conversión cuesta {costo} y el saldo es {self.legatus.presupuesto}.')
        return a_legionarios, a_caballeria, costo

    def convertir_esclavos(self, a_legionarios, a_caballeria):
        """Convierte esclavos vivos en Legionarios o Caballería pagando el precio completo."""
        a_legionarios, a_caballeria, costo = self.validar_conversion(a_legionarios, a_caballeria)
        esclavos = self.unidades_vivas('Esclavo')
        for unidad in esclavos[:a_legionarios]:
            unidad.convertir_tipo('Legionario')
        for unidad in esclavos[a_legionarios:a_legionarios + a_caballeria]:
            unidad.convertir_tipo('Caballeria')
        self.legatus.descontar_presupuesto(costo)
        return costo

    def seleccionar_estrategia(self, nombre):
        if not isinstance(nombre, str) or nombre not in ESTRATEGIAS:
            raise ErrorDominio(f'Estrategia desconocida: {nombre}.')
        estrategia = ESTRATEGIAS[nombre]
        estrategia.validar_aplicabilidad(self)
        self.estrategia = estrategia

    # ---------- Barra de salud (CA132) ----------

    def hp_actual_total(self):
        return sum(max(0, u.hp_actual) for u in self.unidades)

    def hp_maximo_referencia(self):
        """Incluye a los muertos; si una unidad se convirtió, cuenta el HP de su nuevo tipo."""
        return sum(u.tipo.hp_base for u in self.unidades)


# =============================================================================
# 6. BITÁCORA
# =============================================================================

class EventoBitacora:
    def __init__(self, secuencia, tipo_evento, descripcion, numero_turno=None,
                 numero_etapa=None, legion_afectada=None, cantidad_bajas=0):
        self.secuencia = secuencia
        self.tipo_evento = tipo_evento
        self.descripcion = descripcion
        self.numero_turno = numero_turno
        self.numero_etapa = numero_etapa
        self.legion_afectada = legion_afectada   # nombre de la legión (texto)
        self.cantidad_bajas = cantidad_bajas

    def obtener_descripcion(self):
        prefijo = ''
        if self.numero_turno is not None:
            prefijo = f'[T{self.numero_turno}' + (f'·E{self.numero_etapa}' if self.numero_etapa else '') + '] '
        return prefijo + self.descripcion

    def a_dict(self):
        return dict(vars(self))


class Bitacora:
    def __init__(self):
        self.eventos = []
        self.total_eventos = 0

    def registrar_evento(self, tipo_evento, descripcion, numero_turno=None, numero_etapa=None,
                         legion_afectada=None, cantidad_bajas=0):
        self.total_eventos += 1
        evento = EventoBitacora(self.total_eventos, tipo_evento, descripcion, numero_turno,
                                numero_etapa, legion_afectada, cantidad_bajas)
        self.eventos.append(evento)
        return evento

    def registrar_baja(self, legion, clave_tipo, cantidad, numero_turno, numero_etapa):
        texto = f'{legion.nombre} pierde {cantidad} × {CATALOGO[clave_tipo].nombre}.'
        return self.registrar_evento('baja', texto, numero_turno, numero_etapa, legion.nombre, cantidad)

    def consultar_historial(self):
        return self.ordenar_eventos()

    def ordenar_eventos(self):
        return sorted(self.eventos, key=lambda evento: evento.secuencia)


# =============================================================================
# 7. MOTOR DE COMBATE: resuelve UNA etapa (un ataque de una legión a otra)
# =============================================================================

class MotorCombate:

    def __init__(self, generador_aleatorio):
        self.azar = generador_aleatorio      # random.Random con semilla (repetible)
        self.fondo_danio_por_tipo = {}
        self.danio_restante = 0

    def calcular_ataque_total(self, atacante):
        return atacante.calcular_ataque_total()

    def calcular_defensa_total(self, defensor):
        return defensor.calcular_defensa_total()

    def calcular_danio_global(self, ataque_total, defensa_total):
        """Daño = ATK_TOTAL - DEF_TOTAL; si es 0 o negativo, no hay daño (CA064)."""
        diferencia = ataque_total - defensa_total
        return redondear(diferencia) if diferencia > 0 else 0

    def distribuir_danio(self, atacante, danio_global):
        """Reparte el daño global entre los tipos que atacan según su cantidad de
        unidades vivas, usando el método de mayores restos (CA067, CA068)."""
        tipos = atacante.estrategia.aplicar_reglas_especiales()['tipos_que_atacan']
        conteos = {t: atacante.contar_unidades_vivas(t) for t in tipos if atacante.contar_unidades_vivas(t) > 0}
        total = sum(conteos.values())
        if danio_global <= 0 or total == 0:
            return {}
        partes = {t: danio_global * c // total for t, c in conteos.items()}
        restos = {t: danio_global * c % total for t, c in conteos.items()}
        sobrante = danio_global - sum(partes.values())
        for tipo in sorted(conteos, key=lambda t: restos[t], reverse=True)[:sobrante]:
            partes[tipo] += 1
        return partes

    def verificar_objetivos_validos(self, tipo_atacante, objetivos_por_tipo, estrategia_atacante):
        """Tipos enemigos a los que puede golpear este tipo atacante (CA069-CA074)."""
        if tipo_atacante == 'Ballesta':
            permitidos = list(ORDEN_TIPOS)
        elif tipo_atacante in ('Legionario', 'Caballeria'):
            quedan_frontales = objetivos_por_tipo['Legionario'] or objetivos_por_tipo['Caballeria']
            if quedan_frontales:
                permitidos = ['Legionario', 'Caballeria']
                if tipo_atacante == 'Caballeria' and estrategia_atacante.aplicar_reglas_especiales()['caballeria_ataca_esclavos']:
                    permitidos.append('Esclavo')
            else:
                permitidos = ['Ballesta', 'Ingeniero', 'Esclavo']
        else:
            permitidos = []   # Ingenieros y Esclavos no atacan
        return [t for t in permitidos if objetivos_por_tipo[t]]

    def seleccionar_objetivo(self, tipos_validos, objetivos_por_tipo):
        """Elige al azar UNA unidad; todas las elegibles tienen la misma probabilidad (CA075)."""
        total = sum(len(objetivos_por_tipo[t]) for t in tipos_validos)
        if total == 0:
            return None
        posicion = self.azar.randrange(total)
        for tipo in tipos_validos:
            if posicion < len(objetivos_por_tipo[tipo]):
                return objetivos_por_tipo[tipo][posicion]
            posicion -= len(objetivos_por_tipo[tipo])
        return None

    def calcular_danio_individual(self, tipo_atacante, objetivo, mod_atacante, mod_defensor):
        """Daño de un golpe: ATK - DEF (mínimo 1) con todos los bonos (CA078-CA085)."""
        atk = CATALOGO[tipo_atacante].atk_base * mod_atacante['atk']
        defensa = objetivo.obtener_defensa_base() * mod_defensor['def']
        danio = atk - defensa if atk > defensa else 1
        reglas_atq = mod_atacante['reglas']
        reglas_def = mod_defensor['reglas']
        if tipo_atacante == 'Caballeria' and objetivo.clave_tipo == 'Legionario':
            danio *= 1 + BONO_CABALLERIA_VS_LEGIONARIO
        if tipo_atacante == 'Ballesta' and objetivo.clave_tipo == 'Caballeria':
            danio *= 1 + BONO_BALLESTA_VS_CABALLERIA
        if tipo_atacante == 'Ballesta':
            danio *= mod_atacante['bono_ballesta']
        if tipo_atacante == 'Caballeria':
            danio *= 1 + reglas_atq['bono_danio_caballeria']
        danio *= 1 + reglas_def['danio_recibido_extra']
        if objetivo.clave_tipo == 'Legionario' and reglas_def['reduce_danio_legionario']:
            danio *= 1 - REDUCCION_DANIO_LEGIONARIO
        return max(1, redondear(danio))

    def aplicar_danio(self, objetivo, cantidad, mod_defensor):
        """Aplica el golpe. Ballestas e Ingenieros en Orbis no pierden HP (CA087).
        Devuelve True si el objetivo murió."""
        if objetivo.clave_tipo in mod_defensor['reglas']['protegidos']:
            return False
        return objetivo.recibir_danio(cantidad)

    def resolver_etapa(self, atacante, defensor):
        """Ejecuta un ataque completo. Devuelve los números de la etapa."""
        # Los atributos se calculan una vez, al inicio de la etapa (CA059).
        mod_atacante = atacante.calcular_modificadores()
        mod_defensor = defensor.calcular_modificadores()
        ataque_total = self.calcular_ataque_total(atacante)
        defensa_total = self.calcular_defensa_total(defensor)
        danio_global = self.calcular_danio_global(ataque_total, defensa_total)
        self.fondo_danio_por_tipo = self.distribuir_danio(atacante, danio_global)

        objetivos_por_tipo = {t: defensor.unidades_vivas(t) for t in ORDEN_TIPOS}
        bajas = {t: 0 for t in ORDEN_TIPOS}

        for tipo_atacante in ORDEN_TIPOS:
            self.danio_restante = self.fondo_danio_por_tipo.get(tipo_atacante, 0)
            while self.danio_restante > 0:
                tipos_validos = self.verificar_objetivos_validos(tipo_atacante, objetivos_por_tipo, atacante.estrategia)
                objetivo = self.seleccionar_objetivo(tipos_validos, objetivos_por_tipo)
                if objetivo is None:
                    break   # sin objetivos: el daño restante se pierde (CA077)
                danio = self.calcular_danio_individual(tipo_atacante, objetivo, mod_atacante, mod_defensor)
                consumo = min(danio, self.danio_restante)
                self.danio_restante -= consumo
                if self.aplicar_danio(objetivo, consumo, mod_defensor):
                    objetivos_por_tipo[objetivo.clave_tipo].remove(objetivo)
                    bajas[objetivo.clave_tipo] += 1

        return {'ataque_total': ataque_total, 'defensa_total': defensa_total,
                'danio_global': danio_global, 'bajas': bajas}


# =============================================================================
# 8. COMBATE, TURNO Y ETAPA
# =============================================================================

class EtapaCombate:
    def __init__(self, numero_etapa, indice_atacante, indice_defensor):
        self.numero_etapa = numero_etapa
        self.indice_atacante = indice_atacante    # 0 = legión A, 1 = legión B
        self.indice_defensor = indice_defensor
        self.ataque_total = 0.0
        self.defensa_total = 0.0
        self.danio_global = 0
        self.bajas_por_tipo = {t: 0 for t in ORDEN_TIPOS}
        self.cantidad_bajas = 0
        self.hp_perdido = 0          # HP que perdió el defensor (sirve para detectar estancamiento)
        self.finalizada = False

    def ejecutar_etapa(self, combate, numero_turno):
        atacante = combate.legiones[self.indice_atacante]
        defensor = combate.legiones[self.indice_defensor]
        combate.bitacora.registrar_evento('etapa', f'Inicia la etapa: {atacante.nombre} ataca a {defensor.nombre}.',
                                          numero_turno, self.numero_etapa)
        hp_antes = defensor.hp_actual_total()
        resultado = combate.motor.resolver_etapa(atacante, defensor)
        self.hp_perdido = hp_antes - defensor.hp_actual_total()
        self.ataque_total = resultado['ataque_total']
        self.defensa_total = resultado['defensa_total']
        self.danio_global = resultado['danio_global']
        self.bajas_por_tipo = resultado['bajas']
        self.cantidad_bajas = sum(self.bajas_por_tipo.values())
        self.finalizada = True
        combate.bitacora.registrar_evento(
            'etapa', f'ATK total {self.ataque_total:.1f} contra DEF total {self.defensa_total:.1f}: '
                     f'daño global {self.danio_global}.', numero_turno, self.numero_etapa)
        self.registrar_bajas(combate.bitacora, defensor, numero_turno)

    def registrar_bajas(self, bitacora, defensor, numero_turno):
        for clave, cantidad in self.bajas_por_tipo.items():
            if cantidad > 0:
                bitacora.registrar_baja(defensor, clave, cantidad, numero_turno, self.numero_etapa)
        if self.cantidad_bajas == 0:
            bitacora.registrar_evento('baja', f'{defensor.nombre} no sufre bajas.', numero_turno, self.numero_etapa)

    def obtener_resultado(self):
        return {'numero_etapa': self.numero_etapa, 'indice_atacante': self.indice_atacante,
                'indice_defensor': self.indice_defensor, 'ataque_total': self.ataque_total,
                'defensa_total': self.defensa_total, 'danio_global': self.danio_global,
                'bajas_por_tipo': self.bajas_por_tipo, 'cantidad_bajas': self.cantidad_bajas,
                'hp_perdido': self.hp_perdido, 'finalizada': self.finalizada}


class Turno:
    def __init__(self, numero, indice_atacante_primero, estrategia_legion_a, estrategia_legion_b):
        self.numero = numero
        self.indice_atacante_primero = indice_atacante_primero
        self.estrategia_legion_a = estrategia_legion_a     # nombres de estrategia
        self.estrategia_legion_b = estrategia_legion_b
        self.etapas = []
        self.finalizado = False
        self.mantenimiento = [0, 0]

    def ejecutar_primera_etapa(self, combate):
        etapa = EtapaCombate(1, self.indice_atacante_primero, 1 - self.indice_atacante_primero)
        etapa.ejecutar_etapa(combate, self.numero)
        self.etapas.append(etapa)

    def ejecutar_segunda_etapa(self, combate):
        # Los roles se invierten (CA096).
        etapa = EtapaCombate(2, 1 - self.indice_atacante_primero, self.indice_atacante_primero)
        etapa.ejecutar_etapa(combate, self.numero)
        self.etapas.append(etapa)

    def calcular_mantenimiento(self, combate):
        self.mantenimiento = [legion.calcular_mantenimiento() for legion in combate.legiones]
        return self.mantenimiento

    def procesar_reagrupacion(self, combate):
        """Cobra los sueldos SOLO si ambas legiones pueden pagar (CA106-CA108).
        Devuelve la lista de legiones que no pudieron pagar."""
        montos = self.calcular_mantenimiento(combate)
        morosas = [legion for legion, monto in zip(combate.legiones, montos)
                   if not legion.legatus.verificar_presupuesto(monto)]
        if morosas:
            return morosas
        for legion, monto in zip(combate.legiones, montos):
            legion.legatus.descontar_presupuesto(monto)
            combate.bitacora.registrar_evento('mantenimiento', f'{legion.nombre} paga {monto} denarios de mantenimiento '
                                              f'(saldo {legion.legatus.presupuesto}).', self.numero, None, legion.nombre)
        return []

    def planificar_siguiente_turno(self, combate):
        """El que atacó primero ahora defiende primero (CA111)."""
        a, b = combate.legiones
        return Turno(self.numero + 1, 1 - self.indice_atacante_primero, a.estrategia.nombre, b.estrategia.nombre)


class Combate:
    """Controla el orden: etapa 1, etapa 2, reagrupación, siguiente turno, fin."""

    MODOS = ('paso_a_paso', 'automatico')

    def __init__(self, legion_a, legion_b, bitacora, semilla=None):
        self.legion_a = legion_a
        self.legion_b = legion_b
        self.bitacora = bitacora
        self.turnos = []
        self.turno_actual = 0
        self.etapa_siguiente = 1
        self.modo_simulacion = 'paso_a_paso'
        self.estado = 'preparado'    # preparado, en_curso, reagrupacion, finalizado
        self.atacante_inicial = 0
        self.resultado = ''
        self.indice_ganador = None   # 0 o 1 = legión ganadora; None = empate o combate sin terminar
        self.turnos_sin_danio = 0    # turnos seguidos en que ninguna legión perdió HP
        self.semilla = random.randrange(1_000_000) if semilla is None else semilla
        self.motor = MotorCombate(random.Random(self.semilla))

    @property
    def legiones(self):
        return [self.legion_a, self.legion_b]

    def turno_en_curso(self):
        return self.turnos[-1] if self.turnos else None

    def preparar_combate(self, indice_atacante, modo):
        """Valida participantes y aplica Triplex Acies a ambas (CA033-CA039)."""
        for legion in self.legiones:
            if legion.contar_unidades_vivas() == 0:
                raise ErrorDominio(f'{legion.nombre} no tiene unidades contratadas.')
            if not legion.tiene_unidades_combatientes():
                raise ErrorDominio(f'{legion.nombre} solo tiene Esclavos/Auxiliares y no puede combatir.')
        self.atacante_inicial = leer_entero(indice_atacante, 'Legión atacante', 0, 1)
        self.cambiar_modo_simulacion(modo)
        for legion in self.legiones:
            legion.seleccionar_estrategia(ESTRATEGIA_INICIAL)

    def iniciar_combate(self):
        self.estado = 'en_curso'
        self.turno_actual = 1
        self.etapa_siguiente = 1
        self.turnos = [Turno(1, self.atacante_inicial, ESTRATEGIA_INICIAL, ESTRATEGIA_INICIAL)]
        self.bitacora.registrar_evento('combate', f'Comienza el combate: {self.legion_a.nombre} contra '
                                       f'{self.legion_b.nombre}. Ambas usan Triplex Acies.', 1)

    def cambiar_modo_simulacion(self, modo):
        if modo not in self.MODOS:
            raise ErrorDominio('Modo de simulación inválido.')
        self.modo_simulacion = modo

    def ejecutar_siguiente_etapa(self):
        if self.estado != 'en_curso':
            raise ErrorDominio('No se puede avanzar: el combate no está en una etapa de batalla.')
        turno = self.turno_en_curso()
        if self.etapa_siguiente == 1:
            turno.ejecutar_primera_etapa(self)
            if not self.verificar_fin_combate():
                self.etapa_siguiente = 2
            return

        turno.ejecutar_segunda_etapa(self)
        turno.finalizado = True
        self.bitacora.registrar_evento('turno', f'Termina el turno {turno.numero}.', turno.numero)
        if self.verificar_fin_combate():
            return
        morosas = turno.procesar_reagrupacion(self)
        if morosas:
            nombres = ' y '.join(legion.nombre for legion in morosas)
            ganadoras = [legion for legion in self.legiones if legion not in morosas]
            verbo = 'no pueden' if len(morosas) > 1 else 'no puede'
            self.finalizar_combate(f'{nombres} {verbo} pagar el mantenimiento.', ganadoras)
            return
        if self.verificar_estancamiento(turno):
            return
        self.estado = 'reagrupacion'

    def verificar_estancamiento(self, turno):
        """Empate si pasan TURNOS_SIN_DANIO_PARA_EMPATE turnos seguidos sin que nadie pierda HP
        (por ejemplo, si la DEF de ambas legiones supera el ATK del rival)."""
        if any(etapa.hp_perdido > 0 for etapa in turno.etapas):
            self.turnos_sin_danio = 0
            return False
        self.turnos_sin_danio += 1
        if self.turnos_sin_danio >= TURNOS_SIN_DANIO_PARA_EMPATE:
            self.finalizar_combate(f'Ninguna legión logró causar daño durante {self.turnos_sin_danio} '
                                   'turnos seguidos (estancamiento).', [])
            return True
        self.bitacora.registrar_evento('turno', f'Turno sin daño ({self.turnos_sin_danio} de '
                                       f'{TURNOS_SIN_DANIO_PARA_EMPATE}): si nadie causa daño, el combate '
                                       'terminará en empate.', turno.numero)
        return False

    def verificar_fin_combate(self):
        """Fin si una legión se queda solo con esclavos (o sin nadie)."""
        derrotadas = [legion for legion in self.legiones if not legion.tiene_unidades_combatientes()]
        if derrotadas:
            nombres = ' y '.join(legion.nombre for legion in derrotadas)
            ganadoras = [legion for legion in self.legiones if legion not in derrotadas]
            verbo = 'se quedan' if len(derrotadas) > 1 else 'se queda'
            self.finalizar_combate(f'{nombres} {verbo} sin tropas que no sean esclavos.', ganadoras)
            return True
        return False

    def finalizar_combate(self, motivo, ganadoras):
        self.estado = 'finalizado'
        if len(ganadoras) == 1:
            self.indice_ganador = self.legiones.index(ganadoras[0])
            self.resultado = f'Vence {ganadoras[0].nombre}. {motivo}'
        else:
            self.resultado = f'Empate. {motivo}'
        self.bitacora.registrar_evento('fin', f'Fin del combate. {self.resultado}', self.turno_actual)

    def confirmar_reagrupacion(self, decisiones):
        """decisiones = [{'legionarios': n, 'caballeria': n, 'estrategia': 'Cuneus'}, {...}]
        Primero se valida TODO; si algo falla no se cambia nada (CA148)."""
        if self.estado != 'reagrupacion':
            raise ErrorDominio('Solo se puede reagrupar al terminar un turno.')
        if not isinstance(decisiones, list) or len(decisiones) != 2 or not all(isinstance(d, dict) for d in decisiones):
            raise ErrorDominio('Faltan las decisiones de reagrupación de ambas legiones.')

        revisadas = []
        for legion, decision in zip(self.legiones, decisiones):
            legionarios, caballeria, costo = legion.validar_conversion(decision.get('legionarios'), decision.get('caballeria'))
            nombre_estrategia = decision.get('estrategia')
            # isinstance primero: una lista o un diccionario no se pueden buscar en ESTRATEGIAS.
            if not isinstance(nombre_estrategia, str) or nombre_estrategia not in ESTRATEGIAS:
                raise ErrorDominio(f'{legion.nombre}: elija una estrategia válida.')
            ESTRATEGIAS[nombre_estrategia].validar_aplicabilidad(legion, legionarios, caballeria)
            revisadas.append((legion, legionarios, caballeria, costo, nombre_estrategia))

        numero = self.turno_actual
        for legion, legionarios, caballeria, costo, nombre_estrategia in revisadas:
            if legionarios or caballeria:
                legion.convertir_esclavos(legionarios, caballeria)
                self.bitacora.registrar_evento('conversion', f'{legion.nombre} convierte {legionarios} esclavos en Legionarios '
                                               f'y {caballeria} en Caballería por {costo} denarios.', numero, None, legion.nombre)
            legion.seleccionar_estrategia(nombre_estrategia)
            self.bitacora.registrar_evento('estrategia', f'{legion.nombre} elige {nombre_estrategia}.', numero + 1, None, legion.nombre)

        nuevo_turno = self.turno_en_curso().planificar_siguiente_turno(self)
        self.turnos.append(nuevo_turno)
        self.turno_actual = nuevo_turno.numero
        self.etapa_siguiente = 1
        self.estado = 'en_curso'
        self.bitacora.registrar_evento('turno', f'Comienza el turno {nuevo_turno.numero}.', nuevo_turno.numero)


# =============================================================================
# 9. CAMPAÑA: reúne todo y sabe convertirse en diccionario (para guardar)
# =============================================================================

class Campania:
    VERSION_FORMATO = 1

    def __init__(self, nombre='Campaña'):
        self.id_campania = None        # lo asigna la base de datos al guardar
        self.nombre = leer_nombre(nombre, 'Nombre de la campaña')
        self.senado = Senado()
        self.legiones = []
        self.combate_actual = None
        self.bitacora = Bitacora()
        self.estado = 'configurando'   # configurando, en_combate, finalizada

    @classmethod
    def crear_campania(cls, nombre='Campaña'):
        campania = cls(nombre)
        campania.bitacora.registrar_evento('campania', f'Se crea la campaña «{campania.nombre}».')
        return campania

    def registrar_legion(self, nombre_legion, nombre_legatus, indice_consul, porcentaje_atk, porcentaje_def, presupuesto):
        if self.combate_actual is not None:
            raise ErrorDominio('No se pueden crear legiones con un combate iniciado.')
        if len(self.legiones) >= 2:
            raise ErrorDominio('Esta campaña ya tiene sus dos legiones.')
        legatus = Legatus(nombre_legatus, porcentaje_atk, porcentaje_def, presupuesto, indice_consul)
        legion = Legion(nombre_legion, legatus)
        if any(otra.nombre.lower() == legion.nombre.lower() for otra in self.legiones):
            raise ErrorDominio('Ya existe una legión con ese nombre.')
        self.senado.consules[legatus.indice_consul].asignar_legatus(legatus)
        self.legiones.append(legion)
        self.bitacora.registrar_evento('legion', f'Se crea {legion.nombre} al mando de {legatus.nombre} '
                                       f'(%ATK {legatus.porcentaje_atk:g}, %DEF {legatus.porcentaje_def:g}, '
                                       f'presupuesto {legatus.presupuesto}).', legion_afectada=legion.nombre)
        return legion

    def anular_legion_sin_tropas(self):
        """Deshace la última legión creada mientras todavía no contrata tropas, para corregir
        su Legatus o su presupuesto (por ejemplo, un presupuesto que no alcanza para nada)."""
        if self.combate_actual is not None:
            raise ErrorDominio('No se pueden corregir legiones con un combate iniciado.')
        if not self.legiones or self.legiones[-1].unidades:
            raise ErrorDominio('Solo se puede corregir una legión que todavía no ha contratado tropas.')
        legion = self.legiones.pop()
        self.senado.consules[legion.legatus.indice_consul].legatus.remove(legion.legatus)
        self.bitacora.registrar_evento('legion', f'Se anula {legion.nombre} para corregir sus datos.',
                                       legion_afectada=legion.nombre)
        return legion

    def contratar(self, indice_legion, cantidades):
        if self.combate_actual is not None:
            raise ErrorDominio('La contratación se hace antes del combate.')
        indice = leer_entero(indice_legion, 'Legión', 0, len(self.legiones) - 1)
        legion = self.legiones[indice]
        costo = legion.agregar_unidades(cantidades)
        self.bitacora.registrar_evento('contratacion', f'{legion.nombre} contrata tropas por {costo} denarios '
                                       f'(saldo {legion.legatus.presupuesto}).', legion_afectada=legion.nombre)
        return costo

    def iniciar_combate(self, indice_atacante, modo, semilla=None):
        if len(self.legiones) < 2:
            raise ErrorDominio('Se necesitan dos legiones para combatir.')
        if self.combate_actual is not None:
            raise ErrorDominio('El combate ya fue iniciado.')
        combate = Combate(self.legiones[0], self.legiones[1], self.bitacora, semilla)
        combate.preparar_combate(indice_atacante, modo)   # si falla, no se guarda el combate
        combate.iniciar_combate()
        self.combate_actual = combate
        self.estado = 'en_combate'
        return combate

    def actualizar_estado(self):
        if self.combate_actual is not None and self.combate_actual.estado == 'finalizado':
            self.estado = 'finalizada'

    # ---------- Guardar: objeto -> diccionario ----------

    def guardar_campania(self):
        """Devuelve un diccionario con TODO lo necesario para reconstruir la campaña (CA152)."""
        legiones = []
        for legion in self.legiones:
            legatus = legion.legatus
            legiones.append({
                'nombre': legion.nombre,
                'estrategia': legion.estrategia.nombre,
                'legatus': {'nombre': legatus.nombre, 'consul': legatus.indice_consul,
                            'atk': legatus.porcentaje_atk, 'def': legatus.porcentaje_def,
                            'presupuesto': legatus.presupuesto},
                # Cada unidad se guarda como [tipo, hp_actual]; hp <= 0 significa muerta.
                'unidades': [[u.clave_tipo, u.hp_actual] for u in legion.unidades],
            })
        combate = None
        if self.combate_actual is not None:
            c = self.combate_actual
            combate = {
                'estado': c.estado, 'turno_actual': c.turno_actual, 'etapa_siguiente': c.etapa_siguiente,
                'modo': c.modo_simulacion, 'atacante_inicial': c.atacante_inicial,
                'resultado': c.resultado, 'indice_ganador': c.indice_ganador, 'semilla': c.semilla,
                'turnos_sin_danio': c.turnos_sin_danio,
                'turnos': [{'numero': t.numero, 'atacante_primero': t.indice_atacante_primero,
                            'estrategia_a': t.estrategia_legion_a, 'estrategia_b': t.estrategia_legion_b,
                            'finalizado': t.finalizado, 'mantenimiento': t.mantenimiento,
                            'etapas': [e.obtener_resultado() for e in t.etapas]} for t in c.turnos],
            }
        return {
            'formato': 'legio-imperium', 'version': self.VERSION_FORMATO,
            'id': self.id_campania, 'nombre': self.nombre, 'estado': self.estado,
            'legiones': legiones, 'combate': combate,
            'bitacora': [evento.a_dict() for evento in self.bitacora.eventos],
        }

    # ---------- Cargar: diccionario -> objeto ----------

    @classmethod
    def cargar_campania(cls, datos):
        """Reconstruye una campaña. Si el archivo está dañado lanza ErrorDominio y
        NO toca la campaña actual (CA156)."""
        try:
            return cls.restaurar_estado(datos)
        except ErrorDominio as error:
            raise ErrorDominio(f'Archivo de campaña inválido: {error}')
        except (KeyError, TypeError, ValueError, IndexError, AttributeError, OverflowError):
            # OverflowError: un número infinito (por ejemplo 1e999) escrito a mano en el archivo.
            raise ErrorDominio('Archivo de campaña inválido o dañado.')

    @classmethod
    def restaurar_estado(cls, datos):
        if not isinstance(datos, dict) or datos.get('formato') != 'legio-imperium':
            raise ErrorDominio('no es una campaña de Legio Imperium.')
        if datos.get('version') != cls.VERSION_FORMATO:
            raise ErrorDominio('versión de archivo no compatible.')

        campania = cls(datos['nombre'])
        campania.id_campania = datos.get('id')
        if datos['estado'] not in ('configurando', 'en_combate', 'finalizada'):
            raise ErrorDominio('estado desconocido.')
        campania.estado = datos['estado']

        if len(datos['legiones']) > 2:
            raise ErrorDominio('demasiadas legiones.')
        for dl in datos['legiones']:
            dg = dl['legatus']
            legatus = Legatus(dg['nombre'], dg['atk'], dg['def'], dg['presupuesto'], dg['consul'])
            legion = Legion(dl['nombre'], legatus)
            for clave_tipo, hp in dl['unidades']:
                if clave_tipo not in CATALOGO:
                    raise ErrorDominio(f'tipo de unidad desconocido: {clave_tipo}.')
                hp = leer_entero(hp, 'HP', -10_000, CATALOGO[clave_tipo].hp_base)
                legion.unidades.append(Unidad(legion._siguiente_id, clave_tipo, hp))
                legion._siguiente_id += 1
            if dl['estrategia'] not in ESTRATEGIAS:
                raise ErrorDominio('estrategia desconocida.')
            legion.estrategia = ESTRATEGIAS[dl['estrategia']]
            campania.senado.consules[legatus.indice_consul].asignar_legatus(legatus)
            campania.legiones.append(legion)

        for de in datos['bitacora']:
            evento = campania.bitacora.registrar_evento(str(de['tipo_evento']), str(de['descripcion']),
                                                        de.get('numero_turno'), de.get('numero_etapa'),
                                                        de.get('legion_afectada'), int(de.get('cantidad_bajas', 0)))
            evento.secuencia = int(de['secuencia'])

        dc = datos['combate']
        if dc is not None:
            if len(campania.legiones) != 2:
                raise ErrorDominio('un combate necesita dos legiones.')
            # La semilla cambia según los turnos ya jugados para no repetir el mismo azar.
            semilla = int(dc['semilla'])
            combate = Combate(campania.legiones[0], campania.legiones[1], campania.bitacora, semilla)
            combate.motor = MotorCombate(random.Random(semilla + len(dc['turnos']) * 1000 + int(dc['etapa_siguiente'])))
            if dc['estado'] not in ('en_curso', 'reagrupacion', 'finalizado'):
                raise ErrorDominio('estado de combate desconocido.')
            combate.estado = dc['estado']
            combate.turno_actual = leer_entero(dc['turno_actual'], 'Turno', 1, 1_000_000)
            combate.etapa_siguiente = leer_entero(dc['etapa_siguiente'], 'Etapa', 1, 2)
            combate.cambiar_modo_simulacion(dc['modo'])
            combate.atacante_inicial = leer_entero(dc['atacante_inicial'], 'Atacante', 0, 1)
            combate.resultado = str(dc.get('resultado', ''))
            ganador = dc.get('indice_ganador')
            combate.indice_ganador = None if ganador is None else leer_entero(ganador, 'Ganador', 0, 1)
            combate.turnos_sin_danio = leer_entero(dc.get('turnos_sin_danio', 0), 'Turnos sin daño', 0, 1_000_000)
            for dt in dc['turnos']:
                turno = Turno(int(dt['numero']), leer_entero(dt['atacante_primero'], 'Atacante', 0, 1),
                              dt['estrategia_a'], dt['estrategia_b'])
                turno.finalizado = bool(dt['finalizado'])
                turno.mantenimiento = [int(m) for m in dt['mantenimiento']]
                for de in dt['etapas']:
                    etapa = EtapaCombate(int(de['numero_etapa']), int(de['indice_atacante']), int(de['indice_defensor']))
                    etapa.ataque_total = float(de['ataque_total'])
                    etapa.defensa_total = float(de['defensa_total'])
                    etapa.danio_global = int(de['danio_global'])
                    etapa.bajas_por_tipo = {t: int(de['bajas_por_tipo'].get(t, 0)) for t in ORDEN_TIPOS}
                    etapa.cantidad_bajas = int(de['cantidad_bajas'])
                    etapa.hp_perdido = int(de.get('hp_perdido', 0))
                    etapa.finalizada = bool(de['finalizada'])
                    turno.etapas.append(etapa)
                combate.turnos.append(turno)
            if not combate.turnos:
                raise ErrorDominio('combate sin turnos.')
            campania.combate_actual = combate
        return campania
