export async function authRequest(path, options = {}) {
  const response = await fetch(`/api${path}`, {
    credentials: 'same-origin', ...options,
    headers: { 'Content-Type': 'application/json', 'X-WiaNews-Request': '1', ...options.headers },
  });
  const data = await response.json().catch(() => null);
  if (!response.ok) {
    if (response.status === 401 && path !== '/auth/login' && path !== '/auth/me') window.dispatchEvent(new Event('wianews-session-expired'));
    const message = typeof data?.detail === 'string' ? data.detail : Array.isArray(data?.detail) ? data.detail.map(e => e.msg.replace('Value error, ', '')).join(' / ') : '서버에 연결할 수 없습니다. 다시 시도해 주세요.';
    const error = new Error(message); error.status = response.status; throw error;
  }
  return data;
}
export const postAuth = (path, body = {}) => authRequest(path, { method: 'POST', body: JSON.stringify(body) });
