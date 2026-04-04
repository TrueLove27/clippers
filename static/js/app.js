/**
 * Dashboard — sidebar nav, drag-and-drop, downloads, AI clipping, library.
 */
(function () {
  // ---- Sidebar nav switching ------------------------------------------------
  const navItems = document.querySelectorAll('.nav-item[data-tab]');
  const panels   = document.querySelectorAll('.tab-panel');

  function activateTab(btn) {
    navItems.forEach(n => n.classList.remove('active'));
    btn.classList.add('active');
    const target = btn.dataset.tab;
    panels.forEach(p => {
      p.classList.toggle('active', p.id === 'panel-' + target);
    });
  }
  navItems.forEach(btn => btn.addEventListener('click', () => activateTab(btn)));

  // ---- Drag and drop: video cards -> URL textarea ---------------------------
  const urlBox = document.getElementById('urlBox');

  document.querySelectorAll('.vid-card[draggable]').forEach(card => {
    card.addEventListener('dragstart', e => {
      e.dataTransfer.setData('text/plain', card.dataset.url);
      e.dataTransfer.effectAllowed = 'copy';
      card.classList.add('dragging');
    });
    card.addEventListener('dragend', () => card.classList.remove('dragging'));
  });

  if (urlBox) {
    urlBox.addEventListener('dragover', e => { e.preventDefault(); e.dataTransfer.dropEffect = 'copy'; urlBox.classList.add('drop-hover'); });
    urlBox.addEventListener('dragleave', () => urlBox.classList.remove('drop-hover'));
    urlBox.addEventListener('drop', e => {
      e.preventDefault();
      urlBox.classList.remove('drop-hover');
      const url = e.dataTransfer.getData('text/plain');
      if (url && /^https?:\/\//i.test(url)) {
        const cur = urlBox.value.trim();
        urlBox.value = cur ? cur + '\n' + url : url;
        const dlNav = document.querySelector('[data-tab="download"]');
        if (dlNav) dlNav.click();
      }
    });
  }

  // ---- Helpers --------------------------------------------------------------
  async function post(url, body) {
    const r = await fetch(url, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });
    return r.json();
  }
  function log(msg) {
    const el = document.getElementById('dlLog');
    el.textContent += msg + '\n';
    el.scrollTop = el.scrollHeight;
  }
  function sleep(ms) { return new Promise(r => setTimeout(r, ms)); }
  function escHtml(s) { const d = document.createElement('div'); d.textContent = s; return d.innerHTML; }
  function fmtDur(s) {
    s = Math.round(s);
    const m = Math.floor(s / 60), sec = s % 60;
    return m + ':' + String(sec).padStart(2, '0');
  }

  // ---- Download -------------------------------------------------------------
  const dlBtn = document.getElementById('dlBtn');
  let downloadCount = 0, clipCount = 0;
  dlBtn.addEventListener('click', startDownload);

  async function startDownload() {
    const raw = document.getElementById('urlBox').value.trim();
    const urls = raw.split('\n').map(l => l.trim()).filter(l => /^https?:\/\//i.test(l));
    if (!urls.length) { alert('Paste at least one URL.'); return; }

    const dir = document.getElementById('dlDir').value.trim();
    const playlist = document.getElementById('playlistCheck').checked;

    dlBtn.classList.add('loading'); dlBtn.disabled = true;
    document.getElementById('dlLog').textContent = '';
    document.getElementById('dlProgress').innerHTML = '';
    log('Starting download...');

    const res = await post('/api/download', { urls, directory: dir, playlist });
    if (!res.ok) { log('Error: ' + res.error); dlBtn.classList.remove('loading'); dlBtn.disabled = false; return; }

    renderProgressCards(urls);
    pollProgress(res.task_id, urls.length);
  }

  function renderProgressCards(urls) {
    document.getElementById('dlProgress').innerHTML = urls.map((u, i) => `
      <div class="dl-item" id="dl-item-${i}">
        <span class="dl-item__url">${escHtml(u)}</span>
        <div class="progress-bar"><div class="progress-bar__fill" id="dl-fill-${i}"></div></div>
        <span class="dl-item__status" id="dl-status-${i}">Queued</span>
      </div>`).join('');
  }

  async function pollProgress(tid, count) {
    let done = false;
    while (!done) {
      await sleep(800);
      try {
        const res = await (await fetch('/api/download/progress/' + tid)).json();
        if (!res.ok) { log('Poll error: ' + res.error); break; }
        res.items.forEach((item, i) => {
          const fill = document.getElementById('dl-fill-' + i);
          const status = document.getElementById('dl-status-' + i);
          if (fill) fill.style.width = item.progress + '%';
          if (status) {
            if (item.status === 'done') status.textContent = 'Done';
            else if (item.status === 'error') { status.textContent = 'Error'; status.classList.add('error'); log('Error: ' + item.error); }
            else if (item.status === 'downloading') status.textContent = Math.round(item.progress) + '%';
            else status.textContent = 'Queued';
          }
        });
        if (res.status === 'done') {
          done = true;
          downloadCount += count;
          updateStats();
          log('All downloads finished.');
        }
      } catch { log('Network error.'); break; }
    }
    dlBtn.classList.remove('loading'); dlBtn.disabled = false;
  }

  // ====================================================================
  //  AI CLIPPING — OpusClip-style pipeline
  // ====================================================================
  const clipInput   = document.getElementById('clipInput');
  const inputBtn    = document.getElementById('clipInputBtn');
  const phaseInput  = document.getElementById('clipPhaseInput');
  const phaseProc   = document.getElementById('clipPhaseProcessing');
  const phaseResult = document.getElementById('clipPhaseResults');
  const setupWizard = document.getElementById('clipSetupWizard');

  let currentAIClips = [];

  // On load, check if API key is configured
  (async function checkSetup() {
    try {
      const res = await (await fetch('/api/settings')).json();
      if (res.ok && !res.settings.has_api_key) {
        setupWizard.style.display = '';
      }
    } catch {}
  })();

  // Setup wizard save
  document.getElementById('setupSaveBtn').addEventListener('click', async () => {
    const key = document.getElementById('setupApiKey').value.trim();
    if (!key) { alert('Please enter an API key.'); return; }
    const res = await post('/api/settings', { groq_api_key: key });
    if (res.ok) {
      setupWizard.style.display = 'none';
    }
  });

  // Generate Clips button
  inputBtn.addEventListener('click', () => {
    const url = clipInput.value.trim();
    if (!url) { alert('Paste a YouTube URL first.'); return; }
    startAIClipping(url);
  });

  // Enter key in input
  clipInput.addEventListener('keydown', e => {
    if (e.key === 'Enter') inputBtn.click();
  });

  async function startAIClipping(url) {
    // Switch to processing phase
    phaseInput.style.display = 'none';
    phaseResult.style.display = 'none';
    phaseProc.style.display = '';

    resetStepper();

    const res = await post('/api/ai/clip', { url });
    if (!res.ok) {
      alert(res.error || 'Failed to start.');
      phaseProc.style.display = 'none';
      phaseInput.style.display = '';
      return;
    }

    pollAIProgress(res.task_id);
  }

  function resetStepper() {
    for (let i = 1; i <= 4; i++) {
      const step = document.getElementById('aiStep' + i);
      step.classList.remove('active', 'done');
    }
    document.getElementById('aiStep1').classList.add('active');
    document.getElementById('aiProgressFill').style.width = '0%';
    document.getElementById('aiProgressPct').textContent = '0%';
  }

  const stepMap = { downloading: 1, transcribing: 2, analyzing: 3, extracting: 4 };

  async function pollAIProgress(tid) {
    let done = false;
    while (!done) {
      await sleep(1000);
      try {
        const res = await (await fetch('/api/ai/clip/progress/' + tid)).json();
        if (!res.ok) break;

        // Update stepper
        const currentStep = stepMap[res.step] || 1;
        for (let i = 1; i <= 4; i++) {
          const el = document.getElementById('aiStep' + i);
          el.classList.remove('active', 'done');
          if (i < currentStep) el.classList.add('done');
          else if (i === currentStep) el.classList.add('active');
        }

        // Update message for current step
        const msgEl = document.getElementById('aiStepMsg' + currentStep);
        if (msgEl && res.message) msgEl.textContent = res.message;

        // Progress bar
        document.getElementById('aiProgressFill').style.width = res.progress + '%';
        document.getElementById('aiProgressPct').textContent = res.progress + '%';

        if (res.status === 'done') {
          done = true;
          for (let i = 1; i <= 4; i++) {
            document.getElementById('aiStep' + i).classList.remove('active');
            document.getElementById('aiStep' + i).classList.add('done');
          }
          await sleep(800);
          showResults(res.clips || []);
        } else if (res.status === 'error') {
          done = true;
          alert('Error: ' + (res.error || 'Pipeline failed.'));
          phaseProc.style.display = 'none';
          phaseInput.style.display = '';
        }
      } catch {
        done = true;
        phaseProc.style.display = 'none';
        phaseInput.style.display = '';
      }
    }
  }

  // ---- Results grid ---------------------------------------------------------
  function showResults(clips) {
    currentAIClips = clips;
    phaseProc.style.display = 'none';
    phaseResult.style.display = '';

    const grid = document.getElementById('clipResultsGrid');
    grid.innerHTML = clips.map((c, i) => {
      if (!c.ok) return '';
      const scoreClass = c.score >= 8 ? 'high' : c.score >= 5 ? 'med' : 'low';
      return `
        <div class="clip-card glass" data-idx="${i}">
          <div class="clip-card__thumb" data-idx="${i}">
            <video src="/api/files/serve?path=${encodeURIComponent(c.path)}" muted preload="metadata"></video>
            <div class="clip-card__play">
              <svg width="44" height="44" viewBox="0 0 24 24" fill="none" stroke="#00d4ff" stroke-width="2"><polygon points="5 3 19 12 5 21" fill="rgba(0,212,255,0.3)"/></svg>
            </div>
            <span class="clip-card__score clip-card__score--${scoreClass}">${c.score}/10</span>
            <span class="clip-card__dur">${fmtDur(c.duration)}</span>
          </div>
          <div class="clip-card__body">
            <p class="clip-card__title">${escHtml(c.title)}</p>
            <p class="clip-card__summary">${escHtml(c.summary)}</p>
            <div class="clip-card__actions">
              <button class="btn btn--xs btn--primary clip-card__dl" data-idx="${i}">Download</button>
              <button class="btn btn--xs btn--outline clip-card__cap" data-idx="${i}">Add Captions</button>
            </div>
          </div>
        </div>`;
    }).join('');

    // Thumb click -> bubble player
    grid.querySelectorAll('.clip-card__thumb').forEach(thumb => {
      thumb.addEventListener('click', () => {
        const c = currentAIClips[parseInt(thumb.dataset.idx)];
        if (c && c.path) openBubblePlayer(c.path, c.title);
      });
    });

    // Download buttons
    grid.querySelectorAll('.clip-card__dl').forEach(btn => {
      btn.addEventListener('click', () => {
        const c = currentAIClips[parseInt(btn.dataset.idx)];
        if (c && c.path) {
          const a = document.createElement('a');
          a.href = '/api/files/serve?path=' + encodeURIComponent(c.path);
          a.download = c.title.replace(/[^a-zA-Z0-9 _-]/g, '_') + '.mp4';
          a.click();
        }
      });
    });

    // Caption buttons
    grid.querySelectorAll('.clip-card__cap').forEach(btn => {
      btn.addEventListener('click', () => {
        const idx = parseInt(btn.dataset.idx);
        openCaptionEditor(idx);
      });
    });

    clipCount += clips.filter(c => c.ok).length;
    updateStats();
  }

  // "New Video" button in results header
  document.getElementById('aiNewClipBtn').addEventListener('click', () => {
    phaseResult.style.display = 'none';
    phaseInput.style.display = '';
    clipInput.value = '';
  });

  // ---- Caption editor -------------------------------------------------------
  const captionModal   = document.getElementById('captionModal');
  const captionClose   = document.getElementById('captionModalClose');
  const captionBurnBtn = document.getElementById('captionBurnBtn');
  const captionStatus  = document.getElementById('captionStatus');
  let captionClipIdx   = -1;
  let captionStyle     = 'neon';

  function openModal(modal) {
    modal.classList.add('open');
    requestAnimationFrame(() => modal.classList.add('visible'));
  }
  function closeModal(modal) {
    modal.classList.remove('visible');
    setTimeout(() => modal.classList.remove('open'), 400);
  }

  function openCaptionEditor(idx) {
    captionClipIdx = idx;
    const c = currentAIClips[idx];
    document.getElementById('captionClipTitle').textContent = c ? c.title : '';
    captionStatus.textContent = '';
    captionStatus.className = 'status-msg';
    openModal(captionModal);
  }

  captionClose.addEventListener('click', () => closeModal(captionModal));
  captionModal.querySelector('.modal-backdrop').addEventListener('click', () => closeModal(captionModal));

  document.querySelectorAll('.caption-style-opt').forEach(opt => {
    opt.addEventListener('click', () => {
      document.querySelectorAll('.caption-style-opt').forEach(o => o.classList.remove('active'));
      opt.classList.add('active');
      captionStyle = opt.dataset.style;
    });
  });

  captionBurnBtn.addEventListener('click', async () => {
    const c = currentAIClips[captionClipIdx];
    if (!c || !c.path || !c.words || !c.words.length) {
      captionStatus.textContent = 'No word data available for this clip.';
      captionStatus.className = 'status-msg error';
      return;
    }

    captionStatus.textContent = 'Burning captions...';
    captionStatus.className = 'status-msg';
    captionBurnBtn.disabled = true;

    const res = await post('/api/ai/caption', {
      clip_path: c.path,
      words: c.words,
      style: captionStyle,
    });

    captionBurnBtn.disabled = false;

    if (res.ok) {
      captionStatus.textContent = 'Saved: ' + res.path;
      captionStatus.className = 'status-msg success';
    } else {
      captionStatus.textContent = res.error || 'Caption burn failed.';
      captionStatus.className = 'status-msg error';
    }
  });

  // ---- Settings modal -------------------------------------------------------
  const settingsModal = document.getElementById('settingsModal');
  const settingsClose = document.getElementById('settingsModalClose');

  document.getElementById('openSettingsBtn').addEventListener('click', async () => {
    // Load current settings
    try {
      const res = await (await fetch('/api/settings')).json();
      if (res.ok) {
        const s = res.settings;
        document.getElementById('setModel').value = s.model || 'llama-3.3-70b-versatile';
        document.getElementById('setNumClips').value = s.num_clips || 5;
        document.getElementById('setMinDur').value = s.clip_duration_min || 30;
        document.getElementById('setMaxDur').value = s.clip_duration_max || 90;
        document.getElementById('setApiKey').value = '';
        document.getElementById('setApiKey').placeholder = s.has_api_key ? '••••••••  (key saved)' : 'gsk_...';
      }
    } catch {}
    openModal(settingsModal);
  });

  settingsClose.addEventListener('click', () => closeModal(settingsModal));
  settingsModal.querySelector('.modal-backdrop').addEventListener('click', () => closeModal(settingsModal));

  document.getElementById('settingsSaveBtn').addEventListener('click', async () => {
    const updates = {
      model: document.getElementById('setModel').value,
      num_clips: parseInt(document.getElementById('setNumClips').value) || 5,
      clip_duration_min: parseInt(document.getElementById('setMinDur').value) || 30,
      clip_duration_max: parseInt(document.getElementById('setMaxDur').value) || 90,
    };
    const key = document.getElementById('setApiKey').value.trim();
    if (key) updates.groq_api_key = key;

    const statusEl = document.getElementById('settingsStatus');
    statusEl.textContent = 'Saving...';
    statusEl.className = 'status-msg';

    const res = await post('/api/settings', updates);
    if (res.ok) {
      statusEl.textContent = 'Settings saved!';
      statusEl.className = 'status-msg success';
      if (key) {
        setupWizard.style.display = 'none';
        document.getElementById('setApiKey').value = '';
        document.getElementById('setApiKey').placeholder = '••••••••  (key saved)';
      }
      setTimeout(() => { statusEl.textContent = ''; }, 2000);
    } else {
      statusEl.textContent = 'Failed to save.';
      statusEl.className = 'status-msg error';
    }
  });

  // ---- Library --------------------------------------------------------------
  document.getElementById('refreshLib').addEventListener('click', loadLibrary);
  document.addEventListener('DOMContentLoaded', loadLibrary);

  async function loadLibrary() {
    const grid = document.getElementById('fileGrid');
    const empty = document.getElementById('libEmpty');
    try {
      const res = await (await fetch('/api/files')).json();
      if (!res.ok || !res.files.length) { grid.innerHTML = ''; empty.style.display = ''; updateStats(0); return; }
      empty.style.display = 'none';
      updateStats(res.files.length);
      grid.innerHTML = res.files.map((f, i) => `
        <div class="file-card glass">
          <button class="file-card__play" data-idx="${i}" title="Play in bubble">
            <svg width="18" height="18" fill="currentColor" viewBox="0 0 24 24"><polygon points="5 3 19 12 5 21"/></svg>
          </button>
          <div class="file-card__info">
            <p class="file-card__name" title="${escHtml(f.path)}">${escHtml(f.name)}</p>
            <p class="file-card__meta">${f.size_mb} MB &middot; ${f.type}</p>
          </div>
          <button class="btn btn--xs btn--outline" onclick="navigator.clipboard.writeText('${escHtml(f.path).replace(/\\/g, '\\\\')}')">Copy path</button>
        </div>`).join('');

      grid.querySelectorAll('.file-card__play').forEach(btn => {
        btn.addEventListener('click', () => {
          const f = res.files[parseInt(btn.dataset.idx)];
          openBubblePlayer(f.path, f.name);
        });
      });
    } catch { grid.innerHTML = ''; empty.style.display = ''; }
  }

  // ---- Bubble video player --------------------------------------------------
  const bubble      = document.getElementById('bubblePlayer');
  const bubbleVideo = document.getElementById('bubbleVideo');
  const bubbleTitle = document.getElementById('bubbleTitle');
  const bubbleDrag  = document.getElementById('bubbleDragBar');
  const bubbleClose = document.getElementById('bubbleClose');
  const bubbleMin   = document.getElementById('bubbleMin');
  const bubbleMini  = document.getElementById('bubbleMiniView');

  function openBubblePlayer(filePath, fileName) {
    const src = '/api/files/serve?path=' + encodeURIComponent(filePath);
    bubbleVideo.src = src;
    bubbleVideo.load();
    bubbleVideo.play().catch(() => {});
    bubbleTitle.textContent = fileName || 'Now playing';
    bubble.classList.remove('minimized');
    bubble.classList.add('open');
    bubbleMini.style.display = 'none';
  }

  bubbleClose.addEventListener('click', () => {
    bubbleVideo.pause();
    bubbleVideo.removeAttribute('src');
    bubble.classList.remove('open', 'minimized');
  });

  bubbleMin.addEventListener('click', () => {
    bubble.classList.toggle('minimized');
    bubbleMini.style.display = bubble.classList.contains('minimized') ? 'flex' : 'none';
  });

  bubble.addEventListener('click', e => {
    if (bubble.classList.contains('minimized') && e.target.closest('.bubble-player__mini')) {
      bubble.classList.remove('minimized');
      bubbleMini.style.display = 'none';
    }
  });

  let dragOffsetX = 0, dragOffsetY = 0, isDraggingBubble = false;
  bubbleDrag.addEventListener('mousedown', e => {
    isDraggingBubble = true;
    const rect = bubble.getBoundingClientRect();
    dragOffsetX = e.clientX - rect.left;
    dragOffsetY = e.clientY - rect.top;
    bubble.style.transition = 'none';
  });
  window.addEventListener('mousemove', e => {
    if (!isDraggingBubble) return;
    let x = e.clientX - dragOffsetX;
    let y = e.clientY - dragOffsetY;
    x = Math.max(0, Math.min(window.innerWidth - bubble.offsetWidth, x));
    y = Math.max(0, Math.min(window.innerHeight - bubble.offsetHeight, y));
    bubble.style.left = x + 'px';
    bubble.style.top  = y + 'px';
    bubble.style.right = 'auto';
    bubble.style.bottom = 'auto';
  });
  window.addEventListener('mouseup', () => {
    if (isDraggingBubble) {
      isDraggingBubble = false;
      bubble.style.transition = '';
    }
  });

  // ---- Stats ----------------------------------------------------------------
  function updateStats(fileCount) {
    const dl = document.getElementById('statDownloads');
    const cl = document.getElementById('statClips');
    const fi = document.getElementById('statFiles');
    if (dl) dl.textContent = downloadCount;
    if (cl) cl.textContent = clipCount;
    if (fi && fileCount !== undefined) fi.textContent = fileCount;
  }
})();
