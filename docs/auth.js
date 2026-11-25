import { initializeApp } from "https://www.gstatic.com/firebasejs/11.6.0/firebase-app.js";
import {
  getAuth,
  onAuthStateChanged,
  signInWithPopup,
  signInWithRedirect,
  getRedirectResult,
  GoogleAuthProvider,
  GithubAuthProvider,
  signInWithEmailAndPassword,
  createUserWithEmailAndPassword,
  sendPasswordResetEmail,
  updateProfile,
  signOut,
} from "https://www.gstatic.com/firebasejs/11.6.0/firebase-auth.js";
import {
  getFirestore,
  doc,
  getDoc,
  setDoc,
  updateDoc,
  serverTimestamp,
  increment,
} from "https://www.gstatic.com/firebasejs/11.6.0/firebase-firestore.js";

const firebaseConfig = {
  projectId: "lulckit-web",
  appId: "1:946019479374:web:6bda4b4126f96e5e36b81f",
  storageBucket: "lulckit-web.firebasestorage.app",
  apiKey: "AIzaSyDRbFMobwx0ZuRU78erv_w1shMVJ0WVymU",
  authDomain: "lulckit-web.firebaseapp.com",
  messagingSenderId: "946019479374",
};

const app = initializeApp(firebaseConfig);
const auth = getAuth(app);
const db = getFirestore(app);

const $ = (id) => document.getElementById(id);

let currentUser = null;
let profileData = null;
let profileReadyPromise = Promise.resolve();
let emailMode = "signin";

function safePhotoUrl(url) {
  const clean = String(url || "").trim().slice(0, 500);
  return /^https?:\/\//i.test(clean) ? clean : "";
}

function escapeHtml(s) {
  return String(s).replace(/[&<>"']/g, (c) => ({
    "&": "&amp;",
    "<": "&lt;",
    ">": "&gt;",
    '"': "&quot;",
    "'": "&#39;",
  }[c]));
}

function showMsg(elId, msg, isError = false) {
  const el = $(elId);
  if (!el) return;
  el.textContent = msg;
  el.classList.toggle("hidden", !msg);
  el.classList.toggle("is-error", Boolean(isError));
}

function friendlyAuthError(err) {
  const code = err?.code || "";
  if (code === "auth/unauthorized-domain") {
    return "This domain is not yet listed under Firebase Auth Authorized Domains.";
  }
  if (code === "auth/operation-not-allowed") {
    return "This sign-in provider is not enabled in Firebase Console yet.";
  }
  if (code === "auth/invalid-credential" || code === "auth/wrong-password" || code === "auth/user-not-found") {
    return "Incorrect email or password.";
  }
  if (code === "auth/email-already-in-use") {
    return "An account with this email already exists. Try signing in instead.";
  }
  if (code === "auth/weak-password") {
    return "Password must be at least 6 characters.";
  }
  if (code === "auth/popup-closed-by-user" || code === "auth/cancelled-popup-request") {
    return "Sign-in popup was closed before finishing.";
  }
  return err?.message || "Authentication failed. Please try again.";
}

async function ensureUserProfile(user) {
  const ref = doc(db, "users", user.uid);
  const snap = await getDoc(ref);
  const email = String(user.email || "").slice(0, 200);
  const displayName = String(user.displayName || "").slice(0, 100);
  const photoURL = safePhotoUrl(user.photoURL);
  const provider = String(user.providerData?.[0]?.providerId || "password").slice(0, 40);

  if (!snap.exists()) {
    const initial = {
      email,
      displayName,
      photoURL,
      provider,
      organization: "",
      role: "",
      exportsCount: 0,
      savedPresets: [],
      createdAt: serverTimestamp(),
      lastSeenAt: serverTimestamp(),
    };
    await setDoc(ref, initial);
    profileData = { ...initial, savedPresets: [], exportsCount: 0 };
  } else {
    const existing = snap.data() || {};
    const updates = {
      email: email || String(existing.email || "").slice(0, 200),
      provider: provider || String(existing.provider || "password").slice(0, 40),
      lastSeenAt: serverTimestamp(),
    };
    if (!existing.displayName && displayName) updates.displayName = displayName;
    if (!existing.photoURL && photoURL) updates.photoURL = photoURL;
    await updateDoc(ref, updates);
    profileData = { ...existing, ...updates };
  }
  renderProfileUI();
}

function readStudioSettings() {
  return {
    title: String($("titleInput")?.value || "").slice(0, 120),
    mode: String($("modeSelect")?.value || "categorical").slice(0, 24),
    palette: String($("paletteSelect")?.value || "arcgis-crop").slice(0, 40),
    pageSize: String($("pageSizeSelect")?.value || "a4").slice(0, 20),
    orientation: String($("orientationSelect")?.value || "auto").slice(0, 20),
    arrowStyle: String($("arrowStyleSelect")?.value || "compass").slice(0, 24),
    scalebarStyle: String($("scalebarStyleSelect")?.value || "arcgis").slice(0, 24),
    showGrid: Boolean($("gridCheck")?.checked ?? true),
  };
}

function applyStudioPreset(preset) {
  const map = [
    ["titleInput", preset.title, "input"],
    ["modeSelect", preset.mode, "change"],
    ["paletteSelect", preset.palette, "change"],
    ["pageSizeSelect", preset.pageSize, "change"],
    ["orientationSelect", preset.orientation, "change"],
    ["arrowStyleSelect", preset.arrowStyle, "change"],
    ["scalebarStyleSelect", preset.scalebarStyle, "change"],
  ];
  for (const [id, val, evt] of map) {
    const el = $(id);
    if (el && val !== undefined) {
      el.value = String(val);
      el.dispatchEvent(new Event(evt, { bubbles: true }));
    }
  }
  const grid = $("gridCheck");
  if (grid && typeof preset.showGrid === "boolean") {
    grid.checked = preset.showGrid;
    grid.dispatchEvent(new Event("change", { bubbles: true }));
  }
}

function renderNavAuth(user) {
  const btn = $("authOpenBtn");
  const studioBarBtn = $("studioPresetActionBtn");
  const studioBarHint = $("studioPresetHint");
  if (!btn) return;

  if (!user) {
    btn.classList.remove("is-signed-in");
    btn.innerHTML = `<span class="nav-auth-label">Sign In</span>`;
    btn.setAttribute("aria-label", "Sign in to LULCkit");
    if (studioBarBtn) studioBarBtn.textContent = "Sign In to Sync Presets";
    if (studioBarHint) studioBarHint.textContent = "Optional: save palettes & profile across devices";
    return;
  }

  const name = (profileData?.displayName || user.displayName || user.email || "Account").trim();
  const initial = (name[0] || "U").toUpperCase();
  const shortName = name.split(/\s+/)[0].slice(0, 12);
  const photo = safePhotoUrl(profileData?.photoURL || user.photoURL);
  btn.classList.add("is-signed-in");
  btn.setAttribute("aria-label", `Account menu for ${name}`);
  btn.innerHTML = photo
    ? `<img class="nav-auth-avatar" src="${escapeHtml(photo)}" alt="" referrerpolicy="no-referrer" /><span class="nav-auth-name">${escapeHtml(shortName)}</span>`
    : `<span class="nav-auth-avatar-fallback" aria-hidden="true">${escapeHtml(initial)}</span><span class="nav-auth-name">${escapeHtml(shortName)}</span>`;

  if (studioBarBtn) studioBarBtn.textContent = "Saved Presets & Profile";
  const count = Array.isArray(profileData?.savedPresets) ? profileData.savedPresets.length : 0;
  if (studioBarHint) studioBarHint.textContent = `Signed in as ${shortName} · ${count} saved preset${count === 1 ? "" : "s"}`;
}

function renderProfileUI() {
  if (!currentUser) return;
  renderNavAuth(currentUser);

  const head = $("profileSummary");
  if (head) {
    const name = profileData?.displayName || currentUser.displayName || "LULCkit User";
    const email = profileData?.email || currentUser.email || "No public email";
    const exports = Number(profileData?.exportsCount || 0);
    const provider = profileData?.provider || "password";
    head.innerHTML = `
      <div><strong>${escapeHtml(name)}</strong><span>${escapeHtml(email)}</span></div>
      <div class="profile-meta-pills">
        <span class="preset-chip">${escapeHtml(provider)}</span>
        <span class="preset-chip">${exports} export${exports === 1 ? "" : "s"}</span>
      </div>`;
  }

  if ($("profName")) $("profName").value = profileData?.displayName || currentUser.displayName || "";
  if ($("profOrg")) $("profOrg").value = profileData?.organization || "";
  if ($("profRole")) $("profRole").value = profileData?.role || "";

  const list = $("presetList");
  if (!list) return;
  const presets = Array.isArray(profileData?.savedPresets) ? profileData.savedPresets : [];
  if (!presets.length) {
    list.innerHTML = `<p class="preset-empty">No saved presets yet. Configure Studio colors or layout and click Save Current Settings.</p>`;
    return;
  }

  list.innerHTML = presets
    .map(
      (p, idx) => `
      <div class="preset-row">
        <div>
          <strong>${escapeHtml(p.name || `Preset ${idx + 1}`)}</strong>
          <small>${escapeHtml(p.mode || "categorical")} · ${escapeHtml(p.palette || "arcgis-crop")} · ${escapeHtml((p.pageSize || "a4").toUpperCase())}</small>
        </div>
        <div class="preset-actions">
          <button class="btn btn-sm btn-primary" type="button" data-apply-idx="${idx}">Apply</button>
          <button class="btn btn-sm" type="button" data-del-idx="${idx}" aria-label="Delete preset">Delete</button>
        </div>
      </div>`
    )
    .join("");

  list.querySelectorAll("[data-apply-idx]").forEach((el) => {
    el.addEventListener("click", () => {
      const item = presets[Number(el.dataset.applyIdx)];
      if (!item) return;
      applyStudioPreset(item);
      $("profileModal")?.close();
      showMsg("profileMsg", "");
    });
  });

  list.querySelectorAll("[data-del-idx]").forEach((el) => {
    el.addEventListener("click", async () => {
      const idx = Number(el.dataset.delIdx);
      const next = presets.filter((_, i) => i !== idx);
      await updateDoc(doc(db, "users", currentUser.uid), {
        savedPresets: next,
        lastSeenAt: serverTimestamp(),
      });
      profileData.savedPresets = next;
      renderProfileUI();
    });
  });
}

async function oauthSignIn(provider) {
  showMsg("authMsg", "");
  try {
    await signInWithPopup(auth, provider);
    $("authModal")?.close();
  } catch (err) {
    if (err?.code === "auth/popup-blocked") {
      await signInWithRedirect(auth, provider);
      return;
    }
    showMsg("authMsg", friendlyAuthError(err), true);
  }
}

function initAuthUI() {
  const authModal = $("authModal");
  const profileModal = $("profileModal");

  $("authOpenBtn")?.addEventListener("click", () => {
    showMsg("authMsg", "");
    showMsg("profileMsg", "");
    if (currentUser) profileModal?.showModal();
    else authModal?.showModal();
  });

  $("studioPresetActionBtn")?.addEventListener("click", () => {
    if (currentUser) profileModal?.showModal();
    else authModal?.showModal();
  });

  $("authCloseBtn")?.addEventListener("click", () => authModal?.close());
  $("profileCloseBtn")?.addEventListener("click", () => profileModal?.close());

  [authModal, profileModal].forEach((dlg) => {
    dlg?.addEventListener("click", (e) => {
      if (e.target === dlg) dlg.close();
    });
  });

  $("googleSignInBtn")?.addEventListener("click", () => oauthSignIn(new GoogleAuthProvider()));
  $("githubSignInBtn")?.addEventListener("click", () => oauthSignIn(new GithubAuthProvider()));

  document.querySelectorAll("[data-auth-tab]").forEach((tab) => {
    tab.addEventListener("click", () => {
      emailMode = tab.dataset.authTab === "signup" ? "signup" : "signin";
      document.querySelectorAll("[data-auth-tab]").forEach((t) => t.classList.toggle("active", t === tab));
      $("authNameRow")?.classList.toggle("hidden", emailMode !== "signup");
      if ($("emailSubmitBtn")) $("emailSubmitBtn").textContent = emailMode === "signup" ? "Create Free Account" : "Sign In with Email";
      $("forgotPwBtn")?.classList.toggle("hidden", emailMode === "signup");
      showMsg("authMsg", "");
    });
  });

  $("emailAuthForm")?.addEventListener("submit", async (e) => {
    e.preventDefault();
    showMsg("authMsg", "");
    const email = String($("authEmail")?.value || "").trim();
    const password = String($("authPassword")?.value || "");
    const fullName = String($("authFullName")?.value || "").trim().slice(0, 100);
    if (!email || !password) return;

    try {
      if (emailMode === "signup") {
        const cred = await createUserWithEmailAndPassword(auth, email, password);
        if (fullName) {
          await updateProfile(cred.user, { displayName: fullName });
          await profileReadyPromise;
          await updateDoc(doc(db, "users", cred.user.uid), {
            displayName: fullName,
            lastSeenAt: serverTimestamp(),
          });
          if (profileData) profileData.displayName = fullName;
          renderProfileUI();
        }
      } else {
        await signInWithEmailAndPassword(auth, email, password);
      }
      authModal?.close();
    } catch (err) {
      showMsg("authMsg", friendlyAuthError(err), true);
    }
  });

  $("forgotPwBtn")?.addEventListener("click", async () => {
    const email = String($("authEmail")?.value || "").trim();
    if (!email) {
      showMsg("authMsg", "Enter your email address above first to reset password.", true);
      return;
    }
    try {
      await sendPasswordResetEmail(auth, email);
      showMsg("authMsg", "Password reset email sent. Check your inbox.");
    } catch (err) {
      showMsg("authMsg", friendlyAuthError(err), true);
    }
  });

  $("profileForm")?.addEventListener("submit", async (e) => {
    e.preventDefault();
    if (!currentUser) return;
    await profileReadyPromise;
    const displayName = String($("profName")?.value || "").trim().slice(0, 100);
    const organization = String($("profOrg")?.value || "").trim().slice(0, 120);
    const role = String($("profRole")?.value || "").trim().slice(0, 60);
    try {
      await updateDoc(doc(db, "users", currentUser.uid), {
        displayName,
        organization,
        role,
        lastSeenAt: serverTimestamp(),
      });
      if (currentUser.displayName !== displayName && displayName) {
        await updateProfile(currentUser, { displayName }).catch(() => {});
      }
      profileData = { ...(profileData || {}), displayName, organization, role };
      renderProfileUI();
      showMsg("profileMsg", "Profile saved.");
    } catch (err) {
      showMsg("profileMsg", err?.message || "Failed to save profile.", true);
    }
  });

  $("savePresetBtn")?.addEventListener("click", async () => {
    if (!currentUser) return;
    await profileReadyPromise;
    const presets = Array.isArray(profileData?.savedPresets) ? [...profileData.savedPresets] : [];
    if (presets.length >= 20) {
      showMsg("profileMsg", "Maximum 20 saved presets reached. Delete one to add another.", true);
      return;
    }
    const nameInput = String($("presetNameInput")?.value || "").trim();
    const settings = readStudioSettings();
    const presetName = (nameInput || settings.title || `Preset ${presets.length + 1}`).slice(0, 60);
    presets.unshift({ id: String(Date.now()), name: presetName, ...settings });
    try {
      await updateDoc(doc(db, "users", currentUser.uid), {
        savedPresets: presets,
        lastSeenAt: serverTimestamp(),
      });
      profileData = { ...(profileData || {}), savedPresets: presets };
      if ($("presetNameInput")) $("presetNameInput").value = "";
      renderProfileUI();
      showMsg("profileMsg", `Saved "${presetName}" to your account.`);
    } catch (err) {
      showMsg("profileMsg", err?.message || "Could not save preset.", true);
    }
  });

  $("signOutBtn")?.addEventListener("click", async () => {
    await signOut(auth);
    profileModal?.close();
  });

  window.addEventListener("lulckit:export", async () => {
    if (!currentUser) return;
    try {
      await profileReadyPromise;
      await updateDoc(doc(db, "users", currentUser.uid), {
        exportsCount: increment(1),
        lastSeenAt: serverTimestamp(),
      });
      if (profileData) profileData.exportsCount = Number(profileData.exportsCount || 0) + 1;
      renderProfileUI();
    } catch (_) {
      // Export tracking is best-effort and must never interrupt downloads
    }
  });

  getRedirectResult(auth).catch((err) => {
    if (err?.code) showMsg("authMsg", friendlyAuthError(err), true);
  });

  onAuthStateChanged(auth, (user) => {
    currentUser = user;
    if (!user) {
      profileData = null;
      profileReadyPromise = Promise.resolve();
      renderNavAuth(null);
      window.dispatchEvent(new CustomEvent("lulckit:authchange", { detail: { user: null } }));
      return;
    }
    renderNavAuth(user);
    profileReadyPromise = ensureUserProfile(user).catch((err) => {
      showMsg("profileMsg", err?.message || "Could not sync user profile.", true);
    });
    window.dispatchEvent(new CustomEvent("lulckit:authchange", { detail: { user: { uid: user.uid, email: user.email, displayName: user.displayName } } }));
  });
}

if (document.readyState === "loading") {
  document.addEventListener("DOMContentLoaded", initAuthUI);
} else {
  initAuthUI();
}
