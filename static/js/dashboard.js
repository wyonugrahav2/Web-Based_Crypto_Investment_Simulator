/* ============================================================
   MAJALAYA CRYPTO - static/js/dashboard.js
   [DISTRIBUSI KODE] Pusat logika client-side dashboard.
   Dipindahkan seutuhnya dari <script> lama di templates/dashboard.html,
   tanpa mengubah logika bisnis maupun perilaku UI apapun.

   File ini murni JS statis -- tidak ada sintaks Jinja di sini. Nilai-nilai
   yang tadinya di-render langsung oleh Jinja (mis. url_for(...)) sekarang
   dibaca dari window.APP_CONFIG yang di-set lewat blok <script> kecil di
   templates/dashboard.html (lihat {% block scripts %}).
   ============================================================ */

(function () {
    "use strict";

    const CONFIG = window.APP_CONFIG || { role: "user", urls: {} };

    // =====================================================
    // 0. LOADING SCREEN (SESI 3)
    // =====================================================
    const overlay = document.getElementById("loadingOverlay");
    const MIN_SHOW_MS = 400;
    const overlayShownAt = Date.now();

    function showLoadingOverlay() {
        overlay.classList.remove("hidden");
    }
    function hideLoadingOverlay() {
        const elapsed = Date.now() - overlayShownAt;
        const wait = Math.max(MIN_SHOW_MS - elapsed, 0);
        setTimeout(() => overlay.classList.add("hidden"), wait);
    }

    // Sembunyikan loading screen begitu halaman selesai dimuat penuh
    window.addEventListener("load", hideLoadingOverlay);

    // Tampilkan lagi loading screen setiap kali pindah halaman lewat
    // link navigasi biasa (bukan '#' dan bukan tombol refresh harga
    // yang sudah ditangani via AJAX)
    document.querySelectorAll("a[href]").forEach((a) => {
        const href = a.getAttribute("href");
        // [HOTFIX] Tombol "Ekspor Data Pesan (CSV)" (class js-ekspor-csv)
        // sengaja dikecualikan di sini, persis seperti js-refresh-harga.
        // Sebelumnya tombol ini adalah <a href> biasa yang men-download file
        // (Content-Disposition: attachment) -- browser TIDAK pernah
        // menavigasi ke halaman baru untuk request semacam ini, sehingga
        // event "load" yang jadi pemicu hideLoadingOverlay() tidak pernah
        // terjadi lagi dan overlay loading full-screen "nyangkut" berputar
        // selamanya. Sekarang tombol ini punya handler fetch()+blob sendiri
        // (lihat bagian 5b) yang menjamin status loadingnya berhenti lewat
        // blok try/finally, jadi tidak boleh ikut dipicu overlay generik ini.
        if (!href || href === "#" || a.classList.contains("js-refresh-harga") || a.classList.contains("js-ekspor-csv")) return;
        a.addEventListener("click", () => showLoadingOverlay());
    });

    // Tampilkan loading screen setiap kali form (mis. form trading, reset akun) disubmit
    document.querySelectorAll("form").forEach((f) => {
        // [SESI 4] Form komentar/balasan Social Trading Feed dikirim murni
        // lewat AJAX/fetch (lihat bagian 16 di bawah) -- TIDAK reload halaman,
        // jadi sengaja dikecualikan dari loading overlay penuh supaya overlay
        // tidak "nyangkut" tampil selamanya karena tidak pernah ada navigasi
        // halaman baru yang menyembunyikannya kembali.
        // [HOTFIX] Form "Kirim Pesan" di tab Contact (id="contactMessageForm")
        // juga murni AJAX/fetch (lihat pasangMenuContactDanForm() di bawah),
        // jadi ikut dikecualikan dengan alasan yang sama persis -- sebelumnya
        // form ini TIDAK dikecualikan, sehingga overlay loading full-screen
        // sempat tampil duluan (listener ini terdaftar lebih dulu daripada
        // listener submit milik form contact) dan tidak pernah disembunyikan
        // lagi karena tidak ada navigasi halaman baru yang memicu
        // hideLoadingOverlay() -- inilah penyebab "infinite loading" yang
        // dilaporkan pada tombol "Kirim Pesan".
        if (f.classList.contains("js-feed-comment-form") || f.id === "contactMessageForm") return;
        f.addEventListener("submit", (e) => {
            // Kalau form reset akun dibatalkan lewat confirm(), jangan tampilkan overlay
            if (e.defaultPrevented) return;
            showLoadingOverlay();
        });
    });

    // =====================================================
    // 1. Sidebar toggle (collapse/expand)
    // =====================================================
    const shell = document.getElementById("appShell");
    const toggleBtn = document.getElementById("sidebarToggleBtn");
    toggleBtn.addEventListener("click", () => {
        shell.classList.toggle("sidebar-collapsed");
    });

    // =====================================================
    // 2. Dropdown profil (konsisten untuk semua role)
    // =====================================================
    const profileTrigger = document.getElementById("profileTrigger");
    const profileDropdown = document.getElementById("profileDropdown");
    profileTrigger.addEventListener("click", (e) => {
        e.stopPropagation();
        profileDropdown.classList.toggle("open");
    });
    document.addEventListener("click", () => profileDropdown.classList.remove("open"));

    // =====================================================
    // 3. Live search bar untuk filter tabel koin
    // =====================================================
    const searchInput = document.getElementById("coinSearchInput");
    searchInput.addEventListener("input", () => {
        const keyword = searchInput.value.trim().toLowerCase();
        document.querySelectorAll(".coin-row").forEach((row) => {
            const coinName = row.getAttribute("data-coin");
            row.classList.toggle("search-hidden", keyword !== "" && !coinName.includes(keyword));
        });
    });

    // =====================================================
    // 4. Toast flash message dinamis (dipakai hasil AJAX refresh harga)
    // =====================================================
    // [HOTFIX] Durasi auto-dismiss & durasi transisi fade-out, dipakai
    // konsisten baik untuk toast yang dibuat lewat JS (showToast) maupun
    // flash message yang sudah dirender langsung oleh Jinja saat halaman
    // pertama kali dimuat (lihat inisialisasi di bawah).
    const FLASH_AUTO_DISMISS_MS = 4500;
    const FLASH_FADE_MS = 400;

    // Menghapus satu elemen flash/toast dengan fade-out halus dulu,
    // baru benar-benar dibuang dari DOM setelah transisinya selesai.
    // Dipakai baik oleh timer auto-dismiss maupun tombol close manual,
    // dan aman dipanggil dua kali (mis. user klik close pas timer auto
    // -dismiss juga baru saja jalan) karena elemen yang sudah tidak ada
    // di DOM lagi cukup diabaikan.
    function fadeOutDanHapusFlash(el) {
        if (!el || !el.isConnected) return;
        el.classList.add("flash-dismiss");
        setTimeout(() => el.remove(), FLASH_FADE_MS);
    }

    // Melengkapi satu elemen .flash dengan tombol close (x) + timer
    // auto-dismiss, dipakai baik untuk flash yang sudah ada di HTML awal
    // (dirender Jinja lewat get_flashed_messages) maupun flash baru yang
    // dibuat lewat showToast().
    function lengkapiFlashDenganCloseDanAutoDismiss(el) {
        if (!el || el.querySelector(".flash-close-btn")) return; // jangan dobel

        const closeBtn = document.createElement("button");
        closeBtn.type = "button";
        closeBtn.className = "flash-close-btn";
        closeBtn.setAttribute("aria-label", "Tutup notifikasi");
        closeBtn.innerHTML = "&times;";
        closeBtn.addEventListener("click", () => fadeOutDanHapusFlash(el));
        el.appendChild(closeBtn);

        const timer = setTimeout(() => fadeOutDanHapusFlash(el), FLASH_AUTO_DISMISS_MS);
        // Kalau user menutup manual duluan, timer auto-dismiss yang masih
        // tersisa dibatalkan supaya tidak coba menghapus elemen yang sudah
        // tidak ada lagi (meskipun fadeOutDanHapusFlash sudah aman dipanggil
        // berkali-kali, membatalkan timer tetap praktik yang lebih bersih).
        closeBtn.addEventListener("click", () => clearTimeout(timer), { once: true });
    }

    function showToast(message, category) {
        const stack = document.getElementById("flashStack");
        const div = document.createElement("div");
        div.className = "flash flash-" + category;
        div.textContent = message;
        stack.appendChild(div);
        lengkapiFlashDenganCloseDanAutoDismiss(div);
    }

    // [HOTFIX] Flash message yang sudah dirender langsung oleh Jinja saat
    // halaman pertama kali dimuat (mis. pesan "Kamu berhasil logout.")
    // sebelumnya TIDAK punya tombol close ataupun auto-dismiss sama sekali
    // -- akan nempel di layar selamanya sampai halaman di-refresh manual.
    // Baris ini menyamakan perilakunya persis dengan toast yang dibuat
    // lewat JS di atas.
    document.querySelectorAll("#flashStack .flash").forEach((el) => {
        lengkapiFlashDenganCloseDanAutoDismiss(el);
    });

    // =====================================================
    // 5. Tombol "Refresh Harga" -> AJAX ke /api/refresh-harga
    //    (tanpa reload penuh, harga di tabel & ticker ter-update live)
    // =====================================================
    document.querySelectorAll(".js-refresh-harga").forEach((btn) => {
        btn.addEventListener("click", async function (e) {
            e.preventDefault();
            showLoadingOverlay();
            try {
                const resp = await fetch(CONFIG.urls.apiRefreshHarga, {
                    method: "POST",
                    headers: { "X-Requested-With": "XMLHttpRequest" }
                });
                const result = await resp.json();

                if (result.ok) {
                    result.data.forEach((koin) => {
                        const kodeKoin = koin.nama_koin.toLowerCase();
                        const hargaRp2 = "Rp" + koin.harga_fiktif.toLocaleString("id-ID", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
                        const hargaRp0 = "Rp" + koin.harga_fiktif.toLocaleString("id-ID", { maximumFractionDigits: 0 });

                        document.querySelectorAll('.price-cell[data-coin="' + kodeKoin + '"]').forEach((cell) => {
                            cell.textContent = hargaRp2;
                            cell.setAttribute("data-harga", koin.harga_fiktif); // [FIX] jaga harga live tetap akurat untuk Quick Exchange
                            cell.classList.remove("flash-update");
                            void cell.offsetWidth; // restart animasi
                            cell.classList.add("flash-update");
                        });
                        document.querySelectorAll('.ticker-price[data-coin="' + kodeKoin + '"]').forEach((cell) => {
                            cell.textContent = hargaRp0;
                            cell.setAttribute("data-harga", koin.harga_fiktif);
                        });
                        // Sinkronkan juga data-harga di <option> Quick Exchange sebagai fallback
                        document.querySelectorAll('.qe-select option[value="' + koin.nama_koin + '"]').forEach((opt) => {
                            opt.setAttribute("data-harga", koin.harga_fiktif);
                        });
                    });
                    showToast(result.message, "success");
                    hitungQuickExchange(); // [FIX] re-kalkulasi Quick Exchange dengan harga baru

                    // [DISTRIBUSI KODE] chart_history (BTC/ETH/SOL/DOGE) diutamakan
                    // jika tersedia, fallback ke chart_btc lama untuk kompatibilitas.
                    // Chart mengikuti koin yang SEDANG aktif dipilih user lewat
                    // button group (bukan selalu BTC), supaya "Refresh Harga" tidak
                    // menimpa tampilan grafik koin lain yang sedang dilihat user.
                    const dataChartAktif = (result.chart_history && result.chart_history[koinChartAktif])
                        ? result.chart_history[koinChartAktif]
                        : (koinChartAktif === "BTC" ? result.chart_btc : null);
                    if (dataChartAktif) perbaruiChartBtc(dataChartAktif);
                } else {
                    showToast(result.message || "Gagal memperbarui harga.", "danger");
                    if (resp.status === 401) {
                        window.location.href = CONFIG.urls.login;
                    }
                }
            } catch (err) {
                showToast("Gagal terhubung ke server, coba lagi.", "danger");
            } finally {
                hideLoadingOverlay();
            }
        });
    });

    // =====================================================
    // 5b. [HOTFIX] Tombol "Ekspor Data Pesan (CSV)" -> fetch() + blob,
    //     BUKAN navigasi <a href> biasa. Sebelumnya tombol ini berhasil
    //     memicu download file, tapi karena browser tidak pernah benar
    //     -benar berpindah halaman untuk sebuah download, overlay loading
    //     full-screen yang sempat ditampilkan (lihat pengecualian di
    //     bagian 0 di atas) tidak pernah disembunyikan lagi -> "infinite
    //     loading" persis seperti yang dilaporkan. Sekarang tombol ini:
    //       1) menampilkan status loading LOKAL di tombolnya sendiri saja
    //          (bukan overlay penuh layar),
    //       2) mengambil file CSV via fetch() sebagai blob,
    //       3) memicu proses "Save As" lewat elemen <a download> sementara,
    //       4) di blok finally, SELALU mengembalikan tombol ke teks/ikon
    //          semula -- baik saat sukses, gagal, maupun error jaringan --
    //          sehingga tombol tidak pernah nyangkut berputar lagi dan
    //          langsung bisa dipakai ulang tanpa perlu refresh halaman.
    // =====================================================
    const eksporCsvBtn = document.getElementById("contactEksporCsvBtn");
    if (eksporCsvBtn) {
        const eksporCsvLabel = eksporCsvBtn.querySelector(".js-ekspor-csv-label");
        const eksporCsvHtmlAsli = eksporCsvLabel ? eksporCsvLabel.innerHTML : eksporCsvBtn.innerHTML;

        eksporCsvBtn.addEventListener("click", async (e) => {
            e.preventDefault();
            if (eksporCsvBtn.classList.contains("is-loading")) return; // cegah klik dobel saat masih proses

            eksporCsvBtn.classList.add("is-loading");
            eksporCsvBtn.style.pointerEvents = "none";
            const targetLabel = eksporCsvLabel || eksporCsvBtn;
            targetLabel.innerHTML = '<i class="fa-solid fa-spinner fa-spin"></i> Mengekspor...';

            try {
                const resp = await fetch(eksporCsvBtn.href, {
                    headers: { "X-Requested-With": "XMLHttpRequest" }
                });

                if (!resp.ok) {
                    let pesan = "Gagal mengekspor data pesan.";
                    try {
                        const errJson = await resp.clone().json();
                        if (errJson && errJson.message) pesan = errJson.message;
                    } catch (parseErr) {
                        // Respons bukan JSON (mis. error server generik) -> pakai pesan default di atas.
                    }
                    showToast(pesan, "danger");
                    if (resp.status === 403 || resp.status === 401) {
                        window.location.href = CONFIG.urls.login;
                    }
                    return;
                }

                const blob = await resp.blob();
                const urlBlob = window.URL.createObjectURL(blob);

                // Nama file diambil dari header Content-Disposition kalau ada,
                // fallback ke nama default kalau tidak (mis. browser lama).
                let namaFile = "laporan_pesan_majalaya.csv";
                const disposisi = resp.headers.get("Content-Disposition") || "";
                const cocokNamaFile = disposisi.match(/filename="?([^";]+)"?/i);
                if (cocokNamaFile && cocokNamaFile[1]) namaFile = cocokNamaFile[1].trim();

                const linkUnduh = document.createElement("a");
                linkUnduh.href = urlBlob;
                linkUnduh.download = namaFile;
                document.body.appendChild(linkUnduh);
                linkUnduh.click();
                linkUnduh.remove();
                window.URL.revokeObjectURL(urlBlob);

                showToast("Data pesan berhasil diekspor ke CSV.", "success");
            } catch (err) {
                showToast("Gagal terhubung ke server, coba lagi.", "danger");
            } finally {
                // [FIX KRUSIAL] Blok ini WAJIB selalu jalan apapun hasilnya
                // (sukses, gagal, maupun error jaringan) supaya tombol tidak
                // pernah tersangkut dalam status loading selamanya.
                eksporCsvBtn.classList.remove("is-loading");
                eksporCsvBtn.style.pointerEvents = "";
                targetLabel.innerHTML = eksporCsvHtmlAsli;
            }
        });
    }

    // =====================================================
    // 6. [SESI 3] Tab menu utama (Dashboard / Portofolio / Pengaturan /
    //    Admin Area) -- switching tanpa reload halaman penuh.
    // =====================================================
    const navTabButtons = document.querySelectorAll(".nav-item[data-tab]");
    const tabPanels = document.querySelectorAll(".tab-panel");
    navTabButtons.forEach((navBtn) => {
        navBtn.addEventListener("click", (e) => {
            e.preventDefault();
            const targetTab = navBtn.getAttribute("data-tab");

            navTabButtons.forEach((b) => b.classList.remove("active"));
            navBtn.classList.add("active");

            tabPanels.forEach((panel) => {
                panel.classList.toggle("active", panel.id === "tab-" + targetTab);
            });
        });
    });

    // =====================================================
    // 7. [SESI 3] Refresh Ringkasan Master Control (AJAX, admin only)
    // =====================================================
    const refreshRingkasanBtn = document.getElementById("refreshRingkasanBtn");
    if (refreshRingkasanBtn) {
        refreshRingkasanBtn.addEventListener("click", async () => {
            showLoadingOverlay();
            try {
                const resp = await fetch(CONFIG.urls.apiAdminRingkasan);
                const result = await resp.json();
                if (result.ok) {
                    document.querySelectorAll("#statTotalUser, #statTotalUser2").forEach((el) => el.textContent = result.total_user);
                    document.querySelectorAll("#statTotalKoin, #statTotalKoin2").forEach((el) => el.textContent = result.total_koin);
                    showToast(result.message, "success");
                } else {
                    showToast(result.message || "Gagal memperbarui ringkasan.", "danger");
                }
            } catch (err) {
                showToast("Gagal terhubung ke server, coba lagi.", "danger");
            } finally {
                hideLoadingOverlay();
            }
        });
    }

    // =====================================================
    // 8. [SESI 3] Toggle form Trading: Beli (nominal Rupiah) vs
    //    Jual (jumlah koin fraksi)
    // =====================================================
    const tradeTabBtns = document.querySelectorAll(".trade-tab-btn");
    const aksiInput = document.getElementById("aksiInput");
    const beliField = document.getElementById("beliField");
    const jualField = document.getElementById("jualField");
    const nominalBeliInput = document.getElementById("nominalBeliInput");
    const jumlahKoinInput = document.getElementById("jumlahKoinInput");
    const tradeSubmitBtn = document.getElementById("tradeSubmitBtn");
    const tradeCoinSelect = document.getElementById("tradeCoinSelect");
    const ownedHint = document.getElementById("ownedHint");

    // =====================================================
    // 8b. [PART 1] Slider alokasi cepat (25/50/75/100%) untuk form
    //     Beli & Jual, plus hint saldo dinamis di dekat form transaksi.
    //     Slider TIDAK mengunci input manual -- keduanya tetap bisa diketik
    //     bebas, slider murni shortcut yang menulis ulang nilai input.
    //
    //     [FIX KRUSIAL] Deklarasi const di bawah ini SENGAJA dipindahkan ke
    //     ATAS, sebelum updateOwnedHint() didefinisikan/dipanggil. Sebelumnya
    //     "jualSaldoHint" dideklarasikan (const) SETELAH updateOwnedHint()
    //     sempat memanggil updateJualSaldoHint() yang membaca variabel itu,
    //     sehingga meledak "ReferenceError: Cannot access 'jualSaldoHint'
    //     before initialization" (Temporal Dead Zone) SETIAP kali form
    //     trading (Beli/Jual) ada di halaman -- yaitu HANYA untuk role USER,
    //     karena akun ADMIN sama sekali tidak merender form trading
    //     (tradeCoinSelect selalu null buat admin, jadi bug ini "tersembunyi"
    //     dan seolah tidak pernah terjadi). Error tak tertangani ini
    //     menghentikan SISA seluruh <script> secara sinkron, jadi ikut
    //     membekukan slider Beli/Jual/Quick Exchange DAN mencegah tab Contact
    //     ter-pasang ke sidebar -- persis 2 gejala yang dilaporkan.
    // =====================================================
    const nominalBeliSlider = document.getElementById("nominalBeliSlider");
    const beliSaldoHint = document.getElementById("beliSaldoHint");
    const jumlahKoinSlider = document.getElementById("jumlahKoinSlider");
    const jualSaldoHint = document.getElementById("jualSaldoHint");
    const SALDO_IDR_USER = Number(CONFIG.saldoIdr) || 0;

    function formatRupiahSaldoHint(nilai) {
        return "Rp" + Math.round(nilai).toLocaleString("id-ID");
    }

    // ---- Slider Jual: porsi dari sisa fraksi koin yang sedang dipilih ----
    function getOwnedFraksiKoinTerpilih() {
        if (!tradeCoinSelect) return 0;
        const opt = tradeCoinSelect.options[tradeCoinSelect.selectedIndex];
        return opt ? parseFloat(opt.getAttribute("data-owned")) || 0 : 0;
    }

    function updateJualSaldoHint() {
        if (!jualSaldoHint) return;
        jualSaldoHint.textContent = "Sisa saldo koin: " + getOwnedFraksiKoinTerpilih().toFixed(8);
    }

    function updateOwnedHint() {
        if (!tradeCoinSelect || !ownedHint) return;
        const opt = tradeCoinSelect.options[tradeCoinSelect.selectedIndex];
        const owned = opt ? opt.getAttribute("data-owned") : "0.00000000";
        ownedHint.textContent = "(dimiliki saat ini: " + owned + ")";
        updateJualSaldoHint(); // [PART 1] sinkronkan hint sisa saldo koin dinamis tiap kali koin dipilih ulang
    }

    if (tradeCoinSelect) {
        tradeCoinSelect.addEventListener("change", updateOwnedHint);
        updateOwnedHint();
    }

    // ---- Slider Beli: porsi dari sisa Saldo Rupiah user ----
    if (beliSaldoHint) {
        beliSaldoHint.textContent = "Sisa saldo Rupiah: " + formatRupiahSaldoHint(SALDO_IDR_USER);
    }
    if (nominalBeliSlider && nominalBeliInput) {
        nominalBeliSlider.addEventListener("input", () => {
            // Math.max/min menjaga persentase selalu di rentang 0-100 yang
            // aman, walau browser lama/aneh mengirim value di luar batas.
            const persenMentah = parseInt(nominalBeliSlider.value, 10) || 0;
            const persen = Math.min(100, Math.max(0, persenMentah));
            const nominal = Math.floor((SALDO_IDR_USER * persen) / 100);
            // Slider murni SHORTCUT pengisian -- kotak input manual TIDAK
            // dikunci/disabled, user tetap bebas mengetik ulang kapan saja.
            nominalBeliInput.value = nominal > 0 ? nominal : "";
        });
    }
    updateJualSaldoHint();

    if (jumlahKoinSlider && jumlahKoinInput) {
        jumlahKoinSlider.addEventListener("input", () => {
            const persenMentah = parseInt(jumlahKoinSlider.value, 10) || 0;
            const persen = Math.min(100, Math.max(0, persenMentah));
            const dimiliki = getOwnedFraksiKoinTerpilih();
            const jumlah = (dimiliki * persen) / 100;
            // Shortcut saja -- kotak input manual tetap bisa diketik bebas.
            jumlahKoinInput.value = jumlah > 0 ? jumlah.toFixed(8) : "";
        });
    }

    // Reset posisi kedua slider ke 0% setiap kali user berpindah tab Beli/Jual
    // atau berganti koin, supaya slider tidak "menyesatkan" (menunjukkan
    // persentase lama padahal basis saldo/koin sudah berubah).
    tradeTabBtns.forEach((btn) => {
        btn.addEventListener("click", () => {
            if (nominalBeliSlider) nominalBeliSlider.value = 0;
            if (jumlahKoinSlider) jumlahKoinSlider.value = 0;
        });
    });
    if (tradeCoinSelect) {
        tradeCoinSelect.addEventListener("change", () => {
            if (jumlahKoinSlider) jumlahKoinSlider.value = 0;
        });
    }

    tradeTabBtns.forEach((btn) => {
        btn.addEventListener("click", () => {
            tradeTabBtns.forEach((b) => b.classList.remove("active"));
            btn.classList.add("active");
            const aksi = btn.getAttribute("data-aksi");
            aksiInput.value = aksi;

            if (aksi === "beli") {
                beliField.style.display = "";
                jualField.style.display = "none";
                nominalBeliInput.required = true;
                jumlahKoinInput.required = false;
                tradeSubmitBtn.innerHTML = '<i class="fa-solid fa-cart-plus"></i> Proses Beli';
                tradeSubmitBtn.classList.remove("danger-outline");
                tradeSubmitBtn.classList.add("primary");
            } else {
                beliField.style.display = "none";
                jualField.style.display = "";
                nominalBeliInput.required = false;
                jumlahKoinInput.required = true;
                tradeSubmitBtn.innerHTML = '<i class="fa-solid fa-money-bill-transfer"></i> Proses Jual';
                tradeSubmitBtn.classList.remove("primary");
                tradeSubmitBtn.classList.add("danger-outline");
                updateOwnedHint();
            }
        });
    });

    // =====================================================
    // 9. [SESI 3] Quick Exchange -- kalkulasi instan di sisi JS
    //    berdasarkan harga live yang sudah tertanam di opsi <select>.
    // =====================================================
    const qeDariKoin = document.getElementById("qeDariKoin");
    const qeKeKoin = document.getElementById("qeKeKoin");
    const qeJumlahDari = document.getElementById("qeJumlahDari");
    const qeJumlahKe = document.getElementById("qeJumlahKe");
    const qeOwnedHint = document.getElementById("qeOwnedHint");
    const qeEstimasiNilai = document.getElementById("qeEstimasiNilai");

    function formatRupiahQE(nilai) {
        return "Rp" + nilai.toLocaleString("id-ID", { maximumFractionDigits: 0 });
    }

    // ---- [FIX BUG] Baca porsi fraksi desimal koin milik user LANGSUNG dari
    // baris DOM tabel Portofolio (tab "Portofolio"), bukan dari atribut
    // data-owned statis di <option> yang sebelumnya bisa basi / tidak sinkron
    // dan menyebabkan hint selalu menampilkan "dimiliki: 0.00000000". ----
    function bacaJumlahDimilikiDariTabelPortofolio(kodeKoin) {
        const baris = document.querySelector('.portfolio-row[data-coin="' + kodeKoin + '"]');
        if (baris) {
            const jumlah = baris.getAttribute("data-jumlah");
            if (jumlah !== null) return jumlah;
        }
        return "0.00000000";
    }

    // ---- Harga live juga dibaca dari DOM (price-cell) yang sudah otomatis
    // ter-update setiap kali tombol "Refresh Harga" ditekan, supaya kalkulasi
    // Quick Exchange selalu memakai harga instan terkini, bukan harga beku
    // hasil render awal halaman. Fallback ke data-harga bawaan <option> kalau
    // sel harga live belum ditemukan di DOM. ----
    function bacaHargaLiveKoin(kodeKoin, optionFallback) {
        const cellHarga = document.querySelector('.price-cell[data-coin="' + kodeKoin + '"]');
        if (cellHarga && cellHarga.hasAttribute("data-harga")) {
            const harga = parseFloat(cellHarga.getAttribute("data-harga"));
            if (!isNaN(harga)) return harga;
        }
        return parseFloat(optionFallback.getAttribute("data-harga")) || 0;
    }

    function hitungQuickExchange() {
        if (!qeDariKoin || !qeKeKoin) return;

        const optDari = qeDariKoin.options[qeDariKoin.selectedIndex];
        const optKe = qeKeKoin.options[qeKeKoin.selectedIndex];
        if (!optDari || !optKe) return;

        const kodeKoinDari = optDari.value.toLowerCase();
        const kodeKoinKe = optKe.value.toLowerCase();

        const hargaDari = bacaHargaLiveKoin(kodeKoinDari, optDari);
        const hargaKe = bacaHargaLiveKoin(kodeKoinKe, optKe);
        const dimiliki = bacaJumlahDimilikiDariTabelPortofolio(kodeKoinDari);
        const jumlahDari = parseFloat(qeJumlahDari.value) || 0;

        qeOwnedHint.textContent = "dimiliki: " + dimiliki;

        const nilaiRupiah = jumlahDari * hargaDari;
        const jumlahKe = hargaKe > 0 ? nilaiRupiah / hargaKe : 0;

        qeJumlahKe.value = jumlahKe > 0 ? jumlahKe.toFixed(8) : "0.00000000";
        qeEstimasiNilai.textContent = "estimasi nilai: " + formatRupiahQE(nilaiRupiah);
    }

    if (qeDariKoin && qeKeKoin) {
        [qeDariKoin, qeKeKoin, qeJumlahDari].forEach((el) => {
            el.addEventListener("input", hitungQuickExchange);
            el.addEventListener("change", hitungQuickExchange);
        });
        hitungQuickExchange();
    }

    // =====================================================
    // 9b. [PART 1] Slider alokasi cepat (25/50/75/100%) untuk Quick
    //     Exchange -- porsi dari sisa saldo koin asal ("Saya punya"),
    //     dibaca langsung dari tabel Portofolio (sama seperti hint saldo).
    // =====================================================
    const qeJumlahDariSlider = document.getElementById("qeJumlahDariSlider");
    if (qeJumlahDariSlider && qeJumlahDari && qeDariKoin) {
        qeJumlahDariSlider.addEventListener("input", () => {
            const persenMentah = parseInt(qeJumlahDariSlider.value, 10) || 0;
            const persen = Math.min(100, Math.max(0, persenMentah));
            const optDari = qeDariKoin.options[qeDariKoin.selectedIndex];
            const kodeKoinDari = optDari ? optDari.value.toLowerCase() : "";
            const dimiliki = parseFloat(bacaJumlahDimilikiDariTabelPortofolio(kodeKoinDari)) || 0;
            const jumlah = (dimiliki * persen) / 100;
            // Shortcut saja -- kotak input manual tetap bisa diketik bebas.
            qeJumlahDari.value = jumlah > 0 ? jumlah.toFixed(8) : "";
            hitungQuickExchange();
        });
        // Reset slider ke 0% setiap kali koin asal diganti, supaya persentase
        // lama tidak menyesatkan (basis saldo koin asal sudah berbeda).
        qeDariKoin.addEventListener("change", () => { qeJumlahDariSlider.value = 0; });
    }

    // =====================================================
    // 10. [SESI 3] Line Chart tren harga BTC -- inisialisasi awal.
    //     [DISTRIBUSI KODE] Data awal sekarang diambil lewat fetch() ke
    //     /api/market-history (bukan lagi ditanam langsung oleh Jinja),
    //     supaya grafik tetap otomatis terisi jejak harga historis begitu
    //     halaman pertama kali dimuat, tanpa file JS ini bergantung pada
    //     variabel yang di-render server-side.
    // =====================================================
    let btcTrendChart = null;
    const btcChartCanvas = document.getElementById("btcTrendChart");
    const chartTrendTitleEl = document.getElementById("chartTrendTitle");

    // [SESI 4] Metadata tampilan per-koin untuk MULTI-COIN LIVE CHART --
    // warna garis & label judul mengikuti koin aktif.
    // [SESI 2 - FINAL UPGRADE] Ditambah metadata 5 koin baru (BNB, XRP, ADA,
    // NEAR, SHIB) supaya saat tombolnya diklik, chart & judul tren pasar
    // tidak diam-diam fallback ke warna/label BTC.
    const METADATA_KOIN_CHART = {
        BTC:  { label: "BTC (Highest Volume)", warna: "#f0b429", warnaFill: "rgba(240,180,41,0.12)" },
        ETH:  { label: "ETH", warna: "#7c8cf8", warnaFill: "rgba(124,140,248,0.12)" },
        SOL:  { label: "SOL", warna: "#2dd4bf", warnaFill: "rgba(45,212,191,0.12)" },
        DOGE: { label: "DOGE", warna: "#f2545b", warnaFill: "rgba(242,84,91,0.12)" },
        BNB:  { label: "BNB", warna: "#f3ba2f", warnaFill: "rgba(243,186,47,0.12)" },
        XRP:  { label: "XRP", warna: "#5ea0ef", warnaFill: "rgba(94,160,239,0.12)" },
        ADA:  { label: "ADA", warna: "#3468d1", warnaFill: "rgba(52,104,209,0.12)" },
        NEAR: { label: "NEAR", warna: "#8ee3c8", warnaFill: "rgba(142,227,200,0.12)" },
        SHIB: { label: "SHIB", warna: "#ff7a59", warnaFill: "rgba(255,122,89,0.12)" }
    };
    // Koin yang sedang ditampilkan di chart saat ini (default: BTC)
    let koinChartAktif = "BTC";

    function buatChartBtc(dataAwal, kodeKoin) {
        if (!btcChartCanvas || typeof Chart === "undefined") return;
        const meta = METADATA_KOIN_CHART[kodeKoin || "BTC"] || METADATA_KOIN_CHART.BTC;

        // [FIX] Akun baru (mis. user yang baru register) mungkin belum
        // punya riwayat harga sama sekali -> dataAwal bisa jadi array kosong.
        // Beri fallback data tren dasar [0] supaya Chart.js tidak menerima
        // labels/data kosong yang berpotensi menyebabkannya diam-diam gagal
        // merender (silent-crash) dan MEMBEKUKAN sisa script di bawahnya
        // (slider alokasi, tab Contact, dsb).
        const dataAmanUntukChart = (Array.isArray(dataAwal) && dataAwal.length > 0)
            ? dataAwal
            : [{ waktu: "--", harga: 0 }];

        try {
            btcTrendChart = new Chart(btcChartCanvas, {
                type: "line",
                data: {
                    labels: dataAmanUntukChart.map((titik) => titik.waktu),
                    datasets: [{
                        label: "Harga " + meta.label + " (Rp)",
                        data: dataAmanUntukChart.map((titik) => titik.harga),
                        borderColor: meta.warna,
                        backgroundColor: meta.warnaFill,
                        borderWidth: 2,
                        tension: 0.35,
                        fill: true,
                        pointRadius: 3,
                        pointBackgroundColor: meta.warna,
                        pointHoverRadius: 5
                    }]
                },
                options: {
                    responsive: true,
                    maintainAspectRatio: false,
                    animation: { duration: 500 },
                    plugins: {
                        legend: { display: false },
                        tooltip: {
                            callbacks: {
                                label: (ctx) => "Rp" + Number(ctx.parsed.y).toLocaleString("id-ID", { maximumFractionDigits: 0 })
                            }
                        }
                    },
                    scales: {
                        x: {
                            grid: { color: "rgba(255,255,255,0.05)" },
                            ticks: { color: "#838c9e", font: { family: "JetBrains Mono", size: 10 } }
                        },
                        y: {
                            grid: { color: "rgba(255,255,255,0.05)" },
                            ticks: {
                                color: "#838c9e",
                                font: { family: "JetBrains Mono", size: 10 },
                                callback: (val) => "Rp" + Number(val).toLocaleString("id-ID", { notation: "compact", maximumFractionDigits: 1 })
                            }
                        }
                    }
                }
            });
        } catch (e) {
            // [FIX KRUSIAL] Chart utama gagal dibuat (mis. versi Chart.js
            // CDN belum termuat sempurna) -> jangan biarkan error ini
            // merambat ke luar fungsi dan menghentikan SISA <script>
            // (slider alokasi cepat, tab Contact, dsb). Cukup dicatat ke
            // console supaya developer tetap bisa mendiagnosis.
            console.error("Gagal membuat chart tren pasar utama:", e);
        }
    }

    function perbaruiChartBtc(dataChart, kodeKoin) {
        if (!btcTrendChart || !dataChart) return;
        const meta = METADATA_KOIN_CHART[kodeKoin || koinChartAktif] || METADATA_KOIN_CHART.BTC;
        try {
            btcTrendChart.data.labels = dataChart.map((titik) => titik.waktu);
            btcTrendChart.data.datasets[0].data = dataChart.map((titik) => titik.harga);
            if (kodeKoin) {
                // Kalau dipanggil dari pergantian koin (button group), ganti juga
                // warna garis & label dataset supaya konsisten dengan koin baru.
                btcTrendChart.data.datasets[0].label = "Harga " + meta.label + " (Rp)";
                btcTrendChart.data.datasets[0].borderColor = meta.warna;
                btcTrendChart.data.datasets[0].backgroundColor = meta.warnaFill;
                btcTrendChart.data.datasets[0].pointBackgroundColor = meta.warna;
            }
            btcTrendChart.update();
        } catch (e) {
            console.error("Gagal memperbarui chart tren pasar:", e);
        }
    }

    function updateJudulTrenPasar(kodeKoin) {
        if (!chartTrendTitleEl) return;
        const meta = METADATA_KOIN_CHART[kodeKoin] || METADATA_KOIN_CHART.BTC;
        chartTrendTitleEl.textContent = "📈 Tren Pasar — " + meta.label;
    }

    async function initBtcTrendChart() {
        if (!btcChartCanvas) return;
        let dataAwal = [];
        try {
            const resp = await fetch(CONFIG.urls.apiMarketHistory);
            const result = await resp.json();
            if (result.ok && result.data && result.data.BTC) {
                dataAwal = result.data.BTC;
            }
        } catch (err) {
            // Kalau fetch gagal, chart tetap dibuat kosong (bukan error fatal)
            // dan akan otomatis terisi setelah tombol "Refresh Harga" ditekan.
        }
        buatChartBtc(dataAwal, "BTC");
    }

    initBtcTrendChart();
    // Catatan: perbaruiChartBtc() dipakai oleh handler AJAX "Refresh Harga"
    // di item 5 di atas -- karena dideklarasikan dengan `function` (bukan
    // arrow function/const), deklarasinya di-hoist ke seluruh scope IIFE
    // ini, jadi tetap bisa dipanggil meski didefinisikan belakangan di file.

    // =====================================================
    // 11. [SESI 4] Button Group Multi-Coin (BTC/ETH/SOL/DOGE) --
    //     saat salah satu tombol koin diklik: bersihkan data lama di chart,
    //     tembak AJAX ke /api/market-history?coin=NAMA_KOIN, lalu gambar
    //     ulang tren harga koin tsb secara instan + ubah judul dinamis.
    // =====================================================
    const coinChartButtons = document.querySelectorAll(".js-coin-chart-btn");

    async function muatChartUntukKoin(kodeKoin, btnDiklik) {
        if (!btcTrendChart) return;

        // Highlight tombol aktif
        coinChartButtons.forEach((b) => {
            b.classList.remove("primary");
        });
        if (btnDiklik) btnDiklik.classList.add("primary");

        koinChartAktif = kodeKoin;
        updateJudulTrenPasar(kodeKoin);

        // Bersihkan data lama di chart dulu supaya terasa instan / responsif
        // sebelum data baru datang dari server.
        btcTrendChart.data.labels = [];
        btcTrendChart.data.datasets[0].data = [];
        btcTrendChart.update();

        try {
            const resp = await fetch(CONFIG.urls.apiMarketHistory + "?coin=" + encodeURIComponent(kodeKoin));
            const result = await resp.json();

            if (result.ok && result.data && result.data[kodeKoin]) {
                perbaruiChartBtc(result.data[kodeKoin], kodeKoin);
            } else {
                showToast(result.message || "Gagal memuat tren harga " + kodeKoin + ".", "danger");
                if (resp.status === 401) {
                    window.location.href = CONFIG.urls.login;
                }
            }
        } catch (err) {
            showToast("Gagal terhubung ke server, coba lagi.", "danger");
        }
    }

    // =====================================================
    // 11b. [SESI 4] Sinkronkan dropdown koin di form Beli/Jual + smooth
    //      scroll otomatis ke panel form tersebut, setiap kali salah satu
    //      tombol button group koin (BTC/ETH/SOL/DOGE) diklik.
    // =====================================================
    function sinkronkanKoinKeFormTradeDanScroll(kodeKoin) {
        const tradeCoinSelectEl = document.getElementById("tradeCoinSelect");
        if (tradeCoinSelectEl) {
            tradeCoinSelectEl.value = kodeKoin;
            tradeCoinSelectEl.dispatchEvent(new Event("change"));
        }

        // Form Beli/Jual berada di tab "Portofolio" (bukan tab "Dashboard"
        // tempat button group koin ini berada) -- pindahkan tab aktif dulu
        // supaya panelnya tidak tersembunyi (display:none) saat di-scroll.
        const navPortofolio = document.querySelector('.nav-item[data-tab="portofolio"]');
        if (navPortofolio) navPortofolio.click();

        const tradeFormEl = document.getElementById("tradeForm");
        if (tradeFormEl) {
            // Delay singkat supaya panel tab sempat tampil (display:block)
            // dulu sebelum scrollIntoView dihitung, supaya posisi scroll akurat.
            setTimeout(() => {
                tradeFormEl.scrollIntoView({ behavior: "smooth", block: "center" });
            }, 60);
        }
    }

    coinChartButtons.forEach((btn) => {
        btn.addEventListener("click", () => {
            const kodeKoin = btn.getAttribute("data-coin");
            if (kodeKoin !== koinChartAktif) {
                muatChartUntukKoin(kodeKoin, btn);
            }
            sinkronkanKoinKeFormTradeDanScroll(kodeKoin);
        });
    });

    // =====================================================
    // 12. [SESI 4] Tombol ikon surat (✉) di navbar -> dropdown notifikasi
    //     sistem berisi log fiktif (dibangun murni lewat JS, memakai ulang
    //     class .dropdown-menu-custom yang sudah ada supaya tampilannya
    //     konsisten dengan dropdown profil).
    // =====================================================
    const notifBtn = document.querySelector('.icon-btn-wrap .icon-btn[title="Inbox / Notifikasi"]');
    const notifWrap = document.querySelector(".icon-btn-wrap");

    if (notifBtn && notifWrap) {
        const LOG_NOTIFIKASI_FIKTIF = [
            { ikon: "🎉", teks: "Gacha saldo awal berhasil masuk ke akunmu.", waktu: "Baru saja" },
            { ikon: "⟳", teks: "Harga pasar berhasil diperbarui otomatis.", waktu: "5 menit lalu" },
            { ikon: "🔐", teks: "Login berhasil terdeteksi dari perangkat ini.", waktu: "1 jam lalu" },
            { ikon: "💼", teks: "Transaksi terakhirmu sudah tercatat di Recent Activities.", waktu: "Hari ini" }
        ];

        const notifDropdown = document.createElement("div");
        notifDropdown.className = "dropdown-menu-custom";
        notifDropdown.id = "notifDropdown";
        notifDropdown.innerHTML =
            '<div style="padding:11px 16px; font-size:12px; font-weight:600; color:var(--text-faint); border-bottom:1px solid var(--border-soft);">🔔 Notifikasi Sistem</div>' +
            LOG_NOTIFIKASI_FIKTIF.map((n) =>
                '<a href="#" onclick="return false;"><span>' + n.ikon + '</span>' +
                '<span style="flex:1;">' + n.teks + '<br><small style="color:var(--text-faint);">' + n.waktu + '</small></span></a>'
            ).join("");
        notifWrap.appendChild(notifDropdown);

        notifBtn.addEventListener("click", (e) => {
            e.stopPropagation();
            notifDropdown.classList.toggle("open");
            // Begitu dropdown dibuka, hilangkan titik merah penanda notif baru
            const dot = notifWrap.querySelector(".notif-dot");
            if (dot) dot.style.display = "none";
        });
        document.addEventListener("click", () => notifDropdown.classList.remove("open"));
    }

    // =====================================================
    // 13. [SESI 4] Indikator warna dinamis P&L Global (widget Total Saldo)
    //     - Persentase positif (+) -> hijau/teal + panah atas (▲)
    //     - Persentase negatif (-) -> merah + panah bawah (▼)
    //     Nilai persentase dibaca dari atribut data-persen yang sudah
    //     dihitung & dirender server-side lewat hitung_pnl_user() di app.py.
    // =====================================================
    const pnlIndicatorEl = document.getElementById("pnlIndicator");
    if (pnlIndicatorEl) {
        const pnlArrowEl = document.getElementById("pnlArrow");
        const persen = parseFloat(pnlIndicatorEl.getAttribute("data-persen")) || 0;

        if (persen >= 0) {
            pnlIndicatorEl.classList.add("pnl-positive");
            pnlIndicatorEl.classList.remove("pnl-negative");
            if (pnlArrowEl) pnlArrowEl.textContent = "▲";
        } else {
            pnlIndicatorEl.classList.add("pnl-negative");
            pnlIndicatorEl.classList.remove("pnl-positive");
            if (pnlArrowEl) pnlArrowEl.textContent = "▼";
        }
    }

    // =====================================================
    // 14. [SESI 4] SPARKLINE MINI -- WIDGET TOTAL SALDO
    //     Menggambar mini canvas Chart.js tanpa sumbu/label yang
    //     menampilkan jejak tren nilai total kekayaan (saldo + portofolio),
    //     datanya sudah dihitung server-side lewat
    //     hitung_riwayat_nilai_portofolio() di app.py.
    // =====================================================
    const sparklineCanvas = document.getElementById("totalSaldoSparkline");
    // [FIX] Akun baru belum punya jejak nilai portofolio -> CONFIG.sparklineData
    // bisa kosong/panjang 1. Daripada melewatkan widget sepenuhnya (dan
    // berisiko elemen kosong terlihat aneh), pakai fallback data tren dasar
    // [0, 0] supaya Chart.js tetap punya minimal 2 titik untuk digambar.
    const dataSparklineAman = (Array.isArray(CONFIG.sparklineData) && CONFIG.sparklineData.length > 1)
        ? CONFIG.sparklineData
        : [0, 0];
    if (sparklineCanvas && typeof Chart !== "undefined") {
      try {
        const dataSparkline = dataSparklineAman;
        const trenNaik = dataSparkline[dataSparkline.length - 1] >= dataSparkline[0];
        const warnaSparkline = trenNaik ? "#2dd4bf" : "#f2545b";
        const warnaFillSparkline = trenNaik ? "rgba(45,212,191,0.14)" : "rgba(242,84,91,0.14)";

        new Chart(sparklineCanvas, {
            type: "line",
            data: {
                labels: dataSparkline.map((_, i) => i),
                datasets: [{
                    data: dataSparkline,
                    borderColor: warnaSparkline,
                    backgroundColor: warnaFillSparkline,
                    borderWidth: 2,
                    tension: 0.35,
                    fill: true,
                    pointRadius: 0,
                    pointHoverRadius: 3
                }]
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                animation: { duration: 450 },
                plugins: {
                    legend: { display: false },
                    tooltip: {
                        callbacks: {
                            label: (ctx) => "Rp" + Number(ctx.parsed.y).toLocaleString("id-ID", { maximumFractionDigits: 0 })
                        }
                    }
                },
                scales: {
                    x: { display: false },
                    y: { display: false }
                }
            }
        });
      } catch (e) {
        // [FIX KRUSIAL] Jangan biarkan sparkline widget yang gagal digambar
        // menghentikan sisa <script> (slider alokasi, tab Contact, dsb).
        console.error("Gagal membuat sparkline Total Saldo:", e);
      }
    }

    // =====================================================
    // 14b. [PART 1] MINI SPARKLINE -- BOX KOIN DI TICKER STRIP
    //      (BTC, ETH, SOL, DOGE, USDT), tepat di atas grafik utama.
    //      Riwayat harga per-koin diambil dari endpoint yang sama dengan
    //      grafik tren utama (/api/market-history). USDT tidak memiliki
    //      riwayat (selalu flat), jadi digambar sebagai garis datar
    //      memakai harga live yang sudah ada di DOM ticker-strip.
    // =====================================================
    async function initTickerSparklines() {
        const canvasList = document.querySelectorAll(".ticker-sparkline-canvas");
        if (!canvasList.length || typeof Chart === "undefined") return;

        let riwayatSemuaKoin = {};
        try {
            const resp = await fetch(CONFIG.urls.apiMarketHistory);
            const result = await resp.json();
            if (result.ok && result.data) riwayatSemuaKoin = result.data;
        } catch (err) {
            // Kalau fetch gagal, tiap canvas tetap fallback ke garis datar di bawah.
        }

        canvasList.forEach((canvas) => {
          try {
            const kodeKoin = (canvas.getAttribute("data-coin") || "").toUpperCase();
            let titikHarga = (riwayatSemuaKoin[kodeKoin] || []).map((titik) => titik.harga);

            // Koin tanpa riwayat historis (mis. USDT yang selalu flat, atau
            // akun baru yang belum pernah menekan "Refresh Harga") ->
            // tampilkan garis datar memakai harga live yang sudah dirender,
            // fallback ke array [0,0,0,0] kalau harga live pun tidak ketemu,
            // supaya Chart.js tetap punya data valid untuk digambar.
            if (titikHarga.length < 2) {
                const tickerPriceEl = document.querySelector('.ticker-price[data-coin="' + kodeKoin.toLowerCase() + '"]');
                const hargaSekarang = tickerPriceEl ? parseFloat(tickerPriceEl.getAttribute("data-harga")) || 0 : 0;
                titikHarga = [hargaSekarang, hargaSekarang, hargaSekarang, hargaSekarang];
            }

            const trenNaik = titikHarga[titikHarga.length - 1] >= titikHarga[0];
            const warnaGaris = trenNaik ? "#2dd4bf" : "#f2545b";

            new Chart(canvas, {
                type: "line",
                data: {
                    labels: titikHarga.map((_, i) => i),
                    datasets: [{
                        data: titikHarga,
                        borderColor: warnaGaris,
                        borderWidth: 1.5,
                        tension: 0.35,
                        fill: false,
                        pointRadius: 0,
                        pointHoverRadius: 0
                    }]
                },
                options: {
                    responsive: false,
                    maintainAspectRatio: false,
                    animation: false,
                    plugins: {
                        legend: { display: false },
                        tooltip: { enabled: false }
                    },
                    scales: {
                        x: { display: false },
                        y: { display: false }
                    }
                }
            });
          } catch (e) {
            // [FIX KRUSIAL] Satu mini-sparkline gagal digambar TIDAK BOLEH
            // menghentikan sisa loop ataupun sisa <script> di bawahnya.
            console.error("Gagal membuat mini sparkline ticker:", e);
          }
        });
    }
    initTickerSparklines();

    // =====================================================
    // 15b. [PART 1] TAB "✉️ Contact" -- disisipkan ke sidebar lewat JS
    //      (bukan mengedit templates/base.html), lalu didaftarkan ke
    //      logika switching tab yang sudah ada (lihat bagian 6 di atas).
    //      Form "Kirim Pesan" masih murni front-end (belum ada endpoint
    //      backend khusus), jadi submit-nya disimulasikan lewat toast.
    // =====================================================
    (function pasangMenuContactDanForm() {
        const sidebarEl = document.querySelector(".sidebar");
        const navPengaturan = document.querySelector('.nav-item[data-tab="pengaturan"]');
        if (!sidebarEl || !navPengaturan || document.querySelector('.nav-item[data-tab="contact"]')) return;

        const navContact = document.createElement("a");
        navContact.href = "#";
        navContact.className = "nav-item";
        navContact.setAttribute("data-tab", "contact");
        navContact.innerHTML = '<span class="icon">✉️</span><span class="label">Contact</span>';
        navPengaturan.insertAdjacentElement("afterend", navContact);

        // Daftarkan tombol baru ini ke mekanisme switching tab yang sama
        // persis dengan tombol nav lainnya (lihat bagian 6), supaya
        // perilakunya 100% konsisten (highlight aktif + tampilkan panel).
        navContact.addEventListener("click", (e) => {
            e.preventDefault();
            document.querySelectorAll(".nav-item[data-tab]").forEach((b) => b.classList.remove("active"));
            navContact.classList.add("active");
            document.querySelectorAll(".tab-panel").forEach((panel) => {
                panel.classList.toggle("active", panel.id === "tab-contact");
            });
        });

        // [PART 2] Form "Kirim Pesan" -- submit asli ke backend lewat fetch(),
        // pesan disimpan permanen ke tabel contact_messages di SQLite.
        const contactForm = document.getElementById("contactMessageForm");
        if (contactForm) {
            contactForm.addEventListener("submit", (e) => {
                e.preventDefault();

                const namaEl = document.getElementById("contactNama");
                const submitBtn = document.getElementById("contactSubmitBtn");
                const namaPengirim = namaEl && namaEl.value.trim() ? namaEl.value.trim() : "Guest";

                // Simpan teks tombol asli supaya bisa dikembalikan lagi setelah
                // proses selesai (baik sukses maupun gagal), dan ganti sementara
                // jadi teks "Mengirim..." + kunci tombolnya supaya tidak bisa
                // di-double click selama request masih berjalan.
                const teksTombolAsli = submitBtn ? submitBtn.innerHTML : "";
                if (submitBtn) {
                    submitBtn.disabled = true;
                    submitBtn.innerHTML = '<i class="fa-solid fa-spinner fa-spin"></i> Mengirim...';
                }

                const formData = new FormData(contactForm);

                fetch("/api/contact/kirim", {
                    method: "POST",
                    body: formData
                })
                    .then((res) => res.json())
                    .then((data) => {
                        if (data.ok) {
                            showToast(data.message || ("Terima kasih " + namaPengirim + ", pesanmu sudah tercatat untuk developer!"), "success");
                            contactForm.reset();
                        } else {
                            showToast(data.message || "Gagal mengirim pesan, silakan coba lagi.", "danger");
                        }
                    })
                    .catch(() => {
                        showToast("Gagal terhubung ke server, silakan coba lagi.", "danger");
                    })
                    .finally(() => {
                        // Selalu kembalikan tombol ke kondisi semula (teks & aktif
                        // kembali) apa pun hasilnya, dan jaga-jaga sembunyikan lagi
                        // loading overlay full-screen kalau entah kenapa masih
                        // sempat aktif, supaya tidak ada lagi kondisi "nyangkut".
                        if (submitBtn) {
                            submitBtn.disabled = false;
                            submitBtn.innerHTML = teksTombolAsli;
                        }
                        hideLoadingOverlay();
                    });
            });
        }
    })();

    // =====================================================
    // 15c. [FITUR BARU] WIDGET "📬 KOTAK MASUK PESAN (ADMIN ONLY)" --
    //      tombol "Hapus" tiap baris memanggil endpoint AJAX
    //      /api/contact/hapus/<id>, lalu baris tabel yang bersangkutan
    //      langsung dihapus dari DOM (tanpa reload halaman penuh).
    // =====================================================
    (function pasangHandlerKotakMasukPesan() {
        const tbody = document.getElementById("contactInboxTbody");
        if (!tbody) return;

        tbody.addEventListener("click", async (e) => {
            const btn = e.target.closest(".js-contact-hapus-btn");
            if (!btn) return;

            if (!confirm("Hapus pesan ini dari kotak masuk?")) return;

            const msgId = btn.getAttribute("data-msg-id");
            const baris = btn.closest("tr");

            btn.disabled = true;
            const teksTombolAsli = btn.innerHTML;
            btn.innerHTML = '<i class="fa-solid fa-spinner fa-spin"></i> Menghapus...';

            try {
                const resp = await fetch(CONFIG.urls.apiContactHapus + msgId, {
                    method: "POST",
                    headers: { "X-Requested-With": "XMLHttpRequest" }
                });
                const result = await resp.json();

                if (result.ok) {
                    if (baris) {
                        baris.remove();
                        // Kalau semua baris pesan sudah habis dihapus, tampilkan
                        // lagi baris placeholder "Belum ada pesan masuk."
                        if (!tbody.querySelector("tr[data-msg-id]")) {
                            const barisKosong = document.createElement("tr");
                            barisKosong.id = "contactInboxEmptyRow";
                            barisKosong.innerHTML =
                                '<td colspan="6" style="text-align:center; color:var(--text-secondary);">Belum ada pesan masuk.</td>';
                            tbody.appendChild(barisKosong);
                        }
                    }
                    showToast(result.message || "Pesan berhasil dihapus.", "success");
                } else {
                    showToast(result.message || "Gagal menghapus pesan.", "danger");
                    btn.disabled = false;
                    btn.innerHTML = teksTombolAsli;
                }
            } catch (err) {
                showToast("Gagal terhubung ke server, coba lagi.", "danger");
                btn.disabled = false;
                btn.innerHTML = teksTombolAsli;
            }
        });
    })();

    // =====================================================
    // 15. [SESI 4] SOCIAL TRADING FEED -- LIKE, TOGGLE KOMENTAR,
    //     & REPLY THREAD BERTINGKAT (ala YouTube)
    // =====================================================
    function escapeHtmlKomentar(teks) {
        const div = document.createElement("div");
        div.textContent = teks == null ? "" : String(teks);
        return div.innerHTML;
    }

    function hitungTotalKomentar(daftarKomentar) {
        if (!daftarKomentar) return 0;
        let total = 0;
        daftarKomentar.forEach((k) => {
            total += 1 + hitungTotalKomentar(k.balasan);
        });
        return total;
    }

    // Membangun ulang markup HTML thread komentar bertingkat secara manual
    // di sisi client, meniru struktur macro Jinja render_komentar() di
    // templates/dashboard.html, supaya tampilan tetap konsisten setiap kali
    // komentar baru ditambah/dihapus tanpa perlu reload halaman.
    function bangunHtmlKomentar(daftarKomentar, postId, usernameSaya, roleSaya, isReply) {
        if (!daftarKomentar || daftarKomentar.length === 0) {
            return isReply ? "" : '<p class="balance-sub" style="padding:4px 0;">Belum ada komentar. Jadilah yang pertama berkomentar!</p>';
        }
        let html = '<div class="comment-thread' + (isReply ? ' comment-thread-reply' : '') + '">';
        daftarKomentar.forEach((k) => {
            html += '<div class="comment-item" id="commentItem' + k.id + '">';
            html += '<div class="comment-avatar">' + escapeHtmlKomentar(k.username.charAt(0).toUpperCase()) + '</div>';
            html += '<div class="comment-body">';
            html += '<p class="comment-meta"><strong>' + escapeHtmlKomentar(k.username) + '</strong> <span class="comment-time">' + escapeHtmlKomentar(k.timestamp) + '</span></p>';
            html += '<p class="comment-text">' + escapeHtmlKomentar(k.isi_komentar) + '</p>';
            html += '<div class="comment-actions">';
            html += '<button type="button" class="comment-reply-btn js-comment-reply-btn" data-comment-id="' + k.id + '" data-post-id="' + postId + '">Balas</button>';
            if (roleSaya !== "admin" && k.username === usernameSaya) {
                html += '<button type="button" class="comment-delete-btn js-comment-delete-btn" data-comment-id="' + k.id + '" data-post-id="' + postId + '">Hapus</button>';
            }
            html += '</div>';
            html += '<div class="comment-reply-form-wrap" id="replyForm' + k.id + '" style="display:none;">';
            html += '<form class="feed-comment-form js-feed-comment-form" data-post-id="' + postId + '">';
            html += '<input type="hidden" name="post_id" value="' + postId + '">';
            html += '<input type="hidden" name="parent_id" value="' + k.id + '">';
            html += '<textarea name="isi_komentar" rows="1" maxlength="500" placeholder="Balas ' + escapeHtmlKomentar(k.username) + '..." required></textarea>';
            html += '<button type="submit" class="chip-btn primary feed-comment-submit-btn">Balas</button>';
            html += '</form>';
            html += '</div>';
            html += bangunHtmlKomentar(k.balasan, postId, usernameSaya, roleSaya, true);
            html += '</div>';
            html += '</div>';
        });
        html += '</div>';
        return html;
    }

    function renderUlangKomentar(postId, daftarKomentar) {
        const listEl = document.getElementById("commentList" + postId);
        if (listEl) {
            listEl.innerHTML = bangunHtmlKomentar(daftarKomentar, postId, CONFIG.username, CONFIG.role, false);
            pasangHandlerAksiKomentar(listEl);
        }
        const toggleBtn = document.querySelector('.js-feed-comment-toggle-btn[data-post-id="' + postId + '"] span');
        if (toggleBtn) toggleBtn.textContent = hitungTotalKomentar(daftarKomentar) + " Komentar";
    }

    function pasangHandlerFormKomentar(form) {
        form.addEventListener("submit", async (e) => {
            e.preventDefault();
            const textarea = form.querySelector("textarea[name='isi_komentar']");
            const isiKomentar = textarea ? textarea.value.trim() : "";
            if (!isiKomentar) return;

            const postId = form.getAttribute("data-post-id");
            const formData = new FormData(form);
            try {
                const resp = await fetch(CONFIG.urls.apiFeedKomentar, {
                    method: "POST",
                    headers: { "X-Requested-With": "XMLHttpRequest" },
                    body: formData
                });
                const result = await resp.json();
                if (result.ok) {
                    if (textarea) textarea.value = "";
                    renderUlangKomentar(postId, result.komentar);
                } else {
                    showToast(result.message || "Gagal mengirim komentar.", "danger");
                    if (resp.status === 401) window.location.href = CONFIG.urls.login;
                }
            } catch (err) {
                showToast("Gagal terhubung ke server, coba lagi.", "danger");
            }
        });
    }

    function pasangHandlerAksiKomentar(container) {
        container.querySelectorAll(".js-comment-reply-btn").forEach((btn) => {
            btn.addEventListener("click", () => {
                const formWrap = document.getElementById("replyForm" + btn.getAttribute("data-comment-id"));
                if (formWrap) formWrap.style.display = (formWrap.style.display === "none") ? "block" : "none";
            });
        });
        container.querySelectorAll(".js-comment-delete-btn").forEach((btn) => {
            btn.addEventListener("click", async () => {
                if (!confirm("Hapus komentar ini?")) return;
                const commentId = btn.getAttribute("data-comment-id");
                const postId = btn.getAttribute("data-post-id");
                try {
                    const resp = await fetch(CONFIG.urls.apiFeedHapusKomentar + commentId, {
                        method: "POST",
                        headers: { "X-Requested-With": "XMLHttpRequest" }
                    });
                    const result = await resp.json();
                    if (result.ok) {
                        renderUlangKomentar(postId, result.komentar);
                        showToast("Komentar berhasil dihapus.", "success");
                    } else {
                        showToast(result.message || "Gagal menghapus komentar.", "danger");
                    }
                } catch (err) {
                    showToast("Gagal terhubung ke server, coba lagi.", "danger");
                }
            });
        });
        container.querySelectorAll(".js-feed-comment-form").forEach((form) => {
            pasangHandlerFormKomentar(form);
        });
    }

    // Tombol Like (jempol/hati) -> AJAX/fetch toggle like, jumlah like
    // ter-update live tanpa reload halaman.
    document.querySelectorAll(".js-feed-like-btn").forEach((btn) => {
        btn.addEventListener("click", async () => {
            const postId = btn.getAttribute("data-post-id");
            try {
                const resp = await fetch(CONFIG.urls.apiFeedLike + postId, {
                    method: "POST",
                    headers: { "X-Requested-With": "XMLHttpRequest" }
                });
                const result = await resp.json();
                if (result.ok) {
                    btn.classList.toggle("liked", result.liked);
                    const countEl = btn.querySelector(".feed-like-count");
                    if (countEl) countEl.textContent = result.total_like;
                } else {
                    showToast(result.message || "Gagal memproses like.", "danger");
                    if (resp.status === 401) window.location.href = CONFIG.urls.login;
                }
            } catch (err) {
                showToast("Gagal terhubung ke server, coba lagi.", "danger");
            }
        });
    });

    // Tombol Comment (balon chat) -> toggle buka/tutup panel komentar
    document.querySelectorAll(".js-feed-comment-toggle-btn").forEach((btn) => {
        btn.addEventListener("click", () => {
            const postId = btn.getAttribute("data-post-id");
            const panel = document.getElementById("commentPanel" + postId);
            if (panel) panel.style.display = (panel.style.display === "none") ? "block" : "none";
        });
    });

    // Pasang handler untuk form komentar & tombol balas/hapus yang sudah
    // dirender server-side saat halaman pertama kali dimuat.
    document.querySelectorAll(".social-feed-list").forEach((listEl) => pasangHandlerAksiKomentar(listEl));
})();
