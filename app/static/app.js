/* UI del firmante NIP-46: jQuery + AJAX contra la API en /api. */
$(function () {
  "use strict";

  var API = "/api";
  var POLL_MS = 3000;
  var selected = null;   // pubkey hex de la clave seleccionada
  var keys = [];
  var pollTimer = null;

  // --- utilidades -----------------------------------------------------------

  function api(method, path, body) {
    return $.ajax({
      url: API + path,
      method: method,
      contentType: body ? "application/json" : undefined,
      data: body ? JSON.stringify(body) : undefined,
      dataType: method === "DELETE" ? "text" : "json"
    });
  }

  function errorMessage(xhr) {
    var detail = xhr.responseJSON && xhr.responseJSON.detail;
    if (Array.isArray(detail)) return detail.map(function (d) { return d.msg; }).join(", ");
    return detail || ("Error " + xhr.status);
  }

  var toastTimer = null;
  function toast(msg, isError) {
    var $t = $("#toast").text(msg).toggleClass("error", !!isError).removeClass("hidden");
    clearTimeout(toastTimer);
    toastTimer = setTimeout(function () { $t.addClass("hidden"); }, 3500);
  }

  function copy(text) {
    navigator.clipboard.writeText(text).then(
      function () { toast("Copiado al portapapeles"); },
      function () { toast("No se pudo copiar", true); }
    );
  }

  function short(hex) { return hex.slice(0, 8) + "…" + hex.slice(-6); }

  function time(ts) {
    return new Date(ts * 1000).toLocaleTimeString();
  }

  function busy($btn, on) { $btn.prop("disabled", on); }

  // --- claves ---------------------------------------------------------------

  function loadKeys() {
    return api("GET", "/keys").done(function (data) {
      keys = data;
      renderKeys();
      if (selected && !keys.some(function (k) { return k.pubkey === selected; })) select(null);
    }).fail(function (xhr) { toast(errorMessage(xhr), true); });
  }

  function renderKeys() {
    var $list = $("#key-list").empty();
    $("#key-empty").toggleClass("hidden", keys.length > 0);
    keys.forEach(function (k) {
      $("<li>")
        .toggleClass("selected", k.pubkey === selected)
        .attr("data-pubkey", k.pubkey)
        .append($("<div class='key-name'>").text(k.name))
        .append($("<div class='key-npub mono'>").text(k.npub.slice(0, 20) + "…" + k.npub.slice(-6)))
        .appendTo($list);
    });
  }

  function currentKey() {
    return keys.find(function (k) { return k.pubkey === selected; });
  }

  function select(pubkey) {
    selected = pubkey;
    renderKeys();
    clearInterval(pollTimer);
    $("#bunker-box").addClass("hidden");
    var key = currentKey();
    $("#signer-empty").toggleClass("hidden", !!key);
    $("#signer-panel").toggleClass("hidden", !key);
    if (!key) return;
    $("#signer-name").text(key.name);
    $("#signer-npub").text(key.npub);
    refreshSigner();
    pollTimer = setInterval(refreshSigner, POLL_MS);
  }

  function createKey($form, body) {
    var $btn = $form.find("button[type=submit]");
    busy($btn, true);
    api("POST", "/keys", body).done(function (key) {
      $form[0].reset();
      toast("Clave guardada: " + key.name);
      loadKeys().done(function () { select(key.pubkey); });
    }).fail(function (xhr) {
      toast(errorMessage(xhr), true);
    }).always(function () { busy($btn, false); });
  }

  // --- firmante -------------------------------------------------------------

  function refreshSigner() {
    if (!selected) return;
    var pubkey = selected;
    api("GET", "/keys/" + pubkey + "/status").done(function (s) {
      if (pubkey === selected) renderStatus(s);
    });
    api("GET", "/keys/" + pubkey + "/activity").done(function (items) {
      if (pubkey === selected) renderActivity(items);
    });
  }

  function renderStatus(status) {
    var $relays = $("#relay-list").empty();
    $.each(status.relays, function (url, connected) {
      $("<li>")
        .append($("<span class='dot'>").toggleClass("on", connected))
        .append($("<span class='mono'>").text(url))
        .attr("title", connected ? "Conectado" : "Desconectado")
        .appendTo($relays);
    });

    var $clients = $("#client-list").empty();
    $("#client-empty").toggleClass("hidden", status.clients.length > 0);
    status.clients.forEach(function (c) {
      $("<li>")
        .append($("<span>")
          .append($("<span class='mono'>").text(c.name || short(c.pubkey)))
          .append($("<span class='muted'>").text(" · " + c.via + " · " + time(c.last_seen))))
        .append($("<button class='btn small danger revoke'>Revocar</button>").attr("data-client", c.pubkey))
        .appendTo($clients);
    });
  }

  function renderActivity(items) {
    var $body = $("#activity-body").empty();
    $("#activity-empty").toggleClass("hidden", items.length > 0);
    items.forEach(function (a) {
      $("<tr>")
        .append($("<td>").text(time(a.at)))
        .append($("<td class='mono'>").text(a.method))
        .append($("<td class='mono'>").text(short(a.client)))
        .append($("<td>")
          .append($("<span class='badge'>").addClass(a.ok ? "ok" : "err").text(a.ok ? "ok" : "error"))
          .append(a.detail ? $("<span class='muted'>").text(" " + a.detail) : null))
        .appendTo($body);
    });
  }

  // --- eventos --------------------------------------------------------------

  $(".tab").on("click", function () {
    var tab = $(this).data("tab");
    $(".tab").removeClass("active");
    $(this).addClass("active");
    $(".tab-panel").addClass("hidden").filter("[data-panel=" + tab + "]").removeClass("hidden");
  });

  $("#form-generate").on("submit", function (e) {
    e.preventDefault();
    createKey($(this), { name: this.name.value.trim() || null });
  });

  $("#form-import").on("submit", function (e) {
    e.preventDefault();
    createKey($(this), { name: this.name.value.trim() || null, secret: this.secret.value.trim() });
  });

  $("#key-list").on("click", "li", function () { select($(this).attr("data-pubkey")); });

  $("#copy-npub").on("click", function () { copy(currentKey().npub); });

  $("#delete-key").on("click", function () {
    var key = currentKey();
    if (!confirm("¿Eliminar la clave \"" + key.name + "\"? Se perderá si no tienes un respaldo.")) return;
    api("DELETE", "/keys/" + key.pubkey).done(function () {
      toast("Clave eliminada");
      select(null);
      loadKeys();
    }).fail(function (xhr) { toast(errorMessage(xhr), true); });
  });

  $("#new-bunker").on("click", function () {
    var $btn = $(this);
    busy($btn, true);
    api("POST", "/keys/" + selected + "/bunker").done(function (r) {
      $("#bunker-uri").text(r.bunker_uri);
      $("#bunker-box").removeClass("hidden");
    }).fail(function (xhr) {
      toast(errorMessage(xhr), true);
    }).always(function () { busy($btn, false); });
  });

  $("#copy-bunker").on("click", function () { copy($("#bunker-uri").text()); });

  $("#form-nostrconnect").on("submit", function (e) {
    e.preventDefault();
    var form = this;
    var $btn = $(form).find("button");
    busy($btn, true);
    api("POST", "/keys/" + selected + "/nostrconnect", { uri: form.uri.value.trim() }).done(function () {
      form.reset();
      toast("Conectado. Revisa el sitio para continuar.");
      refreshSigner();
    }).fail(function (xhr) {
      toast(errorMessage(xhr), true);
    }).always(function () { busy($btn, false); });
  });

  $("#client-list").on("click", ".revoke", function () {
    api("DELETE", "/keys/" + selected + "/clients/" + $(this).attr("data-client")).done(function () {
      toast("Cliente revocado");
      refreshSigner();
    }).fail(function (xhr) { toast(errorMessage(xhr), true); });
  });

  loadKeys().done(function () {
    if (keys.length === 1) select(keys[0].pubkey);
  });
});
