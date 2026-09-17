import test from 'node:test';
import assert from 'node:assert/strict';
import { sortAccounts } from './accountSort.js';

const account = (employee_id, team_name, role_name, full_name) => ({employee_id, team_name, role_name, full_name});
test('accounts sort by team, explicit job-title precedence, then Korean name without mutation', () => {
  const roles=['대표이사','전무','상무','실장','팀장','책임매니저','책임연구원','매니저','연구원','사원'];
  const input=roles.map((role,i)=>account(String(i),'개발팀',role,i%2?'가나다':'홍길동')).reverse();
  input.unshift(account('other','개발팀','인턴','가나다'));
  input.unshift(account('later-team','영업팀','대표이사','가나다'));
  input.push(account('first-team','가공팀','기타','홍길동'));
  const snapshot=structuredClone(input);
  assert.deepEqual(sortAccounts(input).map(u=>u.employee_id),['first-team',...roles.map((_,i)=>String(i)),'other','later-team']);
  assert.deepEqual(input,snapshot);
});
test('same-rank and unlisted titles sort by name; additions and filtered results retain order', () => {
  const input=[account('3','개발팀','책임 매니저','홍길동'),account('2','개발팀','책임매니저','김길동'),account('5','개발팀','고문','홍길동'),account('4','개발팀','인턴','김길동')];
  assert.deepEqual(sortAccounts(input).map(u=>u.employee_id),['2','3','4','5']);
  assert.deepEqual(sortAccounts([account('1','개발팀','팀장','이길동'),...input]).map(u=>u.employee_id),['1','2','3','4','5']);
  assert.deepEqual(sortAccounts(input).filter(u=>u.full_name==='김길동').map(u=>u.employee_id),['2','4']);
});
