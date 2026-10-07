(() => {
    const form = document.getElementById("student-booking-form");
    if (!form) return;

    const faculty = document.getElementById("faculty-select");
    const lecturer = document.getElementById("lecturer-select");
    const date = document.getElementById("appointment-date");
    const slots = document.getElementById("time-slots");
    const feedback = document.getElementById("slot-feedback");
    const purpose = document.getElementById("appointment-purpose");
    const availabilityId = document.getElementById("booking-availability-id");
    const slotStart = document.getElementById("booking-slot-start");
    let controller;
    let reviewApproved = false;

    const setText = (id, value) => {
        document.getElementById(id).textContent = value || "Not selected";
    };

    const clearSlot = () => {
        availabilityId.value = "";
        slotStart.value = "";
        slots.replaceChildren();
        setText("summary-time", "Not selected");
    };

    const filterLecturers = () => {
        const selectedFaculty = faculty.value;
        for (const option of lecturer.options) {
            if (!option.value) continue;
            const visible = !selectedFaculty || option.dataset.facultyId === selectedFaculty;
            option.hidden = !visible;
            option.disabled = !visible;
        }
        if (lecturer.selectedOptions[0]?.disabled) lecturer.value = "";
    };

    const updateSummary = () => {
        setText("summary-faculty", faculty.selectedOptions[0]?.textContent.trim());
        setText("summary-lecturer", lecturer.selectedOptions[0]?.textContent.trim());
        const selectedDate = date.value;
        setText(
            "summary-date",
            selectedDate
                ? new Intl.DateTimeFormat(undefined, { dateStyle: "medium" }).format(new Date(`${selectedDate}T12:00:00`))
                : "Not selected",
        );
    };

    const renderSlots = (items) => {
        slots.replaceChildren();
        for (const item of items) {
            const label = document.createElement("label");
            label.className = `student-slot-option${item.available ? "" : " is-unavailable"}`;
            const text = document.createElement("span");
            text.textContent = item.available ? item.label : `${item.label} · Unavailable`;
            if (item.available) {
                const input = document.createElement("input");
                input.type = "radio";
                input.name = "slot-selection";
                input.value = item.starts_at;
                input.dataset.availabilityId = item.availability_id;
                input.dataset.label = item.label;
                input.required = true;
                input.addEventListener("change", () => {
                    availabilityId.value = item.availability_id;
                    slotStart.value = item.starts_at;
                    setText("summary-time", item.label);
                    feedback.textContent = "Time selected.";
                });
                label.append(input, text);
            } else {
                label.setAttribute("aria-disabled", "true");
                label.append(text);
            }
            slots.append(label);
        }
    };

    const loadSlots = async () => {
        if (controller) controller.abort();
        clearSlot();
        updateSummary();
        if (!lecturer.value || !date.value) {
            feedback.textContent = "Choose a lecturer and date to find available times.";
            return;
        }

        controller = new AbortController();
        feedback.textContent = "Finding available times…";
        slots.setAttribute("aria-busy", "true");
        const params = new URLSearchParams({ lecturer: lecturer.value, appointment_date: date.value });
        try {
            const response = await fetch(`${form.dataset.slotsUrl}?${params}`, {
                headers: { Accept: "application/json" },
                signal: controller.signal,
            });
            if (!response.ok) throw new Error("The available times could not be loaded.");
            const result = await response.json();
            renderSlots(result.slots || []);
            feedback.textContent = result.slots?.some((item) => item.available)
                ? "Choose an available time. Times are shown in the university timezone."
                : "No available times for this date. Try another date or lecturer.";
        } catch (error) {
            if (error.name !== "AbortError") feedback.textContent = error.message || "The available times could not be loaded.";
        } finally {
            slots.removeAttribute("aria-busy");
        }
    };

    faculty.addEventListener("change", () => {
        filterLecturers();
        clearSlot();
        updateSummary();
        if (lecturer.value && date.value) loadSlots();
    });
    lecturer.addEventListener("change", loadSlots);
    date.addEventListener("change", loadSlots);
    purpose.addEventListener("input", () => {
        document.getElementById("purpose-count").textContent = `${purpose.value.length} / 500`;
    });

    form.addEventListener("submit", (event) => {
        if (!availabilityId.value || !slotStart.value) {
            event.preventDefault();
            feedback.textContent = "Choose an available appointment time before continuing.";
            document.querySelector("#time-heading").scrollIntoView({ block: "center" });
            return;
        }
        if (!purpose.value.trim()) {
            event.preventDefault();
            purpose.focus();
            return;
        }
        if (!reviewApproved) {
            event.preventDefault();
            updateSummary();
            setText("review-lecturer", lecturer.selectedOptions[0]?.textContent.trim());
            setText("review-faculty", faculty.selectedOptions[0]?.textContent.trim());
            setText("review-date", document.getElementById("summary-date").textContent);
            setText("review-time", document.getElementById("summary-time").textContent);
            setText("review-purpose", purpose.value.trim());
            window.UASUI.openDialog("booking-review-dialog", document.getElementById("review-request-button"));
            return;
        }
        reviewApproved = false;
    });

    document.querySelector("[data-booking-confirm]").addEventListener("click", () => {
        reviewApproved = true;
        window.UASUI.closeDialog("booking-review-dialog");
        form.requestSubmit();
    });

    filterLecturers();
    updateSummary();
    document.getElementById("purpose-count").textContent = `${purpose.value.length} / 500`;
    if (lecturer.value && date.value) loadSlots();
})();
