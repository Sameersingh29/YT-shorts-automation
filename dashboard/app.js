/**
 * YT Shorts Automation — Dashboard App
 * Loads analytics and queue data from JSON files in the repo.
 */

// Data file paths (relative to GitHub Pages root or local)
const ANALYTICS_PATH = '../data/analytics.json';
const QUEUE_PATH = '../data/queue.json';

// ─── Data Loading ─────────────────────────────────────────

async function loadJSON(path) {
    try {
        const response = await fetch(path);
        if (!response.ok) throw new Error(`HTTP ${response.status}`);
        return await response.json();
    } catch (error) {
        console.warn(`Failed to load ${path}:`, error.message);
        return null;
    }
}

async function loadAllData() {
    const [analytics, queue] = await Promise.all([
        loadJSON(ANALYTICS_PATH),
        loadJSON(QUEUE_PATH),
    ]);
    return { analytics, queue };
}

// ─── Formatting ───────────────────────────────────────────

function formatNumber(num) {
    if (num >= 1_000_000) return (num / 1_000_000).toFixed(1) + 'M';
    if (num >= 1_000) return (num / 1_000).toFixed(1) + 'K';
    return num.toString();
}

function formatDate(isoString) {
    if (!isoString) return '—';
    const date = new Date(isoString);
    return date.toLocaleDateString('en-IN', {
        month: 'short',
        day: 'numeric',
        hour: '2-digit',
        minute: '2-digit',
    });
}

function timeAgo(isoString) {
    if (!isoString) return 'Never';
    const diff = Date.now() - new Date(isoString).getTime();
    const mins = Math.floor(diff / 60000);
    if (mins < 60) return `${mins}m ago`;
    const hours = Math.floor(mins / 60);
    if (hours < 24) return `${hours}h ago`;
    const days = Math.floor(hours / 24);
    return `${days}d ago`;
}

// ─── UI Updates ───────────────────────────────────────────

function updateStats(analytics) {
    const uploads = analytics?.uploads || [];
    const totalUploads = uploads.length;
    const totalViews = uploads.reduce((sum, u) => sum + (u.views || 0), 0);
    const totalLikes = uploads.reduce((sum, u) => sum + (u.likes || 0), 0);

    animateNumber('totalUploads', totalUploads);
    animateNumber('totalViews', totalViews, true);
    animateNumber('totalLikes', totalLikes, true);

    // Last updated
    const lastUpdated = document.getElementById('lastUpdated');
    lastUpdated.textContent = `Last updated: ${timeAgo(analytics?.last_updated)}`;
}

function updateTypeBars(analytics) {
    const uploads = analytics?.uploads || [];
    const total = uploads.length || 1;

    const viral = uploads.filter(u => u.clip_type === 'viral').length;
    const informative = uploads.filter(u => u.clip_type === 'informative').length;
    const mixed = uploads.filter(u => u.clip_type === 'mixed').length;

    // Animate bars
    setTimeout(() => {
        document.getElementById('barViral').style.width = `${(viral / total) * 100}%`;
        document.getElementById('barInformative').style.width = `${(informative / total) * 100}%`;
        document.getElementById('barMixed').style.width = `${(mixed / total) * 100}%`;
    }, 300);

    document.getElementById('countViral').textContent = viral;
    document.getElementById('countInformative').textContent = informative;
    document.getElementById('countMixed').textContent = mixed;
}

function updateUploadsTable(analytics) {
    const uploads = analytics?.uploads || [];
    const tbody = document.getElementById('uploadsTableBody');

    if (uploads.length === 0) {
        tbody.innerHTML = `
            <tr>
                <td colspan="6" class="empty-state">
                    No uploads yet. Process your first video!
                </td>
            </tr>`;
        return;
    }

    // Show most recent first, max 20
    const recent = [...uploads].reverse().slice(0, 20);

    tbody.innerHTML = recent.map(upload => {
        const badgeClass = `badge-${upload.clip_type || 'mixed'}`;
        const ytUrl = `https://youtube.com/shorts/${upload.youtube_video_id}`;

        return `
            <tr>
                <td title="${upload.title || ''}">${truncate(upload.title || 'Untitled', 45)}</td>
                <td><span class="badge ${badgeClass}">${upload.clip_type || 'mixed'}</span></td>
                <td>${formatDate(upload.scheduled_time)}</td>
                <td>${formatNumber(upload.views || 0)}</td>
                <td>${formatNumber(upload.likes || 0)}</td>
                <td>
                    <a href="${ytUrl}" target="_blank" class="link-btn">
                        ▶ Watch
                    </a>
                </td>
            </tr>`;
    }).join('');
}

function updateQueueStatus(queue) {
    const clips = queue?.clips || [];

    const pending = clips.filter(c => c.status === 'pending').length;
    const uploaded = clips.filter(c => c.status === 'uploaded').length;
    const failed = clips.filter(c => c.status === 'failed').length;

    animateNumber('queuePending', pending);
    animateNumber('queueUploaded', uploaded);
    animateNumber('queueFailed', failed);
    animateNumber('queueSize', pending);

    // Estimate days left (2 uploads per day)
    const daysLeft = Math.ceil(pending / 2);
    animateNumber('queueDays', daysLeft);
}

// ─── Helpers ──────────────────────────────────────────────

function truncate(str, maxLen) {
    if (!str) return '';
    return str.length > maxLen ? str.slice(0, maxLen) + '…' : str;
}

function animateNumber(elementId, target, format = false) {
    const el = document.getElementById(elementId);
    if (!el) return;

    const start = parseInt(el.textContent) || 0;
    const duration = 800;
    const startTime = performance.now();

    function update(currentTime) {
        const elapsed = currentTime - startTime;
        const progress = Math.min(elapsed / duration, 1);

        // Ease out cubic
        const eased = 1 - Math.pow(1 - progress, 3);
        const current = Math.round(start + (target - start) * eased);

        el.textContent = format ? formatNumber(current) : current;

        if (progress < 1) {
            requestAnimationFrame(update);
        }
    }

    requestAnimationFrame(update);
}

// ─── Init ─────────────────────────────────────────────────

async function init() {
    const { analytics, queue } = await loadAllData();

    if (analytics) {
        updateStats(analytics);
        updateTypeBars(analytics);
        updateUploadsTable(analytics);
    }

    if (queue) {
        updateQueueStatus(queue);
    }

    // Auto-refresh every 5 minutes
    setInterval(async () => {
        const data = await loadAllData();
        if (data.analytics) {
            updateStats(data.analytics);
            updateTypeBars(data.analytics);
            updateUploadsTable(data.analytics);
        }
        if (data.queue) {
            updateQueueStatus(data.queue);
        }
    }, 300_000);
}

// Start
document.addEventListener('DOMContentLoaded', init);
