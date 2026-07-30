// Kobo 555送111 湊單清單 — 跨頁共用（index.html / exclusive.html / 555.html）
const LS_CART555 = 'kobo99_555cart';

function cart555Load() {
  try { const r = localStorage.getItem(LS_CART555); return r ? JSON.parse(r) : []; }
  catch (e) { return []; }
}
function cart555Save(cart) {
  try { localStorage.setItem(LS_CART555, JSON.stringify(cart)); } catch (e) {}
}
function cart555ItemPrice(item) {
  return item.isGroup ? (item.total || 0) : (item.price || 0);
}
function cart555Summary() {
  const cart = cart555Load();
  const total = cart.reduce((s, p) => s + cart555ItemPrice(p), 0);
  const count = cart.reduce((s, p) => s + (p.isGroup ? p.members.length : 1), 0);
  return { total, count };
}
// 是否已在清單中（含被併入「組合」裡的情況）
function cart555Has(catId) {
  if (!catId) return false;
  return cart555Load().some(p => p.isGroup ? p.members.some(m => m.catId === catId) : p.catId === catId);
}
// 是否被併入某個「組合」（併組後交由 555.html 管理，書單頁不重複處理）
function cart555InGroup(catId) {
  if (!catId) return false;
  return cart555Load().some(p => p.isGroup && p.members.some(m => m.catId === catId));
}
// entry: {catId, title, price, koboUrl} — 回傳加入後是否為「已在清單中」
function cart555Toggle(entry) {
  let cart = cart555Load();
  // catId 缺失（書無 ISBN 也無網址）時不比對既有項目，避免誤判成同一本而刪錯
  const idx = entry.catId ? cart.findIndex(p => !p.isGroup && p.catId === entry.catId) : -1;
  let added;
  if (idx >= 0) { cart.splice(idx, 1); added = false; }
  else {
    // uid 用整數（555.html 的勾選/分組邏輯用 parseInt 比對，帶小數會截斷造成比對失敗）
    cart.push({ uid: Date.now() + Math.floor(Math.random() * 1000), catId: entry.catId, title: entry.title, price: entry.price || 0, koboUrl: entry.koboUrl || null });
    added = true;
  }
  cart555Save(cart);
  cart555RenderBadge();
  return added;
}

function cart555RenderBadge() {
  // 555.html 本身已有完整清單畫面，不需要再疊一個導去自己的浮動按鈕
  if (/(^|\/)555\.html$/.test(location.pathname)) return;
  let btn = document.getElementById('cart555FloatBtn');
  if (!btn) {
    if (!document.getElementById('cart555Style')) {
      const s = document.createElement('style');
      s.id = 'cart555Style';
      s.textContent = '.cart555-float{position:fixed;right:1.1rem;bottom:1.1rem;background:#1C1917;color:#FAF7F2;border:none;border-radius:30px;padding:.7rem 1.1rem;font-size:.82rem;font-weight:700;display:none;align-items:center;gap:.5rem;box-shadow:0 6px 20px rgba(0,0,0,.25);cursor:pointer;z-index:60;text-decoration:none;transition:transform .15s}.cart555-float:hover{transform:translateY(-2px)}.cart555-float .c5-amt{color:#F97316}@media(max-width:640px){.cart555-float{right:.75rem;bottom:.75rem;font-size:.78rem;padding:.6rem .95rem}}';
      document.head.appendChild(s);
    }
    btn = document.createElement('a');
    btn.id = 'cart555FloatBtn';
    btn.className = 'cart555-float';
    btn.href = '555.html';
    document.body.appendChild(btn);
  }
  const { total, count } = cart555Summary();
  if (count === 0) { btn.style.display = 'none'; return; }
  btn.style.display = 'inline-flex';
  btn.innerHTML = '🧮 已選 ' + count + ' 本 <span class="c5-amt">$' + total + '</span> →';
}

function toggleCart555(btn) {
  const catId = btn.dataset.isbn;
  // 已被併入組合：交由 555.html 管理，這裡不重複加/刪，避免總額被重複計算
  if (cart555InGroup(catId)) {
    location.href = '555.html';
    return;
  }
  const entry = {
    catId,
    title: btn.dataset.title,
    price: parseInt(btn.dataset.price, 10) || 0,
    koboUrl: btn.dataset.url || null,
  };
  const added = cart555Toggle(entry);
  btn.classList.toggle('active', added);
  btn.textContent = '🧮 ' + (added ? '已加入' : '湊555');
}

document.addEventListener('DOMContentLoaded', cart555RenderBadge);
