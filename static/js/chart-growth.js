// تحديث حي لإجمالي الحجوزات والكمية المتاحة + تنبيه "حجز جديد" وتأثير نبضة على الرقم
document.addEventListener("DOMContentLoaded", function () {
  const box = document.querySelector(".growth-box");
  if (!box) return;

  const endpoint = box.dataset.endpoint;
  const totalEl = document.getElementById("growth-total");
  const remainingEl = document.getElementById("growth-remaining");
  const toastEl = document.getElementById("growth-toast");

  let previousTotal = null;
  let toastTimer = null;

  function showToast() {
    if (!toastEl) return;
    toastEl.classList.add("show");
    clearTimeout(toastTimer);
    toastTimer = setTimeout(function () {
      toastEl.classList.remove("show");
    }, 2600);
  }

  function pulseTotal() {
    if (!totalEl) return;
    totalEl.classList.remove("pulse");
    void totalEl.offsetWidth; // إعادة تشغيل الحركة
    totalEl.classList.add("pulse");
  }

  function refresh() {
    if (!endpoint || document.hidden) return; // لا تحديث لو التاب مخفي (يوفّر حصة نقل البيانات)
    fetch(endpoint)
      .then(function (res) { return res.json(); })
      .then(function (data) {
        if (totalEl && typeof data.reserved !== "undefined") totalEl.textContent = data.reserved;
        if (remainingEl && typeof data.remaining !== "undefined") remainingEl.textContent = data.remaining;

        if (previousTotal !== null && data.reserved > previousTotal) {
          showToast();
          pulseTotal();
        }
        previousTotal = data.reserved;
      })
      .catch(function () {
        /* تجاهل أخطاء الشبكة المؤقتة */
      });
  }

  refresh();
  setInterval(refresh, 30000); // تحديث كل 30 ثانية بدل 8 (يقلّل استهلاك حصة النقل الشهرية بشكل كبير)
  document.addEventListener("visibilitychange", function () {
    if (!document.hidden) refresh(); // حدّث فوراً لما الزائر يرجع للتاب
  });
});
