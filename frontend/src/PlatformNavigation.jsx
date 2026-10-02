import { useEffect, useState } from 'react';
import { ArrowLeft } from 'lucide-react';
import { serviceUrl } from './serviceUrl.js';
import './platformNavigation.css';

let destination;
function usePlatformHome() {
  const [href, setHref] = useState(() => `${window.location.protocol}//${window.location.hostname}/`);
  useEffect(() => {
    let active = true;
    destination ??= fetch(serviceUrl('/api/platform-auth'))
      .then(response => { if (!response.ok) throw new Error('Platform configuration unavailable'); return response.json(); })
      .then(config => { const url = new URL(config.platform_origin); if (!['http:', 'https:'].includes(url.protocol)) throw new Error('Invalid platform origin'); return url.origin + '/'; })
      .catch(() => null);
    destination.then(url => { if (active && url) setHref(url); });
    return () => { active = false; };
  }, []);
  return href;
}

export function PlatformReturnLink() {
  return <a className="platform-return-link" href={usePlatformHome()}><ArrowLeft size={15} aria-hidden="true"/><span>AX for Works로 돌아가기</span></a>;
}
export function PlatformHomeLink() {
  return <a className="platform-crumb-link" href={usePlatformHome()}>AX for Works</a>;
}
