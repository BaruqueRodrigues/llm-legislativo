"""Servidor local determinístico para concorrência, META e retries; sem rede externa."""
import http.server,json,pathlib,sys,threading,time
root=pathlib.Path(sys.argv[1]);lock=threading.Lock();counts={};active=0;peak=0
body=b'%PDF-1.7\n%\x00binary\n1 0 obj<</Type/Catalog>>endobj\n%%EOF\n'
class Handler(http.server.BaseHTTPRequestHandler):
 protocol_version='HTTP/1.1'
 def log_message(self,*args):pass
 def do_GET(self):
  global active,peak
  with lock:
   counts[self.path]=counts.get(self.path,0)+1;n=counts[self.path];active+=1;peak=max(peak,active)
   with (root/'events.jsonl').open('a') as f:f.write(json.dumps({'path':self.path,'at':time.time(),'event':'start','active':active})+'\n')
  try:
   code=200;headers={};content=body;mime='application/pdf'
   if self.path=='/slow':time.sleep(.65)
   else:time.sleep(.015)
   if self.path=='/retry' and n==1:code=429;headers['Retry-After']='1';content=b'retry'
   if self.path=='/meta':content=b'<html><meta http-equiv="refresh" content="0; URL=/final"></html>';mime='text/html'
   if self.path=='/html':content=b'<html>erro</html>';mime='text/html'
   value=self.headers.get('Range')
   if value and self.path=='/range':
    offset=int(value.removeprefix('bytes=').removesuffix('-'));code=206;content=body[offset:];headers['Content-Range']=f'bytes {offset}-{len(body)-1}/{len(body)}'
   self.send_response(code);self.send_header('Content-Type',mime);self.send_header('Content-Length',str(len(content)))
   for k,v in headers.items():self.send_header(k,v)
   self.end_headers();self.wfile.write(content)
  finally:
   with lock:
    active-=1
    with (root/'events.jsonl').open('a') as f:f.write(json.dumps({'path':self.path,'at':time.time(),'event':'end','active':active,'peak':peak})+'\n')
server=http.server.ThreadingHTTPServer(('127.0.0.1',0),Handler)
(root/'port').write_text(str(server.server_port));server.serve_forever()
