// Vernis backup restore - shared by the setup wizard (welcome.html) and
// Settings > Backup & Restore.
//
//   VernisBackup.upload(file, {onProgress(pct), onUploaded()})  -> Promise<result>
//   VernisBackup.listLocal()           -> Promise<[{path, name, drive, bytes, modified}]>
//   VernisBackup.restoreLocal(path, {onProgress(pct)})          -> Promise<result>
//   VernisBackup.saveToDrive(path, {onProgress(pct)})           -> Promise<result>
//   VernisBackup.watchRepin(onUpdate)  -> polls re-pinning of restored art
//   VernisBackup.formatBytes(n)
//
// Promises reject with an Error whose message is ready to show.
(function () {
  "use strict";

  function authHeaders() {
    return window.VernisLockGuard ? window.VernisLockGuard.authHeaders() : {};
  }

  function formatBytes(n) {
    if (n >= 1e12) return (n / 1e12).toFixed(2) + " TB";
    if (n >= 1e9) return (n / 1e9).toFixed(1) + " GB";
    if (n >= 1e6) return (n / 1e6).toFixed(1) + " MB";
    return Math.max(1, Math.round(n / 1e3)) + " KB";
  }

  function json(r) {
    return r.json().then(function (d) {
      if (!r.ok || d.error) throw new Error(d.error || "Request failed (" + r.status + ")");
      return d;
    });
  }

  function upload(file, opts) {
    opts = opts || {};
    // Space check first, so a refusal shows before a multi-GB upload starts
    return fetch("/api/backup/import/check?size=" + file.size + "&name=" + encodeURIComponent(file.name))
      .then(function (r) { return r.json(); })
      .catch(function () { return { ok: true }; })  // older Vernis: upload reports problems
      .then(function (check) {
        if (!check.ok) throw new Error(check.error || "This backup can't be restored here");
        return new Promise(function (resolve, reject) {
          // Raw body: the Pi writes it straight to disk (no size cap, no RAM buffering)
          var xhr = new XMLHttpRequest();
          xhr.open("POST", "/api/backup/import", true);
          xhr.setRequestHeader("Content-Type", "application/octet-stream");
          xhr.setRequestHeader("X-Backup-Filename", encodeURIComponent(file.name));
          var auth = authHeaders();
          Object.keys(auth).forEach(function (k) { xhr.setRequestHeader(k, auth[k]); });
          xhr.upload.onprogress = function (e) {
            if (e.lengthComputable && opts.onProgress) opts.onProgress(Math.round((e.loaded / e.total) * 100));
          };
          xhr.upload.onload = function () { if (opts.onUploaded) opts.onUploaded(); };
          xhr.onload = function () {
            var d = {};
            try { d = JSON.parse(xhr.responseText); } catch (e) {}
            if (xhr.status === 200 && d.success) resolve(d);
            else reject(new Error(d.error || "Restore failed"));
          };
          xhr.onerror = function () {
            reject(new Error("The upload stopped. Check the connection and try again: files restored so far are kept."));
          };
          xhr.send(file);
        });
      });
  }

  function listLocal() {
    return fetch("/api/backup/local").then(json).then(function (d) { return d.backups || []; });
  }

  function restoreLocal(path, opts) {
    opts = opts || {};
    return fetch("/api/backup/local/restore", {
      method: "POST",
      headers: Object.assign({ "Content-Type": "application/json" }, authHeaders()),
      body: JSON.stringify({ path: path }),
    })
      .then(json)
      .then(function () {
        return new Promise(function (resolve, reject) {
          (function poll() {
            fetch("/api/backup/restore-status")
              .then(json)
              .then(function (s) {
                if (s.state === "running") {
                  if (opts.onProgress && s.bytes) opts.onProgress(Math.min(100, Math.round((s.read / s.bytes) * 100)));
                  setTimeout(poll, 1000);
                } else if (s.state === "done") resolve(s);
                else reject(new Error(s.error || "Restore failed"));
              })
              .catch(function () { setTimeout(poll, 3000); });
          })();
        });
      });
  }

  // The Vernis writes the backup onto a USB drive plugged into it
  function saveToDrive(path, opts) {
    opts = opts || {};
    return fetch("/api/backup/drive", {
      method: "POST",
      headers: Object.assign({ "Content-Type": "application/json" }, authHeaders()),
      body: JSON.stringify({ path: path }),
    })
      .then(json)
      .then(function () {
        return new Promise(function (resolve, reject) {
          (function poll() {
            fetch("/api/backup/drive/status")
              .then(json)
              .then(function (s) {
                if (s.state === "running") {
                  if (opts.onProgress && s.bytes) opts.onProgress(Math.min(100, Math.round((s.written / s.bytes) * 100)));
                  setTimeout(poll, 1000);
                } else if (s.state === "done") resolve(s);
                else reject(new Error(s.error || "Saving the backup failed"));
              })
              .catch(function () { setTimeout(poll, 3000); });
          })();
        });
      });
  }

  // Restored art is pinned to IPFS again in the background.
  function watchRepin(onUpdate) {
    (function poll() {
      fetch("/api/backup/restore-status")
        .then(function (r) { return r.json(); })
        .then(function (s) {
          var p = s.repin || {};
          onUpdate(p);
          if (p.running) setTimeout(poll, 3000);
        })
        .catch(function () {});
    })();
  }

  window.VernisBackup = {
    upload: upload,
    listLocal: listLocal,
    restoreLocal: restoreLocal,
    saveToDrive: saveToDrive,
    watchRepin: watchRepin,
    formatBytes: formatBytes,
  };
})();
