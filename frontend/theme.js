// Applies a saved theme choice before first paint (loaded without defer). "system" or no saved
// value leaves the OS preference in charge. The switch itself is wired up in app.js.
"use strict";
try {
  const saved = localStorage.getItem("datasentry-theme");
  if (saved === "light" || saved === "dark") document.documentElement.dataset.theme = saved;
} catch {
  // Storage can be unavailable (private mode, blocked site data); the system theme still applies.
}
