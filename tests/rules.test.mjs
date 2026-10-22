import { readFileSync } from "node:fs";
import { initializeTestEnvironment, assertSucceeds, assertFails } from "@firebase/rules-unit-testing";
import { doc, getDoc, setDoc, updateDoc, deleteDoc, writeBatch, increment, serverTimestamp,
  collection, query, where, orderBy, getDocs } from "firebase/firestore";

const env = await initializeTestEnvironment({
  projectId: "nerdscience-ideas-test",
  firestore: { rules: readFileSync(process.argv[2], "utf8"), host: "127.0.0.1", port: 8080 },
});

const results = [];
async function t(name, fn) {
  try { await fn(); results.push(["PASS", name]); }
  catch (e) { results.push(["FAIL", name + " :: " + (e.message || e).toString().split("\n")[0]]); }
}

const alice = env.authenticatedContext("alice", { email: "alice@x.com", email_verified: true }).firestore();
const bob = env.authenticatedContext("bob", { email: "bob@x.com", email_verified: true }).firestore();
const admin = env.authenticatedContext("owner", { email: "brattorre@gmail.com", email_verified: true }).firestore();
const fakeAdmin = env.authenticatedContext("faker", { email: "brattorre@gmail.com", email_verified: false }).firestore();
const anon = env.unauthenticatedContext().firestore();

// seed: one approved idea (5 votes), one pending idea by bob
await env.withSecurityRulesDisabled(async (ctx) => {
  const db = ctx.firestore();
  await setDoc(doc(db, "ideas", "ok"), { title: "Approved idea here", details: "", channel: "science",
    authorUid: "bob", authorName: "Bob B.", status: "approved", votes: 5, createdAt: new Date() });
  await setDoc(doc(db, "ideas", "pend"), { title: "Pending idea here", details: "", channel: "history",
    authorUid: "bob", authorName: "Bob B.", status: "pending", votes: 0, createdAt: new Date() });
  await setDoc(doc(db, "winners", "2026-10-21"), { day: "2026-10-21", title: "x" });
  await setDoc(doc(db, "banned", "mallory"), { at: new Date() });
});
const mallory = env.authenticatedContext("mallory", { email: "m@x.com", email_verified: true }).firestore();

const newIdea = (uid, extra = {}) => ({ title: "Could Deadpool survive Stalingrad?", details: "", channel: "science",
  authorUid: uid, authorName: "Al A.", status: "pending", votes: 0, createdAt: serverTimestamp(), ...extra });
const voteBatch = (db, uid, id, dir = 1, { skipVote = false, skipCount = false, by = dir } = {}) => {
  const b = writeBatch(db);
  const v = doc(db, "votes", `${uid}_${id}`);
  if (!skipVote) dir > 0 ? b.set(v, { uid, ideaId: id, createdAt: serverTimestamp() }) : b.delete(v);
  if (!skipCount) b.update(doc(db, "ideas", id), { votes: increment(by) });
  return b.commit();
};

// reading
await t("anyone reads approved ideas", () => assertSucceeds(getDoc(doc(anon, "ideas", "ok"))));
await t("public cannot read pending ideas", () => assertFails(getDoc(doc(anon, "ideas", "pend"))));
await t("other users cannot read someone's pending idea", () => assertFails(getDoc(doc(alice, "ideas", "pend"))));
await t("author reads own pending idea", () => assertSucceeds(getDoc(doc(bob, "ideas", "pend"))));
await t("public list query (approved, by votes) allowed", () => assertSucceeds(getDocs(query(collection(anon, "ideas"),
  where("status", "==", "approved"), orderBy("votes", "desc")))));
await t("unfiltered list query refused", () => assertFails(getDocs(collection(anon, "ideas"))));
await t("winners are public", () => assertSucceeds(getDoc(doc(anon, "winners", "2026-10-21"))));
await t("nobody can write winners", () => assertFails(setDoc(doc(admin, "winners", "x"), { a: 1 })));

// submitting
await t("signed-in user submits a pending idea", () => assertSucceeds(setDoc(doc(alice, "ideas", "a1"), newIdea("alice"))));
await t("anonymous cannot submit", () => assertFails(setDoc(doc(anon, "ideas", "a2"), newIdea("x"))));
await t("cannot self-approve on submit", () => assertFails(setDoc(doc(alice, "ideas", "a3"), newIdea("alice", { status: "approved" }))));
await t("cannot start with votes", () => assertFails(setDoc(doc(alice, "ideas", "a4"), newIdea("alice", { votes: 50 }))));
await t("cannot submit as someone else", () => assertFails(setDoc(doc(alice, "ideas", "a5"), newIdea("bob"))));
await t("title too short refused", () => assertFails(setDoc(doc(alice, "ideas", "a6"), newIdea("alice", { title: "short" }))));
await t("unknown channel refused", () => assertFails(setDoc(doc(alice, "ideas", "a7"), newIdea("alice", { channel: "music" }))));
await t("extra fields refused", () => assertFails(setDoc(doc(alice, "ideas", "a8"), newIdea("alice", { pinned: true }))));
await t("banned user cannot submit", () => assertFails(setDoc(doc(mallory, "ideas", "m1"), newIdea("mallory"))));

// voting
await t("vote = vote doc + counter +1 in one batch", () => assertSucceeds(voteBatch(alice, "alice", "ok", 1)));
await t("second vote on same idea refused", () => assertFails(voteBatch(alice, "alice", "ok", 1)));
await t("counter +1 without a vote doc refused", () => assertFails(voteBatch(bob, "bob", "ok", 1, { skipVote: true })));
await t("vote doc without counter refused", () => assertFails(voteBatch(bob, "bob", "ok", 1, { skipCount: true })));
await t("counter +2 refused", () => assertFails(voteBatch(bob, "bob", "ok", 1, { by: 2 })));
await t("voting as someone else refused", () => assertFails(voteBatch(bob, "alice", "ok", 1)));
await t("cannot vote on pending idea", () => assertFails(voteBatch(alice, "alice", "pend", 1)));
await t("anonymous cannot vote", () => assertFails(voteBatch(anon, "x", "ok", 1)));
await t("banned user cannot vote", () => assertFails(voteBatch(mallory, "mallory", "ok", 1)));
await t("counter is 6 after one vote", async () => {
  const s = await env.withSecurityRulesDisabled(async (c) => getDoc(doc(c.firestore(), "ideas", "ok")));
  if (s.data().votes !== 6) throw new Error("votes = " + s.data().votes);
});
await t("cannot read other users' votes", () => assertFails(getDoc(doc(bob, "votes", "alice_ok"))));
await t("reads own votes via query", () => assertSucceeds(getDocs(query(collection(alice, "votes"), where("uid", "==", "alice")))));
await t("counter -1 without removing vote refused", () => assertFails(voteBatch(alice, "alice", "ok", -1, { skipVote: true })));
await t("unvote = delete + counter -1", () => assertSucceeds(voteBatch(alice, "alice", "ok", -1)));
await t("can vote again after unvoting", () => assertSucceeds(voteBatch(alice, "alice", "ok", 1)));
await t("users cannot edit title of approved idea", () => assertFails(updateDoc(doc(bob, "ideas", "ok"), { title: "Hacked title!!" })));

// moderation
await t("non-admin cannot approve", () => assertFails(updateDoc(doc(bob, "ideas", "pend"), { status: "approved" })));
await t("unverified admin email cannot approve", () => assertFails(updateDoc(doc(fakeAdmin, "ideas", "pend"), { status: "approved" })));
await t("admin sees pending queue", () => assertSucceeds(getDocs(query(collection(admin, "ideas"),
  where("status", "==", "pending"), orderBy("createdAt", "desc")))));
await t("admin approves", () => assertSucceeds(updateDoc(doc(admin, "ideas", "pend"), { status: "approved" })));
await t("admin cannot inflate votes", () => assertFails(updateDoc(doc(admin, "ideas", "ok"), { votes: 999 })));
await t("admin bans a user", () => assertSucceeds(setDoc(doc(admin, "banned", "bob"), { at: serverTimestamp() })));
await t("non-admin cannot ban", () => assertFails(setDoc(doc(alice, "banned", "x"), { at: serverTimestamp() })));
await t("non-admin cannot delete ideas", () => assertFails(deleteDoc(doc(alice, "ideas", "ok"))));

await env.cleanup();
for (const [s, n] of results) console.log(s, n);
const failed = results.filter((r) => r[0] === "FAIL").length;
console.log(`\n${results.length - failed}/${results.length} passed`);
process.exit(failed ? 1 : 0);
