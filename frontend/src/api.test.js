import test from 'node:test';
import assert from 'node:assert/strict';
import { streamRecommendedDomains } from './api.js';

const domain = { host:'react.dev', name:'리액트', kind:'공식', desc:'설명', reason:'근거', relevance:'관련성' };
const encode = (type, data) => new TextEncoder().encode(`event: ${type}\ndata: ${JSON.stringify(data)}\n\n`);

test('renders complete domains before the final event, including split Korean UTF-8 bytes', async t => {
  let source;
  const body = new ReadableStream({start(controller) {source = controller;}});
  t.mock.method(globalThis, 'fetch', async () => new Response(body, {headers:{'content-type':'text/event-stream'}}));
  const received = [];
  let first;
  const early = new Promise(resolve => {first = resolve;});
  let finished = false;
  const promise = streamRecommendedDomains('React', undefined, d => {received.push(d); first();}).then(()=>{finished=true;});
  const event = encode('domain', domain);
  for (const byte of event) source.enqueue(new Uint8Array([byte]));
  await early;
  assert.equal(received[0].name, '리액트');
  assert.equal(finished, false);
  source.enqueue(encode('domain', domain));
  source.enqueue(encode('done', {count:1}));
  source.close();
  await promise;
  assert.equal(received.length, 1);
});

test('preserves received domains on error or unexpected disconnect', async t => {
  for (const type of ['error','disconnect']) {
    const received=[];
    const body = new ReadableStream({start(controller) {
      controller.enqueue(encode('domain',domain));
      if(type==='error')controller.enqueue(encode('error',{message:'중단되었습니다'}));
      controller.close();
    }});
    const mock = t.mock.method(globalThis,'fetch',async()=>new Response(body,{headers:{'content-type':'text/event-stream'}}));
    await assert.rejects(streamRecommendedDomains('React',undefined,d=>received.push(d)));
    assert.equal(received.length,1);
    mock.mock.restore();
  }
});
