/**
 * AI Transcriptor — Frontend Application
 * by Shivam Kole
 * ═══════════════════════════════════════════
 */

// ─── State ────────────────────────────────────────────────────────
const AppState = {
    ws: null,
    wsRetries: 0,
    currentTab: 'transcription',
    jobs: new Map(),
    errors: [],
    settings: {},
    history: [],
    schedules: [],
    errorConsoleExpanded: false
};

// ─── Initialize ───────────────────────────────────────────────────
document.addEventListener('DOMContentLoaded', () => {
    initWebSocket();
    initNavigation();
    initTranscription();
    initMP3Tools();
    initAPIKeys();
    initScheduler();
    initFeedback();
    initErrorConsole();
    loadSettings();
    loadHistory();
    loadSystemInfo();
});

// ─── WebSocket ────────────────────────────────────────────────────
function initWebSocket() {
    const protocol = location.protocol === 'https:' ? 'wss' : 'ws';
    const wsUrl = `${protocol}://${location.host}/ws`;

    AppState.ws = new WebSocket(wsUrl);

    AppState.ws.onopen = () => {
        AppState.wsRetries = 0;
        updateConnectionStatus(true);
        console.log('🟢 WebSocket connected');
    };

    AppState.ws.onmessage = (event) => {
        try {
            const msg = JSON.parse(event.data);
            handleWSMessage(msg);
        } catch (e) {
            console.error('WS parse error:', e);
        }
    };

    AppState.ws.onclose = () => {
        updateConnectionStatus(false);
        if (AppState.wsRetries < 10) {
            AppState.wsRetries++;
            setTimeout(initWebSocket, 2000 * AppState.wsRetries);
        }
    };

    AppState.ws.onerror = () => {
        console.error('WebSocket error');
    };

    // Keep alive
    setInterval(() => {
        if (AppState.ws?.readyState === WebSocket.OPEN) {
            AppState.ws.send(JSON.stringify({ type: 'ping' }));
        }
    }, 30000);
}

function updateConnectionStatus(connected) {
    const dot = document.getElementById('statusDot');
    const text = document.getElementById('statusText');
    if (dot && text) {
        dot.style.background = connected ? 'var(--success)' : 'var(--error)';
        dot.style.boxShadow = connected ? '0 0 12px var(--success-glow)' : '0 0 12px var(--error-glow)';
        text.textContent = connected ? 'Connected' : 'Reconnecting...';
    }
}

function handleWSMessage(msg) {
    switch (msg.type) {
        case 'log':
            addJobLog(msg.job_id, msg.message);
            addProcessLine(msg.message, 'info');
            break;
        case 'progress':
            updateJobProgress(msg.job_id, msg.progress, msg.message);
            break;
        case 'complete':
            completeJob(msg.job_id, msg.data);
            showToast('success', msg.message);
            loadHistory();
            break;
        case 'error':
            addJobLog(msg.job_id, msg.message);
            addProcessLine(msg.message, 'error');
            addError(msg.message, msg.fix);
            showToast('error', msg.message);
            break;
        case 'pong':
            break;
    }
}

// ─── Navigation ───────────────────────────────────────────────────
function initNavigation() {
    document.querySelectorAll('.nav-tab').forEach(tab => {
        tab.addEventListener('click', () => {
            const target = tab.dataset.tab;
            switchTab(target);
        });
    });
}

function switchTab(tabId) {
    AppState.currentTab = tabId;

    // Update nav tabs
    document.querySelectorAll('.nav-tab').forEach(t => t.classList.remove('active'));
    document.querySelector(`[data-tab="${tabId}"]`)?.classList.add('active');

    // Update page sections
    document.querySelectorAll('.page-section').forEach(s => s.classList.remove('active'));
    document.getElementById(`section-${tabId}`)?.classList.add('active');
}

// ─── Transcription ────────────────────────────────────────────────
function initTranscription() {
    // Input method switching
    document.querySelectorAll('.input-method-btn').forEach(btn => {
        btn.addEventListener('click', () => {
            const method = btn.dataset.method;
            document.querySelectorAll('.input-method-btn').forEach(b => b.classList.remove('active'));
            btn.classList.add('active');
            document.querySelectorAll('.input-panel').forEach(p => p.classList.remove('active'));
            document.getElementById(`panel-${method}`)?.classList.add('active');
        });
    });

    // URL form
    document.getElementById('urlForm')?.addEventListener('submit', async (e) => {
        e.preventDefault();
        const url = document.getElementById('inputUrl').value.trim();
        const company = document.getElementById('inputCompany').value.trim() || 'Meeting';

        if (!url) {
            showToast('error', 'Please enter a URL');
            return;
        }

        const btn = e.target.querySelector('button[type="submit"]');
        btn.disabled = true;
        btn.innerHTML = '<span class="spinner"></span> Starting...';

        try {
            const res = await fetch('/api/transcribe/url', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ url, company_name: company })
            });
            const data = await res.json();

            if (data.job_id) {
                createJobCard(data.job_id, company, url);
                showToast('info', `Job started: ${company}`);
                addProcessLine(`🚀 Job ${data.job_id} started for: ${company}`, 'info');
            }
        } catch (err) {
            showToast('error', `Failed to start: ${err.message}`);
            addError(`Failed to start transcription: ${err.message}`, 'Check if the server is running and try again.');
        }

        btn.disabled = false;
        btn.innerHTML = '🎯 Start Transcription';
    });

    // File upload
    const uploadArea = document.getElementById('uploadArea');
    const fileInput = document.getElementById('fileInput');

    if (uploadArea && fileInput) {
        uploadArea.addEventListener('click', () => fileInput.click());
        uploadArea.addEventListener('dragover', (e) => {
            e.preventDefault();
            uploadArea.classList.add('dragging');
        });
        uploadArea.addEventListener('dragleave', () => uploadArea.classList.remove('dragging'));
        uploadArea.addEventListener('drop', (e) => {
            e.preventDefault();
            uploadArea.classList.remove('dragging');
            handleFileUpload(e.dataTransfer.files);
        });
        fileInput.addEventListener('change', () => handleFileUpload(fileInput.files));
    }
}

async function handleFileUpload(files) {
    if (!files || files.length === 0) return;

    const company = document.getElementById('uploadCompany')?.value.trim() || 'Meeting';

    for (const file of files) {
        const formData = new FormData();
        formData.append('file', file);
        formData.append('company_name', company);

        try {
            const res = await fetch('/api/transcribe/upload', {
                method: 'POST',
                body: formData
            });
            const data = await res.json();

            if (data.job_id) {
                createJobCard(data.job_id, company, file.name);
                showToast('info', `Upload started: ${file.name}`);
                addProcessLine(`📤 Uploaded: ${file.name}`, 'info');
            }
        } catch (err) {
            showToast('error', `Upload failed: ${err.message}`);
            addError(`Upload failed: ${err.message}`, 'Check file format. Supported: MP3, WAV, M4A, MP4, WebM');
        }
    }
}

let jobStartedAt = new Map();

// ─── Job Cards ────────────────────────────────────────────────────
function createJobCard(jobId, title, source) {
    const queueList = document.getElementById('queueList');
    if (!queueList) return;

    const emptyState = queueList.querySelector('.empty-state');
    if (emptyState) emptyState.remove();

    const card = document.createElement('div');
    card.className = 'job-card';
    card.id = `job-${jobId}`;
    card.innerHTML = `
        <div class="job-header">
            <div>
                <div class="job-title">${escapeHtml(title)}</div>
                <div style="font-size: 11px; color: var(--text-muted); margin-top: 2px;" class="truncate">${escapeHtml(source)}</div>
            </div>
            <div style="display: flex; gap: 8px; align-items: center;">
                <span class="job-status processing">Processing</span>
                <button class="btn btn-sm btn-danger cancel-btn" onclick="cancelJob('${jobId}')" style="padding: 4px 8px; font-size: 11px; border-radius: 4px;">⏸ Force Stop</button>
            </div>
        </div>
        <div class="progress-bar-container">
            <div class="progress-bar" id="progress-${jobId}" style="width: 0%"></div>
        </div>
        <div class="progress-text">
            <span id="progress-text-${jobId}">Starting...</span>
            <span id="progress-pct-${jobId}">0%</span>
        </div>
        <div class="job-log" id="log-${jobId}"></div>
    `;

    queueList.prepend(card);
    AppState.jobs.set(jobId, { title, source, status: 'processing', progress: 0 });
    jobStartedAt.set(jobId, Date.now());
}

function cancelJob(jobId) {
    if (ws && ws.readyState === WebSocket.OPEN) {
        ws.send(JSON.stringify({ type: "cancel", job_id: jobId }));
        const card = document.getElementById(`job-${jobId}`);
        if (card) {
            const btn = card.querySelector('.cancel-btn');
            if (btn) btn.remove();
            const status = card.querySelector('.job-status');
            if (status) {
                status.className = 'job-status error';
                status.textContent = 'Cancelled';
            }
            updateJobProgress(jobId, 0, '❌ Force Stopped by User');
            addJobLog(jobId, 'Job cancelled via UI force stop.');
        }
    }
}

function updateJobProgress(jobId, progress, message) {
    const bar = document.getElementById(`progress-${jobId}`);
    const text = document.getElementById(`progress-text-${jobId}`);
    const pct = document.getElementById(`progress-pct-${jobId}`);

    if (bar) bar.style.width = `${progress}%`;
    if (pct) pct.textContent = `${progress}%`;
    if (text && message) {
        let etaMsg = "";
        if (progress > 5 && progress < 100 && jobStartedAt.has(jobId)) {
            let elapsed = (Date.now() - jobStartedAt.get(jobId)) / 1000;
            let rate = progress / elapsed;
            let remaining = (100 - progress) / rate;
            if (remaining > 0) {
                let m = Math.floor(remaining / 60);
                let s = Math.floor(remaining % 60);
                etaMsg = ` (ETA: ${m}m ${s}s)`;
            }
        }
        text.textContent = message + etaMsg;
    }
}

function addJobLog(jobId, message) {
    const log = document.getElementById(`log-${jobId}`);
    if (!log) return;

    const entry = document.createElement('div');
    entry.className = 'log-entry';
    entry.textContent = `[${new Date().toLocaleTimeString()}] ${message}`;
    log.appendChild(entry);
    log.scrollTop = log.scrollHeight;
}

function completeJob(jobId, data) {
    const card = document.getElementById(`job-${jobId}`);
    if (!card) return;

    const status = card.querySelector('.job-status');
    if (status) {
        status.className = 'job-status completed';
        status.textContent = 'Completed';
    }

    const btn = card.querySelector('.cancel-btn');
    if (btn) btn.remove();

    updateJobProgress(jobId, 100, `✅ Done in ${data?.processing_time || 0}s`);

    // Add download links
    const log = document.getElementById(`log-${jobId}`);
    if (log && data) {
        const links = document.createElement('div');
        links.style.cssText = 'margin-top: 8px; display: flex; gap: 8px;';
        links.innerHTML = `
            <button class="btn btn-sm btn-primary" onclick="openFile('${escapeHtml(data.txt_path || '')}')">📄 TXT</button>
            <button class="btn btn-sm btn-primary" onclick="openFile('${escapeHtml(data.pdf_path || '')}')">📕 PDF</button>
            <button class="btn btn-sm btn-secondary" onclick="openFile('${escapeHtml(data.mp3_path || '')}')">🎵 MP3</button>
        `;
        log.after(links);
    }

    AppState.jobs.set(jobId, { ...AppState.jobs.get(jobId), status: 'completed' });
}

function openFile(path) {
    if (path) {
        showToast('info', `File saved at: ${path}`);
    }
}

// ─── MP3 Tools ────────────────────────────────────────────────────
function initMP3Tools() {
    // Compress
    document.getElementById('compressForm')?.addEventListener('submit', async (e) => {
        e.preventDefault();
        const fileInput = document.getElementById('compressFile');
        const bitrate = document.getElementById('compressBitrate')?.value || '128k';

        if (!fileInput?.files?.length) {
            showToast('error', 'Please select a file');
            return;
        }

        const btn = e.target.querySelector('button[type="submit"]');
        btn.disabled = true;
        btn.innerHTML = '<span class="spinner"></span> Compressing...';

        const formData = new FormData();
        formData.append('file', fileInput.files[0]);
        formData.append('bitrate', bitrate);

        try {
            const res = await fetch('/api/mp3/compress', { method: 'POST', body: formData });
            const data = await res.json();
            showToast('success', `Compressed: ${data.original_size_mb}MB → ${data.compressed_size_mb}MB (${data.reduction_pct}% reduction)`);
            document.getElementById('compressResult').innerHTML = `
                <div class="card mt-4" style="background: var(--bg-secondary);">
                    <p>📊 <strong>Original:</strong> ${data.original_size_mb} MB</p>
                    <p>📦 <strong>Compressed:</strong> ${data.compressed_size_mb} MB</p>
                    <p>📉 <strong>Reduction:</strong> ${data.reduction_pct}%</p>
                    <p class="mono" style="font-size: 11px; color: var(--text-muted); margin-top: 8px;">Saved to: ${data.output_path}</p>
                </div>
            `;
        } catch (err) {
            showToast('error', `Compression failed: ${err.message}`);
        }

        btn.disabled = false;
        btn.innerHTML = '🗜️ Compress';
    });

    // Merge
    document.getElementById('mergeForm')?.addEventListener('submit', async (e) => {
        e.preventDefault();
        const fileInput = document.getElementById('mergeFiles');

        if (!fileInput?.files?.length || fileInput.files.length < 2) {
            showToast('error', 'Please select at least 2 files to merge');
            return;
        }

        const btn = e.target.querySelector('button[type="submit"]');
        btn.disabled = true;
        btn.innerHTML = '<span class="spinner"></span> Merging...';

        const formData = new FormData();
        for (const file of fileInput.files) {
            formData.append('files', file);
        }

        try {
            const res = await fetch('/api/mp3/merge', { method: 'POST', body: formData });
            const data = await res.json();
            showToast('success', `Merged ${fileInput.files.length} files (${data.duration_seconds}s)`);
        } catch (err) {
            showToast('error', `Merge failed: ${err.message}`);
        }

        btn.disabled = false;
        btn.innerHTML = '🔗 Merge Files';
    });

    // Split
    document.getElementById('splitForm')?.addEventListener('submit', async (e) => {
        e.preventDefault();
        const fileInput = document.getElementById('splitFile');
        const minutes = document.getElementById('splitMinutes')?.value || 10;

        if (!fileInput?.files?.length) {
            showToast('error', 'Please select a file');
            return;
        }

        const btn = e.target.querySelector('button[type="submit"]');
        btn.disabled = true;
        btn.innerHTML = '<span class="spinner"></span> Splitting...';

        const formData = new FormData();
        formData.append('file', fileInput.files[0]);
        formData.append('segment_minutes', minutes);

        try {
            const res = await fetch('/api/mp3/split', { method: 'POST', body: formData });
            const data = await res.json();
            showToast('success', `Split into ${data.parts} parts`);
        } catch (err) {
            showToast('error', `Split failed: ${err.message}`);
        }

        btn.disabled = false;
        btn.innerHTML = '✂️ Split File';
    });

    // Convert
    document.getElementById('convertForm')?.addEventListener('submit', async (e) => {
        e.preventDefault();
        const fileInput = document.getElementById('convertFile');
        const bitrate = document.getElementById('convertBitrate')?.value || '128k';

        if (!fileInput?.files?.length) {
            showToast('error', 'Please select a file');
            return;
        }

        const btn = e.target.querySelector('button[type="submit"]');
        btn.disabled = true;
        btn.innerHTML = '<span class="spinner"></span> Converting...';

        const formData = new FormData();
        formData.append('file', fileInput.files[0]);
        formData.append('bitrate', bitrate);

        try {
            const res = await fetch('/api/mp3/convert', { method: 'POST', body: formData });
            const data = await res.json();
            showToast('success', `Converted to MP3 (${data.size_mb}MB)`);
        } catch (err) {
            showToast('error', `Convert failed: ${err.message}`);
        }

        btn.disabled = false;
        btn.innerHTML = '🔄 Convert to MP3';
    });

    // ─── Link to MP3 ────────────────────────────────────────────────
    document.getElementById('linkForm')?.addEventListener('submit', async (e) => {
        e.preventDefault();
        const urlInput = document.getElementById('linkUrl').value;
        const bitrate = document.getElementById('linkBitrate')?.value || '128k';

        if (!urlInput) {
            showToast('error', 'Please enter a URL');
            return;
        }

        const btn = e.target.querySelector('button[type="submit"]');
        btn.disabled = true;
        btn.innerHTML = '<span class="spinner"></span> Downloading...';

        const formData = new FormData();
        formData.append('url', urlInput);
        formData.append('bitrate', bitrate);

        try {
            const res = await fetch('/api/mp3/from-link', { method: 'POST', body: formData });
            const data = await res.json();

            if (res.ok) {
                showToast('success', `Saved! Extracted to MP3 (${data.size_mb}MB)`);
                document.getElementById('linkUrl').value = '';
            } else {
                throw new Error(data.detail || data.error || 'Extraction failed');
            }
        } catch (err) {
            showToast('error', `Download failed: ${err.message}`);
        }

        btn.disabled = false;
        btn.innerHTML = '🌐 Download & Compress';
    });
}

// ─── API Keys ─────────────────────────────────────────────────────
function initAPIKeys() {
    document.getElementById('addPaidKey')?.addEventListener('click', () => addAPIKeys('paid'));
    document.getElementById('addFreeKey')?.addEventListener('click', () => addAPIKeys('free'));
}

async function addAPIKeys(type) {
    const inputId = type === 'paid' ? 'paidKeyInput' : 'freeKeyInput';
    const input = document.getElementById(inputId);
    const rawValue = input?.value.trim();

    if (!rawValue) {
        showToast('error', 'Please enter one or more API keys');
        return;
    }

    // Parse multiple keys: split by newlines, commas, semicolons, or spaces between keys
    const rawKeys = rawValue
        .split(/[\n,;]+/)
        .map(k => k.trim())
        .filter(k => k.length > 10 && k.startsWith('gsk_'));

    if (rawKeys.length === 0) {
        // Maybe it's a single key without gsk_ prefix — try the raw value
        if (rawValue.length > 10) {
            rawKeys.push(rawValue);
        } else {
            showToast('error', 'No valid API keys found. Keys should start with gsk_');
            return;
        }
    }

    const settingsKey = type === 'paid' ? 'paid_api_keys' : 'free_api_keys';
    const existingKeys = AppState.settings[settingsKey] || [];
    let added = 0;
    let skipped = 0;
    let failed = 0;

    showToast('info', `🔍 Processing ${rawKeys.length} key(s)...`);

    for (const key of rawKeys) {
        // Skip duplicates
        if (existingKeys.includes(key)) {
            skipped++;
            continue;
        }

        // Quick validation
        try {
            const testRes = await fetch('/api/settings/test-key', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ key })
            });
            const testData = await testRes.json();

            if (testData.status === 'valid') {
                existingKeys.push(key);
                added++;
            } else {
                failed++;
            }
        } catch (err) {
            // Network error — add anyway
            existingKeys.push(key);
            added++;
        }
    }

    AppState.settings[settingsKey] = existingKeys;

    // Save to local storage for persistence (12 hours)
    localStorage.setItem('cached_api_keys', JSON.stringify({
        paid: AppState.settings.paid_api_keys || [],
        free: AppState.settings.free_api_keys || [],
        timestamp: Date.now()
    }));

    await saveSettings();
    renderAPIKeys();
    input.value = '';
    updateKeyCount();
    autoAdjustSettings();

    // Summary toast
    const parts = [];
    if (added > 0) parts.push(`✅ ${added} added`);
    if (skipped > 0) parts.push(`⏭️ ${skipped} duplicates skipped`);
    if (failed > 0) parts.push(`❌ ${failed} invalid`);
    showToast(added > 0 ? 'success' : 'warning', parts.join(' • '));
}

async function removeAPIKey(type, index) {
    const settingsKey = type === 'paid' ? 'paid_api_keys' : 'free_api_keys';
    const keys = AppState.settings[settingsKey] || [];
    keys.splice(index, 1);
    AppState.settings[settingsKey] = keys;

    // Update local storage persistence
    localStorage.setItem('cached_api_keys', JSON.stringify({
        paid: AppState.settings.paid_api_keys || [],
        free: AppState.settings.free_api_keys || [],
        timestamp: Date.now()
    }));

    await saveSettings();
    renderAPIKeys();
    updateKeyCount();
    autoAdjustSettings();
    showToast('info', 'API key removed');
}

function renderAPIKeys() {
    const paidList = document.getElementById('paidKeysList');
    const freeList = document.getElementById('freeKeysList');

    if (paidList) {
        const paidKeys = AppState.settings.paid_api_keys || [];
        paidList.innerHTML = paidKeys.length ? paidKeys.map((key, i) => `
            <li class="key-item">
                <span class="key-value">${maskKey(key)}</span>
                <div class="key-actions">
                    <button class="btn btn-sm btn-secondary" onclick="testKey('${escapeHtml(key)}')" title="Test Key">🧪</button>
                    <button class="btn btn-sm btn-danger" onclick="removeAPIKey('paid', ${i})" title="Remove">✕</button>
                </div>
            </li>
        `).join('') : '<div class="empty-state"><div class="empty-state-text">No paid keys added</div></div>';
    }

    if (freeList) {
        const freeKeys = AppState.settings.free_api_keys || [];
        freeList.innerHTML = freeKeys.length ? freeKeys.map((key, i) => `
            <li class="key-item">
                <span class="key-value">${maskKey(key)}</span>
                <div class="key-actions">
                    <button class="btn btn-sm btn-secondary" onclick="testKey('${escapeHtml(key)}')" title="Test Key">🧪</button>
                    <button class="btn btn-sm btn-danger" onclick="removeAPIKey('free', ${i})" title="Remove">✕</button>
                </div>
            </li>
        `).join('') : '<div class="empty-state"><div class="empty-state-text">No free/Groq keys added</div></div>';
    }
}

async function testKey(key) {
    showToast('info', '🔍 Testing key...');
    try {
        const res = await fetch('/api/settings/test-key', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ key })
        });
        const data = await res.json();
        if (data.status === 'valid') {
            showToast('success', `✅ Key is valid! Models: ${data.models?.slice(0, 3).join(', ')}...`);
        } else {
            showToast('error', `❌ Key invalid: ${data.error}`);
        }
    } catch (err) {
        showToast('error', `Test failed: ${err.message}`);
    }
}

function maskKey(key) {
    if (key.length <= 12) return '****';
    return key.substring(0, 8) + '••••••••' + key.substring(key.length - 4);
}

function updateKeyCount() {
    const total = (AppState.settings.paid_api_keys?.length || 0) + (AppState.settings.free_api_keys?.length || 0);
    const el = document.getElementById('keyCount');
    if (el) el.textContent = `🔑 ${total} key${total !== 1 ? 's' : ''}`;

    const dashEl = document.getElementById('stat-keys');
    if (dashEl) dashEl.textContent = total;
}

// ─── Settings ─────────────────────────────────────────────────────
async function loadSettings() {
    try {
        const res = await fetch('/api/settings');
        const serverSettings = await res.json();

        let shouldSaveSettings = false;

        // ─── LocalStorage Key Recovery (12 Hours) ───
        const cachedStr = localStorage.getItem('cached_api_keys');
        if (cachedStr) {
            try {
                const cache = JSON.parse(cachedStr);
                const TWELVE_HOURS = 12 * 60 * 60 * 1000;

                if (Date.now() - cache.timestamp <= TWELVE_HOURS) {
                    // Cache is valid. Forcefully restore these keys, merging with any existing backend keys
                    const currentPaid = serverSettings.paid_api_keys || [];
                    const currentFree = serverSettings.free_api_keys || [];

                    if (cache.paid && cache.paid.length > 0) {
                        serverSettings.paid_api_keys = Array.from(new Set([...currentPaid, ...cache.paid]));
                        shouldSaveSettings = true;
                    }
                    if (cache.free && cache.free.length > 0) {
                        serverSettings.free_api_keys = Array.from(new Set([...currentFree, ...cache.free]));
                        shouldSaveSettings = true;
                    }
                } else {
                    // Expired
                    localStorage.removeItem('cached_api_keys');
                }
            } catch (e) {
                console.warn('Could not parse cached keys', e);
            }
        }

        AppState.settings = serverSettings;

        if (shouldSaveSettings) {
            console.log("Recovered keys from localStorage, saving to server...");
            await saveSettings();
        }

        renderAPIKeys();
        updateKeyCount();
        applySettings();
    } catch (err) {
        console.error('Failed to load settings:', err);
    }
}

async function saveSettings() {
    try {
        await fetch('/api/settings', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(AppState.settings)
        });
    } catch (err) {
        showToast('error', `Failed to save settings: ${err.message}`);
    }
}

function applySettings() {
    // Apply any UI settings
    const chunkInput = document.getElementById('settingChunkDuration');
    if (chunkInput) chunkInput.value = AppState.settings.chunk_duration_minutes || 10;

    const workersInput = document.getElementById('settingMaxWorkers');
    if (workersInput) workersInput.value = AppState.settings.max_parallel_workers || 20;

    const modelSelect = document.getElementById('settingModel');
    if (modelSelect) modelSelect.value = AppState.settings.default_model || 'whisper-large-v3';

    const dialectSelect = document.getElementById('settingDialect');
    if (dialectSelect) dialectSelect.value = AppState.settings.english_dialect || 'indian';

    const cookiesInput = document.getElementById('settingYoutubeCookies');
    if (cookiesInput) cookiesInput.value = AppState.settings.youtube_cookies || '';
}

async function updateSetting(key, value) {
    AppState.settings[key] = value;
    await saveSettings();
    showToast('info', 'Setting updated');
}

// ─── History ──────────────────────────────────────────────────────
async function loadHistory() {
    try {
        const res = await fetch('/api/history');
        AppState.history = await res.json();
        renderHistory();
    } catch (err) {
        console.error('Failed to load history:', err);
    }
}

function renderHistory() {
    const tbody = document.getElementById('historyBody');
    if (!tbody) return;

    if (!AppState.history.length) {
        tbody.innerHTML = `
            <tr><td colspan="6" class="text-center" style="padding: 40px; color: var(--text-muted);">
                No transcription history yet. Start your first transcription!
            </td></tr>
        `;
        return;
    }

    tbody.innerHTML = AppState.history.map(item => `
        <tr>
            <td><span style="font-weight: 600; color: var(--text-primary);">${escapeHtml(item.company_name || 'Meeting')}</span></td>
            <td>${formatDate(item.timestamp)}</td>
            <td>${item.word_count || 0} words</td>
            <td>${item.processing_time || 0}s</td>
            <td><span class="job-status ${item.status === 'completed' ? 'completed' : 'error'}">${item.status || 'unknown'}</span></td>
            <td>
                <button class="btn btn-sm btn-secondary" onclick="openFile('${escapeHtml(item.txt_path || '')}')">📄</button>
                <button class="btn btn-sm btn-secondary" onclick="openFile('${escapeHtml(item.pdf_path || '')}')">📕</button>
            </td>
        </tr>
    `).join('');
}

async function clearHistory() {
    if (!confirm('Clear all transcription history?')) return;
    try {
        await fetch('/api/history', { method: 'DELETE' });
        AppState.history = [];
        renderHistory();
        showToast('info', 'History cleared');
    } catch (err) {
        showToast('error', `Failed to clear: ${err.message}`);
    }
}

// ─── Scheduler ────────────────────────────────────────────────────
function initScheduler() {
    document.getElementById('scheduleForm')?.addEventListener('submit', async (e) => {
        e.preventDefault();

        const url = document.getElementById('scheduleUrl')?.value.trim();
        const company = document.getElementById('scheduleCompany')?.value.trim() || 'Scheduled Meeting';
        const datetime = document.getElementById('scheduleDatetime')?.value;
        const repeat = document.getElementById('scheduleRepeat')?.value || 'none';

        if (!url || !datetime) {
            showToast('error', 'URL and date/time are required');
            return;
        }

        try {
            const res = await fetch('/api/schedules', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ url, company_name: company, scheduled_time: datetime, repeat })
            });
            const data = await res.json();
            loadSchedules();
            showToast('success', `Scheduled: ${company}`);
            e.target.reset();
        } catch (err) {
            showToast('error', `Schedule failed: ${err.message}`);
        }
    });

    loadSchedules();
}

async function loadSchedules() {
    try {
        const res = await fetch('/api/schedules');
        AppState.schedules = await res.json();
        renderSchedules();
    } catch (err) {
        console.error('Failed to load schedules:', err);
    }
}

function renderSchedules() {
    const list = document.getElementById('scheduleList');
    if (!list) return;

    if (!AppState.schedules.length) {
        list.innerHTML = '<div class="empty-state"><div class="empty-state-icon">📅</div><div class="empty-state-text">No scheduled tasks</div></div>';
        return;
    }

    list.innerHTML = AppState.schedules.map(s => `
        <div class="schedule-card">
            <div class="flex justify-between items-center">
                <div>
                    <div class="schedule-time">📅 ${formatDate(s.scheduled_time)} ${s.repeat !== 'none' ? `(${s.repeat})` : ''}</div>
                    <div style="font-weight: 600; margin-top: 4px;">${escapeHtml(s.company_name)}</div>
                    <div class="schedule-url">${escapeHtml(s.url)}</div>
                </div>
                <div class="flex gap-4 items-center">
                    <span class="job-status ${s.status === 'completed' ? 'completed' : 'processing'}">${s.status}</span>
                    <button class="btn btn-sm btn-danger" onclick="removeSchedule('${s.id}')">✕</button>
                </div>
            </div>
        </div>
    `).join('');
}

async function removeSchedule(id) {
    try {
        await fetch(`/api/schedules/${id}`, { method: 'DELETE' });
        loadSchedules();
        showToast('info', 'Schedule removed');
    } catch (err) {
        showToast('error', `Failed to remove: ${err.message}`);
    }
}

// ─── Feedback ─────────────────────────────────────────────────────
function initFeedback() {
    document.getElementById('feedbackForm')?.addEventListener('submit', async (e) => {
        e.preventDefault();
        const msg = document.getElementById('feedbackMessage')?.value.trim();

        if (!msg) {
            showToast('error', 'Please enter your feedback');
            return;
        }

        try {
            const res = await fetch('/api/feedback', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ message: msg })
            });
            const data = await res.json();
            showToast('success', data.message || 'Feedback sent!');
            document.getElementById('feedbackMessage').value = '';
        } catch (err) {
            showToast('error', `Failed to send: ${err.message}`);
        }
    });
}

// ─── Error Console ────────────────────────────────────────────────
function initErrorConsole() {
    document.getElementById('errorConsoleToggle')?.addEventListener('click', () => {
        const console = document.getElementById('errorConsole');
        AppState.errorConsoleExpanded = !AppState.errorConsoleExpanded;
        console.className = `error-console ${AppState.errorConsoleExpanded ? 'expanded' : 'collapsed'}`;
    });
}

function addError(message, fix) {
    AppState.errors.push({ message, fix, time: new Date() });
    renderErrors();
}

function renderErrors() {
    const body = document.getElementById('errorBody');
    const badge = document.getElementById('errorBadge');

    if (badge) {
        badge.textContent = AppState.errors.length;
        badge.style.display = AppState.errors.length ? 'inline' : 'none';
    }

    if (body) {
        body.innerHTML = AppState.errors.slice(-20).reverse().map(err => `
            <div class="error-entry">
                <div>${escapeHtml(err.message)}</div>
                ${err.fix ? `<div class="error-fix">💡 Fix: ${escapeHtml(err.fix)}</div>` : ''}
            </div>
        `).join('');
    }
}

// ─── System Info ──────────────────────────────────────────────────
async function loadSystemInfo() {
    try {
        const res = await fetch('/api/system');
        const data = await res.json();

        const el = document.getElementById('systemInfo');
        if (el) {
            el.innerHTML = `
                <div class="grid-4">
                    <div class="stat-card">
                        <div class="stat-value">${data.total_api_keys}</div>
                        <div class="stat-label">API Keys</div>
                    </div>
                    <div class="stat-card">
                        <div class="stat-value">${data.history_count}</div>
                        <div class="stat-label">Transcriptions</div>
                    </div>
                    <div class="stat-card">
                        <div class="stat-value">${data.ffmpeg_available ? '✅' : '❌'}</div>
                        <div class="stat-label">FFmpeg</div>
                    </div>
                    <div class="stat-card">
                        <div class="stat-value">${data.ssl_cert_available ? '✅' : '❌'}</div>
                        <div class="stat-label">SSL Cert</div>
                    </div>
                </div>
            `;
        }
    } catch (err) {
        console.error('Failed to load system info:', err);
    }
}

// ─── Process Display ──────────────────────────────────────────────
function addProcessLine(message, type = 'info') {
    const display = document.getElementById('processDisplay');
    if (!display) return;

    const line = document.createElement('div');
    line.className = `process-line ${type}`;
    line.textContent = `[${new Date().toLocaleTimeString()}] ${message}`;
    display.appendChild(line);
    display.scrollTop = display.scrollHeight;

    // Keep only last 100 lines
    while (display.children.length > 100) {
        display.removeChild(display.firstChild);
    }
}

// ─── Toast Notifications ──────────────────────────────────────────
function showToast(type, message) {
    const container = document.getElementById('toastContainer');
    if (!container) return;

    const icons = { success: '✅', error: '❌', warning: '⚠️', info: 'ℹ️' };

    const toast = document.createElement('div');
    toast.className = `toast ${type}`;
    toast.innerHTML = `
        <span class="toast-icon">${icons[type] || 'ℹ️'}</span>
        <span class="toast-message">${escapeHtml(message)}</span>
        <button class="toast-close" onclick="this.parentElement.remove()">✕</button>
    `;

    container.appendChild(toast);

    setTimeout(() => {
        toast.style.opacity = '0';
        toast.style.transform = 'translateX(100%)';
        toast.style.transition = 'all 0.3s ease';
        setTimeout(() => toast.remove(), 300);
    }, 5000);
}

// ─── Utility Functions ────────────────────────────────────────────
function escapeHtml(str) {
    if (!str) return '';
    const div = document.createElement('div');
    div.textContent = str;
    return div.innerHTML;
}

function formatDate(dateStr) {
    if (!dateStr) return 'N/A';
    try {
        const d = new Date(dateStr);
        return d.toLocaleDateString('en-US', {
            month: 'short', day: 'numeric', year: 'numeric',
            hour: '2-digit', minute: '2-digit'
        });
    } catch {
        return dateStr;
    }
}

// ─── Theme Toggle ─────────────────────────────────────────────────
function toggleTheme() {
    const html = document.documentElement;
    const current = html.getAttribute('data-theme');
    const newTheme = current === 'light' ? 'dark' : 'light';
    html.setAttribute('data-theme', newTheme);
    localStorage.setItem('ai-transcriptor-theme', newTheme);

    const btn = document.getElementById('themeToggle');
    if (btn) btn.textContent = newTheme === 'light' ? '☀️' : '🌙';

    // Update background canvas opacity for light mode
    const canvas = document.getElementById('bgCanvas');
    if (canvas) canvas.style.opacity = newTheme === 'light' ? '0.5' : '1';
}

// Restore theme on load
(function () {
    const saved = localStorage.getItem('ai-transcriptor-theme');
    if (saved) {
        document.documentElement.setAttribute('data-theme', saved);
        const btn = document.getElementById('themeToggle');
        if (btn) btn.textContent = saved === 'light' ? '☀️' : '🌙';
        const canvas = document.getElementById('bgCanvas');
        if (canvas) canvas.style.opacity = saved === 'light' ? '0.5' : '1';
    }
})();

// ─── Speed Calculator ─────────────────────────────────────────────
function updateSpeedCalc() {
    const duration = parseInt(document.getElementById('calcMeetingDuration')?.value) || 60;
    const keyType = document.getElementById('calcKeyType')?.value || 'free';
    const totalKeys = (AppState.settings.paid_api_keys?.length || 0) + (AppState.settings.free_api_keys?.length || 0);

    // Update key count display
    const calcKeyEl = document.getElementById('calcKeyCount');
    if (calcKeyEl) calcKeyEl.textContent = `${totalKeys} key${totalKeys !== 1 ? 's' : ''}`;

    // ─── Calculation Logic ──────────────────
    // Free key: ~2 min per 10-min chunk (transcription + overhead)
    // Paid key: ~0.5 min per 10-min chunk (4x rate limits)
    const chunkTimeMinFree = 2.0;   // minutes to process a 10-min chunk (free)
    const chunkTimeMinPaid = 0.5;   // minutes to process a 10-min chunk (paid)

    // Dynamic recommendations based on key count
    let recChunk, recWorkers, recChunkLabel;
    if (totalKeys <= 1) {
        recChunk = 10; recWorkers = 1; recChunkLabel = '10 min (sequential)';
    } else if (totalKeys <= 3) {
        recChunk = 10; recWorkers = totalKeys; recChunkLabel = '10 min';
    } else if (totalKeys <= 5) {
        recChunk = 5; recWorkers = totalKeys; recChunkLabel = '5 min (more chunks, more speed)';
    } else if (totalKeys <= 10) {
        recChunk = 5; recWorkers = totalKeys; recChunkLabel = '5 min';
    } else {
        recChunk = 3; recWorkers = Math.min(totalKeys, 20); recChunkLabel = '3 min (max parallelism)';
    }

    // Estimate processing time
    const totalChunks = Math.ceil(duration / recChunk);
    const timePerChunk = keyType === 'paid' ? chunkTimeMinPaid : chunkTimeMinFree;
    const effectiveWorkers = Math.min(recWorkers, totalChunks);
    const batches = Math.ceil(totalChunks / effectiveWorkers);
    const transcriptionTime = batches * timePerChunk * (recChunk / 10); // scale by chunk size
    const downloadTime = 1.5; // avg download + conversion overhead
    const postProcessTime = 0.5; // post-processing + PDF generation
    const totalEstimate = downloadTime + transcriptionTime + postProcessTime;

    // Build result HTML
    const result = document.getElementById('speedCalcResult');
    if (!result) return;

    result.innerHTML = `
        <div class="grid-4" style="gap: 12px;">
            <div style="background: var(--bg-secondary); border-radius: var(--radius-md); padding: 16px; text-align: center;">
                <div style="font-size: 28px; font-weight: 800; color: var(--accent-primary);">${recChunk} min</div>
                <div style="font-size: 12px; color: var(--text-muted); margin-top: 4px;">Chunk Duration</div>
            </div>
            <div style="background: var(--bg-secondary); border-radius: var(--radius-md); padding: 16px; text-align: center;">
                <div style="font-size: 28px; font-weight: 800; color: var(--accent-primary);">${recWorkers}</div>
                <div style="font-size: 12px; color: var(--text-muted); margin-top: 4px;">Parallel Workers</div>
            </div>
            <div style="background: var(--bg-secondary); border-radius: var(--radius-md); padding: 16px; text-align: center;">
                <div style="font-size: 28px; font-weight: 800; color: var(--accent-primary);">${totalChunks}</div>
                <div style="font-size: 12px; color: var(--text-muted); margin-top: 4px;">Total Chunks</div>
            </div>
            <div style="background: linear-gradient(135deg, rgba(16,185,129,0.1), rgba(5,150,105,0.1)); border: 1px solid rgba(16,185,129,0.2); border-radius: var(--radius-md); padding: 16px; text-align: center;">
                <div style="font-size: 28px; font-weight: 800; color: var(--success);">~${totalEstimate.toFixed(1)} min</div>
                <div style="font-size: 12px; color: var(--text-muted); margin-top: 4px;">Est. Total Time</div>
            </div>
        </div>

        <div style="margin-top: 16px; padding: 16px; background: var(--bg-secondary); border-radius: var(--radius-md); font-size: 13px; line-height: 1.8;">
            <strong style="color: var(--text-primary);">📋 Recommendation for ${totalKeys} key${totalKeys !== 1 ? 's' : ''} + ${duration} min meeting:</strong><br>
            • Set <strong>Chunk Duration</strong> to <strong>${recChunk} min</strong> → ${totalChunks} chunks total<br>
            • Set <strong>Max Workers</strong> to <strong>${recWorkers}</strong> → ${effectiveWorkers} chunks processed simultaneously<br>
            • Processing in <strong>${batches} batch${batches !== 1 ? 'es' : ''}</strong> × ${timePerChunk.toFixed(1)} min/batch ≈ <strong>${transcriptionTime.toFixed(1)} min</strong> transcription<br>
            • + ~${downloadTime} min download + ~${postProcessTime} min post-processing = <strong style="color: var(--success);">~${totalEstimate.toFixed(1)} min total</strong><br>
            ${totalKeys === 0 ? '<br><span style="color: var(--warning);">⚠️ Add API keys above to enable processing!</span>' : ''}
            ${totalKeys >= 1 && totalKeys <= 2 ? '<br><span style="color: var(--info);">💡 Tip: Add more free Groq keys to speed up processing. Each key is free!</span>' : ''}
            ${totalKeys >= 5 ? '<br><span style="color: var(--success);">🚀 Great setup! You have enough keys for fast parallel processing.</span>' : ''}
        </div>

        <div style="margin-top: 12px; padding: 12px 16px; background: var(--bg-secondary); border-radius: var(--radius-md);">
            <strong style="font-size: 13px; color: var(--text-primary);">📊 Quick Reference Table:</strong>
            <table style="width: 100%; margin-top: 8px; font-size: 12px; color: var(--text-secondary); border-collapse: collapse;">
                <thead>
                    <tr style="border-bottom: 1px solid var(--border-color);">
                        <th style="text-align: left; padding: 6px 4px; color: var(--text-muted);">Keys</th>
                        <th style="text-align: center; padding: 6px 4px; color: var(--text-muted);">Chunk</th>
                        <th style="text-align: center; padding: 6px 4px; color: var(--text-muted);">Workers</th>
                        <th style="text-align: center; padding: 6px 4px; color: var(--text-muted);">60 min call</th>
                        <th style="text-align: center; padding: 6px 4px; color: var(--text-muted);">90 min call</th>
                    </tr>
                </thead>
                <tbody>
                    <tr style="border-bottom: 1px solid var(--border-color);${totalKeys === 1 ? 'background:rgba(59,130,246,0.08);' : ''}">
                        <td style="padding: 6px 4px; font-weight: 600;">1 key</td>
                        <td style="text-align: center; padding: 6px 4px;">10 min</td>
                        <td style="text-align: center; padding: 6px 4px;">1</td>
                        <td style="text-align: center; padding: 6px 4px;">~14 min</td>
                        <td style="text-align: center; padding: 6px 4px;">~20 min</td>
                    </tr>
                    <tr style="border-bottom: 1px solid var(--border-color);${totalKeys === 3 ? 'background:rgba(59,130,246,0.08);' : ''}">
                        <td style="padding: 6px 4px; font-weight: 600;">3 keys</td>
                        <td style="text-align: center; padding: 6px 4px;">10 min</td>
                        <td style="text-align: center; padding: 6px 4px;">3</td>
                        <td style="text-align: center; padding: 6px 4px;">~6 min</td>
                        <td style="text-align: center; padding: 6px 4px;">~8 min</td>
                    </tr>
                    <tr style="border-bottom: 1px solid var(--border-color);${totalKeys === 5 ? 'background:rgba(59,130,246,0.08);' : ''}">
                        <td style="padding: 6px 4px; font-weight: 600;">5 keys</td>
                        <td style="text-align: center; padding: 6px 4px;">5 min</td>
                        <td style="text-align: center; padding: 6px 4px;">5</td>
                        <td style="text-align: center; padding: 6px 4px;">~4.5 min</td>
                        <td style="text-align: center; padding: 6px 4px;">~6 min</td>
                    </tr>
                    <tr style="${totalKeys >= 10 ? 'background:rgba(59,130,246,0.08);' : ''}">
                        <td style="padding: 6px 4px; font-weight: 600;">10 keys</td>
                        <td style="text-align: center; padding: 6px 4px;">5 min</td>
                        <td style="text-align: center; padding: 6px 4px;">10</td>
                        <td style="text-align: center; padding: 6px 4px;">~3 min</td>
                        <td style="text-align: center; padding: 6px 4px;">~4 min</td>
                    </tr>
                </tbody>
            </table>
        </div>

        <button class="btn btn-primary" style="margin-top: 16px;" onclick="applyRecommendedSettings(${recChunk}, ${recWorkers})">
            ✨ Apply Recommended Settings (${recChunk} min chunk, ${recWorkers} workers)
        </button>
    `;
}

function applyRecommendedSettings(chunk, workers) {
    const chunkInput = document.getElementById('settingChunkDuration');
    const workersInput = document.getElementById('settingMaxWorkers');

    if (chunkInput) chunkInput.value = chunk;
    if (workersInput) workersInput.value = workers;

    updateSetting('chunk_duration_minutes', chunk);
    updateSetting('max_parallel_workers', workers);
    showToast('success', 'Applied: ' + chunk + ' min chunks, ' + workers + ' workers');
}

function autoAdjustSettings() {
    const totalKeys = (AppState.settings.paid_api_keys?.length || 0) + (AppState.settings.free_api_keys?.length || 0);
    if (totalKeys === 0) return;

    let recChunk, recWorkers;
    if (totalKeys <= 1) {
        recChunk = 10; recWorkers = 1;
    } else if (totalKeys <= 3) {
        recChunk = 10; recWorkers = totalKeys;
    } else if (totalKeys <= 10) {
        recChunk = 5; recWorkers = totalKeys;
    } else {
        recChunk = 3; recWorkers = Math.min(totalKeys, 20);
    }

    const chunkInput = document.getElementById('settingChunkDuration');
    const workersInput = document.getElementById('settingMaxWorkers');

    // Fall back to server settings update if UI elements aren't rendered yet
    if (chunkInput) chunkInput.value = recChunk;
    if (workersInput) workersInput.value = recWorkers;

    updateSetting('chunk_duration_minutes', recChunk);
    updateSetting('max_parallel_workers', recWorkers);

    setTimeout(() => {
        showToast('info', `⚡ Auto-adjusted: ${recWorkers} workers, ${recChunk}m chunks`);
    }, 1500); // Show slightly after the main added/removed toast

    updateSpeedCalc();
}

// Run speed calc when settings load
const _origApplySettings = applySettings;
applySettings = function () {
    _origApplySettings();
    updateSpeedCalc();
};
