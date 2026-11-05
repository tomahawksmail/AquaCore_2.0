"use strict";
(() => {
  const host = document.getElementById("fertilizer-weekdays");
  const save = document.getElementById("fertilizer-weekly-save");
  const count = document.getElementById("fertilizer-weekly-count");
  const feedback = document.getElementById("fertilizer-weekly-feedback");
  if (!host || !save || !count || !feedback) return;
  const inputs = [...host.querySelectorAll('input[type="checkbox"]')];
  const chosen = () => inputs.filter(i => i.checked).map(i => Number(i.value));
  const refresh = () => {
    const n = chosen().length;
    count.textContent = n + (n === 1 ? " time" : " times") + " per week";
  };
  inputs.forEach(i => i.addEventListener("change", refresh));
  refresh();
  save.addEventListener("click", async () => {
    save.disabled = true;
    feedback.textContent = "Saving weekly schedule…";
    try {
      const response = await fetch("/api/fertilizer/schedule/days", {
        method: "POST", credentials: "same-origin",
        headers: {"Content-Type": "application/json", "X-CSRF-Token": window.AQUACORE_CSRF},
        body: JSON.stringify({days: chosen()})
      });
      const result = await response.json();
      if (!response.ok) throw new Error(result.error || "Save failed");
      feedback.textContent = "Saved: " + result.times_per_week + " dose(s) per week. Pump is not triggered.";
    } catch (error) {
      feedback.textContent = "Not saved: " + error.message;
    } finally { save.disabled = false; }
  });
})();
