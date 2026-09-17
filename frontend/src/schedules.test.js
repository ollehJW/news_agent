import test from 'node:test';
import assert from 'node:assert/strict';
import { nextOccurrence, validateSchedule } from './schedules.js';
const base={name:'월요일 브리핑',newsletterId:'n1',frequency:'weekly',weekdays:[1],monthDay:1,time:'09:00',startDate:'2026-09-01'};
test('weekly schedule uses KST and skips elapsed execution time',()=>{
  assert.equal(nextOccurrence(base,new Date('2026-09-13T23:00:00Z')).toISOString(),'2026-09-14T00:00:00.000Z');
  assert.equal(nextOccurrence(base,new Date('2026-09-14T00:00:00Z')).toISOString(),'2026-09-21T00:00:00.000Z');
});
test('month-end and far future start dates are handled',()=>{
  assert.equal(nextOccurrence({...base,frequency:'monthly',monthDay:31,startDate:'2027-02-01'},new Date('2027-02-01T00:00:00Z')).toISOString(),'2027-02-28T00:00:00.000Z');
  assert.equal(nextOccurrence({...base,frequency:'daily',startDate:'2030-01-01'},new Date('2026-01-01T00:00:00Z')).toISOString(),'2030-01-01T00:00:00.000Z');
});
test('invalid dates, empty weekday selection and malformed records are rejected',()=>{
  for(const patch of [{name:''},{weekdays:[]},{time:'25:00'},{startDate:'2026-02-31'},{newsletterId:''}]) assert.ok(validateSchedule({...base,...patch}));
});
