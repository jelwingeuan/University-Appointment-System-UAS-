(() => {
    const escapeText = (value) => String(value ?? "");

    const confirmationDialog = document.getElementById("lecturer-confirm-dialog");
    const confirmationForm = document.getElementById("lecturer-confirm-form");
    if (confirmationDialog && confirmationForm) {
        document.addEventListener("click", (event) => {
            const trigger = event.target.closest("[data-lecturer-confirm]");
            if (!trigger) return;

            confirmationForm.action = trigger.dataset.confirmUrl;
            document.getElementById("lecturer-confirm-id").value = trigger.dataset.confirmId || "";
            document.getElementById("lecturer-confirm-title").textContent = trigger.dataset.confirmTitle || "Confirm appointment update";
            document.getElementById("lecturer-confirm-description").textContent = trigger.dataset.confirmMessage || "Confirm this appointment update?";
            const submit = document.getElementById("lecturer-confirm-submit");
            submit.textContent = trigger.dataset.confirmSubmit || "Confirm";
            submit.dataset.submitLabel = "Submitting…";
            submit.className = `btn btn-${trigger.dataset.confirmVariant || "danger"}`;
            window.UASUI?.openDialog(confirmationDialog, trigger);
        });
    }

    const recurrenceSelect = document.getElementById("eventRepeat");
    const eventDate = document.getElementById("eventDate");
    const endDate = document.getElementById("endDate");
    const recurrenceEnd = document.getElementById("recurrence-end-date");
    const recurrenceDescription = document.getElementById("recurrence-description");
    if (recurrenceSelect && eventDate && endDate && recurrenceEnd) {
        const updateRecurrence = () => {
            const repeats = recurrenceSelect.value !== "";
            recurrenceEnd.hidden = !repeats;
            endDate.disabled = !repeats;
            endDate.required = repeats;
            endDate.min = eventDate.value;
            if (!repeats) {
                endDate.value = "";
                recurrenceDescription.textContent = "Creates availability for this date only.";
            } else {
                if (!endDate.value || endDate.value < eventDate.value) endDate.value = eventDate.value;
                recurrenceDescription.textContent = recurrenceSelect.value === "weekly"
                    ? `Repeats weekly through ${endDate.value || "the selected end date"}.`
                    : `Repeats monthly through ${endDate.value || "the selected end date"}; short months use the closest valid day.`;
            }
        };
        recurrenceSelect.addEventListener("change", updateRecurrence);
        eventDate.addEventListener("change", updateRecurrence);
        endDate.addEventListener("change", () => {
            recurrenceDescription.textContent = recurrenceSelect.value === "weekly"
                ? `Repeats weekly through ${endDate.value}.`
                : `Repeats monthly through ${endDate.value}; short months use the closest valid day.`;
        });
        updateRecurrence();
    }

    const calendarElement = document.getElementById("calendar");
    if (!calendarElement || !window.FullCalendar) return;

    const calendarLoading = document.getElementById("calendar-loading");
    const calendarError = document.getElementById("calendar-error");
    const eventList = document.getElementById("lecturer-event-list");
    const configuredTimeZone = calendarElement.dataset.timeZone || "Asia/Kuala_Lumpur";
    const formatter = new Intl.DateTimeFormat(undefined, {
        timeZone: configuredTimeZone,
        dateStyle: "medium",
        timeStyle: "short",
    });
    const dateFormatter = new Intl.DateTimeFormat(undefined, {
        timeZone: configuredTimeZone,
        dateStyle: "medium",
    });
    const timeFormatter = new Intl.DateTimeFormat(undefined, {
        timeZone: configuredTimeZone,
        timeStyle: "short",
    });

    const displayRangeBoundary = (value) => escapeText(value).replace(/(?:Z|[+-]\d{2}:?\d{2})$/i, "");

    const renderEventList = (events) => {
        eventList.replaceChildren();
        if (!events.length) {
            const empty = document.createElement("li");
            empty.className = "lecturer-event-list-empty";
            empty.textContent = "No availability or accepted appointments in this calendar view.";
            eventList.append(empty);
            return;
        }

        events.forEach((item) => {
            const row = document.createElement("li");
            const start = new Date(item.start);
            const end = new Date(item.end);
            const range = `${dateFormatter.format(start)} · ${timeFormatter.format(start)}–${timeFormatter.format(end)}`;
            const text = document.createElement("span");
            if (item.extendedProps?.kind === "appointment") {
                text.textContent = `Accepted appointment: ${item.title}. ${range}.`;
                const link = document.createElement("a");
                link.href = item.extendedProps.detail_url;
                link.textContent = "View details";
                row.append(text, link);
            } else {
                const booked = item.extendedProps?.has_appointments;
                text.textContent = `Availability${booked ? " · contains appointments" : ""}. ${range}${booked ? ". Cannot be removed." : "."}`;
                row.append(text);
                if (!booked) {
                    const remove = document.createElement("button");
                    remove.className = "btn btn-ghost btn-sm";
                    remove.type = "button";
                    remove.textContent = "Remove availability";
                    remove.dataset.calendarRemoveAvailability = item.extendedProps.availability_id;
                    remove.dataset.start = item.start;
                    remove.dataset.end = item.end;
                    row.append(remove);
                }
            }
            eventList.append(row);
        });
    };

    const deleteDialog = document.getElementById("availability-delete-dialog");
    const deleteForm = document.getElementById("availability-delete-form");
    const deleteId = document.getElementById("availability-delete-id");
    const deleteDescription = document.getElementById("availability-delete-description");
    const openDeleteDialog = (trigger, availabilityId, startValue, endValue) => {
        if (!deleteDialog || !deleteId) return;
        deleteId.value = String(availabilityId || "");
        const start = startValue ? formatter.format(new Date(startValue)) : "this time";
        const end = endValue ? timeFormatter.format(new Date(endValue)) : "";
        deleteDescription.textContent = `Remove availability on ${start}${end ? ` until ${end}` : ""}? Availability with appointment history cannot be removed.`;
        window.UASUI?.openDialog(deleteDialog, trigger);
    };

    eventList.addEventListener("click", (event) => {
        const button = event.target.closest("[data-calendar-remove-availability]");
        if (button) {
            openDeleteDialog(button, button.dataset.calendarRemoveAvailability, button.dataset.start, button.dataset.end);
        }
    });

    if (deleteForm) {
        deleteForm.addEventListener("submit", async (event) => {
            event.preventDefault();
            const submit = deleteForm.querySelector('button[type="submit"]');
            submit.disabled = true;
            submit.setAttribute("aria-busy", "true");
            submit.textContent = "Removing…";
            try {
                const response = await fetch(deleteForm.action, {
                    method: "POST",
                    body: new FormData(deleteForm),
                    credentials: "same-origin",
                    headers: { Accept: "application/json" },
                });
                const result = await response.json().catch(() => ({}));
                if (!response.ok || result.status !== "success") {
                    throw new Error(result.message || "This availability could not be removed. Refresh the calendar and try again.");
                }
                window.UASUI?.closeDialog(deleteDialog);
                window.UASUI?.toast({ kind: "success", message: "Availability removed." });
                calendar.refetchEvents();
            } catch (error) {
                window.UASUI?.toast({ kind: "error", message: error.message || "This availability could not be removed." });
            } finally {
                submit.disabled = false;
                submit.removeAttribute("aria-busy");
                submit.textContent = "Remove availability";
            }
        });
    }

    const todayButton = "today";
    const mobile = window.matchMedia("(max-width: 639px)");
    const toolbar = () => mobile.matches
        ? { start: "prev,next", center: "title", end: todayButton }
        : { start: "prev,next today", center: "title", end: "dayGridMonth,timeGridWeek,timeGridDay" };
    const initialView = mobile.matches ? "timeGridDay" : "timeGridWeek";

    const calendar = new FullCalendar.Calendar(calendarElement, {
        timeZone: configuredTimeZone,
        initialDate: calendarElement.dataset.initialDate,
        initialView,
        headerToolbar: toolbar(),
        buttonIcons: false,
        buttonText: { prev: "Previous", next: "Next", today: "Today" },
        views: {
            dayGridMonth: { buttonText: "Month" },
            timeGridWeek: { buttonText: "Week" },
            timeGridDay: { buttonText: "Day" },
        },
        height: "auto",
        expandRows: true,
        nowIndicator: true,
        selectable: true,
        selectMirror: false,
        editable: false,
        eventStartEditable: false,
        eventDurationEditable: false,
        allDaySlot: false,
        dayMaxEvents: true,
        eventTimeFormat: { hour: "numeric", minute: "2-digit", hour12: true },
        events: async (fetchInfo, successCallback, failureCallback) => {
            calendarError.hidden = true;
            eventList.setAttribute("aria-busy", "true");
            const query = new URLSearchParams({
                start: displayRangeBoundary(fetchInfo.startStr),
                end: displayRangeBoundary(fetchInfo.endStr),
            });
            try {
                const response = await fetch(`${calendarElement.dataset.eventsUrl}?${query}`, {
                    credentials: "same-origin",
                    headers: { Accept: "application/json" },
                });
                if (!response.ok) throw new Error("Calendar request failed");
                const events = await response.json();
                renderEventList(events);
                successCallback(events);
            } catch {
                renderEventList([]);
                calendarError.hidden = false;
                failureCallback();
            } finally {
                eventList.setAttribute("aria-busy", "false");
            }
        },
        loading: (isLoading) => {
            calendarLoading.hidden = !isLoading;
        },
        select: (selection) => {
            const start = selection.startStr;
            const end = selection.endStr;
            document.getElementById("eventDate").value = start.slice(0, 10);
            document.getElementById("startTime").value = start.length > 10 ? start.slice(11, 16) : "09:00";
            document.getElementById("endTime").value = end.length > 10 ? end.slice(11, 16) : "10:00";
            document.getElementById("eventRepeat").value = "";
            document.getElementById("eventRepeat").dispatchEvent(new Event("change", { bubbles: true }));
            window.UASUI?.openDialog("availability-dialog", calendarElement);
            calendar.unselect();
        },
        dateClick: (info) => {
            if (info.allDay) {
                document.getElementById("eventDate").value = info.dateStr.slice(0, 10);
                document.getElementById("startTime").value = "09:00";
                document.getElementById("endTime").value = "10:00";
                window.UASUI?.openDialog("availability-dialog", calendarElement);
            }
        },
        eventClick: (info) => {
            const props = info.event.extendedProps;
            if (props.kind === "appointment") {
                window.location.assign(props.detail_url);
                return;
            }
            if (props.has_appointments) {
                window.UASUI?.toast({ kind: "warning", message: "This availability contains appointment history and cannot be removed." });
                return;
            }
            openDeleteDialog(info.el, props.availability_id, info.event.startStr, info.event.endStr);
        },
    });

    calendar.render();
    mobile.addEventListener("change", () => {
        calendar.setOption("headerToolbar", toolbar());
        calendar.changeView(mobile.matches ? "timeGridDay" : "timeGridWeek");
    });

    document.getElementById("availability-add-button")?.addEventListener("click", () => {
        document.getElementById("eventDate").value = "";
        document.getElementById("startTime").value = "";
        document.getElementById("endTime").value = "";
        document.getElementById("eventRepeat").value = "";
        document.getElementById("eventRepeat").dispatchEvent(new Event("change", { bubbles: true }));
    });
})();
