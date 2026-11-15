(function () {
  "use strict";
  const basePath = document.querySelector('meta[name="app-base-path"]').content;
  function path(value) {
    if (!value.startsWith("/") || value.startsWith("//")) throw new Error("需要应用内路径");
    if (basePath && (value === basePath || value.startsWith(basePath + "/"))) return value;
    return basePath + value;
  }
  function localLink(value) {
    const url = new URL(value, location.origin);
    if (url.origin === "null" || url.origin !== location.origin || url.username || url.password) return null;
    url.pathname = path(url.pathname);
    return url;
  }
  window.assistantPaths = Object.freeze({
    path,
    localLink,
    routePath: () => basePath ? location.pathname.slice(basePath.length) || "/" : location.pathname,
    fetch: (value, options) => fetch(path(value), options),
  });
})();
