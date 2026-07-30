(() => {
  "use strict";

  const body = document.body;
  const menuButton = document.querySelector("[data-menu-toggle]");
  const menuClose = document.querySelector("[data-menu-close]");
  const shelfSearch = document.querySelector("[data-shelf-search]");
  const globalSearch = document.querySelector("[data-global-search]");
  const searchToggle = document.querySelector("[data-search-toggle]");
  const progressBar = document.querySelector(".reading-progress span");

  const setMenu = (open) => {
    body.classList.toggle("menu-open", open);
    menuButton?.setAttribute("aria-expanded", String(open));
    if (open) {
      window.setTimeout(() => shelfSearch?.focus(), 80);
    }
  };

  menuButton?.addEventListener("click", () => setMenu(!body.classList.contains("menu-open")));
  menuClose?.addEventListener("click", () => setMenu(false));

  const filterShelf = (value) => {
    const query = value.trim().toLocaleLowerCase();
    document.querySelectorAll(".shelf-group").forEach((group) => {
      let visible = 0;
      group.querySelectorAll(".shelf-link").forEach((link) => {
        const matches = !query || link.dataset.search.includes(query);
        link.hidden = !matches;
        visible += Number(matches);
      });
      group.hidden = visible === 0;
    });
  };

  shelfSearch?.addEventListener("input", (event) => filterShelf(event.target.value));

  const searchableText = (item) =>
    [item.title, item.path, item.summary, ...(item.headings || [])].join(" ").toLocaleLowerCase();

  const renderSearchResults = (query) => {
    const target = document.querySelector("[data-search-results]");
    if (!target) return;
    const normalized = query.trim().toLocaleLowerCase();
    if (!normalized) {
      target.classList.remove("is-open");
      target.replaceChildren();
      return;
    }
    const terms = normalized.split(/\s+/).filter(Boolean);
    const results = (window.DOCS_SEARCH_INDEX || [])
      .map((item) => ({
        item,
        score: terms.reduce((total, term) => {
          const haystack = searchableText(item);
          return total + (item.title.toLocaleLowerCase().includes(term) ? 4 : 0) + (haystack.includes(term) ? 1 : 0);
        }, 0),
      }))
      .filter(({ score }) => score >= terms.length)
      .sort((left, right) => right.score - left.score || left.item.title.localeCompare(right.item.title))
      .slice(0, 8);

    target.replaceChildren();
    if (!results.length) {
      const empty = document.createElement("div");
      empty.className = "search-empty";
      empty.textContent = `No documents match “${query.trim()}”.`;
      target.append(empty);
    } else {
      results.forEach(({ item }) => {
        const link = document.createElement("a");
        link.className = "search-result";
        link.href = item.url;
        const title = document.createElement("strong");
        title.textContent = item.title;
        const detail = document.createElement("span");
        detail.textContent = item.path;
        link.append(title, detail);
        target.append(link);
      });
    }
    target.classList.add("is-open");
  };

  globalSearch?.addEventListener("input", (event) => renderSearchResults(event.target.value));

  const focusSearch = () => {
    if (globalSearch) {
      globalSearch.focus();
      globalSearch.scrollIntoView({ block: "center", behavior: "smooth" });
      return;
    }
    if (window.matchMedia("(max-width: 820px)").matches) setMenu(true);
    shelfSearch?.focus();
  };

  searchToggle?.addEventListener("click", focusSearch);

  document.addEventListener("keydown", (event) => {
    const target = event.target;
    const typing = target instanceof HTMLInputElement || target instanceof HTMLTextAreaElement || target?.isContentEditable;
    if (event.key === "/" && !typing) {
      event.preventDefault();
      focusSearch();
    }
    if (event.key === "Escape") {
      setMenu(false);
      if (globalSearch) {
        globalSearch.value = "";
        renderSearchResults("");
        globalSearch.blur();
      }
      if (shelfSearch) {
        shelfSearch.value = "";
        filterShelf("");
        shelfSearch.blur();
      }
    }
  });

  document.querySelectorAll(".document-shelf a").forEach((link) => {
    link.addEventListener("click", () => setMenu(false));
  });

  const updateProgress = () => {
    if (!progressBar) return;
    const scrollable = document.documentElement.scrollHeight - window.innerHeight;
    const ratio = scrollable > 0 ? Math.min(1, window.scrollY / scrollable) : 0;
    progressBar.style.width = `${ratio * 100}%`;
  };

  updateProgress();
  window.addEventListener("scroll", updateProgress, { passive: true });
  window.addEventListener("resize", updateProgress);

  const outlineLinks = new Map(
    [...document.querySelectorAll(".outline-scroll a[href^='#']")].map((link) => [decodeURIComponent(link.hash.slice(1)), link]),
  );
  const headings = [...document.querySelectorAll(".markdown-body :is(h2, h3, h4)[id]")];
  if ("IntersectionObserver" in window && headings.length) {
    const visible = new Map();
    const observer = new IntersectionObserver(
      (entries) => {
        entries.forEach((entry) => visible.set(entry.target.id, entry.isIntersecting ? entry.boundingClientRect.top : null));
        const active = [...visible.entries()]
          .filter(([, top]) => top !== null)
          .sort((left, right) => Math.abs(left[1]) - Math.abs(right[1]))[0]?.[0];
        outlineLinks.forEach((link, id) => link.classList.toggle("is-active", id === active));
      },
      { rootMargin: "-72px 0px -72% 0px", threshold: [0, 1] },
    );
    headings.forEach((heading) => observer.observe(heading));
  }

  const copyText = async (text) => {
    if (navigator.clipboard?.writeText) {
      await navigator.clipboard.writeText(text);
      return;
    }
    const area = document.createElement("textarea");
    area.value = text;
    area.setAttribute("readonly", "");
    area.style.position = "fixed";
    area.style.opacity = "0";
    document.body.append(area);
    area.select();
    document.execCommand("copy");
    area.remove();
  };

  document.querySelectorAll("pre").forEach((pre) => {
    const code = pre.querySelector("code");
    if (!code) return;
    const button = document.createElement("button");
    button.type = "button";
    button.className = "copy-code";
    button.textContent = "Copy";
    button.setAttribute("aria-label", "Copy code block");
    button.addEventListener("click", async () => {
      try {
        await copyText(code.textContent);
        button.textContent = "Copied";
      } catch {
        button.textContent = "Copy failed";
      }
      window.setTimeout(() => {
        button.textContent = "Copy";
      }, 1400);
    });
    pre.append(button);
  });

  document.querySelectorAll(".markdown-body a[href^='http']").forEach((link) => {
    link.target = "_blank";
    link.rel = "noreferrer noopener";
  });
})();
