export const SCHEDULE_KEY = 'wianews-schedules-v1';
export const DAYS = ['일', '월', '화', '수', '목', '금', '토'];
export function koreaDate(now = new Date()) { return new Date(now.getTime()+9*3600000).toISOString().slice(0,10); }
export function validateSchedule(item) {
  if (!item.name?.trim() || item.name.length>80) return '구독 이름을 1~80자로 입력해 주세요.';
  if (!item.newsletterId) return '저장된 뉴스레터를 선택해 주세요.';
  if (!['daily','weekly','monthly'].includes(item.frequency)) return '발행 주기를 선택해 주세요.';
  if (!Array.isArray(item.weekdays) || item.weekdays.some(d=>!Number.isInteger(d)||d<0||d>6) || (item.frequency==='weekly'&&!item.weekdays.length)) return '발행 요일을 1개 이상 선택해 주세요.';
  if (!Number.isInteger(item.monthDay)||item.monthDay<1||item.monthDay>31) return '발행일을 1~31일로 설정해 주세요.';
  if (!/^([01]\d|2[0-3]):[0-5]\d$/.test(item.time)) return '발행 시간을 입력해 주세요.';
  if (!/^\d{4}-\d{2}-\d{2}$/.test(item.startDate)||!Number.isFinite(Date.parse(item.startDate)) || new Date(item.startDate).toISOString().slice(0,10)!==item.startDate) return '시작일을 입력해 주세요.';
  return '';
}
export function nextOccurrence(item, now = new Date()) {
  if(validateSchedule(item))return null;
  const first=[koreaDate(now),item.startDate].sort().at(-1);
  const date=new Date(`${first}T00:00:00Z`);
  for(let i=0;i<370;i++) {
    const monthLast=new Date(Date.UTC(date.getUTCFullYear(),date.getUTCMonth()+1,0)).getUTCDate();
    const matches=item.frequency==='daily'||(item.frequency==='weekly'&&item.weekdays.includes(date.getUTCDay()))||(item.frequency==='monthly'&&date.getUTCDate()===Math.min(item.monthDay,monthLast));
    const candidate=new Date(`${date.toISOString().slice(0,10)}T${item.time}:00+09:00`);
    if(matches&&candidate>now)return candidate;
    date.setUTCDate(date.getUTCDate()+1);
  }
  return null;
}
export function formatOccurrence(date) {
  return date ? new Intl.DateTimeFormat('ko-KR',{timeZone:'Asia/Seoul',month:'2-digit',day:'2-digit',weekday:'short',hour:'2-digit',minute:'2-digit',hour12:false}).format(date) : '—';
}
export function frequencyLabel(item) {
  if(item.frequency==='daily')return '매일';
  if(item.frequency==='monthly')return `매월 ${item.monthDay}일`;
  return `매주 ${[1,2,3,4,5,6,0].filter(day=>item.weekdays.includes(day)).map(day=>DAYS[day]).join('·')}`;
}
