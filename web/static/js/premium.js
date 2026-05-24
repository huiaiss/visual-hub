/**
 * FrameCraft Premium Interactions
 * Scroll reveal, mouse glow, 3D card tilt, nav scroll effect
 */
(function() {
  // === SCROLL REVEAL (Intersection Observer) ===
  const revealEls = document.querySelectorAll('.p-reveal');
  const staggerContainers = document.querySelectorAll('.p-reveal-stagger');

  const revealObserver = new IntersectionObserver((entries) => {
    entries.forEach(entry => {
      if (entry.isIntersecting) {
        entry.target.classList.add('p-visible');
        revealObserver.unobserve(entry.target);
      }
    });
  }, {
    threshold: 0.15,
    rootMargin: '0px 0px -40px 0px'
  });

  revealEls.forEach(el => revealObserver.observe(el));

  // Stagger children with delay
  staggerContainers.forEach(container => {
    const children = container.children;
    const staggerObserver = new IntersectionObserver((entries) => {
      if (entries[0].isIntersecting) {
        Array.from(children).forEach((child, i) => {
          setTimeout(() => child.classList.add('p-visible'), i * 80);
        });
        staggerObserver.unobserve(container);
      }
    }, { threshold: 0.1, rootMargin: '0px 0px -40px 0px' });
    staggerObserver.observe(container);
  });

  // === MOUSE GLOW ===
  const glow = document.querySelector('.p-mouse-glow');
  if (glow) {
    document.addEventListener('mousemove', e => {
      glow.style.left = e.clientX + 'px';
      glow.style.top = e.clientY + 'px';
    });
  }

  // === 3D CARD TILT ===
  const cards3d = document.querySelectorAll('.p-card-3d');
  cards3d.forEach(card => {
    card.addEventListener('mousemove', e => {
      const rect = card.getBoundingClientRect();
      const x = e.clientX - rect.left;
      const y = e.clientY - rect.top;
      const centerX = rect.width / 2;
      const centerY = rect.height / 2;
      const rotateX = ((y - centerY) / centerY) * -8;
      const rotateY = ((x - centerX) / centerX) * 8;

      const inner = card.querySelector('.p-card-3d-inner');
      if (inner) {
        inner.style.transform = `perspective(1000px) rotateX(${rotateX}deg) rotateY(${rotateY}deg) translateZ(8px)`;
      }
    });

    card.addEventListener('mouseleave', () => {
      const inner = card.querySelector('.p-card-3d-inner');
      if (inner) {
        inner.style.transform = 'perspective(1000px) rotateX(0) rotateY(0) translateZ(0)';
      }
    });
  });

  // === NAV SCROLL EFFECT ===
  const nav = document.querySelector('.p-nav');
  if (nav) {
    let lastScroll = 0;
    window.addEventListener('scroll', () => {
      const scrollY = window.scrollY;
      if (scrollY > 50) {
        nav.classList.add('scrolled');
      } else {
        nav.classList.remove('scrolled');
      }
      lastScroll = scrollY;
    }, { passive: true });
  }

  // === COUNTER ANIMATION ===
  const counters = document.querySelectorAll('[data-count]');
  const counterObserver = new IntersectionObserver((entries) => {
    entries.forEach(entry => {
      if (entry.isIntersecting) {
        const el = entry.target;
        const target = parseInt(el.getAttribute('data-count'), 10);
        const duration = 1500;
        const start = performance.now();

        function update(now) {
          const elapsed = now - start;
          const progress = Math.min(elapsed / duration, 1);
          // Ease out cubic
          const eased = 1 - Math.pow(1 - progress, 3);
          el.textContent = Math.floor(eased * target);
          if (progress < 1) {
            requestAnimationFrame(update);
          } else {
            el.textContent = target;
          }
        }

        requestAnimationFrame(update);
        counterObserver.unobserve(el);
      }
    });
  }, { threshold: 0.5 });

  counters.forEach(el => counterObserver.observe(el));

})();
