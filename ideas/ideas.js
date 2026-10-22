// Ideas board: Google sign-in, submit (moderated), one vote per person per idea
// (any number of ideas), Idea of the Month. All access control lives in firestore.rules; this file is only UI.
import { initializeApp } from "https://www.gstatic.com/firebasejs/10.12.2/firebase-app.js";
import { getAuth, GoogleAuthProvider, onAuthStateChanged, signInWithPopup, signInWithRedirect, signOut }
  from "https://www.gstatic.com/firebasejs/10.12.2/firebase-auth.js";
import { getFirestore, collection, doc, query, where, orderBy, limit, getDoc, getDocs, addDoc, updateDoc,
  setDoc, writeBatch, increment, serverTimestamp }
  from "https://www.gstatic.com/firebasejs/10.12.2/firebase-firestore.js";

const CFG = window.NV;
const $ = (id) => document.getElementById(id);
const CH = { science: "NerdScience", history: "NerdHistory", nature: "NerdNature" };
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) =>
  ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

if (!CFG.firebase.apiKey) {
  $("board-status").textContent = "The ideas board opens soon. Check back in a day or two.";
  throw new Error("Firebase not configured");
}

const app = initializeApp(CFG.firebase);
const auth = getAuth(app);
const db = getFirestore(app);

let user = null;
let myVotes = new Set();
let sort = "top";
let busy = new Set();

function shortName(u) {
  const parts = (u.displayName || "NerdVerse fan").trim().split(/\s+/);
  return (parts.length > 1 ? `${parts[0]} ${parts[parts.length - 1][0]}.` : parts[0]).slice(0, 40);
}
const isAdmin = () => !!user && user.emailVerified && CFG.admins.includes(user.email);
function say(el, text, bad) { el.textContent = text; el.classList.toggle("bad", !!bad); }

// ── Auth ──────────────────────────────────────────────────────────────────
async function signIn() {
  const provider = new GoogleAuthProvider();
  try { await signInWithPopup(auth, provider); }
  catch (e) {
    if (e.code === "auth/popup-blocked" || e.code === "auth/operation-not-supported-in-this-environment")
      await signInWithRedirect(auth, provider);
    else if (e.code !== "auth/popup-closed-by-user") say($("board-status"), "Sign-in failed. Please try again.", true);
  }
}

function renderAuth() {
  const box = $("auth");
  if (user) {
    box.innerHTML = `<span class="who">Signed in as ${esc(shortName(user))}</span>
      <button class="linkbtn" id="signout" type="button">Sign out</button>`;
    $("signout").onclick = () => signOut(auth);
  } else {
    box.innerHTML = `<button class="btn" id="signin" type="button">Sign in with Google</button>
      <span class="who">to submit ideas and vote</span>`;
    $("signin").onclick = signIn;
  }
  $("submit-form").hidden = !user;
  $("submit-locked").hidden = !!user;
  $("admin").hidden = !isAdmin();
}

// ── Ideas list ────────────────────────────────────────────────────────────
async function loadMyVotes() {
  myVotes = new Set();
  if (!user) return;
  const snap = await getDocs(query(collection(db, "votes"), where("uid", "==", user.uid)));
  snap.forEach((d) => myVotes.add(d.data().ideaId));
}

function ideaCard(id, d) {
  const voted = myVotes.has(id);
  return `<li class="idea ch-${esc(d.channel)} reveal in" data-id="${esc(id)}">
    <button class="vote${voted ? " on" : ""}" type="button" aria-pressed="${voted}"
      aria-label="${voted ? "Remove your vote" : "Vote for this idea"}">
      <span class="arrow" aria-hidden="true"></span><span class="count">${d.votes || 0}</span>
    </button>
    <div class="idea-body">
      <span class="chtag">${esc(CH[d.channel] || "")}</span>
      <h3>${esc(d.title)}</h3>
      ${d.details ? `<p>${esc(d.details)}</p>` : ""}
      <span class="by">Suggested by ${esc(d.authorName)}</span>
    </div>
  </li>`;
}

async function loadIdeas() {
  const list = $("ideas");
  const q = query(collection(db, "ideas"), where("status", "==", "approved"),
    orderBy(sort === "top" ? "votes" : "createdAt", "desc"), limit(60));
  try {
    const snap = await getDocs(q);
    list.innerHTML = snap.empty
      ? `<li class="empty">No ideas yet. Be the first to suggest a fight.</li>`
      : snap.docs.map((d) => ideaCard(d.id, d.data())).join("");
    $("board-status").textContent = "";
  } catch (e) {
    console.error(e);
    say($("board-status"), "Couldn't load ideas right now. Refresh to try again.", true);
  }
}

async function toggleVote(li) {
  const id = li.dataset.id;
  if (!user) return signIn();
  if (busy.has(id)) return;
  busy.add(id);
  const btn = li.querySelector(".vote"), count = li.querySelector(".count");
  const voted = myVotes.has(id);
  // optimistic update, reverted if the write is refused
  btn.classList.toggle("on", !voted); btn.setAttribute("aria-pressed", String(!voted));
  count.textContent = String(+count.textContent + (voted ? -1 : 1));
  const b = writeBatch(db);
  const voteRef = doc(db, "votes", `${user.uid}_${id}`), ideaRef = doc(db, "ideas", id);
  if (voted) { b.delete(voteRef); b.update(ideaRef, { votes: increment(-1) }); }
  else { b.set(voteRef, { uid: user.uid, ideaId: id, createdAt: serverTimestamp() });
         b.update(ideaRef, { votes: increment(1) }); }
  try { await b.commit(); voted ? myVotes.delete(id) : myVotes.add(id); }
  catch (e) {
    console.error(e);
    btn.classList.toggle("on", voted); btn.setAttribute("aria-pressed", String(voted));
    count.textContent = String(+count.textContent + (voted ? 1 : -1));
    say($("board-status"), "That vote didn't go through. Refresh and try again.", true);
  } finally { busy.delete(id); }
}

// ── Idea of the month ─────────────────────────────────────────────────────
const fmtMonth = (m, opts = { month: "long", year: "numeric" }) =>
  new Date(m + "-15T12:00:00Z").toLocaleDateString("en-US", opts);
async function loadMonthly() {
  try {
    const [st, past] = await Promise.all([
      getDoc(doc(db, "standings", "current")),
      getDocs(query(collection(db, "winners"), orderBy("month", "desc"), limit(6))),
    ]);
    const thisMonth = new Date().toISOString().slice(0, 7);
    const s = st.exists() ? st.data() : null;
    const leaders = s && s.month === thisMonth ? s.leaders : [];
    const wins = past.docs.map((d) => d.data());
    const champ = wins[0] && wins[0].month < thisMonth ? wins[0] : null;
    $("champ").hidden = !champ;
    if (champ) $("champ").innerHTML = `<p class="champ-k">Idea of the Month · ${esc(fmtMonth(champ.month))}</p>
      <p class="champ-t">${esc(champ.title)}</p>
      <p class="champ-m">${[CH[champ.channel],
        champ.gained != null && `+${champ.gained} votes in ${fmtMonth(champ.month, { month: "long" })}`,
        champ.authorName && `suggested by ${champ.authorName}`].filter(Boolean).map(esc).join(" · ")}</p>
      ${champ.videoId ? `<a class="btn champ-watch" href="https://www.youtube.com/watch?v=${esc(champ.videoId)}">Watch the video</a>` : ""}
      ${isAdmin() ? `<form class="champ-admin" data-month="${esc(champ.month)}">
        <label for="champ-url">${champ.videoId ? "Change the" : "Link the"} video for this winner</label>
        <div><input id="champ-url" name="url" placeholder="YouTube link, e.g. https://youtu.be/5IUXc8rFqao" required>
        <button class="btn sm" type="submit">Save video</button></div>
        <p class="champ-admin-msg" role="status"></p></form>` : ""}`;
    $("winner").innerHTML = `<p class="w-day">Leading ${esc(fmtMonth(thisMonth, { month: "long" }))} so far</p>` +
      (leaders.length ? `<ol class="leaders">${leaders.map((l, i) => `<li${i ? "" : ' class="lead"'}>
          <span class="w-title">${esc(l.title)}</span>
          <span class="w-meta">${esc(CH[l.channel] || "")} · +${l.gained} votes this month · by ${esc(l.authorName)}</span></li>`).join("")}</ol>
          <p class="w-note">Standings update every morning. The winner is announced on the 1st.</p>`
        : `<p class="w-none">No votes this month yet. The idea with the most votes by the end of the month wins.</p>`);
    $("winners").innerHTML = wins.slice(champ ? 1 : 0).map((w) =>
      `<li><span class="w-d">${esc(fmtMonth(w.month, { month: "short", year: "numeric" }))}</span> ${w.videoId
        ? `<a href="https://www.youtube.com/watch?v=${esc(w.videoId)}">${esc(w.title)}</a>` : esc(w.title)}${w.gained != null ? ` <span class="w-g">+${w.gained}</span>` : ""}</li>`).join("");
    $("winners-h").hidden = wins.length <= (champ ? 1 : 0);
  } catch (e) { console.error(e); }
}

// ── Submitting ────────────────────────────────────────────────────────────
async function loadMine() {
  const box = $("mine");
  if (!user) { box.innerHTML = ""; return; }
  const snap = await getDocs(query(collection(db, "ideas"), where("authorUid", "==", user.uid), limit(20)));
  const rows = snap.docs.map((d) => d.data()).filter((d) => d.status !== "approved");
  box.innerHTML = rows.length ? `<h3>Your submissions</h3><ul>${rows.map((d) =>
    `<li>${esc(d.title)} <span class="st st-${esc(d.status)}">${d.status === "pending" ? "Waiting for approval" : "Not approved"}</span></li>`
  ).join("")}</ul>` : "";
}

async function submitIdea(ev) {
  ev.preventDefault();
  const f = ev.target, msg = $("submit-msg");
  const title = f.title.value.trim(), details = f.details.value.trim();
  if (title.length < 8) return say(msg, "Give the idea a title of at least 8 characters.", true);
  f.querySelector("button").disabled = true;
  try {
    await addDoc(collection(db, "ideas"), { title, details, channel: f.channel.value,
      authorUid: user.uid, authorName: shortName(user), status: "pending", votes: 0, createdAt: serverTimestamp() });
    f.reset();
    say(msg, "Got it! Your idea will show up here once it's approved.");
    loadMine();
  } catch (e) { console.error(e); say(msg, "Couldn't submit that. Check the length and try again.", true); }
  finally { f.querySelector("button").disabled = false; }
}

// ── Admin queue ───────────────────────────────────────────────────────────
async function loadQueue() {
  if (!isAdmin()) return;
  const snap = await getDocs(query(collection(db, "ideas"), where("status", "==", "pending"),
    orderBy("createdAt", "desc"), limit(50)));
  $("queue").innerHTML = snap.empty ? `<li class="empty">Nothing waiting. Nice.</li>` :
    snap.docs.map((d) => { const x = d.data(); return `<li data-id="${esc(d.id)}" data-uid="${esc(x.authorUid)}">
      <div><span class="chtag">${esc(CH[x.channel])}</span><strong>${esc(x.title)}</strong>
      ${x.details ? `<p>${esc(x.details)}</p>` : ""}<span class="by">${esc(x.authorName)}</span></div>
      <div class="q-actions"><button class="btn sm" data-act="approved" type="button">Approve</button>
      <button class="linkbtn" data-act="rejected" type="button">Reject</button>
      <button class="linkbtn" data-act="ban" type="button">Reject + ban author</button></div></li>`; }).join("");
}

async function moderate(btn) {
  const li = btn.closest("li"), act = btn.dataset.act;
  btn.disabled = true;
  try {
    if (act === "ban") await setDoc(doc(db, "banned", li.dataset.uid), { at: serverTimestamp() });
    await updateDoc(doc(db, "ideas", li.dataset.id), { status: act === "approved" ? "approved" : "rejected" });
    li.remove();
    if (act === "approved") loadIdeas();
  } catch (e) { console.error(e); btn.disabled = false; }
}

// Accepts watch?v=, youtu.be/, /shorts/, /live/, /embed/ links or a bare 11-character id.
function videoIdFrom(text) {
  const s = text.trim();
  if (/^[A-Za-z0-9_-]{11}$/.test(s)) return s;
  try {
    const u = new URL(s);
    const v = u.searchParams.get("v") || u.pathname.split("/").filter(Boolean).pop();
    return /^[A-Za-z0-9_-]{11}$/.test(v || "") ? v : null;
  } catch { return null; }
}

async function linkVideo(form) {
  const msg = form.querySelector(".champ-admin-msg");
  const id = videoIdFrom(form.url.value);
  if (!id) return say(msg, "That doesn't look like a YouTube video link.", true);
  form.querySelector("button").disabled = true;
  try {
    await updateDoc(doc(db, "winners", form.dataset.month), { videoId: id });
    loadMonthly();
  } catch (e) {
    console.error(e);
    say(msg, "Couldn't save the video. Are you signed in as the admin?", true);
    form.querySelector("button").disabled = false;
  }
}

// ── Wiring ────────────────────────────────────────────────────────────────
$("ideas").addEventListener("click", (e) => { const li = e.target.closest(".vote")?.closest(".idea"); if (li) toggleVote(li); });
$("queue").addEventListener("click", (e) => { const b = e.target.closest("button[data-act]"); if (b) moderate(b); });
$("submit-form").addEventListener("submit", submitIdea);
$("champ").addEventListener("submit", (e) => { e.preventDefault(); linkVideo(e.target); });
document.querySelectorAll("[data-sort]").forEach((b) => b.addEventListener("click", () => {
  sort = b.dataset.sort;
  document.querySelectorAll("[data-sort]").forEach((x) => x.setAttribute("aria-pressed", String(x === b)));
  loadIdeas();
}));

loadMonthly();
onAuthStateChanged(auth, async (u) => {
  user = u;
  renderAuth();
  await loadMyVotes().catch(console.error);
  loadIdeas();
  loadMine().catch(console.error);
  loadQueue().catch(console.error);
  loadMonthly();  // re-render so the admin sees the link-video box
});
