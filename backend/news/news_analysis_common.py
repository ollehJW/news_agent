"""Shared structured-output validation and bounded analysis concurrency."""
import asyncio
import json
from backend.integrations.llm_client import InvalidLLMResponse

def object_schema(properties):
    return {'type':'object','additionalProperties':False,'required':list(properties),'properties':properties}
def array_schema(name,properties):
    return object_schema({name:{'type':'array','items':object_schema(properties)}})
def parse(raw,key,expected):
    try:
        data=json.loads(raw)
        rows=data[key]
        if not isinstance(rows,list) or any(not isinstance(r,dict) for r in rows):raise ValueError()
        if key!='groups':
            ids=[r['article_id'] for r in rows]
            if len(ids)!=len(set(ids)) or set(ids)!=set(expected):raise ValueError()
        return rows
    except (ValueError,KeyError,TypeError):raise InvalidLLMResponse('Missing, duplicate, or unknown analysis IDs') from None

async def parallel_batches(items,worker):
    semaphore=asyncio.Semaphore(3)
    async def run(batch):
        async with semaphore:return await worker(batch)
    tasks=[asyncio.create_task(run(items[i:i+8])) for i in range(0,len(items),8)]
    try:return [row for batch in await asyncio.gather(*tasks) for row in batch]
    finally:
        for task in tasks:
            if not task.done():task.cancel()
        await asyncio.gather(*tasks,return_exceptions=True)

