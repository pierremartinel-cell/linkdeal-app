/* ── State ── */
let state = {
  url: "",
  phrase: "",
  currentPrice: "",
  originalPrice: "",
  brand: "",
  imageUrls: [],       // all scraped urls
  removedUrls: new Set(),
  jobId: null,
  twitterUrl: null,
  carouselImages: [],  // server paths
};

/* ── DOM refs ── */
const $ = id => document.getElementById(id);

const steps = {
  url: $("step-url"),
  edit: $("step-edit"),
  results: $("step-results"),
};

/* ── Step navigation ── */
function showStep(name) {
  Object.values(steps).forEach(s => s.classList.remove("active"));
  steps[name].classList.add("active");
  window.scrollTo(0, 0);
}

/* ── Toast ── */
function toast(msg) {
  let el = document.querySelector(".toast");
  if (!el) {
    el = document.createElement("div");
    el.className = "toast";
    document.body.appendChild(el);
  }
  el.textContent = msg;
  el.classList.add("show");
  setTimeout(() => el.classList.remove("show"), 2000);
}

/* ── STEP 1: Scrape ── */
$("scrape-btn").addEventListener("click", doScrape);
$("product-url").addEventListener("keydown", e => { if (e.key === "Enter") doScrape(); });

// Auto-scrape on paste
$("product-url").addEventListener("paste", () => {
  setTimeout(doScrape, 50);
});

async function doScrape() {
  const url = $("product-url").value.trim();
  if (!url) return;

  $("scrape-error").classList.add("hidden");
  $("scrape-loader").classList.remove("hidden");
  $("scrape-btn").disabled = true;

  try {
    const res = await fetch("/api/scrape", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ url }),
    });

    if (!res.ok) {
      const err = await res.json().catch(() => ({ detail: "Erreur réseau" }));
      throw new Error(err.detail || "Impossible d'analyser ce lien");
    }

    const data = await res.json();
    state.url = url;
    state.imageUrls = data.image_urls || [];
    state.brand = data.brand || "";
    state.removedUrls = new Set();

    // Pre-fill form
    $("phrase").value = data.title || "";
    $("current-price").value = data.current_price || "";
    $("original-price").value = data.original_price || "";

    renderImagesGrid();
    showStep("edit");

  } catch (err) {
    const errEl = $("scrape-error");
    errEl.textContent = err.message;
    errEl.classList.remove("hidden");
  } finally {
    $("scrape-loader").classList.add("hidden");
    $("scrape-btn").disabled = false;
  }
}

/* ── Images grid ── */
function renderImagesGrid() {
  const grid = $("images-grid");
  grid.innerHTML = "";

  if (!state.imageUrls.length) {
    $("images-card").style.display = "none";
    return;
  }
  $("images-card").style.display = "";

  state.imageUrls.forEach(url => {
    const div = document.createElement("div");
    div.className = "img-thumb" + (state.removedUrls.has(url) ? " removed" : "");
    const img = document.createElement("img");
    img.src = url;
    img.loading = "lazy";
    div.appendChild(img);
    div.addEventListener("click", () => {
      if (state.removedUrls.has(url)) {
        state.removedUrls.delete(url);
        div.classList.remove("removed");
      } else {
        state.removedUrls.add(url);
        div.classList.add("removed");
      }
    });
    grid.appendChild(div);
  });
}

/* ── STEP 2: Process ── */
$("process-btn").addEventListener("click", doProcess);
$("back-btn").addEventListener("click", () => showStep("url"));

async function doProcess() {
  const phrase = $("phrase").value.trim();
  const currentPrice = $("current-price").value.trim();
  const originalPrice = $("original-price").value.trim();

  if (!phrase || !currentPrice || !originalPrice) {
    toast("Remplis tous les champs !");
    return;
  }

  const activeImages = state.imageUrls.filter(u => !state.removedUrls.has(u));

  $("process-btn").disabled = true;
  $("process-btn").textContent = "Génération…";

  try {
    const res = await fetch("/api/process", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        url: state.url,
        phrase,
        current_price: currentPrice,
        original_price: originalPrice,
        image_urls: activeImages,
      }),
    });

    if (!res.ok) throw new Error("Erreur serveur");

    const data = await res.json();
    state.jobId = data.job_id;
    state.twitterUrl = data.twitter_url;
    state.tweetText = data.tweet_text;

    // Show twitter card immediately (no need to wait for images)
    showStep("results");
    showTwitterCard(data.tweet_text, data.twitter_url);

    // Poll for carousel + c8ke status
    pollJob(data.job_id);

  } catch (err) {
    toast("Erreur : " + err.message);
  } finally {
    $("process-btn").disabled = false;
    $("process-btn").textContent = "Générer le deal →";
  }
}

/* ── Twitter card ── */
function showTwitterCard(tweetText, twitterUrl) {
  $("tweet-preview").textContent = tweetText;

  $("open-twitter-btn").onclick = () => window.open(twitterUrl, "_blank");

  $("copy-text-btn").onclick = async () => {
    await navigator.clipboard.writeText(tweetText).catch(() => {});
    toast("Texte copié !");
  };

  // Confirmation → reveal TikTok
  $("tweet-done-btn").onclick = () => {
    $("tweet-done-btn").disabled = true;
    $("tweet-done-btn").textContent = "✓ Tweet posté";
    revealTikTok();
  };

  $("card-twitter").classList.remove("hidden");
}

/* ── Show Twitter photos for saving ── */
function showTwitterPhotos(images) {
  // images[0] = tweet card (skip), images[1] & [2] = product photos for Twitter
  const productPhotos = images.slice(1, 3);
  if (!productPhotos.length) return;

  const row = $("twitter-photos");
  row.innerHTML = "";
  productPhotos.forEach(path => {
    const a = document.createElement("a");
    a.href = path;
    a.target = "_blank";
    a.className = "photo-thumb";
    const img = document.createElement("img");
    img.src = path;
    a.appendChild(img);
    row.appendChild(a);
  });

  $("twitter-photos-section").classList.remove("hidden");

  // Hide the save button — on iOS, user taps photo → long press → Save to Photos
  $("save-twitter-photos-btn").style.display = "none";
}

function revealTikTok() {
  if (state.carouselReady) {
    $("card-tiktok").classList.remove("hidden");
    $("card-tiktok").scrollIntoView({ behavior: "smooth" });
  } else {
    // Still loading — show a spinner inside tiktok card then reveal when ready
    $("card-tiktok").classList.remove("hidden");
    $("card-tiktok").scrollIntoView({ behavior: "smooth" });
    state.revealTikTokPending = true;
  }
}

/* ── Poll job ── */
async function pollJob(jobId) {
  const maxAttempts = 60;
  let attempts = 0;

  while (attempts < maxAttempts) {
    await sleep(2000);
    attempts++;

    try {
      const res = await fetch(`/api/job/${jobId}`);
      const data = await res.json();

      if (data.status === "done") {
        onJobDone(data);
        return;
      }
      if (data.status === "error") {
        onJobError(data.error);
        return;
      }
    } catch {
      // network hiccup, keep polling
    }
  }
  onJobError("Timeout — le job a pris trop de temps");
}

function onJobDone(data) {
  $("result-loader").style.display = "none";

  // TikTok carousel
  if (data.images && data.images.length) {
    state.carouselImages = data.images;
    renderCarousel(data.images);
    showTwitterPhotos(data.images);
    state.carouselReady = true;
    if (state.revealTikTokPending) {
      $("card-tiktok").classList.remove("hidden");
      state.revealTikTokPending = false;
    }
  }

  // c8ke
  const badge = $("c8ke-badge");
  const statusText = $("c8ke-status-text");
  if (data.c8ke_ok) {
    statusText.textContent = "Lien ajouté sur ton c8ke";
    badge.textContent = "✓";
    badge.className = "badge ok";
  } else {
    statusText.textContent = "Ajout c8ke non disponible — fais-le manuellement";
    badge.textContent = "!";
    badge.className = "badge fail";
  }
  $("card-c8ke").classList.remove("hidden");
  $("new-deal-btn").classList.remove("hidden");
}

function onJobError(msg) {
  $("result-loader").style.display = "none";
  toast("Erreur : " + msg);
  $("new-deal-btn").classList.remove("hidden");
}

/* ── Carousel ── */
function renderCarousel(images) {
  const container = $("carousel-slides");
  container.innerHTML = "";

  images.forEach((path, i) => {
    const a = document.createElement("a");
    a.href = path;
    a.target = "_blank";
    a.className = "slide-thumb";
    const img = document.createElement("img");
    img.src = path;
    const num = document.createElement("div");
    num.className = "slide-num";
    num.textContent = `${i + 1}/${images.length}`;
    a.appendChild(img);
    a.appendChild(num);
    container.appendChild(a);
  });
}

/* ── Share / Download ── */
$("share-tiktok-btn").addEventListener("click", async () => {
  const paths = state.carouselImages;
  if (!paths.length) return;

  try {
    $("share-tiktok-btn").textContent = "Préparation…";
    $("share-tiktok-btn").disabled = true;
    const files = await Promise.all(
      paths.map(async (path, i) => {
        const resp = await fetch(path);
        const blob = await resp.blob();
        return new File([blob], `linkdeal_${i + 1}.jpg`, { type: "image/jpeg" });
      })
    );
    if (navigator.canShare && navigator.canShare({ files })) {
      await navigator.share({ files, title: "LinkDeal carousel" });
    }
  } catch (err) {
    if (err.name !== "AbortError") toast("Erreur : " + err.message);
  } finally {
    $("share-tiktok-btn").textContent = "① Sauvegarder les 4 slides →";
    $("share-tiktok-btn").disabled = false;
  }
});

$("open-tiktok-btn").addEventListener("click", () => {
  const tag = "#" + (state.brand || "").toLowerCase().replace(/\s+/g, "").replace(/[^a-z0-9]/g, "");
  if (tag.length > 1 && navigator.clipboard) {
    navigator.clipboard.writeText(tag).catch(() => {});
    toast(`${tag} copié !`);
  }
  setTimeout(() => { window.open("https://www.tiktok.com", "_blank"); }, 300);
});

function downloadImage(path, index) {
  const a = document.createElement("a");
  a.href = path;
  a.download = `linkdeal_slide_${index}.jpg`;
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
}

/* ── New deal ── */
$("new-deal-btn").addEventListener("click", () => {
  state = {
    url: "", phrase: "", currentPrice: "", originalPrice: "",
    brand: "",
    imageUrls: [], removedUrls: new Set(),
    jobId: null, twitterUrl: null, carouselImages: [],
  };
  $("product-url").value = "";
  $("images-grid").innerHTML = "";
  [$("card-twitter"), $("card-tiktok"), $("card-c8ke"), $("new-deal-btn")].forEach(el => el.classList.add("hidden"));
  $("result-loader").style.display = "";
  $("carousel-slides").innerHTML = "";
  showStep("url");
});

/* ── Util ── */
function sleep(ms) { return new Promise(r => setTimeout(r, ms)); }
