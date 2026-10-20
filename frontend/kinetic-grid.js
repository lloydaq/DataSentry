// Kinetic grid background: a fixed canvas grid that warps away from the pointer and ripples on
// press. Vanilla port of the KineticGrid React component, adapted to DataSentry: colors come from
// the theme tokens (and follow theme changes), motion is skipped under prefers-reduced-motion, and
// the loop sleeps when nothing moves or the tab is hidden.
"use strict";

(() => {
  const canvas = document.querySelector(".kinetic-grid");
  if (!canvas || !canvas.getContext) return;
  const ctx = canvas.getContext("2d");

  const CELL_SIZE = 55;
  const INFLUENCE_RADIUS = 260;
  const MAX_WARP = 24;
  const DOT_SPACING = 28;
  const LERP_SPEED = 0.08;
  const NODE_BASE_RADIUS = 1.8;
  const NODE_ACTIVE_RADIUS = 3.2;
  const OFFSCREEN = -9999;

  const reducedMotion = window.matchMedia("(prefers-reduced-motion: reduce)");
  const darkScheme = window.matchMedia("(prefers-color-scheme: dark)");

  const mouse = { x: OFFSCREEN, y: OFFSCREEN };
  const target = { x: OFFSCREEN, y: OFFSCREEN };
  const ripples = [];
  let size = { w: 0, h: 0, dpr: 1 };
  let palette = null;
  let dotLayer = null;
  let raf = 0;

  const lerp = (a, b, t) => a + (b - a) * t;
  const smoothstep = (t) => t * t * (3 - 2 * t);
  const rgba = (c, a) => `rgba(${c.r},${c.g},${c.b},${a.toFixed(3)})`;
  const mix = (base, active, t) => rgba(
    { r: Math.round(lerp(base.r, active.r, t)), g: Math.round(lerp(base.g, active.g, t)), b: Math.round(lerp(base.b, active.b, t)) },
    lerp(base.a, active.a, t),
  );

  // Resolve theme tokens to RGB through computed styles (light-dark() values are not readable directly).
  function readPalette() {
    const probe = document.createElement("span");
    probe.style.cssText = "position:absolute;visibility:hidden;color:var(--accent);background:var(--bg);border-color:var(--text)";
    document.body.append(probe);
    const style = getComputedStyle(probe);
    const parse = (value) => {
      const [r, g, b] = value.match(/[\d.]+/g).map(Number);
      return { r, g, b };
    };
    const result = { accent: parse(style.color), bg: style.backgroundColor, ink: parse(style.borderTopColor) };
    probe.remove();
    return result;
  }

  function buildDotLayer() {
    dotLayer = document.createElement("canvas");
    dotLayer.width = size.w * size.dpr;
    dotLayer.height = size.h * size.dpr;
    const d = dotLayer.getContext("2d");
    d.scale(size.dpr, size.dpr);
    d.fillStyle = rgba(palette.ink, 0.05);
    for (let x = DOT_SPACING / 2; x < size.w; x += DOT_SPACING) {
      for (let y = DOT_SPACING / 2; y < size.h; y += DOT_SPACING) {
        d.beginPath();
        d.arc(x, y, 0.7, 0, Math.PI * 2);
        d.fill();
      }
    }
  }

  function warp(gx, gy, col, row, cols, rows) {
    // Edge pin: boundary rows and columns stay put.
    const edgeMargin = 1.5;
    const colPin = Math.min(col / edgeMargin, (cols - 1 - col) / edgeMargin, 1);
    const rowPin = Math.min(row / edgeMargin, (rows - 1 - row) / edgeMargin, 1);
    const pin = colPin * colPin * rowPin * rowPin;

    const dx = gx - mouse.x;
    const dy = gy - mouse.y;
    const dist = Math.hypot(dx, dy);
    const proximity = Math.max(0, 1 - dist / INFLUENCE_RADIUS) * pin;

    let rx = 0;
    let ry = 0;
    for (const r of ripples) {
      const rdx = gx - r.x;
      const rdy = gy - r.y;
      const diff = Math.hypot(rdx, rdy) - r.radius;
      const waveWidth = 55;
      if (Math.abs(diff) < waveWidth) {
        const strength = (1 - Math.abs(diff) / waveWidth) * r.opacity * 18 * pin;
        const angle = Math.atan2(rdy, rdx);
        const sign = diff < 0 ? -1 : 1;
        rx -= Math.cos(angle) * strength * sign;
        ry -= Math.sin(angle) * strength * sign;
      }
    }

    if (dist < INFLUENCE_RADIUS && dist > 0 && pin > 0) {
      const t = dist / INFLUENCE_RADIUS;
      const eased = t < 0.01 ? 0 : (1 - t) * (1 - t) * Math.min(1, dist / 60);
      const amount = eased * MAX_WARP * pin;
      const angle = Math.atan2(dy, dx);
      return { x: gx - Math.cos(angle) * amount + rx, y: gy - Math.sin(angle) * amount + ry, p: proximity };
    }
    return { x: gx + rx, y: gy + ry, p: proximity };
  }

  function draw(now) {
    const { w: W, h: H } = size;
    const lineBase = { ...palette.ink, a: 0.13 };
    const lineActive = { ...palette.accent, a: 0.9 };
    const nodeBase = { ...palette.ink, a: 0.2 };
    const nodeActive = { ...palette.accent, a: 1 };

    ctx.setTransform(size.dpr, 0, 0, size.dpr, 0, 0);
    ctx.fillStyle = palette.bg;
    ctx.fillRect(0, 0, W, H);
    ctx.drawImage(dotLayer, 0, 0, W, H);

    for (let i = ripples.length - 1; i >= 0; i--) {
      const r = ripples[i];
      const age = (now - r.born) / 1000;
      r.radius = Math.max(0, age * 400);
      r.opacity = Math.max(0, 1 - age * 1.2);
      if (r.opacity <= 0) ripples.splice(i, 1);
    }

    const cols = Math.max(2, Math.ceil(W / CELL_SIZE)) + 1;
    const rows = Math.max(2, Math.ceil(H / CELL_SIZE)) + 1;
    const cellW = W / (cols - 1);
    const cellH = H / (rows - 1);
    const pts = [];
    for (let row = 0; row < rows; row++) {
      pts[row] = [];
      for (let col = 0; col < cols; col++) pts[row][col] = warp(col * cellW, row * cellH, col, row, cols, rows);
    }

    const segment = (a, b) => {
      const t = smoothstep((a.p + b.p) / 2);
      ctx.beginPath();
      ctx.moveTo(a.x, a.y);
      ctx.lineTo(b.x, b.y);
      ctx.strokeStyle = mix(lineBase, lineActive, t);
      ctx.lineWidth = lerp(0.8, 1.5, t);
      ctx.stroke();
    };
    ctx.lineCap = "butt";
    for (let row = 0; row < rows; row++) for (let col = 0; col < cols - 1; col++) segment(pts[row][col], pts[row][col + 1]);
    for (let col = 0; col < cols; col++) for (let row = 0; row < rows - 1; row++) segment(pts[row][col], pts[row + 1][col]);

    for (let row = 0; row < rows; row++) {
      for (let col = 0; col < cols; col++) {
        const p = pts[row][col];
        const t = smoothstep(p.p);
        const radius = lerp(NODE_BASE_RADIUS, NODE_ACTIVE_RADIUS, t);
        if (t > 0.3) {
          const glowRadius = radius + lerp(0, 6, (t - 0.3) / 0.7);
          const glow = ctx.createRadialGradient(p.x, p.y, radius * 0.5, p.x, p.y, glowRadius);
          glow.addColorStop(0, rgba(palette.accent, t * 0.3));
          glow.addColorStop(1, rgba(palette.accent, 0));
          ctx.beginPath();
          ctx.arc(p.x, p.y, glowRadius, 0, Math.PI * 2);
          ctx.fillStyle = glow;
          ctx.fill();
        }
        ctx.beginPath();
        ctx.arc(p.x, p.y, radius, 0, Math.PI * 2);
        ctx.fillStyle = mix(nodeBase, nodeActive, t);
        ctx.fill();
      }
    }

    for (const r of ripples) {
      ctx.beginPath();
      ctx.arc(r.x, r.y, Math.max(0, r.radius), 0, Math.PI * 2);
      ctx.strokeStyle = rgba(palette.accent, r.opacity * 0.28);
      ctx.lineWidth = 1.5;
      ctx.stroke();
    }
  }

  // The loop runs only while something is moving, then sleeps until the next input.
  function frame(now) {
    raf = 0;
    mouse.x = lerp(mouse.x, target.x, LERP_SPEED);
    mouse.y = lerp(mouse.y, target.y, LERP_SPEED);
    draw(now);
    const settled = Math.abs(mouse.x - target.x) < 0.3 && Math.abs(mouse.y - target.y) < 0.3;
    if (!settled || ripples.length) wake();
  }

  function wake() {
    if (!raf && !document.hidden && !reducedMotion.matches) raf = requestAnimationFrame(frame);
  }

  function redrawStill() {
    if (reducedMotion.matches) {
      mouse.x = mouse.y = target.x = target.y = OFFSCREEN;
      ripples.length = 0;
    }
    draw(performance.now());
  }

  function resize() {
    const dpr = Math.min(window.devicePixelRatio || 1, 2);
    size = { w: window.innerWidth, h: window.innerHeight, dpr };
    canvas.width = Math.round(size.w * dpr);
    canvas.height = Math.round(size.h * dpr);
    buildDotLayer();
    redrawStill();
  }

  function refreshTheme() {
    palette = readPalette();
    buildDotLayer();
    redrawStill();
  }

  window.addEventListener("pointermove", (e) => {
    target.x = e.clientX;
    target.y = e.clientY;
    if (mouse.x === OFFSCREEN) {
      mouse.x = e.clientX;
      mouse.y = e.clientY;
    }
    wake();
  }, { passive: true });
  window.addEventListener("pointerdown", (e) => {
    if (reducedMotion.matches) return;
    ripples.push({ x: e.clientX, y: e.clientY, radius: 0, opacity: 1, born: performance.now() });
    wake();
  }, { passive: true });
  window.addEventListener("resize", resize);
  document.addEventListener("visibilitychange", () => (document.hidden ? (cancelAnimationFrame(raf), (raf = 0)) : wake()));
  reducedMotion.addEventListener("change", redrawStill);
  darkScheme.addEventListener("change", refreshTheme);
  new MutationObserver(refreshTheme).observe(document.documentElement, { attributes: true, attributeFilter: ["data-theme"] });

  palette = readPalette();
  resize();
})();
