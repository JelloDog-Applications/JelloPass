const BASE = 'http://127.0.0.1:47984';

function setStatus(msg, isError) {
  const el = document.getElementById('status');
  el.textContent = msg;
  el.className = 'status ' + (isError ? 'error' : 'ok');
}

async function loadList() {
  const listEl = document.getElementById('list');
  listEl.innerHTML = '';
  setStatus('Loading…', false);
  try {
    const r = await fetch(BASE + '/list');
    if (!r.ok) throw new Error('JelloPass not running');
    const data = await r.json();
    const entries = data.entries || [];
    if (entries.length === 0) {
      listEl.innerHTML = '<li style="cursor:default;background:transparent;color:#9ca3af">No passwords saved.</li>';
      setStatus('', false);
      return;
    }
    entries.forEach(({ name, index }) => {
      const li = document.createElement('li');
      li.innerHTML = `
        <span class="name">${escapeHtml(name)}</span>
        <span class="btns">
          <button class="copy" data-index="${index}">Copy</button>
          <button class="fill" data-index="${index}">Fill</button>
        </span>
      `;
      li.querySelector('.copy').onclick = (e) => { e.stopPropagation(); copyPassword(index); };
      li.querySelector('.fill').onclick = (e) => { e.stopPropagation(); fillOnPage(index); };
      listEl.appendChild(li);
    });
    setStatus('', false);
  } catch (e) {
    listEl.innerHTML = '<li style="cursor:default;background:transparent;color:#f87171">Open JelloPass (GUI) first.</li>';
    setStatus('JelloPass app not running. Start it with: python main.py --gui', true);
  }
}

function escapeHtml(s) {
  const div = document.createElement('div');
  div.textContent = s;
  return div.innerHTML;
}

async function getPassword(index) {
  const r = await fetch(BASE + '/get?index=' + encodeURIComponent(index));
  if (!r.ok) throw new Error('Failed to get password');
  return await r.json();
}

async function copyPassword(index) {
  try {
    const { password } = await getPassword(index);
    await navigator.clipboard.writeText(password);
    setStatus('Copied to clipboard.', false);
  } catch (e) {
    setStatus('Error: ' + (e.message || 'failed'), true);
  }
}

async function fillOnPage(index) {
  try {
    const { name, password } = await getPassword(index);
    const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
    if (!tab || !tab.id) {
      setStatus('No active tab.', true);
      return;
    }
    chrome.tabs.sendMessage(tab.id, { action: 'fill', password, name });
    setStatus('Fill sent to page.', false);
  } catch (e) {
    setStatus('Error: ' + (e.message || 'failed'), true);
  }
}

loadList();
