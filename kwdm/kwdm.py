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

# przetwarzanie
import pydicom
from pydicom.dataset import Dataset
from pydicom.sequence import Sequence
from pydicom.dataset import FileDataset

from datetime import datetime

import numpy as np
import cv2
import tempfile

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
    
    if not 'OrthancInstanceID' in q:
        response = 'no OrthancInstanceID in query'
        status = 'error'
        code = 400
        _logger.info(f"bad request from {remoteIP}")
    else:
        code, status = process(q['OrthancInstanceID'], remoteIP)
        if code == 200:
            response = 'OK'
        else:
            response = 'error'
        _logger.info(f"good request from {remoteIP}; response {code}")
    
    return make_response(jsonify({'response' : response, \
                                      'status' : status}), code)
    
        
def process(OrthancInstanceID, serverIP):
    
    uri = os.environ.get('ORTHANC_URI', "http://{serverIP}:8042/")
    user = os.environ.get('ORTHANC_USER', '')
    password = os.environ.get('ORTHANC_PASSWORD', '')
    
    s = session()
    if user:
        s.auth = (user, password)
    
    hget = { "Accept" : "application/octet-stream" }
    hpost = { "Accept" : "application/json;charset=UTF-8", \
              "Content-Type" : "application/octet-stream" }    
        
    _logger.info(f"{uri}/instances/{OrthancInstanceID}/file")
    response = s.get(f"{uri}/instances/{OrthancInstanceID}/file", headers=hget)
    if response.status_code != 200:
        return (400, f"{OrthancInstanceID} not accessible")
    
    # wszystko w unikalnym, tymczasowym katalogu, który zostanie usunięty 
    # po zakończeniu przetwarzania
    with tempfile.TemporaryDirectory() as tempDir:
        dicomIn= os.path.join(tempDir, 'DICOMIN')
        dicomOut= os.path.join(tempDir, 'DICOMOUT')
        
        # zapisujemy to, co odebraliśmy
        with open(dicomIn, 'wb') as file:
            file.write(response.content)

        # przetwarzamy
        try:
            processFile(dicomIn, dicomOut)        
        except Exception as e :
            return (500, f"Instance {OrthancInstanceID} not processed {e}")
    
        # czytamy plik dicomowy do oddania
        with open(dicomOut, 'rb') as file:
            content = file.read()
            
            # wysyłamy
            response = s.post(f"{uri}/instances/", headers=hpost, data = content)
            if response.status_code != 200:
                return (500, f"Results of {OrthancInstanceID} not accepted back")
    
    return 200, "OK"

def processArray(npimg):
    # bardzo optymistycznie zaprojektowana segmentacja płuc: 
    # bazując na skali HU wybierz dwa największe obszary powietrza 
    # w klatce piersiowej
    
    #lungs = cv2.bitwise_and(cv2.threshold(npimg, -700, 255, cv2.THRESH_BINARY)[1], 
    #                        cv2.threshold(npimg, -600, 255, cv2.THRESH_BINARY_INV)[1])

    # progowanie
    lungs = np.logical_and(npimg >= -1000, npimg <= -700)
    
    # otwarcie morfologiczne
    k = np.ones((3, 3), np.uint8) 
    lungs = cv2.morphologyEx(lungs.astype('uint8'), cv2.MORPH_OPEN, k, iterations=1) 
    
    # szukanie dwóch największych obszarów [które nie zawsze są płucami, ale
    # tak zakładamy]
    n, labels, stats, centroids = cv2.connectedComponentsWithStats(lungs.astype('uint8'), 4, cv2.CV_32S)
    if n < 2:
        lungs = np.zeros(lungs.shape, dtype=bool)
    else:
        area = stats[:, cv2.CC_STAT_AREA]
        area[0] = 0 # tło
        labelsFromBiggest = np.argsort(area)[::-1]
        
        lungs = (labels == labelsFromBiggest[0]) | (labels == labelsFromBiggest[1])
    
    # checkpoint
    #cv2.imwrite('test.png', lungs.astype(np.int8) * 255)
    
    # nałóż płuca jako jednolicie czerwoną maskę na oryginalny obraz
    # przeskalowany do 0-255
    npimg = (npimg - np.min(npimg)) / (np.max(npimg) - np.min(npimg)) #float
    npimg = (npimg * 255).astype(np.uint8)
    masked1 = npimg.copy() # potrzebujemy głębokiej kopii
    masked1[lungs > 0] = 255
    masked2 = npimg.copy()
    masked2[lungs > 0] = 0

    # sklej w obraz kolorowy BGR
    npimg = np.stack([masked2, masked2, masked1], axis=2)
    #cv2.imwrite('test.png', npimg)
    
    return npimg

def processFile(fileIn, fileOut):
    # na bazie skryptu pydicomMSI.py
    
    now = datetime.now()
    currentDate = now.strftime("%Y%m%d") # content of the SC, so NOW
    currentTime = now.strftime("%H%M%S")
    
    #https://simpleitk.readthedocs.io/en/master/Examples/DicomImagePrintTags/Documentation.html
    #http://insightsoftwareconsortium.github.io/SimpleITK-Notebooks/Python_html/01_Image_Basics.html 
    #https://simpleitk-prototype.readthedocs.io/en/latest/user_guide/visualization/plot_visseg.html
    #http://gdcm.sourceforge.net/wiki/index.php/Writing_DICOM#Secondary_Capture_Images
    image = pydicom.dcmread(fileIn)

    
    npimg = image.pixel_array # + ewentualne dekodowanie

    # tylko nowsze wersje pydicom
    #npimg = pydicom.pixel_data_handlers.apply_rescale(npimg, image) # -> Hounsfield HU

    # na piechotę    
    slope = np.double(getattr(image, 'RescaleSlope', '1.0'))
    intercept = np.int32(getattr(image, 'RescaleIntercept', '0'))
    npimg = np.int32((np.double(npimg) * slope) + intercept)
    
    npimg = processArray(npimg)
    

    # 2. metadata
    ds = Dataset()
    
    classUID = '1.2.840.10008.5.1.4.1.1.7' # Secondary Capture Image IOD; NIE multiframe color
    SOPUID = pydicom.uid.generate_uid()
    file_meta = Dataset()
    file_meta.MediaStorageSOPClassUID = classUID
    file_meta.MediaStorageSOPInstanceUID = SOPUID
    file_meta.ImplementationClassUID = "1.2.826.0.1.3680043.8.498.1" # przypisany do PyDicom
    ds.file_meta = file_meta
    ds.is_little_endian = True
    ds.is_implicit_VR = True
    
    # 
    toBeCopied = [ 'SpecificCharacterSet', \
                   'PatientName', 'PatientID', 'PatientBirthDate', 'PatientSex', \
                   'StudyInstanceUID', 'StudyID', 'StudyDate', 'StudyTime', 'ReferringPhysicianName', 'AccessionNumber', \
                   'PatientOrientation', 'AcquisitionNumber', 'AcquisitionDate', 'AcquisitionTime', 'AcquisitionDateTime', 'Laterality', \
                   'InstanceNumber'] # instance number może być pusty, ale jeżeli będzie, to można go skopiować
    for k in toBeCopied:
        val = getattr(image, k, '') # domyślnie przyjmujemy puste
        setattr(ds, k, val)
    
    # Pozostałe metadane
    
    # 2.0. SOP Common
    ds.SOPClassUID = classUID
    ds.SOPInstanceUID = SOPUID
    ds.InstanceCreationDate = currentDate
    ds.InstanceCreationTime = currentTime
    
    # 2.1. Patient 
    # Wszystko co trzeba skopiowane powyżej
    # 2.2. Study
    # Wszystko co trzeba skopiowane powyżej
    # 2.3. Series
    ds.Modality = 'OT' # Other
    ds.SeriesInstanceUID = pydicom.uid.generate_uid()
    ds.SeriesNumber = '' # może być pusty, więc z tego korzystamy
    ds.SeriesInstanceUID = pydicom.uid.generate_uid()
    ds.SeriesDate = currentDate
    ds.SeriesTime = currentTime
    ds.SeriesDescription = 'Segmented Lungs'
    # można by tu dodać odniesienie do oryginalnej serii
    
    # 2.4. SC Equipement
    ds.ConversionType = 'WSD'
    ds.SecondaryCaptureDeviceManufacturer = 'PS'
    ds.SecondaryCaptureDeviceManufacturerModelName = 'MSI'
    
    # 2.5. General Image
    #ds.PatientOrientation  # skopiowany
    ds.ImageType = 'DERIVED\SECONDARY'
    ds.ContentDate = currentDate
    ds.ContentTime = currentTime
    #ds.AcquisitionNumber 
    #ds.AcquisitionDate
    #ds.AcquisitionTime
    
    # 2.6. SC Image na bazie A.8.5.4
    ds.SamplesPerPixel = 3
    ds.PhotometricInterpretation = 'RGB'
    ds.PlanarConfiguration = 0
    ds.BitsAllocated = 8
    ds.BitsStored = 8
    ds.HighBit = 7
    ds.PixelRepresentation = 0
    ds.PlanarConfiguration = 0
    
    ds.Columns = npimg.shape[1]
    ds.Rows = npimg.shape[0]
    ds.PixelData = npimg.tobytes()
    
    # cześć metadanych powinna być przeliczona, więc False
    ds.save_as(fileOut, write_like_original = False)

if __name__ == '__main__':
    port = int(os.environ.get('PORT', '5000'))
    app.debug = True
    app.run(host = '0.0.0.0', port = port)
