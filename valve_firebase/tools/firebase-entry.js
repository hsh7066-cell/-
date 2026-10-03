export { initializeApp, deleteApp } from "firebase/app";
export { getAuth, signInWithEmailAndPassword, signOut, onAuthStateChanged, createUserWithEmailAndPassword,
  updatePassword, EmailAuthProvider, reauthenticateWithCredential, connectAuthEmulator } from "firebase/auth";
export { initializeFirestore, persistentLocalCache, persistentMultipleTabManager, connectFirestoreEmulator,
  collection, doc, getDoc, getDocs, setDoc, updateDoc, deleteDoc, query, where, orderBy, limit, onSnapshot, runTransaction,
  writeBatch, serverTimestamp, Timestamp, increment } from "firebase/firestore";
