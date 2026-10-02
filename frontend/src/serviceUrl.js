// Support both the portal subpath and the original standalone service URL.
export function serviceUrl(path, pathname = globalThis.location?.pathname || '/') {
  if (!path || !path.startsWith('/') || path.startsWith('//')) return path;
  const prefix = pathname === '/wianews' || pathname.startsWith('/wianews/') ? '/wianews' : '';
  return prefix + path;
}
