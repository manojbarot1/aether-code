/**
 * Liquid Glass UI Interactivity & Dynamic Effects
 */

document.addEventListener("DOMContentLoaded", () => {
  initThemeSelector();
  initMouseSpecularSheen();
  initGlassTabs();
  initLiveBlurControls();
  initCounterAnimations();
  initMobileNav();
  initInteractiveWidgets();
});

// 1. Mouse Specular Reflection Spotlight on Glass Elements
function initMouseSpecularSheen() {
  const cards = document.querySelectorAll(".glass-card, .glass-panel, .pricing-card");
  
  cards.forEach(card => {
    card.addEventListener("mousemove", (e) => {
      const rect = card.getBoundingClientRect();
      const x = e.clientX - rect.left;
      const y = e.clientY - rect.top;
      
      card.style.setProperty("--mouse-x", `${x}px`);
      card.style.setProperty("--mouse-y", `${y}px`);
    });
  });
}

// 2. Liquid Theme Selector (Aurora, Nebula, Crystal)
function initThemeSelector() {
  const themeButtons = document.querySelectorAll(".theme-btn");
  if (!themeButtons.length) return;

  const savedTheme = localStorage.getItem("liquid_theme") || "crystal";
  applyTheme(savedTheme);

  themeButtons.forEach(btn => {
    btn.addEventListener("click", () => {
      const theme = btn.dataset.theme;
      applyTheme(theme);
      localStorage.setItem("liquid_theme", theme);
    });
  });
}

function applyTheme(themeName) {
  document.documentElement.setAttribute("data-theme", themeName);
  
  document.querySelectorAll(".theme-btn").forEach(btn => {
    if (btn.dataset.theme === themeName) {
      btn.classList.add("active");
    } else {
      btn.classList.remove("active");
    }
  });

  const blob1 = document.querySelector(".blob-1");
  const blob2 = document.querySelector(".blob-2");
  const blob3 = document.querySelector(".blob-3");

  if (!blob1 || !blob2 || !blob3) return;

  if (themeName === "aurora") {
    blob1.style.background = "radial-gradient(circle, #00f2fe 0%, #4facfe 50%, transparent 75%)";
    blob2.style.background = "radial-gradient(circle, #43e97b 0%, #38ef7d 50%, transparent 75%)";
    blob3.style.background = "radial-gradient(circle, #0575e6 0%, #00f2fe 50%, transparent 75%)";
  } else if (themeName === "nebula") {
    blob1.style.background = "radial-gradient(circle, #f857a6 0%, #ff5858 50%, transparent 75%)";
    blob2.style.background = "radial-gradient(circle, #7f00ff 0%, #e100ff 50%, transparent 75%)";
    blob3.style.background = "radial-gradient(circle, #ff0844 0%, #ffb199 50%, transparent 75%)";
  } else {
    // crystal
    blob1.style.background = "radial-gradient(circle, #6366f1 0%, #3b82f6 50%, transparent 75%)";
    blob2.style.background = "radial-gradient(circle, #ec4899 0%, #8b5cf6 50%, transparent 75%)";
    blob3.style.background = "radial-gradient(circle, #06b6d4 0%, #10b981 50%, transparent 75%)";
  }
}

// 3. Glass Tab Switcher
function initGlassTabs() {
  const tabs = document.querySelectorAll(".glass-tab-btn");
  if (!tabs.length) return;

  tabs.forEach(tab => {
    tab.addEventListener("click", () => {
      const targetId = tab.dataset.target;
      const targetPane = document.getElementById(targetId);
      
      if (!targetPane) return;

      tabs.forEach(t => t.classList.remove("active"));
      tab.classList.add("active");

      document.querySelectorAll(".tab-pane").forEach(pane => {
        pane.classList.remove("active");
      });
      targetPane.classList.add("active");
    });
  });
}

// 4. Live Blur & Opacity Control (Interactive Glass Lab)
function initLiveBlurControls() {
  const blurSlider = document.getElementById("slider-blur");
  const opacitySlider = document.getElementById("slider-opacity");
  const sampleCard = document.getElementById("glass-preview-sample");

  if (!sampleCard) return;

  if (blurSlider) {
    blurSlider.addEventListener("input", (e) => {
      const val = e.target.value;
      sampleCard.style.backdropFilter = `blur(${val}px) saturate(180%)`;
      sampleCard.style.webkitBackdropFilter = `blur(${val}px) saturate(180%)`;
      const valDisplay = document.getElementById("val-blur");
      if (valDisplay) valDisplay.textContent = `${val}px`;
    });
  }

  if (opacitySlider) {
    opacitySlider.addEventListener("input", (e) => {
      const val = e.target.value;
      sampleCard.style.backgroundColor = `rgba(255, 255, 255, ${val / 100})`;
      const valDisplay = document.getElementById("val-opacity");
      if (valDisplay) valDisplay.textContent = `${val}%`;
    });
  }
}

// 5. Metric Number Counter Animation
function initCounterAnimations() {
  const counters = document.querySelectorAll(".counter-val");
  if (!counters.length) return;

  counters.forEach(counter => {
    const target = parseInt(counter.dataset.count, 10);
    const suffix = counter.dataset.suffix || "";
    let current = 0;
    const increment = Math.ceil(target / 40);
    const timer = setInterval(() => {
      current += increment;
      if (current >= target) {
        current = target;
        clearInterval(timer);
      }
      counter.textContent = current.toLocaleString() + suffix;
    }, 30);
  });
}

// 6. Mobile Navigation Drawer
function initMobileNav() {
  const toggleBtn = document.querySelector(".mobile-nav-toggle");
  const navLinks = document.querySelector(".nav-links");

  if (toggleBtn && navLinks) {
    toggleBtn.addEventListener("click", () => {
      navLinks.classList.toggle("open");
    });
  }
}

// 7. Interactive Toast / UI triggers
function showGlassToast(message) {
  let toast = document.getElementById("glass-toast");
  if (!toast) {
    toast = document.createElement("div");
    toast.id = "glass-toast";
    toast.style.position = "fixed";
    toast.style.bottom = "30px";
    toast.style.right = "30px";
    toast.style.padding = "16px 26px";
    toast.style.borderRadius = "16px";
    toast.style.background = "rgba(15, 23, 42, 0.85)";
    toast.style.backdropFilter = "blur(20px)";
    toast.style.border = "1px solid rgba(255, 255, 255, 0.25)";
    toast.style.color = "#fff";
    toast.style.boxShadow = "0 20px 40px rgba(0, 0, 0, 0.5)";
    toast.style.zIndex = "9999";
    toast.style.transition = "all 0.3s cubic-bezier(0.16, 1, 0.3, 1)";
    toast.style.transform = "translateY(50px)";
    toast.style.opacity = "0";
    document.body.appendChild(toast);
  }

  toast.textContent = message;
  toast.style.transform = "translateY(0)";
  toast.style.opacity = "1";

  setTimeout(() => {
    toast.style.transform = "translateY(50px)";
    toast.style.opacity = "0";
  }, 3000);
}

function initInteractiveWidgets() {
  // Contact form submission feedback
  const contactForm = document.getElementById("liquid-contact-form");
  if (contactForm) {
    contactForm.addEventListener("submit", (e) => {
      e.preventDefault();
      showGlassToast("✨ Message transmitted through liquid glass relay!");
      contactForm.reset();
    });
  }

  // Interactive Play/Pause button for media card
  const playBtn = document.getElementById("player-play-btn");
  if (playBtn) {
    let isPlaying = false;
    playBtn.addEventListener("click", () => {
      isPlaying = !isPlaying;
      playBtn.textContent = isPlaying ? "⏸" : "▶";
      showGlassToast(isPlaying ? "Playing Liquid Soundscapes" : "Audio Paused");
    });
  }
}
