(() => {
  const user = window.ERP_USER;
  const admin = user.role === 'admin';
  const bar = document.createElement('div');
  bar.style.cssText = 'position:sticky;top:0;z-index:1000;background:#40291c;color:#fff;padding:10px 20px;display:flex;gap:18px;align-items:center;flex-wrap:wrap;font:14px system-ui';
  const label = document.createElement('strong');
  label.textContent = user.username + (admin ? ' · Admin' : ' · Manager · Demo data · View only');
  bar.append(label);

  const addLink = (title, href) => {
    const link = document.createElement('a');
    link.href = href;
    link.textContent = title;
    link.style.color = '#fff';
    bar.append(link);
  };
  if (admin) {
    addLink('Manage logins', '/erp/accounts');
    addLink('Edit / delete records', '/erp/records#records');
    addLink('Action history', '/erp/records#history');
  }
  addLink(admin ? 'Download Catalog (PDF)' : 'Download Sample Catalogue (PDF)', '/api/erp/catalogue.pdf');

  const logout = document.createElement('button');
  logout.textContent = 'Log out';
  logout.onclick = async () => {
    await fetch('/api/auth/logout', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: '{}' });
    location.href = '/erp/login';
  };
  bar.append(logout);
  document.body.prepend(bar);
})();
