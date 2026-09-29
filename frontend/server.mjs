// Serve the built frontend over HTTPS and stream API requests to the local backend.
import https from 'node:https';
import http from 'node:http';
import {readFileSync,createReadStream} from 'node:fs';
import {stat,realpath} from 'node:fs/promises';
import {fileURLToPath} from 'node:url';
import {resolve,sep,extname} from 'node:path';

const root=await realpath(fileURLToPath(new URL('./dist',import.meta.url)));
const target=new URL(process.env.BACKEND_ORIGIN||'http://127.0.0.1:9801');
if(target.protocol!=='http:'||!['127.0.0.1','localhost'].includes(target.hostname))throw new Error('Backend must be local HTTP');
const options={cert:readFileSync(process.env.WIANEWS_TLS_CERT),key:readFileSync(process.env.WIANEWS_TLS_KEY),minVersion:'TLSv1.2'};
const mime={'.html':'text/html; charset=utf-8','.js':'text/javascript; charset=utf-8','.css':'text/css; charset=utf-8','.json':'application/json','.svg':'image/svg+xml','.png':'image/png','.jpg':'image/jpeg','.jpeg':'image/jpeg','.webp':'image/webp','.ico':'image/x-icon','.woff':'font/woff','.woff2':'font/woff2'};
const hop=new Set(['connection','keep-alive','proxy-authenticate','proxy-authorization','te','trailer','transfer-encoding','upgrade']);
function headersWithoutHop(headers){const blocked=new Set([...hop,...String(headers.connection||'').toLowerCase().split(',').map(v=>v.trim())]);return Object.fromEntries(Object.entries(headers).filter(([key])=>!blocked.has(key)));}
function error(res,status,message){if(res.headersSent){res.destroy();return;}res.writeHead(status,{'Content-Type':'text/plain; charset=utf-8','Cache-Control':'no-store'});res.end(message);}

const server=https.createServer(options,async(req,res)=>{
  res.setHeader('X-Content-Type-Options','nosniff');
  let pathname;
  try{pathname=decodeURIComponent(new URL(req.url,'https://localhost').pathname);}catch{return error(res,400,'Invalid URL');}
  if(pathname==='/api'||pathname.startsWith('/api/')){
    const headers={...headersWithoutHop(req.headers),host:target.host,'x-forwarded-proto':'https','x-forwarded-host':req.headers.host,'x-forwarded-for':req.socket.remoteAddress};
    const upstream=http.request({hostname:target.hostname,port:target.port||80,path:req.url,method:req.method,headers},reply=>{
      res.writeHead(reply.statusCode,headersWithoutHop(reply.headers));res.flushHeaders();reply.pipe(res);
      reply.on('error',()=>res.destroy());
    });
    upstream.setTimeout(660000,()=>upstream.destroy());
    upstream.on('error',()=>error(res,502,'Backend unavailable'));
    req.on('aborted',()=>upstream.destroy());res.on('close',()=>{if(!res.writableEnded)upstream.destroy();});req.pipe(upstream);return;
  }
  if(!['GET','HEAD'].includes(req.method))return error(res,405,'Method not allowed');
  if(pathname.split('/').some(part=>part.startsWith('.')))return error(res,404,'Not found');
  try{
    let filename=resolve(root,'.'+pathname);
    if(filename!==root&&!filename.startsWith(root+sep))return error(res,403,'Forbidden');
    let info;
    try{info=await stat(filename);}catch{}
    if(!info?.isFile()){
      if(extname(pathname)||pathname.startsWith('/assets/'))return error(res,404,'Not found');
      filename=resolve(root,'index.html');info=await stat(filename);
    }
    filename=await realpath(filename);
    if(!filename.startsWith(root+sep))return error(res,403,'Forbidden');
    res.writeHead(200,{'Content-Type':mime[extname(filename)]||'application/octet-stream','Content-Length':info.size,'Cache-Control':pathname.startsWith('/assets/')?'public, max-age=31536000, immutable':'no-cache'});
    if(req.method==='HEAD')return res.end();
    const stream=createReadStream(filename);stream.on('error',()=>res.destroy());stream.pipe(res);
  }catch{error(res,500,'Unable to serve frontend');}
});
server.requestTimeout=120000;
server.listen(Number(process.env.FRONTEND_PORT||9802),process.env.FRONTEND_HOST||'0.0.0.0',()=>console.log('WiaNews HTTPS frontend listening on '+(process.env.FRONTEND_PORT||9802)));
for(const signal of ['SIGINT','SIGTERM'])process.on(signal,()=>{server.close(()=>process.exit(0));setTimeout(()=>process.exit(0),30000).unref();});
