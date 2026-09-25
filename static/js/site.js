/* ==========================================================================
   Ballet Dance Studio UG — public site behaviour
   Plain ES2020, no framework. Everything degrades gracefully without JS.
   ========================================================================== */
(function () {
  'use strict';

  const $  = (sel, ctx = document) => ctx.querySelector(sel);
  const $$ = (sel, ctx = document) => Array.from(ctx.querySelectorAll(sel));
  const reduceMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches;

  /* ------------------------------------------------------------------ nav */
  function initNav() {
    const nav = $('.navbar');
    const toggle = $('.nav-toggle');
    const links = $('.nav-links');
    if (!nav) return;

    // Solid bar once the hero has scrolled past (or immediately if no hero).
    const hasHero = document.body.classList.contains('has-hero');
    const threshold = hasHero ? window.innerHeight * 0.55 : 10;

    const onScroll = () => {
      nav.classList.toggle('is-solid', window.scrollY > threshold);
    };
    onScroll();
    window.addEventListener('scroll', onScroll, { passive: true });

    if (toggle && links) {
      toggle.addEventListener('click', () => {
        const open = links.classList.toggle('is-open');
        toggle.setAttribute('aria-expanded', String(open));
        toggle.innerHTML = open
          ? '<i class="fas fa-xmark"></i>'
          : '<i class="fas fa-bars"></i>';
        document.body.style.overflow = open ? 'hidden' : '';
      });

      links.addEventListener('click', (e) => {
        if (e.target.closest('a')) {
          links.classList.remove('is-open');
          toggle.innerHTML = '<i class="fas fa-bars"></i>';
          toggle.setAttribute('aria-expanded', 'false');
          document.body.style.overflow = '';
        }
      });
    }

    document.addEventListener('keydown', (e) => {
      if (e.key === 'Escape' && links && links.classList.contains('is-open')) {
        toggle.click();
      }
    });
  }

  /* ----------------------------------------------------------------- hero */
  function initHero() {
    const hero = $('.hero');
    if (!hero) return;

    splitHeadline();
    initHeroVideo(hero);
    initHeroSlides(hero);
  }

  /**
   * Wrap every word of the headline in a span so it can rise into place one
   * after another. Elements marked .accent keep their own styling.
   */
  function splitHeadline() {
    const title = $('.hero-slide.is-active .hero-title') || $('.hero-title');
    if (!title || title.dataset.split === 'done') return;

    let index = 0;
    const wrapNode = (node) => {
      if (node.nodeType === Node.TEXT_NODE) {
        const words = node.textContent.split(/\s+/).filter(Boolean);
        if (!words.length) return document.createDocumentFragment();
        const frag = document.createDocumentFragment();
        words.forEach((word) => {
          const span = document.createElement('span');
          span.className = 'word';
          span.textContent = word;
          span.style.setProperty('--word-delay', `${index * 90}ms`);
          index += 1;
          frag.appendChild(span);
        });
        return frag;
      }
      if (node.nodeType === Node.ELEMENT_NODE) {
        const clone = node.cloneNode(false);
        clone.classList.add('word');
        clone.style.setProperty('--word-delay', `${index * 90}ms`);
        index += 1;
        clone.textContent = node.textContent.trim();
        return clone;
      }
      return document.createDocumentFragment();
    };

    const rebuilt = document.createDocumentFragment();
    Array.from(title.childNodes).forEach((node) => rebuilt.appendChild(wrapNode(node)));
    title.textContent = '';
    title.appendChild(rebuilt);
    title.dataset.split = 'done';

    if (reduceMotion) {
      $$('.word', title).forEach((w) => {
        w.style.animation = 'none';
        w.style.opacity = '1';
        w.style.transform = 'none';
      });
    }
  }

  /**
   * Autoplay is only allowed while muted, and some browsers refuse even then
   * (data saver, low power mode, an automation profile).
   *
   * The <video poster> attribute already paints the poster frame whenever the
   * clip is not running, so a refusal needs no fallback markup -- the hero is
   * never a black rectangle. All that is left to do is try again on the
   * viewer's first interaction, which is a gesture browsers do accept.
   */
  function initHeroVideo(hero) {
    const video = $('video', hero);
    if (!video) return;

    video.muted = true;
    video.playsInline = true;

    const attempt = () => {
      const played = video.play();
      return played && typeof played.catch === 'function'
        ? played.catch(() => false)
        : Promise.resolve();
    };

    attempt().then((ok) => {
      if (ok === false) {
        // Blocked. Retry once the viewer does anything at all.
        const retry = () => {
          attempt();
          ['pointerdown', 'keydown', 'touchstart', 'scroll']
            .forEach((evt) => window.removeEventListener(evt, retry));
        };
        ['pointerdown', 'keydown', 'touchstart', 'scroll']
          .forEach((evt) => window.addEventListener(evt, retry, { passive: true }));
      }
    });

    // Pause off-screen so a background video does not burn battery.
    if ('IntersectionObserver' in window) {
      new IntersectionObserver((entries) => {
        entries.forEach((entry) => {
          if (entry.isIntersecting) video.play().catch(() => {});
          else video.pause();
        });
      }, { threshold: 0.1 }).observe(hero);
    }

    const sound = $('.hero-sound', hero);
    if (sound) {
      sound.addEventListener('click', () => {
        video.muted = !video.muted;
        sound.innerHTML = video.muted
          ? '<i class="fas fa-volume-xmark"></i>'
          : '<i class="fas fa-volume-high"></i>';
        sound.setAttribute(
          'aria-label', video.muted ? 'Unmute background video' : 'Mute background video',
        );
      });
    }
  }

  function initHeroSlides(hero) {
    const slides = $$('.hero-slide', hero);
    const dots = $$('.hero-dots button', hero);
    if (slides.length < 2) return;

    let current = 0;
    let timer = null;

    const show = (i) => {
      slides[current].classList.remove('is-active');
      dots[current] && dots[current].classList.remove('is-active');
      current = (i + slides.length) % slides.length;
      slides[current].classList.add('is-active');
      dots[current] && dots[current].classList.add('is-active');

      const video = $('video', slides[current]);
      if (video) video.play().catch(() => {});
      splitHeadline();
    };

    const start = () => {
      if (reduceMotion) return;
      stop();
      timer = setInterval(() => show(current + 1), 9000);
    };
    const stop = () => timer && clearInterval(timer);

    dots.forEach((dot, i) => dot.addEventListener('click', () => { show(i); start(); }));
    hero.addEventListener('mouseenter', stop);
    hero.addEventListener('mouseleave', start);
    start();
  }

  /* --------------------------------------------------------- scroll reveal */
  function initReveal() {
    const items = $$('[data-reveal]');
    if (!items.length) return;

    if (reduceMotion || !('IntersectionObserver' in window)) {
      items.forEach((el) => el.classList.add('is-visible'));
      return;
    }

    const observer = new IntersectionObserver((entries) => {
      entries.forEach((entry) => {
        if (!entry.isIntersecting) return;
        entry.target.classList.add('is-visible');
        observer.unobserve(entry.target);
      });
    }, { threshold: 0.12, rootMargin: '0px 0px -60px 0px' });

    items.forEach((el, i) => {
      // Stagger siblings so a grid of cards cascades rather than snapping in.
      if (!el.style.getPropertyValue('--reveal-delay')) {
        const siblingIndex = Array.from(el.parentElement?.children || []).indexOf(el);
        el.style.setProperty('--reveal-delay', `${Math.min(siblingIndex, 6) * 90}ms`);
      }
      observer.observe(el);
    });
  }

  /* ------------------------------------------------------------- counters */
  function initCounters() {
    const nodes = $$('[data-count]');
    if (!nodes.length || !('IntersectionObserver' in window)) {
      nodes.forEach((n) => { n.textContent = n.dataset.count; });
      return;
    }

    const run = (el) => {
      const target = parseFloat(el.dataset.count) || 0;
      const suffix = el.dataset.suffix || '';
      if (reduceMotion) { el.textContent = target + suffix; return; }

      const duration = 1500;
      const started = performance.now();
      const tick = (now) => {
        const progress = Math.min((now - started) / duration, 1);
        const eased = 1 - Math.pow(1 - progress, 3);
        el.textContent = Math.round(target * eased).toLocaleString() + suffix;
        if (progress < 1) requestAnimationFrame(tick);
      };
      requestAnimationFrame(tick);
    };

    const observer = new IntersectionObserver((entries) => {
      entries.forEach((entry) => {
        if (!entry.isIntersecting) return;
        run(entry.target);
        observer.unobserve(entry.target);
      });
    }, { threshold: 0.5 });

    nodes.forEach((n) => observer.observe(n));
  }

  /* ------------------------------------------------------------ countdown */
  function initCountdown() {
    const box = $('[data-countdown]');
    if (!box) return;

    const target = new Date(box.dataset.countdown).getTime();
    if (Number.isNaN(target)) return;

    const fields = {
      days: $('[data-unit="days"]', box),
      hours: $('[data-unit="hours"]', box),
      minutes: $('[data-unit="minutes"]', box),
      seconds: $('[data-unit="seconds"]', box),
    };

    const tick = () => {
      const gap = target - Date.now();
      if (gap <= 0) {
        box.innerHTML = '<p class="tagline">The curtain is up — thank you for coming.</p>';
        clearInterval(handle);
        return;
      }
      const days = Math.floor(gap / 86400000);
      const hours = Math.floor((gap % 86400000) / 3600000);
      const minutes = Math.floor((gap % 3600000) / 60000);
      const seconds = Math.floor((gap % 60000) / 1000);
      if (fields.days) fields.days.textContent = String(days);
      if (fields.hours) fields.hours.textContent = String(hours).padStart(2, '0');
      if (fields.minutes) fields.minutes.textContent = String(minutes).padStart(2, '0');
      if (fields.seconds) fields.seconds.textContent = String(seconds).padStart(2, '0');
    };

    tick();
    const handle = setInterval(tick, 1000);
  }

  /* ------------------------------------------------------------- lightbox */
  function initLightbox() {
    const items = $$('[data-lightbox]');
    if (!items.length) return;

    const box = document.createElement('div');
    box.className = 'lightbox';
    box.setAttribute('role', 'dialog');
    box.setAttribute('aria-modal', 'true');
    box.setAttribute('aria-label', 'Photo viewer');
    box.innerHTML = `
      <button class="lightbox-close" aria-label="Close"><i class="fas fa-xmark"></i></button>
      <button class="lightbox-prev" aria-label="Previous photo"><i class="fas fa-chevron-left"></i></button>
      <button class="lightbox-next" aria-label="Next photo"><i class="fas fa-chevron-right"></i></button>
      <div>
        <img alt="">
        <p class="lightbox-caption"></p>
      </div>`;
    document.body.appendChild(box);

    const img = $('img', box);
    const caption = $('.lightbox-caption', box);
    let index = 0;
    let lastFocused = null;

    const open = (i) => {
      index = (i + items.length) % items.length;
      const source = items[index];
      img.src = source.dataset.lightbox || source.querySelector('img')?.src || '';
      img.alt = source.dataset.alt || '';
      caption.textContent = source.dataset.caption || '';
      box.classList.add('is-open');
      document.body.style.overflow = 'hidden';
      $('.lightbox-close', box).focus();
    };

    const close = () => {
      box.classList.remove('is-open');
      document.body.style.overflow = '';
      if (lastFocused) lastFocused.focus();
    };

    items.forEach((item, i) => {
      item.addEventListener('click', (e) => {
        e.preventDefault();
        lastFocused = item;
        open(i);
      });
    });

    $('.lightbox-close', box).addEventListener('click', close);
    $('.lightbox-prev', box).addEventListener('click', () => open(index - 1));
    $('.lightbox-next', box).addEventListener('click', () => open(index + 1));
    box.addEventListener('click', (e) => { if (e.target === box) close(); });

    document.addEventListener('keydown', (e) => {
      if (!box.classList.contains('is-open')) return;
      if (e.key === 'Escape') close();
      if (e.key === 'ArrowLeft') open(index - 1);
      if (e.key === 'ArrowRight') open(index + 1);
    });
  }

  /* ------------------------------------------------------------ accordion */
  function initAccordion() {
    $$('.accordion-head').forEach((head) => {
      head.setAttribute('aria-expanded', 'false');
      head.addEventListener('click', () => {
        const item = head.closest('.accordion-item');
        const open = item.classList.toggle('is-open');
        head.setAttribute('aria-expanded', String(open));
      });
    });
  }

  /* --------------------------------------------------------------- toasts */
  function initToasts() {
    $$('.toast').forEach((toast, i) => {
      const dismiss = () => {
        toast.style.transition = 'opacity .3s, transform .3s';
        toast.style.opacity = '0';
        toast.style.transform = 'translateX(40px)';
        setTimeout(() => toast.remove(), 300);
      };
      const button = $('button', toast);
      if (button) button.addEventListener('click', dismiss);
      setTimeout(dismiss, 6000 + i * 700);
    });
  }

  /* ------------------------------------------------------- announcement bar */
  function initAnnounceBar() {
    const bar = $('.announce-bar');
    if (!bar) return;
    const key = 'bdsu-announce-' + (bar.dataset.id || '0');

    try {
      if (localStorage.getItem(key) === 'dismissed') { bar.remove(); return; }
    } catch (_) { /* private browsing — just show it */ }

    const close = $('.close', bar);
    if (close) {
      close.addEventListener('click', () => {
        bar.remove();
        try { localStorage.setItem(key, 'dismissed'); } catch (_) {}
      });
    }
  }

  /* ------------------------------------------------------------------ init */
  function init() {
    initNav();
    initHero();
    initReveal();
    initCounters();
    initCountdown();
    initLightbox();
    initAccordion();
    initToasts();
    initAnnounceBar();
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }

  // HTMX swaps bring in new markup that needs the same wiring.
  document.body.addEventListener('htmx:afterSwap', () => {
    initReveal();
    initAccordion();
    initToasts();
  });
})();
