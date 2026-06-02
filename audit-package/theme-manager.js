/**
 * Vernis Theme Manager
 * Handles light/dark theme persistence across all pages
 */

(function () {
  // Load and apply saved theme on page load
  const savedTheme = localStorage.getItem('vernis-theme') || 'light';
  document.documentElement.setAttribute('data-theme', savedTheme);
})();

// Export theme toggle function for settings page
function toggleTheme() {
  const currentTheme = document.documentElement.getAttribute('data-theme');
  const newTheme = currentTheme === 'dark' ? 'light' : 'dark';

  document.documentElement.setAttribute('data-theme', newTheme);
  localStorage.setItem('vernis-theme', newTheme);

  return newTheme;
}
