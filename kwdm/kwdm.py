#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""

"""

from flask import Flask
from flask import make_response, request, jsonify, redirect
from datetime import datetime

import os
import logging

logging.basicConfig(level=logging.INFO)
_logger = logging.getLogger(__name__)


import psycopg2


app = Flask(__name__)

# baza danych
db = os.environ.get('DB', 'queue.db')

def getConnection():
    conn = psycopg2.connect(user='postgres', 
                            password=os.environ.get('POSTGRES_PASSWORD'),
                            host='postgres',
                            port=5432,
                            database='postgres')
    return conn

def prepareTable():
    conn = getConnection()
    cursor = conn.cursor()

    # w postgresie można wykorzystać meta-typ SERIAL
    # który tworzy autoinkrementującą kolejkę
    cursor.execute('CREATE TABLE IF NOT EXISTS queue ' \
                       ' (id SERIAL PRIMARY KEY, date TIMESTAMP, ' \
                       '  orthancInstanceID TEXT, state INTEGER, returnAddress TEXT)')
    cursor.execute('CREATE INDEX IF NOT EXISTS did ON queue(state, date)')
    conn.commit()
    conn.close()

def enqueue(orthancInstanceID, returnAddress):
    # w sqlite3 w szablonie wykorzystuje się ?
    # w postgresie %s (lub wariacje)
    q = "INSERT INTO queue (date, orthancInstanceID, state, returnAddress) " \
        " VALUES (%s, %s, %s, %s)"
    conn = getConnection()
    cursor = conn.cursor()
    cursor.execute(q, (datetime.now(), orthancInstanceID, 0, returnAddress)) # 0 - nowe
    conn.commit()
    conn.close()

def _updatequeue(orthancInstanceID, state):
    q = "UPDATE queue SET state = %s WHERE orthancInstanceID = %s"
    conn = getConnection()
    cursor = conn.cursor()
    cursor.execute(q, (state, orthancInstanceID))
    conn.commit()
    conn.close()
    return

def dequeue(orthancInstanceID):
    return _updatequeue(orthancInstanceID, 2)
    
def markerror(orthancInstanceID):
    return _updatequeue(orthancInstanceID, -1)

def queue():
    q = "SELECT orthancInstanceID, returnAddress FROM queue WHERE state = 0 ORDER BY date"
    conn = getConnection()
    cursor = conn.cursor()
    cursor.execute(q)
    fa = cursor.fetchall()
    if not fa:
        fa = []
    else:
        fa = [{'OrthancInstanceID' : m[0], 'ReturnAddress' : m[1] } for m in fa]
    conn.close()
    return fa

@app.route("/queue/", methods = ["GET"])
def getQueue():
    q = queue()
    return make_response(jsonify(q), 200)
    
@app.route("/queue/", methods = ["POST"])
def updateState():
    r = request.get_json(force = True)
    if not 'OrthancInstanceID' in r:
        return make_response("No OrthanceInstanceID in request", 400)

    oid = r['OrthancInstanceID']
    remoteIP = request.environ.get('HTTP_X_REAL_IP', request.remote_addr)   
    uri = os.environ.get('ORTHANC_URI', f"http://{remoteIP}:8042/instances/")
    
    # dodanie do kolejki
    if not 'State' in r or r['State'] == 0 or r['State'] == 'new':
        _logger.info(f"enqueue {oid}")
        enqueue(oid, uri)
    # wyrzucenie z kolejki
    elif r['State'] == 2 or r['State'] == 'done':
        _logger.info(f"dequeue {oid}")        
        dequeue(r['OrthancInstanceID'])
    elif r['State'] == -1 or r['State'] == 'error':
        _logger.warning(f"error while processing {oid}")        
        markerror(r['OrthancInstanceID'])
    else:
        _logger.error(f"error while processing {oid} with state {r['State']}")
        return make_response("Only State 0/2/-1 ==0 or new/done/error possible now", 400)
    
    return make_response("OK", 200)


# przekierowanie na bardziej uniwersalny endpoint
@app.route('/newInstance/', methods=["POST"])
def newInstance():
    return redirect("/queue/", 301)
   

if __name__ == '__main__':
    prepareTable()
    port = int(os.environ.get('PORT', '5000'))
    app.debug = True
    app.run(host = '0.0.0.0', port = port)
