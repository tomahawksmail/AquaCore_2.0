"use strict";
(() => {
  const button = document.getElementById('fertilizer-dose-now');
  const durationInput = document.getElementById('fertilizer-seconds');
  const status = document.getElementById('fertilizer-dose-status');
  if (!button || !durationInput || !status) return;

  let busy = false;
  let queued = false;
  const refresh = () => {
    const seconds = Number(durationInput.dataset.saved ?? durationInput.value);
    button.disabled = busy || queued || durationInput.disabled ||
      !Number.isInteger(seconds) || seconds < 1 || seconds > 60;
  };
  document.addEventListener('aquacore:setting-saved', event => {
    if (event.detail?.field === 'fertilizer_duration_seconds') queueMicrotask(refresh);
  });
  button.addEventListener('click', async () => {
    if (busy || queued || button.disabled) return;
    const duration = Number(durationInput.dataset.saved ?? durationInput.value);
    if (!Number.isInteger(duration) || duration < 1 || duration > 60) return;
    if (!window.confirm('Run the fertilizer pump now for ' + duration +
          ' seconds? This is an EXTRA dose in addition to the daily schedule.')) return;
    busy = true;
    refresh();
    status.textContent = 'Sending manual dose request…';
    try {
      const response = await fetch('/api/fertilizer/dose', {
        method: 'POST',
        credentials: 'same-origin',
        headers: {'X-CSRF-Token': window.AQUACORE_CSRF, 'Content-Type': 'application/json'},
        body: '{}'
      });
      const result = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(result.error || 'HTTP ' + response.status);
      queued = true;
      status.textContent = 'Requested ' + result.duration_seconds +
        '-second manual dose. Check relay logs to confirm activation.';
    } catch (error) {
      status.textContent = 'Manual dose not requested: ' + error.message;
    } finally {
      busy = false;
      refresh();
    }
  });
  refresh();
})();
