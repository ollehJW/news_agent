import test from 'node:test';
import assert from 'node:assert/strict';
import { normalizeDomain, collectDemo, rankNews, newsletterHTML } from './lib.js';
test('domain normalization accepts public hosts and rejects unsafe inputs',()=>{
  assert.equal(normalizeDomain('https://www.Example.com/blog'),'example.com');
  for(const value of ['javascript:alert(1)','https://user:pass@example.com','localhost','https://example.com:8080','bad host.com','-bad.com']) assert.throws(()=>normalizeDomain(value));
});
test('collection honors selected hosts and ranking removes duplicates before selecting five',()=>{
  const data=collectDemo('React',[{name:'React',host:'react.dev'}],{start:'2026-09-01',end:'2026-09-07'});
  const ranked=rankNews(data);
  assert.equal(data.length,9);assert.equal(ranked.length,5);
  assert.equal(new Set(ranked.map(n=>n.issue)).size,5);
  assert.ok(data.every(n=>n.host==='react.dev'&&n.date==='2026-09-07'));
  assert.ok(ranked.every((n,i)=>n.score>=70&&(i===0||ranked[i-1].score>=n.score)));
  assert.equal(rankNews([{...data[0],scores:[0,0,0,0]}]).length,0);
});
test('export escapes user text',()=>{
  const html=newsletterHTML({title:'<script>alert(1)</script>',topic:'<img>',dates:{start:'a',end:'b'},issues:[]});
  assert.ok(!html.includes('<script>'));assert.ok(html.includes('&lt;script&gt;'));assert.ok(html.includes('&lt;img&gt;'));
});
