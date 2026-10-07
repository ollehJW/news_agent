import { useEffect, useState } from 'react';
import { Loader2 } from 'lucide-react';
import { authRequest, postAuth } from './authApi';
import { serviceUrl } from './serviceUrl.js';
import './auth.css';
import AdminWorkspace from './AdminWorkspace';

export async function goToPlatformLogin({ completeProfile = false } = {}) {
  // The backend reads this origin from config.yaml, including direct legacy-port access.
  const response = await fetch(serviceUrl('/api/platform-auth'), { credentials: 'same-origin' });
  if (!response.ok) throw new Error('통합 로그인 설정을 확인할 수 없습니다.');
  const { platform_origin } = await response.json();
  const origin = new URL(platform_origin);
  const prefix = '/wianews';
  const path = window.location.pathname.startsWith(prefix + '/') ? window.location.pathname : prefix + window.location.pathname;
  const destination = path + window.location.search + window.location.hash;
  const params = new URLSearchParams({ next: destination });
  if (completeProfile) params.set('profile', 'complete');
  window.location.replace(origin.origin + '/login?' + params.toString());
}

export default function AuthGate({ children }) {
  const [user, setUser] = useState(null);
  const [notice, setNotice] = useState('');
  useEffect(() => {
    let active = true;
    async function redirect(completeProfile = false) { try { await goToPlatformLogin({completeProfile}); } catch (e) { if(active) setNotice(e.message); } }
    async function refresh() {
      try {
        const value = await authRequest('/auth/me');
        if (!active) return;
        if (value.must_change_password) { setUser(null); await redirect(); return; }
        if (!value.is_admin && value.missing_profile_fields?.length) { setUser(null); await redirect(true); return; }
        setUser(value); setNotice('');
      } catch (e) {
        if (!active) return;
        if (e.status === 401) { setUser(null); await redirect(); }
        else setNotice(e.message);
      }
    }
    function expired() { setUser(null); redirect(); }
    refresh(); window.addEventListener('wianews-session-expired', expired); window.addEventListener('focus', refresh);
    return () => { active=false; window.removeEventListener('wianews-session-expired', expired); window.removeEventListener('focus', refresh); };
  }, []);
  async function logout() {
    try { await postAuth('/auth/logout'); setUser(null); await goToPlatformLogin(); }
    catch (e) { setNotice(e.message); }
  }
  if (!user) return <div className="auth-page">{notice ? <p role="alert">{notice}</p> : <><Loader2 className="spin" size={32}/><span>통합 로그인 확인 중</span></>}</div>;
  return <>{notice && <div role="alert">{notice}</div>}{user.is_admin ? <AdminWorkspace user={user} onLogout={logout}/> : children(user, logout)}</>;
}
