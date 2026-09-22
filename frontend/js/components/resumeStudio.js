/**
 * RESUMESTUDIO.JS — Drag & Drop CV Upload, Parsed Profile & 3-Pass ATS Shrink
 */

window.JobAgent = window.JobAgent || {};

JobAgent.resumeStudio = {
  init() {
    this.cvDropzone = document.getElementById('cvDropzone');
    this.cvFileInput = document.getElementById('cvFileInput');
    this.dropzoneActiveFile = document.getElementById('dropzoneActiveFile');
    this.btnGenerateTailored = document.getElementById('btnGenerateTailored');
    this.shrinkProgressCard = document.getElementById('shrinkProgressCard');
    this.generatedPreviewCard = document.getElementById('generatedPreviewCard');
    this.tailorJobSelect = document.getElementById('tailorJobSelect');

    this.btnDownloadResume = document.getElementById('btnDownloadResume');
    this.btnDownloadCoverLetter = document.getElementById('btnDownloadCoverLetter');
    this.btnDownloadPackage = document.getElementById('btnDownloadPackage');

    this.bindEvents();
  },

  bindEvents() {
    // Dropzone click & drag events
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

    // Tailored Resume Generation simulation (3-Pass Shrink)
    if (this.btnGenerateTailored) {
      this.btnGenerateTailored.addEventListener('click', () => {
        this.runShrinkEngine();
      });
    }

    // Download handlers
    if (this.btnDownloadResume) {
      this.btnDownloadResume.addEventListener('click', () => {
        this.triggerDownload('Mubashir_Tailored_Resume.pdf', '%PDF-1.4 ATS Tailored 1-page resume for KoboToolbox');
      });
    }

    if (this.btnDownloadCoverLetter) {
      this.btnDownloadCoverLetter.addEventListener('click', () => {
        this.triggerDownload('Cover_Letter.txt', 'Dear Hiring Team,\n\nI am writing to express my strong interest in the Frontend Developer position at KoboToolbox...');
      });
    }

    if (this.btnDownloadPackage) {
      this.btnDownloadPackage.addEventListener('click', () => {
        this.triggerDownload('Apply_Package_KoboToolbox.zip', 'PK [Mock ZIP Package containing resume.pdf, cover_letter.txt, form_data.json]');
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

  runShrinkEngine() {
    this.shrinkProgressCard.classList.remove('hidden');
    this.generatedPreviewCard.classList.add('hidden');

    const step1 = document.getElementById('step1');
    const step2 = document.getElementById('step2');
    const step3 = document.getElementById('step3');

    step1.className = 'shrink-step active';
    step2.className = 'shrink-step';
    step3.className = 'shrink-step';

    setTimeout(() => {
      step1.className = 'shrink-step done';
      step2.className = 'shrink-step active';
    }, 600);

    setTimeout(() => {
      step2.className = 'shrink-step done';
      step3.className = 'shrink-step active';
    }, 1300);

    setTimeout(() => {
      step3.className = 'shrink-step done';
      this.shrinkProgressCard.classList.add('hidden');
      this.generatedPreviewCard.classList.remove('hidden');
      JobAgent.toast.show('3-Pass ATS 1-page resume + cover letter generated successfully!');
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
