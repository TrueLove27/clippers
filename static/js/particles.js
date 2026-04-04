/**
 * Particle-network canvas background.
 * Call initParticles(canvasId, opts) after the element exists.
 */
function initParticles(canvasId, opts = {}) {
  const canvas = document.getElementById(canvasId);
  if (!canvas) return;
  const ctx = canvas.getContext('2d');

  const cfg = {
    density:     opts.density     ?? 80,
    speed:       opts.speed       ?? 0.35,
    linkDist:    opts.linkDist    ?? 130,
    mouseRadius: opts.mouseRadius ?? 110,
    opacity:     opts.opacity     ?? 0.55,
    color1:      opts.color1      || [0, 212, 255],
    color2:      opts.color2      || [123, 47, 247],
  };

  let W, H, particles = [], mouse = { x: -1000, y: -1000 };

  function resize() {
    W = canvas.width = window.innerWidth;
    H = canvas.height = window.innerHeight;
    seed();
  }

  function seed() {
    const count = Math.floor((W * H) / (12000 / (cfg.density / 80)));
    particles = [];
    for (let i = 0; i < count; i++) {
      const t = Math.random();
      const r = lerp(cfg.color1[0], cfg.color2[0], t);
      const g = lerp(cfg.color1[1], cfg.color2[1], t);
      const b = lerp(cfg.color1[2], cfg.color2[2], t);
      particles.push({
        x: Math.random() * W,
        y: Math.random() * H,
        vx: (Math.random() - 0.5) * cfg.speed,
        vy: (Math.random() - 0.5) * cfg.speed,
        radius: Math.random() * 1.8 + 0.8,
        color: `${r},${g},${b}`,
      });
    }
  }

  function lerp(a, b, t) { return Math.round(a + (b - a) * t); }

  function draw() {
    ctx.clearRect(0, 0, W, H);

    for (let i = 0; i < particles.length; i++) {
      const p = particles[i];
      p.x += p.vx;
      p.y += p.vy;
      if (p.x < 0 || p.x > W) p.vx *= -1;
      if (p.y < 0 || p.y > H) p.vy *= -1;

      // Mouse repulsion
      const dx = p.x - mouse.x;
      const dy = p.y - mouse.y;
      const dist = Math.sqrt(dx * dx + dy * dy);
      if (dist < cfg.mouseRadius) {
        const force = (cfg.mouseRadius - dist) / cfg.mouseRadius * 0.04;
        p.vx += dx * force;
        p.vy += dy * force;
      }
      const maxV = cfg.speed * 2;
      p.vx = Math.max(-maxV, Math.min(maxV, p.vx));
      p.vy = Math.max(-maxV, Math.min(maxV, p.vy));

      ctx.beginPath();
      ctx.arc(p.x, p.y, p.radius, 0, Math.PI * 2);
      ctx.fillStyle = `rgba(${p.color},${cfg.opacity})`;
      ctx.fill();

      for (let j = i + 1; j < particles.length; j++) {
        const q = particles[j];
        const lx = p.x - q.x;
        const ly = p.y - q.y;
        const ld = Math.sqrt(lx * lx + ly * ly);
        if (ld < cfg.linkDist) {
          ctx.beginPath();
          ctx.moveTo(p.x, p.y);
          ctx.lineTo(q.x, q.y);
          const a = (1 - ld / cfg.linkDist) * cfg.opacity * 0.5;
          ctx.strokeStyle = `rgba(${p.color},${a})`;
          ctx.lineWidth = 0.6;
          ctx.stroke();
        }
      }
    }
    requestAnimationFrame(draw);
  }

  window.addEventListener('resize', resize);
  canvas.addEventListener('mousemove', e => { mouse.x = e.clientX; mouse.y = e.clientY; });
  canvas.addEventListener('mouseleave', () => { mouse.x = -1000; mouse.y = -1000; });

  resize();
  draw();
}
