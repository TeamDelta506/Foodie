(function () {
  var btn = document.getElementById("btn-scale-recipe");
  var section = document.getElementById("ingredients-section");
  if (!btn || !section) return;
  var scaleUrl = section.getAttribute("data-scale-url");
  var recipeId = parseInt(section.getAttribute("data-recipe-id"), 10);
  if (!scaleUrl || !Number.isFinite(recipeId)) return;

  function formatQty(q) {
    if (typeof q !== "number" || !Number.isFinite(q)) return "";
    var rounded = Math.round(q * 100) / 100;
    return rounded % 1 === 0 ? String(Math.round(rounded)) : String(rounded);
  }

  btn.addEventListener("click", function () {
    var input = document.getElementById("target_servings");
    var status = document.getElementById("scale-ingredients-status");
    var tbody = document.getElementById("ingredients-tbody");
    if (!tbody || !status) return;

    var servings = parseInt(input && input.value, 10);
    if (!Number.isFinite(servings) || servings < 1) {
      status.classList.remove("d-none", "text-success");
      status.classList.add("text-danger");
      status.textContent = "Enter a positive number of servings.";
      return;
    }

    status.classList.add("d-none");
    btn.disabled = true;

    fetch(scaleUrl, {
      method: "POST",
      credentials: "same-origin",
      redirect: "manual",
      headers: {
        "Content-Type": "application/json",
        Accept: "application/json",
      },
      body: JSON.stringify({ recipe_id: recipeId, target_servings: servings }),
    })
      .then(function (res) {
        if (res.status === 302 || res.status === 303) {
          window.location.href = res.headers.get("Location") || "/login";
          return Promise.reject(new Error("redirect"));
        }
        return res.json().then(function (data) {
          if (!res.ok) {
            var msg =
              data && data.message ? data.message : "Could not update quantities.";
            status.classList.remove("d-none", "text-success");
            status.classList.add("text-danger");
            status.textContent = msg;
            return;
          }
          var list = data.ingredients || [];
          var qtyCells = tbody.querySelectorAll(".js-ing-qty");
          for (var i = 0; i < qtyCells.length && i < list.length; i++) {
            qtyCells[i].textContent = formatQty(list[i].quantity);
            var row = qtyCells[i].closest("tr");
            var unitCell = row ? row.querySelector(".js-ing-unit") : null;
            if (unitCell && list[i].unit) unitCell.textContent = list[i].unit;
          }
          status.classList.remove("d-none", "text-danger");
          status.classList.add("text-success");
          status.textContent =
            "Quantities updated for " +
            servings +
            " serving(s) (from the server). Reload the page to restore the default list.";
        });
      })
      .catch(function (err) {
        if (err && err.message === "redirect") return;
        status.classList.remove("d-none", "text-success");
        status.classList.add("text-danger");
        status.textContent =
          "Could not update quantities. Check your connection and try again.";
      })
      .finally(function () {
        btn.disabled = false;
      });
  });
})();
