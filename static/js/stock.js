// تحديث حي لعداد الكمية المتاحة (بدون تحديث الصفحة)
document.addEventListener("DOMContentLoaded", function () {
  const box = document.getElementById("stock-box");
  if (!box) return;

  const endpoint = box.dataset.endpoint;
  const remainingEl = document.getElementById("stock-remaining");
  const percentEl = document.getElementById("stock-percent");
  const fillEl = document.getElementById("stock-bar-fill");
  const soldoutEl = document.getElementById("stock-soldout");
  const reserveBtn = document.querySelector('.reserve-box button[type="submit"]');

  function applyStock(data) {
    remainingEl.textContent = data.remaining;
    percentEl.textContent = data.percent + "%";
    fillEl.style.width = data.percent + "%";

    const growthRemainingEl = document.getElementById("growth-remaining");
    if (growthRemainingEl) growthRemainingEl.textContent = data.remaining;

    if (data.sold_out) {
      soldoutEl.style.display = "block";
      if (reserveBtn) {
        reserveBtn.disabled = true;
        reserveBtn.textContent = "نفدت الكمية بالكامل";
      }
    } else {
      soldoutEl.style.display = "none";
    }
  }

  function fetchStock() {
    if (document.hidden) return; // لا داعي للتحديث لو التاب مو مفتوح فعلياً (يوفّر حصة نقل البيانات)
    fetch(endpoint)
      .then((res) => res.json())
      .then(applyStock)
      .catch(() => {
        /* تجاهل أخطاء الشبكة المؤقتة */
      });
  }

  fetchStock();
  setInterval(fetchStock, 30000); // تحديث كل 30 ثانية بدل 8 (يقلّل استهلاك حصة النقل الشهرية بشكل كبير)
  document.addEventListener("visibilitychange", function () {
    if (!document.hidden) fetchStock(); // حدّث فوراً لما الزائر يرجع للتاب
  });
});
