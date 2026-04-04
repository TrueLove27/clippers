/* ==========================================================================
   Clippers — AI Reel Generator frontend
   ========================================================================== */

(() => {
  "use strict";

  /* ---- DOM refs ---- */
  const urlInput    = document.getElementById("urlInput");
  const generateBtn = document.getElementById("generateBtn");

  const phaseInput      = document.getElementById("phaseInput");
  const phaseProcessing = document.getElementById("phaseProcessing");
  const phaseResults    = document.getElementById("phaseResults");
  const setupWizard     = document.getElementById("setupWizard");

  const progressFill = document.getElementById("progressFill");
  const progressPct  = document.getElementById("progressPct");

  const reelsGrid   = document.getElementById("reelsGrid");
  const newVideoBtn = document.getElementById("newVideoBtn");

  const settingsModal = document.getElementById("settingsModal");
  const settingsClose = document.getElementById("settingsClose");
  const openSettings  = document.getElementById("openSettingsBtn");
  const settingsSave  = document.getElementById("settingsSaveBtn");

  const previewModal = document.getElementById("previewModal");
  const previewClose = document.getElementById("previewClose");
  const previewVideo = document.getElementById("previewVideo");
  const previewTitle = document.getElementById("previewTitle");
  const previewSummary = document.getElementById("previewSummary");
  const previewDownload = document.getElementById("previewDownload");

  /* ---- Helpers ---- */
  function fmtDur(s) {
    const m = Math.floor(s / 60);
    const sec = Math.floor(s % 60);
    return m > 0 ? `${m}:${String(sec).padStart(2, "0")}` : `0:${String(sec).padStart(2, "0")}`;
  }

  function openModal(el) {
    el.classList.add("open");
    requestAnimationFrame(() => el.classList.add("visible"));
  }
  function closeModal(el) {
    el.classList.remove("visible");
    setTimeout(() => el.classList.remove("open"), 450);
  }

  function show(el) { if (el) el.style.display = ""; }
  function hide(el) { if (el) el.style.display = "none"; }

  /* ---- Check API key on load ---- */
  async function checkSetup() {
    try {
      const r = await fetch("/api/settings");
      const d = await r.json();
      if (d.ok && !d.settings.has_api_key) {
        show(setupWizard);
      }
    } catch { /* ignore */ }
  }
  checkSetup();

  /* Setup wizard save */
  const setupSaveBtn = document.getElementById("setupSaveBtn");
  const setupApiKey  = document.getElementById("setupApiKey");

  if (setupSaveBtn) {
    setupSaveBtn.addEventListener("click", async () => {
      const key = setupApiKey.value.trim();
      if (!key) return;
      setupSaveBtn.textContent = "Saving...";
      const r = await fetch("/api/settings", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ groq_api_key: key }),
      });
      const d = await r.json();
      if (d.ok && d.has_api_key) {
        hide(setupWizard);
      }
      setupSaveBtn.textContent = "Save Key";
    });
  }

  /* ---- Generate reels ---- */
  if (generateBtn) {
    generateBtn.addEventListener("click", () => startGeneration());
  }
  if (urlInput) {
    urlInput.addEventListener("keydown", (e) => {
      if (e.key === "Enter") startGeneration();
    });
  }

  async function startGeneration() {
    const url = urlInput.value.trim();
    if (!url) { urlInput.focus(); return; }

    generateBtn.disabled = true;
    hide(phaseInput);
    show(phaseProcessing);
    hide(phaseResults);
    resetStepper();

    try {
      const r = await fetch("/api/generate", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ url }),
      });
      const d = await r.json();

      if (!d.ok) {
        alert(d.error || "Failed to start generation.");
        showInput();
        return;
      }

      pollProgress(d.task_id);
    } catch (err) {
      alert("Network error: " + err.message);
      showInput();
    }
  }

  function showInput() {
    show(phaseInput);
    hide(phaseProcessing);
    hide(phaseResults);
    generateBtn.disabled = false;
  }

  /* ---- Stepper ---- */
  const STEP_MAP = {
    downloading: 1,
    transcribing: 2,
    analyzing: 3,
    extracting: 4,
    captioning: 5,
    done: 5,
  };

  function resetStepper() {
    for (let i = 1; i <= 5; i++) {
      const el = document.getElementById("aiStep" + i);
      if (el) {
        el.classList.remove("active", "done");
        const msg = document.getElementById("aiMsg" + i);
        if (msg) msg.textContent = "";
      }
    }
    if (progressFill) progressFill.style.width = "0%";
    if (progressPct)  progressPct.textContent = "0%";
  }

  function updateStepper(step, message, progress) {
    const num = STEP_MAP[step] || 1;

    for (let i = 1; i <= 5; i++) {
      const el = document.getElementById("aiStep" + i);
      if (!el) continue;
      el.classList.remove("active", "done");
      if (i < num) el.classList.add("done");
      else if (i === num) el.classList.add("active");
    }

    const msgEl = document.getElementById("aiMsg" + num);
    if (msgEl && message) msgEl.textContent = message;

    if (progressFill) progressFill.style.width = progress + "%";
    if (progressPct)  progressPct.textContent = progress + "%";
  }

  /* ---- Polling ---- */
  function pollProgress(tid) {
    const interval = setInterval(async () => {
      try {
        const r = await fetch("/api/generate/progress/" + tid);
        const d = await r.json();

        if (!d.ok) {
          clearInterval(interval);
          alert(d.error || "Error fetching progress.");
          showInput();
          return;
        }

        updateStepper(d.step, d.message, d.progress);

        if (d.status === "done") {
          clearInterval(interval);
          setTimeout(() => showResults(d.reels || []), 600);
        } else if (d.status === "error") {
          clearInterval(interval);
          alert(d.error || "Generation failed.");
          showInput();
        }
      } catch {
        clearInterval(interval);
        showInput();
      }
    }, 1500);
  }

  /* ---- Results ---- */
  let currentReels = [];

  function showResults(reels) {
    currentReels = reels;
    hide(phaseInput);
    hide(phaseProcessing);
    show(phaseResults);
    generateBtn.disabled = false;

    reelsGrid.innerHTML = "";

    reels.forEach((reel, idx) => {
      if (!reel.ok) return;

      const scoreClass = reel.score >= 8 ? "high" : reel.score >= 5 ? "med" : "low";
      const serveUrl = "/api/reels/serve?path=" + encodeURIComponent(reel.path);

      const card = document.createElement("div");
      card.className = "reel-card";
      card.style.animationDelay = (idx * 0.08) + "s";

      card.innerHTML = `
        <div class="reel-card__thumb" data-idx="${idx}">
          <video src="${serveUrl}" muted preload="metadata"></video>
          <div class="reel-card__play">
            <svg width="40" height="40" viewBox="0 0 24 24" fill="rgba(255,255,255,0.9)"><polygon points="8,5 20,12 8,19"/></svg>
          </div>
          <span class="reel-card__score reel-card__score--${scoreClass}">${reel.score}/10</span>
          <span class="reel-card__dur">${fmtDur(reel.duration)}</span>
        </div>
        <div class="reel-card__body">
          <p class="reel-card__title">${reel.title}</p>
          <p class="reel-card__summary">${reel.summary}</p>
          <div class="reel-card__actions">
            <a class="btn btn--primary btn--sm" href="${serveUrl}" download="${reel.title}.mp4">
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="7 10 12 15 17 10"/><line x1="12" y1="15" x2="12" y2="3"/></svg>
              Download
            </a>
            <button class="btn btn--outline btn--sm" data-preview="${idx}">
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polygon points="5 3 19 12 5 21"/></svg>
              Preview
            </button>
          </div>
        </div>
      `;

      reelsGrid.appendChild(card);
    });

    /* Bind preview clicks */
    reelsGrid.querySelectorAll("[data-preview]").forEach((btn) => {
      btn.addEventListener("click", () => {
        const i = parseInt(btn.dataset.preview);
        openPreview(i);
      });
    });
    reelsGrid.querySelectorAll(".reel-card__thumb").forEach((el) => {
      el.addEventListener("click", () => {
        const i = parseInt(el.dataset.idx);
        openPreview(i);
      });
    });
  }

  /* ---- Preview modal ---- */
  function openPreview(idx) {
    const reel = currentReels[idx];
    if (!reel || !reel.path) return;
    const src = "/api/reels/serve?path=" + encodeURIComponent(reel.path);
    previewVideo.src = src;
    previewTitle.textContent = reel.title;
    previewSummary.textContent = reel.summary;
    previewDownload.href = src;
    previewDownload.download = reel.title + ".mp4";
    openModal(previewModal);
  }

  if (previewClose) {
    previewClose.addEventListener("click", () => {
      previewVideo.pause();
      previewVideo.src = "";
      closeModal(previewModal);
    });
  }
  if (previewModal) {
    previewModal.querySelector(".modal-backdrop")?.addEventListener("click", () => {
      previewVideo.pause();
      previewVideo.src = "";
      closeModal(previewModal);
    });
  }

  /* ---- New video button ---- */
  if (newVideoBtn) {
    newVideoBtn.addEventListener("click", () => {
      urlInput.value = "";
      showInput();
    });
  }

  /* ---- Settings modal ---- */
  if (openSettings) {
    openSettings.addEventListener("click", async () => {
      try {
        const r = await fetch("/api/settings");
        const d = await r.json();
        if (d.ok) {
          const s = d.settings;
          const setModel    = document.getElementById("setModel");
          const setNumClips = document.getElementById("setNumClips");
          const setMinDur   = document.getElementById("setMinDur");
          const setMaxDur   = document.getElementById("setMaxDur");

          if (setModel)    setModel.value    = s.model || "llama-3.3-70b-versatile";
          if (setNumClips) setNumClips.value  = s.num_clips || 8;
          if (setMinDur)   setMinDur.value    = s.clip_duration_min || 15;
          if (setMaxDur)   setMaxDur.value    = s.clip_duration_max || 25;

          /* Set active caption style */
          const stylePicker = document.getElementById("captionStylePicker");
          if (stylePicker && s.caption_style) {
            stylePicker.querySelectorAll(".caption-style-opt").forEach((b) => {
              b.classList.toggle("active", b.dataset.style === s.caption_style);
            });
          }
        }
      } catch { /* ignore */ }
      openModal(settingsModal);
    });
  }

  if (settingsClose) {
    settingsClose.addEventListener("click", () => closeModal(settingsModal));
  }
  if (settingsModal) {
    settingsModal.querySelector(".modal-backdrop")?.addEventListener("click", () => closeModal(settingsModal));
  }

  /* Caption style toggle */
  const captionPicker = document.getElementById("captionStylePicker");
  if (captionPicker) {
    captionPicker.addEventListener("click", (e) => {
      const opt = e.target.closest(".caption-style-opt");
      if (!opt) return;
      captionPicker.querySelectorAll(".caption-style-opt").forEach((b) => b.classList.remove("active"));
      opt.classList.add("active");
    });
  }

  /* Save settings */
  if (settingsSave) {
    settingsSave.addEventListener("click", async () => {
      const apiKey   = document.getElementById("setApiKey")?.value.trim();
      const model    = document.getElementById("setModel")?.value;
      const numClips = parseInt(document.getElementById("setNumClips")?.value || "8");
      const minDur   = parseInt(document.getElementById("setMinDur")?.value || "15");
      const maxDur   = parseInt(document.getElementById("setMaxDur")?.value || "25");
      const activeStyle = captionPicker?.querySelector(".caption-style-opt.active");
      const style = activeStyle?.dataset.style || "neon";

      const payload = {
        model,
        num_clips: numClips,
        clip_duration_min: minDur,
        clip_duration_max: maxDur,
        caption_style: style,
      };
      if (apiKey) payload.groq_api_key = apiKey;

      const status = document.getElementById("settingsStatus");
      settingsSave.textContent = "Saving...";

      try {
        const r = await fetch("/api/settings", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(payload),
        });
        const d = await r.json();
        if (d.ok) {
          if (status) { status.textContent = "Saved!"; status.className = "status-msg success"; }
          if (d.has_api_key) hide(setupWizard);
        } else {
          if (status) { status.textContent = "Error saving."; status.className = "status-msg error"; }
        }
      } catch {
        if (status) { status.textContent = "Network error."; status.className = "status-msg error"; }
      }
      settingsSave.textContent = "Save Settings";
      setTimeout(() => { if (status) status.textContent = ""; }, 3000);
    });
  }

})();
