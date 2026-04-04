/**
 * TimeDial — draggable circular time picker.
 * Usage: new TimeDial(containerEl, { label, maxSeconds, initial, onChange })
 */
class TimeDial {
  constructor(container, opts = {}) {
    this.maxSeconds  = opts.maxSeconds  || 600;
    this.seconds     = opts.initial     || 0;
    this.label       = opts.label       || 'TIME';
    this.onChange     = opts.onChange    || (() => {});
    this.color1      = opts.color1      || '#00d4ff';
    this.color2      = opts.color2      || '#7b2ff7';
    this.dragging    = false;

    this.R      = 80;
    this.CX     = 100;
    this.CY     = 100;
    this.CIRCUM = 2 * Math.PI * this.R;

    this._build(container);
    this._bind();
    this._update();
  }

  _build(container) {
    const uid = 'td' + Math.random().toString(36).slice(2, 8);
    container.innerHTML = `
      <div class="dial" data-dial="${uid}">
        <svg class="dial__svg" viewBox="0 0 200 200">
          <defs>
            <linearGradient id="${uid}_g" x1="0" y1="0" x2="200" y2="200">
              <stop offset="0%" stop-color="${this.color1}"/>
              <stop offset="100%" stop-color="${this.color2}"/>
            </linearGradient>
            <filter id="${uid}_glow">
              <feGaussianBlur stdDeviation="4" result="blur"/>
              <feMerge><feMergeNode in="blur"/><feMergeNode in="SourceGraphic"/></feMerge>
            </filter>
          </defs>
          <!-- Track -->
          <circle cx="${this.CX}" cy="${this.CY}" r="${this.R}"
                  stroke="rgba(255,255,255,0.06)" stroke-width="10" fill="none"/>
          <!-- Tick marks -->
          ${this._ticks()}
          <!-- Arc -->
          <circle class="dial__arc" cx="${this.CX}" cy="${this.CY}" r="${this.R}"
                  stroke="url(#${uid}_g)" stroke-width="10" fill="none"
                  stroke-linecap="round"
                  stroke-dasharray="${this.CIRCUM}"
                  stroke-dashoffset="${this.CIRCUM}"
                  transform="rotate(-90 ${this.CX} ${this.CY})"/>
          <!-- Handle -->
          <circle class="dial__handle" cx="${this.CX}" cy="${this.CY - this.R}" r="13"
                  fill="${this.color1}" filter="url(#${uid}_glow)" style="cursor:grab"/>
          <!-- Center display -->
          <text class="dial__time" x="${this.CX}" y="${this.CY - 4}"
                text-anchor="middle" dominant-baseline="middle"
                fill="#fff" font-size="26" font-family="'Syne','Space Grotesk',sans-serif" font-weight="700">00:00</text>
          <text class="dial__label" x="${this.CX}" y="${this.CY + 22}"
                text-anchor="middle" fill="rgba(136,146,164,0.8)" font-size="11"
                font-family="'Space Grotesk',sans-serif" letter-spacing="0.08em">${this.label}</text>
        </svg>
        <div class="dial__range">
          <button class="dial__range-btn" data-dir="-1">&minus;</button>
          <span class="dial__range-val">${this._rangeLabel()}</span>
          <button class="dial__range-btn" data-dir="1">+</button>
        </div>
      </div>`;

    this.el       = container.querySelector('.dial');
    this.svg      = this.el.querySelector('.dial__svg');
    this.arc      = this.el.querySelector('.dial__arc');
    this.handle   = this.el.querySelector('.dial__handle');
    this.timeText = this.el.querySelector('.dial__time');
    this.rangeVal = this.el.querySelector('.dial__range-val');
  }

  _ticks() {
    let out = '';
    for (let i = 0; i < 12; i++) {
      const angle = (i / 12) * 360 - 90;
      const rad   = angle * Math.PI / 180;
      const x1 = this.CX + (this.R + 14) * Math.cos(rad);
      const y1 = this.CY + (this.R + 14) * Math.sin(rad);
      const x2 = this.CX + (this.R + 8) * Math.cos(rad);
      const y2 = this.CY + (this.R + 8) * Math.sin(rad);
      out += `<line x1="${x1}" y1="${y1}" x2="${x2}" y2="${y2}" stroke="rgba(255,255,255,0.12)" stroke-width="1.5"/>`;
    }
    return out;
  }

  _bind() {
    const onStart = e => { e.preventDefault(); this.dragging = true; this.handle.style.cursor = 'grabbing'; this._onMove(e); };
    const onMove  = e => { if (this.dragging) this._onMove(e); };
    const onEnd   = () => { this.dragging = false; this.handle.style.cursor = 'grab'; };

    this.svg.addEventListener('mousedown', onStart);
    window.addEventListener('mousemove', onMove);
    window.addEventListener('mouseup', onEnd);
    this.svg.addEventListener('touchstart', e => onStart(e.touches[0]), { passive: false });
    window.addEventListener('touchmove', e => { if (this.dragging) { e.preventDefault(); this._onMove(e.touches[0]); } }, { passive: false });
    window.addEventListener('touchend', onEnd);

    this.el.querySelectorAll('.dial__range-btn').forEach(btn => {
      btn.addEventListener('click', () => {
        const dir = parseInt(btn.dataset.dir);
        const scales = [60, 120, 300, 600, 1800, 3600];
        let idx = scales.indexOf(this.maxSeconds);
        if (idx < 0) idx = 3;
        idx = Math.max(0, Math.min(scales.length - 1, idx + dir));
        this.maxSeconds = scales[idx];
        this.seconds = Math.min(this.seconds, this.maxSeconds);
        this.rangeVal.textContent = this._rangeLabel();
        this._update();
        this.onChange(this.seconds);
      });
    });

    this.timeText.style.cursor = 'pointer';
    this.timeText.addEventListener('click', () => {
      const val = prompt('Enter time (MM:SS or seconds):', this.formatTime(this.seconds));
      if (val !== null) {
        this.seconds = this._parseTime(val);
        this._update();
        this.onChange(this.seconds);
      }
    });
  }

  _onMove(e) {
    const rect = this.svg.getBoundingClientRect();
    const sx = (e.clientX - rect.left) / rect.width * 200;
    const sy = (e.clientY - rect.top) / rect.height * 200;
    let angle = Math.atan2(sy - this.CY, sx - this.CX) + Math.PI / 2;
    if (angle < 0) angle += 2 * Math.PI;
    const frac = angle / (2 * Math.PI);
    this.seconds = Math.round(frac * this.maxSeconds);
    this.seconds = Math.max(0, Math.min(this.maxSeconds, this.seconds));
    this._update();
    this.onChange(this.seconds);
  }

  _update() {
    const frac   = this.seconds / this.maxSeconds;
    const offset = this.CIRCUM * (1 - frac);
    this.arc.setAttribute('stroke-dashoffset', offset);

    const angle = frac * 2 * Math.PI - Math.PI / 2;
    const hx = this.CX + this.R * Math.cos(angle);
    const hy = this.CY + this.R * Math.sin(angle);
    this.handle.setAttribute('cx', hx);
    this.handle.setAttribute('cy', hy);

    this.timeText.textContent = this.formatTime(this.seconds);
  }

  _rangeLabel() {
    if (this.maxSeconds < 120) return `${this.maxSeconds}s range`;
    return `${this.maxSeconds / 60}m range`;
  }

  formatTime(s) {
    s = Math.round(s);
    const h = Math.floor(s / 3600);
    const m = Math.floor((s % 3600) / 60);
    const sec = s % 60;
    if (h > 0) return `${h}:${String(m).padStart(2,'0')}:${String(sec).padStart(2,'0')}`;
    return `${m}:${String(sec).padStart(2,'0')}`;
  }

  _parseTime(str) {
    str = str.trim();
    if (/^\d+$/.test(str)) return Math.min(parseInt(str), this.maxSeconds);
    const parts = str.split(':').map(Number);
    if (parts.length === 3) return Math.min(parts[0] * 3600 + parts[1] * 60 + parts[2], this.maxSeconds);
    if (parts.length === 2) return Math.min(parts[0] * 60 + parts[1], this.maxSeconds);
    return 0;
  }

  setValue(s) {
    this.seconds = Math.max(0, Math.min(this.maxSeconds, s));
    this._update();
  }
}
