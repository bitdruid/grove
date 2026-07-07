/*
 * datepicker - small month/year picker
 *
 * usage:
 *   const picker = datePicker(inputEl, {
 *     onChange: (value) => {...},   // value is "YYYY-MM" or ""
 *     getMin: () => otherInput.value || null,  // re-read on every render
 *     getMax: () => otherInput.value || null,
 *   });
 */
(function (global) {
    const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

    function parse(value) {
        if (!value) return null;
        const [y, m] = value.split("-").map(Number);
        if (!y || !m) return null;
        return { year: y, month: m - 1 };
    }

    function format(year, month) {
        return `${year}-${String(month + 1).padStart(2, "0")}`;
    }

    function datePicker(input, opts) {
        opts = opts || {};
        let popup = null;
        let viewYear = new Date().getFullYear();

        function bounds() {
            return {
                min: opts.getMin ? parse(opts.getMin()) : null,
                max: opts.getMax ? parse(opts.getMax()) : null,
            };
        }

        function inBounds(year, month) {
            const { min, max } = bounds();
            const key = year * 12 + month;
            if (min && key < min.year * 12 + min.month) return false;
            if (max && key > max.year * 12 + max.month) return false;
            return true;
        }

        function yearHasOpenMonth(year) {
            for (let m = 0; m < 12; m++) if (inBounds(year, m)) return true;
            return false;
        }

        function render() {
            const sel = parse(input.value);
            const now = new Date();
            popup.querySelector(".datepicker-year").textContent = viewYear;
            popup.querySelectorAll(".datepicker-month").forEach((btn, i) => {
                btn.disabled = !inBounds(viewYear, i);
                btn.classList.toggle("selected", !!sel && sel.year === viewYear && sel.month === i);
                btn.classList.toggle("today", viewYear === now.getFullYear() && i === now.getMonth());
            });
            popup.querySelector(".datepicker-prev-year").disabled = !yearHasOpenMonth(viewYear - 1);
            popup.querySelector(".datepicker-next-year").disabled = !yearHasOpenMonth(viewYear + 1);
        }

        function position() {
            const r = input.getBoundingClientRect();
            popup.style.top = `${window.scrollY + r.bottom + 4}px`;
            popup.style.left = `${window.scrollX + r.left}px`;
        }

        function onOutsideClick(e) {
            if (popup && !popup.contains(e.target) && e.target !== input) close();
        }

        function onKeydown(e) {
            if (e.key === "Escape") close();
        }

        function onReposition() {
            if (popup) position();
        }

        function open() {
            if (input.disabled || popup) return;
            const sel = parse(input.value);
            viewYear = sel ? sel.year : new Date().getFullYear();

            popup = document.createElement("div");
            popup.className = "datepicker-popup";
            popup.innerHTML =
                '<div class="datepicker-header" title="Scroll to change year">' +
                '<span class="datepicker-nav datepicker-prev-year">‹</span>' +
                '<span class="datepicker-year-group">' +
                '<span class="datepicker-year"></span>' +
                '<i class="bi bi-mouse2-fill datepicker-scroll-hint"></i>' +
                "</span>" +
                '<span class="datepicker-nav datepicker-next-year">›</span>' +
                "</div>" +
                '<div class="datepicker-grid">' +
                MONTHS.map((m) => `<button type="button" class="datepicker-month">${m}</button>`).join("") +
                "</div>";
            document.body.appendChild(popup);
            position();
            render();

            function stepYear(dir) {
                if (!yearHasOpenMonth(viewYear + dir)) return;
                viewYear += dir;
                render();
            }

            popup.querySelector(".datepicker-prev-year").addEventListener("click", () => stepYear(-1));
            popup.querySelector(".datepicker-next-year").addEventListener("click", () => stepYear(1));
            popup.querySelector(".datepicker-header").addEventListener(
                "wheel",
                (e) => {
                    e.preventDefault();
                    stepYear(e.deltaY < 0 ? 1 : -1);
                },
                { passive: false },
            );
            popup.querySelectorAll(".datepicker-month").forEach((btn, i) => {
                btn.addEventListener("click", () => {
                    if (btn.disabled) return;
                    setValue(format(viewYear, i));
                    close();
                });
            });

            document.addEventListener("mousedown", onOutsideClick, true);
            document.addEventListener("keydown", onKeydown, true);
            window.addEventListener("scroll", onReposition, true);
            window.addEventListener("resize", onReposition);
        }

        function close() {
            if (!popup) return;
            popup.remove();
            popup = null;
            document.removeEventListener("mousedown", onOutsideClick, true);
            document.removeEventListener("keydown", onKeydown, true);
            window.removeEventListener("scroll", onReposition, true);
            window.removeEventListener("resize", onReposition);
        }

        function setValue(value) {
            input.value = value;
            input.dispatchEvent(new Event("change", { bubbles: true }));
            if (opts.onChange) opts.onChange(value);
        }

        input.readOnly = true;
        input.addEventListener("click", open);

        return {
            close,
            setValue,
            get value() {
                return input.value;
            },
        };
    }

    global.datePicker = datePicker;
})(window);
