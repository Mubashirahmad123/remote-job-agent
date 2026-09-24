/**
 * RESUMESTUDIO.JS — CV Upload, Parsed Profile & On-Demand Tailor Engine
 * Live: POST /api/resume/{fp} + POST /api/cover-letter/{fp} with same-origin
 * downloads; GET /api/cv/profile + GET /api/cv/variants when the backend
 * provides them (404/501 -> quiet static fallback, not an error banner).
 * Falls back to the simulated demo when the API is unreachable.
 * Reads JobAgent.store.state (never MOCK_*); job ids are string fingerprints.
 */

window.JobAgent = window.JobAgent || {};

JobAgent.resumeStudio = {
  lastResult: null, // {fp, resumeFilename, coverFilename, coverText, resumeHtml, coverHtml}
  _previewTab: 'resume', // 'resume' | 'cover' — active preview tab in the card
  _resumeHtml: '', // cached resume sheet HTML for the active package
  _coverHtml: '', // cached cover-letter sheet HTML for the active package
  SELECT_KEY: 'rja_tailor_fp',
  VARIANT_KEY: 'rja_cv_variant',
  PROFILE_KEY: 'rja_profile_override',
  _profileLoaded: false,
  _variantsLoaded: false,
  _pendingTailorFp: '', // explicit Tailor intent from job cards (wins over prev/saved)
  _variants: [], // last variant list (live or demo) for selection persistence
  _lastProfile: null, // last rendered profile (live merged with local edits)
  _editingProfile: false,

  init() {
    this.cvDropzone = document.getElementById('cvDropzone');
    this.cvFileInput = document.getElementById('cvFileInput');
    this.dropzoneActiveFile = document.getElementById('dropzoneActiveFile');
    this.btnGenerateTailored = document.getElementById('btnGenerateTailored');
    this.shrinkProgressCard = document.getElementById('shrinkProgressCard');
    this.generatedPreviewCard = document.getElementById('generatedPreviewCard');
    this.tailorJobSelect = document.getElementById('tailorJobSelect');
    this.tailorSelectNote = document.getElementById('tailorSelectNote');
    this.variantList = document.getElementById('cvVariantList');
    this.btnDownloadResume = document.getElementById('btnDownloadResume');
    this.btnDownloadCoverLetter = document.getElementById('btnDownloadCoverLetter');
    this.btnDownloadPackage = document.getElementById('btnDownloadPackage');
    this.tabPreviewResume = document.getElementById('tabPreviewResume');
    this.tabPreviewCover = document.getElementById('tabPreviewCover');
    this.btnOpenPdf = document.getElementById('btnOpenPdf');
    this.variantsStatusNote = document.getElementById('variantsStatusNote');
    this.profileStatusNote = document.getElementById('profileStatusNote');

    this.bindEvents();
    this.populateJobSelect();
    this.loadProfile();
    this.loadVariants();
    // Stamp static demo variant cards so click-to-select works before live load.
    if (this.variantList) {
      this.variantList.querySelectorAll('.cv-variant-card').forEach((card) => {
        if (!card.getAttribute('data-variant-name')) {
          const n = (card.querySelector('.variant-name') || {}).textContent || '';
          if (n.trim()) card.setAttribute('data-variant-name', n.trim());
          card.setAttribute('title', 'Click to select this variant for tailoring');
          card.style.cursor = 'pointer';
        }
      });
      // Seed _variants from static demo so Add merges instead of wiping.
      if (!this._variants.length) {
        this._variants = [...this.variantList.querySelectorAll('.cv-variant-card')].map((card) => ({
          name: card.getAttribute('data-variant-name') || '',
          meta: ((card.querySelector('.variant-meta') || {}).textContent || '').trim(),
          raw: null,
        })).filter(v => v.name);
      }
    }
    JobAgent.store.subscribe(() => this.populateJobSelect());
  },

  escapeHtml(value) {
    return String(value == null ? '' : value).replace(/[&<>"']/g, (character) => ({
      '&': '&amp;',
      '<': '&lt;',
      '>': '&gt;',
      '"': '&quot;',
      "'": '&#39;'
    })[character]);
  },

  _note(el, msg, isError) {
    if (!el) return;
    el.textContent = msg || '';
    el.style.color = isError ? '#f59e0b' : '';
  },

  _jobs() {
    // Top-30 from store.state (live or mock fallback). No fingerprint filter
    // here: mock rows carry numeric ids and are still worth listing;
    // selectedFingerprint() decides whether live generation is possible.
    // Scored rows come first (score desc); unscored/snapshot rows (score 0)
    // sink to the bottom ordered by posted date desc — never above fresh
    // scored rows.
    return [...(JobAgent.store.state.jobs || [])]
      .sort((a, b) => {
        const sa = a.match_score || 0, sb = b.match_score || 0;
        if ((sb > 0) !== (sa > 0)) return (sb > 0 ? 1 : 0) - (sa > 0 ? 1 : 0);
        if (sa !== sb) return sb - sa;
        return String(b.posted_date_iso || '') < String(a.posted_date_iso || '') ? -1 : 1;
      })
      .slice(0, 30);
  },

  _optionDate(job) {
    // Per-option posted date so staleness is visible in the dropdown itself.
    if (job.posted_text) return job.posted_text;
    const iso = job.posted_date_iso || (job._raw && (job._raw.posted_date_iso || job._raw.scraped_at)) || '';
    return (String(iso).slice(0, 10)) || 'date unknown';
  },

  _newestAgeDays() {
    // Age of the freshest job in the store (null when no dated rows).
    let newest = 0;
    for (const j of (JobAgent.store.state.jobs || [])) {
      const iso = j.posted_date_iso || (j._raw && (j._raw.posted_date_iso || j._raw.scraped_at)) || '';
      const t = new Date(iso).getTime();
      if (!isNaN(t) && t > newest) newest = t;
    }
    if (!newest) return null;
    return Math.max(0, Math.floor((Date.now() - newest) / 86400000));
  },

  _liveJobs() {
    return (JobAgent.store.state.jobs || []).filter(j => j.job_fingerprint);
  },

  _optionValue(job) {
    if (job.job_fingerprint) return job.job_fingerprint;
    return 'mock-' + String(job.id);
  },

  _savedSelection() {
    try {
      let v = localStorage.getItem(this.SELECT_KEY) || '';
      // Migrate legacy numeric demo ids ("1".."8") to mock scheme once so the
      // ghost-guard does not silently jump on upgrade. Pure mapping, no crash.
      if (/^[1-9]\d*$/.test(v)) {
        v = 'mock-' + v;
        try { localStorage.setItem(this.SELECT_KEY, v); } catch (_) { /* ignore */ }
      }
      return v;
    }
    catch (_) { return ''; }
  },

  _saveSelection(value) {
    try { localStorage.setItem(this.SELECT_KEY, value || ''); }
    catch (_) { /* storage unavailable */ }
  },

  /**
   * Called by job cards (✨ Tailor) before switching to the Studio tab.
   * Accepts a job object or a raw id/fingerprint string. Persists intent so
   * even a not-yet-loaded dropdown picks it up on the next populate.
   * Returns true when the dropdown now shows the target.
   */
  setSelectedJob(jobOrId) {
    let target = '';
    if (jobOrId && typeof jobOrId === 'object') {
      target = this._optionValue(jobOrId) || '';
      // Live object without fingerprint but with numeric id -> mock scheme.
      if (!target && jobOrId.id != null) target = 'mock-' + String(jobOrId.id);
    } else if (jobOrId != null) {
      target = String(jobOrId);
      if (/^[1-9]\d*$/.test(target)) target = 'mock-' + target;
    }
    if (!target) return false;
    this._pendingTailorFp = target;
    this._saveSelection(target);
    if (this.tailorJobSelect && this.tailorJobSelect.options.length) {
      const options = [...this.tailorJobSelect.options].map(o => o.value);
      if (options.includes(target)) {
        this.tailorJobSelect.value = target;
        this._saveSelection(target);
        this._pendingTailorFp = '';
        return true;
      }
      // Target not in current page: rebuild (may appear after sort/filter).
      this.populateJobSelect();
      const after = [...this.tailorJobSelect.options].map(o => o.value);
      if (after.includes(target)) {
        this.tailorJobSelect.value = target;
        this._saveSelection(target);
        this._pendingTailorFp = '';
        return true;
      }
    }
    // Saved + pending: next populateJobSelect() (e.g. after loadAll) applies it.
    return false;
  },

  _savedVariant() {
    try { return localStorage.getItem(this.VARIANT_KEY) || ''; }
    catch (_) { return ''; }
  },

  _saveVariant(name) {
    try { localStorage.setItem(this.VARIANT_KEY, name || ''); }
    catch (_) { /* storage unavailable */ }
  },

  selectVariant(name) {
    const key = String(name || '').trim();
    if (!key) return false;
    this._saveVariant(key);
    // Update card highlight without full re-render.
    if (this.variantList) {
      this.variantList.querySelectorAll('.cv-variant-card').forEach(card => {
        const n = card.getAttribute('data-variant-name') || '';
        card.classList.toggle('selected', n === key);
      });
    }
    if (JobAgent.toast) JobAgent.toast.show(`CV variant selected: ${key} — will be used for tailoring.`);
    return true;
  },

  getSelectedVariant() {
    return this._savedVariant() || ((this._variants[0] && (this._variants[0].name || '')) || '');
  },

  populateJobSelect() {
    if (!this.tailorJobSelect) return;
    const jobs = this._jobs();
    if (!jobs.length) {
      // Nothing in the store yet: show a disabled loading/demo placeholder
      // instead of stale hardcoded companies. Never leave Kobo/Bjak/Airspace
      // demo rows visible here — they now live only in mockData.js fallback.
      this.tailorJobSelect.innerHTML = '<option value="">Loading live jobs from /api/jobs…</option>';
      this.tailorJobSelect.value = '';
      this.tailorJobSelect.disabled = true;
      this.tailorJobSelect.dataset.source = 'loading';
      this._note(this.tailorSelectNote, JobAgent.store.state.loading.jobs
        ? 'Loading live jobs from /api/jobs…'
        : 'Live jobs unavailable — press Scrape Now or check API connection.', false);
      return;
    }
    this.tailorJobSelect.disabled = false;
    const live = this._liveJobs().length;
    const isCached = !live;
    const prev = this.tailorJobSelect.value || '';
    const saved = this._savedSelection();
    this.tailorJobSelect.innerHTML = jobs.map(j => {
      const score = (j.match_score || 0);
      // Cached/mock rows are visually distinct so users never mistake them
      // for fresh live jobs: prefix [CACHED] when no fingerprints exist.
      const prefix = isCached ? '[CACHED] ' : '';
      return `<option value="${this.escapeHtml(this._optionValue(j))}">${this.escapeHtml(prefix + j.job_title)} @ ${this.escapeHtml(j.company)} (${score}% · ${this.escapeHtml(this._optionDate(j))})</option>`;
    }).join('');
    this.tailorJobSelect.dataset.source = isCached ? 'cached' : 'live';
    const options = [...this.tailorJobSelect.options].map(o => o.value);
    // Priority: explicit Tailor intent (✨ Tailor on job card) > current DOM >
    // saved storage > first option. Pending survives until its fp appears.
    const pending = this._pendingTailorFp || '';
    let next;
    if (pending && options.includes(pending)) {
      next = pending;
      this._pendingTailorFp = '';
    } else if (prev && options.includes(prev)) {
      next = prev;
    } else if (saved && options.includes(saved)) {
      next = saved;
    } else {
      next = (options[0] || '');
    }
    // If pending target is not in this page yet (top-30 filter / not loaded),
    // keep it for the next populate instead of dropping the intent.
    this.tailorJobSelect.value = next;
    this._saveSelection(this.tailorJobSelect.value);
    if (!live) {
      this._note(this.tailorSelectNote,
        'Showing CACHED jobs (mock fallback) — live generation unavailable until the API responds. Press Scrape Now for fresh listings.', true);
      return;
    }
    const age = this._newestAgeDays();
    const ageBit = (age == null) ? ''
      : (age <= 0 ? ' · newest posted today'
      : age === 1 ? ' · newest posted yesterday'
      : ` · newest posted ${age} days ago`);
    if (age != null && age > 3) {
      // Live-but-old: amber warning (isError=true renders #f59e0b), not the
      // plain "Live jobs loaded" line that hid staleness before.
      this._note(this.tailorSelectNote,
        `Live jobs loaded (${live} with fingerprints, top 30 by score${ageBit}). `
        + `Jobs are ${age} days old — press Scrape Now for fresh listings.`, true);
    } else {
      this._note(this.tailorSelectNote,
        `Live jobs loaded (${live} with fingerprints, top 30 by score${ageBit}).`, false);
    }
  },

  _selectedJob() {
    if (!this.tailorJobSelect) return null;
    const v = this.tailorJobSelect.value || '';
    const jobs = this._jobs();
    return jobs.find(j => this._optionValue(j) === v) || null;
  },

  _demoProfile() {
    const p = this._lastProfile || {};
    const name = p.full_name || p.name
      || ((document.getElementById('profName') || {}).textContent || '').trim() || 'Your Name';
    const email = p.email
      || ((document.getElementById('profEmail') || {}).textContent || '').trim() || '';
    const skills = Array.isArray(p.skills) ? p.skills
      : Array.isArray(p.core_skills) ? p.core_skills : null;
    const skillList = (skills && skills.length ? skills : [...document.querySelectorAll('#profSkills .skill-tag')]
      .map(s => (s.textContent || '').trim()).filter(Boolean)).slice(0, 12);
    return { name, email, skills: skillList };
  },

  _resumeSheetHtml({ name, sub, skills, jobTitle, company, demoBadge }) {
    return `
      <div class="mock-name">${this.escapeHtml((name || 'YOUR NAME').toUpperCase())}</div>
      <div class="mock-sub">${this.escapeHtml(sub || '')}</div>
      <div class="mock-rule"></div>
      <div class="mock-section-title">TECHNICAL EXPERTISE</div>
      <div class="mock-text">${this.escapeHtml((skills && skills.length ? skills : ['—']).join(', '))}</div>
      <div class="mock-section-title">PROFESSIONAL EXPERIENCE</div>
      <div class="mock-bullet">• Tailored to ${this.escapeHtml(jobTitle || 'selected role')}${company ? ' @ ' + this.escapeHtml(company) : ''} — keyword-matched bullets</div>`
      + (demoBadge ? '\n<div class="mock-bullet">• Demo preview — live generation replaces this with LLM output</div>' : '');
  },

  _demoCoverText(jobTitle, company) {
    return `Dear Hiring Team,\n\nI am excited to apply for the ${jobTitle || 'role'}${company ? ' at ' + company : ''}. `
      + `My background aligns closely with the tech stack and requirements in the posting. (Demo letter — live generation replaces this.)`;
  },

  _coverSheetHtml({ coverText, jobTitle, company, demoBadge }) {
    const body = coverText
      || (demoBadge ? this._demoCoverText(jobTitle, company) : '—');
    return `
      <div class="mock-section-title">COVER LETTER PREVIEW</div>
      <div class="mock-text" style="white-space: pre-wrap;">${this.escapeHtml(body)}</div>`;
  },

  _showPackageCard({ filename, jobTitle, company, resumeHtml, coverHtml, defaultTab }) {
    // Stores both sheet views, paints the requested tab, unhides the card.
    this._resumeHtml = resumeHtml || '';
    this._coverHtml = coverHtml || '';
    this._previewTab = defaultTab === 'cover' ? 'cover' : 'resume';
    if (!this.generatedPreviewCard) return;
    const header = this.generatedPreviewCard.querySelector('.doc-preview-meta h4');
    if (header) header.innerHTML = `Tailored Package Generated: <code>${this.escapeHtml(filename || 'resume.pdf')}</code>`;
    const meta = this.generatedPreviewCard.querySelector('.doc-meta-info');
    if (meta) meta.textContent = `${jobTitle || ''}${company ? ' @ ' + company : ''} • 1 Page ATS Verified`.trim() || '1 Page ATS Verified';
    this._paintPreviewTab();
    this.generatedPreviewCard.classList.remove('hidden');
  },

  _paintPreviewTab() {
    if (!this.generatedPreviewCard) return;
    const preview = this.generatedPreviewCard.querySelector('.mock-sheet');
    if (preview) {
      preview.innerHTML = this._previewTab === 'cover' ? (this._coverHtml || '') : (this._resumeHtml || '');
    }
    if (this.tabPreviewResume) this.tabPreviewResume.classList.toggle('active', this._previewTab !== 'cover');
    if (this.tabPreviewCover) this.tabPreviewCover.classList.toggle('active', this._previewTab === 'cover');
  },

  switchPreviewTab(which) {
    const next = which === 'cover' ? 'cover' : 'resume';
    if (next === 'cover' && !this._coverHtml) {
      if (JobAgent.toast) JobAgent.toast.show('No cover letter yet — press Generate first.', 'warn');
      return;
    }
    if (next === 'resume' && !this._resumeHtml) {
      if (JobAgent.toast) JobAgent.toast.show('No resume yet — press Generate first.', 'warn');
      return;
    }
    this._previewTab = next;
    this._paintPreviewTab();
  },
  selectedFingerprint() {
    if (!this.tailorJobSelect) return '';
    const v = this.tailorJobSelect.value || '';
    // Live options carry fingerprints; demo options carry numeric mock ids
    // and mock-fallback options carry a 'mock-' prefix. Neither is generatable.
    if (/^\d+$/.test(v) || /^mock-/.test(v)) return '';
    return v;
  },

  bindEvents() {
    // Persist the tailor target across reloads (string fingerprint ids).
    if (this.tailorJobSelect && !this.tailorJobSelect.dataset.persistWired) {
      this.tailorJobSelect.dataset.persistWired = '1';
      this.tailorJobSelect.addEventListener('change', () => {
        this._saveSelection(this.tailorJobSelect.value);
      });
    }

    // Parsed AI Profile Cache: Edit toggles inline inputs, Save persists.
    const btnEditProfile = document.getElementById('btnEditProfile');
    if (btnEditProfile && !btnEditProfile.dataset.wired) {
      btnEditProfile.dataset.wired = '1';
      btnEditProfile.addEventListener('click', () => {
        if (this._editingProfile) this.saveProfileEdit();
        else this.enterEditMode();
      });
    }

    // Multi-CV variants: click a card to select it for tailoring; +Add Variant
    // picks a local .pdf/.docx and adds it to the list (persists locally
    // until a backend upload endpoint exists — Phase 2 backlog).
    if (this.variantList && !this.variantList.dataset.selectWired) {
      this.variantList.dataset.selectWired = '1';
      this.variantList.style.cursor = 'pointer';
      this.variantList.addEventListener('click', (e) => {
        const card = e.target.closest('.cv-variant-card');
        if (!card) return;
        const name = card.getAttribute('data-variant-name')
          || (card.querySelector('.variant-name') || {}).textContent || '';
        if (name.trim()) this.selectVariant(name.trim());
      });
    }
    const btnAddVariant = document.getElementById('btnAddVariant');
    if (btnAddVariant && !btnAddVariant.dataset.wired) {
      btnAddVariant.dataset.wired = '1';
      btnAddVariant.addEventListener('click', () => {
        // Hidden file picker (no backend POST yet — local add only).
        let picker = document.getElementById('cvVariantFileInput');
        if (!picker) {
          picker = document.createElement('input');
          picker.type = 'file';
          picker.id = 'cvVariantFileInput';
          picker.accept = '.pdf,.docx';
          picker.style.display = 'none';
          document.body.appendChild(picker);
          picker.addEventListener('change', () => {
            const f = picker.files && picker.files[0];
            picker.value = '';
            if (!f) return;
            if (!/\.(pdf|docx)$/i.test(f.name)) {
              JobAgent.toast.show('Only PDF or DOCX variants are supported.', 'warn');
              return;
            }
            if (f.size > 10 * 1024 * 1024) {
              JobAgent.toast.show('Variant file exceeds 10MB limit.', 'warn');
              return;
            }
            this.addLocalVariant(f.name, `${(f.size / 1024).toFixed(1)} KB • Added just now`);
          });
        }
        picker.click();
      });
    }
    // Dropzone click & drag events (local demo — no upload endpoint yet, Phase 2 backlog)
    if (this.cvDropzone && this.cvFileInput) {
      this.cvDropzone.addEventListener('click', () => {
        this.cvFileInput.click();
      });

      this.cvFileInput.addEventListener('change', (e) => {
        if (e.target.files.length > 0) {
          const file = e.target.files[0];
          this.handleUploadedFile(file.name, file.size);
        }
      });

      this.cvDropzone.addEventListener('dragover', (e) => {
        e.preventDefault();
        this.cvDropzone.classList.add('drag-over');
      });

      this.cvDropzone.addEventListener('dragleave', () => {
        this.cvDropzone.classList.remove('drag-over');
      });

      this.cvDropzone.addEventListener('drop', (e) => {
        e.preventDefault();
        this.cvDropzone.classList.remove('drag-over');
        if (e.dataTransfer.files.length > 0) {
          const file = e.dataTransfer.files[0];
          this.handleUploadedFile(file.name, file.size);
        }
      });
    }

    if (this.btnGenerateTailored) {
      this.btnGenerateTailored.addEventListener('click', () => {
        this.generate();
      });
    }

    if (this.btnDownloadResume) {
      this.btnDownloadResume.addEventListener('click', () => {
        const r = this.lastResult;
        if (r && r.fp === this.selectedFingerprint() && r.resumeFilename) {
          window.location.href = JobAgent.api.baseUrl() + '/api/resume/' + encodeURIComponent(r.fp) + '/download';
        } else {
          this.triggerDownload('Tailored_Resume.pdf', '%PDF-1.4 ATS Tailored 1-page resume (demo)');
        }
      });
    }

    if (this.btnDownloadCoverLetter) {
      this.btnDownloadCoverLetter.addEventListener('click', () => {
        const r = this.lastResult;
        // Live result for the selected job, or the demo package (fp 'demo').
        if (r && r.coverText && (r.fp === this.selectedFingerprint() || r.fp === 'demo')) {
          this.triggerDownload(r.coverFilename || 'cover_letter.txt', r.coverText);
        } else {
          this.triggerDownload('Cover_Letter.txt', 'Dear Hiring Team,\n\nI am writing to express my strong interest... (demo)');
        }
      });
    }

    if (this.btnDownloadPackage) {
      this.btnDownloadPackage.addEventListener('click', () => {
        const r = this.lastResult;
        if (r && r.fp === this.selectedFingerprint()) {
          window.location.href = JobAgent.api.baseUrl() + '/api/resume/' + encodeURIComponent(r.fp) + '/download';
          setTimeout(() => {
            window.location.href = JobAgent.api.baseUrl() + '/api/cover-letter/' + encodeURIComponent(r.fp) + '/download';
          }, 800);
          JobAgent.toast.show('Downloading tailored package (resume + cover letter).');
        } else {
          this.triggerDownload('Apply_Package.zip', 'PK [demo package]');
        }
      });
    }

    // Preview tabs: Resume | Cover Letter switch the sheet view in place.
    if (this.tabPreviewResume && !this.tabPreviewResume.dataset.wired) {
      this.tabPreviewResume.dataset.wired = '1';
      this.tabPreviewResume.addEventListener('click', () => this.switchPreviewTab('resume'));
    }
    if (this.tabPreviewCover && !this.tabPreviewCover.dataset.wired) {
      this.tabPreviewCover.dataset.wired = '1';
      this.tabPreviewCover.addEventListener('click', () => this.switchPreviewTab('cover'));
    }
    // Open PDF: real generated PDF in a new tab (live results only).
    if (this.btnOpenPdf && !this.btnOpenPdf.dataset.wired) {
      this.btnOpenPdf.dataset.wired = '1';
      this.btnOpenPdf.addEventListener('click', () => {
        const r = this.lastResult;
        const fp = this.selectedFingerprint();
        if (r && r.fp && r.fp !== 'demo' && r.fp === fp && r.resumeFilename) {
          window.open(JobAgent.api.baseUrl() + '/api/resume/' + encodeURIComponent(r.fp) + '/download', '_blank', 'noopener');
        } else {
          JobAgent.toast.show('No live PDF to open — select a live job and press Generate first.', 'warn');
        }
      });
    }
  },

  handleUploadedFile(name, size) {
    const sizeKb = (size / 1024).toFixed(1);
    if (this.dropzoneActiveFile) {
      this.dropzoneActiveFile.innerHTML = `
        <span class="file-tag">Current: <strong>${name}</strong> (${sizeKb} KB)</span>
        <span class="badge-emerald">Uploaded & Parsed</span>
      `;
    }
    JobAgent.toast.show(`Uploaded ${name}. Extracted skills and contact profile cache.`);
  },

  setSteps(state) {
    // state: 'role' | 'resume' | 'letter' | 'done'
    const step1 = document.getElementById('step1');
    const step2 = document.getElementById('step2');
    const step3 = document.getElementById('step3');
    if (!step1 || !step2 || !step3) return;
    const order = ['role', 'resume', 'letter'];
    [step1, step2, step3].forEach((el, i) => {
      el.className = 'shrink-step'
        + (state === 'done' || order.indexOf(state) > i ? ' done' : '')
        + (state !== 'done' && order.indexOf(state) === i ? ' active' : '');
    });
    const labels = {
      role: 'Role category detected — adjusting tone & skills',
      resume: 'Generating 1-page ATS resume (LLM)…',
      letter: 'Generating tailored cover letter…',
    };
    const setText = (el, html) => {
      if (!el) return;
      const t = el.querySelector('.step-text');
      if (t) t.innerHTML = html;
    };
    if (state === 'role') setText(step1, labels.role);
    if (state === 'resume') setText(step2, labels.resume);
    if (state === 'letter') setText(step3, labels.letter);
  },

  async generate() {
    const fp = this.selectedFingerprint();
    if (!fp) {
      // No generatable fingerprint selected: demo job (numeric), mock-fallback
      // row ('mock-…'), or an empty store. Say which before running the demo.
      const live = this._liveJobs().length;
      JobAgent.toast.show(live
        ? 'Selected job has no live fingerprint — showing demo package instead.'
        : 'No live jobs loaded — running the demo tailor engine instead.', 'warn');
      this.runShrinkEngine();
      return;
    }
    if (this.shrinkProgressCard) this.shrinkProgressCard.classList.remove('hidden');
    if (this.generatedPreviewCard) this.generatedPreviewCard.classList.add('hidden');
    this.btnGenerateTailored.disabled = true;
    try {
      this.setSteps('role');
      await new Promise(r => setTimeout(r, 400));
      this.setSteps('resume');
      const resume = await JobAgent.api.createResume(fp);
      this.setSteps('letter');
      const letter = await JobAgent.api.createCoverLetter(fp);
      this.setSteps('done');
      this.lastResult = {
        fp,
        resumeFilename: resume.filename,
        coverFilename: letter.filename,
        coverText: letter.cover_letter || '',
      };
      this.showResult(resume, letter);
      JobAgent.toast.show('Tailored resume + cover letter generated successfully!');
    } catch (e) {
      JobAgent.toast.show('Live generation failed (' + (e && e.message ? e.message : 'unknown error') + ') — showing demo package instead.', 'warn');
      this.runShrinkEngine();
    } finally {
      this.btnGenerateTailored.disabled = false;
    }
  },

  showResult(resume, letter) {
    if (this.shrinkProgressCard) this.shrinkProgressCard.classList.add('hidden');
    const jobTitle = (resume && resume.job_title) || '';
    const company = (resume && resume.company) || '';
    const prof = this._demoProfile();
    const resumeHtml = this._resumeSheetHtml({
      name: prof.name,
      sub: [jobTitle, company, prof.email].filter(Boolean).join(' • '),
      skills: prof.skills, jobTitle, company, demoBadge: false,
    });
    const coverText = (letter && letter.cover_letter) || '';
    const coverHtml = this._coverSheetHtml({ coverText, jobTitle, company, demoBadge: false });
    if (this.lastResult) {
      this.lastResult.resumeHtml = resumeHtml;
      this.lastResult.coverHtml = coverHtml;
    }
    this._showPackageCard({
      filename: (resume && resume.filename) || 'resume.pdf',
      jobTitle, company, resumeHtml, coverHtml,
      defaultTab: this._previewTab,
    });
  },

  async loadProfile() {
    if (this._profileLoaded) return;
    this._profileLoaded = true;
    this._note(this.profileStatusNote, 'Loading parsed profile from /api/cv/profile…', false);
    const override = this._getProfileOverride();
    try {
      const profile = await JobAgent.api.getCvProfile();
      if (!profile || profile._unavailable) {
        if (override && Object.keys(override).length) {
          this.renderProfile(override);
          this._note(this.profileStatusNote, 'Showing your saved edits (live profile unavailable).', false);
        } else {
          // Backend endpoint not built yet: keep the static panel, quiet note.
          this._note(this.profileStatusNote, 'Live profile not available yet — showing cached demo.', false);
        }
        return;
      }
      const merged = this._applyOverride(profile, override);
      this.renderProfile(merged);
      this._note(this.profileStatusNote, override && Object.keys(override).length
        ? 'Live profile loaded + your saved edits applied.'
        : 'Live profile loaded.', false);
    } catch (e) {
      if (override && Object.keys(override).length) {
        this.renderProfile(override);
        this._note(this.profileStatusNote, 'Showing your saved edits (profile API unreachable).', true);
      } else {
        this._note(this.profileStatusNote,
          'Profile API error: ' + (e && e.message ? e.message : 'unknown error') + ' — showing cached demo.', true);
      }
    }
  },

  _getProfileOverride() {
    try {
      const raw = localStorage.getItem(this.PROFILE_KEY) || '';
      if (!raw) return {};
      const obj = JSON.parse(raw);
      return (obj && typeof obj === 'object') ? obj : {};
    } catch (_) { return {}; }
  },

  _saveProfileOverride(obj) {
    try { localStorage.setItem(this.PROFILE_KEY, JSON.stringify(obj || {})); }
    catch (_) { /* storage unavailable */ }
  },

  _applyOverride(profile, override) {
    if (!override || !Object.keys(override).length) return profile;
    const merged = { ...(profile || {}) };
    for (const k of ['name', 'full_name', 'email', 'phone', 'linkedin', 'linkedin_url', 'location']) {
      if (override[k] != null && String(override[k]).trim() !== '') merged[k] = override[k];
    }
    if (Array.isArray(override.skills) && override.skills.length) merged.skills = override.skills;
    return merged;
  },

  _currentFieldValues() {
    const text = (id) => {
      const el = document.getElementById(id);
      if (!el) return '';
      const input = el.querySelector('input, textarea');
      if (input) return (input.value || '').trim();
      return (el.textContent || '').trim();
    };
    const skillsEl = document.getElementById('profSkills');
    let skills = [];
    if (skillsEl) {
      const ta = skillsEl.querySelector('textarea');
      if (ta) {
        skills = String(ta.value || '').split(/[,;\n]+/).map(s => s.trim()).filter(Boolean);
      } else {
        skills = [...skillsEl.querySelectorAll('.skill-tag')].map(s => (s.textContent || '').trim()).filter(Boolean);
      }
    }
    return {
      name: text('profName'),
      email: text('profEmail'),
      phone: text('profPhone'),
      linkedin: text('profLinkedIn'),
      skills,
    };
  },

  enterEditMode() {
    if (this._editingProfile) return;
    this._editingProfile = true;
    const vals = this._lastProfile ? {
      name: this._lastProfile.full_name || this._lastProfile.name || '',
      email: this._lastProfile.email || '',
      phone: this._lastProfile.phone || '',
      linkedin: this._lastProfile.linkedin || this._lastProfile.linkedin_url || '',
      skills: Array.isArray(this._lastProfile.skills) ? this._lastProfile.skills
        : Array.isArray(this._lastProfile.core_skills) ? this._lastProfile.core_skills : null,
    } : {
      name: '', email: '', phone: '', linkedin: '', skills: null,
    };
    // Fall back to visible demo text when no profile has rendered yet.
    const fallback = (id) => {
      const el = document.getElementById(id);
      return el ? (el.textContent || '').trim() : '';
    };
    if (!vals.name) vals.name = fallback('profName');
    if (!vals.email) vals.email = fallback('profEmail');
    if (!vals.phone) vals.phone = fallback('profPhone');
    if (!vals.linkedin) vals.linkedin = fallback('profLinkedIn');
    if (vals.skills == null) {
      const skillsEl = document.getElementById('profSkills');
      vals.skills = skillsEl
        ? [...skillsEl.querySelectorAll('.skill-tag')].map(s => (s.textContent || '').trim()).filter(Boolean)
        : [];
    }
    const toInput = (id, value, placeholder) => {
      const el = document.getElementById(id);
      if (!el) return;
      el.innerHTML = '';
      const input = document.createElement('input');
      input.type = 'text';
      input.value = (value === '—' ? '' : value) || '';
      input.placeholder = placeholder || '';
      input.className = 'filter-select full-width';
      input.style.cssText = 'font-size:12.5px;padding:6px 8px;';
      el.appendChild(input);
    };
    toInput('profName', vals.name, 'Full name');
    toInput('profEmail', vals.email, 'Email');
    toInput('profPhone', vals.phone, 'Phone');
    toInput('profLinkedIn', vals.linkedin, 'LinkedIn URL');
    const skillsEl = document.getElementById('profSkills');
    if (skillsEl) {
      skillsEl.innerHTML = '';
      skillsEl.classList.add('editing');
      const ta = document.createElement('textarea');
      ta.value = (vals.skills || []).join(', ');
      ta.placeholder = 'Comma-separated skills: React, Python, FastAPI';
      ta.rows = 6;
      // NOTE: no `filter-select` class here — that select style forces
      // height:32px (jobs.css) and shrinks the textarea. Sizing lives in
      // resume.css `#profSkills textarea` + the inline min-height below.
      ta.className = 'profile-skills-input';
      ta.style.cssText = 'font-size:13px;padding:10px 12px;resize:vertical;min-height:140px;width:100%;box-sizing:border-box;line-height:1.6;';
      skillsEl.appendChild(ta);
      setTimeout(() => { try { ta.style.height = Math.max(140, ta.scrollHeight + 8) + 'px'; } catch (_) { /* ignore */ } }, 0);
      ta.addEventListener('input', () => { try { ta.style.height = 'auto'; ta.style.height = Math.max(140, ta.scrollHeight + 8) + 'px'; } catch (_) { /* ignore */ } });
    }
    const btn = document.getElementById('btnEditProfile');
    if (btn) btn.textContent = 'Save';
    let cancel = document.getElementById('btnCancelProfile');
    if (!cancel && btn && btn.parentElement) {
      cancel = document.createElement('button');
      cancel.id = 'btnCancelProfile';
      cancel.className = 'action-btn secondary small';
      cancel.textContent = 'Cancel';
      cancel.style.marginLeft = '6px';
      cancel.addEventListener('click', () => this.cancelEditMode());
      btn.parentElement.appendChild(cancel);
    }
    if (cancel) cancel.style.display = '';
    this._note(this.profileStatusNote, 'Editing profile — Save to apply locally + sync to API.', false);
  },

  cancelEditMode() {
    this._editingProfile = false;
    const btn = document.getElementById('btnEditProfile');
    if (btn) btn.textContent = 'Edit';
    const cancel = document.getElementById('btnCancelProfile');
    if (cancel) cancel.style.display = 'none';
    // Re-render last known profile (or reload demo) without saving.
    if (this._lastProfile) {
      this.renderProfile(this._lastProfile);
      this._note(this.profileStatusNote, 'Edits discarded.', false);
    } else {
      this._profileLoaded = false;
      this.loadProfile();
    }
  },

  async saveProfileEdit() {
    const vals = this._currentFieldValues();
    if (!vals.name) {
      JobAgent.toast.show('Full name is required.', 'warn');
      return;
    }
    if (vals.email && !/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(vals.email)) {
      JobAgent.toast.show('Email looks invalid — check it and save again.', 'warn');
      return;
    }
    const patch = {
      name: vals.name,
      full_name: vals.name,
      email: vals.email,
      phone: vals.phone,
      linkedin: vals.linkedin,
      linkedin_url: vals.linkedin,
      skills: vals.skills,
    };
    this._saveProfileOverride(patch);
    const merged = this._applyOverride(this._lastProfile || {}, patch);
    this._editingProfile = false;
    const btn = document.getElementById('btnEditProfile');
    if (btn) { btn.textContent = 'Edit'; btn.disabled = true; }
    try {
      this.renderProfile(merged);
      this._note(this.profileStatusNote, 'Saved locally — syncing to API…', false);
      const saved = await JobAgent.api.updateCvProfile(patch);
      if (saved && !saved._unavailable) {
        this.renderProfile(this._applyOverride(saved, this._getProfileOverride()));
        this._note(this.profileStatusNote, 'Profile saved (local + API cache).', false);
        JobAgent.toast.show('Profile saved — used for auto-fill and tailoring.');
      } else {
        this._note(this.profileStatusNote, 'Saved locally (API cache unavailable — will sync later).', true);
        JobAgent.toast.show('Saved locally. API unavailable — edits kept in this browser.', 'warn');
      }
    } catch (e) {
      this._note(this.profileStatusNote,
        'Saved locally; API sync failed (' + (e && e.message ? e.message : 'unknown error') + ').', true);
      JobAgent.toast.show('Saved locally; API sync failed — edits kept in this browser.', 'warn');
    } finally {
      if (btn) btn.disabled = false;
      const cancel = document.getElementById('btnCancelProfile');
      if (cancel) cancel.style.display = 'none';
    }
  },

  renderProfile(p = {}) {
    // Enrichment-absent fields come back null — render "—", never crash.
    this._lastProfile = { ...(p || {}) };
    const set = (id, val) => {
      const el = document.getElementById(id);
      if (el) el.textContent = (val == null || val === '') ? '—' : String(val);
    };
    set('profName', p.full_name || p.name);
    set('profEmail', p.email);
    set('profPhone', p.phone);
    set('profLinkedIn', p.linkedin || p.linkedin_url);
    const skillsEl = document.getElementById('profSkills');
    if (skillsEl) {
      skillsEl.classList.remove('editing');
      const skills = Array.isArray(p.skills) ? p.skills
        : Array.isArray(p.core_skills) ? p.core_skills : null;
      if (skills) {
        skillsEl.innerHTML = skills.length
          ? skills.map(s => `<span class="skill-tag">${this.escapeHtml(s)}</span>`).join('')
          : '<span style="color: var(--text-muted);">—</span>';
      }
    }
  },

  async loadVariants(force) {
    if (this._variantsLoaded && !force) return;
    this._variantsLoaded = true;
    this._note(this.variantsStatusNote, 'Loading CV variants from /api/cv/variants…', false);
    try {
      const data = await JobAgent.api.getCvVariants();
      if (!data || data._unavailable) {
        // Backend endpoint not built yet: keep the static list, quiet note.
        this._note(this.variantsStatusNote, 'Live variants not available yet — showing cached demo.', false);
        return;
      }
      const list = Array.isArray(data) ? data : (data.variants || data.cvs || []);
      if (!list.length) {
        this._note(this.variantsStatusNote, 'No variants returned — showing cached demo.', false);
        return;
      }
      this.renderVariants(list);
      this._note(this.variantsStatusNote, 'Live variants loaded.', false);
    } catch (e) {
      this._note(this.variantsStatusNote,
        'Variants API error: ' + (e && e.message ? e.message : 'unknown error') + ' — showing cached demo.', true);
    }
  },

  renderVariants(list = []) {
    if (!this.variantList) return;
    // Normalize backend shape [{name, tags}] + legacy demo shape
    // [{name/filename/title, meta/description/skills}] into {name, meta}.
    const normalized = (Array.isArray(list) ? list : []).map((v) => {
      if (typeof v === 'string') return { name: v, meta: '' };
      const name = (v && (v.name || v.filename || v.title)) || 'Untitled variant';
      let meta = (v && (v.meta || v.description)) || '';
      if (!meta && v && Array.isArray(v.tags) && v.tags.length) meta = v.tags.join(', ');
      if (!meta && v && Array.isArray(v.skills) && v.skills.length) meta = v.skills.join(', ');
      if (!meta && v && v.primary) meta = 'Primary';
      return { name: String(name), meta: String(meta || '—'), raw: v };
    }).filter(v => v.name);
    if (!normalized.length) return;
    this._variants = normalized;
    // Restore selection: saved > first. First run with no saved value keeps
    // the demo-highlighted first card and persists it.
    let selected = this._savedVariant();
    if (!normalized.some(v => v.name === selected)) {
      selected = normalized[0].name;
      this._saveVariant(selected);
    }
    this.variantList.innerHTML = normalized.map((v) => {
      const isSel = v.name === selected;
      const isDefault = (v.raw && v.raw.default) || v.name === normalized[0].name;
      return `<div class="cv-variant-card${isSel ? ' selected' : ''}" data-variant-name="${this.escapeHtml(v.name)}" title="Click to select this variant for tailoring">`
        + `<div class="variant-info">`
        + `<span class="variant-name">${this.escapeHtml(v.name)}</span>`
        + `<span class="variant-meta">${this.escapeHtml(v.meta || '—')}</span>`
        + `</div>`
        + (isDefault ? '<span class="badge-tag">DEFAULT</span>' : '')
        + (isSel ? '<span class="badge-emerald">SELECTED</span>' : '')
        + `</div>`;
    }).join('');
  },

  addLocalVariant(name, meta) {
    const clean = String(name || '').trim();
    if (!clean) return;
    // Merge with current list (live or demo) so nothing disappears.
    const current = (this._variants && this._variants.length ? this._variants : []).map(v => ({ name: v.name, meta: v.meta, raw: v.raw }));
    if (!current.some(v => v.name === clean)) {
      current.push({ name: clean, meta: meta || 'Added just now • local only', raw: null });
    }
    this._variantsLoaded = true;
    this.renderVariants(current.map(v => v.raw || { name: v.name, meta: v.meta }));
    // renderVariants resets selection to saved; now select the new one.
    this.selectVariant(clean);
    this._note(this.variantsStatusNote, 'Variant added locally — drop the file in cvs/ to persist it server-side.', false);
  },

  runShrinkEngine() {
    // Simulated demo (offline fallback) — renders DYNAMIC preview from the
    // selected job + parsed profile so no hardcoded KoboToolbox/Mubashir
    // fixture is ever shown.
    if (this.shrinkProgressCard) this.shrinkProgressCard.classList.remove('hidden');
    if (this.generatedPreviewCard) this.generatedPreviewCard.classList.add('hidden');

    const step1 = document.getElementById('step1');
    const step2 = document.getElementById('step2');
    const step3 = document.getElementById('step3');

    if (step1) step1.className = 'shrink-step active';
    if (step2) step2.className = 'shrink-step';
    if (step3) step3.className = 'shrink-step';

    setTimeout(() => {
      if (step1) step1.className = 'shrink-step done';
      if (step2) step2.className = 'shrink-step active';
    }, 600);

    setTimeout(() => {
      if (step2) step2.className = 'shrink-step done';
      if (step3) step3.className = 'shrink-step active';
    }, 1300);

    setTimeout(() => {
      if (step3) step3.className = 'shrink-step done';
      if (this.shrinkProgressCard) this.shrinkProgressCard.classList.add('hidden');
      const job = this._selectedJob();
      const prof = this._demoProfile();
      const jobTitle = job ? job.job_title : 'Selected role';
      const company = job ? job.company : '';
      const safe = (s) => String(s || '').replace(/[^\w]+/g, '_').replace(/^_+|_+$/g, '').slice(0, 40) || 'Resume';
      const filename = `${safe(company)}_${safe(jobTitle)}.pdf`;
      const resumeHtml = this._resumeSheetHtml({
        name: prof.name,
        sub: [jobTitle, company, prof.email].filter(Boolean).join(' • '),
        skills: prof.skills, jobTitle, company, demoBadge: true,
      });
      const demoLetter = this._demoCoverText(jobTitle, company);
      const coverHtml = this._coverSheetHtml({ coverText: demoLetter, jobTitle, company, demoBadge: true });
      this.lastResult = {
        fp: 'demo',
        resumeFilename: filename,
        coverFilename: 'Cover_Letter.txt',
        coverText: demoLetter,
        resumeHtml, coverHtml,
      };
      this._showPackageCard({ filename, jobTitle, company, resumeHtml, coverHtml, defaultTab: 'resume' });
      JobAgent.toast.show('Demo package ready (API unreachable — live data will replace this).');
    }, 2000);
  },

  triggerDownload(filename, content) {
    const blob = new Blob([content], { type: 'text/plain;charset=utf-8' });
    const url = URL.createObjectURL(blob);
    const link = document.createElement('a');
    link.href = url;
    link.download = filename;
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
    URL.revokeObjectURL(url);
    JobAgent.toast.show(`Download started: ${filename}`);
  }
};
