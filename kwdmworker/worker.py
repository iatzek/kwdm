#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""

"""

from datetime import datetime

import os
from requests import session
import logging

logging.basicConfig(level=logging.INFO)
_logger = logging.getLogger(__name__)

# przetwarzanie
import pydicom
from pydicom.dataset import Dataset

import numpy as np
import cv2
import tempfile

import time
import sys
import json

# FIXME: brak raportowania błędów do kolejki        
def processID(OrthancInstanceID, ReturnAddress):
    
    user = os.environ.get('ORTHANC_USER', '')
    password = os.environ.get('ORTHANC_PASSWORD', '')
    
    s = session()
    if user:
        s.auth = (user, password)
    
    hget = { "Accept" : "application/octet-stream" }
    hpost = { "Accept" : "application/json;charset=UTF-8", \
              "Content-Type" : "application/octet-stream" }    
        
    _logger.info(f"{ReturnAddress}/instances/{OrthancInstanceID}/file")
    response = s.get(f"{ReturnAddress}/instances/{OrthancInstanceID}/file", headers=hget)

    if response.status_code != 200:
        _logger.error(f"{OrthancInstanceID} not accessible")
        return False
        
    
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
            _logger.error(f"Instance {OrthancInstanceID} not processed {e}")
            return False
    
        # czytamy plik dicomowy do oddania
        with open(dicomOut, 'rb') as file:
            content = file.read()
            
            # wysyłamy
            response = s.post(f"{ReturnAddress}/instances/", headers=hpost, data = content)
            if response.status_code != 200:
                _logger.error(f"Results of {OrthancInstanceID} not accepted back")
                return False
    _logger.info(f"{OrthancInstanceID} processed correctly")
    return True

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


if __name__ == '__main__':
    
    # do odpytywania
    queueUri = os.environ.get('QUEUE_URI', '')
    if not queueUri:
        sys.exit(2)
        
    s = session()
    headers = { "Accept" : "application/json; charset=UTF-8"}
    
        
    pause = 2
    # odpytujemy
    while (True):
        response =  s.get(queueUri, headers = headers)
        if response.status_code != 200:
            _logger.warning(f"Queue not retrieved status={response.code}")
        else:
            try:
                queue = json.loads(response.content)
            except json.JSONDecoderError as e:
                _logger.warning(f"incorrect JSON {e}")
                time.sleep(pause)
                continue
            _logger.debug(f"queue length={len(queue)}")
            for q in queue:
                _logger.info(f"processing {q['OrthancInstanceID']} for {q['ReturnAddress']}")
                oid = q['OrthancInstanceID']
                ra = q['ReturnAddress']
                
                state = processID(oid, ra)
                r = s.post(queueUri, headers = headers, data = json.dumps( \
                     {'OrthancInstanceID' : oid, \
                      'State' : 'done' if state else 'error'}))
                if r.status_code != 200:
                    _logger.error(f"status not updated for {oid}: {r.content}")
                           
        time.sleep(pause)
        
        