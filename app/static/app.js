document.addEventListener("DOMContentLoaded", () => {
  document.querySelectorAll("[data-select-search]").forEach((input) => {
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
});
