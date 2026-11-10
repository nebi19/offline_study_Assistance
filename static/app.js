"use strict";

// ---------------------------------------------------------------- UI text
const TEXT = {
  en: {
    appName: "Study Assistant", tagline: "Mathematics · works offline", unit: "Unit",
    tabLessons: "Lessons", tabAsk: "Ask", tabQuiz: "Quiz", tabTeacher: "Teacher",
    showSummary: "Show visual summary", pickSection: "Pick a section to read it, or open the visual summary.",
    askHint: "Ask anything about this unit. Answers come only from your textbook.",
    askPlaceholder: "e.g. What is a proper subset?", send: "Ask",
    quizTitle: "Practice quiz", quizInEnglish: "Quizzes are in English for now.", newQuiz: "New quiz (5 questions)", submit: "Check my answers",
    teacherTitle: "Teacher view", teacherHint: "Choose which units students can see, and find where they struggle.",
    pin: "Teacher PIN", grade: "Grade", summaryLoading: "Making the summary… (the first time can take a minute)",
    quizLoading: "Writing your quiz… (this can take a minute)", overview: "Overview", conceptMap: "Concept map",
    formulas: "Key formulas and rules", terms: "Key terms", example: "Worked example", answer: "Answer",
    sources: "From your textbook:", page: "p.", score: (s, t) => `You scored ${s} out of ${t}`,
    visible: "Visible", questions: "Questions", notFound: "Not in textbook", attempts: "Quiz attempts",
    average: "Average score", topQuestions: "Most asked", noData: "No questions yet",
    regenerate: "Make a new summary", error: "Something went wrong:", answerAll: "Answer every question first.",
    modelDown: "The AI model is not running. Ask the lab admin to start it.",
  },
  am: {
    appName: "የጥናት ረዳት", tagline: "ሂሳብ · ያለ ኢንተርኔት ይሰራል", unit: "ምዕራፍ",
    tabLessons: "ትምህርቶች", tabAsk: "ጠይቅ", tabQuiz: "ፈተና", tabTeacher: "መምህር",
    showSummary: "የምስል ማጠቃለያ አሳይ", pickSection: "ለማንበብ ክፍል ይምረጡ፣ ወይም የምስል ማጠቃለያውን ይክፈቱ።",
    askHint: "ስለዚህ ምዕራፍ ማንኛውንም ይጠይቁ። መልሶቹ ከመማሪያ መጽሐፍዎ ብቻ ይመጣሉ።",
    askPlaceholder: "ለምሳሌ፡ ንዑስ ስብስብ ምንድን ነው?", send: "ጠይቅ",
    quizTitle: "የልምምድ ፈተና", quizInEnglish: "ፈተናዎች ለጊዜው በእንግሊዝኛ ብቻ ናቸው።", newQuiz: "አዲስ ፈተና (5 ጥያቄዎች)", submit: "መልሶቼን አረጋግጥ",
    teacherTitle: "የመምህር ገጽ", teacherHint: "ተማሪዎች የሚያዩዋቸውን ምዕራፎች ይምረጡ፣ የሚቸገሩበትንም ይመልከቱ።",
    pin: "የመምህር ፒን", grade: "ክፍል", summaryLoading: "ማጠቃለያ እየተዘጋጀ ነው… (የመጀመሪያው ጊዜ አንድ ደቂቃ ሊወስድ ይችላል)",
    quizLoading: "ፈተናዎ እየተዘጋጀ ነው… (አንድ ደቂቃ ሊወስድ ይችላል)", overview: "አጠቃላይ እይታ", conceptMap: "የፅንሰ-ሀሳብ ካርታ",
    formulas: "ቁልፍ ቀመሮች እና ሕጎች", terms: "ቁልፍ ቃላት", example: "የተሰራ ምሳሌ", answer: "መልስ",
    sources: "ከመማሪያ መጽሐፍዎ፡", page: "ገጽ", score: (s, t) => `ከ${t} ውስጥ ${s} አግኝተዋል`,
    visible: "ይታያል", questions: "ጥያቄዎች", notFound: "በመጽሐፉ የለም", attempts: "የፈተና ሙከራዎች",
    average: "አማካይ ውጤት", topQuestions: "በብዛት የተጠየቁ", noData: "እስካሁን ጥያቄ የለም",
    regenerate: "አዲስ ማጠቃለያ አዘጋጅ", error: "ችግር ተፈጥሯል፡", answerAll: "መጀመሪያ ሁሉንም ጥያቄዎች ይመልሱ።",
    modelDown: "የኤአይ ሞዴሉ አልተጀመረም። የላብ አስተዳዳሪውን ይጠይቁ።",
  },
};

const state = {
  lang: localStorageGet("lang") || "en",
  library: [],
  unitId: localStorageGet("unitId"),
  quiz: null,
  pin: localStorageGet("pin") || "",
};
const t = (key) => TEXT[state.lang][key] ?? TEXT.en[key] ?? key;
const $ = (sel) => document.querySelector(sel);

function localStorageGet(key) { try { return localStorage.getItem(key); } catch { return null; } }
function localStorageSet(key, value) { try { localStorage.setItem(key, value); } catch { /* private mode */ } }

function el(tag, attrs = {}, ...children) {
  const node = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (k === "class") node.className = v;
    else if (k.startsWith("on")) node.addEventListener(k.slice(2), v);
    else if (v !== undefined && v !== null && v !== false) node.setAttribute(k, v === true ? "" : v);
  }
  for (const child of children.flat()) {
    if (child === null || child === undefined || child === false) continue;
    node.append(child instanceof Node ? child : document.createTextNode(String(child)));
  }
  return node;
}

function sourceBadge(src) {
  if (!src) return null;
  if (src.pages !== undefined) {
    if (!src.section) return null;
    return el("span", { class: "source" }, `§ ${src.section}${src.pages ? " · " + src.pages : ""}`);
  }
  const page = src.page ? ` · ${t("page")} ${src.page}` : "";
  return el("span", { class: "source" }, `${src.unit} · § ${src.section}${page}`);
}

async function api(path, options = {}) {
  const headers = { "Content-Type": "application/json", ...(options.headers || {}) };
  if (state.pin) headers["X-Teacher-Pin"] = state.pin;
  const res = await fetch(path, { ...options, headers });
  if (!res.ok) {
    let detail = res.statusText;
    try { detail = (await res.json()).detail || detail; } catch { /* not JSON */ }
    const err = new Error(detail);
    err.status = res.status;
    throw err;
  }
  return res;
}

function errorText(err) {
  return err.status === 503 ? t("modelDown") : `${t("error")} ${err.message}`;
}

// ------------------------------------------------------------- language/UI
function applyLanguage() {
  document.documentElement.lang = state.lang;
  document.querySelectorAll("[data-i18n]").forEach((n) => { n.textContent = t(n.dataset.i18n); });
  document.querySelectorAll("[data-i18n-placeholder]").forEach((n) => { n.placeholder = t(n.dataset.i18nPlaceholder); });
  document.querySelectorAll(".lang button").forEach((b) => b.classList.toggle("active", b.dataset.lang === state.lang));
  document.title = t("appName");
}

document.querySelectorAll(".lang button").forEach((b) =>
  b.addEventListener("click", () => {
    state.lang = b.dataset.lang;
    localStorageSet("lang", state.lang);
    applyLanguage();
    renderUnitSelect();
  }),
);

document.querySelectorAll(".tabs button").forEach((b) =>
  b.addEventListener("click", () => showTab(b.dataset.tab)),
);

function showTab(name) {
  document.querySelectorAll(".tabs button").forEach((b) => b.classList.toggle("active", b.dataset.tab === name));
  document.querySelectorAll(".panel").forEach((p) => p.classList.toggle("active", p.id === `tab-${name}`));
  if (name === "teacher") loadTeacher();
}

// ------------------------------------------------------------------ library
async function loadLibrary() {
  const data = await (await api("/api/library")).json();
  state.library = data.grades;
  const all = data.grades.flatMap((g) => g.units);
  if (!all.some((u) => u.id === state.unitId)) state.unitId = all[0]?.id || null;
  renderUnitSelect();
  renderUnit();
}

function currentUnit() {
  return state.library.flatMap((g) => g.units).find((u) => u.id === state.unitId);
}

function renderUnitSelect() {
  const select = $("#unitSelect");
  select.replaceChildren(
    ...state.library.map((g) =>
      el("optgroup", { label: `${t("grade")} ${g.grade}` },
        g.units.map((u) => el("option", { value: u.id, selected: u.id === state.unitId }, `${t("grade")} ${g.grade} · ${t("unit")} ${u.number}: ${u.title}`)),
      ),
    ),
  );
}

$("#unitSelect").addEventListener("change", (e) => {
  state.unitId = e.target.value;
  localStorageSet("unitId", state.unitId);
  state.quiz = null;
  $("#quiz").replaceChildren();
  $("#messages").replaceChildren(el("p", { class: "muted" }, t("askHint")));
  renderUnit();
});

function renderUnit() {
  const unit = currentUnit();
  if (!unit) return;
  $("#unitTitle").textContent = `${t("unit")} ${unit.number}: ${unit.title}`;
  $("#sectionList").replaceChildren(
    ...unit.sections.map((s) =>
      el("li", {},
        el("button", { onclick: (e) => openSection(s.id, e.currentTarget) },
          `${s.number.startsWith("S") ? "" : s.number + " "}${s.title}`,
          el("span", { class: "pages" }, s.pages),
        ),
      ),
    ),
  );
  $("#reader").replaceChildren(el("p", { class: "muted" }, t("pickSection")));
}

async function openSection(sectionId, button) {
  document.querySelectorAll(".section-list li button").forEach((b) => b.classList.remove("active"));
  button?.classList.add("active");
  const reader = $("#reader");
  reader.replaceChildren(el("span", { class: "spinner" }));
  try {
    const sec = await (await api(`/api/sections/${encodeURIComponent(sectionId)}`)).json();
    reader.replaceChildren(
      el("h2", {}, `${sec.number.startsWith("S") ? "" : sec.number + " "}${sec.title}`),
      ...sec.pages.flatMap((p) => [
        p.page ? el("div", { class: "page-label" }, `${t("page")} ${p.page}`) : null,
        el("div", { class: "page-text" }, p.text),
      ]),
    );
  } catch (err) {
    reader.replaceChildren(el("p", { class: "error" }, errorText(err)));
  }
}

// ------------------------------------------------------------------ summary
mermaid.initialize({ startOnLoad: false, securityLevel: "strict", theme: "base", flowchart: { htmlLabels: true } });
let mermaidCount = 0;

$("#summaryBtn").addEventListener("click", () => loadSummary(false));

async function loadSummary(refresh) {
  const reader = $("#reader");
  const btn = $("#summaryBtn");
  btn.disabled = true;
  document.querySelectorAll(".section-list li button").forEach((b) => b.classList.remove("active"));
  reader.replaceChildren(el("p", {}, el("span", { class: "spinner" }), t("summaryLoading")));
  try {
    const url = `/api/units/${encodeURIComponent(state.unitId)}/summary?language=${state.lang}${refresh ? "&refresh=true" : ""}`;
    const s = await (await api(url)).json();
    await renderSummary(s);
  } catch (err) {
    reader.replaceChildren(el("p", { class: "error" }, errorText(err)));
  } finally {
    btn.disabled = false;
  }
}

async function renderSummary(s) {
  const map = el("div", { class: "concept-map" });
  const reader = $("#reader");
  reader.replaceChildren(
    el("div", { class: "row" },
      el("h2", {}, s.unit),
      el("button", { class: "link", onclick: () => loadSummary(true) }, t("regenerate")),
    ),
    s.overview ? el("p", { class: "overview" }, s.overview) : null,
    el("h3", {}, t("conceptMap")),
    map,
    s.formulas.length ? el("h3", {}, t("formulas")) : null,
    s.formulas.length
      ? el("div", { class: "cards" },
          s.formulas.map((f) => el("div", { class: "mini" },
            el("strong", {}, f.name), el("div", { class: "formula" }, f.formula), f.meaning, el("div", {}, sourceBadge(f)))))
      : null,
    s.key_terms.length ? el("h3", {}, t("terms")) : null,
    s.key_terms.length
      ? el("div", { class: "cards" },
          s.key_terms.map((k) => el("div", { class: "mini" }, el("strong", {}, k.term), k.meaning, el("div", {}, sourceBadge(k)))))
      : null,
    s.worked_example
      ? el("div", { class: "example" },
          el("h3", {}, t("example")),
          el("div", { class: "mini" },
            el("strong", {}, s.worked_example.problem),
            el("ol", {}, s.worked_example.steps.map((step) => el("li", {}, step))),
            s.worked_example.answer ? el("p", {}, el("b", {}, `${t("answer")}: `), s.worked_example.answer) : null,
            sourceBadge(s.worked_example)))
      : null,
  );
  try {
    const { svg } = await mermaid.render(`cmap${++mermaidCount}`, s.concept_map);
    map.innerHTML = svg; // generated by Mermaid from escaped labels (securityLevel: strict)
  } catch {
    map.replaceChildren(el("ul", {}, s.topics.map((tp) => el("li", {}, el("b", {}, tp.title), ": ", tp.key_ideas.join("; ")))));
  }
}

// ---------------------------------------------------------------------- ask
$("#askForm").addEventListener("submit", async (e) => {
  e.preventDefault();
  const input = $("#question");
  const question = input.value.trim();
  if (!question || !state.unitId) return;
  input.value = "";
  const messages = $("#messages");
  messages.querySelector(".muted")?.remove();
  messages.append(el("div", { class: "msg user" }, question));
  const answer = el("div", { class: "msg bot typing" });
  const body = el("span");
  const sources = el("div", { class: "sources" });
  answer.append(body, sources);
  messages.append(answer);
  messages.scrollTop = messages.scrollHeight;
  const submit = e.submitter || $("#askForm button");
  submit.disabled = true;

  try {
    const res = await api("/api/ask", {
      method: "POST",
      body: JSON.stringify({ unit_id: state.unitId, question, language: state.lang }),
    });
    const reader = res.body.getReader();
    const decoder = new TextDecoder();
    let buffer = "";
    for (;;) {
      const { value, done } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });
      const lines = buffer.split("\n");
      buffer = lines.pop();
      for (const line of lines) {
        if (!line.trim()) continue;
        const ev = JSON.parse(line);
        if (ev.type === "sources") {
          sources.replaceChildren(
            ev.sources.length ? el("small", { class: "muted" }, t("sources"), " ") : "",
            ...ev.sources.map(sourceBadge),
          );
          if (!ev.sources.length) body.textContent = "";
        } else if (ev.type === "token") {
          body.textContent += ev.text;
        } else if (ev.type === "done") {
          if (!ev.answered) answer.classList.add("not-found");
        } else if (ev.type === "error") {
          body.textContent = t("modelDown");
          answer.classList.add("not-found");
        }
        messages.scrollTop = messages.scrollHeight;
      }
    }
  } catch (err) {
    body.textContent = errorText(err);
    answer.classList.add("not-found");
  } finally {
    answer.classList.remove("typing");
    submit.disabled = false;
    input.focus();
  }
});

// --------------------------------------------------------------------- quiz
$("#newQuizBtn").addEventListener("click", async () => {
  const box = $("#quiz");
  const btn = $("#newQuizBtn");
  btn.disabled = true;
  box.replaceChildren(el("p", {}, el("span", { class: "spinner" }), t("quizLoading")));
  try {
    const res = await api("/api/quizzes", {
      method: "POST",
      body: JSON.stringify({ unit_id: state.unitId, language: state.lang }),
    });
    state.quiz = await res.json();
    renderQuiz();
  } catch (err) {
    box.replaceChildren(el("p", { class: "error" }, errorText(err)));
  } finally {
    btn.disabled = false;
  }
});

function renderQuiz(result) {
  const quiz = state.quiz;
  const form = el("form", {
    onsubmit: async (e) => {
      e.preventDefault();
      const answers = quiz.questions.map((_, i) => {
        const checked = form.querySelector(`input[name="q${i}"]:checked`);
        return checked ? Number(checked.value) : null;
      });
      if (answers.includes(null)) { alert(t("answerAll")); return; }
      try {
        const res = await api(`/api/quizzes/${quiz.quiz_id}/submit`, { method: "POST", body: JSON.stringify({ answers }) });
        renderQuiz(await res.json());
      } catch (err) {
        alert(errorText(err));
      }
    },
  });
  if (quiz.language && quiz.language !== state.lang) form.append(el("p", { class: "muted" }, t("quizInEnglish")));
  quiz.questions.forEach((q, i) => {
    const r = result?.results[i];
    form.append(
      el("div", { class: "question" },
        el("p", {}, `${i + 1}. ${q.question}`),
        q.options.map((opt, j) =>
          el("label", {
            class: "option" + (r ? (j === r.answer_index ? " correct" : j === r.chosen ? " wrong" : "") : ""),
          },
            el("input", { type: "radio", name: `q${i}`, value: j, disabled: !!r, checked: r ? j === r.chosen : false }),
            el("span", {}, opt),
          ),
        ),
        r ? el("div", { class: "explanation" }, `${r.correct ? "✅" : "❌"} ${r.explanation}`) : null,
        el("div", {}, sourceBadge(q.source)),
      ),
    );
  });
  form.append(result
    ? el("p", { class: "score" }, t("score")(result.score, result.total))
    : el("button", { class: "primary", type: "submit" }, t("submit")));
  $("#quiz").replaceChildren(form);
}

// ------------------------------------------------------------------ teacher
$("#pinForm").addEventListener("submit", (e) => {
  e.preventDefault();
  state.pin = $("#pin").value;
  localStorageSet("pin", state.pin);
  loadTeacher();
});

async function loadTeacher() {
  const box = $("#teacher");
  box.replaceChildren(el("span", { class: "spinner" }));
  try {
    const data = await (await api("/api/teacher/overview")).json();
    $("#pinForm").classList.add("hidden");
    box.replaceChildren(
      el("div", { class: "table-wrap" },
        el("table", {},
          el("thead", {}, el("tr", {},
            el("th", {}, t("visible")), el("th", {}, t("unit")), el("th", { class: "num" }, t("questions")),
            el("th", { class: "num" }, t("notFound")), el("th", { class: "num" }, t("attempts")), el("th", { class: "num" }, t("average")),
          )),
          el("tbody", {},
            data.units.map((u) =>
              el("tr", {},
                el("td", {},
                  el("label", { class: "switch" },
                    el("input", {
                      type: "checkbox", checked: !u.hidden,
                      onchange: async (e) => {
                        await api("/api/teacher/visibility", { method: "POST", body: JSON.stringify({ unit_id: u.id, hidden: !e.target.checked }) });
                        loadLibrary();
                      },
                    }),
                  )),
                el("td", {},
                  el("b", {}, `${t("grade")} ${u.grade} · ${u.title}`),
                  u.top_questions.length
                    ? el("div", {}, el("small", { class: "muted" }, t("topQuestions")),
                        el("ol", { class: "top-q" }, u.top_questions.map((q) =>
                          el("li", {}, `${q.question} (${q.count})`, q.answered ? null : el("span", { class: "badge-bad" }, ` · ${t("notFound")}`)))))
                    : el("small", { class: "muted" }, t("noData")),
                ),
                el("td", { class: "num" }, u.questions),
                el("td", { class: "num" }, u.unanswered),
                el("td", { class: "num" }, u.quiz_attempts),
                el("td", { class: "num" }, u.quiz_average === null ? "–" : `${u.quiz_average}%`),
              ),
            ),
          ),
        ),
      ),
    );
  } catch (err) {
    if (err.status === 401) {
      $("#pinForm").classList.remove("hidden");
      box.replaceChildren();
    } else {
      box.replaceChildren(el("p", { class: "error" }, errorText(err)));
    }
  }
}

// --------------------------------------------------------------------- boot
async function boot() {
  applyLanguage();
  try {
    await loadLibrary();
    const health = await (await api("/api/health")).json();
    const m = health.model;
    $("#status").textContent = m && m.running
      ? `${health.units} units · ${health.passages} passages · model ${m.chat_model}${m.chat_model_installed ? "" : " (not installed)"}`
      : `${health.units} units · ${t("modelDown")}`;
  } catch (err) {
    $("#status").textContent = errorText(err);
  }
}
boot();
