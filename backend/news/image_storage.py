"""Bounded public-image downloads and article-owned local storage."""
import hashlib
import io
import ipaddress
import logging
import os
from pathlib import Path
import socket
import ssl
import tempfile
from urllib.parse import urlsplit,urljoin
import uuid
import warnings
import httpx
from PIL import Image,ImageOps
from dotenv import dotenv_values
from backend.core.paths import BACKEND_DIR,PROJECT_DIR
from backend.core.auth import database

WORKSPACE=BACKEND_DIR/'workspace'
MAX_BYTES=8*1024*1024
log=logging.getLogger(__name__)


def download_image(url):
    settings={**dotenv_values(PROJECT_DIR/'.env'),**os.environ}
    tls=ssl.create_default_context(cafile=settings.get('EXA_CA_BUNDLE') or None)
    if settings.get('EXA_LEGACY_CA')=='1':tls.verify_flags &= ~ssl.VERIFY_X509_STRICT
    with httpx.Client(verify=tls,trust_env=False,timeout=12,follow_redirects=False) as client:
        for _ in range(5):
            parsed=urlsplit(url)
            if parsed.scheme not in ('https','http') or not parsed.hostname or parsed.username or parsed.password or parsed.port not in (None,80,443):raise ValueError('Invalid image URL')
            port=parsed.port or (443 if parsed.scheme=='https' else 80)
            addresses={r[4][0] for r in socket.getaddrinfo(parsed.hostname,port,type=socket.SOCK_STREAM)}
            if not addresses or any(not ipaddress.ip_address(ip).is_global for ip in addresses):raise ValueError('Non-public image host')
            ip=sorted(addresses,key=lambda v:':' in v)[0]
            # Pin the resolved address; preserve TLS hostname verification and HTTP host.
            target=httpx.URL(url).copy_with(host=ip)
            with client.stream('GET',target,headers={'Host':parsed.netloc,'User-Agent':'WiaNews/1.0'},extensions={'sni_hostname':parsed.hostname}) as response:
                if response.status_code in (301,302,303,307,308):
                    url=urljoin(url,response.headers.get('location',''));continue
                response.raise_for_status()
                data=bytearray()
                for chunk in response.iter_bytes():
                    data.extend(chunk)
                    if len(data)>MAX_BYTES:raise ValueError('Image too large')
                return bytes(data)
    raise ValueError('Too many image redirects')


def normalize_image(data):
    with warnings.catch_warnings():
        warnings.simplefilter('error',Image.DecompressionBombWarning)
        with Image.open(io.BytesIO(data)) as source:
            if source.format not in ('JPEG','PNG','WEBP','GIF'):raise ValueError('Unsupported image')
            if source.width*source.height>25_000_000:raise ValueError('Image dimensions too large')
            source.seek(0)
            image=ImageOps.exif_transpose(source)
            image.thumbnail((1280,1280))
            # Flatten transparency for consistent JPEG rendering in email clients.
            rgba=image.convert('RGBA')
            canvas=Image.new('RGB',rgba.size,'white');canvas.paste(rgba,mask=rgba.getchannel('A'))
            out=io.BytesIO();canvas.save(out,format='JPEG',quality=88,optimize=True)
            return out.getvalue()


def read_stored_image(article_id,path):
    if not path:return None
    try:
        aid=str(uuid.UUID(article_id))
        target=(BACKEND_DIR/path).resolve()
        expected=(WORKSPACE/aid).resolve()
        if not expected.is_relative_to(WORKSPACE.resolve()) or not target.is_relative_to(expected):return None
        if target.suffix!='.jpg' or target.stat().st_size>MAX_BYTES:return None
        data=target.read_bytes()
        return data if data.startswith(b'\xff\xd8\xff') else None
    except (OSError,ValueError):return None


def ensure_article_image(article_id):
    with database() as db:
        row=db.execute('SELECT article_id,image_url,image_storage_path FROM articles WHERE article_id=?',(article_id,)).fetchone()
    if not row or not row['image_url']:return None
    existing=read_stored_image(article_id,row['image_storage_path'])
    if existing:return row['image_storage_path']
    try:
        aid=str(uuid.UUID(article_id))
        data=normalize_image(download_image(row['image_url']))
        folder=WORKSPACE/aid;folder.mkdir(parents=True,exist_ok=True)
        if not folder.resolve().is_relative_to(WORKSPACE.resolve()):raise ValueError('Invalid workspace path')
        name='image-'+hashlib.sha256(row['image_url'].encode()).hexdigest()[:16]+'.jpg'
        target=folder/name
        fd,temp=tempfile.mkstemp(dir=folder,suffix='.tmp')
        try:
            with os.fdopen(fd,'wb') as file:file.write(data)
            os.replace(temp,target)
        finally:
            if os.path.exists(temp):os.unlink(temp)
        path=str(target.relative_to(BACKEND_DIR))
        with database() as db:
            changed=db.execute('UPDATE articles SET image_storage_path=? WHERE article_id=? AND image_url=?',(path,article_id,row['image_url'])).rowcount
        return path if changed else None
    except (OSError,ValueError,httpx.HTTPError,Image.DecompressionBombError,Image.DecompressionBombWarning):
        log.warning('Article image unavailable (article_id=%s)',article_id)
        return None
