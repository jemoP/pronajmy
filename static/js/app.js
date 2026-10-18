// Formulář pohybu: zobrazí jen pole, která druh používá, a nabídne účely daného druhu.
(function () {
  "use strict";

  function sync(form, kindChanged) {
    const kind = form.elements.kind.value;
    form.querySelectorAll("[data-kinds]").forEach((label) => {
      const needed = label.dataset.kinds.split(" ").includes(kind);
      label.hidden = !needed;
      label.querySelector("select").disabled = !needed;
    });
    const accountLabel = form.querySelector("[data-label-transfer]");
    if (accountLabel) accountLabel.textContent = kind === "TRANSFER" ? "Z účtu" : "Účet";
    const select = form.elements.category_id;
    for (const option of select.options) {
      const optionKind = option.dataset.kind;
      // Náklad smí mít i účel druhu příjem – vrácení příjmu (ZM-003).
      const allowed = !optionKind || optionKind === kind || optionKind === "NEUTRAL"
        || (kind === "EXPENSE" && optionKind === "INCOME");
      if (!allowed && option.selected && kindChanged) select.value = "";
      // Už vybraný účel jiného druhu zůstane viditelný, aby šla chyba opravit.
      const hide = !allowed && !option.selected;
      option.hidden = hide;
      option.disabled = hide;
    }
  }

  function init(root) {
    root.querySelectorAll("form.entry-form").forEach((form) => sync(form, false));
  }

  document.addEventListener("change", (event) => {
    const target = event.target;
    if (target.name === "kind" && target.form && target.form.classList.contains("entry-form")) {
      sync(target.form, true);
    }
  });
  document.addEventListener("DOMContentLoaded", () => init(document));
  document.addEventListener("htmx:load", (event) => init(event.detail.elt));
})();

// Přílohy: vedle tlačítka „Vybrat soubory“ ukáže, co je vybrané.
(function () {
  "use strict";

  function label(files) {
    if (!files.length) return "Nic nevybráno";
    if (files.length === 1) return files[0].name;
    const n = files.length;
    const word = n < 5 ? "soubory" : "souborů";
    return `${n} ${word}: ${Array.from(files, (f) => f.name).join(", ")}`;
  }

  document.addEventListener("change", (event) => {
    const input = event.target;
    if (!input.matches || !input.matches("input[data-file-input]")) return;
    const names = input.form && input.form.querySelector("[data-file-names]");
    if (names) names.textContent = label(input.files);
  });
})();

// Platba z předpisů (ZM-005) a splátek (ZM-006): počet a součet označených položek.
(function () {
  "use strict";
  const czk = new Intl.NumberFormat("cs-CZ", { style: "currency", currency: "CZK" });

  function summary(form) {
    const boxes = document.querySelectorAll(`input[data-amount][form="${form.id}"]:checked`);
    const target = form.querySelector("[data-selected-summary]");
    if (!target) return;
    if (!boxes.length) {
      target.textContent = "Označeno: nic";
      return;
    }
    const total = Array.from(boxes).reduce((sum, box) => sum + Number(box.dataset.amount), 0);
    const n = boxes.length;
    const words = (form.dataset.words || "předpis,předpisy,předpisů").split(",");
    const word = n === 1 ? words[0] : n < 5 ? words[1] : words[2];
    target.textContent = `Označeno: ${n} ${word}, ${czk.format(total / 100)}`;
  }

  document.addEventListener("change", (event) => {
    const box = event.target;
    if (!box.matches || !box.matches("input[data-amount][form]")) return;
    const form = document.getElementById(box.getAttribute("form"));
    if (form) summary(form);
  });
})();
