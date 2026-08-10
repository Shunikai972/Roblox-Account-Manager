/* ==========================================================================
   Astro Account Manager — Documentation Script
   ========================================================================== */

document.addEventListener('DOMContentLoaded', () => {
  const searchInput = document.getElementById('docSearchInput');
  const navLinks = document.querySelectorAll('.nav-link');
  const sections = document.querySelectorAll('.doc-section, .hero-card');

  // Interactive Live Search
  if (searchInput) {
    searchInput.addEventListener('input', (e) => {
      const term = e.target.value.toLowerCase().trim();
      sections.forEach(section => {
        const text = section.textContent.toLowerCase();
        if (term === '' || text.includes(term)) {
          section.style.display = 'block';
        } else {
          section.style.display = 'none';
        }
      });
    });
  }

  // Smooth Scroll & Active Nav State
  window.addEventListener('scroll', () => {
    let current = '';
    sections.forEach(section => {
      const sectionTop = section.offsetTop - 100;
      if (window.scrollY >= sectionTop) {
        current = section.getAttribute('id');
      }
    });

    navLinks.forEach(link => {
      link.classList.remove('active');
      if (link.getAttribute('href') === `#${current}`) {
        link.classList.add('active');
      }
    });
  });
});

// Copy Code Snippet Helper
function copyCode(button) {
  const container = button.closest('.code-block-container');
  const code = container.querySelector('code').innerText;
  navigator.clipboard.writeText(code).then(() => {
    const originalText = button.innerText;
    button.innerText = 'Copied!';
    button.style.color = '#34D399';
    setTimeout(() => {
      button.innerText = originalText;
      button.style.color = '';
    }, 2000);
  });
}
