/* ==========================================================================
   NUTC "Open Another Door" Blueprint Interactive Controls
   ========================================================================== */

(function () {
  "use strict";

  /* ── 1. Mobile Navigation Drawer & Active Scroll-Spy ── */
  const navToggle = document.getElementById("nav-toggle");
  const siteNav = document.getElementById("site-nav");
  const navLinks = Array.from(document.querySelectorAll(".site-nav .nav-link"));

  if (navToggle && siteNav) {
    navToggle.addEventListener("click", function () {
      const isOpen = siteNav.classList.toggle("is-open");
      navToggle.setAttribute("aria-expanded", String(isOpen));
    });

    navLinks.forEach(function (link) {
      link.addEventListener("click", function () {
        siteNav.classList.remove("is-open");
        navToggle.setAttribute("aria-expanded", "false");
      });
    });
  }

  const sections = Array.from(document.querySelectorAll("main > section[id]"));
  if ("IntersectionObserver" in window && sections.length) {
    const spy = new IntersectionObserver(
      function (entries) {
        entries.forEach(function (entry) {
          if (!entry.isIntersecting) return;
          const id = entry.target.getAttribute("id");
          navLinks.forEach(function (link) {
            const match = link.getAttribute("href") === "#" + id;
            link.classList.toggle("is-active", match);
          });
        });
      },
      { rootMargin: "-25% 0px -60% 0px", threshold: 0.05 }
    );
    sections.forEach(function (sec) {
      spy.observe(sec);
    });
  }

  /* ── 2. Shared SVG Architecture & Card Interactive Focus Helper ── */
  function setupDiagramFocus(cfg) {
    const svg = document.getElementById(cfg.svgId);
    const buttons = Array.from(document.querySelectorAll("[" + cfg.btnAttr + "]"));
    const nodes = Array.from(document.querySelectorAll("#" + cfg.svgId + " " + cfg.nodeSelector));
    const flows = Array.from(document.querySelectorAll("#" + cfg.svgId + " " + cfg.flowSelector));
    const cards = Array.from(document.querySelectorAll(cfg.cardSelector));

    if (!svg) return;
    let currentFocus = "all";

    function applyFocus(focus) {
      currentFocus = focus;

      buttons.forEach(function (btn) {
        btn.classList.toggle("is-active", btn.getAttribute(cfg.btnAttr) === focus);
      });

      if (focus === "all") {
        svg.classList.remove("has-focus");
        nodes.forEach(function (n) { n.classList.remove("is-focused"); });
        flows.forEach(function (f) { f.classList.remove("is-focused"); });
        cards.forEach(function (c) { c.classList.remove("is-focused", "is-dimmed"); });
        return;
      }

      svg.classList.add("has-focus");
      nodes.forEach(function (n) {
        n.classList.toggle("is-focused", n.getAttribute(cfg.nodeAttr) === focus);
      });
      flows.forEach(function (f) {
        const tags = (f.getAttribute("data-flow") || "").split(/\s+/);
        f.classList.toggle("is-focused", tags.indexOf(focus) !== -1);
      });
      cards.forEach(function (c) {
        const isMatch = c.getAttribute(cfg.cardAttr) === focus;
        c.classList.toggle("is-focused", isMatch);
        c.classList.toggle("is-dimmed", !isMatch);
      });
    }

    function toggleFocus(targetFocus) {
      applyFocus(currentFocus === targetFocus ? "all" : targetFocus);
    }

    function bindInteractive(el, attrName) {
      el.addEventListener("click", function () {
        toggleFocus(el.getAttribute(attrName));
      });
      el.addEventListener("keydown", function (ev) {
        if (ev.key === "Enter" || ev.key === " ") {
          ev.preventDefault();
          toggleFocus(el.getAttribute(attrName));
        }
      });
    }

    buttons.forEach(function (btn) {
      btn.addEventListener("click", function () {
        applyFocus(btn.getAttribute(cfg.btnAttr));
      });
    });

    nodes.forEach(function (node) { bindInteractive(node, cfg.nodeAttr); });
    cards.forEach(function (card) { bindInteractive(card, cfg.cardAttr); });
  }

  /* Section 1: Master 1-2-3 Dual-Axis Architecture Focus */
  setupDiagramFocus({
    svgId: "core-arch-svg",
    btnAttr: "data-arch-focus",
    nodeSelector: ".arch-node",
    nodeAttr: "data-node",
    flowSelector: ".arch-flow",
    cardSelector: "#arch-legend-grid .node-spec-card",
    cardAttr: "data-focus"
  });

  /* Section 2: School Curriculum Fostering Architecture Focus */
  setupDiagramFocus({
    svgId: "curriculum-arch-svg",
    btnAttr: "data-curr-focus",
    nodeSelector: ".curr-node",
    nodeAttr: "data-stage",
    flowSelector: ".curr-flow",
    cardSelector: "#curr-stage-grid .node-spec-card",
    cardAttr: "data-curr-stage"
  });

  /* ── 3. Section 3: 6-Week Sandbox Pain-Point Compression Simulator ── */
  const sandboxCases = {
    rag: {
      deliverable: "24 小時系辦修課法規問答微軟體",
      pct: "-75%",
      beforeHrs: "10.0 hr/週",
      beforePct: 84,
      afterHrs: "2.5 hr/週",
      afterPct: 21,
      input: "輸入：公開學則・歷年抵免 Q&A",
      redline: "紅線：無學生姓名・無成績學號",
      tech: "技術：RAG 向量檢索 + 引用出處"
    },
    form: {
      deliverable: "空白實習合約與表單格式自動檢核器",
      pct: "-70%",
      beforeHrs: "8.0 hr/週",
      beforePct: 68,
      afterHrs: "2.4 hr/週",
      afterPct: 20,
      input: "輸入：空白合約範本・欄位規則表",
      redline: "紅線：僅格式比對・學生敏資不外傳",
      tech: "技術：規則引擎 + 前端本地解析"
    },
    promo: {
      deliverable: "系網活動圖文與多管道排程產生工具",
      pct: "-69%",
      beforeHrs: "6.5 hr/週",
      beforePct: 55,
      afterHrs: "2.0 hr/週",
      afterPct: 17,
      input: "輸入：公開講座資訊・系網版型規範",
      redline: "紅線：僅公開宣傳文稿・不碰名單",
      tech: "技術：多模態模板 + 自動排程輸出"
    },
    eval: {
      deliverable: "評鑑公開佐證資料結構化彙整工具",
      pct: "-70%",
      beforeHrs: "12.0 hr/週",
      beforePct: 96,
      afterHrs: "3.6 hr/週",
      afterPct: 29,
      input: "輸入：去識別化統計指標・公開成果",
      redline: "紅線：物理隔離校務核心資料庫",
      tech: "技術：結構化彙整 Agent + 清單輸出"
    }
  };

  const simTabs = Array.from(document.querySelectorAll(".sim-tab[data-case]"));
  const elDeliverable = document.getElementById("sim-deliverable");
  const elPct = document.getElementById("sim-pct");
  const elBarBefore = document.getElementById("sim-bar-before");
  const elBarAfter = document.getElementById("sim-bar-after");
  const elValBefore = document.getElementById("sim-val-before");
  const elValAfter = document.getElementById("sim-val-after");
  const elGuardStrip = document.getElementById("sim-guard-strip");

  simTabs.forEach(function (tab) {
    tab.addEventListener("click", function () {
      const key = tab.getAttribute("data-case");
      const data = sandboxCases[key];
      if (!data) return;

      simTabs.forEach(function (t) {
        const active = t === tab;
        t.classList.toggle("is-active", active);
        t.setAttribute("aria-selected", String(active));
      });

      if (elDeliverable) elDeliverable.textContent = data.deliverable;
      if (elPct) elPct.textContent = data.pct;
      if (elBarBefore) elBarBefore.style.transform = "scaleX(" + (data.beforePct / 100) + ")";
      if (elBarAfter) elBarAfter.style.transform = "scaleX(" + (data.afterPct / 100) + ")";
      if (elValBefore) elValBefore.textContent = data.beforeHrs;
      if (elValAfter) elValAfter.textContent = data.afterHrs;

      if (elGuardStrip) {
        elGuardStrip.innerHTML =
          "<span class=\"pill-tag mint\">" + data.input + "</span>" +
          "<span class=\"pill-tag coral\">" + data.redline + "</span>" +
          "<span class=\"pill-tag cyan\">" + data.tech + "</span>";
      }
    });
  });

  /* ── 4. Section 4: Inter-University Strategy Matrix Filter ── */
  const matrixButtons = Array.from(document.querySelectorAll("[data-matrix-filter]"));
  const matrixRows = Array.from(document.querySelectorAll("#matrix-table tbody tr"));

  matrixButtons.forEach(function (btn) {
    btn.addEventListener("click", function () {
      const filter = btn.getAttribute("data-matrix-filter");
      matrixButtons.forEach(function (b) {
        b.classList.toggle("is-active", b === btn);
      });

      matrixRows.forEach(function (row) {
        const cat = row.getAttribute("data-cat");
        if (filter === "all") {
          row.classList.remove("is-dimmed");
        } else if (filter === "nutc") {
          row.classList.toggle("is-dimmed", cat !== "nutc");
        } else {
          row.classList.toggle("is-dimmed", cat !== filter && cat !== "nutc");
        }
      });
    });
  });

  /* ── 5. Section 6: Seven-Scene Blueprint Briefing Index ── */
  const sceneBriefs = {
    s01: {
      code: "S01 //",
      num: "SCENE 01 / 07",
      text: "灰暗舊式 PPT 投影片碎裂解體 → 溫潤木質門扉開啟：破除「只用 AI 做簡報」的假轉型。"
    },
    s02: {
      code: "S02 //",
      num: "SCENE 02 / 07",
      text: "無印紙感舞台展開三座跨界造物工坊：互動軟體造物 × 3D 空間視覺 × 程式碼驅動動態影音與音效。"
    },
    s03: {
      code: "S03 //",
      num: "SCENE 03 / 07",
      text: "盤點 15,600+ 師生、6 大學院與五專／四技／二技／進修部體質：捨棄軍備戰與論文課，啟動雙軸生態。"
    },
    s04: {
      code: "S04 //",
      num: "SCENE 04 / 07",
      text: "「AI 跨界造物者社群」：禁論文與靜態簡報、推動授課加薪與 AI 補助，每月主導開門 AI 造物講堂。"
    },
    s05: {
      code: "S05 //",
      num: "SCENE 05 / 07",
      text: "軸一「系辦 × iPAS 微軟體特攻隊」：嚴守零個資沙盒紅線、行政持證加薪敘獎，目標縮減 70% 重複工時。"
    },
    s06: {
      code: "S06 //",
      num: "SCENE 06 / 07",
      text: "軸二「開門 AI 講堂 × 日間三學制 × 進修部夜間企業 AI 包班」：不改 18 學分課綱，同步活化夜間教室造血。"
    },
    s07: {
      code: "S07 //",
      num: "SCENE 07 / 07",
      text: "3 階段滾動擴張：點火打樣 → 啟動進修部企業包班 → 造物大賞與包班營收反哺算力池。"
    }
  };

  const sceneTabs = Array.from(document.querySelectorAll(".scene-chip[data-scene]"));
  const sceneBriefBar = document.getElementById("scene-brief-bar");

  sceneTabs.forEach(function (btn) {
    btn.addEventListener("click", function () {
      const key = btn.getAttribute("data-scene");
      const info = sceneBriefs[key];
      if (!info || !sceneBriefBar) return;

      sceneTabs.forEach(function (t) {
        const active = t === btn;
        t.classList.toggle("is-active", active);
        t.setAttribute("aria-selected", String(active));
      });

      sceneBriefBar.innerHTML =
        "<span><strong>" +
        info.code +
        "</strong> " +
        info.text +
        "</span><span class=\"mono\">" +
        info.num +
        "</span>";
    });
  });
})();
