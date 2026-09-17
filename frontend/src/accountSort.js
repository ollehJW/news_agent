const roleOrder = ['대표이사', '전무', '상무', '실장', '팀장', '책임매니저', '책임연구원', '매니저', '연구원', '사원'];
const collator = new Intl.Collator('ko-KR');
const normalize = value => String(value ?? '').normalize('NFKC').trim();
function roleRank(name) {
  const index = roleOrder.indexOf(normalize(name).replace(/\s/g, ''));
  return index < 0 ? roleOrder.length : index;
}

export function sortAccounts(accounts) {
  return [...accounts].sort((a, b) =>
    collator.compare(normalize(a.team_name), normalize(b.team_name)) ||
    roleRank(a.role_name) - roleRank(b.role_name) ||
    collator.compare(normalize(a.full_name), normalize(b.full_name)) ||
    collator.compare(normalize(a.employee_id), normalize(b.employee_id))
  );
}
