// Fill login fields when JelloPass extension sends a password
chrome.runtime.onMessage.addListener((msg, sender, sendResponse) => {
  if (msg.action !== 'fill') return;
  const password = msg.password;
  const name = msg.name || '';

  const inputs = document.querySelectorAll('input[type="password"]');
  const visible = Array.from(inputs).filter(el => {
    const style = window.getComputedStyle(el);
    return style.display !== 'none' && style.visibility !== 'hidden' && el.offsetParent !== null;
  });

  if (visible.length === 0) {
    sendResponse({ ok: false, error: 'No password field found' });
    return;
  }

  const pwdField = visible[0];
  pwdField.focus();
  pwdField.value = password;
  pwdField.dispatchEvent(new Event('input', { bubbles: true }));
  pwdField.dispatchEvent(new Event('change', { bubbles: true }));

  // Optionally fill the last visible text/email field before this (username)
  const all = document.querySelectorAll('input[type="text"], input[type="email"], input:not([type])');
  let prev = null;
  for (const el of all) {
    if (el === pwdField) break;
    const style = window.getComputedStyle(el);
    if (style.display !== 'none' && style.visibility !== 'hidden' && el.offsetParent !== null) {
      prev = el;
    }
  }
  if (prev && name) {
    prev.value = name;
    prev.dispatchEvent(new Event('input', { bubbles: true }));
    prev.dispatchEvent(new Event('change', { bubbles: true }));
  }

  sendResponse({ ok: true });
});
