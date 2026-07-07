/**
 * LumaKit Web UI — main entry point.
 * Boots WebSocket, initializes components, routes views.
 */

import { wsUrl } from './lib/auth.js';
import { WS } from './lib/ws.js';

// --- DOM refs ---
const $messages = document.getElementById('messages');
const $messagesInner = document.getElementById('messages-inner');
const $emptyState = document.getElementById('empty-state');
const $input = document.getElementById('input');
const $sendBtn = document.getElementById('send-btn');
const $photoInput = document.getElementById('photo-input');
const $photoBtn = document.getElementById('photo-btn');
const $photoPreview = document.getElementById('photo-preview');
const $chatList = document.getElementById('chat-list');
const $newChatBtn = document.getElementById('new-chat-btn');
const $topbarTitle = document.getElementById('topbar-title');
const $modelBadge = document.getElementById('model-badge');
const $modelBadgeText = $modelBadge?.querySelector('.model-badge-text') || $modelBadge;
const $statusLabel = document.getElementById('status-label');
const $statusDot = document.getElementById('status-dot');
const $workspaceForm = document.getElementById('workspace-form');
const $workspaceInput = document.getElementById('workspace-input');
const $workspaceBrowse = document.getElementById('workspace-browse');
const $sidebarToggle = document.getElementById('sidebar-toggle');
const $sidebar = document.getElementById('sidebar');
const $diffPanel = document.getElementById('diff-panel');
const $diffPanelBackdrop = document.getElementById('diff-panel-backdrop');
const $diffPanelTool = document.getElementById('diff-panel-tool');
const $diffPanelPath = document.getElementById('diff-panel-path');
const $diffPanelBody = document.getElementById('diff-panel-body');
const $diffPanelFooter = document.getElementById('diff-panel-footer');
const $diffPanelClose = document.getElementById('diff-panel-close');
const $diffPanelApprove = document.getElementById('diff-panel-approve');
const $diffPanelDeny = document.getElementById('diff-panel-deny');
const $navTasks = document.getElementById('nav-tasks');
const $navSettings = document.getElementById('nav-settings');
const $taskList = document.getElementById('task-list');
const $settingsContent = document.getElementById('settings-content');
const $setupOverlay = document.getElementById('setup-overlay');
const $setupOpenSettings = document.getElementById('setup-open-settings');
const $emptyHeadline = document.getElementById('empty-headline');
const $emptySubcopy = document.getElementById('empty-subcopy');

// --- State ---
let isWorking = false;
let currentView = 'chat';
let currentChatId = null;
let currentWorkspacePath = '';
let statusEl = null;
let activityCardEl = null;
let activityTitleEl = null;
let activityLiveEl = null;
let activityListEl = null;
let activityLastText = '';
let streamMessageEl = null;
let streamBubbleEl = null;
let streamText = '';
let activeTranscript = [];
// Pending confirm card awaiting a decision (only one at a time)
let pendingConfirm = null;
let currentTurnHadRichReply = false;
let notificationPollTimer = null;
const emailDraftCards = new Map();
let settingsState = null;
let requiresModelSetup = false;
let pendingSettingsFocus = false;
let lastEmptyPromptIndex = -1;
let emptyStateDismissTimer = null;
let attachedPhoto = null;

const EMPTY_STATE_PROMPTS = [
    {
        headline: 'Your local AI agent is ready.',
        subcopy: 'Cat-powered automation, right from your machine.',
    },
    {
        headline: 'Local-first automation.',
        subcopy: 'Plan, search, write, and run — without leaving your machine.',
    },
    {
        headline: 'Give the cat a mission.',
        subcopy: 'Hand over a task and let Lumi get to work.',
    },
];

const HERO_IMAGES = [
    '/photos/lumakit_hero.png',
    '/photos/lumakit_lava.png',
    '/photos/lumarock.png',
    '/photos/lumaskate.png',
];
let lastHeroIndex = -1;
const MAX_PHOTO_BYTES = 10 * 1024 * 1024;

// --- Markdown setup ---
if (window.marked) {
    marked.setOptions({
        breaks: true,
        gfm: true,
        highlight: (code, lang) => {
            if (window.hljs && lang && hljs.getLanguage(lang)) {
                return hljs.highlight(code, { language: lang }).value;
            }
            return code;
        },
    });
}

// --- Helpers ---
function renderMarkdown(text) {
    if (!text) return '';
    if (window.marked) {
        return marked.parse(text);
    }
    return text
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/\n/g, '<br>');
}

function getCodeLanguage(codeEl) {
    const classes = Array.from(codeEl?.classList || []);
    const languageClass = classes.find(cls => cls.startsWith('language-') || cls.startsWith('lang-'));
    const raw = languageClass
        ? languageClass.replace(/^language-/, '').replace(/^lang-/, '')
        : '';
    const normalized = (raw || '').trim().toLowerCase();
    const aliases = {
        js: 'javascript',
        jsx: 'jsx',
        ts: 'typescript',
        tsx: 'tsx',
        py: 'python',
        ps1: 'powershell',
        pwsh: 'powershell',
        sh: 'bash',
        shell: 'bash',
        yml: 'yaml',
        md: 'markdown',
    };
    return aliases[normalized] || normalized || 'text';
}

async function copyTextToClipboard(text) {
    if (navigator.clipboard?.writeText) {
        await navigator.clipboard.writeText(text);
        return;
    }
    const textarea = document.createElement('textarea');
    textarea.value = text;
    textarea.setAttribute('readonly', '');
    textarea.style.position = 'fixed';
    textarea.style.opacity = '0';
    textarea.style.pointerEvents = 'none';
    document.body.appendChild(textarea);
    textarea.select();
    document.execCommand('copy');
    textarea.remove();
}

function enhanceCodeBlocks(root) {
    if (!root) return;

    if (window.hljs) {
        root.querySelectorAll('pre code').forEach(codeEl => {
            if (!codeEl.dataset.highlighted) {
                hljs.highlightElement(codeEl);
            }
        });
    }

    root.querySelectorAll('pre').forEach(pre => {
        if (pre.closest('.code-block')) return;

        const code = pre.querySelector('code');
        if (!code) return;

        const wrapper = document.createElement('div');
        wrapper.className = 'code-block';

        const header = document.createElement('div');
        header.className = 'code-block-header';

        const language = document.createElement('span');
        language.className = 'code-block-language';
        language.textContent = getCodeLanguage(code);

        const copy = document.createElement('button');
        copy.className = 'code-block-copy';
        copy.type = 'button';
        copy.textContent = 'Copy';
        copy.title = 'Copy code';
        copy.setAttribute('aria-label', 'Copy code block');
        copy.addEventListener('click', async () => {
            const original = copy.textContent;
            try {
                await copyTextToClipboard(code.textContent || '');
                copy.textContent = 'Copied';
                copy.classList.add('copied');
            } catch {
                copy.textContent = 'Failed';
                copy.classList.add('failed');
            }
            window.setTimeout(() => {
                copy.textContent = original;
                copy.classList.remove('copied', 'failed');
            }, 1400);
        });

        header.appendChild(language);
        header.appendChild(copy);
        pre.parentNode.insertBefore(wrapper, pre);
        wrapper.appendChild(header);
        wrapper.appendChild(pre);
    });
}

function scrollToBottom() {
    $messages.scrollTop = $messages.scrollHeight;
}

function setWorking(working) {
    isWorking = working;
    if ($workspaceInput) $workspaceInput.disabled = working;
    if ($workspaceBrowse) $workspaceBrowse.disabled = working;
    if ($photoBtn) $photoBtn.disabled = working;
    // Type /stop to interrupt — no UI toggle needed
}

function workspaceLabel(path) {
    const text = String(path || '').trim();
    if (!text) return 'Working directory';
    const normalized = text.replace(/\\/g, '/');
    const parts = normalized.split('/').filter(Boolean);
    return parts.slice(-2).join('/') || text;
}

function setWorkspace(path, displayPath) {
    currentWorkspacePath = String(path || '');
    if ($workspaceInput) {
        $workspaceInput.value = currentWorkspacePath;
        $workspaceInput.title = displayPath || currentWorkspacePath || 'Working directory';
        $workspaceInput.setAttribute('aria-label', `Working directory: ${workspaceLabel(currentWorkspacePath)}`);
    }
}

function showWorkspaceError(message) {
    if ($workspaceInput) {
        $workspaceInput.classList.add('error');
        $workspaceForm?.classList.add('error');
        $workspaceInput.title = message || 'Could not set working directory.';
        window.setTimeout(() => {
            $workspaceInput.classList.remove('error');
            $workspaceForm?.classList.remove('error');
        }, 1800);
    }
}

function applySetupState() {
    const blocked = !!requiresModelSetup;
    $input.disabled = blocked;
    $sendBtn.disabled = blocked;
    $newChatBtn.disabled = blocked;
    if ($photoBtn) $photoBtn.disabled = blocked || isWorking;
    if (blocked) {
        $input.placeholder = 'Choose a model in Settings before chatting...';
        const viewingSettings = currentView === 'settings';
        $setupOverlay.classList.toggle('hidden', viewingSettings);
        if (!viewingSettings) {
            switchView('settings');
        }
    } else {
        $input.placeholder = 'Message Lumi... (type /stop to interrupt)';
        $setupOverlay.classList.add('hidden');
    }
}

function removeStatus() {
    if (statusEl) {
        statusEl.remove();
        statusEl = null;
    }
}

function clearActivityCard() {
    if (activityCardEl) {
        activityCardEl.remove();
        activityCardEl = null;
        activityTitleEl = null;
        activityLiveEl = null;
        activityListEl = null;
        activityLastText = '';
    }
}

function dismissEmptyState() {
    if (!$emptyState || $emptyState.classList.contains('hidden')) {
        exitCenteredMode();
        return;
    }
    if ($emptyState.classList.contains('is-exiting')) return;
    $emptyState.classList.add('is-exiting');
    const chatView = document.getElementById('chat-view');
    chatView.classList.add('empty-state-exiting');
    if (emptyStateDismissTimer) clearTimeout(emptyStateDismissTimer);
    emptyStateDismissTimer = setTimeout(() => {
        $emptyState.classList.add('hidden');
        $emptyState.classList.remove('is-exiting');
        chatView.classList.remove('empty-state-exiting');
        exitCenteredMode();
        emptyStateDismissTimer = null;
    }, 220);
}

function rotateEmptyPrompt() {
    if (!$emptyHeadline || !$emptySubcopy || EMPTY_STATE_PROMPTS.length === 0) return;
    let index = Math.floor(Math.random() * EMPTY_STATE_PROMPTS.length);
    if (EMPTY_STATE_PROMPTS.length > 1 && index === lastEmptyPromptIndex) {
        index = (index + 1) % EMPTY_STATE_PROMPTS.length;
    }
    lastEmptyPromptIndex = index;
    const prompt = EMPTY_STATE_PROMPTS[index];
    $emptyHeadline.textContent = prompt.headline;
    $emptySubcopy.textContent = prompt.subcopy;
    $emptyHeadline.classList.remove('compact');
}

function exitCenteredMode() {
    const chatView = document.getElementById('chat-view');
    chatView.classList.remove('chat-view-centered');
    document.getElementById('hero-bg')?.classList.remove('ready');
}

function rotateHeroBackground() {
    const heroEl = document.getElementById('hero-bg');
    if (!heroEl || HERO_IMAGES.length === 0) return;
    let index = Math.floor(Math.random() * HERO_IMAGES.length);
    if (HERO_IMAGES.length > 1 && index === lastHeroIndex) {
        index = (index + 1) % HERO_IMAGES.length;
    }
    lastHeroIndex = index;
    const src = HERO_IMAGES[index];
    const img = new Image();
    img.onload = () => {
        heroEl.style.setProperty('--hero-img', `url("${src}")`);
        heroEl.classList.add('ready');
    };
    img.src = src;
}

function enterCenteredMode() {
    const chatView = document.getElementById('chat-view');
    if (emptyStateDismissTimer) {
        clearTimeout(emptyStateDismissTimer);
        emptyStateDismissTimer = null;
    }
    chatView.classList.remove('empty-state-exiting');
    chatView.classList.add('chat-view-centered');
    $emptyState?.classList.remove('hidden', 'is-exiting');
    rotateEmptyPrompt();
    rotateHeroBackground();
}

function addMessage(role, content) {
    if ($emptyState && !$emptyState.classList.contains('hidden')) {
        dismissEmptyState();
    }
    removeStatus();

    const div = document.createElement('div');
    div.className = `message ${role}`;
    div.dataset.role = role;

    const bubble = document.createElement('div');
    bubble.className = 'bubble';
    bubble.innerHTML = renderMarkdown(content);

    div.appendChild(bubble);
    $messagesInner.appendChild(div);
    enhanceCodeBlocks(div);
    scrollToBottom();
}

function addUserPhotoMessage(text, photo) {
    if (!photo) {
        addMessage('user', text);
        return;
    }
    if ($emptyState && !$emptyState.classList.contains('hidden')) {
        dismissEmptyState();
    }
    removeStatus();

    const div = document.createElement('div');
    div.className = 'message user image-message';
    div.dataset.role = 'user';

    const bubble = document.createElement('div');
    bubble.className = 'bubble user-photo-bubble';

    const image = document.createElement('img');
    image.className = 'user-attached-image';
    image.src = photo.data_url;
    image.alt = photo.name || 'Attached photo';
    bubble.appendChild(image);

    if (text) {
        const caption = document.createElement('div');
        caption.className = 'user-photo-caption';
        caption.innerHTML = renderMarkdown(text);
        bubble.appendChild(caption);
    }

    div.appendChild(bubble);
    $messagesInner.appendChild(div);
    enhanceCodeBlocks(div);
    scrollToBottom();
}

function ensureStreamMessage() {
    if (streamMessageEl && streamBubbleEl) return streamBubbleEl;
    if ($emptyState && !$emptyState.classList.contains('hidden')) {
        dismissEmptyState();
    }
    removeStatus();

    const div = document.createElement('div');
    div.className = 'message assistant streaming';
    div.dataset.role = 'assistant';

    const bubble = document.createElement('div');
    bubble.className = 'bubble';
    div.appendChild(bubble);

    $messagesInner.appendChild(div);
    streamMessageEl = div;
    streamBubbleEl = bubble;
    streamText = '';
    return bubble;
}

function renderStreamText(text) {
    const bubble = ensureStreamMessage();
    bubble.innerHTML = renderMarkdown(text || '');
    enhanceCodeBlocks(streamMessageEl);
    currentTurnHadRichReply = true;
    scrollToBottom();
}

function appendStreamText(text) {
    if (!text) return;
    streamText += text;
    renderStreamText(streamText);
}

function finishStreamText(text) {
    const finalText = (text || streamText || '').trim();
    if (finalText) {
        renderStreamText(finalText);
    }
    if (streamMessageEl) {
        streamMessageEl.classList.remove('streaming');
    }
    streamMessageEl = null;
    streamBubbleEl = null;
    streamText = '';
    return finalText;
}

function cancelStreamText() {
    if (streamMessageEl) {
        streamMessageEl.remove();
    }
    streamMessageEl = null;
    streamBubbleEl = null;
    streamText = '';
}

function ensureActivityCard() {
    if (activityCardEl) return activityCardEl;
    if ($emptyState && !$emptyState.classList.contains('hidden')) {
        dismissEmptyState();
    }
    removeStatus();

    const div = document.createElement('div');
    div.className = 'message assistant activity-message';
    div.dataset.role = 'assistant';

    const bubble = document.createElement('div');
    bubble.className = 'bubble activity-bubble';
    bubble.innerHTML = `
        <div class="activity-header">
            <span class="activity-dot"></span>
            <span class="activity-title">Lumi is thinking</span>
        </div>
        <div class="activity-live">Working through it...</div>
        <div class="activity-log"></div>
    `;

    div.appendChild(bubble);
    $messagesInner.appendChild(div);
    activityCardEl = div;
    activityTitleEl = bubble.querySelector('.activity-title');
    activityLiveEl = bubble.querySelector('.activity-live');
    activityListEl = bubble.querySelector('.activity-log');
    scrollToBottom();
    return div;
}

function _normalizedForDedupe(text) {
    return String(text || '')
        .toLowerCase()
        .replace(/[\s.…:;!?]+$/g, '')
        .replace(/\s+/g, ' ')
        .trim();
}

function appendActivityLine(text, kind = 'status') {
    const value = String(text || '').trim();
    if (!value) return;
    ensureActivityCard();
    const normalized = _normalizedForDedupe(value);
    const lastNormalized = _normalizedForDedupe(activityLastText);
    // Drop exact repeats AND substring overlaps so things like
    // "browser_automation for https://x" immediately followed by
    // "navigating to https://x" don't show as two lines.
    if (normalized && lastNormalized) {
        if (
            normalized === lastNormalized ||
            normalized.includes(lastNormalized) ||
            lastNormalized.includes(normalized)
        ) {
            // Keep the richer line visible.
            const richer = value.length >= activityLastText.length ? value : activityLastText;
            if (activityLiveEl) activityLiveEl.textContent = richer;
            if (richer !== activityLastText && activityListEl.lastElementChild) {
                activityListEl.lastElementChild.textContent = richer;
                activityLastText = richer;
            }
            return;
        }
    }

    const line = document.createElement('div');
    line.className = `activity-line ${kind}`;
    line.textContent = value;
    activityListEl.appendChild(line);
    activityLastText = value;

    while (activityListEl.children.length > 8) {
        activityListEl.removeChild(activityListEl.firstChild);
    }
    if (activityLiveEl) activityLiveEl.style.display = 'none';
    scrollToBottom();
}

function setActivityHeadline(text) {
    ensureActivityCard();
    if (activityTitleEl) activityTitleEl.textContent = text;
    if (activityLiveEl) activityLiveEl.textContent = text;
    scrollToBottom();
}

function settleActivityCard(state = 'done') {
    if (!activityCardEl) return;
    activityCardEl.classList.remove('active', 'done', 'error', 'stopped');
    activityCardEl.classList.add(state);
    if (activityTitleEl) {
        activityTitleEl.textContent =
            state === 'error' ? 'Lumi hit a problem'
            : state === 'stopped' ? 'Lumi stopped'
            : 'What Lumi did';
    }
}

function formatPlainText(text) {
    return escapeHtml(String(text || '')).replace(/\n/g, '<br>');
}

function renderEmailSections(email, { includeDraft = true } = {}) {
    const bodyPreview = email?.body_preview || '';
    const summary = email?.summary || '';
    const draftPreview = includeDraft ? (email?.draft_preview || '') : '';
    const links = Array.isArray(email?.links) ? email.links : [];

    const sections = [];

    if (bodyPreview) {
        sections.push(`
            <div class="email-card-section">
                <div class="email-card-section-title">Body</div>
                <div class="email-card-section-body">${formatPlainText(bodyPreview)}</div>
            </div>
        `);
    }

    if (summary) {
        sections.push(`
            <div class="email-card-section">
                <div class="email-card-section-title">Lumi's Take</div>
                <div class="email-card-section-body">${formatPlainText(summary)}</div>
            </div>
        `);
    }

    if (draftPreview) {
        sections.push(`
            <div class="email-card-section">
                <div class="email-card-section-title">Draft Reply</div>
                <div class="email-card-section-body">${formatPlainText(draftPreview)}</div>
            </div>
        `);
    }

    if (links.length) {
        const linkItems = links.map(link => `
            <li class="email-card-link-item">
                <span class="email-card-link-url">${escapeHtml(link.url || '')}</span>
                <span class="email-card-link-label">${escapeHtml(link.label || '')}</span>
            </li>
        `).join('');
        sections.push(`
            <div class="email-card-section">
                <div class="email-card-section-title">Links Lumi Could Not See</div>
                <ul class="email-card-links">${linkItems}</ul>
            </div>
        `);
    }

    return sections.join('');
}

function renderIncomingEmailCard(email) {
    return `
        <div class="email-card">
            <div class="email-card-head">
                <span class="email-card-badge">New Email</span>
                <span class="email-card-subtitle">Background notification</span>
            </div>
            <div class="email-card-meta">
                <div class="email-card-row">
                    <span class="email-card-key">From</span>
                    <span class="email-card-value">${escapeHtml(email?.from || '')}</span>
                </div>
                <div class="email-card-row">
                    <span class="email-card-key">Subject</span>
                    <span class="email-card-value">${escapeHtml(email?.subject || '(no subject)')}</span>
                </div>
            </div>
            ${renderEmailSections(email)}
        </div>
    `;
}

function renderEmailConfirmCard(data) {
    const preview = data.email_preview || {};
    const actionLabel = preview.action === 'reply' ? 'Reply Preview' : 'Email Preview';
    const remaining = preview.remaining_after_send;
    return `
        <div class="confirm-card email-confirm-card">
            <div class="confirm-card-head">
                <span class="confirm-card-icon">✉</span>
                <span class="confirm-card-tool">${escapeHtml(data.tool_name || 'email')}</span>
                <span class="confirm-card-prompt">${escapeHtml(data.prompt || 'Approve this email?')}</span>
            </div>
            <div class="email-card">
                <div class="email-card-head">
                    <span class="email-card-badge">${escapeHtml(actionLabel)}</span>
                    <span class="email-card-subtitle">Review before sending</span>
                </div>
                <div class="email-card-meta">
                    <div class="email-card-row">
                        <span class="email-card-key">To</span>
                        <span class="email-card-value">${escapeHtml(preview.to || '')}</span>
                    </div>
                    ${preview.cc ? `
                        <div class="email-card-row">
                            <span class="email-card-key">CC</span>
                            <span class="email-card-value">${escapeHtml(preview.cc)}</span>
                        </div>
                    ` : ''}
                    <div class="email-card-row">
                        <span class="email-card-key">Subject</span>
                        <span class="email-card-value">${escapeHtml(preview.subject || '(no subject)')}</span>
                    </div>
                    ${typeof remaining === 'number' ? `
                        <div class="email-card-row">
                            <span class="email-card-key">Remaining</span>
                            <span class="email-card-value">${escapeHtml(String(remaining))} send(s) after approval</span>
                        </div>
                    ` : ''}
                </div>
                <div class="email-card-section">
                    <div class="email-card-section-title">Message</div>
                    <div class="email-card-section-body">${formatPlainText(preview.body || '')}</div>
                </div>
            </div>
            <div class="confirm-card-actions">
                <span class="confirm-card-hint"><kbd>Y</kbd> approve &middot; <kbd>N</kbd> deny</span>
                <button class="confirm-btn confirm-no">Deny (N)</button>
                <button class="confirm-btn confirm-yes">Approve (Y)</button>
            </div>
            <div class="confirm-card-status"></div>
        </div>
    `;
}

function setEmailDraftPendingState(draftId, pendingText) {
    const entry = emailDraftCards.get(String(draftId));
    if (!entry) return;
    entry.approve.disabled = true;
    entry.discard.disabled = true;
    entry.status.textContent = pendingText;
    entry.status.classList.remove('approved', 'denied');
    entry.status.classList.add('pending');
}

function resolveEmailDraftCard(data) {
    const draftId = data.draft_id != null ? String(data.draft_id) : null;
    const entry = draftId ? emailDraftCards.get(draftId) : null;
    if (!entry) {
        addMessage('assistant', `${data.ok ? '✓' : '✗'} ${data.text}`);
        return;
    }

    entry.actions.remove();
    entry.status.textContent = `${data.ok ? '✓' : '✗'} ${data.text}`;
    entry.status.classList.remove('pending');
    entry.status.classList.add(data.ok ? 'approved' : 'denied');
    emailDraftCards.delete(draftId);
    scrollToBottom();
}

function addBackgroundMessage(data) {
    const text = (data.text || '').trim();
    if (!text) return;

    const draftId = data.draft_id != null ? String(data.draft_id) : null;
    if (draftId && emailDraftCards.has(draftId)) {
        return;
    }

    if ($emptyState && !$emptyState.classList.contains('hidden')) {
        $emptyState.classList.add('hidden');
        exitCenteredMode();
    }
    removeStatus();

    const div = document.createElement('div');
    div.className = 'message assistant';
    div.dataset.role = 'assistant';

    const bubble = document.createElement('div');
    bubble.className = 'bubble';
    if (data.kind === 'email' && data.email) {
        div.classList.add('email-card-message');
        bubble.innerHTML = renderIncomingEmailCard(data.email);
    } else {
        bubble.innerHTML = renderMarkdown(text);
    }
    div.appendChild(bubble);

    if (draftId) {
        const actionParent = data.kind === 'email' && data.email
            ? bubble.querySelector('.email-card') || bubble
            : bubble;
        const actions = document.createElement('div');
        actions.className = 'email-draft-actions';

        const discard = document.createElement('button');
        discard.className = 'confirm-btn confirm-no';
        discard.textContent = 'Discard';
        discard.onclick = () => {
            setEmailDraftPendingState(draftId, 'Discarding...');
            ws.send({ type: 'email_draft_action', action: 'discard', draft_id: Number(draftId) });
        };

        const approve = document.createElement('button');
        approve.className = 'confirm-btn confirm-yes';
        approve.textContent = 'Send';
        approve.onclick = () => {
            setEmailDraftPendingState(draftId, 'Sending...');
            ws.send({ type: 'email_draft_action', action: 'approve', draft_id: Number(draftId) });
        };

        const status = document.createElement('div');
        status.className = 'email-draft-status';

        actions.appendChild(discard);
        actions.appendChild(approve);
        actionParent.appendChild(actions);
        actionParent.appendChild(status);
        emailDraftCards.set(draftId, { approve, discard, actions, status });
    }

    $messagesInner.appendChild(div);
    enhanceCodeBlocks(div);
    scrollToBottom();
}

function getLastUserMessage() {
    const messages = $messagesInner.querySelectorAll('.message.user');
    return messages.length ? messages[messages.length - 1] : null;
}

function addReactionToLatestUserMessage(emoji) {
    if (!emoji) return;
    const message = getLastUserMessage();
    if (!message) return;

    let reaction = message.querySelector('.message-reaction');
    if (!reaction) {
        reaction = document.createElement('div');
        reaction.className = 'message-reaction';
        message.appendChild(reaction);
    }

    reaction.textContent = emoji;
    scrollToBottom();
}

function addDeliveredImage(url, caption = '') {
    if (!url) return;
    if ($emptyState && !$emptyState.classList.contains('hidden')) {
        $emptyState.classList.add('hidden');
        exitCenteredMode();
    }
    removeStatus();

    const div = document.createElement('div');
    div.className = 'message assistant image-message';
    div.dataset.role = 'assistant';

    const bubble = document.createElement('div');
    bubble.className = 'bubble';

    const link = document.createElement('a');
    link.className = 'delivered-image-link';
    link.href = url;
    link.target = '_blank';
    link.rel = 'noreferrer noopener';

    const image = document.createElement('img');
    image.className = 'delivered-image';
    image.src = url;
    image.alt = caption || 'Delivered image';
    image.loading = 'lazy';

    link.appendChild(image);
    bubble.appendChild(link);

    if (caption) {
        const captionEl = document.createElement('div');
        captionEl.className = 'delivered-image-caption';
        captionEl.textContent = caption;
        bubble.appendChild(captionEl);
    }

    div.appendChild(bubble);
    $messagesInner.appendChild(div);
    scrollToBottom();
}

function parseToolMessageContent(content) {
    if (!content) return null;

    try {
        return JSON.parse(content);
    } catch {
        return null;
    }
}

function restoreRichToolMessage(message) {
    const parsed = parseToolMessageContent(message?.content);
    const data = parsed?.data || {};

    if (message?.name === 'react_to_message' && data.reacted && data.emoji) {
        addReactionToLatestUserMessage(data.emoji);
        return true;
    }

    if (
        ['send_photo', 'screenshot'].includes(message?.name) &&
        data.sent &&
        data.interface === 'web' &&
        data.url
    ) {
        addDeliveredImage(data.url, data.caption || '');
        return true;
    }

    return false;
}

function isInlineToolResult(data) {
    return !data.error && ['react_to_message', 'send_photo', 'screenshot'].includes(data.name);
}

function addToolCard(name, detail, isResult = false, isError = false) {
    removeStatus();

    const div = document.createElement('div');
    div.className = `tool-card${isResult ? ' result' : ''}${isError ? ' error' : ''}`;

    if (isResult) {
        div.innerHTML = `<span class="tool-detail">${detail}</span>`;
    } else {
        div.innerHTML = `<span class="tool-name">${name}</span><span class="tool-detail">${detail || ''}</span>`;
    }

    $messagesInner.appendChild(div);
    scrollToBottom();
}

function showStatus(text) {
    removeStatus();
    statusEl = document.createElement('div');
    statusEl.className = 'status-msg';
    statusEl.textContent = text;
    $messagesInner.appendChild(statusEl);
    scrollToBottom();
}

function clearMessages() {
    $messagesInner.innerHTML = '';
    $emptyState.classList.remove('hidden');
    enterCenteredMode();
    currentTurnHadRichReply = false;
    clearActivityCard();
    clearAttachedPhoto();
}

function visibleTranscriptCount(messages) {
    return (messages || []).filter(m => (
        m && (m.role === 'user' || m.role === 'assistant') && String(m.content || '').trim()
    )).length;
}

function rememberVisibleMessage(role, content) {
    const text = String(content || '').trim();
    if (!text || !['user', 'assistant'].includes(role)) return;
    activeTranscript.push({ role, content: text });
}

function renderChatMessages(messages) {
    clearMessages();

    const hasMessages = (messages || []).some(m => m.role === 'user' || m.role === 'assistant');
    if (hasMessages) exitCenteredMode();

    for (const msg of messages || []) {
        if (msg.role === 'system') continue;
        if (msg.role === 'tool') {
            restoreRichToolMessage(msg);
            continue;
        }
        if (msg.role === 'user' || msg.role === 'assistant') {
            const content = msg.content || '';
            if (content) addMessage(msg.role, content);
        }
    }
}

// --- Views ---
function switchView(view) {
    currentView = view;
    document.querySelectorAll('.view').forEach(v => v.classList.remove('active'));
    document.getElementById(`${view}-view`).classList.add('active');

    $navTasks.classList.toggle('active', view === 'task');
    $navSettings.classList.toggle('active', view === 'settings');

    if (view === 'task') loadTasks();
    if (view === 'settings') loadSettings();
    applySetupState();
}

// --- Chat list ---
async function loadChatList() {
    try {
        const res = await fetch('/api/chats');
        const chats = await res.json();
        $chatList.innerHTML = '';
        const label = document.querySelector('.chat-list-label');
        if (label) label.classList.toggle('visible', chats.length > 0);
        for (const chat of chats) {
            const item = document.createElement('div');
            item.className = `chat-item${chat.id === currentChatId ? ' active' : ''}`;

            const icon = document.createElement('span');
            icon.className = 'chat-item-icon';
            icon.innerHTML = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2Z"/></svg>';

            const title = document.createElement('span');
            title.className = 'chat-item-title';
            title.textContent = chat.title || 'Untitled';
            title.onclick = () => {
                if (chat.id === currentChatId) {
                    switchView('chat');
                    $sidebar.classList.remove('open');
                    return;
                }
                ws.send({ type: 'load_chat', chat_id: chat.id });
                $sidebar.classList.remove('open');
            };

            const del = document.createElement('button');
            del.className = 'chat-item-delete';
            del.title = 'Delete chat';
            del.setAttribute('aria-label', 'Delete chat');
            del.innerHTML = '&times;';
            del.onclick = async (e) => {
                e.stopPropagation();
                const ok = await showConfirmDialog({
                    title: `Delete "${chat.title || 'Untitled'}"?`,
                    body: "This chat and its history will be removed. This can't be undone.",
                    confirmLabel: 'Delete',
                    danger: true,
                });
                if (!ok) return;
                try {
                    await fetch(`/api/chats/${encodeURIComponent(chat.id)}`, { method: 'DELETE' });
                    if (chat.id === currentChatId) {
                        // Was the active chat — spin up a fresh one over the existing
                        // WebSocket instead of reloading the page (which left the
                        // sidebar empty for ~1s while everything re-mounted).
                        ws.send({ type: 'new_chat' });
                    }
                    loadChatList();
                } catch (err) {
                    console.error('Failed to delete chat:', err);
                }
            };

            item.appendChild(icon);
            item.appendChild(title);
            item.appendChild(del);
            $chatList.appendChild(item);
        }
    } catch (e) {
        console.error('Failed to load chats:', e);
    }
}

// --- App dialog (replaces window.confirm / window.alert) ---
const $appDialog = document.getElementById('app-dialog');
const $appDialogTitle = document.getElementById('app-dialog-title');
const $appDialogBody = document.getElementById('app-dialog-body');
const $appDialogCancel = document.getElementById('app-dialog-cancel');
const $appDialogConfirm = document.getElementById('app-dialog-confirm');

let _appDialogResolver = null;
// While locked (e.g. mid-restart) the dialog ignores Escape/Enter/backdrop —
// closing it wouldn't cancel the operation, just hide its progress.
let _appDialogLocked = false;

function _closeAppDialog(result) {
    if (!$appDialog || _appDialogLocked) return;
    $appDialog.classList.add('hidden');
    const r = _appDialogResolver;
    _appDialogResolver = null;
    if (r) r(result);
}

function showConfirmDialog({ title, body, confirmLabel = 'Confirm', cancelLabel = 'Cancel', danger = false } = {}) {
    return new Promise((resolve) => {
        if (!$appDialog) { resolve(window.confirm(`${title}\n\n${body || ''}`)); return; }
        $appDialogTitle.textContent = title || '';
        $appDialogBody.textContent = body || '';
        $appDialogConfirm.textContent = confirmLabel;
        $appDialogCancel.textContent = cancelLabel;
        $appDialogConfirm.classList.toggle('task-action-danger', !!danger);
        $appDialogConfirm.classList.toggle('task-action-primary', !danger);
        $appDialogCancel.hidden = false;
        _appDialogResolver = resolve;
        $appDialog.classList.remove('hidden');
        setTimeout(() => $appDialogConfirm.focus(), 0);
    });
}

function showAlertDialog({ title, body, confirmLabel = 'OK' } = {}) {
    return new Promise((resolve) => {
        if (!$appDialog) { window.alert(`${title}\n\n${body || ''}`); resolve(); return; }
        $appDialogTitle.textContent = title || '';
        $appDialogBody.textContent = body || '';
        $appDialogConfirm.textContent = confirmLabel;
        $appDialogConfirm.classList.remove('task-action-danger');
        $appDialogConfirm.classList.add('task-action-primary');
        $appDialogCancel.hidden = true;
        _appDialogResolver = () => resolve();
        $appDialog.classList.remove('hidden');
        setTimeout(() => $appDialogConfirm.focus(), 0);
    });
}

function showProgressDialog({ title, body } = {}) {
    // Modal progress state (spinner, no buttons, not dismissable). Returns
    // handles to update the copy and to release/close the dialog.
    if (!$appDialog) return { update() {}, close() {} };
    _appDialogLocked = false;
    $appDialogTitle.textContent = title || '';
    $appDialogBody.innerHTML = `<span class="button-spinner app-dialog-spinner" aria-hidden="true"></span><span></span>`;
    $appDialogBody.lastElementChild.textContent = body || '';
    $appDialogConfirm.hidden = true;
    $appDialogCancel.hidden = true;
    _appDialogResolver = null;
    _appDialogLocked = true;
    $appDialog.classList.remove('hidden');
    return {
        update({ title: nextTitle, body: nextBody } = {}) {
            if (nextTitle !== undefined) $appDialogTitle.textContent = nextTitle;
            if (nextBody !== undefined) $appDialogBody.lastElementChild.textContent = nextBody;
        },
        close() {
            _appDialogLocked = false;
            $appDialogConfirm.hidden = false;
            $appDialog.classList.add('hidden');
        },
    };
}

if ($appDialogConfirm) $appDialogConfirm.onclick = () => _closeAppDialog(true);
if ($appDialogCancel) $appDialogCancel.onclick = () => _closeAppDialog(false);
if ($appDialog) {
    $appDialog.addEventListener('click', (e) => {
        if (e.target === $appDialog) _closeAppDialog(false);
    });
    document.addEventListener('keydown', (e) => {
        if ($appDialog.classList.contains('hidden')) return;
        if (e.key === 'Escape') { e.preventDefault(); _closeAppDialog(false); }
        if (e.key === 'Enter') { e.preventDefault(); _closeAppDialog(true); }
    });
}

// --- Tasks ---
let taskListWs = null;
let taskListCache = [];
let taskDetailWs = null;
let taskDetailId = null;
let taskDetailCache = null;
const TERMINAL_STATUSES = new Set(['done', 'failed', 'cancelled']);

function formatTaskTimestamp(ts) {
    if (!ts) return '';
    // Backend serializes datetime.isoformat(); display the local-ish prefix.
    return ts.slice(0, 16).replace('T', ' ');
}

function formatFriendlyDate(value) {
    if (!value) return '';
    // Accept either an ISO timestamp or a datetime-local "YYYY-MM-DDTHH:MM" value.
    const d = new Date(value);
    if (isNaN(d.getTime())) return '';
    const now = new Date();
    const sameDay = d.toDateString() === now.toDateString();
    const tomorrow = new Date(now);
    tomorrow.setDate(now.getDate() + 1);
    const isTomorrow = d.toDateString() === tomorrow.toDateString();
    const timeStr = d.toLocaleTimeString(undefined, { hour: 'numeric', minute: '2-digit' });
    if (sameDay) return `Today at ${timeStr}`;
    if (isTomorrow) return `Tomorrow at ${timeStr}`;
    const dateStr = d.toLocaleDateString(undefined, {
        weekday: 'short', month: 'short', day: 'numeric', year: 'numeric',
    });
    return `${dateStr} • ${timeStr}`;
}

function renderTaskListItems() {
    if (!taskListCache || taskListCache.length === 0) {
        $taskList.innerHTML = '<p class="task-empty-note">No tasks yet. Use “+ New Task” to create one.</p>';
        return;
    }
    $taskList.innerHTML = '';
    for (const task of taskListCache) {
        const item = document.createElement('div');
        item.className = 'task-item';
        item.dataset.taskId = String(task.id);
        item.innerHTML = `
            <div class="task-title">${escapeHtml(task.title || 'Untitled')}</div>
            <div class="task-meta">
                <span class="task-status ${escapeHtml(task.status)}">${escapeHtml(task.status)}</span>
                <span>${escapeHtml(formatTaskTimestamp(task.created_at))}</span>
            </div>
        `;
        item.onclick = () => openTaskDetail(task.id);
        $taskList.appendChild(item);
    }
}

async function loadTasks() {
    try {
        const res = await fetch('/api/tasks');
        taskListCache = await res.json();
        renderTaskListItems();
        connectTaskListWs();
    } catch (e) {
        $taskList.innerHTML = '<p style="color: var(--error)">Failed to load tasks.</p>';
    }
}

function connectTaskListWs() {
    if (taskListWs && taskListWs.readyState <= 1) return;
    try {
        taskListWs = new WebSocket(wsUrl('/ws/tasks'));
    } catch (_) {
        return;
    }
    taskListWs.onmessage = async (evt) => {
        let msg;
        try { msg = JSON.parse(evt.data); } catch { return; }
        if (msg.type === 'snapshot' && Array.isArray(msg.tasks)) {
            taskListCache = msg.tasks;
            renderTaskListItems();
            return;
        }
        // Any task_* event prompts a quick refresh of the list cache; cheap
        // because it's a single SQLite query and keeps statuses live.
        if (msg.type === 'task_created' || msg.type === 'task_updated' || msg.type === 'task_deleted') {
            try {
                const res = await fetch('/api/tasks');
                taskListCache = await res.json();
                renderTaskListItems();
            } catch (_) { /* ignore — next event will retry */ }
        }
    };
    taskListWs.onclose = () => {
        taskListWs = null;
        // Reconnect only if the task view is still active; avoids burning sockets.
        if (currentView === 'task') {
            setTimeout(connectTaskListWs, 2000);
        }
    };
}

// --- Task detail panel ---
const $taskPanel = document.getElementById('task-panel');
const $taskPanelBackdrop = document.getElementById('task-panel-backdrop');
const $taskPanelBody = document.getElementById('task-panel-body');
const $taskPanelTitle = document.getElementById('task-panel-title');
const $taskPanelStatus = document.getElementById('task-panel-status');
const $taskPanelClose = document.getElementById('task-panel-close');

async function openTaskDetail(taskId) {
    taskDetailId = taskId;
    $taskPanel.classList.remove('hidden');
    $taskPanel.setAttribute('aria-hidden', 'false');
    $taskPanelBackdrop.classList.remove('hidden');
    $taskPanelBody.innerHTML = '<p class="task-empty-note">Loading…</p>';
    $taskPanelTitle.textContent = '';
    $taskPanelStatus.textContent = '';
    $taskPanelStatus.className = 'task-status';

    try {
        const res = await fetch(`/api/tasks/${taskId}`);
        if (!res.ok) throw new Error('not found');
        taskDetailCache = await res.json();
        renderTaskDetail(taskDetailCache);
        connectTaskDetailWs(taskId);
    } catch (e) {
        $taskPanelBody.innerHTML = `<p style="color: var(--error)">Could not load task: ${escapeHtml(String(e))}</p>`;
    }
}

function closeTaskDetail() {
    $taskPanel.classList.add('hidden');
    $taskPanel.setAttribute('aria-hidden', 'true');
    $taskPanelBackdrop.classList.add('hidden');
    taskDetailId = null;
    taskDetailCache = null;
    if (taskDetailWs) {
        try { taskDetailWs.close(); } catch (_) {}
        taskDetailWs = null;
    }
}

function renderTaskDetail(task) {
    $taskPanelTitle.textContent = task.title || 'Untitled';
    $taskPanelStatus.textContent = task.status;
    $taskPanelStatus.className = `task-status ${task.status}`;

    const plan = Array.isArray(task.plan) ? task.plan : [];
    const history = Array.isArray(task.history) ? task.history : [];
    const isTerminal = TERMINAL_STATUSES.has(task.status);
    const isPaused = task.status === 'paused';
    const isBlocked = task.status === 'blocked';

    const actionButtons = [];
    if (!isTerminal) {
        if (isPaused || isBlocked) {
            actionButtons.push('<button class="task-action-btn task-action-primary" data-action="resume">Resume</button>');
        } else {
            actionButtons.push('<button class="task-action-btn" data-action="pause">Pause</button>');
        }
        // Labelled "Stop Task" so it isn't mistaken for "close this panel".
        actionButtons.push('<button class="task-action-btn task-action-secondary" data-action="cancel">Stop Task</button>');
    } else if (task.status === 'cancelled' || task.status === 'failed' || task.status === 'done') {
        actionButtons.push('<button class="task-action-btn task-action-primary" data-action="restart">Restart</button>');
    }
    actionButtons.push('<button class="task-action-btn task-action-danger" data-action="delete">Delete</button>');

    // The plan is the agent's live todo list. Each item carries its own status
    // (pending / in_progress / done) which it maintains as it works.
    const planHtml = plan.length
        ? `<ol class="task-plan-list">${plan.map((step, i) => {
            const status = (step && step.status) || (i < task.current_step ? 'done' : '');
            const isDone = status === 'done';
            const isCurrent = status === 'in_progress' && !isTerminal;
            const cls = isCurrent ? 'current' : isDone ? 'done' : '';
            const mark = isDone ? '✓' : (i + 1) + '.';
            return `<li class="task-plan-step ${cls}">
                <span class="task-plan-step-index">${mark}</span>
                <span>${escapeHtml(step.description || '')}</span>
            </li>`;
        }).join('')}</ol>`
        : '<p class="task-empty-note">No todo list yet — Lumi will draft one after it looks around.</p>';

    // Runtime-retry backoff is now tracked on the task (transient model/network
    // outage), so the whole task is waiting to retry — not a single step.
    const constraints = (task.constraints && typeof task.constraints === 'object') ? task.constraints : {};

    // Pending protected-action approval (§6.3) — the task is parked until the
    // owner approves or denies, here or from Telegram (/approve, /deny).
    const pendingApproval = (constraints._pending_approval && typeof constraints._pending_approval === 'object')
        ? constraints._pending_approval
        : null;
    const approvalBannerHtml = (!isTerminal && pendingApproval)
        ? `<div class="task-retry-banner">
                <div><strong>Approval needed</strong> — Lumi wants to run
                    <code>${escapeHtml(pendingApproval.tool || '?')}</code>:</div>
                <div class="task-retry-reason"><code>${escapeHtml(pendingApproval.summary || '')}</code></div>
                <div class="task-actions-row" style="margin-top:8px">
                    <button class="task-action-btn task-action-primary" data-action="approve">Approve once</button>
                    <button class="task-action-btn task-action-secondary" data-action="deny">Deny</button>
                </div>
           </div>`
        : '';

    const retryCount = Number(constraints._runtime_retries || 0);
    const retryBannerHtml = (!isTerminal && retryCount > 0)
        ? `<div class="task-retry-banner">
                <div><strong>Runtime hiccup</strong> — retry attempt ${retryCount}.
                    Next try ${escapeHtml(formatFriendlyDate(task.next_run_at) || task.next_run_at || 'soon')}.</div>
                <div class="task-retry-reason">Model/runtime was briefly unreachable; backing off instead of failing.</div>
           </div>`
        : '';

    // Waiting banner — the task is parked on a real external wait (a build, a
    // reply, a time window). Intentional, not a stall: it resumes on its own.
    const waitingReason = constraints._wait_reason || '';
    const waitUntil = constraints._wait_until || task.next_run_at || '';
    const waitingBannerHtml = (!isTerminal && retryCount === 0 && waitingReason)
        ? `<div class="task-wait-banner">
                <div><strong>Waiting on something external</strong> — resumes
                    ${escapeHtml(formatFriendlyDate(waitUntil) || waitUntil || 'soon')}.</div>
                <div class="task-wait-reason">${escapeHtml(waitingReason)}</div>
           </div>`
        : '';

    const historyHtml = history.length
        ? history.slice().reverse().map(entry => renderHistoryEntry(entry)).join('')
        : '<p class="task-empty-note">No activity recorded yet.</p>';

    const resultHtml = task.result
        ? `<div class="task-result">${escapeHtml(task.result)}</div>`
        : '';

    const toDtLocal = (iso) => {
        if (!iso) return '';
        // datetime-local needs YYYY-MM-DDTHH:MM (no seconds, no zone)
        return iso.slice(0, 16);
    };

    $taskPanelBody.innerHTML = `
        <div class="task-actions-row">${actionButtons.join('')}</div>
        ${approvalBannerHtml}
        ${retryBannerHtml}
        ${waitingBannerHtml}

        <section class="task-panel-section">
            <h4>Details</h4>
            <label class="task-field">
                <span>Title</span>
                <input type="text" data-edit="title" value="${escapeHtml(task.title || '')}" ${isTerminal ? 'disabled' : ''}>
            </label>
            <label class="task-field">
                <span>Goal</span>
                <textarea rows="3" data-edit="goal" ${isTerminal ? 'disabled' : ''}>${escapeHtml(task.goal || '')}</textarea>
            </label>
            <div class="task-edit-row">
                <label class="task-field" style="flex:1">
                    <span>Due at</span>
                    <input type="datetime-local" data-edit="due_at" data-preview="due_at-preview" value="${escapeHtml(toDtLocal(task.due_at))}" ${isTerminal ? 'disabled' : ''}>
                    <span class="task-date-preview" id="due_at-preview">${escapeHtml(formatFriendlyDate(task.due_at) || 'No deadline')}</span>
                </label>
                <label class="task-field" style="flex:1">
                    <span>Next run</span>
                    <input type="datetime-local" data-edit="next_run_at" data-preview="next_run_at-preview" value="${escapeHtml(toDtLocal(task.next_run_at))}" ${isTerminal ? 'disabled' : ''}>
                    <span class="task-date-preview" id="next_run_at-preview">${escapeHtml(formatFriendlyDate(task.next_run_at) || 'Not scheduled')}</span>
                </label>
            </div>
            ${isTerminal ? '' : '<button class="task-action-btn task-action-primary" data-action="save">Save changes</button>'}
        </section>

        ${resultHtml ? `<section class="task-panel-section"><h4>Result</h4>${resultHtml}</section>` : ''}

        <section class="task-panel-section">
            <h4>Todo list${plan.length ? ` (${plan.filter(s => (s.status || '') === 'done' || (plan.indexOf(s) < task.current_step)).length}/${plan.length} done)` : ''}</h4>
            ${planHtml}
        </section>

        <section class="task-panel-section">
            <h4>Activity</h4>
            <div class="task-activity" id="task-activity">${historyHtml}</div>
        </section>

        <section class="task-panel-section">
            <h4>Workspace</h4>
            <p class="task-empty-note">${escapeHtml(task.workspace_path || 'not set')}</p>
        </section>
    `;

    // Wire action buttons
    $taskPanelBody.querySelectorAll('[data-action]').forEach(btn => {
        btn.onclick = () => handleTaskAction(task.id, btn.dataset.action);
    });

    // Live human-readable previews for the datetime inputs.
    $taskPanelBody.querySelectorAll('[data-preview]').forEach(input => {
        const previewEl = document.getElementById(input.dataset.preview);
        if (!previewEl) return;
        input.addEventListener('input', () => {
            const friendly = formatFriendlyDate(input.value);
            const isDue = input.dataset.edit === 'due_at';
            previewEl.textContent = friendly || (isDue ? 'No deadline' : 'Not scheduled');
        });
    });
}

function renderHistoryEntry(entry) {
    const type = entry.type || 'event';
    const ts = formatTaskTimestamp(entry.timestamp);
    let text = '';
    let label = type;
    let extraClass = '';
    if (type === 'plan_generated') {
        const steps = Array.isArray(entry.steps) ? entry.steps : [];
        text = `Plan generated with ${entry.step_count || steps.length} step${(entry.step_count || steps.length) === 1 ? '' : 's'}.`;
    } else if (type === 'step_result') {
        text = `Step ${(entry.step_index ?? 0) + 1} [${entry.verdict || '?'}]: ${entry.summary || ''}`;
    } else if (type === 'planning_retry') {
        text = `Planning retry #${entry.attempt} — next at ${formatTaskTimestamp(entry.next_run_at)}. ${entry.error || ''}`;
    } else if (type === 'workspace_fallback') {
        text = `Workspace missing (${entry.recorded}); using fallback ${entry.fallback}.`;
    } else if (type === 'step_activity') {
        // Live progress events emitted from inside an in-flight step. Render
        // them compactly so the activity feed reads like a running log.
        const stepNum = (entry.step_index ?? 0) + 1;
        const kind = entry.kind || 'activity';
        extraClass = 'task-activity-live';
        if (kind === 'thinking') {
            label = `step ${stepNum} · thinking`;
            text = `Round ${entry.round || '?'} — model is deciding next action.`;
        } else if (kind === 'tool') {
            label = `step ${stepNum} · tool`;
            text = `${entry.tool || '?'}${entry.detail ? ` — ${entry.detail}` : ''}`;
        } else if (kind === 'tool_error') {
            label = `step ${stepNum} · tool error`;
            extraClass = 'task-activity-live task-activity-error';
            text = `${entry.tool || '?'} failed: ${entry.detail || ''}`;
        } else if (kind === 'answer') {
            label = `step ${stepNum} · drafting answer`;
            text = entry.detail || '(no preview)';
        } else if (kind === 'error') {
            label = `step ${stepNum} · error`;
            extraClass = 'task-activity-live task-activity-error';
            text = entry.detail || '';
        } else {
            label = `step ${stepNum} · ${kind}`;
            text = entry.detail || JSON.stringify(entry);
        }
    } else if (type === 'step_retry') {
        text = `Runtime retry #${entry.attempt || '?'} — next at ${formatTaskTimestamp(entry.next_run_at)}. ${entry.reason || ''}`;
        extraClass = 'task-activity-error';
    } else if (type === 'step_wait' || type === 'task_wait') {
        label = 'waiting';
        text = `Waiting for ${entry.reason || 'something external'} — resumes ${formatTaskTimestamp(entry.resume_at)}.`;
        extraClass = 'task-activity-wait';
    } else if (type === 'task_started') {
        text = 'Task started — looking at the workspace before acting.';
    } else if (type === 'todos_updated') {
        const total = entry.total ?? (Array.isArray(entry.todos) ? entry.todos.length : 0);
        label = 'todo list';
        text = `Updated todo list (${entry.done ?? 0}/${total} done).`;
    } else if (type === 'activity') {
        // Live progress from inside the continuous task loop.
        const kind = entry.kind || 'activity';
        extraClass = 'task-activity-live';
        if (kind === 'thinking') {
            label = 'thinking';
            text = `Round ${entry.round || '?'} — deciding the next action.`;
        } else if (kind === 'tool') {
            label = 'tool';
            text = `${entry.tool || '?'}${entry.detail ? ` — ${entry.detail}` : ''}`;
        } else if (kind === 'tool_error') {
            label = 'tool error';
            extraClass = 'task-activity-live task-activity-error';
            text = `${entry.tool || '?'} failed: ${entry.detail || ''}`;
        } else if (kind === 'answer') {
            label = 'note';
            text = entry.detail || '(no preview)';
        } else if (kind === 'wait') {
            label = 'waiting';
            extraClass = 'task-activity-live task-activity-wait';
            text = entry.detail || 'waiting on something external';
        } else {
            label = kind;
            text = entry.detail || JSON.stringify(entry);
        }
    } else {
        text = entry.summary || entry.description || JSON.stringify(entry);
    }
    return `<div class="task-activity-entry ${extraClass}">
        <div class="task-activity-meta"><span>${escapeHtml(label)}</span><span>${escapeHtml(ts)}</span></div>
        <div class="task-activity-text">${escapeHtml(text)}</div>
    </div>`;
}

async function handleTaskAction(taskId, action) {
    try {
        // Destructive actions need a confirm — closing the panel by accident
        // shouldn't kill a running task.
        const title = taskDetailCache?.title || 'this task';
        if (action === 'cancel') {
            const ok = await showConfirmDialog({
                title: `Stop "${title}"?`,
                body: 'The runner will halt and the task will move to the cancelled state. You can restart it later.',
                confirmLabel: 'Stop Task',
                danger: true,
            });
            if (!ok) return;
        }
        if (action === 'delete') {
            const ok = await showConfirmDialog({
                title: `Delete "${title}"?`,
                body: 'This removes all of its history permanently and cannot be undone.',
                confirmLabel: 'Delete',
                danger: true,
            });
            if (!ok) return;
        }

        if (action === 'pause' || action === 'resume' || action === 'cancel' || action === 'restart' || action === 'approve' || action === 'deny') {
            const res = await fetch(`/api/tasks/${taskId}/${action}`, { method: 'POST' });
            if (!res.ok) throw new Error((await res.json()).error || `Failed to ${action}`);
            taskDetailCache = await res.json();
            renderTaskDetail(taskDetailCache);
        } else if (action === 'delete') {
            const res = await fetch(`/api/tasks/${taskId}`, { method: 'DELETE' });
            if (!res.ok) throw new Error('Delete failed');
            closeTaskDetail();
            loadTasks();
        } else if (action === 'save') {
            const payload = {};
            $taskPanelBody.querySelectorAll('[data-edit]').forEach(el => {
                const key = el.dataset.edit;
                const val = el.value;
                // Send empty datetime fields as null so the server can clear them.
                if (key === 'due_at' || key === 'next_run_at') {
                    payload[key] = val ? val : null;
                } else {
                    payload[key] = val;
                }
            });
            const res = await fetch(`/api/tasks/${taskId}`, {
                method: 'PATCH',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(payload),
            });
            if (!res.ok) throw new Error((await res.json()).error || 'Save failed');
            taskDetailCache = await res.json();
            renderTaskDetail(taskDetailCache);
        }
    } catch (e) {
        showAlertDialog({
            title: 'Action failed',
            body: e.message || String(e),
        });
    }
}

function connectTaskDetailWs(taskId) {
    if (taskDetailWs) {
        try { taskDetailWs.close(); } catch (_) {}
        taskDetailWs = null;
    }
    try {
        taskDetailWs = new WebSocket(wsUrl(`/ws/tasks?task_id=${taskId}`));
    } catch (_) { return; }
    taskDetailWs.onmessage = async (evt) => {
        let msg;
        try { msg = JSON.parse(evt.data); } catch { return; }
        if (taskDetailId !== taskId) return; // panel was closed/switched

        if (msg.type === 'snapshot' && msg.task) {
            taskDetailCache = msg.task;
            renderTaskDetail(taskDetailCache);
            return;
        }
        if (msg.type === 'history_appended' && taskDetailCache) {
            taskDetailCache.history = taskDetailCache.history || [];
            taskDetailCache.history.push(msg.entry);
            const activityEl = document.getElementById('task-activity');
            if (activityEl) {
                activityEl.insertAdjacentHTML('afterbegin', renderHistoryEntry(msg.entry));
            }
            return;
        }
        if (msg.type === 'task_updated' || msg.type === 'task_created') {
            try {
                const res = await fetch(`/api/tasks/${taskId}`);
                if (res.ok) {
                    taskDetailCache = await res.json();
                    renderTaskDetail(taskDetailCache);
                }
            } catch (_) {}
        }
        if (msg.type === 'task_deleted') {
            closeTaskDetail();
            loadTasks();
        }
    };
    taskDetailWs.onclose = () => {
        // If the panel is still open, retry once after a beat.
        if (taskDetailId === taskId) {
            setTimeout(() => {
                if (taskDetailId === taskId) connectTaskDetailWs(taskId);
            }, 2000);
        }
    };
}

if ($taskPanelClose) $taskPanelClose.onclick = closeTaskDetail;
if ($taskPanelBackdrop) $taskPanelBackdrop.onclick = closeTaskDetail;

// --- New task modal ---
const $newTaskBtn = document.getElementById('new-task-btn');
const $newTaskModal = document.getElementById('new-task-modal');
const $newTaskClose = document.getElementById('new-task-close');
const $newTaskCancel = document.getElementById('new-task-cancel');
const $newTaskForm = document.getElementById('new-task-form');
const $newTaskError = document.getElementById('new-task-error');

function openNewTaskModal() {
    $newTaskForm.reset();
    $newTaskError.classList.add('hidden');
    $newTaskModal.classList.remove('hidden');
}
function closeNewTaskModal() {
    $newTaskModal.classList.add('hidden');
}
if ($newTaskBtn) $newTaskBtn.onclick = openNewTaskModal;
if ($newTaskClose) $newTaskClose.onclick = closeNewTaskModal;
if ($newTaskCancel) $newTaskCancel.onclick = closeNewTaskModal;

// Live previews on the new-task modal date inputs
['start', 'due'].forEach((key) => {
    const input = document.getElementById(`new-task-${key}`);
    const preview = document.getElementById(`new-task-${key}-preview`);
    if (!input || !preview) return;
    const fallback = key === 'start' ? 'Starts immediately' : 'No deadline';
    input.addEventListener('input', () => {
        preview.textContent = formatFriendlyDate(input.value) || fallback;
    });
});
if ($newTaskForm) {
    $newTaskForm.onsubmit = async (e) => {
        e.preventDefault();
        $newTaskError.classList.add('hidden');
        const payload = {
            title: document.getElementById('new-task-title').value.trim(),
            goal: document.getElementById('new-task-goal').value.trim(),
            start_at: document.getElementById('new-task-start').value || null,
            due_at: document.getElementById('new-task-due').value || null,
        };
        try {
            const res = await fetch('/api/tasks', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(payload),
            });
            if (!res.ok) {
                const err = await res.json().catch(() => ({}));
                throw new Error(err.error || `Server returned ${res.status}`);
            }
            const created = await res.json();
            closeNewTaskModal();
            await loadTasks();
            if (created && created.id) openTaskDetail(created.id);
        } catch (err) {
            $newTaskError.textContent = err.message || 'Could not create task.';
            $newTaskError.classList.remove('hidden');
        }
    };
}

// --- Settings ---
async function loadSettings() {
    try {
        const res = await fetch('/api/settings');
        if (!res.ok) {
            throw new Error(`Settings API returned ${res.status}`);
        }
        const settings = await res.json();
        settingsState = settings;
        requiresModelSetup = !!settings.setup_required;

        const modelOptions = (settings.installed_models || [])
            .map(name => `<option value="${escapeHtml(name)}">${escapeHtml(name)}</option>`)
            .join('');
        const banner = settings.setup_required ? `
            <div class="settings-banner">
                No primary model is configured yet. Pick one below before using the web UI.
            </div>
        ` : '';
        const modelsError = settings.installed_models_error
            ? `<div class="settings-error">Could not load installed models from Ollama: ${escapeHtml(settings.installed_models_error)}</div>`
            : '';
        const restartBanner = settings.restart_required ? `
            <div class="settings-banner settings-restart-banner">
                <div>
                    <strong>Restart needed.</strong>
                    Your environment file changed after LumaKit started
                    (${escapeHtml((settings.restart_reasons || []).join(', '))}).
                    The new values won't be used until the backend restarts.
                </div>
                ${settings.restart_supported !== false
                    ? '<button type="button" id="restart-backend-btn" class="settings-btn primary">Restart Backend</button>'
                    : '<div class="settings-subgroup-hint">From a terminal, run <code>lumakit stop</code>, then <code>lumakit open</code>.</div>'}
            </div>
        ` : '';
        const approvalsOn = !!settings.require_tool_approvals;
        const approvalStateLabel = approvalsOn ? 'On' : 'Off';

        const provider = settings.llm_provider || 'ollama';
        const providerKeySet = settings.api_keys_set || {};
        const providerOptions = ['ollama', 'anthropic', 'openai', 'xai']
            .map(p => `<option value="${p}" ${p === provider ? 'selected' : ''}>${{ollama: 'Ollama (local)', anthropic: 'Anthropic (Claude)', openai: 'OpenAI (GPT)', xai: 'xAI (Grok)'}[p]}</option>`)
            .join('');
        const keyPlaceholder = (p) => providerKeySet[p]
            ? 'Key found in your environment — leave blank to use it'
            : 'Paste your API key';

        $settingsContent.innerHTML = `
            ${banner}
            ${restartBanner}
            <div class="settings-card">
                <h3>Model Provider</h3>
                <div class="settings-note">
                    Run on local Ollama (private), or bring an API key for Claude, GPT, or Grok.
                    Keys already set in .env are detected automatically; anything you paste here
                    is stored server-side only and never shown again.
                </div>
                <form id="provider-form" class="settings-form">
                    <div class="settings-field">
                        <label for="provider-select">Provider</label>
                        <select id="provider-select" class="settings-select">${providerOptions}</select>
                    </div>
                    <div class="settings-field" id="api-key-field" ${provider === 'ollama' ? 'style="display:none"' : ''}>
                        <label for="api-key-input">API Key <span id="api-key-status" class="setting-source-pill" ${providerKeySet[provider] ? '' : 'style="display:none"'}>key detected</span></label>
                        <input id="api-key-input" class="settings-input" type="password" value="" placeholder="${keyPlaceholder(provider)}" autocomplete="off">
                    </div>
                    <div class="settings-actions">
                        <button type="submit" class="settings-btn primary">Save Provider</button>
                    </div>
                </form>
            </div>
            <div class="settings-card">
                <h3>Runtime Models</h3>
                <div class="settings-note">
                    Choose the model LumaKit should use by default in the web UI. These settings persist in the app data directory and override the .env defaults until you reset them.
                </div>
                <form id="settings-form" class="settings-form">
                    <div class="settings-field">
                        <label for="primary-model-input">Primary Model</label>
                        <input id="primary-model-input" class="settings-input" type="text" value="${escapeHtml(settings.app_primary_model || settings.model || '')}" placeholder="e.g. glm-5:cloud or qwen3">
                    </div>
                    <div class="settings-field">
                        <label for="fallback-model-input">Fallback Model</label>
                        <input id="fallback-model-input" class="settings-input" type="text" value="${escapeHtml(settings.app_fallback_model || settings.fallback_model || '')}" placeholder="Optional">
                    </div>
                    <div class="settings-field">
                        <label for="installed-models-select">Detected Ollama Models</label>
                        <select id="installed-models-select" class="settings-select">
                            <option value="">Choose an installed model...</option>
                            ${modelOptions}
                        </select>
                    </div>
                    ${modelsError}
                    <div class="settings-actions">
                        <button type="submit" class="settings-btn primary">Save Models</button>
                        <button type="button" id="reset-model-settings" class="settings-btn secondary">Reset To .env Defaults</button>
                    </div>
                </form>
            </div>
            <div class="settings-card">
                <div class="settings-card-header">
                    <h3>Tool Permissions</h3>
                    <div class="settings-radio-group" role="radiogroup" aria-label="Tool approvals">
                        <label class="settings-radio-option ${approvalsOn ? 'selected' : ''}">
                            <input type="radio" name="tool-approvals" value="on" ${approvalsOn ? 'checked' : ''}>
                            <span>On</span>
                        </label>
                        <label class="settings-radio-option ${!approvalsOn ? 'selected' : ''}">
                            <input type="radio" name="tool-approvals" value="off" ${!approvalsOn ? 'checked' : ''}>
                            <span>Off</span>
                        </label>
                    </div>
                </div>
                <div class="settings-permission-copy">
                    Tool Permissions is currently <strong>${approvalStateLabel}</strong>.
                    When Tool Permissions is off, Lumi can use ordinary tools without asking permission.
                    When Tool Permissions is on, tool use requires user approval.
                    Delete file and git stage, commit, and push always require approval.
                </div>
            </div>
            <div class="settings-card">
                <h3>Current Configuration</h3>
                <div class="settings-note">
                    A read-only view of what LumaKit is actually using right now, and where each value came from.
                </div>

                <div class="settings-subgroup">
                    <div class="settings-subgroup-label">Active models</div>
                    <div class="setting-row">
                        <span class="setting-label">Primary</span>
                        <span class="setting-value">${settings.model || 'not set'} <span class="setting-source-pill">${settings.model_source || 'unknown'}</span></span>
                    </div>
                    <div class="setting-row">
                        <span class="setting-label">Fallback</span>
                        <span class="setting-value">${settings.fallback_model || 'none'} <span class="setting-source-pill">${settings.fallback_model_source || 'unknown'}</span></span>
                    </div>
                </div>

                <div class="settings-subgroup">
                    <div class="settings-subgroup-label">App overrides <span class="settings-subgroup-hint">(set via this Settings page)</span></div>
                    <div class="setting-row">
                        <span class="setting-label">Primary override</span>
                        <span class="setting-value">${settings.app_primary_model || 'none'}</span>
                    </div>
                    <div class="setting-row">
                        <span class="setting-label">Fallback override</span>
                        <span class="setting-value">${settings.app_fallback_model || 'none'}</span>
                    </div>
                </div>

                <div class="settings-subgroup">
                    <div class="settings-subgroup-label">From .env <span class="settings-subgroup-hint">(defaults shipped with the project)</span></div>
                    <div class="setting-row">
                        <span class="setting-label">Primary</span>
                        <span class="setting-value">${settings.env_primary_model || 'not set'}</span>
                    </div>
                    <div class="setting-row">
                        <span class="setting-label">Fallback</span>
                        <span class="setting-value">${settings.env_fallback_model || 'none'}</span>
                    </div>
                    <div class="setting-row">
                        <span class="setting-label">Optional local model</span>
                        <span class="setting-value">${settings.local_model || 'not set'}</span>
                    </div>
                </div>

                <div class="settings-subgroup">
                    <div class="settings-subgroup-label">System</div>
                    <div class="setting-row">
                        <span class="setting-label">Data directory</span>
                        <span class="setting-value">${settings.data_dir}</span>
                    </div>
                </div>
            </div>
        `;

        const $primaryModelInput = document.getElementById('primary-model-input');
        const $fallbackModelInput = document.getElementById('fallback-model-input');
        const $installedModelsSelect = document.getElementById('installed-models-select');
        const $settingsForm = document.getElementById('settings-form');
        const $resetModelSettings = document.getElementById('reset-model-settings');
        const $toolApprovalInputs = $settingsContent.querySelectorAll('input[name="tool-approvals"]');
        const $providerForm = document.getElementById('provider-form');
        const $providerSelect = document.getElementById('provider-select');
        const $apiKeyField = document.getElementById('api-key-field');
        const $apiKeyInput = document.getElementById('api-key-input');

        $providerSelect?.addEventListener('change', () => {
            const p = $providerSelect.value;
            if ($apiKeyField) {
                $apiKeyField.style.display = p === 'ollama' ? 'none' : '';
            }
            if ($apiKeyInput) {
                $apiKeyInput.placeholder = keyPlaceholder(p);
            }
            const $keyStatus = document.getElementById('api-key-status');
            if ($keyStatus) {
                $keyStatus.style.display = providerKeySet[p] ? '' : 'none';
            }
        });

        $providerForm?.addEventListener('submit', async (e) => {
            e.preventDefault();
            const selectedProvider = $providerSelect?.value || 'ollama';
            const providerChanged = selectedProvider !== provider;
            const payload = { llm_provider: selectedProvider };
            const key = ($apiKeyInput?.value || '').trim();
            if (key) payload.llm_api_key = key;
            const saved = await saveSettings(payload, {
                successMessage: 'Provider settings saved. New chats use the new provider.',
                busyLabel: 'Saving...',
            });
            if (saved && (providerChanged || key)) {
                await offerBackendRestart({
                    title: 'Restart to apply everywhere?',
                    body: 'Your provider settings are saved and new chats already use them, '
                        + 'but background tasks and other surfaces keep the previous configuration '
                        + 'until LumaKit restarts.',
                });
            }
        });

        document.getElementById('restart-backend-btn')?.addEventListener('click', async () => {
            const ok = await showConfirmDialog({
                title: 'Restart LumaKit?',
                body: 'The backend will restart to pick up your environment changes. '
                    + 'This takes a few seconds; the app reloads automatically when it\'s back.',
                confirmLabel: 'Restart now',
                cancelLabel: 'Cancel',
            });
            if (ok) await performBackendRestart();
        });

        if (pendingSettingsFocus) {
            pendingSettingsFocus = false;
            requestAnimationFrame(() => {
                $primaryModelInput?.focus();
                $primaryModelInput?.select();
            });
        }

        $installedModelsSelect?.addEventListener('change', () => {
            if ($installedModelsSelect.value) {
                $primaryModelInput.value = $installedModelsSelect.value;
            }
        });

        $settingsForm?.addEventListener('submit', async (e) => {
            e.preventDefault();
            const primary_model = $primaryModelInput.value.trim();
            const fallback_model = $fallbackModelInput.value.trim();
            if (!primary_model && !(settings.env_primary_model || '').trim()) {
                loadSettingsError('Choose a primary model or set OLLAMA_MODEL in .env first.');
                return;
            }
            await saveSettings(
                { primary_model, fallback_model },
                {
                    successMessage: `Saved model settings. Using ${primary_model || settings.env_primary_model}.`,
                    busyLabel: 'Saving...',
                },
            );
        });

        $toolApprovalInputs.forEach(input => {
            input.addEventListener('change', async () => {
                if (!input.checked) return;
                const enabled = input.value === 'on';
                const payload = { require_tool_approvals: enabled };
                if (!enabled) {
                    const ok = await showConfirmDialog({
                        title: 'Turn off tool approvals?',
                        body: 'Most tool actions will run without asking. Shell commands, Python '
                            + 'execution, deletes, and git writes still always require approval.',
                        confirmLabel: 'Turn off',
                        danger: true,
                    });
                    if (!ok) {
                        await loadSettings();
                        return;
                    }
                    payload.confirm_disable_approvals = true;
                }
                await saveSettings(
                    payload,
                    {
                        successMessage: `Tool approvals ${enabled ? 'enabled' : 'disabled'}.`,
                        busyLabel: 'Saving...',
                    },
                );
            });
        });

        $resetModelSettings?.addEventListener('click', async () => {
            await saveSettings(
                { primary_model: '', fallback_model: '' },
                {
                    successMessage: 'Reset model settings to .env defaults.',
                    busyLabel: 'Resetting...',
                },
            );
        });

        applySetupState();
    } catch (e) {
        console.error('Failed to load settings', e);
        const message = e?.message || String(e);
        $settingsContent.innerHTML = `<p style="color: var(--error)">Failed to load settings: ${escapeHtml(message)}</p>`;
    }
}

function loadSettingsError(message) {
    showSettingsNotice('error', message);
}

function clearSettingsNotice() {
    const existing = $settingsContent.querySelector('.settings-notice-inline');
    if (existing) existing.remove();
}

function showSettingsNotice(kind, message) {
    clearSettingsNotice();
    const notice = document.createElement('div');
    notice.className = `settings-notice settings-notice-inline ${kind === 'error' ? 'error' : 'success'}`;
    notice.textContent = message;
    $settingsContent.prepend(notice);
}

function setSettingsBusy(busy, label = 'Saving...') {
    const $saveButton = $settingsContent.querySelector('.settings-btn.primary');
    const $resetButton = $settingsContent.querySelector('#reset-model-settings');
    const $settingsInputs = $settingsContent.querySelectorAll('.settings-input, .settings-select, input[name="tool-approvals"]');

    if ($saveButton) {
        if (!$saveButton.dataset.defaultLabel) {
            $saveButton.dataset.defaultLabel = $saveButton.textContent;
        }
        $saveButton.classList.toggle('is-busy', busy);
        $saveButton.innerHTML = busy
            ? `<span class="button-spinner" aria-hidden="true"></span><span>${escapeHtml(label)}</span>`
            : escapeHtml($saveButton.dataset.defaultLabel);
        $saveButton.disabled = busy;
    }

    if ($resetButton) {
        if (!$resetButton.dataset.defaultLabel) {
            $resetButton.dataset.defaultLabel = $resetButton.textContent;
        }
        $resetButton.classList.toggle('is-busy', busy);
        $resetButton.innerHTML = busy
            ? '<span class="button-spinner" aria-hidden="true"></span><span>Working...</span>'
            : escapeHtml($resetButton.dataset.defaultLabel);
        $resetButton.disabled = busy;
    }

    $settingsInputs.forEach(input => {
        input.disabled = busy;
    });
}

async function saveSettings(payload, { successMessage = 'Model settings saved.', busyLabel = 'Saving...' } = {}) {
    clearSettingsNotice();
    setSettingsBusy(true, busyLabel);
    try {
        const res = await fetch('/api/settings', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload),
        });
        if (!res.ok) throw new Error('save failed');
        await loadSettings();
        await loadHealth();
        showSettingsNotice('success', successMessage);
        return true;
    } catch (e) {
        loadSettingsError('Failed to save settings.');
        return false;
    } finally {
        setSettingsBusy(false);
    }
}

// --- Backend restart (§6.3: restart-required notice) ---
// The backend reads .env once at startup and long-lived surfaces cache their
// LLM clients, so provider/key/config changes only fully apply on a fresh
// process. This drives the one-click restart: POST /api/restart, watch
// /api/health until the new process is up, then reload the page.

const RESTART_POLL_INTERVAL_MS = 1000;
const RESTART_TIMEOUT_MS = 45000;

async function performBackendRestart() {
    const progress = showProgressDialog({
        title: 'Restarting LumaKit',
        body: 'Asking the backend to restart...',
    });

    try {
        const res = await fetch('/api/restart', { method: 'POST' });
        if (!res.ok) {
            const detail = await res.json().catch(() => ({}));
            progress.close();
            await showAlertDialog({
                title: 'Restart not available',
                body: detail.error
                    || 'The backend could not restart itself. From a terminal, run `lumakit stop`, then `lumakit open`.',
            });
            return;
        }
    } catch (e) {
        progress.close();
        await showAlertDialog({
            title: 'Restart failed',
            body: 'Could not reach the backend to restart it. From a terminal, run `lumakit stop`, then `lumakit open`.',
        });
        return;
    }

    progress.update({ body: 'Backend is restarting — waiting for it to come back online...' });

    // Give the old process a moment to actually go down before polling,
    // so we don't mistake its final responses for the new process.
    await new Promise(resolve => setTimeout(resolve, 2500));

    const deadline = Date.now() + RESTART_TIMEOUT_MS;
    while (Date.now() < deadline) {
        try {
            const res = await fetch('/api/health');
            if (res.ok) {
                const health = await res.json();
                if (health && health.status === 'ok') {
                    progress.update({ title: 'Back online', body: 'Reloading the app...' });
                    await new Promise(resolve => setTimeout(resolve, 600));
                    location.reload();
                    return;
                }
            }
        } catch (e) {
            // Expected while the backend is down — keep polling.
        }
        await new Promise(resolve => setTimeout(resolve, RESTART_POLL_INTERVAL_MS));
    }

    progress.close();
    await showAlertDialog({
        title: "LumaKit didn't come back up",
        body: 'The backend restarted but never became healthy on this address. '
            + 'From a terminal, run `lumakit open` to start it again (it may have moved to a different port).',
    });
}

async function offerBackendRestart({ title, body } = {}) {
    const restartSupported = settingsState?.restart_supported !== false;
    if (!restartSupported) {
        await showAlertDialog({
            title: title || 'Restart required',
            body: `${body || ''} From a terminal, run \`lumakit stop\`, then \`lumakit open\`.`.trim(),
        });
        return;
    }
    const ok = await showConfirmDialog({
        title: title || 'Restart required',
        body: `${body || ''} Restart takes a few seconds; running tasks pause and resume automatically.`.trim(),
        confirmLabel: 'Restart now',
        cancelLabel: 'Later',
    });
    if (ok) await performBackendRestart();
}

// --- Health check for model badge ---
async function loadHealth() {
    try {
        const res = await fetch('/api/health');
        const data = await res.json();
        $modelBadgeText.textContent = data.model || 'unknown';
        if (typeof data.setup_required === 'boolean') {
            requiresModelSetup = data.setup_required;
            applySetupState();
        }
    } catch (e) {
        $modelBadgeText.textContent = 'offline';
    }
}

async function pollNotifications() {
    if (!ws.connected) return;
    try {
        const res = await fetch('/api/notifications/unshown');
        const notifications = await res.json();
        for (const item of notifications) {
            const handler = ws.handlers[item.type];
            if (handler) handler(item);
        }
    } catch (e) {
        console.error('Failed to poll notifications:', e);
    }
}

function startNotificationPolling() {
    if (notificationPollTimer) return;
    notificationPollTimer = setInterval(() => {
        pollNotifications();
    }, 5000);
    pollNotifications();
}

function stopNotificationPolling() {
    if (!notificationPollTimer) return;
    clearInterval(notificationPollTimer);
    notificationPollTimer = null;
}

// --- WebSocket ---
const ws = new WS({
    onConnect() {
        $statusDot.classList.remove('disconnected');
        if ($statusLabel) $statusLabel.textContent = 'Connected';
        loadChatList();
        loadHealth();
        startNotificationPolling();
    },

    onDisconnect() {
        $statusDot.classList.add('disconnected');
        if ($statusLabel) $statusLabel.textContent = 'Offline';
        stopNotificationPolling();
    },

    response(data) {
        setWorking(false);
        if (data.workspace_path) {
            setWorkspace(data.workspace_path, data.workspace_display);
        }
        const runState = data.run_state || 'completed';
        const cardState = runState === 'failed' ? 'error'
            : runState === 'stopped' || runState === 'interrupted' ? 'stopped'
            : 'done';
        settleActivityCard(cardState);
        if (data.model_used) {
            const requested = data.model_requested && data.model_requested !== data.model_used
                ? ` (requested ${data.model_requested})`
                : '';
            appendActivityLine(`Model used: ${data.model_used}${requested}`, 'status');
            $modelBadgeText.textContent = data.model_used;
        }
        removeStatus();
        const text = (data.text || '').trim();
        const runError = (data.run_error || '').trim();
        if (data.streamed) {
            if (streamMessageEl && text) finishStreamText(text);
        } else if (text) {
            addMessage('assistant', text);
            rememberVisibleMessage('assistant', text);
        } else if (runState === 'failed' && runError) {
            addMessage('assistant', `_Run stopped: ${runError}_`);
            rememberVisibleMessage('assistant', `_Run stopped: ${runError}_`);
        } else if (runState === 'failed') {
            addMessage('assistant', '_Run stopped before a reply was produced._');
            rememberVisibleMessage('assistant', '_Run stopped before a reply was produced._');
        } else if (!currentTurnHadRichReply) {
            addMessage('assistant', '_Done._');
            rememberVisibleMessage('assistant', '_Done._');
        }
        currentTurnHadRichReply = false;

        if (Array.isArray(data.messages)) {
            activeTranscript = data.messages.map(msg => ({ ...msg }));
        }

        if (data.title) {
            $topbarTitle.textContent = data.title;
            currentChatId = data.chat_id;
            loadChatList();
        }
    },

    stream_delta(data) {
        appendStreamText(String(data.text || ''));
    },

    stream_end(data) {
        const text = String(data.text || '');
        const finalText = finishStreamText(text);
        rememberVisibleMessage('assistant', finalText);
    },

    stream_cancel() {
        cancelStreamText();
    },

    status(data) {
        const text = String(data.text || '').trim();
        if (!text) return;
        if (text === 'Lumi is thinking...' || text === 'Lumi is thinking') {
            setActivityHeadline('Lumi is thinking');
            return;
        }
        if (text === 'Lumi is working...' || text === 'Lumi is working') {
            setActivityHeadline('Lumi is working');
            return;
        }
        if (text === 'Stopping...') {
            appendActivityLine('Stopping...', 'status');
            settleActivityCard('stopped');
            return;
        }
        appendActivityLine(text, 'status');
    },

    tool_call(data) {
        const detail = data.detail ? `: ${data.detail}` : '';
        appendActivityLine(`Using ${data.name}${detail}`, 'tool');
    },

    tool_result(data) {
        if (isInlineToolResult(data)) return;
        appendActivityLine(data.summary, data.error ? 'error' : 'result');
    },

    reaction(data) {
        addReactionToLatestUserMessage(data.emoji);
        currentTurnHadRichReply = true;
    },

    image(data) {
        addDeliveredImage(data.url, data.caption || '');
        currentTurnHadRichReply = true;
    },

    message(data) {
        addBackgroundMessage(data);
    },

    reminder(data) {
        const label = data.label || 'Reminder';
        addMessage('assistant', `🔔 ${label}: ${data.text}`);
    },

    email_draft_result(data) {
        resolveEmailDraftCard(data);
    },

    error(data) {
        setWorking(false);
        settleActivityCard('error');
        removeStatus();
        currentTurnHadRichReply = false;
        addMessage('assistant', `Error: ${data.text}`);
    },

    workspace_updated(data) {
        setWorkspace(data.workspace_path, data.workspace_display);
    },

    workspace_error(data) {
        showWorkspaceError(data.text || 'Could not set working directory.');
    },

    workspace_picked(data) {
        const path = String(data.path || '').trim();
        if (!path) return;
        if ($workspaceInput) $workspaceInput.value = path;
        if (path === currentWorkspacePath) return;
        ws.send({ type: 'set_workspace', path });
    },

    confirm(data) {
        showConfirmCard(data);
    },

    chat_loaded(data) {
        const previousChatId = currentChatId;
        if (data.chat_id === previousChatId && isWorking) {
            currentChatId = data.chat_id;
            $topbarTitle.textContent = data.title || 'New Chat';
            setWorkspace(data.workspace_path, data.workspace_display);
            loadChatList();
            switchView('chat');
            return;
        }
        const loadedMessages = data.messages || [];
        const renderMessages = (
            data.chat_id === previousChatId
            && visibleTranscriptCount(activeTranscript) > visibleTranscriptCount(loadedMessages)
        ) ? activeTranscript : loadedMessages;

        currentChatId = data.chat_id;
        $topbarTitle.textContent = data.title || 'New Chat';
        setWorkspace(data.workspace_path, data.workspace_display);
        activeTranscript = renderMessages.map(msg => ({ ...msg }));
        renderChatMessages(renderMessages);

        loadChatList();
        switchView('chat');
    },
});

// --- Inline confirm card + right-side diff panel ---

function escapeHtml(s) {
    return String(s)
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;');
}

function renderDiffLines(diffText) {
    const lines = diffText.split('\n');
    const out = [];
    for (const line of lines) {
        // Skip the unified-diff file headers — the panel header already shows the path
        if (line.startsWith('--- ') || line.startsWith('+++ ')) continue;
        let cls = 'diff-line';
        if (line.startsWith('@@')) cls += ' diff-hunk';
        else if (line.startsWith('+')) cls += ' diff-add';
        else if (line.startsWith('-')) cls += ' diff-del';
        out.push(`<div class="${cls}">${escapeHtml(line) || '&nbsp;'}</div>`);
    }
    return out.join('');
}

function openDiffPanel(data) {
    $diffPanelTool.textContent = data.tool_name || 'diff';
    $diffPanelPath.textContent = data.path || data.detail || '';
    $diffPanelBody.innerHTML = renderDiffLines(data.diff || '');
    // Panel carries its own approve/deny buttons only while a decision is pending
    $diffPanelFooter.classList.toggle('hidden', !pendingConfirm);
    $diffPanel.classList.remove('hidden');
    $diffPanelBackdrop.classList.remove('hidden');
    $diffPanelBody.scrollTop = 0;
}

function closeDiffPanel() {
    $diffPanel.classList.add('hidden');
    $diffPanelBackdrop.classList.add('hidden');
}

function resolveConfirmCard(approved) {
    if (!pendingConfirm) return;
    const { card, data } = pendingConfirm;
    card.classList.add('resolved');
    const status = card.querySelector('.confirm-card-status');
    if (status) {
        status.classList.add(approved ? 'approved' : 'denied');
        status.textContent = approved ? '\u2713 Approved' : '\u2717 Denied';
    }
    ws.send({ type: 'confirm_response', approved });
    pendingConfirm = null;
    closeDiffPanel();
}

function showConfirmCard(data) {
    removeStatus();
    if ($emptyState && !$emptyState.classList.contains('hidden')) {
        $emptyState.classList.add('hidden');
        exitCenteredMode();
    }

    // The tool_call card emitted just before the confirm is redundant with the
    // richer confirm card we're about to render — fold them into one.
    const last = $messagesInner.lastElementChild;
    if (last && last.classList.contains('tool-card') && !last.classList.contains('result')) {
        last.remove();
    }

    const toolName = data.tool_name || 'action';
    const detail = data.detail || '';
    const prompt = data.prompt || 'Approve this action?';
    const hasDiff = !!(data.diff && data.diff.trim());
    const isEmailConfirm = data.kind === 'email' && data.email_preview;

    const card = document.createElement('div');
    if (isEmailConfirm) {
        // handled below via a detached wrapper so we can bind actions normally
    } else {
        card.className = 'confirm-card';
        card.innerHTML = `
            <div class="confirm-card-head">
                <span class="confirm-card-icon">\u2713</span>
                <span class="confirm-card-tool">${escapeHtml(toolName)}</span>
                <span class="confirm-card-prompt">${escapeHtml(prompt)}</span>
            </div>
            <div class="confirm-card-detail">${escapeHtml(detail)}</div>
            <div class="confirm-card-actions">
                ${hasDiff ? '<button class="confirm-card-diff-link">View diff \u2192</button>' : ''}
                <span class="confirm-card-hint"><kbd>Y</kbd> approve &middot; <kbd>N</kbd> deny</span>
                <button class="confirm-btn confirm-no">Deny (N)</button>
                <button class="confirm-btn confirm-yes">Approve (Y)</button>
            </div>
            <div class="confirm-card-status"></div>
        `;
    }

    const renderedCard = isEmailConfirm ? (() => {
        const wrapper = document.createElement('div');
        wrapper.innerHTML = renderEmailConfirmCard(data);
        return wrapper.firstElementChild;
    })() : card;

    $messagesInner.appendChild(renderedCard);
    scrollToBottom();

    pendingConfirm = { card: renderedCard, data };

    // Pull focus off the composer so Y/N keystrokes land here, not in the textarea
    if (document.activeElement === $input) $input.blur();

    renderedCard.querySelector('.confirm-yes').onclick = () => resolveConfirmCard(true);
    renderedCard.querySelector('.confirm-no').onclick = () => resolveConfirmCard(false);
    if (hasDiff && !isEmailConfirm) {
        renderedCard.querySelector('.confirm-card-diff-link').onclick = () => openDiffPanel(data);
        // Auto-open the panel so the user can see the diff immediately
        openDiffPanel(data);
    }
}

$diffPanelClose.onclick = closeDiffPanel;
$diffPanelBackdrop.onclick = closeDiffPanel;
$diffPanelApprove.onclick = () => resolveConfirmCard(true);
$diffPanelDeny.onclick = () => resolveConfirmCard(false);

document.addEventListener('keydown', (e) => {
    // Don't intercept while the user is typing in the composer
    const typing = document.activeElement === $input;

    if (pendingConfirm && !typing) {
        const k = e.key.toLowerCase();
        if (k === 'y' || k === 'enter') {
            e.preventDefault();
            resolveConfirmCard(true);
            return;
        }
        if (k === 'n') {
            e.preventDefault();
            resolveConfirmCard(false);
            return;
        }
    }

    if (e.key === 'Escape') {
        if (!$diffPanel.classList.contains('hidden')) {
            closeDiffPanel();
        }
    }
});

// --- Photo attachments ---
function fileToDataUrl(file) {
    return new Promise((resolve, reject) => {
        const reader = new FileReader();
        reader.onload = () => resolve(String(reader.result || ''));
        reader.onerror = () => reject(reader.error || new Error('Could not read image'));
        reader.readAsDataURL(file);
    });
}

async function attachPhotoFile(file) {
    if (!file) return;
    if (!file.type?.startsWith('image/')) {
        showStatus('Choose an image file.');
        return;
    }
    if (file.size > MAX_PHOTO_BYTES) {
        showStatus('Images need to be 10 MB or smaller.');
        return;
    }
    const dataUrl = await fileToDataUrl(file);
    attachedPhoto = {
        name: file.name || 'Pasted image',
        type: file.type || 'image/png',
        size: file.size || 0,
        data_url: dataUrl,
    };
    renderAttachedPhoto();
}

function renderAttachedPhoto() {
    if (!$photoPreview) return;
    $photoBtn?.classList.toggle('has-photo', !!attachedPhoto);
    if (!attachedPhoto) {
        $photoPreview.classList.add('hidden');
        $photoPreview.innerHTML = '';
        return;
    }

    $photoPreview.classList.remove('hidden');
    $photoPreview.innerHTML = `
        <div class="photo-preview-card">
            <img class="photo-preview-thumb" src="${attachedPhoto.data_url}" alt="">
            <div class="photo-preview-name">${escapeHtml(attachedPhoto.name || 'Attached photo')}</div>
            <button class="photo-preview-remove" type="button" title="Remove photo" aria-label="Remove photo">&times;</button>
        </div>
    `;
    $photoPreview.querySelector('.photo-preview-remove')?.addEventListener('click', clearAttachedPhoto);
}

function clearAttachedPhoto() {
    attachedPhoto = null;
    if ($photoInput) $photoInput.value = '';
    renderAttachedPhoto();
}

// --- Send message ---
// Users can send multiple messages in a row without waiting for a response.
function sendMessage() {
    const text = $input.value.trim();
    const photo = attachedPhoto;
    if (!text && !photo) return;
    if (requiresModelSetup) {
        switchView('settings');
        return;
    }

    // Only reset the activity card when starting a fresh turn — if the agent
    // is still working, the user's new message is queued alongside the
    // existing activity, not starting a new one.
    if (!isWorking) {
        currentTurnHadRichReply = false;
        clearActivityCard();
    }
    addUserPhotoMessage(text || 'What do you see in this image?', photo);
    rememberVisibleMessage('user', text || 'What do you see in this image?');
    ws.send({ type: 'message', text, image: photo });
    $input.value = '';
    $input.style.height = 'auto';
    clearAttachedPhoto();
    setWorking(true);
}

$sendBtn.onclick = sendMessage;

document.querySelectorAll('.suggestion-card').forEach(card => {
    card.addEventListener('click', () => {
        const prompt = card.getAttribute('data-prompt') || '';
        if (!prompt) return;
        $input.value = prompt;
        $input.focus();
        sendMessage();
    });
});
$photoBtn?.addEventListener('click', () => $photoInput?.click());
$photoInput?.addEventListener('change', async () => {
    const file = $photoInput.files?.[0];
    if (!file) return;
    try {
        await attachPhotoFile(file);
    } catch (e) {
        console.error('Failed to attach photo', e);
        showStatus('Could not attach that image.');
    }
});

$workspaceForm?.addEventListener('submit', (e) => {
    e.preventDefault();
    const path = ($workspaceInput?.value || '').trim();
    if (!path || path === currentWorkspacePath) return;
    ws.send({ type: 'set_workspace', path });
});

$workspaceBrowse?.addEventListener('click', () => {
    if (isWorking) return;
    ws.send({ type: 'pick_workspace', base: currentWorkspacePath || '' });
});

$input.addEventListener('keydown', (e) => {
    if (e.key === 'Enter' && !e.shiftKey) {
        e.preventDefault();
        sendMessage();
    }
});

$input.addEventListener('paste', async (e) => {
    const file = Array.from(e.clipboardData?.files || []).find(item => item.type?.startsWith('image/'));
    if (!file) return;
    e.preventDefault();
    try {
        await attachPhotoFile(file);
    } catch (err) {
        console.error('Failed to paste photo', err);
        showStatus('Could not paste that image.');
    }
});

document.addEventListener('keydown', async (e) => {
    if (!(e.altKey && e.key.toLowerCase() === 'v')) return;
    if (requiresModelSetup) return;
    e.preventDefault();
    // Browsers require a permission prompt for programmatic clipboard reads.
    // Use the native paste event for clipboard images, and make Alt+V a picker shortcut.
    $photoInput?.click();
});

// Auto-resize textarea
$input.addEventListener('input', () => {
    $input.style.height = 'auto';
    $input.style.height = Math.min($input.scrollHeight, 200) + 'px';
});

// New chat
$newChatBtn.onclick = () => {
    ws.send({ type: 'new_chat' });
    $sidebar.classList.remove('open');
};

// Sidebar toggle (mobile)
$sidebarToggle.onclick = () => {
    $sidebar.classList.toggle('open');
};

// Navigation
$navTasks.onclick = () => switchView('task');
$navSettings.onclick = () => switchView('settings');

$modelBadge?.addEventListener('click', () => switchView('settings'));
$setupOpenSettings.onclick = () => {
    pendingSettingsFocus = true;
    switchView('settings');
};

// Click outside sidebar to close on mobile
document.addEventListener('click', (e) => {
    if (window.innerWidth <= 768 &&
        $sidebar.classList.contains('open') &&
        !$sidebar.contains(e.target) &&
        e.target !== $sidebarToggle) {
        $sidebar.classList.remove('open');
    }
});

// --- Boot ---
enterCenteredMode();
ws.connect();
loadSettings();
$input.focus();
