# -*- coding: utf-8 -*-
"""
*** BuscadorDeTransporteAgent ***

Agente que se registra como BuscadorDeTransporte y atiende peticiones de transporte según la ontología ECSDI.

"""

from multiprocessing import Process, Queue
import logging
import argparse

from flask import Flask, request, render_template
from rdflib import Graph, Namespace, Literal
from rdflib.namespace import FOAF, RDF, RDFS, XSD

from AgentUtil.ACL import ACL
from AgentUtil.FlaskServer import shutdown_server
from AgentUtil.ACLMessages import build_message, send_message, get_message_properties
from AgentUtil.Agent import Agent
from AgentUtil.Logging import config_logger
from AgentUtil.DSO import DSO
from AgentUtil.Util import gethostname
from datetime import date
import socket

# Parámetros de línea de comandos
parser = argparse.ArgumentParser()
parser.add_argument('--open', action='store_true', default=False)
parser.add_argument('--verbose', action='store_true', default=False)
parser.add_argument('--port', type=int)
parser.add_argument('--dhost')
parser.add_argument('--dport', type=int)
args = parser.parse_args()

# Configuración de red
port = args.port or 9010
if args.open:
    hostname = '0.0.0.0'
    hostaddr = gethostname()
else:
    hostaddr = hostname = socket.gethostname()

dhost = args.dhost or socket.gethostname()
dport = args.dport or 9000

# Logger
logger = config_logger(level=1)
if not args.verbose:
    logging.getLogger('werkzeug').setLevel(logging.ERROR)

# Namespaces
ECSDI = Namespace("http://www.semanticweb.org/aloha/ontologies/2025/3/ECSDI#")
agn = Namespace("http://www.agentes.org#")

# Agente
BuscadorDeTransporte = Agent('BuscadorDeTransporte', agn.BuscadorDeTransporte,
                             f'http://{hostaddr}:{port}/comm', f'http://{hostaddr}:{port}/stop')
DirectoryAgent = Agent('DirectoryAgent', agn.Directory,
                       f'http://{dhost}:{dport}/Register', f'http://{dhost}:{dport}/Stop')

# Flask
app = Flask(__name__)

# Contador de mensajes
mss_cnt = 0

# Cola para tidyup
cola = Queue()


def register():
    """ Registrar en el Directory Service como BuscadorDeTransporte """
    global mss_cnt
    g = Graph()
    g.bind('foaf', FOAF)
    g.bind('dso', DSO)
    # Acción Register
    reg_obj = agn['reg-BuscadorTransporte']
    g.add((reg_obj, RDF.type, DSO.Register))
    g.add((reg_obj, DSO.Uri, Literal(BuscadorDeTransporte.uri)))
    g.add((reg_obj, FOAF.name, Literal(BuscadorDeTransporte.name)))
    g.add((reg_obj, DSO.Address, Literal(BuscadorDeTransporte.address)))
    g.add((reg_obj, DSO.AgentType, agn.BuscadorDeTransporte))
    msg = build_message(g, perf=ACL.request, sender=BuscadorDeTransporte.uri,
                        receiver=DirectoryAgent.uri, content=reg_obj, msgcnt=mss_cnt)
    send_message(msg, DirectoryAgent.address)
    mss_cnt += 1

@app.route('/', methods=['GET'])
def form():
    # Sirve la página con el formulario
    min_date = date.today().isoformat()
    return render_template('transport_form.html', min_date=min_date)

@app.route('/comm', methods=['GET','POST'])
def comm():
    """ Endpoint de comunicación: procesa PeticionTransporte y retorna RespuestaTransporte """
    global mss_cnt

    # 1) Si viene del formulario construimos la PeticionTransporte “manualmente”
    if request.method == 'POST':
        origen     = request.form['origen']
        destino    = request.form['destino']
        fecha      = request.form['fecha']
        precio_max = request.form['precio_max']
        pref       = request.form['preferencia']

        # Montamos el grafo semántico de la petición
        gpet = Graph()
        gpet.bind('ecsdi', ECSDI)
        pet = ECSDI['Pet-' + str(mss_cnt)]
        gpet.add((pet, RDF.type, ECSDI.PeticionTransporte))
        gpet.add((pet, ECSDI.origen, Literal(origen)))
        gpet.add((pet, ECSDI.destino, Literal(destino)))
        gpet.add((pet, ECSDI.fecha, Literal(fecha, datatype=XSD.date)))
        gpet.add((pet, ECSDI.PrecioMaximo, Literal(precio_max, datatype=XSD.float)))
        gpet.add((pet, ECSDI.preferenciaTransporte, Literal(pref)))

        # Ahora lo envolvemos en un mensaje ACL para reutilizar la misma lógica
        gm = Graph()
        gm.parse(data=gpet.serialize(format='xml'), format='xml')
        props   = get_message_properties(gm)
        content = pet
        accion  = ECSDI.PeticionTransporte

    # 2) Si viene por GET entendemos que es un ACL.query clásico
    else:
        message = request.args.get('content')
        gm = Graph()
        gm.parse(data=message, format='xml')
        props   = get_message_properties(gm)
        # si no es un ACL.request no tendrá 'content'
        content = props.get('content')
        accion  = gm.value(subject=content, predicate=RDF.type) if content else None

    # 3) Comprobamos performativa y acción
    if not props or props['performative'] != ACL.request:
        gr = build_message(Graph(),
                           ACL['not-understood'],
                           sender=BuscadorDeTransporte.uri,
                           msgcnt=mss_cnt)

    elif accion == ECSDI.PeticionTransporte:
        # delegamos en tu función, pasándole también props
        gr = handle_peticion_transporte(content, props)

    else:
        gr = build_message(Graph(),
                           ACL['not-understood'],
                           sender=BuscadorDeTransporte.uri,
                           msgcnt=mss_cnt)

    mss_cnt += 1
    return gr.serialize(format='xml')




def handle_peticion_transporte(pet_obj, props):
    """Genera una RespuestaTransporte ficticia con un Transporte"""
    g = Graph()
    g.bind('ecsdi', ECSDI)
    # Crear objeto respuesta
    resp = ECSDI['Resp-' + str(mss_cnt)]
    g.add((resp, RDF.type, ECSDI.RespuestaTransporte))
    # Crear instancia de Transporte
    t = ECSDI['Transp-' + str(mss_cnt)]
    g.add((t, RDF.type, ECSDI.Tren))  # por ejemplo Tren
    # Añadir propiedades de Transporte
    g.add((t, ECSDI.idTransporte, Literal('TREN123', datatype=XSD.string)))
    g.add((t, ECSDI.ImporteTransporte, Literal('45.00', datatype=XSD.float)))
    # Vincular respuesta con transporte
    g.add((resp, ECSDI.BuscaTransporte, t))
    # Construir mensaje ACL
    msg = build_message(g, perf=ACL.inform, sender=BuscadorDeTransporte.uri,
                        receiver=props['sender'], content=resp, msgcnt=mss_cnt)
    return msg


@app.route('/stop')
def stop():
    tidyup()
    shutdown_server()
    return 'Stopping'


def tidyup():
    cola.put(0)


def behavior():
    # Registrar al inicio
    register()
    # Esperar orden de parada
    while True:
        if not cola.empty() and cola.get() == 0:
            break


if __name__ == '__main__':
    # Ejecutar comportamiento en proceso
    p = Process(target=behavior)
    p.start()
    app.run(host=hostname, port=port)
    p.join()
