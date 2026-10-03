"""Small explicit CMP selector list; reviewed 2026-10-03. No consent clicks."""

CMP_SELECTORS = [
    '#onetrust-banner-sdk', '#onetrust-consent-sdk', '.onetrust-pc-dark-filter',
    '#CybotCookiebotDialog', '#CybotCookiebotDialogBodyUnderlay', '#CookiebotWidget',
    '#didomi-host', '.didomi-popup-container', '.didomi-popup-backdrop',
    '.qc-cmp2-container', '#qc-cmp2-container', '#qc-cmp2-ui',
    '#truste-consent-track', '#truste-consent-content', '.truste_overlay', '.truste_box_overlay',
    '#usercentrics-root', '#usercentrics-cmp-ui', '[data-testid="uc-app-container"]',
    '.osano-cm-dialog', '.osano-cm-window__dialog', '.osano-cm-window__overlay',
    '.wt-cck--container',  # European Commission webtools cookie kit; verified in live QA
]

# Conservative heuristics: only fixed/sticky consent dialogs with consent text and controls.
# Never blanket-hide every element whose name happens to contain "cookie".
HIDE_BANNERS = r"""(selectors) => {
  const hidden = [];
  const hide = (el) => {
    if (!el || ['HTML','BODY','MAIN','ARTICLE'].includes(el.tagName)) return;
    const box = el.getBoundingClientRect();
    if (box.width > 0 && box.height > 0) hidden.push(el.id || el.className || el.tagName);
    el.style.setProperty('display', 'none', 'important');
  };
  for (const selector of selectors) for (const el of document.querySelectorAll(selector)) hide(el);
  for (const el of document.querySelectorAll('[id*="cookie" i],[id*="consent" i],[class*="cookie-banner" i]')) {
    const style = getComputedStyle(el), text = (el.innerText || '').slice(0,3000);
    if (!['fixed','sticky'].includes(style.position) && el.getAttribute('role') !== 'dialog') continue;
    if (!/(cookie|consent|privacy|datenschutz|einwilligung)/i.test(text)) continue;
    if (!/(accept|reject|agree|preferences|akzeptieren|ablehnen|zustimmen)/i.test(text)) continue;
    if (!el.querySelector('button,[role="button"],input[type="button"]')) continue;
    hide(el);
  }
  if (hidden.length) {
    document.documentElement.style.setProperty('overflow','auto','important');
    if (document.body) document.body.style.setProperty('overflow','auto','important');
  }
  return hidden.length;
}"""
