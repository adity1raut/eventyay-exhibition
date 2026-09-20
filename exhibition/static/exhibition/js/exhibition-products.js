document.addEventListener("DOMContentLoaded", () => {
    const table = document.querySelector(".exhibition-products-table");
    if (!table) return;

    // A product without an exhibition purpose has no booth, and an exhibition product
    // always has one, so the checkbox only makes sense for sponsorships.
    const syncBoothToggle = (row, purposeChanged = false) => {
        const purpose = row.querySelector(".exhibition-purpose-input");
        const toggle = row.querySelector(".exhibition-booth-toggle");
        const input = row.querySelector(".exhibition-booth-input");
        if (!purpose || !toggle || !input) return;

        if (purpose.value === "sponsorship") {
            // A sponsorship comes with a booth unless the organiser turns it off, so a
            // product that has just become one starts with the box ticked. A sponsorship
            // that is already saved without a booth keeps the answer it was given.
            if (purposeChanged) {
                input.checked = row.dataset.sponsorshipBooth !== "off";
            }
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
        const booth = row.querySelector(".exhibition-booth-input");
        if (booth) {
            if (purpose && purpose.value === "sponsorship") {
                row.dataset.sponsorshipBooth = booth.checked ? "on" : "off";
            }
            booth.addEventListener("change", () => {
                row.dataset.sponsorshipBooth = booth.checked ? "on" : "off";
            });
        }
        if (purpose) {
            purpose.addEventListener("change", () => syncBoothToggle(row, true));
        }
        syncBoothToggle(row);
    });
});
