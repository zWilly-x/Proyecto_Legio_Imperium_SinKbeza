"""
app.py — CONTROLADOR (la "C" de MVC) y punto de arranque.

Recibe las acciones de la pantalla (templates/index.html), le pide al modelo
(modelo.py) que aplique las reglas, usa datos.py para guardar/cargar y responde
con el estado actualizado en JSON para que la vista lo dibuje.

Ejecutar:  python app.py   y abrir http://127.0.0.1:5000
"""

import json
import threading
import webbrowser

from flask import Flask, Response, jsonify, render_template, request

import datos
from modelo import CATALOGO, ESTRATEGIAS, LIMITE_BONIFICACION_LEGATUS, MAX_UNIDADES_POR_TIPO, ORDEN_TIPOS, \
    TIPOS_QUE_ATACAN, TURNOS_SIN_DANIO_PARA_EMPATE, \
    PRESUPUESTO_MAXIMO, Campania, ErrorDominio

app = Flask(__name__)
datos.iniciar(app)

# La campaña abierta vive en memoria del servidor (un usuario a la vez).
campania_actual = None
# Evita que el modo automático y un clic modifiquen el combate al mismo tiempo.
candado = threading.Lock()


# =============================================================================
# Traducir el modelo a datos simples para la vista
# =============================================================================

def describir_legion(legion):
    modificadores = legion.calcular_modificadores()
    tipos = []
    for clave in ORDEN_TIPOS:
        tipo = CATALOGO[clave]
        vivas = legion.unidades_vivas(clave)
        tipos.append({
            'clave': clave, 'nombre': tipo.nombre, 'vivos': len(vivas),
            'contratados': sum(1 for u in legion.unidades if u.clave_tipo == clave),
            'hp': sum(u.hp_actual for u in vivas),
            'atk': round(len(vivas) * tipo.atk_base * modificadores['atk'], 1),
            'def': round(len(vivas) * tipo.def_base * modificadores['def'], 1),
        })
    hp_maximo = legion.hp_maximo_referencia()
    hp_actual = legion.hp_actual_total()
    return {
        'nombre': legion.nombre,
        'legatus': {'nombre': legion.legatus.nombre, 'atk': legion.legatus.porcentaje_atk,
                    'def': legion.legatus.porcentaje_def, 'costo': legion.legatus.calcular_porcentaje_costo(),
                    'consul': legion.legatus.indice_consul},
        'presupuesto': legion.legatus.presupuesto,
        'estrategia': legion.estrategia.nombre,
        'vivos': legion.contar_unidades_vivas(),
        'contratados': len(legion.unidades),
        'ataque_total': round(legion.calcular_ataque_total(), 1),
        'defensa_total': round(legion.calcular_defensa_total(), 1),
        'mantenimiento': legion.calcular_mantenimiento(),
        'salud': {'actual': hp_actual, 'maximo': hp_maximo,
                  'porcentaje': round(100 * hp_actual / hp_maximo, 1) if hp_maximo else 0},
        'tipos': tipos,
    }


def calcular_fase(campania):
    """Decide qué pantalla corresponde según el estado de la campaña."""
    if campania is None:
        return 'sin_campania', None
    combate = campania.combate_actual
    if combate is None:
        for indice in range(2):
            if indice >= len(campania.legiones):
                return 'crear_legion', indice
            if not campania.legiones[indice].unidades:
                return 'contratar', indice
        return 'preparar', None
    if combate.estado == 'reagrupacion':
        return 'reagrupacion', None
    if combate.estado == 'finalizado':
        return 'finalizado', None
    return 'batalla', None


def estado_para_vista():
    campania = campania_actual
    fase, indice = calcular_fase(campania)
    respuesta = {
        'fase': fase,
        'indice_legion': indice,
        'catalogo': [{'clave': c, 'nombre': CATALOGO[c].nombre, 'hp': CATALOGO[c].hp_base,
                      'atk': CATALOGO[c].atk_base, 'def': CATALOGO[c].def_base, 'costo': CATALOGO[c].costo,
                      'habilidad': CATALOGO[c].habilidad_especial} for c in ORDEN_TIPOS],
        'estrategias': [{'nombre': e.nombre, 'atk': e.modificador_atk, 'def': e.modificador_def,
                         'condicion': e.condicion_aplicacion, 'sinergia': e.descripcion_sinergia}
                        for e in ESTRATEGIAS.values()],
        'limites': {'bonificacion': LIMITE_BONIFICACION_LEGATUS, 'unidades': MAX_UNIDADES_POR_TIPO,
                    'presupuesto': PRESUPUESTO_MAXIMO, 'turnos_sin_danio': TURNOS_SIN_DANIO_PARA_EMPATE},
        'tipos_que_atacan': TIPOS_QUE_ATACAN,
    }
    if campania is None:
        return respuesta

    respuesta['campania'] = {'id': campania.id_campania, 'nombre': campania.nombre}
    respuesta['jerarquia'] = {
        'senado': campania.senado.nombre,
        'consules': [{'nombre': consul.nombre,
                      'legatus': [{'nombre': g.nombre, 'legion': g.legion.nombre} for g in consul.obtener_legatus()]}
                     for consul in campania.senado.obtener_consules()],
    }
    respuesta['legiones'] = [describir_legion(legion) for legion in campania.legiones]
    respuesta['bitacora'] = [{'secuencia': e.secuencia, 'tipo': e.tipo_evento, 'texto': e.obtener_descripcion()}
                             for e in campania.bitacora.consultar_historial()]

    combate = campania.combate_actual
    if combate is not None:
        turno = combate.turno_en_curso()
        if combate.etapa_siguiente == 1:
            atacante_siguiente = turno.indice_atacante_primero
        else:
            atacante_siguiente = 1 - turno.indice_atacante_primero
        ultima = None
        for t in reversed(combate.turnos):
            if t.etapas:
                ultima = t.etapas[-1].obtener_resultado()
                ultima['turno'] = t.numero
                break
        respuesta['combate'] = {
            'estado': combate.estado, 'turno': combate.turno_actual, 'etapa_siguiente': combate.etapa_siguiente,
            'modo': combate.modo_simulacion, 'resultado': combate.resultado,
            'indice_ganador': combate.indice_ganador, 'turnos_jugados': len(combate.turnos),
            'turnos_sin_danio': combate.turnos_sin_danio,
            'atacante_siguiente': atacante_siguiente, 'ultima_etapa': ultima, 'semilla': combate.semilla,
        }
    return respuesta


# =============================================================================
# Ayudantes del controlador
# =============================================================================

def cuerpo():
    """Datos JSON enviados por la vista; {} si vienen vacíos o mal formados."""
    datos_recibidos = request.get_json(silent=True)
    return datos_recibidos if isinstance(datos_recibidos, dict) else {}


def exigir_campania():
    if campania_actual is None:
        raise ErrorDominio('Primero cree o cargue una campaña.')
    return campania_actual


def responder(accion, mensaje=''):
    """Ejecuta una acción del modelo y responde con el estado nuevo.
    Si una regla falla, responde 400 con el mensaje para el usuario."""
    try:
        with candado:
            resultado = accion()
        respuesta = estado_para_vista()
        respuesta['mensaje'] = resultado if isinstance(resultado, str) else mensaje
        return jsonify(respuesta)
    except (ErrorDominio, datos.ErrorBaseDatos) as error:
        return jsonify({'error': str(error)}), 400


@app.errorhandler(Exception)
def error_inesperado(error):
    """Cualquier fallo no previsto se informa sin botar el servidor."""
    codigo = getattr(error, 'code', 500)
    if codigo == 500:
        app.logger.exception(error)   # el detalle queda en la consola del servidor
    return jsonify({'error': f'Error inesperado: {type(error).__name__}. El detalle quedó en la consola del servidor.'}), codigo


# =============================================================================
# Rutas (cada una es una acción del usuario)
# =============================================================================

@app.get('/')
def inicio():
    return render_template('index.html')


@app.get('/api/estado')
def ver_estado():
    return jsonify(estado_para_vista())


@app.post('/api/nueva')
def nueva_campania():
    def accion():
        global campania_actual
        nombre = cuerpo().get('nombre') or 'Campaña'
        campania_actual = Campania.crear_campania(nombre)
    return responder(accion, 'Campaña creada.')


@app.post('/api/legion')
def crear_legion():
    def accion():
        d = cuerpo()
        legion = exigir_campania().registrar_legion(d.get('nombre'), d.get('legatus'), d.get('consul', 0),
                                                    d.get('atk'), d.get('def'), d.get('presupuesto'))
        return f'{legion.nombre} creada. Ahora contrate sus tropas.'
    return responder(accion)


@app.post('/api/corregir_legion')
def corregir_legion():
    def accion():
        legion = exigir_campania().anular_legion_sin_tropas()
        return f'Corrija los datos de {legion.nombre}.'
    return responder(accion)


@app.post('/api/contratar')
def contratar():
    def accion():
        d = cuerpo()
        costo = exigir_campania().contratar(d.get('indice'), d.get('cantidades'))
        return f'Contratación confirmada por {costo} denarios.'
    return responder(accion)


@app.post('/api/iniciar')
def iniciar_combate():
    def accion():
        d = cuerpo()
        # La semilla del azar no aparece en pantalla: solo la envían las pruebas automáticas
        # para que un combate aleatorio se pueda repetir y comprobar.
        semilla = d.get('semilla')
        semilla = int(semilla) if str(semilla or '').strip().isdigit() else None
        exigir_campania().iniciar_combate(d.get('atacante'), d.get('modo', 'paso_a_paso'), semilla)
    return responder(accion, '¡Comienza el combate!')


@app.post('/api/etapa')
def siguiente_etapa():
    def accion():
        campania = exigir_campania()
        if campania.combate_actual is None:
            raise ErrorDominio('El combate no ha comenzado.')
        campania.combate_actual.ejecutar_siguiente_etapa()
        campania.actualizar_estado()
    return responder(accion)


@app.post('/api/modo')
def cambiar_modo():
    def accion():
        campania = exigir_campania()
        if campania.combate_actual is None:
            raise ErrorDominio('El combate no ha comenzado.')
        campania.combate_actual.cambiar_modo_simulacion(cuerpo().get('modo'))
    return responder(accion)


@app.post('/api/reagrupar')
def reagrupar():
    def accion():
        campania = exigir_campania()
        if campania.combate_actual is None:
            raise ErrorDominio('El combate no ha comenzado.')
        campania.combate_actual.confirmar_reagrupacion(cuerpo().get('decisiones'))
    return responder(accion, 'Reagrupación confirmada. Comienza el siguiente turno.')


# ---------- Persistencia ----------

@app.post('/api/guardar')
def guardar():
    def accion():
        campania = exigir_campania()
        campania.id_campania = datos.guardar(campania.guardar_campania())
        return f'Campaña guardada en la base de datos (n.º {campania.id_campania}).'
    return responder(accion)


@app.get('/api/campanias')
def listar_campanias():
    try:
        return jsonify({'campanias': datos.listar()})
    except datos.ErrorBaseDatos as error:
        return jsonify({'error': str(error)}), 400


@app.post('/api/cargar/<int:id_campania>')
def cargar_desde_base(id_campania):
    def accion():
        global campania_actual
        nueva = Campania.cargar_campania(datos.obtener(id_campania))
        nueva.id_campania = id_campania
        campania_actual = nueva
        return f'Campaña «{nueva.nombre}» cargada.'
    return responder(accion)


@app.get('/api/exportar')
def exportar():
    """Entrega la campaña como archivo .json (respaldo para el cuadro de diálogo)."""
    if campania_actual is None:
        return jsonify({'error': 'No hay campaña para exportar.'}), 400
    with candado:
        contenido = json.dumps(campania_actual.guardar_campania(), ensure_ascii=False, indent=1)
    return Response(contenido, mimetype='application/json',
                    headers={'Content-Disposition': 'attachment; filename=campania.json'})


@app.post('/api/importar')
def importar():
    """Carga un archivo elegido por el usuario. Si es inválido, la campaña actual no cambia.
    Si es válido, se sincroniza con la base de datos (CA157)."""
    def accion():
        global campania_actual
        nueva = Campania.cargar_campania(request.get_json(silent=True))
        nueva.id_campania = None   # se guarda como fila nueva: así no pisa otra campaña con el mismo n.º
        campania_actual = nueva
        try:
            nueva.id_campania = datos.guardar(nueva.guardar_campania())
            return f'Archivo cargado y sincronizado con la base de datos (n.º {nueva.id_campania}).'
        except datos.ErrorBaseDatos as error:
            return f'Archivo cargado, pero no se sincronizó con la base de datos: {error}'
    return responder(accion)


if __name__ == '__main__':
    # Abre el navegador automáticamente un segundo después de arrancar.
    threading.Timer(1.0, lambda: webbrowser.open('http://127.0.0.1:5000')).start()
    app.run(host='127.0.0.1', port=5000, debug=False)
