"""Shared bounded Exa retrieval for newsletter pipelines; never fetch arbitrary URLs locally."""
import asyncio
import os
import ssl
from datetime import date, datetime, time, timedelta, timezone
from urllib.parse import urlsplit, urlunsplit, parse_qsl, urlencode
from zoneinfo import ZoneInfo
import httpx
from fastapi import HTTPException
from backend.news.article_images import article_image_url

KST = ZoneInfo('Asia/Seoul')

def canonical_url(value):
    if not isinstance(value,str): return None
    try:
        url=urlsplit(value)
        if url.scheme not in ('http','https') or not url.hostname or url.username or url.password or url.port not in (None,80,443): return None
        host=url.hostname.lower().removeprefix('www.')
        query=[(k,v) for k,v in parse_qsl(url.query,keep_blank_values=True) if not k.lower().startswith('utm_') and k.lower() not in ('fbclid','gclid','msclkid')]
        return urlunsplit((url.scheme,host,url.path or '/',urlencode(sorted(query)),''))
    except ValueError:return None

def publication_day(value):
    if not isinstance(value,str):return None
    try:
        stamp=datetime.fromisoformat(value.replace('Z','+00:00'))
        # Exa often supplies a date-only UTC-midnight timestamp; date remains correct in KST.
        return stamp.replace(tzinfo=timezone.utc).astimezone(KST).date() if stamp.tzinfo is None else stamp.astimezone(KST).date()
    except ValueError:return None

def normalize_results(results,domains,start,end):
    by_url={}; rejected=0
    hosts=sorted(domains,key=lambda d:len(d['host']),reverse=True)
    for item in results:
        url=canonical_url(item.get('url'));published=publication_day(item.get('publishedDate'))
        host=urlsplit(url).hostname if url else ''
        domain=next((d for d in hosts if host==d['host'] or host.endswith('.'+d['host'])),None)
        title=item.get('title');content=item.get('text')
        if not url or not domain or not published or not start<=published<=end or published>datetime.now(KST).date() or not isinstance(title,str) or not title.strip() or not isinstance(content,str) or len(content.strip())<120:
            rejected+=1;continue
        row={'url':url,'domain_id':domain['domain_id'],'title':title.strip()[:1000],'published_at':published.isoformat(),
             'content':content[:20000],
             'highlights':[h for h in item.get('highlights',[]) if isinstance(h,str) and h.strip()] if isinstance(item.get('highlights'),list) else None,
             'image_url':article_image_url(canonical_url(item.get('image')),canonical_url(item.get('favicon'))),'favicon_url':canonical_url(item.get('favicon'))}
        if url not in by_url or len(row['content'])>len(by_url[url]['content']):by_url[url]=row
    return list(by_url.values()),rejected

async def search_articles(queries,domains,start,end,on_progress):
    if not 1<=len(queries)<=5:raise HTTPException(400,'검색 쿼리는 1~5개로 설정해 주세요.')
    key=os.getenv('EXA_API_KEY','').strip()
    if not key:raise HTTPException(503,'Exa API 키가 설정되지 않았습니다.')
    tls=ssl.create_default_context(cafile=os.getenv('EXA_CA_BUNDLE') or None)
    if os.getenv('EXA_LEGACY_CA')=='1':tls.verify_flags &= ~ssl.VERIFY_X509_STRICT
    lower=datetime.combine(start,time.min,KST).astimezone(timezone.utc)
    upper=datetime.combine(end+timedelta(days=1),time.min,KST).astimezone(timezone.utc)
    semaphore=asyncio.Semaphore(3);done=0
    async with httpx.AsyncClient(verify=tls,timeout=httpx.Timeout(55,connect=15)) as client:
        async def search(query):
            nonlocal done
            async with semaphore:
                for attempt in range(2):
                    try:
                        res=await client.post('https://api.exa.ai/search',headers={'x-api-key':key},json={
                            'query':query['query'],'type':'auto','numResults':10,'includeDomains':[d['host'] for d in domains],
                            'startPublishedDate':lower.isoformat(),'endPublishedDate':upper.isoformat(),
                            'contents':{'text':{'maxCharacters':20000},'highlights':True}})
                    except httpx.HTTPError:
                        if attempt==0:await asyncio.sleep(1);continue
                        raise HTTPException(502,'Exa 검색 서비스에 연결하지 못했습니다. 네트워크와 인증서를 확인해 주세요.') from None
                    if res.status_code==429 or res.status_code>=500:
                        if attempt==0:await asyncio.sleep(1);continue
                    if res.status_code!=200:raise HTTPException(502,f'Exa 검색에 실패했습니다 (HTTP {res.status_code}). API 설정과 사용 한도를 확인해 주세요.')
                    try:
                        data=res.json();results=data['results']
                        if not isinstance(results,list) or any(not isinstance(r,dict) for r in results):raise ValueError()
                    except (ValueError,KeyError,TypeError):raise HTTPException(502,'Exa 검색 결과 형식이 올바르지 않습니다.') from None
                    done+=1;await on_progress(0,f'검색 쿼리 {done}/{len(queries)}개 수집 완료')
                    return results[:10]
        tasks=[asyncio.create_task(search(q)) for q in queries]
        try:groups=await asyncio.gather(*tasks)
        finally:
            for task in tasks:
                if not task.done():task.cancel()
            await asyncio.gather(*tasks,return_exceptions=True)
    raw=[r for group in groups for r in group]
    articles,rejected=normalize_results(raw,domains,start,end)
    return articles,{'search_results':len(raw),'invalid_results':rejected,'url_duplicates':len(raw)-rejected-len(articles)}
