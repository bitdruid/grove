document.addEventListener('DOMContentLoaded', function () {
    // Dismiss flash alerts by collapsing the whole wrapper (auto after 5s or on
    // the close button) — removing only the inner .alert left the wrapper's mt-3
    // margin behind as a persistent gap until reload.
    document.querySelectorAll('.flash-alert').forEach(wrapper => {
        const dismiss = () => {
            wrapper.classList.add('alert-slideup');
            setTimeout(() => wrapper.remove(), 500); // match the CSS transition duration
        };
        const timer = setTimeout(dismiss, 5000);
        const btn = wrapper.querySelector('.btn-close');
        if (btn) btn.addEventListener('click', () => { clearTimeout(timer); dismiss(); });
    });
});
