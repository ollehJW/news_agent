// Self-contained SVG keeps the newsletter logo available in exported HTML.
export const newsletterLogo = `<svg xmlns="http://www.w3.org/2000/svg" width="224" height="48" viewBox="0 0 224 48">
  <rect x="1" y="1" width="46" height="46" rx="13" fill="#ffffff" fill-opacity=".1" stroke="#a9c8ef" stroke-opacity=".4"/>
  <path d="m12 19 12-7 12 7-12 7-12-7Z" fill="#c6ddff"/>
  <path d="m12 25 12 7 12-7M12 31l12 7 12-7" fill="none" stroke="#c6ddff" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"/>
  <text x="60" y="34" fill="#ffffff" font-family="Arial,Helvetica,sans-serif" font-size="31" font-weight="700" letter-spacing="-.9">Wia<tspan fill="#c6ddff">News</tspan></text>
</svg>`;
export const newsletterLogoUrl = `data:image/svg+xml;charset=utf-8,${encodeURIComponent(newsletterLogo)}`;
