(function () {
  var form = document.getElementById("mealplan-add-form");
  if (!form || !form.dataset.recipeSuggest) return;

  var searchInput = document.getElementById("mealplan-recipe-search");
  var hiddenId = document.getElementById("mealplan-recipe-id");
  var panel = document.getElementById("mealplan-suggest-panel");
  var picked = document.getElementById("mealplan-recipe-picked");
  var url = form.dataset.recipeSuggest;
  var timer = null;
  var hideTimer = null;

  function setExpanded(on) {
    searchInput.setAttribute("aria-expanded", on ? "true" : "false");
  }

  function hidePanel() {
    panel.classList.add("d-none");
    panel.innerHTML = "";
    setExpanded(false);
  }

  function showPanel() {
    panel.classList.remove("d-none");
    setExpanded(true);
  }

  function selectRecipe(id, name) {
    hiddenId.value = String(id);
    searchInput.value = name;
    picked.textContent = "Selected: " + name;
    picked.classList.remove("d-none");
    searchInput.classList.remove("is-invalid");
    document.getElementById("mealplan-recipe-err").classList.add("d-none");
    hidePanel();
  }

  function renderResults(recipes) {
    panel.innerHTML = "";
    if (!recipes.length) {
      var empty = document.createElement("div");
      empty.className = "small text-muted px-3 py-2";
      empty.textContent = "No matches. Try another word or open Discover to find recipes.";
      panel.appendChild(empty);
      showPanel();
      return;
    }
    recipes.forEach(function (r) {
      var btn = document.createElement("button");
      btn.type = "button";
      btn.className = "foodie-suggest-item";
      btn.setAttribute("role", "option");
      btn.dataset.id = r.id;
      btn.dataset.name = r.name;
      if (r.image_url) {
        var img = document.createElement("img");
        img.src = r.image_url;
        img.alt = "";
        img.className = "foodie-suggest-thumb";
        img.width = 40;
        img.height = 40;
        btn.appendChild(img);
      }
      var span = document.createElement("span");
      span.textContent = r.name;
      btn.appendChild(span);
      btn.addEventListener("click", function () {
        selectRecipe(r.id, r.name);
      });
      panel.appendChild(btn);
    });
    showPanel();
  }

  function fetchSuggest(q) {
    var sep = url.indexOf("?") >= 0 ? "&" : "?";
    fetch(url + sep + "q=" + encodeURIComponent(q), { credentials: "same-origin" })
      .then(function (res) {
        if (res.status === 401) return { recipes: [] };
        return res.json();
      })
      .then(function (data) {
        renderResults(data.recipes || []);
      })
      .catch(function () {
        renderResults([]);
      });
  }

  function scheduleFetch() {
    clearTimeout(timer);
    timer = setTimeout(function () {
      fetchSuggest(searchInput.value.trim());
    }, 220);
  }

  searchInput.addEventListener("input", function () {
    hiddenId.value = "";
    picked.classList.add("d-none");
    searchInput.classList.remove("is-invalid");
    document.getElementById("mealplan-recipe-err").classList.add("d-none");
    scheduleFetch();
  });

  searchInput.addEventListener("focus", function () {
    scheduleFetch();
  });

  searchInput.addEventListener("blur", function () {
    clearTimeout(hideTimer);
    hideTimer = setTimeout(hidePanel, 200);
  });

  panel.addEventListener("mousedown", function (e) {
    e.preventDefault();
  });

  form.addEventListener("submit", function (e) {
    if (!hiddenId.value.trim()) {
      e.preventDefault();
      searchInput.classList.add("is-invalid");
      document.getElementById("mealplan-recipe-err").classList.remove("d-none");
      searchInput.focus();
    }
  });

  document.addEventListener("click", function (e) {
    if (!form.contains(e.target)) hidePanel();
  });
})();

(function () {
  var alertBox = document.getElementById("mealplan-delete-alert");
  function showDeleteErr(msg) {
    if (!alertBox) return;
    alertBox.textContent = msg;
    alertBox.classList.remove("d-none");
  }
  function hideDeleteErr() {
    if (!alertBox) return;
    alertBox.classList.add("d-none");
    alertBox.textContent = "";
  }

  document.querySelectorAll("[data-mealplan-clear-day]").forEach(function (btn) {
    btn.addEventListener("click", function () {
      var day = btn.getAttribute("data-mealplan-clear-day");
      if (day === null || day === "") return;
      hideDeleteErr();
      btn.disabled = true;
      var prevLabel = btn.textContent;
      btn.textContent = "Clearing…";

      var csrfMeta = document.querySelector('meta[name="csrf-token"]');
      var csrfVal = csrfMeta ? csrfMeta.getAttribute("content") : "";
      fetch("/mealplan/" + encodeURIComponent(day), {
        method: "DELETE",
        credentials: "same-origin",
        redirect: "manual",
        headers: {
          Accept: "text/html, application/json",
          "X-CSRFToken": csrfVal,
        },
      })
        .then(function (res) {
          if (res.status === 404) {
            showDeleteErr("Nothing was planned for that day (or it was already cleared).");
            return;
          }
          if (res.status === 401) {
            window.location.href = "/login";
            return;
          }
          if (res.status === 302 || res.status === 303) {
            var loc = res.headers.get("Location");
            if (loc) {
              window.location.href = loc;
              return;
            }
            window.location.reload();
            return;
          }
          if (res.ok) {
            window.location.reload();
            return;
          }
          showDeleteErr("Could not clear that day. Please try again.");
        })
        .catch(function () {
          showDeleteErr("Network error while clearing the day. Check your connection and try again.");
        })
        .finally(function () {
          btn.disabled = false;
          btn.textContent = prevLabel;
        });
    });
  });
})();
