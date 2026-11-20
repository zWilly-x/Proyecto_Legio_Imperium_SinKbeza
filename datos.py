"""
datos.py — CAPA DE ACCESO A DATOS.

Guarda y recupera campañas en una base de datos MySQL externa usando
Flask-SQLAlchemy. Recibe y entrega diccionarios: no conoce las clases del
modelo ni las pantallas.

Tabla única "campanias":
    id | nombre | estado_json (la campaña completa en JSON) | actualizada

Para cambiar usuario, contraseña o servidor, definir la variable de entorno
LEGIO_BD_URL o editar URL_POR_DEFECTO.
"""

import json
import os
from datetime import datetime

from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import create_engine, text
from sqlalchemy.dialects.mysql import LONGTEXT
from sqlalchemy.engine import make_url

# Formato: mysql+pymysql://USUARIO:CONTRASEÑA@SERVIDOR:PUERTO/NOMBRE_BASE
URL_POR_DEFECTO = 'mysql+pymysql://root:legio2026@localhost:3306/legio_imperium'

db = SQLAlchemy()


class ErrorBaseDatos(Exception):
    """La base de datos no responde o rechazó la operación."""


class CampaniaGuardada(db.Model):
    __tablename__ = 'campanias'

    id = db.Column(db.Integer, primary_key=True)
    nombre = db.Column(db.String(80), nullable=False)
    # LONGTEXT en MySQL (hasta 4 GB): una campaña con miles de unidades no cabe en TEXT.
    estado_json = db.Column(db.Text().with_variant(LONGTEXT(), 'mysql'), nullable=False)
    actualizada = db.Column(db.DateTime, nullable=False, default=datetime.now)


def iniciar(app):
    """Conecta Flask con la base. Si MySQL no responde, la aplicación igual arranca
    y el error se informa al intentar guardar o cargar."""
    url = os.environ.get('LEGIO_BD_URL', URL_POR_DEFECTO)
    app.config['SQLALCHEMY_DATABASE_URI'] = url
    opciones = {'pool_pre_ping': True}
    if url.startswith('mysql'):
        opciones['connect_args'] = {'connect_timeout': 3}
    app.config['SQLALCHEMY_ENGINE_OPTIONS'] = opciones
    db.init_app(app)
    with app.app_context():
        try:
            preparar_tablas()
        except ErrorBaseDatos as error:
            print(f'AVISO: {error}')


_tablas_listas = False   # se vuelve True la primera vez que la base responde


def preparar_tablas():
    """Crea la base de datos (si es MySQL) y la tabla, si todavía no existen."""
    global _tablas_listas
    if _tablas_listas:
        return
    try:
        url = make_url(db.engine.url)
        if url.drivername.startswith('mysql') and url.database:
            # Se conecta al servidor sin elegir base, porque la base todavía puede no existir.
            servidor = create_engine(url.set(database=''), connect_args={'connect_timeout': 3})
            with servidor.connect() as conexion:
                conexion.execute(text(f'CREATE DATABASE IF NOT EXISTS `{url.database}` '
                                      'CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci'))
            servidor.dispose()
        db.create_all()
        _tablas_listas = True
    except Exception as error:
        raise ErrorBaseDatos(f'No se pudo conectar a la base de datos ({type(error).__name__}). '
                             'Revise que MySQL esté encendido y que usuario y contraseña sean correctos.')


def guardar(datos_campania):
    """Inserta o actualiza una campaña. Devuelve su id."""
    try:
        preparar_tablas()
        fila = None
        if datos_campania.get('id'):
            fila = db.session.get(CampaniaGuardada, datos_campania['id'])
        if fila is None:
            fila = CampaniaGuardada(nombre=datos_campania['nombre'], estado_json='{}')
            db.session.add(fila)
            db.session.flush()            # así MySQL asigna el id antes de escribir el JSON
        datos_campania['id'] = fila.id
        fila.nombre = datos_campania['nombre']
        fila.estado_json = json.dumps(datos_campania, ensure_ascii=False)
        fila.actualizada = datetime.now()
        db.session.commit()
        return fila.id
    except ErrorBaseDatos:
        raise
    except Exception as error:
        db.session.rollback()
        raise ErrorBaseDatos(f'No se pudo guardar en la base de datos ({type(error).__name__}).')


def listar():
    """Lista corta de campañas guardadas, de la más reciente a la más antigua."""
    try:
        preparar_tablas()
        filas = CampaniaGuardada.query.order_by(CampaniaGuardada.actualizada.desc()).all()
        return [{'id': f.id, 'nombre': f.nombre, 'actualizada': f.actualizada.strftime('%d-%m-%Y %H:%M')}
                for f in filas]
    except ErrorBaseDatos:
        raise
    except Exception as error:
        raise ErrorBaseDatos(f'No se pudo leer la base de datos ({type(error).__name__}).')


def obtener(id_campania):
    """Devuelve el diccionario de una campaña guardada."""
    try:
        preparar_tablas()
        fila = db.session.get(CampaniaGuardada, id_campania)
    except ErrorBaseDatos:
        raise
    except Exception as error:
        raise ErrorBaseDatos(f'No se pudo leer la base de datos ({type(error).__name__}).')
    if fila is None:
        raise ErrorBaseDatos('La campaña solicitada no existe.')
    return json.loads(fila.estado_json)
