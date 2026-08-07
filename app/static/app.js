function bindInteractiveFields(root = document) {
  root.querySelectorAll("[data-select-search]").forEach((input) => {
    if (input.dataset.bound) return;
    input.dataset.bound = "true";
    const select = document.getElementById(input.dataset.selectSearch);
    if (!select) return;
    input.addEventListener("input", () => {
      const query = input.value.trim().toLocaleLowerCase();
      let visibleCount = 0;
      Array.from(select.options).forEach((option, index) => {
        if (index === 0) {
          option.hidden = false;
          return;
        }
        const visible = !query || option.text.toLocaleLowerCase().includes(query);
        option.hidden = !visible;
        if (visible) visibleCount += 1;
      });
      select.dataset.empty = visibleCount === 0 ? "true" : "false";
    });
  });

  root.querySelectorAll("[data-checkbox-search]").forEach((input) => {
    if (input.dataset.bound) return;
    input.dataset.bound = "true";
    const container = document.getElementById(input.dataset.checkboxSearch);
    if (!container) return;
    input.addEventListener("input", () => {
      const query = input.value.trim().toLocaleLowerCase();
      container.querySelectorAll(".site-choice").forEach((choice) => {
        choice.hidden = Boolean(query) && !choice.dataset.searchText.toLocaleLowerCase().includes(query);
      });
    });
  });

  root.querySelectorAll("[data-check-all]").forEach((input) => {
    if (input.dataset.bound) return;
    input.dataset.bound = "true";
    const container = document.getElementById(input.dataset.checkAll);
    if (!container) return;
    input.addEventListener("change", () => {
      container.querySelectorAll(".site-choice:not([hidden]) input[type=checkbox]").forEach((checkbox) => {
        checkbox.checked = input.checked;
      });
    });
  });
}

document.addEventListener("DOMContentLoaded", () => bindInteractiveFields());
document.addEventListener("htmx:afterSwap", (event) => bindInteractiveFields(event.detail.target));

function syncConditionalFields(root = document) {
  root.querySelectorAll("[data-show-when-value]").forEach((field) => {
    const source = document.querySelector(field.dataset.showWhenValue);
    if (!source) return;
    const target = field;
    const expected = field.dataset.showWhenMatch;
    const apply = () => {
      const current = source.type === "checkbox" ? (source.checked ? "on" : "") : source.value;
      const show = current === expected;
      target.hidden = !show;
      if (!show) target.querySelectorAll("input,textarea,select").forEach((input) => (input.required = false));
    };
    apply();
    source.addEventListener("change", apply);
  });
}

document.addEventListener("DOMContentLoaded", () => syncConditionalFields());
document.addEventListener("htmx:afterSwap", (event) => syncConditionalFields(event.detail.target));
