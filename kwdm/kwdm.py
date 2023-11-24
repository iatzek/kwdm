#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""

"""

from flask import Flask
from flask import make_response, request, jsonify
from datetime import datetime

import os
from requests import session, Timeout
import logging

_logger = logging.getLogger(__name__)

# ustawienia
url = os.environ.get('RESULTS_ENDPOINT', 'http://localhost:8042')
s = session()

app = Flask(__name__)


@app.route('/newInstance/', methods=["POST"])
def newInstance():
    #try:
    q = request.get_json(force = True) # wymuś traktowanie wejścia jako JSON
    #except TypeError:
    #    q = {}
    
    remoteIP = request.environ.get('HTTP_X_REAL_IP', request.remote_addr)   
    
    if not 'SOPInstanceUID' in q:
        response = 'no SOPInstanceUID in query'
        status = 'error'
        code = 400
        _logger.info(f"bad request from {remoteIP}")
    else:
        response = process(q['SOPInstanceUID'])
        status = 'OK'
        code = 200
        _logger.info(f"good request from {remoteIP}")
    
    return make_response(jsonify({'response' : response, \
                                      'status' : status}), code)
    
        
def process(SOPInstanceUID):
    return ':)'

if __name__ == '__main__':
    os.system('ping -c 1 -t 1 kwdm')
    port = int(os.environ.get('PORT', '5000'))
    app.debug = True
    app.run(host = '0.0.0.0', port = port)
