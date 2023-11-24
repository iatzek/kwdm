function OnStoredInstance(instanceId, tags, metadata)

   -- przy każdej wysyłanej instancji wyślij powiadomienie do zewnętrznego serwisu -- 

   local url = os.getenv('KWDM_ENDPOINT')

   local sop = string.lower(tags['SOPInstanceUID'])
   
   -- ewentualne filtrowanie -- 
   -- if tags['SOPClassUID'] == '1234' and tags["StudyDescription"] 
   -- end

   local headers = {}
   headers['Content-Type'] = 'application/json'

   local body = {}
   body['SOPInstanceUID'] = sop

   HttpPost(url, DumpJson(body, true), headers)

end

