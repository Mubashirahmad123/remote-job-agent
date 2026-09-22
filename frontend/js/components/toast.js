/**
 * TOAST.JS — Toast Notification UI Component
 */

window.JobAgent = window.JobAgent || {};

JobAgent.toast = {
  show(message, type = 'success') {
    const existing = document.querySelector('.app-toast');
    if (existing) existing.remove();

    const toast = document.createElement('div');
    toast.className = 'app-toast';
    toast.style.cssText = `
      position: fixed;
      bottom: 24px;
      right: 24px;
      background: #1e293b;
      color: #fff;
      padding: 12px 20px;
      border-radius: var(--radius-md);
      border: 1px solid var(--border-active);
      box-shadow: 0 8px 24px rgba(0, 0, 0, 0.5);
      font-size: 13px;
      font-weight: 500;
      z-index: 200;
      animation: toastIn 200ms ease-out forwards;
      display: flex;
      align-items: center;
      gap: 10px;
    `;

    const icon = type === 'success' ? '✓' : '⚠';
    toast.innerHTML = `<span style="color: ${type === 'success' ? 'var(--accent-emerald)' : 'var(--accent-amber)'}; font-weight: bold;">${icon}</span> <span>${message}</span>`;
    document.body.appendChild(toast);

    setTimeout(() => {
      toast.style.opacity = '0';
      toast.style.transform = 'translateY(10px)';
      toast.style.transition = 'all 200ms ease';
      setTimeout(() => toast.remove(), 250);
    }, 3200);
  }
};
