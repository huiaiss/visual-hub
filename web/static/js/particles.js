/**
 * FrameCraft Premium Particle System
 * Subtle golden floating particles — low CPU, high impact
 * Inspired by activtheory.net reference
 */
(function() {
  const canvas = document.getElementById('p-particles');
  if (!canvas) return;

  const ctx = canvas.getContext('2d');
  let particles = [];
  let animId;
  let mouseX = -1000;
  let mouseY = -1000;

  // Config
  const COUNT = 60;
  const BASE_OPACITY = 0.35;
  const GLOW_COLOR = '232, 180, 90'; // --p-accent

  function resize() {
    canvas.width = window.innerWidth;
    canvas.height = window.innerHeight;
  }

  function createParticle() {
    return {
      x: Math.random() * canvas.width,
      y: Math.random() * canvas.height,
      r: Math.random() * 1.8 + 0.4,
      vx: (Math.random() - 0.5) * 0.25,
      vy: (Math.random() - 0.5) * 0.25 - 0.08,
      opacity: Math.random() * BASE_OPACITY + 0.08,
      pulse: Math.random() * Math.PI * 2,
      pulseSpeed: Math.random() * 0.015 + 0.005,
    };
  }

  function init() {
    resize();
    particles = Array.from({ length: COUNT }, createParticle);
  }

  function animate() {
    ctx.clearRect(0, 0, canvas.width, canvas.height);

    particles.forEach(p => {
      // Move
      p.x += p.vx;
      p.y += p.vy;
      p.pulse += p.pulseSpeed;

      // Subtle mouse attraction (very gentle)
      const dx = mouseX - p.x;
      const dy = mouseY - p.y;
      const dist = Math.sqrt(dx * dx + dy * dy);
      if (dist < 200 && dist > 0) {
        const force = 0.003;
        p.vx += (dx / dist) * force;
        p.vy += (dy / dist) * force;
      }

      // Damping
      p.vx *= 0.999;
      p.vy *= 0.999;

      // Wrap around edges
      if (p.x < -20) p.x = canvas.width + 20;
      if (p.x > canvas.width + 20) p.x = -20;
      if (p.y < -20) p.y = canvas.height + 20;
      if (p.y > canvas.height + 20) p.y = -20;

      // Pulsing opacity
      const pulseOp = p.opacity + Math.sin(p.pulse) * 0.12;

      // Draw glow
      const glow = ctx.createRadialGradient(p.x, p.y, 0, p.x, p.y, p.r * 6);
      glow.addColorStop(0, `rgba(${GLOW_COLOR}, ${pulseOp})`);
      glow.addColorStop(0.3, `rgba(${GLOW_COLOR}, ${pulseOp * 0.5})`);
      glow.addColorStop(1, `rgba(${GLOW_COLOR}, 0)`);

      ctx.beginPath();
      ctx.arc(p.x, p.y, p.r * 6, 0, Math.PI * 2);
      ctx.fillStyle = glow;
      ctx.fill();

      // Draw core
      ctx.beginPath();
      ctx.arc(p.x, p.y, p.r, 0, Math.PI * 2);
      ctx.fillStyle = `rgba(${GLOW_COLOR}, ${pulseOp * 1.4})`;
      ctx.fill();
    });

    animId = requestAnimationFrame(animate);
  }

  // Track mouse for subtle attraction
  document.addEventListener('mousemove', e => {
    mouseX = e.clientX;
    mouseY = e.clientY;
  });

  // Handle resize
  window.addEventListener('resize', resize);

  // Handle reduced motion
  const mq = window.matchMedia('(prefers-reduced-motion: reduce)');
  if (mq.matches) {
    canvas.style.display = 'none';
    return;
  }

  init();
  animate();
})();
