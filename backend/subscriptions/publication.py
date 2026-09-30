"""Shared subscription editions and one durable email submission per subscription."""
from backend.subscriptions.usage import subscription_sample_context
import asyncio
import calendar
import json
import re
import uuid
from datetime import datetime,date,time,timedelta,timezone
from pathlib import Path
from weakref import WeakValueDictionary
from fastapi import HTTPException
from backend.core.auth import database,now
from backend.core.error_storage import record_error
from backend.core.tracking import llm_user_context
from backend.news.article_repository import decode
from backend.news.scoring_rules import evaluation_complete
from backend.news.newsletter_summary import generate_newsletter_summary
from backend.news.newsletter_rendering import render_newsletter
from backend.subscriptions.collection import KST
from backend.subscriptions.selection import select_issues
from backend.mail import delivery as mail

_locks=WeakValueDictionary()


def init_publication_db():
    with database() as db:
        for statement in Path(__file__).with_name('publication_schema.sql').read_text().split(';'):
            if statement.strip():db.execute(statement)


def matches_day(settings,day):
    if day<date.fromisoformat(settings['start_date']):return False
    if settings['frequency']=='daily':return True
    if settings['frequency']=='weekly':return (day.weekday()+1)%7 in json.loads(settings['weekdays'])
    return day.day==min(settings['month_day'],calendar.monthrange(day.year,day.month)[1])


def due_publications(clock=None):
    clock=(clock or datetime.now(KST)).astimezone(KST)
    scheduled=datetime.combine(clock.date(),time(8),KST)
    if clock<scheduled:return []
    with database() as db:
        rows=db.execute("""SELECT s.*,st.frequency,st.weekdays,st.month_day,st.start_date
            FROM subscriptions s JOIN subscription_settings st USING(subscription_id)
            JOIN users u USING(user_id) WHERE s.status='active' AND u.is_active=1""").fetchall()
        due=[]
        for row in rows:
            # A subscription created after today's 08:00 starts on its next scheduled date.
            if datetime.fromisoformat(row['created_at'])>scheduled or not matches_day(row,clock.date()):continue
            job=db.execute('SELECT * FROM subscription_publication_jobs WHERE subscription_id=? AND scheduled_date=?',(row['subscription_id'],clock.date().isoformat())).fetchone()
            if job:
                if job['status'] in ('completed','skipped','review'):continue
                age=clock-datetime.fromisoformat(job['started_at'])
                if job['status']=='running' and age<timedelta(minutes=15):continue
                if job['status']=='failed' and (job['attempt']>=3 or age<timedelta(hours=1)):continue
            due.append((row['subscription_id'],clock.date()))
    return due


def claim_job(sid,day):
    stamp=now();token=str(uuid.uuid4())
    with database() as db:
        db.execute('BEGIN IMMEDIATE')
        sub=db.execute("""SELECT s.*,st.name,st.frequency,st.weekdays,st.month_day,st.start_date,d.topic
            FROM subscriptions s JOIN subscription_settings st USING(subscription_id)
            JOIN sample_details d ON d.sample_id=s.sample_id JOIN users u ON u.user_id=s.user_id
            WHERE s.subscription_id=? AND s.status='active' AND u.is_active=1""",(sid,)).fetchone()
        if not sub:return None,None
        if not matches_day(sub,day):return None,None
        existing=db.execute('SELECT * FROM subscription_publication_jobs WHERE subscription_id=? AND scheduled_date=?',(sid,day.isoformat())).fetchone()
        if existing:
            if existing['status'] in ('completed','skipped','review'):return None,None
            if existing['status']=='running' and datetime.now(timezone.utc)-datetime.fromisoformat(existing['started_at'])<timedelta(minutes=15):return None,None
            db.execute("UPDATE subscription_publication_jobs SET status='running',attempt=attempt+1,attempt_token=?,started_at=?,completed_at=NULL WHERE job_id=?",(token,stamp,existing['job_id']))
            jid=existing['job_id']
        else:
            jid=str(uuid.uuid4())
            db.execute("INSERT INTO subscription_publication_jobs(job_id,subscription_id,scheduled_date,status,attempt_token,started_at) VALUES(?,?,?,'running',?,?)",(jid,sid,day.isoformat(),token,stamp))
        return dict(db.execute('SELECT * FROM subscription_publication_jobs WHERE job_id=?',(jid,)).fetchone()),dict(sub)


def job_current(db,job):
    return bool(db.execute("SELECT 1 FROM subscription_publication_jobs WHERE job_id=? AND attempt_token=? AND status='running'",(job['job_id'],job['attempt_token'])).fetchone())


def finish_job(job,status,newsletter_id=None):
    with database() as db:
        db.execute('UPDATE subscription_publication_jobs SET status=?,newsletter_id=COALESCE(?,newsletter_id),completed_at=? WHERE job_id=? AND attempt_token=?',
            (status,newsletter_id,now(),job['job_id'],job['attempt_token']))


def recipients_for_subscription(db,sid):
    rows=db.execute("""SELECT m.member_type,m.user_id,
        CASE WHEN m.member_type='internal' THEN u.email ELSE m.email_address END AS email_address,
        CASE WHEN m.member_type='internal' THEN u.full_name ELSE m.email_address END AS name
        FROM subscription_members m LEFT JOIN users u USING(user_id)
        WHERE m.subscription_id=? AND m.status='active' AND (m.member_type='external' OR (u.is_active=1 AND u.is_admin=0))
        ORDER BY m.member_type,m.member_id""",(sid,)).fetchall()
    recipients=[]
    for row in rows:
        value=dict(row);address=(value['email_address'] or '').strip().lower()
        if not re.fullmatch(r'[^\s@]+@[^\s@]+\.[^\s@]+',address):
            raise HTTPException(422,'구독 수신자의 이메일을 확인해 주세요.')
        value['email_address']=address;recipients.append(value)
    return recipients


def coverage(db,sub,day):
    previous=db.execute('''SELECT max(n.coverage_end_date) FROM subscription_history h
        JOIN subscripted_newsletters n USING(newsletter_id)
        WHERE h.subscription_id=? AND n.coverage_end_date<?''',(sub['subscription_id'],day.isoformat())).fetchone()[0]
    # Since 05:00 collection fetches yesterday, an 08:00 edition ends yesterday.
    start=date.fromisoformat(previous)+timedelta(days=1) if previous else max(date.fromisoformat(sub['start_date']),datetime.fromisoformat(sub['created_at']).astimezone(KST).date())
    return start,day-timedelta(days=1)


def existing_edition(db,sample_id,start,end):
    row=db.execute('SELECT * FROM subscripted_newsletters WHERE sample_id=? AND coverage_start_date=? AND coverage_end_date=?',
        (sample_id,start.isoformat(),end.isoformat())).fetchone()
    return dict(row) if row else None


async def get_edition(sub,day):
    with database() as db:start,end=coverage(db,sub,day)
    if start>end:return None
    key=(sub['sample_id'],start,end)
    lock=_locks.get(key)
    if lock is None:lock=asyncio.Lock();_locks[key]=lock
    async with lock:
        with database() as db:
            saved=existing_edition(db,sub['sample_id'],start,end)
            if saved:return saved
            collected=db.execute("SELECT 1 FROM subscription_collection_runs WHERE sample_id=? AND collection_date=? AND status='completed'",(sub['sample_id'],end.isoformat())).fetchone()
            if not collected:raise HTTPException(409,'전날 기사 수집이 아직 완료되지 않았습니다.')
            rows=[decode(r) for r in db.execute('''SELECT a.* FROM articles a JOIN subscripted_articles sa USING(article_id)
                WHERE sa.sample_id=? AND a.published_at>=? AND a.published_at<=?
                ORDER BY a.total_score DESC,a.published_at DESC,a.article_id''',(sub['sample_id'],start.isoformat(),end.isoformat()))]
        # Avoid silently issuing an incomplete edition while evaluation is still pending.
        if any(not evaluation_complete(a) for a in rows):raise HTTPException(409,'구독 기사 평가가 완료되지 않았습니다.')
        candidates=[a for a in rows if a['total_score'] is not None and a['total_score']>=70][:50]
        if not candidates:return None
        selected,request_id=await select_issues(sub['topic'],candidates)
        if not selected:return None
        issues=[{'title':a['newsletter_title'],'summary':a['summary'],'date':a['published_at'],
            'imageUrl':a['image_url'],'imageAlt':a['newsletter_title'],'url':a['url']} for a in selected]
        summary,summary_request=await generate_newsletter_summary(sub['topic'],issues,operation='subscription_newsletter_summary')
        html=render_newsletter(title=sub['topic'],dates={'start':start.isoformat(),'end':end.isoformat()},issues=issues,total_summary=summary)
        with database() as db:
            db.execute('BEGIN IMMEDIATE')
            saved=existing_edition(db,sub['sample_id'],start,end)
            if saved:return saved
            stamp=now();nid=str(uuid.uuid4());ids=[]
            for rank,article in enumerate(selected,1):
                iid=str(uuid.uuid4());ids.append(iid)
                db.execute('INSERT INTO subscripted_issues(issue_id,subscription_id,article_id,request_id,summary,rank,created_at) VALUES(?,?,?,?,?,?,?)',
                    (iid,sub['subscription_id'],article['article_id'],request_id,article['summary'],rank,stamp))
            db.execute('''INSERT INTO subscripted_newsletters(newsletter_id,sample_id,coverage_start_date,coverage_end_date,issue_ids,summary,request_id,html_content,created_at,published_at)
                VALUES(?,?,?,?,?,?,?,?,?,?)''',(nid,sub['sample_id'],start.isoformat(),end.isoformat(),json.dumps(ids),summary,summary_request,html,stamp,stamp))
            db.execute('''UPDATE sample_newsletters SET last_issued_newsletter_id=? WHERE sample_id=? AND
                (last_issued_newsletter_id IS NULL OR COALESCE((SELECT coverage_end_date FROM subscripted_newsletters WHERE newsletter_id=last_issued_newsletter_id),'')<=?)''',
                (nid,sub['sample_id'],end.isoformat()))
            return dict(db.execute('SELECT * FROM subscripted_newsletters WHERE newsletter_id=?',(nid,)).fetchone())


def send_subscription_edition(job,sub,edition):
    """Prepare first; claim immediately before SMTP. A claimed submission is never repeated."""
    request_id=f"subscription-{sub['subscription_id']}-{job['scheduled_date']}"
    with database() as db:
        previous=db.execute('SELECT * FROM mailing WHERE subscription_id=? AND (request_id=? OR newsletter_id=?)',
            (sub['subscription_id'],request_id,edition['newsletter_id'])).fetchone()
        if previous:return dict(previous)
    sender,password=mail.mail_settings()
    prepared=mail.prepare_inline_images(edition['html_content'])
    with database() as db:
        db.execute('BEGIN IMMEDIATE')
        if not job_current(db,job):raise HTTPException(409,'발행 작업이 만료되었습니다.')
        active=db.execute("SELECT s.* FROM subscriptions s JOIN users u USING(user_id) WHERE s.subscription_id=? AND s.status='active' AND u.is_active=1",(sub['subscription_id'],)).fetchone()
        if not active:return None
        recipients=recipients_for_subscription(db,sub['subscription_id'])
        if not recipients:return None
        previous=db.execute('SELECT * FROM mailing WHERE subscription_id=? AND (request_id=? OR newsletter_id=?)',
            (sub['subscription_id'],request_id,edition['newsletter_id'])).fetchone()
        if previous:return dict(previous)
        mid=str(uuid.uuid4())
        db.execute('''INSERT INTO mailing(mailing_id,user_id,request_id,kind,newsletter_id,subscription_id,subject,sender_email,mailing_list,status,created_at)
            VALUES(?,?,?,'subscription',?,?,?,?,?,'processing',?)''',
            (mid,sub['user_id'],request_id,edition['newsletter_id'],sub['subscription_id'],'[WiaNews] '+' '.join(sub['name'].split()),sender,json.dumps(recipients,ensure_ascii=False),now()))
    addresses=list(dict.fromkeys(r['email_address'] for r in recipients))
    try:
        statuses=mail.deliver(sender,password,addresses,sub['name'],edition['html_content'],prepared=prepared)
    except Exception as error:
        # A crash after submission may mean the message was delivered. Preserve unknown outcomes.
        record_error(sub['user_id'],'subscription_newsletter_email',error)
        statuses={address:'unknown' for address in addresses}
    stamp=now()
    results=[{**r,'status':statuses.get(r['email_address'],'unknown'),
        'sent_at':stamp if statuses.get(r['email_address'])=='sent' else None,'completed_at':stamp} for r in recipients]
    accepted=any(r['status']=='sent' for r in results)
    with database() as db:
        db.execute("UPDATE mailing SET results_json=?,status='completed',sent_at=?,completed_at=? WHERE mailing_id=?",(json.dumps(results,ensure_ascii=False),stamp if accepted else None,stamp,mid))
        if accepted:db.execute('INSERT OR IGNORE INTO subscription_history(subscription_id,newsletter_id,created_at) VALUES(?,?,?)',(sub['subscription_id'],edition['newsletter_id'],stamp))
        return dict(db.execute('SELECT * FROM mailing WHERE mailing_id=?',(mid,)).fetchone())


async def publish_subscription(sid,day):
    job,sub=claim_job(sid,day)
    if not job:return
    usage_token=subscription_sample_context.set(sub['sample_id'])
    token=llm_user_context.set(sub['user_id'])
    try:
        with database() as db:
            prior=db.execute('SELECT * FROM mailing WHERE subscription_id=? AND request_id=?',
                (sid,f"subscription-{sid}-{job['scheduled_date']}")).fetchone()
        if prior:
            outcomes=json.loads(prior['results_json'])
            status='completed' if prior['status']=='completed' and outcomes and all(r['status']=='sent' for r in outcomes) else 'review'
            finish_job(job,status,prior['newsletter_id']);return

        with database() as db:
            if not recipients_for_subscription(db,sid):
                finish_job(job,'skipped');return
        async with asyncio.timeout(600):edition=await get_edition(sub,day)
        if not edition:finish_job(job,'skipped');return
        # SMTP is bounded by its own timeout; do not cancel/retry a possibly submitted message.
        result=await asyncio.to_thread(send_subscription_edition,job,sub,edition)
        if result is None:finish_job(job,'skipped',edition['newsletter_id']);return
        outcomes=json.loads(result['results_json'])
        review=result['status']=='processing' or any(r['status']!='sent' for r in outcomes)
        if review:record_error(sub['user_id'],'subscription_newsletter_email',HTTPException(502,'구독 메일 발송 결과 확인이 필요합니다. 발송 이력을 확인해 주세요.'))
        finish_job(job,'review' if review else 'completed',edition['newsletter_id'])
    except asyncio.CancelledError:
        # Leave the lease for restart recovery; an SMTP thread may still be finishing.
        raise
    except Exception as error:
        record_error(sub['user_id'],'subscription_newsletter_publication',error)
        finish_job(job,'failed')
        raise
    finally:
        llm_user_context.reset(token)
        subscription_sample_context.reset(usage_token)
