"""
pruebas.py — Pruebas automáticas de las reglas y de la aplicación.

Ejecutar:  python -m unittest pruebas -v

Usan una base SQLite temporal para no tocar la base MySQL real.
Cada prueba indica el criterio de aceptación (CA) que comprueba.
"""

import os
import tempfile
import unittest

# Antes de importar app: base temporal solo para pruebas.
_carpeta_temporal = tempfile.mkdtemp()
os.environ['LEGIO_BD_URL'] = 'sqlite:///' + os.path.join(_carpeta_temporal, 'pruebas.db').replace('\\', '/')

from modelo import (CATALOGO, ESTRATEGIAS, TURNOS_SIN_DANIO_PARA_EMPATE, Campania, ErrorDominio, Legatus, Legion,  # noqa: E402
                    MotorCombate, Unidad, redondear)
import app as aplicacion  # noqa: E402


def campania_lista(semilla=7):
    """Campaña con dos legiones contratadas y el combate iniciado."""
    c = Campania.crear_campania('Prueba')
    c.registrar_legion('Legio A', 'César', 0, 10, 5, 20000)
    c.contratar(0, {'Legionario': 500, 'Caballeria': 200, 'Ballesta': 100, 'Esclavo': 100})
    c.registrar_legion('Legio B', 'Pompeyo', 1, 0, 0, 20000)
    c.contratar(1, {'Legionario': 300, 'Caballeria': 100, 'Ballesta': 50, 'Ingeniero': 20, 'Esclavo': 60})
    c.iniciar_combate(0, 'paso_a_paso', semilla)
    return c


class PruebasValidaciones(unittest.TestCase):
    """Datos inválidos que el profesor podría escribir en los formularios."""

    def test_bonificacion_fuera_de_rango(self):          # CA012, CA014
        for atk, defensa in [(26, 0), (0, -25.1), ('abc', 0), ('', 0), (float('nan'), 0)]:
            with self.assertRaises(ErrorDominio):
                Legatus('X', atk, defensa, 100, 0)

    def test_bonificacion_en_el_limite_se_acepta(self):
        legatus = Legatus('X', 25, -25, 100, 0)
        self.assertEqual(legatus.calcular_porcentaje_costo(), 0)   # CA015

    def test_presupuesto_invalido(self):                  # CA019
        for presupuesto in [-1, 10.5, 'mil', '', None, True]:
            with self.assertRaises(ErrorDominio):
                Legatus('X', 0, 0, presupuesto, 0)

    def test_nombres_obligatorios(self):                  # CA009
        with self.assertRaises(ErrorDominio):
            Legion('   ', Legatus('X', 0, 0, 10, 0))
        with self.assertRaises(ErrorDominio):
            Legatus('', 0, 0, 10, 0)

    def test_cantidades_invalidas(self):                  # CA024
        legion = Legion('L', Legatus('X', 0, 0, 1000, 0))
        for cantidades in [{'Legionario': -1}, {'Legionario': 2.5}, {'Legionario': 'diez'}, {'Legionario': 10**9}]:
            with self.assertRaises(ErrorDominio):
                legion.agregar_unidades(cantidades)
        self.assertEqual(legion.legatus.presupuesto, 1000)   # no se descontó nada

    def test_contratacion_sobre_presupuesto(self):        # CA029
        legion = Legion('L', Legatus('X', 25, 25, 100, 0))
        with self.assertRaises(ErrorDominio):
            legion.agregar_unidades({'Ballesta': 6})        # 120 > 100
        self.assertEqual(legion.legatus.presupuesto, 100)
        self.assertEqual(legion.agregar_unidades({'Ballesta': 5}), 100)  # el %Costo no afecta (CA027)
        self.assertEqual(legion.legatus.presupuesto, 0)

    def test_legion_sin_unidades_que_ataquen(self):      # CA036, CA074
        # Se rechaza al contratar, para que el usuario pueda corregir y no quede atascado.
        c = Campania.crear_campania('X')
        c.registrar_legion('A', 'a', 0, 0, 0, 1000)
        for solo_no_atacantes in ({'Esclavo': 10}, {'Ingeniero': 5}, {'Ingeniero': 5, 'Esclavo': 50}):
            with self.assertRaises(ErrorDominio):
                c.contratar(0, solo_no_atacantes)
        self.assertEqual(c.legiones[0].legatus.presupuesto, 1000)   # no se cobró nada
        self.assertEqual(c.legiones[0].unidades, [])
        c.contratar(0, {'Ballesta': 1, 'Ingeniero': 5})            # con una que ataque, sí

    def test_estancamiento_termina_en_empate(self):
        # Nadie puede dañar a nadie: 1 Legionario (ATK 27,5) contra mucha DEF, y al revés.
        c = Campania.crear_campania('X')
        c.registrar_legion('A', 'a', 0, 0, 0, 10_000)
        c.contratar(0, {'Legionario': 1, 'Ingeniero': 20})
        c.registrar_legion('B', 'b', 1, 0, 0, 10_000)
        c.contratar(1, {'Legionario': 1, 'Ingeniero': 20})
        combate = c.iniciar_combate(0, 'paso_a_paso', 1)
        for _ in range(50):
            if combate.estado == 'finalizado':
                break
            if combate.estado == 'reagrupacion':
                combate.confirmar_reagrupacion([{'estrategia': 'Triplex Acies'}] * 2)
            else:
                combate.ejecutar_siguiente_etapa()
        self.assertEqual(combate.estado, 'finalizado')
        self.assertEqual(combate.turno_actual, TURNOS_SIN_DANIO_PARA_EMPATE)
        self.assertIsNone(combate.indice_ganador)
        self.assertIn('estancamiento', combate.resultado)

    def test_contador_sin_danio_se_guarda(self):
        c = Campania.crear_campania('X')
        c.registrar_legion('A', 'a', 0, 0, 0, 10_000)
        c.contratar(0, {'Legionario': 1, 'Ingeniero': 20})
        c.registrar_legion('B', 'b', 1, 0, 0, 10_000)
        c.contratar(1, {'Legionario': 1, 'Ingeniero': 20})
        combate = c.iniciar_combate(0, 'paso_a_paso', 1)
        combate.ejecutar_siguiente_etapa()
        combate.ejecutar_siguiente_etapa()
        self.assertEqual(combate.turnos_sin_danio, 1)
        copia = Campania.cargar_campania(c.guardar_campania())
        self.assertEqual(copia.combate_actual.turnos_sin_danio, 1)

    def test_presupuesto_cero_se_puede_corregir(self):    # CA019 acepta 0, CA029 permite ajustar
        c = Campania.crear_campania('X')
        c.registrar_legion('A', 'a', 1, 0, 0, 0)
        with self.assertRaises(ErrorDominio):
            c.contratar(0, {'Legionario': 1})                # sin dinero no se puede contratar
        c.anular_legion_sin_tropas()                         # vuelve al formulario
        self.assertEqual(c.legiones, [])
        self.assertEqual(c.senado.consules[1].obtener_legatus(), [])
        c.registrar_legion('A', 'a', 1, 0, 0, 100)           # mismo nombre, ahora con presupuesto
        c.contratar(0, {'Legionario': 1})
        with self.assertRaises(ErrorDominio):                # ya contrató: no se puede anular
            c.anular_legion_sin_tropas()

    def test_numeros_con_formato_raro(self):             # CA019, CA024
        # Python aceptaría todos estos como números; la simulación solo acepta dígitos 0-9.
        for raro in ['1_000', '1e3', '0x10', 'Infinity', '١٢', '５', '!@#$%^&*(', 'eval(5)', '5 5']:
            with self.assertRaises(ErrorDominio, msg=raro):
                Legatus('X', 0, 0, raro, 0)
        self.assertEqual(Legatus('X', '+5', ' -2,5 ', ' 7 ', 0).presupuesto, 7)

    def test_simbolos_y_codigo_en_nombres_se_guardan_como_texto(self):
        # Lo que escribió el profesor al probar: símbolos, código Python, SQL y HTML.
        raros = ['!@#$%^^&**(', '__import__("os").system("calc")', "'; DROP TABLE campanias; --",
                 '<img src=x onerror=alert(1)>', '{{7*7}}', 'Ñandú 😀']
        for texto in raros:
            c = Campania.crear_campania(texto)
            legion = c.registrar_legion(texto, texto, 0, 0, 0, 100)
            self.assertEqual((c.nombre, legion.nombre, legion.legatus.nombre), (texto, texto, texto))
            copia = Campania.cargar_campania(c.guardar_campania())
            self.assertEqual(copia.legiones[0].legatus.nombre, texto)

    def test_caracteres_invisibles_en_nombres(self):
        for texto in ['Legio\x00', 'Le\u200bgio', 'oigeL\u202e']:   # nulo, espacio invisible, texto invertido
            with self.assertRaises(ErrorDominio):
                Legatus(texto, 0, 0, 100, 0)

    def test_nombres_de_legion_repetidos(self):
        c = Campania.crear_campania('X')
        c.registrar_legion('Legio', 'a', 0, 0, 0, 100)
        with self.assertRaises(ErrorDominio):
            c.registrar_legion('legio', 'b', 1, 0, 0, 100)


class PruebasReglas(unittest.TestCase):

    def test_redondeo_medio_sube(self):                  # CA085
        self.assertEqual(redondear(2.5), 3)
        self.assertEqual(redondear(2.49), 2)

    def test_danio_global_nunca_negativo(self):           # CA064
        motor = MotorCombate(None)
        self.assertEqual(motor.calcular_danio_global(100, 500), 0)
        self.assertEqual(motor.calcular_danio_global(500.5, 100), 401)

    def test_distribucion_mayores_restos(self):           # CA067, CA068
        legion = Legion('L', Legatus('X', 0, 0, 100000, 0))
        legion.agregar_unidades({'Legionario': 1, 'Caballeria': 1, 'Ballesta': 1, 'Esclavo': 5})
        partes = MotorCombate(None).distribuir_danio(legion, 10)
        self.assertEqual(sum(partes.values()), 10)          # el total se conserva
        self.assertNotIn('Esclavo', partes)                 # los esclavos no atacan

    def test_danio_individual_minimo_y_bonos(self):       # CA080, CA081
        atacante = Legion('A', Legatus('X', 0, 0, 1000, 0))
        defensor = Legion('B', Legatus('Y', 0, 0, 1000, 0))
        motor = MotorCombate(None)
        mod_a, mod_d = atacante.calcular_modificadores(), defensor.calcular_modificadores()
        # Ingeniero (ATK 5) contra Legionario (DEF 35): daño mínimo 1
        self.assertEqual(motor.calcular_danio_individual('Ingeniero', Unidad(1, 'Legionario'), mod_a, mod_d), 1)
        # Caballería contra Legionario: (45*1.1 - 35*1.1) = 11 -> *1.2 carga -> *0.8 Triplex = 10.56 -> 11
        self.assertEqual(motor.calcular_danio_individual('Caballeria', Unidad(1, 'Legionario'), mod_a, mod_d), 11)

    def test_orbis_protege_ballestas(self):              # CA057, CA087
        defensor = Legion('B', Legatus('Y', 0, 0, 1000, 0))
        defensor.agregar_unidades({'Legionario': 1, 'Ballesta': 1})
        defensor.seleccionar_estrategia('Orbis')
        ballesta = defensor.unidades_vivas('Ballesta')[0]
        MotorCombate(None).aplicar_danio(ballesta, 99, defensor.calcular_modificadores())
        self.assertEqual(ballesta.hp_actual, CATALOGO['Ballesta'].hp_base)

    def test_estrategias_requieren_unidades(self):        # CA049, CA054
        legion = Legion('L', Legatus('X', 0, 0, 1000, 0))
        legion.agregar_unidades({'Ballesta': 1})
        for nombre in ('Cuneus', 'Orbis'):
            with self.assertRaises(ErrorDominio):
                legion.seleccionar_estrategia(nombre)

    def test_mantenimiento(self):                         # CA102-CA105
        legion = Legion('L', Legatus('X', 10, 10, 100000, 0))  # %Costo = 20
        legion.agregar_unidades({'Legionario': 10, 'Esclavo': 100})   # base 50 + 100 = 150
        # 150 * 1.20 = 180; 100 esclavos = 2 grupos -> -30 % -> 126
        self.assertEqual(legion.calcular_mantenimiento(), 126)
        legion.agregar_unidades({'Esclavo': 400})           # 10 grupos: descuento tope 100 %
        self.assertEqual(legion.calcular_mantenimiento(), 0)


class PruebasCombate(unittest.TestCase):

    def test_combate_completo_termina(self):
        c = campania_lista()
        combate = c.combate_actual
        for _ in range(200):
            if combate.estado == 'finalizado':
                break
            if combate.estado == 'reagrupacion':
                combate.confirmar_reagrupacion([{'estrategia': 'Triplex Acies'}] * 2)
            else:
                combate.ejecutar_siguiente_etapa()
        self.assertEqual(combate.estado, 'finalizado')
        with self.assertRaises(ErrorDominio):                # CA117: no se puede seguir
            combate.ejecutar_siguiente_etapa()
        # La pantalla de resultado necesita saber quién ganó, y eso debe sobrevivir a guardar/cargar.
        if combate.indice_ganador is None:
            self.assertTrue(combate.resultado.startswith('Empate'))
        else:
            self.assertTrue(combate.resultado.startswith('Vence ' + c.legiones[combate.indice_ganador].nombre))
        copia = Campania.cargar_campania(c.guardar_campania())
        self.assertEqual(copia.combate_actual.indice_ganador, combate.indice_ganador)

    def test_misma_semilla_mismo_resultado(self):
        a, b = campania_lista(3), campania_lista(3)
        for c in (a, b):
            c.combate_actual.ejecutar_siguiente_etapa()
        self.assertEqual([u.hp_actual for u in a.legiones[1].unidades],
                         [u.hp_actual for u in b.legiones[1].unidades])

    def test_reagrupacion_invalida_no_cambia_nada(self):  # CA148
        c = campania_lista()
        combate = c.combate_actual
        while combate.estado == 'en_curso':
            combate.ejecutar_siguiente_etapa()
        if combate.estado != 'reagrupacion':
            self.skipTest('El combate terminó antes de la reagrupación con esta semilla.')
        saldo = c.legiones[0].legatus.presupuesto
        esclavos = c.legiones[0].contar_unidades_vivas('Esclavo')
        malas = [
            [{'legionarios': esclavos + 1, 'estrategia': 'Triplex Acies'}, {'estrategia': 'Triplex Acies'}],
            [{'legionarios': 1, 'estrategia': 'Triplex Acies'}, {'estrategia': 'Inventada'}],
            [{'legionarios': -3, 'estrategia': 'Triplex Acies'}, {'estrategia': 'Triplex Acies'}],
            [{'estrategia': ['Cuneus']}, {'estrategia': {'a': 1}}],       # estrategia que no es texto
            'no es una lista',
        ]
        for decisiones in malas:
            with self.assertRaises(ErrorDominio):
                combate.confirmar_reagrupacion(decisiones)
        self.assertEqual(c.legiones[0].legatus.presupuesto, saldo)
        self.assertEqual(c.legiones[0].contar_unidades_vivas('Esclavo'), esclavos)
        combate.confirmar_reagrupacion([{'legionarios': 1, 'estrategia': 'Triplex Acies'}, {'estrategia': 'Triplex Acies'}])
        self.assertEqual(c.legiones[0].legatus.presupuesto, saldo - CATALOGO['Legionario'].costo)
        self.assertEqual(combate.turno_actual, 2)
        self.assertEqual(combate.turno_en_curso().indice_atacante_primero, 1)   # CA111

    def test_sin_dinero_para_mantenimiento_termina(self):  # CA107, CA113
        c = Campania.crear_campania('X')
        c.registrar_legion('A', 'a', 0, 0, 0, 5)
        c.contratar(0, {'Legionario': 1})                    # queda con saldo 0
        c.registrar_legion('B', 'b', 1, 0, 0, 5)
        c.contratar(1, {'Legionario': 1})
        combate = c.iniciar_combate(0, 'paso_a_paso', 1)
        combate.ejecutar_siguiente_etapa()
        combate.ejecutar_siguiente_etapa()
        self.assertEqual(combate.estado, 'finalizado')
        self.assertIn('mantenimiento', combate.resultado)
        self.assertIsNone(combate.indice_ganador)            # ninguna puede pagar: empate

    def test_guardar_y_cargar_conserva_todo(self):        # CA152, CA158
        c = campania_lista()
        c.combate_actual.ejecutar_siguiente_etapa()
        copia = Campania.cargar_campania(c.guardar_campania())
        self.assertEqual(copia.guardar_campania()['legiones'], c.guardar_campania()['legiones'])
        self.assertEqual(copia.combate_actual.etapa_siguiente, c.combate_actual.etapa_siguiente)
        self.assertEqual(len(copia.bitacora.eventos), len(c.bitacora.eventos))

    def test_archivo_corrupto(self):                      # CA156
        datos = campania_lista().guardar_campania()
        datos['legiones'][0]['unidades'][0][0] = 'Dragon'
        infinito = campania_lista().guardar_campania()
        infinito['bitacora'][0]['secuencia'] = float('inf')   # archivo editado a mano con 1e999
        for malo in [None, [], {'formato': 'otro'}, {'formato': 'legio-imperium', 'version': 1}, datos, infinito]:
            with self.assertRaises(ErrorDominio):
                Campania.cargar_campania(malo)


class PruebasAplicacion(unittest.TestCase):
    """Recorre la aplicación como lo haría la pantalla, usando el cliente de pruebas de Flask."""

    def setUp(self):
        aplicacion.campania_actual = None
        self.cliente = aplicacion.app.test_client()

    def post(self, ruta, datos=None):
        return self.cliente.post(ruta, json=datos if datos is not None else {})

    def test_recorrido_completo_y_persistencia(self):
        self.assertEqual(self.post('/api/nueva', {'nombre': 'Galia'}).status_code, 200)
        r = self.post('/api/legion', {'nombre': 'A', 'legatus': 'a', 'consul': 0, 'atk': 30, 'def': 0, 'presupuesto': 100})
        self.assertEqual(r.status_code, 400)                 # %ATK 30 rechazado con mensaje
        self.assertIn('error', r.get_json())
        self.post('/api/legion', {'nombre': 'A', 'legatus': 'a', 'consul': 0, 'atk': 5, 'def': 5, 'presupuesto': 3000})
        self.assertEqual(self.post('/api/contratar', {'indice': 0, 'cantidades': {'Legionario': 'x'}}).status_code, 400)
        self.post('/api/contratar', {'indice': 0, 'cantidades': {'Legionario': 200, 'Ballesta': 20, 'Esclavo': 50}})
        self.post('/api/legion', {'nombre': 'B', 'legatus': 'b', 'consul': 1, 'atk': 0, 'def': 0, 'presupuesto': 3000})
        self.post('/api/contratar', {'indice': 1, 'cantidades': {'Legionario': 150, 'Caballeria': 40}})
        estado = self.post('/api/iniciar', {'atacante': 1, 'modo': 'automatico', 'semilla': '5'}).get_json()
        self.assertEqual(estado['fase'], 'batalla')
        self.assertEqual(self.post('/api/etapa').status_code, 200)

        guardado = self.post('/api/guardar').get_json()
        id_guardado = guardado['campania']['id']
        self.assertTrue(id_guardado)
        lista = self.cliente.get('/api/campanias').get_json()['campanias']
        self.assertEqual(lista[0]['id'], id_guardado)

        exportado = self.cliente.get('/api/exportar').get_json()
        self.assertEqual(self.post('/api/importar', {'basura': True}).status_code, 400)
        self.assertEqual(aplicacion.campania_actual.nombre, 'Galia')   # el archivo malo no cambió nada
        self.assertEqual(self.post('/api/importar', exportado).status_code, 200)
        self.assertEqual(self.post(f'/api/cargar/{id_guardado}').status_code, 200)

    def test_acciones_sin_campania_no_botan_el_servidor(self):
        for ruta in ['/api/legion', '/api/contratar', '/api/iniciar', '/api/etapa', '/api/reagrupar', '/api/guardar']:
            self.assertEqual(self.post(ruta).status_code, 400, ruta)
        self.assertEqual(self.cliente.post('/api/nueva', data='esto no es json').status_code, 200)
        self.assertEqual(self.post('/api/cargar/99999').status_code, 400)

    def test_datos_maliciosos_nunca_dan_error_500(self):
        raros = ['!@#$%^^&**(', '__import__("os").system("calc")', "'; DROP TABLE x; --", '<script>', None,
                 True, [], {}, [1], {'a': 1}, 1e308, -1, '', '   ', 'a' * 5000]
        for valor in raros:
            self.post('/api/nueva', {'nombre': valor})
            for campo in ['nombre', 'legatus', 'consul', 'atk', 'def', 'presupuesto']:
                datos = {'nombre': 'A', 'legatus': 'a', 'consul': 0, 'atk': 0, 'def': 0, 'presupuesto': 500}
                datos[campo] = valor
                self.assertLess(self.post('/api/legion', datos).status_code, 500, (campo, valor))
            self.assertLess(self.post('/api/contratar', {'indice': valor, 'cantidades': {'Legionario': valor}}).status_code, 500)
            self.assertLess(self.post('/api/iniciar', {'atacante': valor, 'modo': valor}).status_code, 500)
            self.assertLess(self.post('/api/reagrupar', {'decisiones': [{'estrategia': valor, 'legionarios': valor}] * 2}).status_code, 500)
            self.assertLess(self.post('/api/importar', valor).status_code, 500)


if __name__ == '__main__':
    unittest.main()
