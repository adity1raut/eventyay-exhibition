document.addEventListener("DOMContentLoaded", () => {
    const table = document.querySelector(".exhibition-products-table");
    if (!table) return;

    // A product without an exhibition purpose has no booth, and an exhibition product
    // always has one, so the checkbox only makes sense for sponsorships.
    const syncBoothToggle = (row) => {
        const purpose = row.querySelector(".exhibition-purpose-input");
        const toggle = row.querySelector(".exhibition-booth-toggle");
        const input = row.querySelector(".exhibition-booth-input");
        if (!purpose || !toggle || !input) return;

        if (purpose.value === "sponsorship") {
            input.disabled = false;
            toggle.classList.remove("is-disabled");
            return;
        }

        input.checked = purpose.value === "exhibition";
        input.disabled = true;
        toggle.classList.add("is-disabled");
    };

    table.querySelectorAll(".exhibition-product-row").forEach((row) => {
        const purpose = row.querySelector(".exhibition-purpose-input");
        if (purpose) {
            purpose.addEventListener("change", () => syncBoothToggle(row));
        }
        syncBoothToggle(row);
    });
});
