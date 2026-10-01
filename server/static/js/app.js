/**
 * GAME-ROOM's Backlog Tracker - Client Application (v3.0)
 * Features StopGame 4-Tier SVG Ratings, Collapsible Sidebar, Streamlined RAWG 1-Click Tool,
 * Russian Genre Chips & Presets, GigaChat AI, Full-Bundle Cloud Sync,
 * Backlog Randomizer Wheel, YouTube Video/Gameplay Player, RAWG Auto-Enricher, and PWA Support.
 */

// Global 401 interceptor: redirect to /login if session expires or is missing
(function() {
  const _origFetch = window.fetch;
  window.fetch = async function(...args) {
    const res = await _origFetch.apply(this, args);
    if (res.status === 401) {
      const url = typeof args[0] === 'string' ? args[0] : (args[0]?.url || '');
      if (!url.includes('/api/auth/login')) {
        window.location.replace('/login');
      }
    }
    return res;
  };
})();

const app = {
  games: [],
  currentTab: 'playing',
  stats: {},
  settings: {},
  chatHistory: [],
  selectedModalGrade: '',
  selectedCompleteGrade: 'izumitelno',
  selectedGenres: [],

  // YouTube Trailer State
  currentTrailerGame: null,
  currentTrailerMode: 'trailer',
  currentTrailerVideoList: [],

  // Backlog Randomizer Wheel State
  wheelCandidates: [],
  wheelExcludedIds: new Set(),
  wheelAngle: 0,
  wheelIsSpinning: false,
  wheelWinner: null,
  wheelSoundEnabled: true,
  audioCtx: null,

  // Dialog & Toast System
  _dialogResolver: null,
  isEnriching: false,
  deferredPwaPrompt: null,

  AVAILABLE_GENRES: [
    "Экшен", "Приключения", "Сюжетная", "Ролевая игра (RPG)", "Шутер", "Хоррор",
    "Психологический хоррор", "Стелс", "Выживание", "Открытый мир", "Платформер",
    "Головоломка", "Инди", "Sci-Fi", "Киберпанк", "Фэнтези", "Слэшер",
    "Интерактивное кино", "VR", "Гонки", "Файтинг", "Стратегия", "Симулятор",
    "Метроидвания", "Рогалик", "Соулслайк", "Детектив"
  ],

  GENRE_PRESETS: {
    story_action: ["Экшен", "Приключения", "Сюжетная"],
    horror_survival: ["Хоррор", "Выживание", "Стелс"],
    open_rpg: ["Ролевая игра (RPG)", "Открытый мир", "Приключения"],
    scifi_cyber: ["Sci-Fi", "Киберпанк", "Экшен"],
    indie_puzzle: ["Инди", "Платформер", "Головоломка"],
    slasher_souls: ["Экшен", "Слэшер", "Соулслайк"],
    clear: []
  },

  async init() {
    // Verify session status before rendering
    try {
      const authRes = await fetch('/api/auth/me');
      if (!authRes.ok) {
        window.location.replace('/login');
        return;
      }
    } catch (e) {
      window.location.replace('/login');
      return;
    }

    this.initPwa();
    this.bindEvents();
    this.renderGenreChips();
    
    try {
      this.wheelSoundEnabled = localStorage.getItem('gameroom_wheel_sound') !== 'false';
    } catch (e) {
      this.wheelSoundEnabled = true;
    }
    
    this.loadSettings();
    this.loadChatHistory();
    this.refreshAllData();
    
    // Set network label
    const host = window.location.hostname || 'localhost';
    const port = window.location.port || '8080';
    const label = document.getElementById('network-host-label');
    if (label) label.textContent = `${host}:${port} // ONLINE`;
  },

  // --- PWA INSTALLATION & SERVICE WORKER ---
  initPwa() {
    if ('serviceWorker' in navigator) {
      window.addEventListener('load', () => {
        navigator.serviceWorker.register('/sw.js').catch(e => console.log('SW registration error:', e));
      });
    }

    window.addEventListener('beforeinstallprompt', e => {
      e.preventDefault();
      this.deferredPwaPrompt = e;
      const installWrap = document.getElementById('sidebar-install-wrap');
      if (installWrap) installWrap.style.display = 'block';
    });

    const isStandalone = (window.matchMedia && window.matchMedia('(display-mode: standalone)').matches) || (typeof navigator !== 'undefined' && navigator.standalone === true);
    if (isStandalone) {
      const installWrap = document.getElementById('sidebar-install-wrap');
      if (installWrap) installWrap.style.display = 'none';
    }
  },

  async installPwa() {
    if (this.deferredPwaPrompt) {
      this.deferredPwaPrompt.prompt();
      const choice = await this.deferredPwaPrompt.userChoice;
      if (choice && choice.outcome === 'accepted') {
        this.showToast('Приложение успешно установлено на ваше устройство!', 'success');
      }
      this.deferredPwaPrompt = null;
      const installWrap = document.getElementById('sidebar-install-wrap');
      if (installWrap) installWrap.style.display = 'none';
    } else {
      const isIos = /iPad|iPhone|iPod/.test(navigator.userAgent) && !window.MSStream;
      if (isIos) {
        this.showAlert(
          'Чтобы установить приложение на iPhone / iPad:<br><br>1. Нажмите кнопку <strong>«Поделиться»</strong> (значок 📤 внизу Safari).<br>2. Выберите <strong>«На экран Домой» (➕)</strong>.',
          'УСТАНОВКА НА IOS',
          'info'
        );
      } else {
        this.showAlert(
          'Чтобы установить приложение:<br><br>1. Откройте меню браузера (три точки <strong>⋮</strong> в правом верхнем углу).<br>2. Нажмите <strong>«Установить приложение»</strong> или <strong>«Добавить на главный экран»</strong>.',
          'УСТАНОВКА ПРИЛОЖЕНИЯ',
          'info'
        );
      }
    }
  },

  bindEvents() {
    // Tab switching
    document.querySelectorAll('.sidebar-nav .nav-item').forEach(item => {
      item.addEventListener('click', () => {
        const tab = item.getAttribute('data-tab');
        if (tab) this.switchTab(tab);
      });
    });

    // Sliding Sidebar Toggles (Desktop & Mobile)
    const menuBtn = document.getElementById('menu-toggle-btn');
    const closeBtn = document.getElementById('sidebar-close-btn');
    const sidebar = document.getElementById('sidebar');

    if (menuBtn && sidebar) {
      menuBtn.addEventListener('click', () => {
        if (window.innerWidth <= 900) {
          sidebar.classList.toggle('open');
        } else {
          sidebar.classList.toggle('collapsed');
        }
      });
    }

    if (closeBtn && sidebar) {
      closeBtn.addEventListener('click', () => {
        if (window.innerWidth <= 900) {
          sidebar.classList.remove('open');
        } else {
          sidebar.classList.add('collapsed');
        }
      });
    }

    // Top action buttons
    const btnQuickRawg = document.getElementById('btn-quick-rawg');
    if (btnQuickRawg) {
      btnQuickRawg.addEventListener('click', () => this.switchTab('rawg-search'));
    }

    const btnAddGame = document.getElementById('btn-add-custom-game');
    if (btnAddGame) {
      btnAddGame.addEventListener('click', () => this.openGameModal());
    }

    // Backlog live filter triggers
    ['backlog-search', 'backlog-platform-filter', 'backlog-genre-filter', 'backlog-priority-filter', 'backlog-sort'].forEach(id => {
      const el = document.getElementById(id);
      if (el) {
        el.addEventListener('input', () => this.filterAndRenderBacklog());
        el.addEventListener('change', () => this.filterAndRenderBacklog());
      }
    });

    // Wishlist filters
    ['wishlist-search', 'wishlist-platform-filter'].forEach(id => {
      const el = document.getElementById(id);
      if (el) {
        el.addEventListener('input', () => this.filterAndRenderWishlist());
        el.addEventListener('change', () => this.filterAndRenderWishlist());
      }
    });

    // Completed filters
    ['completed-search', 'completed-grade-filter', 'completed-sort'].forEach(id => {
      const el = document.getElementById(id);
      if (el) {
        el.addEventListener('input', () => this.filterAndRenderCompleted());
        el.addEventListener('change', () => this.filterAndRenderCompleted());
      }
    });

    // RAWG search input on enter
    const rawgInput = document.getElementById('rawg-page-search');
    const rawgBtn = document.getElementById('btn-do-rawg-search');
    if (rawgInput) {
      rawgInput.addEventListener('keypress', (e) => {
        if (e.key === 'Enter') {
          e.preventDefault();
          this.performRawgSearch(rawgInput.value);
        }
      });
    }
    if (rawgBtn && rawgInput) {
      rawgBtn.addEventListener('click', () => this.performRawgSearch(rawgInput.value));
    }

    // GigaChat send input
    const aiInput = document.getElementById('ai-user-input');
    const aiBtn = document.getElementById('btn-send-ai');
    if (aiInput) {
      aiInput.addEventListener('keypress', (e) => {
        if (e.key === 'Enter') {
          e.preventDefault();
          this.sendAiMessage();
        }
      });
    }
    if (aiBtn) {
      aiBtn.addEventListener('click', () => this.sendAiMessage());
    }

    // AI suggestions chips
    document.querySelectorAll('.suggestion-chip').forEach(chip => {
      chip.addEventListener('click', () => {
        const prompt = chip.getAttribute('data-prompt');
        const action = chip.getAttribute('data-action') || 'chat';
        if (prompt) this.sendAiMessage(prompt, action);
      });
    });

    const gamerPortraitBtn = document.getElementById('btn-ai-gamer-portrait');
    if (gamerPortraitBtn) {
      gamerPortraitBtn.addEventListener('click', () => {
        this.sendAiMessage("Построй подробный психологический портрет меня как геймера на основе пройденного и оценок 'Изумительно'.", "portrait");
      });
    }

    const clearAiBtn = document.getElementById('btn-clear-ai-history');
    if (clearAiBtn) {
      clearAiBtn.addEventListener('click', async () => {
        const confirmed = await this.showConfirm({
          title: 'ОЧИСТКА ЧАТА',
          message: 'Очистить историю диалогов со Штурманом?',
          confirmText: 'Да, очистить',
          type: 'warning'
        });
        if (confirmed) {
          await fetch('/api/ai/history', { method: 'DELETE' });
          this.chatHistory = [];
          this.renderChatMessages();
          this.showToast('История чата очищена', 'info');
        }
      });
    }

    // Yandex buttons
    const btnYandexBackup = document.getElementById('btn-yandex-backup-now');
    if (btnYandexBackup) {
      btnYandexBackup.addEventListener('click', () => this.triggerYandexBackup());
    }

    const btnYandexRefresh = document.getElementById('btn-yandex-refresh-list');
    if (btnYandexRefresh) {
      btnYandexRefresh.addEventListener('click', () => this.loadYandexBackups());
    }

    // Full Bundle Import trigger
    const btnTriggerImport = document.getElementById('btn-trigger-import');
    const fileInput = document.getElementById('json-file-input');
    if (btnTriggerImport && fileInput) {
      btnTriggerImport.addEventListener('click', () => fileInput.click());
      fileInput.addEventListener('change', (e) => this.handleFullBundleImport(e));
    }

    // Forms
    const gameForm = document.getElementById('game-form');
    if (gameForm) {
      gameForm.addEventListener('submit', (e) => {
        e.preventDefault();
        this.saveGameForm();
      });
    }

    const quickTimeForm = document.getElementById('quick-time-form');
    if (quickTimeForm) {
      quickTimeForm.addEventListener('submit', (e) => {
        e.preventDefault();
        this.saveQuickTime();
      });
    }

    const completeForm = document.getElementById('complete-form');
    if (completeForm) {
      completeForm.addEventListener('submit', (e) => {
        e.preventDefault();
        this.saveCompleteForm();
      });
    }

    const settingsForm = document.getElementById('settings-form');
    if (settingsForm) {
      settingsForm.addEventListener('submit', (e) => {
        e.preventDefault();
        this.saveSettings();
      });
    }
  },

  // --- RUSSIAN GENRE CHIPS & PRESETS ---
  renderGenreChips() {
    const container = document.getElementById('genre-chips-container');
    if (!container) return;

    container.innerHTML = this.AVAILABLE_GENRES.map(g => {
      const slug = this.slugify(g);
      return `<button type="button" class="genre-chip" id="genre-chip-${slug}" onclick="app.toggleGenreChip('${g}')">${g}</button>`;
    }).join('');
  },

  toggleGenreChip(genre) {
    if (this.selectedGenres.includes(genre)) {
      this.selectedGenres = this.selectedGenres.filter(item => item !== genre);
    } else {
      this.selectedGenres.push(genre);
    }
    this.updateGenreUi();
  },

  applyGenrePreset(presetKey) {
    const preset = this.GENRE_PRESETS[presetKey] || [];
    this.selectedGenres = [...preset];
    this.updateGenreUi();
  },

  setModalGenres(genresString) {
    if (!genresString || !genresString.trim()) {
      this.selectedGenres = [];
    } else {
      this.selectedGenres = genresString.split(',').map(s => s.trim()).filter(Boolean);
    }
    this.updateGenreUi();
  },

  updateGenreUi() {
    const summary = document.getElementById('genre-selected-summary');
    const hiddenInput = document.getElementById('form-genres');

    const genresStr = this.selectedGenres.join(', ');
    if (hiddenInput) hiddenInput.value = genresStr;

    if (summary) {
      summary.innerHTML = this.selectedGenres.length > 0
        ? `Выбрано: <strong>${this.escapeHtml(genresStr)}</strong>`
        : `Выбрано: <em>не выбрано</em>`;
    }

    this.AVAILABLE_GENRES.forEach(g => {
      const chip = document.getElementById(`genre-chip-${this.slugify(g)}`);
      if (chip) {
        if (this.selectedGenres.includes(g)) {
          chip.classList.add('active');
        } else {
          chip.classList.remove('active');
        }
      }
    });
  },

  slugify(text) {
    return encodeURIComponent(text).replace(/%/g, '_');
  },

  // --- TAB NAVIGATION ---
  switchTab(tabName) {
    this.currentTab = tabName;

    document.querySelectorAll('.sidebar-nav .nav-item').forEach(item => {
      if (item.getAttribute('data-tab') === tabName) {
        item.classList.add('active');
      } else {
        item.classList.remove('active');
      }
    });

    document.querySelectorAll('.tab-pane').forEach(pane => {
      pane.classList.remove('active');
    });
    const targetPane = document.getElementById(`tab-${tabName}`);
    if (targetPane) targetPane.classList.add('active');

    const titles = {
      'playing': '⚡ В ПРОЦЕССЕ (NOW PLAYING)',
      'backlog': '📚 БЭКЛОГ ИГР (BACKLOG)',
      'wishlist': '⭐ ВИШЛИСТ (WISHLIST)',
      'completed': '🏆 ПРОЙДЕННЫЕ (HALL OF FAME)',
      'paused': '⏸️ ПАУЗА / ДРОПНУТО',
      'rawg-search': '🔍 RAWG.IO ИНСТРУМЕНТ ДОБАВЛЕНИЯ',
      'ai-assistant': '🤖 GIGACHAT AI ШТУРМАН',
      'cloud-sync': '☁️ ОБЛАКО, БЭКАП & ИМПОРТ',
      'stats': '📊 АНАЛИТИКА & ОЦЕНКИ',
      'settings': '⚙️ НАСТРОЙКИ API & СИСТЕМЫ'
    };
    const titleEl = document.getElementById('view-title');
    if (titleEl) titleEl.textContent = titles[tabName] || "GAME-ROOM's";

    // Auto-close sidebar on mobile
    if (window.innerWidth <= 900) {
      const sidebar = document.getElementById('sidebar');
      if (sidebar) sidebar.classList.remove('open');
    }

    if (tabName === 'playing') this.renderPlayingView();
    if (tabName === 'backlog') this.filterAndRenderBacklog();
    if (tabName === 'wishlist') this.filterAndRenderWishlist();
    if (tabName === 'completed') this.filterAndRenderCompleted();
    if (tabName === 'paused') this.renderPausedView();
    if (tabName === 'cloud-sync') this.loadYandexStatusAndBackups();
    if (tabName === 'stats') this.renderStatsView();
    if (tabName === 'ai-assistant') this.renderChatMessages();
  },

  // --- DATA FETCHING ---
  async refreshAllData() {
    try {
      const res = await fetch('/api/games');
      const data = await res.json();
      this.games = data.games || [];

      const statsRes = await fetch('/api/stats');
      this.stats = await statsRes.json();

      this.updateBadges();
      this.switchTab(this.currentTab);
    } catch (e) {
      console.error('Error fetching games:', e);
    }
  },

  updateBadges() {
    const counts = {
      playing: this.games.filter(g => g.status === 'playing').length,
      backlog: this.games.filter(g => g.status === 'backlog').length,
      wishlist: this.games.filter(g => g.status === 'wishlist').length,
      completed: this.games.filter(g => g.status === 'completed').length,
      paused: this.games.filter(g => g.status === 'paused' || g.status === 'dropped').length,
    };

    for (const [k, v] of Object.entries(counts)) {
      const el = document.getElementById(`badge-${k}`);
      if (el) el.textContent = v;
    }
  },

  // --- SVG RATING HELPERS ---
  renderGradeBadgeHtml(grade) {
    if (!grade) return '';
    const map = {
      'izumitelno': { label: 'Изумительно', cls: 'grade-badge-izumitelno', svg: '/assets/ratings/izumitelno.svg' },
      'pohvalno': { label: 'Похвально', cls: 'grade-badge-pohvalno', svg: '/assets/ratings/pohvalno.svg' },
      'prohodnyak': { label: 'Проходняк', cls: 'grade-badge-prohodnyak', svg: '/assets/ratings/prohodnyak.svg' },
      'musor': { label: 'Мусор', cls: 'grade-badge-musor', svg: '/assets/ratings/musor.svg' }
    };
    const item = map[grade];
    if (!item) return '';
    return `
      <div class="grade-badge ${item.cls}" title="${item.label}">
        <img src="${item.svg}" alt="${item.label}">
        <span>${item.label}</span>
      </div>
    `;
  },

  selectModalGrade(grade) {
    this.selectedModalGrade = (this.selectedModalGrade === grade) ? '' : grade;
    document.getElementById('form-rating-grade').value = this.selectedModalGrade;
    document.querySelectorAll('#game-modal .rating-picker-item').forEach(el => {
      if (el.getAttribute('data-grade') === this.selectedModalGrade) {
        el.classList.add('selected');
      } else {
        el.classList.remove('selected');
      }
    });
  },

  selectCompleteGrade(grade) {
    this.selectedCompleteGrade = grade;
    document.getElementById('complete-rating-grade').value = grade;
    document.querySelectorAll('#complete-modal .rating-picker-item').forEach(el => {
      if (el.id === `c-grade-${grade}`) {
        el.classList.add('selected');
      } else {
        el.classList.remove('selected');
      }
    });
  },

  // --- RENDER VIEWS ---

  // 1. PLAYING
  renderPlayingView() {
    const container = document.getElementById('playing-hero-container');
    const emptyState = document.getElementById('playing-empty-state');
    if (!container) return;

    const playingGames = this.games.filter(g => g.status === 'playing');

    if (playingGames.length === 0) {
      container.innerHTML = '';
      if (emptyState) emptyState.style.display = 'block';
      return;
    }

    if (emptyState) emptyState.style.display = 'none';

    container.innerHTML = playingGames.map(game => {
      const playedHours = (game.user_playtime_minutes / 60).toFixed(1);
      const estHours = game.playtime_main || 10.0;
      const progressPercent = Math.min(100, Math.round((game.user_playtime_minutes / (estHours * 60)) * 100));
      const bgImg = game.cover_url || game.background_url || '';

      return `
        <div class="hero-card">
          <div class="hero-backdrop" style="background-image: url('${bgImg}')">
            <div class="hero-badge-strip">
              <span class="comic-badge badge-playing">💥 В ПРОЦЕССЕ</span>
              <span class="comic-badge badge-platform">${game.platform || 'PC'}</span>
              <span class="comic-badge badge-priority">🔥 ${this.formatPriority(game.priority)}</span>
            </div>
          </div>

          <div class="hero-body">
            <h2 class="hero-title">${this.escapeHtml(game.title)}</h2>
            <div class="hero-genres">${this.escapeHtml(game.genres || 'Экшен, Приключения')} ${game.release_date ? '• ' + game.release_date.split('-')[0] : ''}</div>

            <div class="tracker-box">
              <div class="tracker-stats">
                <div>
                  <span class="tracker-hours">${playedHours} ч</span>
                  <span style="font-size:0.75rem; color:var(--sv-text-muted);">наиграно</span>
                </div>
                <div class="tracker-target">
                  Цель: ~<strong>${estHours} ч</strong> (${progressPercent}%)
                </div>
              </div>

              <div class="progress-bar-wrap">
                <div class="progress-bar-fill" style="width: ${progressPercent}%"></div>
              </div>

              <div class="quick-time-buttons">
                <button class="quick-btn" onclick="app.quickAddMinutes(${game.id}, 15)">+15м</button>
                <button class="quick-btn" onclick="app.quickAddMinutes(${game.id}, 30)">+30м</button>
                <button class="quick-btn" onclick="app.quickAddMinutes(${game.id}, 60)">+1ч</button>
                <button class="quick-btn" onclick="app.openQuickTimeModal(${game.id}, '${this.escapeJs(game.title)}')">⏱️ Время...</button>
              </div>
            </div>

            ${game.notes ? `<div style="font-size:0.82rem; color:var(--sv-text-secondary); background:rgba(0,0,0,0.3); padding:8px 12px; clip-path:var(--clip-badge); margin-bottom:16px;">📝 ${this.escapeHtml(game.notes)}</div>` : ''}

            <div class="hero-actions">
              <div style="display:flex; gap:8px; flex-wrap:wrap;">
                <button class="sv-btn sv-btn-yellow sv-btn-sm" onclick="app.openCompleteModal(${game.id}, '${this.escapeJs(game.title)}')">🏆 Пройдено!</button>
                <button class="sv-btn sv-btn-cyan sv-btn-sm" onclick="app.openTrailerModal(${game.id}, '${this.escapeJs(game.title)}', '${this.escapeJs(game.cover_url || game.background_url || '')}', '${this.escapeJs(game.platform || '')}', '${this.escapeJs(game.genres || '')}')">🎬 Трейлер</button>
                <button class="sv-btn sv-btn-outline sv-btn-sm" onclick="app.openGameModal(${game.id})" title="Редактировать">✏️</button>
                <button class="sv-btn sv-btn-outline sv-btn-sm" style="color:var(--sv-red); border-color:var(--sv-red);" onclick="app.deleteGame(${game.id})" title="Удалить из библиотеки">🗑️</button>
              </div>
              <select class="sv-select" onchange="app.changeStatus(${game.id}, this.value)" style="font-size:0.78rem; padding:4px 8px;">
                <option value="playing" selected>⚡ Играю</option>
                <option value="backlog">📚 В бэклог</option>
                <option value="paused">⏸️ На паузу</option>
                <option value="dropped">❌ Дропнуть</option>
              </select>
            </div>
          </div>
        </div>
      `;
    }).join('');
  },

  // 2. BACKLOG
  filterAndRenderBacklog() {
    const grid = document.getElementById('backlog-grid');
    if (!grid) return;

    const searchTerm = (document.getElementById('backlog-search')?.value || '').toLowerCase();
    const platform = document.getElementById('backlog-platform-filter')?.value || 'all';
    const genre = document.getElementById('backlog-genre-filter')?.value || 'all';
    const priority = document.getElementById('backlog-priority-filter')?.value || 'all';
    const sortBy = document.getElementById('backlog-sort')?.value || 'created_at_desc';

    let list = this.games.filter(g => g.status === 'backlog');

    if (searchTerm) {
      list = list.filter(g => 
        (g.title || '').toLowerCase().includes(searchTerm) || 
        (g.genres || '').toLowerCase().includes(searchTerm) ||
        (g.notes || '').toLowerCase().includes(searchTerm)
      );
    }

    if (platform !== 'all') {
      list = list.filter(g => (g.platform || '').includes(platform) || (g.platforms_list || []).includes(platform));
    }

    if (genre !== 'all') {
      list = list.filter(g => (g.genres || '').includes(genre));
    }

    if (priority !== 'all') {
      list = list.filter(g => g.priority === priority);
    }

    if (sortBy === 'playtime_asc') list.sort((a, b) => (a.playtime_main || 0) - (b.playtime_main || 0));
    else if (sortBy === 'playtime_desc') list.sort((a, b) => (b.playtime_main || 0) - (a.playtime_main || 0));
    else if (sortBy === 'rating_desc') list.sort((a, b) => (b.rawg_rating || 0) - (a.rawg_rating || 0));
    else if (sortBy === 'title_asc') list.sort((a, b) => a.title.localeCompare(b.title));
    else if (sortBy === 'priority_desc') {
      const pWeights = { urgent: 1, high: 2, medium: 3, low: 4 };
      list.sort((a, b) => (pWeights[a.priority] || 5) - (pWeights[b.priority] || 5));
    } else {
      list.sort((a, b) => b.id - a.id);
    }

    if (list.length === 0) {
      grid.innerHTML = `<div style="grid-column: 1/-1; text-align:center; padding: 40px; color:var(--sv-text-muted);">Игр в бэклоге не найдено. Нажмите «RAWG.io Инструмент» или «+ Добавить игру»!</div>`;
      return;
    }

    grid.innerHTML = list.map(g => this.renderGameCardHtml(g, 'backlog')).join('');
  },

  // 3. WISHLIST
  filterAndRenderWishlist() {
    const grid = document.getElementById('wishlist-grid');
    if (!grid) return;

    const searchTerm = (document.getElementById('wishlist-search')?.value || '').toLowerCase();
    const platform = document.getElementById('wishlist-platform-filter')?.value || 'all';

    let list = this.games.filter(g => g.status === 'wishlist');

    if (searchTerm) {
      list = list.filter(g => (g.title || '').toLowerCase().includes(searchTerm) || (g.genres || '').toLowerCase().includes(searchTerm));
    }
    if (platform !== 'all') {
      list = list.filter(g => (g.platform || '').includes(platform) || (g.platforms_list || []).includes(platform));
    }

    if (list.length === 0) {
      grid.innerHTML = `<div style="grid-column: 1/-1; text-align:center; padding: 40px; color:var(--sv-text-muted);">Вишлист пуст. Добавьте ожидаемые тайтлы или перенесите новинки!</div>`;
      return;
    }

    grid.innerHTML = list.map(g => this.renderGameCardHtml(g, 'wishlist')).join('');
  },

  // 4. COMPLETED
  filterAndRenderCompleted() {
    const grid = document.getElementById('completed-grid');
    if (!grid) return;

    const searchTerm = (document.getElementById('completed-search')?.value || '').toLowerCase();
    const gradeFilter = document.getElementById('completed-grade-filter')?.value || 'all';
    const sortBy = document.getElementById('completed-sort')?.value || 'created_at_desc';

    let list = this.games.filter(g => g.status === 'completed');

    if (searchTerm) {
      list = list.filter(g => (g.title || '').toLowerCase().includes(searchTerm) || (g.user_review || '').toLowerCase().includes(searchTerm));
    }

    if (gradeFilter !== 'all') {
      list = list.filter(g => g.rating_grade === gradeFilter);
    }

    if (sortBy === 'grade_desc') {
      const gWeights = { izumitelno: 1, pohvalno: 2, prohodnyak: 3, musor: 4 };
      list.sort((a, b) => (gWeights[a.rating_grade] || 5) - (gWeights[b.rating_grade] || 5));
    } else if (sortBy === 'user_playtime_desc') {
      list.sort((a, b) => (b.user_playtime_minutes || 0) - (a.user_playtime_minutes || 0));
    } else {
      list.sort((a, b) => b.id - a.id);
    }

    if (list.length === 0) {
      grid.innerHTML = `<div style="grid-column: 1/-1; text-align:center; padding: 40px; color:var(--sv-text-muted);">Пока нет пройденных игр по выбранным критериям.</div>`;
      return;
    }

    grid.innerHTML = list.map(g => this.renderGameCardHtml(g, 'completed')).join('');
  },

  // 5. PAUSED
  renderPausedView() {
    const grid = document.getElementById('paused-grid');
    if (!grid) return;

    const list = this.games.filter(g => g.status === 'paused' || g.status === 'dropped');

    if (list.length === 0) {
      grid.innerHTML = `<div style="grid-column: 1/-1; text-align:center; padding: 40px; color:var(--sv-text-muted);">Нет игр на паузе или дропнутых.</div>`;
      return;
    }

    grid.innerHTML = list.map(g => this.renderGameCardHtml(g, 'paused')).join('');
  },

  renderGameCardHtml(g, context) {
    const poster = g.cover_url || g.background_url || '';
    const playedH = (g.user_playtime_minutes / 60).toFixed(1);
    const estH = g.playtime_main ? `${g.playtime_main} ч` : 'Не указано';

    return `
      <div class="game-card">
        <div class="card-poster" style="background-image: url('${poster}')">
          <div class="card-top-bar">
            <div class="card-badges">
              <span class="comic-badge badge-platform">${g.platform || 'PC'}</span>
              ${g.priority ? `<span class="comic-badge badge-priority">${this.formatPriority(g.priority)}</span>` : ''}
            </div>
            <div class="rating-tag">
              ${g.rating_grade ? this.renderGradeBadgeHtml(g.rating_grade) : (g.rawg_rating ? `⭐ ${g.rawg_rating.toFixed(1)}` : '')}
            </div>
          </div>
        </div>

        <div class="card-content">
          <h3 class="card-title">${this.escapeHtml(g.title)}</h3>
          <div class="card-meta">
            ${g.genres ? this.escapeHtml(g.genres) : 'Игры'} ${g.release_date ? '• ' + g.release_date.split('-')[0] : ''}
          </div>

          <div class="card-playtime-row">
            <span class="card-playtime-label">
              ${context === 'completed' ? 'Итог:' : (g.user_playtime_minutes > 0 ? 'Наиграно:' : 'Сюжет:')}
            </span>
            <span class="card-playtime-val">
              ${context === 'completed' ? `${playedH} ч` : (g.user_playtime_minutes > 0 ? `${playedH} / ~${estH}` : `~${estH}`)}
            </span>
          </div>

          ${g.user_review ? `<div style="font-size:0.8rem; color:var(--sv-yellow); margin-bottom:10px; font-style:italic; border-left:3px solid var(--sv-yellow); padding-left:8px;">"${this.escapeHtml(g.user_review)}"</div>` : ''}
          ${g.notes && !g.user_review ? `<div style="font-size:0.78rem; color:var(--sv-text-muted); margin-bottom:10px;">📝 ${this.escapeHtml(g.notes)}</div>` : ''}

          <div class="card-footer-layout">
            <div class="card-primary-actions">
              ${context === 'backlog' ? `
                <button class="sv-btn sv-btn-primary sv-btn-sm" style="width:100%;" onclick="app.startPlaying(${g.id})">⚡ Играть</button>
              ` : ''}
              ${context === 'wishlist' ? `
                <button class="sv-btn sv-btn-cyan sv-btn-sm" style="flex:1;" onclick="app.changeStatus(${g.id}, 'backlog')">📚 В бэклог</button>
                <button class="sv-btn sv-btn-primary sv-btn-sm" style="flex:1;" onclick="app.startPlaying(${g.id})">⚡ Играть</button>
              ` : ''}
              ${context === 'completed' ? `
                <button class="sv-btn sv-btn-yellow sv-btn-sm" style="width:100%;" onclick="app.openCompleteModal(${g.id}, '${this.escapeJs(g.title)}')">🏆 Оценка</button>
              ` : ''}
              ${context === 'paused' ? `
                <button class="sv-btn sv-btn-primary sv-btn-sm" style="width:100%;" onclick="app.startPlaying(${g.id})">⚡ Возобновить</button>
              ` : ''}
            </div>
            <div class="card-utility-actions">
              <button class="sv-btn sv-btn-cyan sv-btn-sm" style="flex:1;" onclick="app.openTrailerModal(${g.id}, '${this.escapeJs(g.title)}', '${this.escapeJs(g.cover_url || g.background_url || '')}', '${this.escapeJs(g.platform || '')}', '${this.escapeJs(g.genres || '')}')" title="Смотреть трейлер">🎬 Трейлер</button>
              <button class="sv-btn sv-btn-outline sv-btn-sm" onclick="app.openGameModal(${g.id})" title="Редактировать">✏️</button>
              <button class="sv-btn sv-btn-outline sv-btn-sm" style="color:var(--sv-red); border-color:var(--sv-red);" onclick="app.deleteGame(${g.id})" title="Удалить">🗑️</button>
            </div>
          </div>
        </div>
      </div>
    `;
  },

  // --- STATS VIEW ---
  renderStatsView() {
    const row = document.getElementById('stats-cards-container');
    const tierRow = document.getElementById('tier-stats-container');
    const chart = document.getElementById('platform-stats-chart');
    const genreChart = document.getElementById('genre-stats-chart');
    if (!row) return;

    row.innerHTML = `
      <div class="stat-box">
        <div class="stat-number">${this.stats.total_games || 0}</div>
        <div class="stat-label">Всего игр в базе</div>
      </div>
      <div class="stat-box">
        <div class="stat-number" style="color:var(--sv-magenta);">${this.stats.playing_count || 0}</div>
        <div class="stat-label">В процессе</div>
      </div>
      <div class="stat-box">
        <div class="stat-number" style="color:var(--sv-yellow);">${this.stats.backlog_count || 0}</div>
        <div class="stat-label">Бэклог (~${this.stats.backlog_total_hours || 0} ч)</div>
      </div>
      <div class="stat-box">
        <div class="stat-number" style="color:var(--sv-green);">${this.stats.completed_count || 0}</div>
        <div class="stat-label">Успешно пройдено</div>
      </div>
      <div class="stat-box">
        <div class="stat-number">${this.stats.total_playtime_hours || 0} ч</div>
        <div class="stat-label">Общее игровое время</div>
      </div>
    `;

    // 4-Tier SVG Rating Stats
    if (tierRow && this.stats.grade_counts) {
      const g = this.stats.grade_counts;
      tierRow.innerHTML = `
        <div class="tier-stat-card" style="border-color:#6ca2ac;">
          <img src="/assets/ratings/izumitelno.svg" alt="Изумительно">
          <div>
            <div style="font-family:var(--font-comic); font-size:1.4rem; color:#6ca2ac;">${g.izumitelno || 0}</div>
            <div style="font-size:0.75rem; font-weight:800; text-transform:uppercase;">Изумительно</div>
          </div>
        </div>
        <div class="tier-stat-card" style="border-color:#68a679;">
          <img src="/assets/ratings/pohvalno.svg" alt="Похвально">
          <div>
            <div style="font-family:var(--font-comic); font-size:1.4rem; color:#68a679;">${g.pohvalno || 0}</div>
            <div style="font-size:0.75rem; font-weight:800; text-transform:uppercase;">Похвально</div>
          </div>
        </div>
        <div class="tier-stat-card" style="border-color:#e99b21;">
          <img src="/assets/ratings/prohodnyak.svg" alt="Проходняк">
          <div>
            <div style="font-family:var(--font-comic); font-size:1.4rem; color:#e99b21;">${g.prohodnyak || 0}</div>
            <div style="font-size:0.75rem; font-weight:800; text-transform:uppercase;">Проходняк</div>
          </div>
        </div>
        <div class="tier-stat-card" style="border-color:#cb282c;">
          <img src="/assets/ratings/musor.svg" alt="Мусор">
          <div>
            <div style="font-family:var(--font-comic); font-size:1.4rem; color:#cb282c;">${g.musor || 0}</div>
            <div style="font-size:0.75rem; font-weight:800; text-transform:uppercase;">Мусор</div>
          </div>
        </div>
      `;
    }

    // Platforms Chart
    if (chart && this.stats.platform_counts) {
      const entries = Object.entries(this.stats.platform_counts);
      if (entries.length === 0) {
        chart.innerHTML = `<div style="color:var(--sv-text-muted);">Нет данных по платформам.</div>`;
      } else {
        const maxVal = Math.max(...entries.map(e => e[1])) || 1;
        chart.innerHTML = entries.map(([plat, count]) => {
          const percent = Math.round((count / maxVal) * 100);
          return `
            <div>
              <div style="display:flex; justify-content:space-between; font-size:0.85rem; font-weight:700; margin-bottom:4px;">
                <span>${this.escapeHtml(plat)}</span>
                <span style="color:var(--sv-cyan);">${count} игр</span>
              </div>
              <div class="progress-bar-wrap" style="height:10px;">
                <div class="progress-bar-fill" style="width: ${percent}%;"></div>
              </div>
            </div>
          `;
        }).join('');
      }
    }

    // Genres Chart
    if (genreChart && this.stats.top_genres) {
      genreChart.innerHTML = this.stats.top_genres.map(([genre, count]) => `
        <div style="background:var(--sv-bg-deep); border:1px solid var(--sv-border-bright); padding:6px 14px; clip-path:var(--clip-badge); font-size:0.85rem; font-weight:700;">
          <span style="color:#fff;">${this.escapeHtml(genre)}</span>: <strong style="color:var(--sv-cyan);">${count}</strong>
        </div>
      `).join('');
    }
  },

  // --- RAWG STREAMLINED SEARCH & 1-CLICK ADD TOOL ---
  async performRawgSearch(query) {
    if (!query || !query.trim()) return;
    const grid = document.getElementById('rawg-results-grid');
    const msg = document.getElementById('rawg-status-message');
    if (!grid) return;

    grid.innerHTML = `<div style="grid-column:1/-1; text-align:center; padding:40px; color:var(--sv-cyan);">🔍 Поиск в базе RAWG.io... По запросу "${query}"...</div>`;

    try {
      const res = await fetch(`/api/rawg/search?query=${encodeURIComponent(query.trim())}`);
      const data = await res.json();

      if (msg) {
        if (data.requires_api_key) {
          msg.innerHTML = `<div style="background:rgba(255,230,0,0.15); border:1px solid var(--sv-yellow); color:var(--sv-yellow); padding:10px 16px; clip-path:var(--clip-cut-corner); font-size:0.85rem;">⚠️ ${data.message} Показаны примеры.</div>`;
        } else if (!data.success && data.error) {
          msg.innerHTML = `<div style="background:rgba(255,34,71,0.15); border:1px solid var(--sv-red); color:var(--sv-red); padding:10px 16px; clip-path:var(--clip-cut-corner); font-size:0.85rem;">❌ ${data.error}</div>`;
        } else {
          msg.innerHTML = `<div style="color:var(--sv-green); font-size:0.85rem; font-weight:700;">✅ Найдено игр в RAWG: ${data.count || (data.results || []).length}</div>`;
        }
      }

      const results = data.results || [];
      if (results.length === 0) {
        grid.innerHTML = `<div style="grid-column:1/-1; text-align:center; padding:40px; color:var(--sv-text-muted);">Ничего не найдено по запросу "${query}".</div>`;
        return;
      }

      grid.innerHTML = results.map(item => {
        const itemJson = encodeURIComponent(JSON.stringify(item));
        return `
          <div class="game-card">
            <div class="card-poster" style="background-image: url('${item.cover_url || ''}')">
              <div class="card-top-bar">
                <div class="card-badges">
                  <span class="comic-badge badge-platform">${item.platform || 'PC'}</span>
                </div>
                <div class="rating-tag" style="background:rgba(0,0,0,0.8); border:1px solid var(--sv-yellow); color:var(--sv-yellow); padding:3px 8px; clip-path:var(--clip-badge); font-family:var(--font-comic); font-size:0.8rem;">
                  ⭐ ${item.rawg_rating ? item.rawg_rating.toFixed(1) : (item.metacritic || '-')}
                </div>
              </div>
            </div>
            <div class="card-content">
              <h3 class="card-title">${this.escapeHtml(item.title)}</h3>
              <div class="card-meta">${this.escapeHtml(item.genres || 'Экшен')} • ${item.release_date ? item.release_date.split('-')[0] : 'TBA'}</div>
              <div class="card-playtime-row">
                <span class="card-playtime-label">Время сюжета:</span>
                <span class="card-playtime-val">~${item.playtime_main} ч</span>
              </div>
              <div class="card-footer-layout">
                <div class="card-primary-actions">
                  <button class="sv-btn sv-btn-cyan sv-btn-sm" style="flex:1;" onclick="app.quickAddFromRawg(${item.rawg_id}, '${itemJson}', 'backlog')">📚 В бэклог</button>
                  <button class="sv-btn sv-btn-primary sv-btn-sm" style="flex:1;" onclick="app.quickAddFromRawg(${item.rawg_id}, '${itemJson}', 'playing')">⚡ Играть</button>
                </div>
                <div class="card-utility-actions">
                  <button class="sv-btn sv-btn-yellow sv-btn-sm" style="flex:1;" onclick="app.quickAddFromRawg(${item.rawg_id}, '${itemJson}', 'wishlist')">⭐ В вишлист</button>
                  <button class="sv-btn sv-btn-outline sv-btn-sm" onclick="app.openTrailerModal(null, '${this.escapeJs(item.title)}', '${this.escapeJs(item.cover_url || '')}', '${this.escapeJs(item.platform || '')}', '${this.escapeJs(item.genres || '')}')" title="Смотреть трейлер">🎬</button>
                </div>
              </div>
            </div>
          </div>
        `;
      }).join('');
    } catch (e) {
      grid.innerHTML = `<div style="grid-column:1/-1; text-align:center; padding:40px; color:var(--sv-red);">Ошибка поиска RAWG: ${e.message}</div>`;
    }
  },

  async quickAddFromRawg(rawgId, encodedJson, targetStatus) {
    try {
      const item = JSON.parse(decodeURIComponent(encodedJson));
      const res = await fetch('/api/rawg/quick-add', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          rawg_id: rawgId || item.rawg_id,
          target_status: targetStatus,
          game_data: item
        })
      });
      const data = await res.json();
      if (data.success) {
        this.showToast(`«${item.title}» добавлена в раздел «${this.formatStatus(targetStatus)}»!`, 'success');
        await this.refreshAllData();
        this.switchTab(targetStatus);
      } else {
        this.showAlert(data.error || 'Не удалось добавить игру', 'ОШИБКА ДОБАВЛЕНИЯ', 'error');
      }
    } catch (e) {
      this.showAlert(e.message, 'СЕТЕВАЯ ОШИБКА RAWG', 'error');
    }
  },

  // --- ACTIONS & CRUD ---
  async startPlaying(gameId) {
    await this.updateGameField(gameId, { status: 'playing' });
    this.refreshAllData();
    this.switchTab('playing');
  },

  openCompleteModal(gameId, gameTitle) {
    const modal = document.getElementById('complete-modal');
    document.getElementById('complete-game-id').value = gameId;
    document.getElementById('complete-game-name').textContent = `Игра: ${gameTitle}`;
    document.getElementById('complete-review-text').value = '';
    this.selectCompleteGrade('izumitelno');
    if (modal) modal.classList.add('open');
  },

  async saveCompleteForm() {
    const gameId = document.getElementById('complete-game-id').value;
    const grade = document.getElementById('complete-rating-grade').value;
    const review = document.getElementById('complete-review-text').value;

    await this.updateGameField(gameId, {
      status: 'completed',
      rating_grade: grade,
      user_review: review || ''
    });
    this.closeModal('complete-modal');
    await this.refreshAllData();
    this.switchTab('completed');
  },

  async changeStatus(gameId, newStatus) {
    await this.updateGameField(gameId, { status: newStatus });
    this.refreshAllData();
  },

  async quickAddMinutes(gameId, minutes) {
    try {
      const res = await fetch(`/api/games/${gameId}/quick-time`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ additional_minutes: minutes, note: `+${minutes} мин сессия` })
      });
      if (res.ok) {
        await this.refreshAllData();
      }
    } catch (e) {
      console.error(e);
    }
  },

  async deleteGame(gameId) {
    const game = this.games.find(g => g.id === gameId);
    const gameName = game ? game.title : 'эту игру';
    const confirmed = await this.showConfirm({
      title: '🗑️ УДАЛЕНИЕ ИГРЫ',
      message: `Вы действительно хотите удалить <strong>«${this.escapeHtml(gameName)}»</strong> из библиотеки?`,
      confirmText: 'Да, удалить',
      type: 'danger'
    });
    if (!confirmed) return;

    try {
      const res = await fetch(`/api/games/${gameId}`, { method: 'DELETE' });
      if (res.ok) {
        this.showToast(`«${gameName}» удалена из библиотеки`, 'info');
        await this.refreshAllData();
      }
    } catch (e) {
      this.showAlert(e.message, 'ОШИБКА УДАЛЕНИЯ', 'error');
    }
  },

  async deleteCurrentModalGame() {
    const gameId = parseInt(document.getElementById('form-game-id').value, 10);
    if (!gameId) return;
    this.closeModal('game-modal');
    await this.deleteGame(gameId);
  },

  async moveAllWishlistToBacklog() {
    const wishlistGames = this.games.filter(g => g.status === 'wishlist');
    if (wishlistGames.length === 0) {
      this.showAlert('В вишлисте нет игр для переноса.', 'ВИШЛИСТ ПУСТ', 'info');
      return;
    }

    const confirmed = await this.showConfirm({
      title: '📚 ПЕРЕНОС В БЭКЛОГ',
      message: `Перенести все игры из вишлиста (<strong>${wishlistGames.length} шт.</strong>) в бэклог? Они станут доступны для Колеса Рандомайзера и планирования прохождений.`,
      confirmText: 'Да, перенести все',
      type: 'warning'
    });
    if (!confirmed) return;

    try {
      const res = await fetch('/api/games/move-status', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ from_status: 'wishlist', to_status: 'backlog' })
      });
      const data = await res.json();
      if (data.success) {
        this.showToast(`Перенесено в бэклог: ${data.moved_count} игр!`, 'success');
        await this.refreshAllData();
        this.switchTab('backlog');
      } else {
        this.showAlert(data.error || 'Ошибка переноса', 'ОШИБКА', 'error');
      }
    } catch (e) {
      this.showAlert(e.message, 'ОШИБКА СЕТИ', 'error');
    }
  },

  async clearStatusCategory(status) {
    const count = this.games.filter(g => g.status === status).length;
    if (count === 0) {
      this.showAlert(`В этом разделе нет игр для удаления.`, 'РАЗДЕЛ ПУСТ', 'info');
      return;
    }

    const statusName = this.formatStatus(status);
    const confirmed = await this.showConfirm({
      title: `🗑️ ОЧИСТИТЬ «${statusName.toUpperCase()}»`,
      message: `Вы действительно хотите удалить <strong>все ${count} игр</strong> из раздела «${statusName}»? Это действие необратимо.`,
      confirmText: 'Да, удалить все',
      type: 'danger'
    });
    if (!confirmed) return;

    try {
      const res = await fetch('/api/games/clear-status', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ status: status })
      });
      const data = await res.json();
      if (data.success) {
        this.showToast(`Раздел «${statusName}» очищен (${data.deleted_count} игр)`, 'info');
        await this.refreshAllData();
      } else {
        this.showAlert(data.error || 'Ошибка очистки', 'ОШИБКА', 'error');
      }
    } catch (e) {
      this.showAlert(e.message, 'ОШИБКА СЕТИ', 'error');
    }
  },

  async updateGameField(gameId, fields) {
    try {
      const res = await fetch(`/api/games/${gameId}`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(fields)
      });
      return await res.json();
    } catch (e) {
      console.error(e);
    }
  },

  // --- MODALS ---
  openGameModal(gameId = null) {
    const modal = document.getElementById('game-modal');
    const titleEl = document.getElementById('game-modal-title');
    const form = document.getElementById('game-form');
    const delBtn = document.getElementById('modal-btn-delete');
    form.reset();
    this.selectedModalGrade = '';
    document.getElementById('form-rating-grade').value = '';

    if (gameId) {
      if (delBtn) delBtn.style.display = 'inline-flex';
      const game = this.games.find(g => g.id === gameId);
      if (game) {
        titleEl.textContent = '✏️ РЕДАКТИРОВАТЬ ИГРУ';
        document.getElementById('form-game-id').value = game.id;
        document.getElementById('form-title').value = game.title || '';
        document.getElementById('form-status').value = game.status || 'backlog';
        document.getElementById('form-priority').value = game.priority || 'medium';
        document.getElementById('form-platform').value = game.platform || 'PC';
        document.getElementById('form-release-date').value = game.release_date || '';
        document.getElementById('form-completed-at').value = this.formatCompletedAtDisplay(game.completed_at) || '';
        document.getElementById('form-developer').value = game.developer || '';
        document.getElementById('form-cover-url').value = game.cover_url || '';
        document.getElementById('form-playtime-main').value = game.playtime_main || '';
        document.getElementById('form-user-playtime').value = game.user_playtime_minutes || 0;
        document.getElementById('form-user-review').value = game.user_review || '';
        document.getElementById('form-notes').value = game.notes || '';
        
        this.setModalGenres(game.genres || '');

        if (game.rating_grade) {
          this.selectModalGrade(game.rating_grade);
        }
      }
    } else {
      if (delBtn) delBtn.style.display = 'none';
      titleEl.textContent = '⚡ ДОБАВИТЬ ИГРУ';
      document.getElementById('form-game-id').value = '';
      if (document.getElementById('form-completed-at')) {
        document.getElementById('form-completed-at').value = '';
      }
      this.setModalGenres('');
    }

    if (modal) modal.classList.add('open');
  },

  formatCompletedAtDisplay(val) {
    if (!val) return '';
    const trimmed = String(val).trim();
    if (!trimmed) return '';
    if (/^\d{2}\.\d{4}$/.test(trimmed)) return trimmed;
    if (/^\d{1}\.\d{4}$/.test(trimmed)) return '0' + trimmed;
    if (/^\d{4}-\d{2}$/.test(trimmed)) {
      const parts = trimmed.split('-');
      return `${parts[1]}.${parts[0]}`;
    }
    try {
      const d = new Date(trimmed);
      if (!isNaN(d.getTime())) {
        const m = String(d.getMonth() + 1).padStart(2, '0');
        const y = d.getFullYear();
        return `${m}.${y}`;
      }
    } catch (e) {}
    return trimmed;
  },

  openQuickTimeModal(gameId, gameTitle) {
    const modal = document.getElementById('quick-time-modal');
    document.getElementById('quick-time-game-id').value = gameId;
    document.getElementById('quick-time-game-name').textContent = `Игра: ${gameTitle}`;
    document.getElementById('quick-minutes-input').value = '30';
    if (modal) modal.classList.add('open');
  },

  setQuickMinutes(mins) {
    document.getElementById('quick-minutes-input').value = mins;
  },

  closeModal(modalId) {
    const modal = document.getElementById(modalId);
    if (modal) modal.classList.remove('open');
  },

  async saveGameForm() {
    const id = document.getElementById('form-game-id').value;
    const payload = {
      title: document.getElementById('form-title').value,
      status: document.getElementById('form-status').value,
      priority: document.getElementById('form-priority').value,
      platform: document.getElementById('form-platform').value,
      release_date: document.getElementById('form-release-date').value,
      completed_at: document.getElementById('form-completed-at')?.value?.trim() || '',
      genres: document.getElementById('form-genres').value || 'Экшен',
      developer: document.getElementById('form-developer').value,
      cover_url: document.getElementById('form-cover-url').value,
      playtime_main: parseFloat(document.getElementById('form-playtime-main').value) || 0.0,
      user_playtime_minutes: parseInt(document.getElementById('form-user-playtime').value, 10) || 0,
      rating_grade: document.getElementById('form-rating-grade').value || '',
      user_review: document.getElementById('form-user-review').value || '',
      notes: document.getElementById('form-notes').value
    };

    try {
      if (id) {
        await fetch(`/api/games/${id}`, {
          method: 'PUT',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(payload)
        });
      } else {
        await fetch('/api/games', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(payload)
        });
      }
      this.closeModal('game-modal');
      await this.refreshAllData();
    } catch (e) {
      this.showAlert(e.message, 'ОШИБКА СОХРАНЕНИЯ', 'error');
    }
  },

  async saveQuickTime() {
    const gameId = document.getElementById('quick-time-game-id').value;
    const mins = parseInt(document.getElementById('quick-minutes-input').value, 10) || 0;

    if (mins <= 0) return;
    await this.quickAddMinutes(gameId, mins);
    this.closeModal('quick-time-modal');
  },

  // --- GIGACHAT AI ASSISTANT ---
  async loadChatHistory() {
    try {
      const res = await fetch('/api/ai/history');
      const data = await res.json();
      this.chatHistory = data.history || [];
      this.renderChatMessages();
    } catch (e) {
      console.error(e);
    }
  },

  renderChatMessages() {
    const msgList = document.getElementById('ai-messages-list');
    if (!msgList) return;

    if (!this.chatHistory || this.chatHistory.length === 0) {
      msgList.innerHTML = `
        <div class="chat-bubble chat-bubble-assistant">
          🎮 <strong>Штурман GAME-ROOM's на связи!</strong> Я знаю статус всех твоих игр, тайминги прохождений и оценки StopGame ('Изумительно', 'Похвально', 'Проходняк', 'Мусор'). Нажми <strong>«🧠 Портрет геймера»</strong> или задай любой вопрос!
        </div>
      `;
      return;
    }

    msgList.innerHTML = this.chatHistory.map(m => {
      const isUser = m.role === 'user';
      return `
        <div class="chat-bubble ${isUser ? 'chat-bubble-user' : 'chat-bubble-assistant'}">
          ${!isUser ? `<div style="font-size:0.75rem; color:var(--sv-cyan); margin-bottom:6px; font-weight:800;">🤖 AI Штурман</div>` : ''}
          ${this.formatMarkdown(m.content)}
        </div>
      `;
    }).join('');
    msgList.scrollTop = msgList.scrollHeight;
  },

  async sendAiMessage(customPrompt = null, actionType = "chat") {
    const input = document.getElementById('ai-user-input');
    const msgList = document.getElementById('ai-messages-list');
    const userText = customPrompt || (input ? input.value.trim() : '');
    if (!userText) return;

    if (input && !customPrompt) input.value = '';

    this.chatHistory.push({ role: 'user', content: userText });
    this.renderChatMessages();

    const loadingId = 'ai-loading-' + Date.now();
    msgList.innerHTML += `
      <div class="chat-bubble chat-bubble-assistant" id="${loadingId}">
        ⚡ <em>GigaChat анализирует библиотеку и формирует ответ...</em>
      </div>
    `;
    msgList.scrollTop = msgList.scrollHeight;

    try {
      const res = await fetch('/api/ai/chat', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          message: userText,
          history: this.chatHistory,
          include_backlog_context: true,
          action_type: actionType
        })
      });
      const data = await res.json();
      const loadEl = document.getElementById(loadingId);
      if (loadEl) loadEl.remove();

      const reply = data.reply || 'Штурман временно не смог ответить.';
      this.chatHistory.push({ role: 'assistant', content: reply });
      this.renderChatMessages();
    } catch (e) {
      const loadEl = document.getElementById(loadingId);
      if (loadEl) loadEl.remove();
      msgList.innerHTML += `
        <div class="chat-bubble chat-bubble-assistant" style="border-color:var(--sv-red);">
          ❌ Ошибка связи с ассистентом: ${e.message}
        </div>
      `;
    }
  },

  // --- YANDEX.DISK & FULL BUNDLE SYNC ---
  async loadYandexStatusAndBackups() {
    const badge = document.getElementById('yandex-connection-badge');
    const info = document.getElementById('yandex-disk-info');
    if (badge) {
      badge.textContent = 'Проверка связи...';
      badge.className = 'api-status-badge';
    }

    try {
      const statusRes = await fetch('/api/yandex/status');
      const statusData = await statusRes.json();

      if (statusData.connected) {
        if (badge) {
          badge.textContent = `Подключен (${statusData.user})`;
          badge.className = 'api-status-badge api-status-active';
        }
        if (info) {
          info.innerHTML = `Диск: свободно <strong>${statusData.free_gb} ГБ</strong> из ${statusData.total_gb} ГБ | Папка: <code>${statusData.folder}</code>`;
        }
      } else {
        if (badge) {
          badge.textContent = statusData.error || 'Токен не настроен';
          badge.className = 'api-status-badge api-status-missing';
        }
        if (info) {
          info.innerHTML = `Укажите токен в разделе <a href="javascript:app.switchTab('settings')" style="color:var(--sv-cyan);">Настройки</a>.`;
        }
      }

      await this.loadYandexBackups();
    } catch (e) {
      console.error(e);
    }
  },

  async triggerYandexBackup() {
    try {
      const res = await fetch('/api/yandex/backup', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ note: 'Manual user backup' })
      });
      const data = await res.json();
      if (data.success) {
        this.showToast(`Резервная копия успешно создана на Яндекс.Диске! (${data.games_count} игр)`, 'success');
        this.loadYandexBackups();
      } else {
        this.showAlert(data.error || 'Неизвестная ошибка', 'ОШИБКА БЭКАПА', 'error');
      }
    } catch (e) {
      this.showAlert(e.message, 'СЕТЕВАЯ ОШИБКА ЯНДЕКС.ДИСКА', 'error');
    }
  },

  async loadYandexBackups() {
    const listContainer = document.getElementById('yandex-backups-container');
    if (!listContainer) return;

    try {
      const res = await fetch('/api/yandex/backups');
      const data = await res.json();

      if (!data.success || !data.backups || data.backups.length === 0) {
        listContainer.innerHTML = `<div style="color:var(--sv-text-muted); font-size:0.85rem;">Резервных копий пока нет или токен не настроен. Нажмите «Создать бэкап в Яндекс.Диск».</div>`;
        return;
      }

      listContainer.innerHTML = data.backups.map(b => {
        const kbSize = (b.size / 1024).toFixed(1);
        const dateStr = b.created ? new Date(b.created).toLocaleString('ru-RU') : '';
        return `
          <div style="display:flex; justify-content:space-between; align-items:center; background:rgba(0,0,0,0.3); padding:10px 16px; clip-path:var(--clip-badge); margin-bottom:8px; border:1px solid var(--sv-border);">
            <div>
              <strong style="color:var(--sv-cyan);">${this.escapeHtml(b.name)}</strong>
              <div style="font-size:0.75rem; color:var(--sv-text-muted);">${dateStr} • ${kbSize} КБ</div>
            </div>
            <div style="display:flex; gap:8px;">
              <button class="sv-btn sv-btn-yellow sv-btn-sm" onclick="app.restoreYandexBackup('${this.escapeJs(b.path)}')">📥 Восстановить</button>
              <button class="sv-btn sv-btn-outline sv-btn-sm" style="color:var(--sv-red); border-color:var(--sv-red);" onclick="app.deleteYandexBackup('${this.escapeJs(b.path)}', '${this.escapeJs(b.name)}')\" title=\"Удалить этот снимок\">🗑️</button>
            </div>
          </div>
        `;
      }).join('');
    } catch (e) {
      listContainer.innerHTML = `<div style="color:var(--sv-red); font-size:0.85rem;">Ошибка получения списка бэкапов.</div>`;
    }
  },

  async restoreYandexBackup(remotePath) {
    const confirmed = await this.showConfirm({
      title: '☁️ ВОССТАНОВЛЕНИЕ ИЗ ОБЛАКА',
      message: 'Восстановить базу данных из этой облачной копии? Все игры, статусы, тайминги, настройки API и история чата будут полностью синхронизированы.',
      confirmText: '📥 Восстановить всё',
      type: 'warning'
    });
    if (!confirmed) return;

    try {
      const res = await fetch('/api/yandex/restore', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ backup_path: remotePath })
      });
      const data = await res.json();
      if (data.success) {
        this.showToast(data.message || 'Восстановление завершено!', 'success');
        await this.refreshAllData();
        await this.loadSettings();
        await this.loadChatHistory();
      } else {
        this.showAlert(data.error || 'Ошибка восстановления', 'ОШИБКА ВОССТАНОВЛЕНИЯ', 'error');
      }
    } catch (e) {
      this.showAlert(e.message, 'СЕТЕВАЯ ОШИБКА', 'error');
    }
  },

  async deleteYandexBackup(remotePath, filename) {
    const confirmed = await this.showConfirm({
      title: '🗑️ УДАЛЕНИЕ СНИМКА',
      message: `Удалить облачный снимок <strong>«${this.escapeHtml(filename)}»</strong> с Яндекс.Диска навсегда?`,
      confirmText: 'Да, удалить',
      type: 'danger'
    });
    if (!confirmed) return;

    try {
      const res = await fetch('/api/yandex/delete', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ backup_path: remotePath })
      });
      const data = await res.json();
      if (data.success) {
        this.showToast('Резервная копия удалена с Яндекс.Диска', 'info');
        this.loadYandexBackups();
      } else {
        this.showAlert(data.error || 'Ошибка удаления', 'ОШИБКА УДАЛЕНИЯ', 'error');
      }
    } catch (e) {
      this.showAlert(e.message, 'СЕТЕВАЯ ОШИБКА', 'error');
    }
  },

  async handleFullBundleImport(e) {
    const file = e.target.files[0];
    if (!file) return;
    const formData = new FormData();
    formData.append('file', file);

    try {
      const res = await fetch('/api/import/full-bundle', { method: 'POST', body: formData });
      const data = await res.json();
      if (data.success) {
        this.showToast(`Полный бандл импортирован! (${data.imported_games} игр, ${data.imported_settings} настроек)`, 'success');
        await this.refreshAllData();
        await this.loadSettings();
        await this.loadChatHistory();
      } else {
        this.showAlert(JSON.stringify(data), 'ОШИБКА ИМПОРТА', 'error');
      }
    } catch (err) {
      this.showAlert(err.message, 'ОШИБКА ИМПОРТА', 'error');
    }
  },

  // --- SETTINGS ---
  async loadSettings() {
    try {
      const res = await fetch('/api/settings');
      if (res.status === 401) {
        window.location.replace('/login');
        return;
      }
      const data = await res.json();
      const s = data.settings || {};
      
      this.settings = Object.assign({}, s, {
        rawg_configured: data.rawg_configured || data.is_rawg_configured,
        youtube_configured: data.youtube_configured || data.is_youtube_configured,
        gigachat_configured: data.gigachat_configured || data.is_gigachat_configured,
        yandex_configured: data.yandex_configured || data.is_yandex_configured,
        is_rawg_configured: data.rawg_configured || data.is_rawg_configured,
        is_youtube_configured: data.youtube_configured || data.is_youtube_configured,
        is_gigachat_configured: data.gigachat_configured || data.is_gigachat_configured,
        is_yandex_configured: data.yandex_configured || data.is_yandex_configured
      });

      const rawgEl = document.getElementById('setting-rawg-key');
      const ytEl = document.getElementById('setting-youtube-key');
      const gigaKeyEl = document.getElementById('setting-gigachat-key');
      const gigaScopeEl = document.getElementById('setting-gigachat-scope');
      const userEl = document.getElementById('setting-user-name');
      const yandexTokenEl = document.getElementById('setting-yandex-token');
      const yandexFolderEl = document.getElementById('setting-yandex-folder');

      if (rawgEl) {
        rawgEl.value = '';
        rawgEl.placeholder = (data.rawg_configured || data.is_rawg_configured)
          ? '•••••••••••••••• (Ключ сохранён на сервере)'
          : 'Пример: 3a1b2c4d5e6f7g8h9i0j...';
      }
      if (ytEl) {
        ytEl.value = '';
        ytEl.placeholder = (data.youtube_configured || data.is_youtube_configured)
          ? '•••••••••••••••• (Ключ сохранён на сервере)'
          : 'Пример: AIzaSy...';
      }
      if (gigaKeyEl) {
        gigaKeyEl.value = '';
        gigaKeyEl.placeholder = (data.gigachat_configured || data.is_gigachat_configured)
          ? '•••••••••••••••• (Ключ сохранён на сервере)'
          : 'Авторизационные данные Base64 (Client Secret)...';
      }
      if (gigaScopeEl && s.gigachat_scope) gigaScopeEl.value = s.gigachat_scope;
      if (userEl && s.user_name) userEl.value = s.user_name;
      if (yandexTokenEl) {
        yandexTokenEl.value = '';
        yandexTokenEl.placeholder = (data.yandex_configured || data.is_yandex_configured)
          ? '•••••••••••••••• (Токен сохранён на сервере)'
          : 'OAuth токен (y0_...)';
      }
      if (yandexFolderEl && s.yandex_backup_folder) yandexFolderEl.value = s.yandex_backup_folder;

      const syncTokenEl = document.getElementById('setting-sync-token');
      if (syncTokenEl) {
        syncTokenEl.value = data.sync_token_configured
          ? '•••••••••••••••• [Управляется сервером]'
          : '•••••••••••••••• [Не настроен]';
      }
    } catch (e) {
      console.error(e);
    }
  },

  async saveSettings() {
    const rawgVal = (document.getElementById('setting-rawg-key')?.value || '').trim();
    const ytVal = (document.getElementById('setting-youtube-key')?.value || '').trim();
    const gigaVal = (document.getElementById('setting-gigachat-key')?.value || '').trim();
    const yandexVal = (document.getElementById('setting-yandex-token')?.value || '').trim();

    const settingsPayload = {
      user_name: (document.getElementById('setting-user-name')?.value || '').trim(),
      gigachat_scope: (document.getElementById('setting-gigachat-scope')?.value || '').trim(),
      yandex_backup_folder: (document.getElementById('setting-yandex-folder')?.value || '').trim()
    };

    // Only send secret fields if user actually entered a new non-placeholder value
    if (rawgVal && !rawgVal.startsWith('••')) settingsPayload.rawg_api_key = rawgVal;
    if (ytVal && !ytVal.startsWith('••')) settingsPayload.youtube_api_key = ytVal;
    if (gigaVal && !gigaVal.startsWith('••')) settingsPayload.gigachat_auth_key = gigaVal;
    if (yandexVal && !yandexVal.startsWith('••')) settingsPayload.yandex_disk_token = yandexVal;

    try {
      const res = await fetch('/api/settings', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ settings: settingsPayload })
      });
      const data = await res.json();
      if (data.success) {
        this.showToast('Настройки успешно сохранены!', 'success');
        this.loadSettings();
      }
    } catch (e) {
      this.showAlert(e.message, 'ОШИБКА НАСТРОЕК', 'error');
    }
  },

  async logout() {
    try {
      await fetch('/api/auth/logout', { method: 'POST' });
    } catch (e) {
      console.error('Logout error:', e);
    }
    window.location.replace('/login');
  },

  // --- STYLIZED DIALOGS & TOASTS ---
  showConfirm({ title = '⚡ ПОДТВЕРЖДЕНИЕ', message = '', confirmText = 'Подтвердить', cancelText = 'Отмена', type = 'warning' } = {}) {
    return new Promise(resolve => {
      this._dialogResolver = resolve;
      const modal = document.getElementById('app-dialog-modal');
      const titleEl = document.getElementById('dialog-title');
      const msgEl = document.getElementById('dialog-message');
      const iconEl = document.getElementById('dialog-icon');
      const confirmBtn = document.getElementById('dialog-btn-confirm');
      const cancelBtn = document.getElementById('dialog-btn-cancel');

      if (titleEl) titleEl.textContent = title;
      if (msgEl) msgEl.innerHTML = message;

      if (iconEl) {
        iconEl.textContent = (type === 'danger') ? '🗑️' : ((type === 'warning') ? '⚠️' : '⚡');
      }

      if (confirmBtn) {
        confirmBtn.textContent = confirmText;
        confirmBtn.className = (type === 'danger') ? 'sv-btn sv-btn-primary' : 'sv-btn sv-btn-yellow';
        if (type === 'danger') confirmBtn.style.background = 'var(--sv-red)';
        else confirmBtn.style.background = '';
      }

      if (cancelBtn) {
        cancelBtn.style.display = 'inline-flex';
        cancelBtn.textContent = cancelText;
      }

      if (modal) modal.classList.add('open');
    });
  },

  showAlert(message, title = '🎮 УВЕДОМЛЕНИЕ', type = 'info', confirmText = 'ПОНЯТНО') {
    return new Promise(resolve => {
      this._dialogResolver = resolve;
      const modal = document.getElementById('app-dialog-modal');
      const titleEl = document.getElementById('dialog-title');
      const msgEl = document.getElementById('dialog-message');
      const iconEl = document.getElementById('dialog-icon');
      const confirmBtn = document.getElementById('dialog-btn-confirm');
      const cancelBtn = document.getElementById('dialog-btn-cancel');

      if (titleEl) titleEl.textContent = title;
      if (msgEl) msgEl.innerHTML = message;

      if (iconEl) {
        iconEl.textContent = (type === 'error') ? '❌' : ((type === 'success') ? '✅' : 'ℹ️');
      }

      if (confirmBtn) {
        confirmBtn.textContent = confirmText;
        confirmBtn.className = 'sv-btn sv-btn-cyan';
        confirmBtn.style.background = '';
      }

      if (cancelBtn) cancelBtn.style.display = 'none';

      if (modal) modal.classList.add('open');
    });
  },

  resolveDialog(result) {
    const modal = document.getElementById('app-dialog-modal');
    if (modal) modal.classList.remove('open');
    if (this._dialogResolver) {
      this._dialogResolver(result);
      this._dialogResolver = null;
    }
  },

  showToast(message, type = 'info', duration = 3500) {
    const container = document.getElementById('toast-container');
    if (!container) return;

    const toast = document.createElement('div');
    toast.className = `sv-toast toast-${type}`;
    const icons = { success: '✅', error: '❌', warning: '⚠️', info: '⚡' };
    toast.innerHTML = `<span>${icons[type] || '⚡'}</span><span>${this.escapeHtml(message)}</span>`;

    container.appendChild(toast);

    setTimeout(() => {
      toast.classList.add('fade-out');
      setTimeout(() => toast.remove(), 250);
    }, duration);
  },

  // --- AUDIO SYNTHESIZER (WEB AUDIO API) ---
  initAudio() {
    if (!this.audioCtx) {
      const AudioCtx = window.AudioContext || window.webkitAudioContext;
      if (AudioCtx) {
        this.audioCtx = new AudioCtx();
      }
    }
    if (this.audioCtx && this.audioCtx.state === "suspended") {
      this.audioCtx.resume();
    }
  },

  playTickSound(freq = 480) {
    if (!this.wheelSoundEnabled) return;
    try {
      this.initAudio();
      if (!this.audioCtx) return;
      const osc = this.audioCtx.createOscillator();
      const gain = this.audioCtx.createGain();
      osc.type = "triangle";
      osc.frequency.setValueAtTime(freq, this.audioCtx.currentTime);
      osc.frequency.exponentialRampToValueAtTime(120, this.audioCtx.currentTime + 0.04);
      gain.gain.setValueAtTime(0.18, this.audioCtx.currentTime);
      gain.gain.exponentialRampToValueAtTime(0.001, this.audioCtx.currentTime + 0.04);
      osc.connect(gain);
      gain.connect(this.audioCtx.destination);
      osc.start();
      osc.stop(this.audioCtx.currentTime + 0.04);
    } catch (e) {}
  },

  playWinFanfare() {
    if (!this.wheelSoundEnabled) return;
    try {
      this.initAudio();
      if (!this.audioCtx) return;
      const notes = [261.63, 329.63, 392.00, 523.25, 659.25, 783.99]; // C4, E4, G4, C5, E5, G5
      notes.forEach((freq, idx) => {
        const osc = this.audioCtx.createOscillator();
        const gain = this.audioCtx.createGain();
        osc.type = "sine";
        const startTime = this.audioCtx.currentTime + idx * 0.08;
        osc.frequency.setValueAtTime(freq, startTime);
        gain.gain.setValueAtTime(0.2, startTime);
        gain.gain.exponentialRampToValueAtTime(0.001, startTime + 0.35);
        osc.connect(gain);
        gain.connect(this.audioCtx.destination);
        osc.start(startTime);
        osc.stop(startTime + 0.35);
      });
    } catch (e) {}
  },

  toggleWheelSound() {
    this.wheelSoundEnabled = !this.wheelSoundEnabled;
    try {
      localStorage.setItem("gameroom_wheel_sound", this.wheelSoundEnabled ? "true" : "false");
    } catch (e) {}
    const btn = document.getElementById("wheel-sound-toggle");
    if (btn) {
      btn.textContent = this.wheelSoundEnabled ? "🔊 ЗВУК: ВКЛ" : "🔇 ЗВУК: ВЫКЛ";
      btn.style.color = this.wheelSoundEnabled ? "var(--sv-yellow)" : "var(--sv-text-muted)";
      btn.style.borderColor = this.wheelSoundEnabled ? "var(--sv-yellow)" : "var(--sv-border-bright)";
    }
  },

  // --- YOUTUBE TRAILER & GAMEPLAY MODAL ---
  openTrailerModal(gameId, title, coverUrl = "", platform = "", genres = "") {
    this.currentTrailerGame = { id: gameId, title, coverUrl, platform, genres };
    this.currentTrailerMode = "trailer";

    const modal = document.getElementById("trailer-modal");
    const titleEl = document.getElementById("trailer-modal-title");
    const metaEl = document.getElementById("trailer-modal-meta");
    const playBtn = document.getElementById("video-action-play");

    if (titleEl) titleEl.textContent = `🎬 ${title}`;
    if (metaEl) metaEl.textContent = `${platform || "Все платформы"} • ${genres || "Игры"}`;

    if (playBtn) {
      if (gameId) {
        const game = this.games.find(g => g.id === gameId);
        playBtn.style.display = (game && game.status === "playing") ? "none" : "inline-flex";
      } else {
        playBtn.style.display = "none";
      }
    }

    // Reset mode buttons
    document.querySelectorAll(".trailer-mode-btn").forEach(btn => {
      btn.classList.remove("active");
    });
    const defaultModeBtn = document.getElementById("trailer-mode-trailer");
    if (defaultModeBtn) defaultModeBtn.classList.add("active");

    if (modal) modal.classList.add("open");

    this.loadTrailerVideo(title, platform, "trailer");
  },

  switchTrailerMode(mode) {
    if (!this.currentTrailerGame) return;
    this.currentTrailerMode = mode;

    document.querySelectorAll(".trailer-mode-btn").forEach(btn => {
      btn.classList.remove("active");
    });
    const activeBtn = document.getElementById(`trailer-mode-${mode}`);
    if (activeBtn) activeBtn.classList.add("active");

    this.loadTrailerVideo(this.currentTrailerGame.title, this.currentTrailerGame.platform, mode);
  },

  async loadTrailerVideo(title, platform, mode) {
    const loader = document.getElementById("video-loader");
    const iframe = document.getElementById("trailer-iframe");
    const fallbackBox = document.getElementById("video-fallback-box");
    const fallbackTitle = document.getElementById("video-fallback-title");
    const fallbackDesc = document.getElementById("video-fallback-desc");
    const fallbackBtn = document.getElementById("video-fallback-btn");
    const titleLabel = document.getElementById("video-playing-title");
    const channelLabel = document.getElementById("video-playing-channel");
    const extLink = document.getElementById("video-external-link");
    const relatedBar = document.getElementById("related-videos-bar");
    const relatedChips = document.getElementById("related-videos-chips");

    if (loader) loader.style.display = "flex";
    if (fallbackBox) fallbackBox.style.display = "none";
    if (relatedBar) relatedBar.style.display = "none";
    if (iframe) iframe.src = "";

    try {
      const res = await fetch(`/api/youtube/trailer?title=${encodeURIComponent(title)}&platform=${encodeURIComponent(platform || "")}&mode=${encodeURIComponent(mode)}`);
      const data = await res.json();

      if (loader) loader.style.display = "none";

      if (data.success && data.primary_video) {
        const vid = data.primary_video;
        if (iframe) iframe.src = vid.embed_url;
        if (titleLabel) titleLabel.textContent = vid.title;
        if (channelLabel) channelLabel.textContent = `Канал: ${vid.channelTitle || "YouTube"}`;
        if (extLink) extLink.href = vid.watch_url;

        const otherVideos = (data.videos || []).filter(v => v.videoId !== vid.videoId);
        if (otherVideos.length > 0 && relatedBar && relatedChips) {
          relatedChips.innerHTML = otherVideos.map(v => {
            return `<button type="button" class="related-chip" onclick="app.selectAlternateVideo('${v.videoId}', '${this.escapeJs(v.title)}', '${this.escapeJs(v.channelTitle)}', '${this.escapeJs(v.watch_url)}')">▶️ ${this.escapeHtml(v.title)}</button>`;
          }).join("");
          relatedBar.style.display = "flex";
        }
      } else if (data.requires_api_key) {
        if (fallbackBox) {
          if (fallbackTitle) fallbackTitle.textContent = "YouTube API Key не настроен";
          if (fallbackDesc) fallbackDesc.textContent = data.message || "Укажите ключ в настройках для автозагрузки трейлеров.";
          if (fallbackBtn) fallbackBtn.href = data.fallback_search_url || `https://www.youtube.com/results?search_query=${encodeURIComponent(title + " trailer")}`;
          fallbackBox.style.display = "flex";
        }
        if (titleLabel) titleLabel.textContent = title;
        if (channelLabel) channelLabel.textContent = "Поиск на YouTube";
        if (extLink) extLink.href = data.fallback_search_url || `https://www.youtube.com/results?search_query=${encodeURIComponent(title + " trailer")}`;
      } else {
        if (fallbackBox) {
          if (fallbackTitle) fallbackTitle.textContent = "Видео не найдено";
          if (fallbackDesc) fallbackDesc.textContent = data.error || "Не удалось загрузить видео через YouTube API.";
          if (fallbackBtn) fallbackBtn.href = data.fallback_search_url || `https://www.youtube.com/results?search_query=${encodeURIComponent(title + " trailer")}`;
          fallbackBox.style.display = "flex";
        }
      }
    } catch (e) {
      if (loader) loader.style.display = "none";
      if (fallbackBox) {
        if (fallbackTitle) fallbackTitle.textContent = "Ошибка загрузки";
        if (fallbackDesc) fallbackDesc.textContent = e.message;
        fallbackBox.style.display = "flex";
      }
    }
  },

  selectAlternateVideo(videoId, title, channelTitle, watchUrl) {
    const iframe = document.getElementById("trailer-iframe");
    const titleLabel = document.getElementById("video-playing-title");
    const channelLabel = document.getElementById("video-playing-channel");
    const extLink = document.getElementById("video-external-link");

    if (iframe) iframe.src = `https://www.youtube.com/embed/${videoId}?autoplay=1&rel=0`;
    if (titleLabel) titleLabel.textContent = title;
    if (channelLabel) channelLabel.textContent = `Канал: ${channelTitle}`;
    if (extLink) extLink.href = watchUrl;
  },

  closeTrailerModal() {
    const modal = document.getElementById("trailer-modal");
    const iframe = document.getElementById("trailer-iframe");
    if (iframe) iframe.src = "";
    if (modal) modal.classList.remove("open");
  },

  startPlayingFromTrailer() {
    if (this.currentTrailerGame && this.currentTrailerGame.id) {
      this.startPlaying(this.currentTrailerGame.id);
      this.closeTrailerModal();
    }
  },

  // --- BACKLOG RANDOMIZER WHEEL ---
  openWheelModal() {
    const modal = document.getElementById("wheel-modal");
    this.wheelWinner = null;
    this.closeWinnerOverlay();
    
    const sndBtn = document.getElementById("wheel-sound-toggle");
    if (sndBtn) {
      sndBtn.textContent = this.wheelSoundEnabled ? "🔊 ЗВУК: ВКЛ" : "🔇 ЗВУК: ВЫКЛ";
    }

    this.updateWheelPool();
    if (modal) modal.classList.add("open");

    setTimeout(() => {
      this.drawWheel();
    }, 50);
  },

  updateWheelPool() {
    const platform = document.getElementById("wheel-filter-platform")?.value || "all";
    const duration = document.getElementById("wheel-filter-duration")?.value || "all";
    const genre = document.getElementById("wheel-filter-genre")?.value || "all";
    const priority = document.getElementById("wheel-filter-priority")?.value || "all";

    let backlogGames = this.games.filter(g => g.status === "backlog");

    if (platform !== "all") {
      backlogGames = backlogGames.filter(g => (g.platform || "").includes(platform) || (g.platforms_list || []).includes(platform));
    }

    if (duration !== "all") {
      backlogGames = backlogGames.filter(g => {
        const h = g.playtime_main || 0;
        if (duration === "short") return h > 0 && h < 6;
        if (duration === "medium") return h >= 6 && h <= 15;
        if (duration === "long") return h > 15 && h <= 30;
        if (duration === "epic") return h > 30;
        return true;
      });
    }

    if (genre !== "all") {
      backlogGames = backlogGames.filter(g => (g.genres || "").includes(genre));
    }

    if (priority !== "all") {
      if (priority === "urgent") {
        backlogGames = backlogGames.filter(g => g.priority === "urgent");
      } else if (priority === "high") {
        backlogGames = backlogGames.filter(g => g.priority === "urgent" || g.priority === "high");
      } else if (priority === "medium") {
        backlogGames = backlogGames.filter(g => g.priority === "urgent" || g.priority === "high" || g.priority === "medium");
      }
    }

    this.wheelCandidates = backlogGames;

    const poolStats = document.getElementById("wheel-pool-stats");
    const candCount = document.getElementById("wheel-candidate-count");
    const activeCandidates = this.getActiveWheelCandidates();

    if (poolStats) poolStats.textContent = `В пуле выбора: ${activeCandidates.length} из ${backlogGames.length} игр`;
    if (candCount) candCount.textContent = activeCandidates.length;

    this.renderWheelCandidatesList();
    this.drawWheel();
  },

  getActiveWheelCandidates() {
    return this.wheelCandidates.filter(g => !this.wheelExcludedIds.has(g.id));
  },

  applyWheelPreset(preset) {
    const platEl = document.getElementById("wheel-filter-platform");
    const durEl = document.getElementById("wheel-filter-duration");
    const genEl = document.getElementById("wheel-filter-genre");
    const prioEl = document.getElementById("wheel-filter-priority");

    if (preset === "quick") {
      if (durEl) durEl.value = "short";
      if (platEl) platEl.value = "all";
      if (genEl) genEl.value = "all";
      if (prioEl) prioEl.value = "all";
    } else if (preset === "story") {
      if (genEl) genEl.value = "Сюжетная";
      if (durEl) durEl.value = "all";
      if (platEl) platEl.value = "all";
      if (prioEl) prioEl.value = "all";
    } else if (preset === "urgent") {
      if (prioEl) prioEl.value = "urgent";
      if (durEl) durEl.value = "all";
      if (platEl) platEl.value = "all";
      if (genEl) genEl.value = "all";
    } else if (preset === "reset") {
      if (platEl) platEl.value = "all";
      if (durEl) durEl.value = "all";
      if (genEl) genEl.value = "all";
      if (prioEl) prioEl.value = "all";
      this.wheelExcludedIds.clear();
    }

    this.updateWheelPool();
  },

  renderWheelCandidatesList() {
    const listEl = document.getElementById("wheel-candidates-list");
    if (!listEl) return;

    if (this.wheelCandidates.length === 0) {
      listEl.innerHTML = `<div style="text-align:center; padding:20px; color:var(--sv-text-muted); font-size:0.8rem;">Нет игр, соответствующих фильтрам. Попробуйте ослабить фильтры.</div>`;
      return;
    }

    listEl.innerHTML = this.wheelCandidates.map(g => {
      const isExcluded = this.wheelExcludedIds.has(g.id);
      const thumb = g.cover_url || g.background_url || "";
      const estH = g.playtime_main ? `${g.playtime_main} ч` : "н/д";
      return `
        <div class="candidate-item ${isExcluded ? "excluded" : ""}" onclick="app.toggleWheelCandidate(${g.id})">
          <input type="checkbox" ${isExcluded ? "" : "checked"} onclick="event.stopPropagation(); app.toggleWheelCandidate(${g.id})">
          ${thumb ? `<img src="${thumb}" class="candidate-thumb" alt="">` : `<div class="candidate-thumb" style="display:flex;align-items:center;justify-content:center;font-size:12px;">🎮</div>`}
          <div class="candidate-info">
            <div class="candidate-title" title="${this.escapeHtml(g.title)}">${this.escapeHtml(g.title)}</div>
            <div class="candidate-meta">${g.platform || "PC"} • ~${estH} • ${this.formatPriority(g.priority)}</div>
          </div>
        </div>
      `;
    }).join("");
  },

  toggleWheelCandidate(gameId) {
    if (this.wheelExcludedIds.has(gameId)) {
      this.wheelExcludedIds.delete(gameId);
    } else {
      this.wheelExcludedIds.add(gameId);
    }
    const poolStats = document.getElementById("wheel-pool-stats");
    const candCount = document.getElementById("wheel-candidate-count");
    const active = this.getActiveWheelCandidates();
    if (poolStats) poolStats.textContent = `В пуле выбора: ${active.length} из ${this.wheelCandidates.length} игр`;
    if (candCount) candCount.textContent = active.length;

    this.renderWheelCandidatesList();
    this.drawWheel();
  },

  shuffleWheelPool() {
    for (let i = this.wheelCandidates.length - 1; i > 0; i--) {
      const j = Math.floor(Math.random() * (i + 1));
      [this.wheelCandidates[i], this.wheelCandidates[j]] = [this.wheelCandidates[j], this.wheelCandidates[i]];
    }
    this.renderWheelCandidatesList();
    this.drawWheel();
  },

  getWheelDisplaySliceCandidates() {
    const allActive = this.getActiveWheelCandidates();
    if (allActive.length <= 16) {
      return allActive;
    }
    // Return first 16 candidates for clean, readable slices
    return allActive.slice(0, 16);
  },

  drawWheel() {
    const canvas = document.getElementById("wheel-canvas");
    if (!canvas) return;
    const ctx = canvas.getContext("2d");
    const size = canvas.width;
    const center = size / 2;
    const radius = center - 18;

    ctx.clearRect(0, 0, size, size);

    const active = this.getActiveWheelCandidates();
    const slices = this.getWheelDisplaySliceCandidates();
    const count = slices.length;

    // Outer cyber ring
    ctx.save();
    ctx.beginPath();
    ctx.arc(center, center, radius + 10, 0, 2 * Math.PI);
    ctx.strokeStyle = "#2e2358";
    ctx.lineWidth = 12;
    ctx.stroke();

    ctx.beginPath();
    ctx.arc(center, center, radius + 14, 0, 2 * Math.PI);
    ctx.strokeStyle = "#00f0ff";
    ctx.lineWidth = 2;
    ctx.stroke();
    ctx.restore();

    if (count === 0) {
      ctx.save();
      ctx.beginPath();
      ctx.arc(center, center, radius, 0, 2 * Math.PI);
      ctx.fillStyle = "#140f28";
      ctx.fill();
      ctx.strokeStyle = "#ff0055";
      ctx.lineWidth = 4;
      ctx.stroke();

      ctx.fillStyle = "#c9cdd8";
      ctx.font = "bold 15px 'Russo One', sans-serif";
      ctx.textAlign = "center";
      ctx.fillText("ПУЛ ИГР ПУСТ", center, center - 10);
      ctx.font = "12px 'Montserrat', sans-serif";
      ctx.fillText("Настройте фильтры выше", center, center + 14);
      ctx.restore();
      return;
    }

    const arc = (2 * Math.PI) / count;
    const colors = [
      "#ff0055", "#00f0ff", "#ffe600", "#9d00ff", "#39ff14", 
      "#0066ff", "#ff5500", "#e91e63", "#00e676", "#ff007f",
      "#00e5ff", "#ffea00", "#d500f9", "#00c853", "#ff6d00", "#2979ff"
    ];

    ctx.save();
    ctx.translate(center, center);
    ctx.rotate(this.wheelAngle);

    for (let i = 0; i < count; i++) {
      const angle = i * arc;
      const game = slices[i];
      const color = colors[i % colors.length];

      // Draw Slice
      ctx.beginPath();
      ctx.moveTo(0, 0);
      ctx.arc(0, 0, radius, angle, angle + arc);
      ctx.lineTo(0, 0);
      ctx.fillStyle = color;
      ctx.fill();

      ctx.strokeStyle = "#07050e";
      ctx.lineWidth = 2;
      ctx.stroke();

      // Radial gradient overlay
      const grad = ctx.createRadialGradient(0, 0, 30, 0, 0, radius);
      grad.addColorStop(0, "rgba(0,0,0,0.1)");
      grad.addColorStop(1, "rgba(0,0,0,0.6)");
      ctx.fillStyle = grad;
      ctx.fill();

      // Text along slice
      ctx.save();
      ctx.rotate(angle + arc / 2);
      ctx.textAlign = "right";
      ctx.fillStyle = "#ffffff";
      ctx.font = (count > 12) ? "bold 12px 'Russo One', sans-serif" : "bold 14px 'Russo One', sans-serif";
      ctx.shadowColor = "rgba(0,0,0,0.95)";
      ctx.shadowBlur = 4;
      ctx.shadowOffsetX = 1;
      ctx.shadowOffsetY = 1;

      let title = game.title || "Game";
      const maxChars = (count > 12) ? 18 : 22;
      if (title.length > maxChars) {
        title = title.substring(0, maxChars - 2) + "..";
      }

      ctx.fillText(title, radius - 20, 5);
      ctx.restore();
    }

    // Outer rim tick dots
    for (let i = 0; i < count; i++) {
      const angle = i * arc;
      const x = (radius + 4) * Math.cos(angle);
      const y = (radius + 4) * Math.sin(angle);
      ctx.beginPath();
      ctx.arc(x, y, 3, 0, 2 * Math.PI);
      ctx.fillStyle = "#ffe600";
      ctx.fill();
    }

    ctx.restore();
  },

  spinWheel() {
    if (this.wheelIsSpinning) return;
    const allActive = this.getActiveWheelCandidates();
    if (allActive.length === 0) {
      this.showAlert("В пуле нет доступных игр для рандомайзера! Ослабьте фильтры или добавьте игры в бэклог.", "ПУЛ ПУСТ", "warning");
      return;
    }

    this.wheelIsSpinning = true;
    this.closeWinnerOverlay();

    const spinBtn = document.getElementById("wheel-main-spin-btn");
    const centerBtn = document.getElementById("wheel-center-btn");
    if (spinBtn) spinBtn.disabled = true;
    if (centerBtn) centerBtn.disabled = true;

    // Pick winning game fairly across all active candidates
    const winIndexInAll = Math.floor(Math.random() * allActive.length);
    const winnerGame = allActive[winIndexInAll];

    // Ensure winner is visible in the display slices
    let displaySlices = this.getWheelDisplaySliceCandidates();
    let winSlot = displaySlices.findIndex(g => g.id === winnerGame.id);
    if (winSlot === -1) {
      winSlot = Math.floor(Math.random() * displaySlices.length);
      displaySlices[winSlot] = winnerGame;
      // Re-order candidates so the slice displays winner
      this.wheelCandidates = [
        winnerGame,
        ...this.wheelCandidates.filter(g => g.id !== winnerGame.id)
      ];
      this.drawWheel();
      displaySlices = this.getWheelDisplaySliceCandidates();
      winSlot = displaySlices.findIndex(g => g.id === winnerGame.id);
      if (winSlot === -1) winSlot = 0;
    }

    const count = displaySlices.length;
    const arc = (2 * Math.PI) / count;

    const fullRotations = 7 + Math.floor(Math.random() * 3);
    const targetOffset = (1.5 * Math.PI) - ((winSlot + 0.5) * arc);
    
    const startAngle = this.wheelAngle % (2 * Math.PI);
    const totalRotation = (fullRotations * 2 * Math.PI) + (targetOffset - startAngle);
    const finalAngle = this.wheelAngle + totalRotation;

    const duration = 4600;
    const startTime = performance.now();
    let lastTickSlice = -1;

    const pointerEl = document.getElementById("wheel-pointer");

    const animate = (currentTime) => {
      const elapsed = currentTime - startTime;
      const progress = Math.min(elapsed / duration, 1);

      const easeOut = 1 - Math.pow(1 - progress, 5);
      const currentAngle = this.wheelAngle + totalRotation * easeOut;

      const normalizedCurrent = (currentAngle % (2 * Math.PI) + 2 * Math.PI) % (2 * Math.PI);
      const pointerAngle = (1.5 * Math.PI - normalizedCurrent + 2 * Math.PI) % (2 * Math.PI);
      const currentSlice = Math.floor(pointerAngle / arc);

      if (currentSlice !== lastTickSlice) {
        lastTickSlice = currentSlice;
        this.playTickSound(350 + (1 - progress) * 250);
        if (pointerEl) {
          pointerEl.classList.add("tick");
          setTimeout(() => pointerEl.classList.remove("tick"), 40);
        }
      }

      this.wheelAngle = currentAngle;
      this.drawWheel();

      if (progress < 1) {
        requestAnimationFrame(animate);
      } else {
        this.wheelAngle = finalAngle;
        this.drawWheel();
        this.wheelIsSpinning = false;
        if (spinBtn) spinBtn.disabled = false;
        if (centerBtn) centerBtn.disabled = false;

        this.playWinFanfare();
        this.showWinner(winnerGame);
      }
    };

    requestAnimationFrame(animate);
  },

  showWinner(game) {
    this.wheelWinner = game;
    const overlay = document.getElementById("wheel-winner-overlay");
    const titleEl = document.getElementById("winner-game-title");
    const posterImg = document.getElementById("winner-poster-img");
    const metaRow = document.getElementById("winner-meta-row");
    const playtimeEl = document.getElementById("winner-playtime-val");
    const notesBox = document.getElementById("winner-notes-box");
    const notesText = document.getElementById("winner-notes-text");

    if (!overlay) return;

    if (titleEl) titleEl.textContent = game.title;
    if (posterImg) {
      posterImg.src = game.cover_url || game.background_url || "";
    }

    if (metaRow) {
      metaRow.innerHTML = `
        <span class="comic-badge badge-platform">${game.platform || "PC"}</span>
        <span class="comic-badge badge-priority">🔥 ${this.formatPriority(game.priority)}</span>
        <span style="color:#fff; font-weight:700;">${this.escapeHtml(game.genres || "Экшен")}</span>
        ${game.release_date ? `<span>• ${game.release_date.split("-")[0]}</span>` : ""}
        ${game.rawg_rating ? `<span style="color:var(--sv-yellow); font-family:var(--font-comic);">⭐ ${game.rawg_rating.toFixed(1)}</span>` : ""}
      `;
    }

    if (playtimeEl) {
      playtimeEl.textContent = game.playtime_main ? `~${game.playtime_main} часов (Сюжет)` : `Не указано`;
    }

    if (notesBox && notesText) {
      if (game.notes) {
        notesText.textContent = game.notes;
        notesBox.style.display = "block";
      } else {
        notesBox.style.display = "none";
      }
    }

    overlay.style.display = "flex";
  },

  startPlayingFromWinner() {
    if (this.wheelWinner) {
      const winId = this.wheelWinner.id;
      this.closeWinnerOverlay();
      this.closeModal("wheel-modal");
      this.startPlaying(winId);
    }
  },

  openTrailerFromWinner() {
    if (this.wheelWinner) {
      const g = this.wheelWinner;
      this.closeModal("wheel-modal");
      this.openTrailerModal(g.id, g.title, g.cover_url || g.background_url || "", g.platform || "", g.genres || "");
    }
  },

  spinWheelAgain() {
    this.closeWinnerOverlay();
    this.spinWheel();
  },

  closeWinnerOverlay() {
    const overlay = document.getElementById("wheel-winner-overlay");
    if (overlay) overlay.style.display = "none";
  },

  // --- RAWG METADATA & COVER ENRICHER ---
  async autoFillModalFromRawg() {
    const titleInput = document.getElementById('form-title');
    const title = titleInput ? titleInput.value.trim() : '';
    if (!title) {
      this.showAlert('Сначала введите название игры для поиска в RAWG.', 'ВВЕДИТЕ НАЗВАНИЕ', 'warning');
      return;
    }

    this.showToast(`🔍 Поиск «${title}» в RAWG...`, 'info');
    try {
      const res = await fetch(`/api/rawg/search?query=${encodeURIComponent(title)}`);
      const data = await res.json();
      if (!data.results || data.results.length === 0) {
        this.showAlert(`В RAWG ничего не найдено по запросу «${title}».`, 'НЕ НАЙДЕНО', 'warning');
        return;
      }

      const item = data.results[0];
      const coverInput = document.getElementById('form-cover-url');
      const playtimeInput = document.getElementById('form-playtime-main');
      const releaseInput = document.getElementById('form-release-date');
      const devInput = document.getElementById('form-developer');

      if (coverInput && item.cover_url) coverInput.value = item.cover_url;
      if (playtimeInput && item.playtime_main) playtimeInput.value = item.playtime_main;
      if (releaseInput && item.release_date) releaseInput.value = item.release_date;
      if (devInput && item.developer) devInput.value = item.developer;
      if (item.genres) this.setModalGenres(item.genres);

      this.showToast(`Данные и обложка для «${item.title}» успешно загружены!`, 'success');
    } catch (e) {
      this.showAlert(e.message, 'ОШИБКА RAWG', 'error');
    }
  },

  async startBulkRawgEnrichment(status = null) {
    const hasRawg = this.settings.rawg_configured || this.settings.is_rawg_configured || (this.settings.rawg_api_key && this.settings.rawg_api_key.trim());
    if (!hasRawg) {
      this.showAlert('Для авто-загрузки обложек укажите бесплатный ключ RAWG API в Настройках.', 'ТРЕБУЕТСЯ RAWG API КЛЮЧ', 'warning');
      return;
    }

    const countRes = await fetch(`/api/rawg/missing-count${status ? '?status=' + status : ''}`);
    const countData = await countRes.json();
    const totalMissing = countData.missing_count || 0;

    if (totalMissing === 0) {
      this.showAlert('У всех игр в этом разделе уже есть обложки!', 'ВСЁ ЗАГРУЖЕНО', 'success');
      return;
    }

    const confirmed = await this.showConfirm({
      title: '🖼️ АВТО-ЗАГРУЗКА ОБЛОЖЕК',
      message: `Найдено <strong>${totalMissing} игр</strong> без обложек. Запустить автоматический поиск и подтягивание постеров, жанров и времени сюжета через RAWG API?`,
      confirmText: '⚡ Запустить авто-поиск',
      type: 'info'
    });
    if (!confirmed) return;

    this.isEnriching = true;
    const modal = document.getElementById('enrich-modal');
    const logBox = document.getElementById('enrich-log-box');
    const progressBar = document.getElementById('enrich-progress-bar');
    const countsLabel = document.getElementById('enrich-counts-label');
    const percentLabel = document.getElementById('enrich-percent-label');
    const stopBtn = document.getElementById('enrich-stop-btn');
    const doneBtn = document.getElementById('enrich-done-btn');

    if (modal) modal.classList.add('open');
    if (logBox) logBox.innerHTML = '<div>🚀 Запуск авто-подтягивания метаданных...</div>';
    if (stopBtn) stopBtn.style.display = 'inline-flex';
    if (doneBtn) doneBtn.style.display = 'none';

    let processedSoFar = 0;
    const totalToProcess = totalMissing;

    while (this.isEnriching) {
      try {
        const res = await fetch(`/api/rawg/bulk-enrich?batch_size=10${status ? '&status=' + status : ''}`, {
          method: 'POST'
        });
        const data = await res.json();

        if (!data.success) {
          if (logBox) logBox.innerHTML += `<div style="color:var(--sv-red);">❌ Ошибка: ${data.error || data.message}</div>`;
          break;
        }

        processedSoFar += data.processed_count;
        const currentPercent = Math.min(100, Math.round((processedSoFar / totalToProcess) * 100));

        if (progressBar) progressBar.style.width = `${currentPercent}%`;
        if (countsLabel) countsLabel.textContent = `Обработано: ${processedSoFar} / ${totalToProcess}`;
        if (percentLabel) percentLabel.textContent = `${currentPercent}%`;

        if (logBox) {
          logBox.innerHTML += `<div style="color:var(--sv-green);">✅ Найдено обложек в пачке: +${data.enriched_count}</div>`;
          logBox.scrollTop = logBox.scrollHeight;
        }

        if (!data.has_more || processedSoFar >= totalToProcess || data.processed_count === 0) {
          if (logBox) logBox.innerHTML += `<div style="color:var(--sv-cyan); font-weight:800; margin-top:8px;">🎉 Синхронизация завершена!</div>`;
          break;
        }
      } catch (err) {
        if (logBox) logBox.innerHTML += `<div style="color:var(--sv-red);">Сетевая ошибка: ${err.message}</div>`;
        break;
      }
    }

    this.isEnriching = false;
    if (stopBtn) stopBtn.style.display = 'none';
    if (doneBtn) doneBtn.style.display = 'inline-flex';
    await this.refreshAllData();
  },

  stopBulkEnrichment() {
    this.isEnriching = false;
    this.closeModal('enrich-modal');
    this.refreshAllData();
  },

  // --- HELPERS ---
  formatPriority(p) {
    const map = { urgent: '🔥 Срочно', high: '⚡ Высокий', medium: '⭐ Средний', low: '💤 Низкий' };
    return map[p] || 'Средний';
  },

  formatStatus(s) {
    const map = { playing: 'Сейчас играю', backlog: 'Бэклог', wishlist: 'Вишлист', completed: 'Пройдено', paused: 'Пауза' };
    return map[s] || s;
  },

  escapeHtml(str) {
    if (!str) return '';
    return String(str).replace(/[&<>'"]/g, tag => ({
      '&': '&amp;', '<': '&lt;', '>': '&gt;', "'": '&#39;', '"': '&quot;'
    }[tag] || tag));
  },

  escapeJs(str) {
    if (!str) return '';
    return String(str).replace(/'/g, "\\'").replace(/"/g, '\\"');
  },

  formatMarkdown(text) {
    if (!text) return '';
    let out = this.escapeHtml(text);
    out = out.replace(/\*\*(.*?)\*\*/g, '<strong>$1</strong>');
    out = out.replace(/\*(.*?)\*/g, '<em>$1</em>');
    out = out.replace(/\n/g, '<br>');
    return out;
  }
};

// Initialize app when DOM is ready
document.addEventListener('DOMContentLoaded', () => {
  app.init();
});
