import { initializeTestEnvironment, assertSucceeds, assertFails } from "@firebase/rules-unit-testing";
import { doc, getDoc, setDoc, updateDoc, writeBatch, serverTimestamp, collection, deleteDoc } from "firebase/firestore";
import fs from "fs";
const env = await initializeTestEnvironment({ projectId: "demo-valve",
  firestore: { rules: fs.readFileSync(new URL("../firestore.rules", import.meta.url), "utf8"), host: "127.0.0.1", port: 8080 } });
await env.clearFirestore();
const db = uid => env.authenticatedContext(uid).firestore();
const A = db("admin"), K = db("kim"), L = db("lee"), X = db("stranger");
let pass = 0, fail = 0;
async function t(name, p, ok) { try { await (ok ? assertSucceeds(p) : assertFails(p)); pass++; } catch (e) { fail++; console.log("FAIL:", name, e.message); } }
const user = (login, name, role="user") => ({ login, name, dept: "", role, active: true, mustChangePw: true, createdAt: serverTimestamp() });

// 최초 설정
let b = writeBatch(X); b.set(doc(X, "users/stranger"), user("s","s","admin"));
await t("stranger self-admin without setup doc", b.commit(), false);
b = writeBatch(A); b.set(doc(A, "users/admin"), user("admin","관리자","admin")); b.set(doc(A, "meta/setup"), { adminUid: "admin" });
await t("first admin setup", b.commit(), true);
b = writeBatch(X); b.set(doc(X, "users/stranger"), user("s","s","admin")); 
await t("second setup blocked", b.commit(), false);
await t("stranger write own user", setDoc(doc(X, "users/stranger"), user("s","s")), false);
await t("admin creates kim", setDoc(doc(A, "users/kim"), user("kim","김운영")), true);
await t("admin creates lee (팀장)", setDoc(doc(A, "users/lee"), { ...user("lee","이기계"), canVerify: true }), true);
await t("canVerify must be bool", setDoc(doc(A, "users/bad"), { ...user("bad","b"), canVerify: "yes" }), false);
await t("kim grants self canVerify", updateDoc(doc(K, "users/kim"), { canVerify: true }), false);
await t("kim clears mustChangePw", updateDoc(doc(K, "users/kim"), { mustChangePw: false }), true);
await t("kim sets own session", updateDoc(doc(K, "users/kim"), { session: "abc" }), true);
await t("kim sets lee session blocked", updateDoc(doc(K, "users/lee"), { session: "abc" }), false);
await t("kim makes self admin", updateDoc(doc(K, "users/kim"), { role: "admin" }), false);
await t("admin deactivates self", updateDoc(doc(A, "users/admin"), { active: false }), false);
await t("stranger reads valves", getDoc(doc(X, "valves/v1")), false);

// 밸브 등록
const valve = { seq: 1, area: "축열조", tag: "HV-301", pid: "", target: "CLOSE", note: "", owner: "", phone: "", workStart: "", workEnd: "",
  current: "미확인", status: "미조작", operatedBy: "", operatedById: "", operatedAt: null, verifiedBy: "", verifiedById: "", verifiedAt: null, rev: 0, active: true, batch: "" };
await t("kim creates valve", setDoc(doc(K, "valves/v1"), valve), false);
b = writeBatch(A); b.set(doc(A, "valves/v1"), valve);
b.set(doc(collection(A, "events")), { valveId: "v1", tag: "HV-301", area: "축열조", kind: "등록", userId: "admin", userName: "관리자", ts: serverTimestamp(), toState: "CLOSE", fromState: "", memo: "", rev: 0 });
await t("admin creates valve + event", b.commit(), true);
await t("kim reads valve", getDoc(doc(K, "valves/v1")), true);

const operate = (fs_, uid, name, state, rev) => {
  const bb = writeBatch(fs_);
  bb.update(doc(fs_, "valves/v1"), { current: state, status: "확인대기", operatedBy: name, operatedById: uid, operatedAt: serverTimestamp(), verifiedBy: "", verifiedById: "", verifiedAt: null, rev: rev + 1 });
  bb.set(doc(collection(fs_, "events")), { valveId: "v1", tag: "HV-301", area: "축열조", kind: "조작", userId: uid, userName: name, ts: serverTimestamp(), fromState: "미확인", toState: state, memo: "", rev: rev + 1 });
  return bb.commit();
};
const verify = (fs_, uid, name, ok, rev) => {
  const bb = writeBatch(fs_);
  bb.update(doc(fs_, "valves/v1"), { status: ok ? "확인완료" : "불일치", verifiedBy: name, verifiedById: uid, verifiedAt: serverTimestamp(), rev: rev + 1 });
  bb.set(doc(collection(fs_, "events")), { valveId: "v1", tag: "HV-301", area: "축열조", kind: ok ? "확인" : "불일치", userId: uid, userName: name, ts: serverTimestamp(), fromState: "CLOSE", toState: "CLOSE", memo: "", rev: rev + 1 });
  return bb.commit();
};
await t("kim operates as lee (forged name)", operate(K, "kim", "이기계", "CLOSE", 0), false);
await t("kim operates with wrong rev", operate(K, "kim", "김운영", "CLOSE", 5), false);
await t("kim operates CLOSE", operate(K, "kim", "김운영", "CLOSE", 0), true);
await t("bad phase blocked", updateDoc(doc(K, "valves/v1"), { phase: "기타", rev: 2 }), false);
await t("kim (no 확인권한) self-verifies", verify(K, "kim", "김운영", true, 1), false);
await t("lee verifies as kim id", verify(L, "kim", "김운영", true, 1), false);
await t("lee verifies", verify(L, "lee", "이기계", true, 1), true);
await t("lee verifies again (already done)", verify(L, "lee", "이기계", true, 2), false);
// 운영팀장(lee)·관리자는 본인 조작분도 확인 가능 (별도 밸브 v9)
await t("admin creates v9", setDoc(doc(A, "valves/v9"), { ...valve, tag: "HV-999" }), true);
const op9 = (fs_, uid, name, state, rev, ok) => { const bb = writeBatch(fs_);
  bb.update(doc(fs_, "valves/v9"), ok ? { status: "확인완료", verifiedBy: name, verifiedById: uid, verifiedAt: serverTimestamp(), rev: rev + 1 }
    : { current: state, status: "확인대기", operatedBy: name, operatedById: uid, operatedAt: serverTimestamp(), verifiedBy: "", verifiedById: "", verifiedAt: null, rev: rev + 1 });
  bb.set(doc(collection(fs_, "events")), { valveId: "v9", kind: ok ? "확인" : "조작", userId: uid, userName: name, ts: serverTimestamp(), rev: rev + 1 });
  return bb.commit(); };
await t("lee operates v9", op9(L, "lee", "이기계", "CLOSE", 0, false), true);
await t("lee (팀장) verifies own operation", op9(L, "lee", "이기계", "", 1, true), true);
await t("admin operates v9", op9(A, "admin", "관리자", "OPEN", 2, false), true);
await t("admin verifies own operation", op9(A, "admin", "관리자", "", 3, true), true);
await t("fake event without valve change", setDoc(doc(collection(K, "events")), { valveId: "v1", kind: "조작", userId: "kim", userName: "김운영", ts: serverTimestamp(), rev: 3 }), false);
await t("admin forges verification", updateDoc(doc(A, "valves/v1"), { status: "확인완료", verifiedBy: "관리자", verifiedById: "admin", rev: 3 }), false);
await t("admin edits note", updateDoc(doc(A, "valves/v1"), { note: "메모", rev: 3 }), true);
await t("admin resets", updateDoc(doc(A, "valves/v1"), { current: "미확인", status: "미조작", operatedBy: "", operatedById: "", operatedAt: null, verifiedBy: "", verifiedById: "", verifiedAt: null, rev: 4 }), true);
// 엑셀 현재상태 반영
const xs = { current: "OPEN", status: "확인대기", operatedBy: "관리자(엑셀)", operatedById: "admin", operatedAt: serverTimestamp(), verifiedBy: "", verifiedById: "", verifiedAt: null };
await t("admin creates valve with excel state", setDoc(doc(A, "valves/v2"), { ...valve, tag: "HV-302", ...xs }), true);
await t("admin excel state forged operator", setDoc(doc(A, "valves/v3"), { ...valve, tag: "HV-303", ...xs, operatedById: "kim" }), false);
await t("admin excel state on existing", updateDoc(doc(A, "valves/v1"), { ...xs, current: "CLOSE", rev: 5 }), true);
await t("kim excel-style state", updateDoc(doc(K, "valves/v2"), { ...xs, operatedById: "kim", rev: 1 }), false);
let bb = writeBatch(A); bb.set(doc(collection(A, "events")), { valveId: "v2", kind: "엑셀반영", userId: "admin", userName: "관리자", ts: serverTimestamp(), rev: 0 });
await t("admin excel event", bb.commit(), true);
await t("lee verifies excel state", (() => { const b2 = writeBatch(L);
  b2.update(doc(L, "valves/v2"), { status: "확인완료", verifiedBy: "이기계", verifiedById: "lee", verifiedAt: serverTimestamp(), rev: 1 });
  b2.set(doc(collection(L, "events")), { valveId: "v2", kind: "확인", userId: "lee", userName: "이기계", ts: serverTimestamp(), rev: 1 }); return b2.commit(); })(), true);
// 사진
const photo = (fs_, uid, name, size, pid) => { const b2 = writeBatch(fs_);
  b2.set(doc(fs_, "photos/" + pid), { valveId: "v1", thumb: "x", caption: "c", takenAt: 1, userId: uid, userName: name, ts: serverTimestamp() });
  b2.set(doc(fs_, "photoFull/" + pid), { data: "x".repeat(size), userId: uid });
  b2.set(doc(collection(fs_, "events")), { valveId: "v1", kind: "사진", photoId: pid, userId: uid, userName: name, ts: serverTimestamp() });
  return b2.commit(); };
await t("kim uploads photo", photo(K, "kim", "김운영", 500000, "p1"), true);
await t("photo too big", photo(K, "kim", "김운영", 1010000, "p2"), false);
await t("lee overwrites kim photo full", setDoc(doc(L, "photoFull/p1"), { data: "y", userId: "lee" }), false);
await t("photo event without photo", setDoc(doc(collection(K, "events")), { valveId: "v1", kind: "사진", photoId: "nope", userId: "kim", userName: "김운영", ts: serverTimestamp() }), false);
await t("lee reads photo", getDoc(doc(L, "photoFull/p1")), true);
await t("kim deletes photo", deleteDoc(doc(K, "photos/p1")), false);
await t("photo count +1", updateDoc(doc(K, "valves/v1"), { photoCount: 1 }), true);
await t("photo count +5 blocked", updateDoc(doc(K, "valves/v1"), { photoCount: 6 }), false);
await t("photo count with other field blocked", updateDoc(doc(K, "valves/v1"), { photoCount: 2, note: "x" }), false);
await t("admin writes secret", setDoc(doc(A, "userSecrets/kim"), { pw: "kimpw12", login: "kim" }), true);
await t("admin reads secret", getDoc(doc(A, "userSecrets/kim")), true);
await t("kim reads own secret blocked", getDoc(doc(K, "userSecrets/kim")), false);
await t("lee reads kim secret blocked", getDoc(doc(L, "userSecrets/kim")), false);
await t("kim updates own secret", setDoc(doc(K, "userSecrets/kim"), { pw: "newpw12", login: "kim" }), true);
await t("lee writes kim secret blocked", setDoc(doc(L, "userSecrets/kim"), { pw: "hacked1", login: "kim" }), false);
await t("admin writes login map", setDoc(doc(A, "logins/kim"), { email: "kim@valve.local", uid: "kim" }), true);
await t("kim writes login map blocked", setDoc(doc(K, "logins/kim"), { email: "x@valve.local", uid: "kim" }), false);
await t("anyone reads login map", getDoc(doc(env.unauthenticatedContext().firestore(), "logins/kim")), true);
await t("kim deletes user lee blocked", deleteDoc(doc(K, "users/lee")), false);
await t("admin deletes self blocked", deleteDoc(doc(A, "users/admin")), false);
await t("kim deletes event", deleteDoc(doc(K, "events/x")), false);
await t("admin deletes event", deleteDoc(doc(A, "events/x")), true);
await t("admin deletes user bad-free", deleteDoc(doc(A, "users/nobody")), true);
await t("admin deactivates kim", updateDoc(doc(A, "users/kim"), { active: false }), true);
await t("deactivated kim reads valve", getDoc(doc(K, "valves/v1")), false);
console.log(`passed ${pass}, failed ${fail}`);
await env.cleanup();
process.exit(fail ? 1 : 0);
