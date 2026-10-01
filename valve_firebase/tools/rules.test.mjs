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
await t("admin creates lee", setDoc(doc(A, "users/lee"), user("lee","이기계")), true);
await t("kim clears mustChangePw", updateDoc(doc(K, "users/kim"), { mustChangePw: false }), true);
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
await t("kim self-verifies", verify(K, "kim", "김운영", true, 1), false);
await t("lee verifies as kim id", verify(L, "kim", "김운영", true, 1), false);
await t("lee verifies", verify(L, "lee", "이기계", true, 1), true);
await t("lee verifies again (already done)", verify(L, "lee", "이기계", true, 2), false);
await t("fake event without valve change", setDoc(doc(collection(K, "events")), { valveId: "v1", kind: "조작", userId: "kim", userName: "김운영", ts: serverTimestamp(), rev: 3 }), false);
await t("admin forges verification", updateDoc(doc(A, "valves/v1"), { status: "확인완료", verifiedBy: "관리자", verifiedById: "admin", rev: 3 }), false);
await t("admin edits note", updateDoc(doc(A, "valves/v1"), { note: "메모", rev: 3 }), true);
await t("admin resets", updateDoc(doc(A, "valves/v1"), { current: "미확인", status: "미조작", operatedBy: "", operatedById: "", operatedAt: null, verifiedBy: "", verifiedById: "", verifiedAt: null, rev: 4 }), true);
await t("event delete blocked", deleteDoc(doc(A, "events/x")), false);
await t("admin deactivates kim", updateDoc(doc(A, "users/kim"), { active: false }), true);
await t("deactivated kim reads valve", getDoc(doc(K, "valves/v1")), false);
console.log(`passed ${pass}, failed ${fail}`);
await env.cleanup();
process.exit(fail ? 1 : 0);
