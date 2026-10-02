import test from 'node:test';
import assert from 'node:assert/strict';
import { serviceUrl } from './serviceUrl.js';

test('API and media URLs retain the prefix only inside the portal mount', () => {
  for (const pathname of ['/wianews', '/wianews/', '/wianews/nested']) {
    assert.equal(serviceUrl('/api/auth/me', pathname), '/wianews/api/auth/me');
    assert.equal(serviceUrl('/media/intro.mp4', pathname), '/wianews/media/intro.mp4');
    assert.equal(serviceUrl('/guides/manual.pptx', pathname), '/wianews/guides/manual.pptx');
  }
  for (const pathname of ['/', '/wianews-other/']) {
    assert.equal(serviceUrl('/api/auth/me', pathname), '/api/auth/me');
  }
});

test('external URLs, hash links and missing resources are unchanged', () => {
  for (const value of [null, '', '#app', 'https://example.org/guide', '//example.org/guide']) {
    assert.equal(serviceUrl(value, '/wianews/'), value);
  }
});
