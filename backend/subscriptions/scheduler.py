"""Daily 05:00 Asia/Seoul collection, with bounded catch-up and retry."""
import asyncio
import logging
import os
from datetime import datetime,timedelta,timezone,date
from backend.core.auth import database
from backend.subscriptions.collection import KST,collect_sample

log=logging.getLogger(__name__)


def due_jobs(clock=None):
    clock=clock or datetime.now(KST)
    clock=clock.astimezone(KST)
    last_day=clock.date()-timedelta(days=1 if clock.hour>=5 else 2)
    with database() as db:
        subscriptions=db.execute("""SELECT s.sample_id,s.user_id,s.created_at,st.start_date
            FROM subscriptions s JOIN users u USING(user_id)
            LEFT JOIN subscription_settings st USING(subscription_id)
            WHERE s.status='active' AND u.is_active=1 ORDER BY s.created_at,s.subscription_id""").fetchall()
        grouped={}
        for sub in subscriptions:
            created=datetime.fromisoformat(sub['created_at']).astimezone(KST).date()
            first=max(created,date.fromisoformat(sub['start_date']) if sub['start_date'] else created)
            sample=grouped.setdefault(sub['sample_id'],{'user_id':sub['user_id'],'first':first})
            sample['first']=min(sample['first'],first)
        jobs=[]
        for sample_id,sample in grouped.items():
            runs={r['collection_date']:dict(r) for r in db.execute('SELECT * FROM subscription_collection_runs WHERE sample_id=?',(sample_id,))}
            if any(r['status']=='running' and clock.astimezone(timezone.utc)-datetime.fromisoformat(r['started_at'])<timedelta(minutes=10) for r in runs.values()):continue
            day=sample['first'];queued=0
            while day<=last_day and queued<7:
                run=runs.get(day.isoformat())
                if not run or (run['status']!='completed' and run['attempt']<3 and clock.astimezone(timezone.utc)-datetime.fromisoformat(run['started_at'])>=timedelta(hours=1)):
                    jobs.append((sample_id,day,sample['user_id']));queued+=1
                day+=timedelta(days=1)
        return jobs


async def scheduler_loop():
    while True:
        try:
            for sample_id,day,user_id in due_jobs():
                try:await collect_sample(sample_id,day,user_id)
                except asyncio.CancelledError:raise
                except Exception as error:log.warning('Subscription collection failed: sample=%s date=%s type=%s',sample_id,day,type(error).__name__)
        except asyncio.CancelledError:raise
        except Exception:log.exception('Subscription scheduler tick failed')
        await asyncio.sleep(30)


def start_scheduler():
    if os.getenv('WIANEWS_SUBSCRIPTION_COLLECTION_ENABLED','1')!='1':return None
    return asyncio.create_task(scheduler_loop(),name='subscription-daily-collection')
