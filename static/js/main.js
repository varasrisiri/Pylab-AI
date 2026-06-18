
// PyLab AI - Main JavaScript

// ── Theme System ──────────────────────────────────────────
const ThemeManager = {
  themes: ['dark', 'cyber', 'ocean', 'purple', 'light'],
  current: localStorage.getItem('pylab-theme') || 'dark',

  init() {
    document.documentElement.setAttribute('data-theme', this.current);
    this.updateButtons();
    document.querySelectorAll('.theme-btn').forEach(btn => {
      btn.addEventListener('click', () => this.set(btn.dataset.theme));
    });
  },

  set(theme) {
    this.current = theme;
    document.documentElement.setAttribute('data-theme', theme);
    localStorage.setItem('pylab-theme', theme);
    this.updateButtons();
    this.updateParticles();
  },

  updateButtons() {
    document.querySelectorAll('.theme-btn').forEach(btn => {
      btn.classList.toggle('active', btn.dataset.theme === this.current);
    });
  },

  updateParticles() {
    const colors = {
      dark: ['rgba(0,212,255,0.6)', 'rgba(0,255,136,0.4)'],
      cyber: ['rgba(0,255,65,0.7)', 'rgba(57,255,20,0.5)'],
      ocean: ['rgba(76,201,240,0.6)', 'rgba(114,9,183,0.4)'],
      purple: ['rgba(191,95,255,0.6)', 'rgba(255,107,255,0.4)'],
      light: ['rgba(0,102,204,0.3)', 'rgba(0,170,85,0.2)']
    };
    ParticleSystem.colors = colors[this.current] || colors.dark;
    ParticleSystem.restart();
  }
};

// ── Particle System ───────────────────────────────────────
const ParticleSystem = {
  colors: ['rgba(0,212,255,0.6)', 'rgba(0,255,136,0.4)'],
  particles: [],
  container: null,
  interval: null,

  init() {
    this.container = document.getElementById('bgParticles');
    if (!this.container) return;
    this.start();
  },

  createParticle() {
    const p = document.createElement('div');
    p.className = 'particle';
    const size = Math.random() * 4 + 2;
    const color = this.colors[Math.floor(Math.random() * this.colors.length)];
    const left = Math.random() * 100;
    const duration = Math.random() * 15 + 10;
    const delay = Math.random() * 5;
    p.style.cssText = `width:${size}px;height:${size}px;left:${left}%;background:${color};animation-duration:${duration}s;animation-delay:${delay}s;box-shadow:0 0 ${size*2}px ${color};`;
    this.container.appendChild(p);
    setTimeout(() => p.remove(), (duration + delay) * 1000);
  },

  start() {
    this.interval = setInterval(() => this.createParticle(), 600);
    for (let i = 0; i < 15; i++) this.createParticle();
  },

  restart() {
    clearInterval(this.interval);
    if (this.container) this.container.innerHTML = '';
    this.start();
  }
};

// ── Navbar ────────────────────────────────────────────────
function initNavbar() {
  const hamburger = document.getElementById('hamburger');
  const navLinks = document.getElementById('navLinks');
  if (hamburger && navLinks) {
    hamburger.addEventListener('click', () => navLinks.classList.toggle('open'));
    document.addEventListener('click', e => {
      if (!hamburger.contains(e.target) && !navLinks.contains(e.target)) {
        navLinks.classList.remove('open');
      }
    });
  }
}

// ── Code Copy ─────────────────────────────────────────────
function initCodeCopy() {
  document.querySelectorAll('.code-copy').forEach(btn => {
    btn.addEventListener('click', () => {
      const code = btn.closest('.code-block').querySelector('code');
      if (code) {
        navigator.clipboard.writeText(code.textContent).then(() => {
          btn.textContent = '✓ Copied!';
          setTimeout(() => btn.textContent = 'Copy', 2000);
        });
      }
    });
  });
}

// ── Tabs ──────────────────────────────────────────────────
function initTabs() {
  document.querySelectorAll('.tab').forEach(tab => {
    tab.addEventListener('click', () => {
      const group = tab.closest('.tabs').dataset.group;
      document.querySelectorAll(`.tab[data-group="${group}"]`).forEach(t => t.classList.remove('active'));
      document.querySelectorAll(`.tab-content[data-group="${group}"]`).forEach(c => c.classList.remove('active'));
      tab.classList.add('active');
      const target = document.getElementById(tab.dataset.target);
      if (target) target.classList.add('active');
    });
  });
}

// ── Problem Cards ─────────────────────────────────────────
function initProblems() {
  document.querySelectorAll('.problem-card').forEach(card => {
    card.addEventListener('click', () => {
      const detail = card.querySelector('.problem-detail');
      if (detail) detail.classList.toggle('open');
    });
  });
}

// ── Bookmark ──────────────────────────────────────────────
function bookmark(questionId, questionText) {
  fetch('/api/bookmark', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({question_id: questionId, question_text: questionText})
  }).then(r => r.json()).then(d => {
    showToast('Bookmarked! 🔖');
  });
}

// ── Toast ─────────────────────────────────────────────────
function showToast(msg, type = 'success') {
  const toast = document.createElement('div');
  toast.style.cssText = `position:fixed;bottom:2rem;right:2rem;background:var(--bg-card);border:1px solid var(--border-color);color:var(--text-primary);padding:0.75rem 1.5rem;border-radius:10px;z-index:9999;font-size:0.9rem;box-shadow:var(--shadow-card);animation:slideIn 0.3s ease;`;
  toast.textContent = msg;
  document.body.appendChild(toast);
  setTimeout(() => toast.remove(), 3000);
}

// ── Highlight.js ──────────────────────────────────────────
function initHighlight() {
  if (typeof hljs !== 'undefined') {
    document.querySelectorAll('pre code').forEach(el => hljs.highlightElement(el));
  }
}

// ── Scroll Animations ─────────────────────────────────────
function initScrollAnimations() {
  const observer = new IntersectionObserver(entries => {
    entries.forEach(e => {
      if (e.isIntersecting) {
        e.target.style.opacity = '1';
        e.target.style.transform = 'translateY(0)';
      }
    });
  }, {threshold: 0.1});

  document.querySelectorAll('.card, .feature-card, .problem-card, .lib-card, .game-card').forEach(el => {
    el.style.opacity = '0';
    el.style.transform = 'translateY(20px)';
    el.style.transition = 'opacity 0.5s ease, transform 0.5s ease';
    observer.observe(el);
  });
}

// ── Counter Animation ─────────────────────────────────────
function animateCounters() {
  document.querySelectorAll('.stat-num[data-target]').forEach(el => {
    const target = parseInt(el.dataset.target);
    let current = 0;
    const step = target / 60;
    const timer = setInterval(() => {
      current += step;
      if (current >= target) { current = target; clearInterval(timer); }
      el.textContent = Math.floor(current) + (el.dataset.suffix || '');
    }, 16);
  });
}

// ── Init ──────────────────────────────────────────────────
document.addEventListener('DOMContentLoaded', () => {
  // Always run dynamic session navbar first to guarantee it is set up
  initUserSessionNavbar();

  // Highlight active navbar link dynamically
  try { highlightActiveNavLink(); } catch (e) { console.error("HighlightActiveNavLink error:", e); }

  // Initialize other components safely to avoid cascading errors
  try { ThemeManager.init(); } catch (e) { console.error("ThemeManager error:", e); }
  try { ParticleSystem.init(); } catch (e) { console.error("ParticleSystem error:", e); }
  try { initNavbar(); } catch (e) { console.error("Navbar error:", e); }
  try { initCodeCopy(); } catch (e) { console.error("CodeCopy error:", e); }
  try { initTabs(); } catch (e) { console.error("Tabs error:", e); }
  try { initProblems(); } catch (e) { console.error("Problems error:", e); }
  try { initHighlight(); } catch (e) { console.error("Highlight error:", e); }
  setTimeout(() => {
    try { initScrollAnimations(); } catch (e) { console.error("ScrollAnimations error:", e); }
  }, 100);
  setTimeout(() => {
    try { animateCounters(); } catch (e) { console.error("Counters error:", e); }
  }, 500);
});

// ── Dynamic User Navbar Session Integration ──
async function initUserSessionNavbar() {
  try {
    const res = await fetch('/api/user/session');
    const data = await res.json();
    
    const navActions = document.querySelector('.nav-actions');
    if (!navActions) return;
    
    // Avoid double render if elements exist statically (like base.html pages)
    if (document.getElementById('userMenu') || document.querySelector('.nav-login-btn')) {
      return; 
    }
    
    const hamburger = document.getElementById('hamburger');
    
    if (data.logged_in) {
      const username = data.user_id;
      const isGuest = username === 'guest';
      const isAdmin = username === 'admin';
      const avatarChar = isGuest ? '👤' : username[0].toUpperCase();
      const roleName = isGuest ? 'Guest Explorer' : (isAdmin ? 'Administrator' : 'Python Learner');
      
      const userMenuHtml = `
        <div class="user-menu" id="userMenu">
            <button class="user-avatar-btn" id="userAvatarBtn" title="${username}">
                <span class="avatar-circle">${avatarChar}</span>
                <span class="avatar-name">${username}</span>
                <span style="font-size:.7rem;opacity:.6;">▼</span>
            </button>
            <div class="user-dropdown" id="userDropdown">
                <div class="user-dropdown-header">
                    <div class="ud-avatar">${avatarChar}</div>
                    <div>
                        <div style="font-weight:700;color:var(--text-heading);">${username}</div>
                        <div style="font-size:.75rem;color:var(--text-muted);">${roleName}</div>
                    </div>
                </div>
                <div class="user-dropdown-divider"></div>
                ${isAdmin ? '<a href="/admin/dashboard" class="ud-item" style="color:var(--accent-primary); font-weight: 700;">⚙️ Admin Dashboard</a>' : ''}
                ${!isGuest ? `
                  <a href="/profile" class="ud-item">👤 My Profile</a>
                  <a href="/dashboard" class="ud-item">📊 Dashboard</a>
                  <a href="/streak" class="ud-item">🔥 My Streak</a>
                ` : `
                  <a href="/login" class="ud-item">🔑 Login / Register</a>
                `}
                <div class="user-dropdown-divider"></div>
                <a href="/logout" class="ud-item ud-logout">🚪 Logout</a>
            </div>
        </div>
      `;
      
      const tempDiv = document.createElement('div');
      tempDiv.innerHTML = userMenuHtml;
      const userMenuNode = tempDiv.firstElementChild;
      
      if (hamburger) {
        navActions.insertBefore(userMenuNode, hamburger);
      } else {
        navActions.appendChild(userMenuNode);
      }
      
      // Bind toggle click events using the 'open' class matching base.html styles
      const btn = userMenuNode.querySelector('#userAvatarBtn');
      const dropdown = userMenuNode.querySelector('#userDropdown');
      if (btn && dropdown) {
        btn.addEventListener('click', (e) => {
          e.stopPropagation();
          dropdown.classList.toggle('open');
        });
        
        document.addEventListener('click', (e) => {
          if (!userMenuNode.contains(e.target)) {
            dropdown.classList.remove('open');
          }
        });
      }
      
    } else {
      // Show login button
      const loginBtn = document.createElement('a');
      loginBtn.href = '/login';
      loginBtn.className = 'nav-login-btn';
      loginBtn.innerHTML = '🔑 Login';
      
      if (hamburger) {
        navActions.insertBefore(loginBtn, hamburger);
      } else {
        navActions.appendChild(loginBtn);
      }
    }
  } catch(e) {
    console.error("Error setting up dynamic session navbar:", e);
  }
}

// ── Highlight Active Navbar Link ──
function highlightActiveNavLink() {
  const currentPath = window.location.pathname;
  document.querySelectorAll('.nav-links .nav-link').forEach(link => {
    const href = link.getAttribute('href');
    if (href === currentPath || (href !== '/' && currentPath.startsWith(href))) {
      link.classList.add('active');
    } else {
      link.classList.remove('active');
    }
  });
}
