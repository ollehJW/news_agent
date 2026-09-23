"""Resolve newsletter images to local article files for MIME related attachments."""
import hashlib
from backend.core.auth import database
from backend.news.image_storage import ensure_article_image,read_stored_image
from backend.mail.email_html import Document,article_nodes


def prepare_inline_images(html):
    sources={}
    attachments=[]
    total=0
    root=Document(html).root
    urls=dict.fromkeys(image.attrs.get('src','') for article in article_nodes(root) for image in article.find('img'))
    for url in urls:
        sources[url]=''
        with database() as db:
            article=db.execute('SELECT article_id FROM articles WHERE image_url=? ORDER BY collected_at DESC LIMIT 1',(url,)).fetchone()
        if not article:continue
        aid=article['article_id']
        path=ensure_article_image(aid)
        data=read_stored_image(aid,path)
        if not data or total+len(data)>10*1024*1024:continue
        cid='article-'+hashlib.sha256(url.encode()).hexdigest()[:24]+'@wianews'
        sources[url]='cid:'+cid
        attachments.append({'cid':cid,'data':data,'filename':aid+'.jpg'})
        total+=len(data)
    return sources,attachments
