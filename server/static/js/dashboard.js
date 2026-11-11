/**
 * Smart Garage - 1st Floor Dashboard (Tablet & Mobile Kiosk Controller)
 */

// Auto-attach CSRF token to mutating requests
(function() {
    const origFetch = window.fetch;
    window.fetch = function(url, options = {}) {
        if (options && options.method && ['POST', 'PUT', 'DELETE', 'PATCH'].includes(options.method.toUpperCase())) {
            const csrfToken = sessionStorage.getItem('sg_csrf_token');
            if (csrfToken) {
                if (!options.headers) {
                    options.headers = {};
                }
                if (options.headers instanceof Headers) {
                    if (!options.headers.has('X-CSRF-Token')) {
                        options.headers.set('X-CSRF-Token', csrfToken);
                    }
                } else if (!options.headers['X-CSRF-Token']) {
                    options.headers['X-CSRF-Token'] = csrfToken;
                }
            }
        }
        return origFetch(url, options);
    };
})();

document.addEventListener('DOMContentLoaded', () => {
    // --- STATE VARIABLES ---
    let wakeLock = null;
    let isListening = false;
    let ttsEnabled = true;
    let recognition = null;
    let isLightOn = false;
    let isFanOn = false;

    // --- DOM REFERENCES ---
    // Clock
    const clockTime = document.getElementById('clockTime');
    const clockDate = document.getElementById('clockDate');

    // Header buttons
    const btnWakeLock = document.getElementById('btnWakeLock');
    const btnFullscreen = document.getElementById('btnFullscreen');
    const btnTts = document.getElementById('btnTts');
    const btnRefresh = document.getElementById('btnRefresh');
    const btnDashAuth = document.getElementById('btnDashAuth');
    const dashAuthIcon = document.getElementById('dashAuthIcon');
    const dashAuthLabel = document.getElementById('dashAuthLabel');
    const dashPinModal = document.getElementById('dashPinModal');
    const dashPinForm = document.getElementById('dashPinForm');
    const dashPinInput = document.getElementById('dashPinInput');
    const dashPinError = document.getElementById('dashPinError');
    const btnDashPinClose = document.getElementById('btnDashPinClose');

    // Status pills
    const pillServerDot = document.getElementById('pillServerDot');
    const pillServerText = document.getElementById('pillServerText');
    const pillCpuTemp = document.getElementById('pillCpuTemp');
    const pillRam = document.getElementById('pillRam');
    const pillServerBat = document.getElementById('pillServerBat');
    const pillEspStatus = document.getElementById('pillEspStatus');
    const pillEspContainer = document.getElementById('pillEspContainer');
    const pillEspDot = document.getElementById('pillEspDot');
    const esp32GatewayStrip = document.getElementById('esp32GatewayStrip');
    const esp32StripBadge = document.getElementById('esp32StripBadge');
    const esp32StripIp = document.getElementById('esp32StripIp');
    const esp32StripLastSeen = document.getElementById('esp32StripLastSeen');
    const btnEsp32Ping = document.getElementById('btnEsp32Ping');
    const btnEsp32Poll = document.getElementById('btnEsp32Poll');
    const btnEsp32Logs = document.getElementById('btnEsp32Logs');
    const modalEsp32 = document.getElementById('modalEsp32');

    // Touch Tiles
    const tileLight = document.getElementById('tileLight');
    const statusLight = document.getElementById('statusLight');
    const tileFan = document.getElementById('tileFan');
    const statusFan = document.getElementById('statusFan');

    // Quick light buttons
    const btnAllLightsOn = document.getElementById('btnAllLightsOn');
    const btnAllLightsOff = document.getElementById('btnAllLightsOff');

    // Sensors & Floors
    const valTempFloor1 = document.getElementById('valTempFloor1');
    const valHumFloor1 = document.getElementById('valHumFloor1');
    const batFloor1 = document.getElementById('batFloor1');
    const subFloor1 = document.getElementById('subFloor1');

    const valTempFloor2 = document.getElementById('valTempFloor2');
    const valHumFloor2 = document.getElementById('valHumFloor2');
    const batFloor2 = document.getElementById('batFloor2');
    const subFloor2 = document.getElementById('subFloor2');

    const valTempBasement = document.getElementById('valTempBasement');
    const valHumBasement = document.getElementById('valHumBasement');
    const batBasement = document.getElementById('batBasement');
    const subBasement = document.getElementById('subBasement');

    const valBleSensorsCount = document.getElementById('valBleSensorsCount');
    const subBleSensors = document.getElementById('subBleSensors');

    // Voice Assistant
    const btnMicHero = document.getElementById('btnMicHero');
    const voiceStatusText = document.getElementById('voiceStatusText');
    const voiceDialogBox = document.getElementById('voiceDialogBox');
    const dialogUserText = document.getElementById('dialogUserText');
    const dialogAiText = document.getElementById('dialogAiText');
    const voiceForm = document.getElementById('voiceForm');
    const voiceInput = document.getElementById('voiceInput');
    const btnWakeContinuous = document.getElementById('btnWakeContinuous');
    const wakeContinuousLabel = document.getElementById('wakeContinuousLabel');
    let isContinuousWakeMode = localStorage.getItem('smartgarage_wake_continuous') === 'true';
    let isManualMicSession = false;
    let isWaitingFollowup = false;
    let followupTimeoutTimer = null;
    let isSpeaking = false;
    let isProcessingCommand = false;
    let autoRestartTimer = null;
    let followupStartTimer = null;
    let lastWakeWordTimestamp = 0;

    // Scenarios
    const scenarioBtns = document.querySelectorAll('.scenario-btn');

    // Media & Projector
    const projOnlineDot = document.getElementById('projOnlineDot');
    const projStatusBadge = document.getElementById('projStatusBadge');
    const btnProjPause = document.getElementById('btnProjPause');
    const btnProjResume = document.getElementById('btnProjResume');
    const btnProjStop = document.getElementById('btnProjStop');
    const btnProjMirror = document.getElementById('btnProjMirror');
    const mediaStreamForm = document.getElementById('mediaStreamForm');
    const mediaStreamInput = document.getElementById('mediaStreamInput');
    const mediaChipsContainer = document.getElementById('mediaChipsContainer');

    // Speaker Elements
    const btnSpeakerJxbt = document.getElementById('btnSpeakerJxbt');
    const btnSpeakerJbl = document.getElementById('btnSpeakerJbl');
    const dotJxbt = document.getElementById('dotJxbt');
    const dotJbl = document.getElementById('dotJbl');
    const subJxbt = document.getElementById('subJxbt');
    const subJbl = document.getElementById('subJbl');
    const speakerSelect = document.getElementById('speakerSelect');
    const jblCardTitle = document.getElementById('jblCardTitle');
    const jblOnlineDot = document.getElementById('jblOnlineDot');
    const jblStatusBadge = document.getElementById('jblStatusBadge');
    const jblDeviceName = document.getElementById('jblDeviceName');
    const jblMac = document.getElementById('jblMac');
    const btnJblConnect = document.getElementById('btnJblConnect');
    const btnJblDisconnect = document.getElementById('btnJblDisconnect');
    const jblVolumeVal = document.getElementById('jblVolumeVal');
    const jblVolumeSlider = document.getElementById('jblVolumeSlider');
    const jblNowPlaying = document.getElementById('jblNowPlaying');
    const btnJblPrev = document.getElementById('btnJblPrev');
    const btnJblRewind = document.getElementById('btnJblRewind');
    const btnJblPause = document.getElementById('btnJblPause');
    const btnJblResume = document.getElementById('btnJblResume');
    const btnJblForward = document.getElementById('btnJblForward');
    const btnJblStop = document.getElementById('btnJblStop');
    const dashTimelineSlider = document.getElementById('dashTimelineSlider');
    const dashMediaTimeElapsed = document.getElementById('dashMediaTimeElapsed');
    const dashMediaTimeDuration = document.getElementById('dashMediaTimeDuration');
    const dashJblUpcomingContainer = document.getElementById('dashJblUpcomingContainer');
    const dashJblUpcomingTrack = document.getElementById('dashJblUpcomingTrack');
    let isDashScrubbing = false;
    const jblPlayForm = document.getElementById('jblPlayForm');
    const jblPlayInput = document.getElementById('jblPlayInput');

    // Internet Radio Elements
    const radioQuickPicks = document.getElementById('radioQuickPicks');
    const radioStationsContainer = document.getElementById('radioStationsContainer');
    const radioSearchInput = document.getElementById('radioSearchInput');
    const btnRadioSearch = document.getElementById('btnRadioSearch');
    const btnRadioReset = document.getElementById('btnRadioReset');
    let currentRadioUrl = null;

    // System Stats
    const statCpuLoad = document.getElementById('statCpuLoad');
    const statCpuTemp = document.getElementById('statCpuTemp');
    const statRam = document.getElementById('statRam');
    const statServerBat = document.getElementById('statServerBat');
    const statUptime = document.getElementById('statUptime');
    const statLocalIp = document.getElementById('statLocalIp');
    const statTailscaleIp = document.getElementById('statTailscaleIp');

    // --- HAPTIC FEEDBACK ---
    function hapticFeedback(duration = 25) {
        if (navigator.vibrate) {
            try { navigator.vibrate(duration); } catch (e) { }
        }
    }

    // --- CLOCK & DATE WIDGET ---
    function updateClock() {
        const now = new Date();
        const hours = String(now.getHours()).padStart(2, '0');
        const minutes = String(now.getMinutes()).padStart(2, '0');
        const seconds = String(now.getSeconds()).padStart(2, '0');
        if (clockTime) clockTime.textContent = `${hours}:${minutes}:${seconds}`;

        const options = { weekday: 'long', day: 'numeric', month: 'long' };
        let dateStr = now.toLocaleDateString('uk-UA', options);
        if (dateStr) {
            dateStr = dateStr.charAt(0).toUpperCase() + dateStr.slice(1);
            if (clockDate) clockDate.textContent = dateStr;
        }
    }
    setInterval(updateClock, 1000);
    updateClock();

    // --- SCREEN WAKE LOCK (Keep screen on) ---
    async function requestWakeLock() {
        if ('wakeLock' in navigator) {
            try {
                wakeLock = await navigator.wakeLock.request('screen');
                if (btnWakeLock) {
                    btnWakeLock.classList.add('active');
                    btnWakeLock.querySelector('.btn-label').textContent = 'Екран: Завжди ввімкнено';
                }
                wakeLock.addEventListener('release', () => {
                    if (btnWakeLock) {
                        btnWakeLock.classList.remove('active');
                        btnWakeLock.querySelector('.btn-label').textContent = 'Екран: Авто';
                    }
                });
            } catch (err) {
                console.warn('Wake Lock error:', err);
            }
        }
    }

    if (btnWakeLock) {
        btnWakeLock.addEventListener('click', () => {
            hapticFeedback();
            if (wakeLock !== null) {
                wakeLock.release().then(() => { wakeLock = null; });
            } else {
                requestWakeLock();
            }
        });
    }

    // Auto-reacquire wake lock on visibility change
    document.addEventListener('visibilitychange', () => {
        if (document.visibilityState === 'visible' && btnWakeLock && btnWakeLock.classList.contains('active')) {
            requestWakeLock();
        }
    });

    // Try acquiring wake lock on start
    requestWakeLock();

    // --- FULLSCREEN TOGGLE ---
    if (btnFullscreen) {
        btnFullscreen.addEventListener('click', () => {
            hapticFeedback();
            if (!document.fullscreenElement) {
                document.documentElement.requestFullscreen().catch(err => console.log(err));
            } else {
                if (document.exitFullscreen) document.exitFullscreen();
            }
        });
    }

    // --- TTS TOGGLE ---
    if (btnTts) {
        btnTts.addEventListener('click', () => {
            hapticFeedback();
            ttsEnabled = !ttsEnabled;
            if (ttsEnabled) {
                btnTts.classList.add('active');
                btnTts.querySelector('.btn-label').textContent = 'Голос: Увімк';
            } else {
                btnTts.classList.remove('active');
                btnTts.querySelector('.btn-label').textContent = 'Голос: Вимк';
                stopTtsPlaybackDash();
            }
        });
    }

    // --- TTS SETTINGS & PROVIDER SELECTION ---
    const btnTtsSettings = document.getElementById('btnTtsSettings');
    const ttsSettingsPanel = document.getElementById('ttsSettingsPanel');
    const selectTtsProvider = document.getElementById('selectTtsProvider');
    const selectTtsVoice = document.getElementById('selectTtsVoice');
    const ttsProviderLabel = document.getElementById('ttsProviderLabel');
    const ttsFallbackBadge = document.getElementById('ttsFallbackBadge');
    const ttsFallbackHint = document.getElementById('ttsFallbackHint');
    const btnTtsPreview = document.getElementById('btnTtsPreview');
    const btnTtsSave = document.getElementById('btnTtsSave');

    let ttsProvidersData = null;

    async function loadTtsProviders() {
        try {
            const res = await fetch('/api/voice/providers');
            if (!res.ok) return;
            const data = await res.json();
            if (!data.success) return;
            ttsProvidersData = data;

            const activeProv = data.active_provider || 'edge';
            const activeVoice = data.active_voice_id || 'uk-UA-PolinaNeural';
            const fallbackProv = data.fallback_provider || 'edge';

            if (ttsProviderLabel) {
                const provName = activeProv === 'edge' ? 'Edge (Поліна)' : (activeProv === 'elevenlabs' ? 'ElevenLabs' : 'HeyGen');
                ttsProviderLabel.textContent = `TTS: ${provName}`;
            }

            if (ttsFallbackBadge) {
                if (activeProv === 'edge') {
                    ttsFallbackBadge.textContent = 'Baseline: Edge TTS (Безкоштовно)';
                    ttsFallbackBadge.style.background = 'rgba(52, 211, 153, 0.15)';
                    ttsFallbackBadge.style.color = '#34d399';
                } else {
                    ttsFallbackBadge.textContent = `Активний: ${activeProv} | Резерв: ${fallbackProv}`;
                    ttsFallbackBadge.style.background = 'rgba(59, 130, 246, 0.15)';
                    ttsFallbackBadge.style.color = '#60a5fa';
                }
            }

            if (ttsFallbackHint) {
                ttsFallbackHint.textContent = `Резервний синтез (fallback): ${fallbackProv} або Web Speech API у браузері`;
            }

            if (selectTtsProvider) {
                selectTtsProvider.innerHTML = '';
                const providersList = [
                    { id: 'edge', name: 'Microsoft Edge Neural (uk, безкоштовно)' },
                    { id: 'elevenlabs', name: 'ElevenLabs Flash v2.5' },
                    { id: 'heygen', name: 'HeyGen Voice Turbo REST' },
                ];
                providersList.forEach(p => {
                    const opt = document.createElement('option');
                    opt.value = p.id;
                    const provInfo = data.providers ? data.providers[p.id] : null;
                    const isConfigured = provInfo ? provInfo.configured : (p.id === 'edge');
                    opt.textContent = isConfigured ? p.name : `${p.name} (потрібен API-ключ на сервері)`;
                    if (p.id === activeProv) opt.selected = true;
                    selectTtsProvider.appendChild(opt);
                });
            }

            updateVoicesDropdown(activeProv, activeVoice);
        } catch (err) {
            console.warn('[Dashboard TTS] Помилка завантаження провайдерів:', err);
        }
    }

    function updateVoicesDropdown(providerId, currentVoiceId) {
        if (!selectTtsVoice) return;
        selectTtsVoice.innerHTML = '';

        let voices = [];
        if (ttsProvidersData && ttsProvidersData.providers && ttsProvidersData.providers[providerId]) {
            voices = ttsProvidersData.providers[providerId].voices || [];
        }

        if (voices.length === 0) {
            if (providerId === 'edge') {
                voices = [
                    { voice_id: 'uk-UA-PolinaNeural', name: 'Поліна (жіночий, базовий)' },
                    { voice_id: 'uk-UA-OstapNeural', name: 'Остап (чоловічий)' }
                ];
            } else {
                const opt = document.createElement('option');
                opt.value = '';
                opt.textContent = 'Немає доступних українських голосів (провайдер не налаштований)';
                selectTtsVoice.appendChild(opt);
                return;
            }
        }

        voices.forEach(v => {
            const opt = document.createElement('option');
            opt.value = v.voice_id;
            opt.textContent = `${v.name} (${v.voice_id})`;
            if (v.voice_id === currentVoiceId) opt.selected = true;
            selectTtsVoice.appendChild(opt);
        });
    }

    if (btnTtsSettings && ttsSettingsPanel) {
        btnTtsSettings.addEventListener('click', () => {
            hapticFeedback();
            const isHidden = ttsSettingsPanel.style.display === 'none' || !ttsSettingsPanel.style.display;
            ttsSettingsPanel.style.display = isHidden ? 'block' : 'none';
            if (isHidden && !ttsProvidersData) {
                loadTtsProviders();
            }
        });
    }

    if (selectTtsProvider) {
        selectTtsProvider.addEventListener('change', () => {
            const chosen = selectTtsProvider.value;
            updateVoicesDropdown(chosen, null);
        });
    }

    if (btnTtsSave) {
        btnTtsSave.addEventListener('click', async () => {
            hapticFeedback();
            const provider = selectTtsProvider ? selectTtsProvider.value : 'edge';
            const voice_id = selectTtsVoice ? selectTtsVoice.value : 'uk-UA-PolinaNeural';

            try {
                btnTtsSave.textContent = 'Збереження...';
                const res = await fetch('/api/voice/config', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ provider, voice_id })
                });
                const data = await res.json();
                btnTtsSave.textContent = 'Зберегти';
                if (data.success) {
                    if (voiceStatusText) {
                        voiceStatusText.textContent = `✓ Налаштування TTS збережено: ${data.active_provider}`;
                        voiceStatusText.style.color = '#34d399';
                    }
                    await loadTtsProviders();
                } else {
                    if (voiceStatusText) {
                        voiceStatusText.textContent = `⚠️ Помилка збереження TTS: ${data.error || 'помилка'}`;
                        voiceStatusText.style.color = 'var(--accent-amber)';
                    }
                }
            } catch (err) {
                btnTtsSave.textContent = 'Зберегти';
                console.error(err);
            }
        });
    }

    if (btnTtsPreview) {
        btnTtsPreview.addEventListener('click', async () => {
            hapticFeedback();
            const provider = selectTtsProvider ? selectTtsProvider.value : 'edge';
            const voice = selectTtsVoice ? selectTtsVoice.value : 'uk-UA-PolinaNeural';
            const sampleText = 'Світло в гаражі увімкнено. Температура плюс вісімнадцять градусів.';

            try {
                btnTtsPreview.textContent = '⏳ Синтез...';
                const res = await fetch('/api/voice/preview', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ provider, voice, text: sampleText })
                });
                btnTtsPreview.textContent = '▶ Прослухати';

                if (!res.ok) {
                    throw new Error(`HTTP ${res.status}`);
                }

                const isFallback = res.headers.get('X-TTS-Fallback') === 'true';
                const usedProv = res.headers.get('X-TTS-Provider') || provider;
                if (isFallback && voiceStatusText) {
                    voiceStatusText.textContent = `⚠️ Резервний синтез: використано ${usedProv}`;
                    voiceStatusText.style.color = 'var(--accent-amber)';
                } else if (voiceStatusText) {
                    voiceStatusText.textContent = `🔊 Тестове відтворення: ${usedProv}`;
                    voiceStatusText.style.color = '#34d399';
                }

                const blob = await res.blob();
                const audioUrl = URL.createObjectURL(blob);
                const audio = new Audio(audioUrl);
                audio.play();
            } catch (err) {
                btnTtsPreview.textContent = '▶ Прослухати';
                console.warn('[Dashboard TTS Preview] Помилка прев’ю:', err);
                if (voiceStatusText) {
                    voiceStatusText.textContent = '⚠️ Помилка попереднього прослуховування голосу';
                    voiceStatusText.style.color = 'var(--accent-amber)';
                }
            }
        });
    }

    // Load initial TTS configuration on page load
    loadTtsProviders();

    // --- TTS & SPEECH CLEANING ---
    function cleanSpeechText(text) {
        if (!text) return '';
        let clean = text
            // Strip URLs
            .replace(/https?:\/\/\S+/g, '')
            // Strip all emojis (Extended_Pictographic + broad Unicode ranges)
            .replace(/\p{Extended_Pictographic}/gu, '')
            .replace(/[\u{1F300}-\u{1FAFF}\u{2600}-\u{27BF}\u{FE00}-\u{FE0F}\u{1F900}-\u{1F9FF}\u{200D}]/gu, '')
            // Strip Markdown formatting
            .replace(/[*_#`~[\]()]/g, ' ')
            .replace(/[•·]/g, ', ')
            // Strip single and double quotes (prevents staccato robotic pauses in neural TTS)
            .replace(/['"«»“”]/g, '')
            // Units and numbers to spoken Ukrainian
            .replace(/(\d+(?:[.,]\d+)?)\s*°C/g, '$1 градусів')
            .replace(/°C/g, ' градусів')
            .replace(/(\d+(?:[.,]\d+)?)\s*%/g, '$1 відсотків')
            .replace(/%/g, ' відсотків')
            // Floors and locations
            .replace(/1-й\s*поверх/gi, 'перший поверх')
            .replace(/2-й\s*поверх/gi, 'другий поверх')
            .replace(/1-му\s*поверсі/gi, 'першому поверсі')
            .replace(/2-му\s*поверсі/gi, 'другому поверсі')
            .replace(/на\s+музика\s+(?:1-й|перший|1)\s+поверх/gi, 'на першому поверсі')
            .replace(/на\s+музика\s+1/gi, 'на першому поверсі')
            // System status cleanups
            .replace(/\[онлайн\]/gi, 'онлайн')
            .replace(/\[офлайн\]/gi, 'офлайн')
            // Radio & Latin names to phonetic Ukrainian
            .replace(/\bhit\s*fm\b/gi, 'Хіт ФМ')
            .replace(/\bkiss\s*fm\b/gi, 'Кіс ФМ')
            .replace(/\blounge\s*fm\b/gi, 'Лаундж ФМ')
            .replace(/\bradio\s*roks\b/gi, 'Радіо Рокс')
            .replace(/\bradio\s*jazz\b/gi, 'Радіо Джаз')
            .replace(/\bfm\b/gi, 'ФМ')
            // Punctuation to conversational intonational pauses
            .replace(/[:;]+/g, ', ')
            .replace(/\s+[-—–]\s+/g, ', ')
            .replace(/[-—–]+/g, ' ')
            .replace(/\s+/g, ' ')
            .replace(/\s+([.,!?])/g, '$1')
            .trim();
        if (clean && !/[.!?]$/.test(clean)) {
            clean += '.';
        }
        return clean;
    }

    let cachedUkVoice = null;
    function getUkrainianVoice() {
        if (!('speechSynthesis' in window)) return null;
        const voices = window.speechSynthesis.getVoices() || [];
        if (!voices || voices.length === 0) return null;
        return voices.find(v => {
            const lang = (v.lang || '').toLowerCase().replace(/_/g, '-');
            const name = (v.name || '').toLowerCase();
            // Explicitly exclude any English/British/UK voices (e.g. en-UK, Google UK English)
            const isEnglish = lang.startsWith('en') || name.includes('english') || name.includes('british') || name.includes('united kingdom');
            if (isEnglish) return false;
            return lang === 'uk' || lang.startsWith('uk-') || name.includes('ukrain') || name.includes('україн');
        }) || null;
    }

    let currentTtsAudio = null;
    let currentTtsUrl = null;

    function stopTtsPlaybackDash() {
        if (currentTtsAudio) {
            try {
                currentTtsAudio.pause();
                currentTtsAudio.currentTime = 0;
            } catch (_) {}
            currentTtsAudio = null;
        }
        if (currentTtsUrl) {
            try { URL.revokeObjectURL(currentTtsUrl); } catch (_) {}
            currentTtsUrl = null;
        }
        if ('speechSynthesis' in window) {
            try { window.speechSynthesis.cancel(); } catch (_) {}
        }
        isSpeaking = false;
        if (btnMicHero) btnMicHero.classList.remove('speaking');
    }

    function playBrowserSpeechSynthesisDash(clean, onEnded) {
        if (!('speechSynthesis' in window)) {
            if (typeof onEnded === 'function') onEnded();
            return;
        }
        try {
            window.speechSynthesis.cancel();
            const utt = new SpeechSynthesisUtterance(clean);
            utt.lang = 'uk-UA';
            const ukVoice = getUkrainianVoice();
            if (ukVoice) utt.voice = ukVoice;
            utt.onend = () => {
                if (typeof onEnded === 'function') onEnded();
            };
            utt.onerror = () => {
                if (typeof onEnded === 'function') onEnded();
            };
            window.speechSynthesis.speak(utt);
        } catch (e) {
            console.warn('Dashboard browser speechSynthesis error:', e);
            if (typeof onEnded === 'function') onEnded();
        }
    }

    function speakText(text, onEnded) {
        if (!ttsEnabled) {
            if (typeof onEnded === 'function') onEnded();
            return;
        }
        const clean = cleanSpeechText(text);
        if (!clean) {
            if (typeof onEnded === 'function') onEnded();
            return;
        }

        // Система починає говорити: негайно вимикаємо мікрофон
        isSpeaking = true;
        stopMicrophone();

        // Cancel any browser speech synthesis
        if ('speechSynthesis' in window) {
            try { window.speechSynthesis.cancel(); } catch (_) {}
        }

        // Stop any currently playing TTS audio
        if (currentTtsAudio) {
            try {
                currentTtsAudio.pause();
                currentTtsAudio.currentTime = 0;
            } catch (_) {}
            currentTtsAudio = null;
        }
        if (currentTtsUrl) {
            try { URL.revokeObjectURL(currentTtsUrl); } catch (_) {}
            currentTtsUrl = null;
        }

        let endedFired = false;
        const fireEnded = () => {
            if (endedFired) return;
            endedFired = true;
            isSpeaking = false;
            if (btnMicHero) btnMicHero.classList.remove('speaking');
            if (currentTtsUrl) {
                try { URL.revokeObjectURL(currentTtsUrl); } catch (_) {}
                currentTtsUrl = null;
            }
            currentTtsAudio = null;
            if (typeof onEnded === 'function') {
                onEnded();
            }
        };

        if (btnMicHero) {
            btnMicHero.classList.add('speaking');
        }

        const ttsUrl = '/api/voice/tts?text=' + encodeURIComponent(clean);
        fetch(ttsUrl)
            .then(res => {
                if (!res.ok) {
                    throw new Error(`Server TTS HTTP ${res.status}`);
                }
                const provider = res.headers.get('X-TTS-Provider') || 'server';
                const isFallback = res.headers.get('X-TTS-Fallback') === 'true';
                if (isFallback) {
                    console.info(`[Dashboard TTS] Використано серверний fallback: ${provider}`);
                    if (voiceStatusText) {
                        voiceStatusText.textContent = `⚠️ Резервний синтез: використано ${provider}`;
                        voiceStatusText.style.color = 'var(--accent-amber)';
                    }
                }
                return res.blob();
            })
            .then(blob => {
                if (!blob || blob.size === 0) {
                    throw new Error('Отримано порожнє аудіо від сервера');
                }
                currentTtsUrl = URL.createObjectURL(blob);
                currentTtsAudio = new Audio(currentTtsUrl);
                currentTtsAudio.onended = fireEnded;
                currentTtsAudio.onerror = () => {
                    console.warn('[Dashboard TTS] Audio playback error, fallback to browser synthesis');
                    if (voiceStatusText) {
                        voiceStatusText.textContent = '⚠️ Резервний синтез: браузерний голос';
                        voiceStatusText.style.color = 'var(--accent-amber)';
                    }
                    playBrowserSpeechSynthesisDash(clean, fireEnded);
                };
                return currentTtsAudio.play();
            })
            .catch(err => {
                console.warn('[Dashboard TTS] Серверний синтез недоступний:', err.message);
                if (voiceStatusText) {
                    voiceStatusText.textContent = '⚠️ Серверний TTS недоступний (резерв: браузерний голос)';
                    voiceStatusText.style.color = 'var(--accent-amber)';
                }
                if ('speechSynthesis' in window) {
                    playBrowserSpeechSynthesisDash(clean, fireEnded);
                } else {
                    // Якщо браузер не має speechSynthesis, передаємо на Bluetooth/PipeWire сервера
                    fetch('/api/voice/speak', {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({ text: clean })
                    }).catch(e => console.warn('Server TTS speak_locally failed:', e));
                    setTimeout(fireEnded, Math.min(Math.max(clean.length * 80, 1800), 5000));
                }
            });
    }

    // --- PROMPT ECHO IMMUNITY & WAKE PARSER ---
    const PROMPT_ECHO_REGEX = /^(?:що\s*(?:тобі|вам)?\s*(?:потрібно|треба)|що\s*(?:потрібно|треба)|потрібно|треба|слухаю|я\s*слухаю)\s*[!?.]*$/i;

    function isPurePromptEcho(text) {
        if (!text || !text.trim()) return true;
        const clean = text.trim().toLowerCase();
        return PROMPT_ECHO_REGEX.test(clean);
    }

    // --- STRIP ECHO & WAKE PREFIXES ---
    function stripEchoAndWakePrefix(text) {
        if (!text || !text.trim()) return '';
        let clean = text.trim();
        // 1. Очищення фрази виклику на початку (наприклад: "Альо гараж, відчини ворота" -> "відчини ворота")
        clean = clean.replace(/^(?:(?:альо|ало|алло|але|оле|ольо)\s*[, -]?\s*гараж(?:у)?|гараж)\s*[,:;!?-]*\s*/i, '');
        // 2. Очищення луни запиту системи, якщо мікрофон почув голос помічника (наприклад: "Що тобі потрібно відчини ворота" -> "відчини ворота")
        clean = clean.replace(/^(?:що\s*(?:тобі|вам)?\s*(?:потрібно|треба)|слухаю|я\s*слухаю)\s*[,:;!?-]*\s*/i, '');
        return clean.trim();
    }

    // --- WAKE WORD PARSER & FILTER ---
    function parseWakeCommand(rawText) {
        if (!rawText || !rawText.trim()) return null;
        const text = rawText.trim();
        const lower = text.toLowerCase();

        // 1. Regex to find wake phrase: альо/ало/алло/але/оле/ольо + гараж
        const wakeRegex = /(?:^|\s)(?:альо|ало|алло|але|оле|ольо)\s*[, -]?\s*гараж(?:у)?(?:\s*[,:;!?-]+\s*|\s+|$)/i;
        const wakeMatch = lower.match(wakeRegex);

        if (wakeMatch) {
            const splitIdx = wakeMatch.index + wakeMatch[0].length;
            const commandAfter = text.substring(splitIdx).replace(/^[,:;!?-]+\s*/, '').trim();
            const cleanSub = stripEchoAndWakePrefix(commandAfter);
            return {
                isWake: true,
                command: cleanSub || null
            };
        }

        // 2. Standalone call phrases: "альо", "ало", "алло", "гараж", "гараж прийом"
        const standaloneRegex = /^(?:альо|ало|алло|гараж|гараж\s*прийом)\s*[!?.]*$/i;
        if (standaloneRegex.test(lower)) {
            return {
                isWake: true,
                command: null
            };
        }

        // 3. Prefix "гараж, <команда>"
        const garagePrefixRegex = /^гараж\s*[,:;-]\s*/i;
        if (garagePrefixRegex.test(lower)) {
            const commandAfter = text.replace(garagePrefixRegex, '').trim();
            const cleanSub = stripEchoAndWakePrefix(commandAfter);
            return {
                isWake: true,
                command: cleanSub || null
            };
        }

        return null;
    }

    // --- CONTROLLING MICROPHONE SAFELY ---
    function startMicrophone() {
        if (isSpeaking || isProcessingCommand) {
            console.log('🔇 startMicrophone заблоковано: система озвучує або обробляє команду.');
            return false;
        }
        if (!recognition) {
            initSpeechRecognition();
        }
        if (!recognition) return false;
        if (isListening) return true;

        clearTimeout(autoRestartTimer);
        autoRestartTimer = null;

        try {
            recognition.start();
            return true;
        } catch (e) {
            if (e.name !== 'InvalidStateError') {
                console.warn('Помилка запуску розпізнавання:', e);
            }
            return false;
        }
    }

    function stopMicrophone() {
        clearTimeout(autoRestartTimer);
        autoRestartTimer = null;
        clearTimeout(followupStartTimer);
        followupStartTimer = null;

        if (recognition) {
            try {
                recognition.abort();
            } catch (_) {}
        }
        isListening = false;
        if (btnMicHero) btnMicHero.classList.remove('listening');
    }

    // --- VOICE SPEECH RECOGNITION (Web Speech API) ---
    function initSpeechRecognition() {
        const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
        if (!SpeechRecognition) {
            const isHttp = window.location.protocol === 'http:';
            if (isHttp && !window.isSecureContext) {
                if (voiceStatusText) {
                    voiceStatusText.innerHTML = '⚠️ <b>Браузер блокує мікрофон по HTTP</b>. Натисніть сюди для інструкції або введіть команду нижче.';
                    voiceStatusText.style.color = '#fbbf24';
                    voiceStatusText.style.cursor = 'pointer';
                    voiceStatusText.onclick = showHttpVoiceHelp;
                }
            } else if (voiceStatusText) {
                voiceStatusText.textContent = 'Голосове розпізнавання підтримується у Chrome / Edge / Android';
            }
            return false;
        }

        try {
            recognition = new SpeechRecognition();
            recognition.continuous = false;
            recognition.interimResults = false;
            recognition.lang = 'uk-UA';

            recognition.onstart = () => {
                if (isSpeaking || isProcessingCommand) {
                    stopMicrophone();
                    return;
                }
                isListening = true;
                if (btnMicHero) btnMicHero.classList.add('listening');
                if (voiceStatusText) {
                    if (isWaitingFollowup) {
                        voiceStatusText.textContent = '🎙️ Слухаю команду... Назвіть дію';
                        voiceStatusText.style.color = 'var(--accent-emerald, #10b981)';
                    } else if (isContinuousWakeMode) {
                        voiceStatusText.textContent = '👂 Слухаю тільки «Альо, гараж»...';
                        voiceStatusText.style.color = '';
                    } else {
                        voiceStatusText.textContent = '🎙️ Слухаю... Говоріть команду';
                        voiceStatusText.style.color = '';
                    }
                }
            };

            recognition.onresult = (event) => {
                const transcript = (event.results[0][0].transcript || '').trim();
                if (!transcript) return;

                // Зупиняємо мікрофон миттєво, щоб система не захопила власний звук або фонові шуми
                stopMicrophone();

                // Якщо почуто виключно власне запитання асистента ("що тобі потрібно" / "що тобі треба") -> це луна!
                if (isPurePromptEcho(transcript)) {
                    console.warn('🔇 [Anti-Loop] Проігноровано акустичну луну запиту помічника:', transcript);
                    if (isWaitingFollowup) {
                        if (voiceStatusText) {
                            voiceStatusText.textContent = '🎙️ Слухаю команду... Назвіть дію';
                            voiceStatusText.style.color = 'var(--accent-emerald, #10b981)';
                        }
                        // Продовжуємо чекати реальну команду користувача
                        setTimeout(() => {
                            if (isWaitingFollowup && !isSpeaking && !isProcessingCommand) {
                                startMicrophone();
                            }
                        }, 500);
                    } else if (isContinuousWakeMode) {
                        setTimeout(() => {
                            if (!isSpeaking && !isProcessingCommand && isContinuousWakeMode) {
                                startMicrophone();
                            }
                        }, 500);
                    }
                    return;
                }

                // 1. Ручне натискання кнопки мікрофона (push-to-talk)
                if (isManualMicSession) {
                    isManualMicSession = false;
                    isWaitingFollowup = false;
                    clearTimeout(followupTimeoutTimer);
                    const cleanCommand = stripEchoAndWakePrefix(transcript);
                    if (!cleanCommand || isPurePromptEcho(cleanCommand)) {
                        updateWakeContinuousUi();
                        return;
                    }
                    if (voiceStatusText) voiceStatusText.textContent = `Ви сказали: "${cleanCommand}"`;
                    executeUserCommand(cleanCommand);
                    return;
                }

                // 2. Відповідь на уточнювальний запит («Що тобі потрібно?»)
                if (isWaitingFollowup) {
                    const cleanCommand = stripEchoAndWakePrefix(transcript);
                    if (!cleanCommand || isPurePromptEcho(cleanCommand)) {
                        console.warn('🔇 [Anti-Loop] Проігноровано луну у сесії очікування команди:', transcript);
                        if (voiceStatusText) {
                            voiceStatusText.textContent = '🎙️ Слухаю команду... Назвіть дію';
                            voiceStatusText.style.color = 'var(--accent-emerald, #10b981)';
                        }
                        setTimeout(() => {
                            if (isWaitingFollowup && !isSpeaking && !isProcessingCommand) {
                                startMicrophone();
                            }
                        }, 500);
                        return;
                    }

                    clearTimeout(followupTimeoutTimer);
                    isWaitingFollowup = false;
                    if (voiceStatusText) voiceStatusText.textContent = `Команда: "${cleanCommand}"`;
                    executeUserCommand(cleanCommand);
                    return;
                }

                // 3. Автоматичний режим очікування фрази «Альо, гараж»
                if (isContinuousWakeMode) {
                    const wake = parseWakeCommand(transcript);
                    if (!wake) {
                        // Розмова в кімнаті без фрази «Альо, гараж» -> ігноруємо
                        console.log('🔇 Проігноровано фонову розмову (немає фрази «Альо, гараж»):', transcript);
                        if (voiceStatusText) {
                            voiceStatusText.textContent = `👂 Очікую «Альо, гараж»... (почуто: "${transcript}")`;
                            setTimeout(() => {
                                if (isContinuousWakeMode && !isWaitingFollowup && !isListening && !isSpeaking && !isProcessingCommand) {
                                    updateWakeContinuousUi();
                                }
                            }, 2500);
                        }
                        return;
                    }

                    // Захист від зациклення: блокуємо повторний виклик wake-слова частіше ніж раз на 4 секунди
                    const now = Date.now();
                    if (now - lastWakeWordTimestamp < 4000) {
                        console.warn('🔇 [Anti-Loop] Cooldown wake-слова (4с): ігноруємо повторний тригер');
                        setTimeout(() => {
                            if (isContinuousWakeMode && !isWaitingFollowup && !isListening && !isSpeaking && !isProcessingCommand) {
                                startMicrophone();
                            }
                        }, 1000);
                        return;
                    }
                    lastWakeWordTimestamp = now;

                    // Фраза «Альо, гараж» розпізнана!
                    hapticFeedback(50);
                    if (wake.command) {
                        const cleanCommand = stripEchoAndWakePrefix(wake.command);
                        if (!cleanCommand || isPurePromptEcho(cleanCommand)) {
                            if (voiceStatusText) voiceStatusText.textContent = `⚡ «Альо, гараж» розпізнано!`;
                            executeUserCommand("Альо, гараж");
                        } else {
                            if (voiceStatusText) voiceStatusText.textContent = `⚡ «Альо, гараж»: ${cleanCommand}`;
                            executeUserCommand(cleanCommand);
                        }
                    } else {
                        if (voiceStatusText) voiceStatusText.textContent = `⚡ «Альо, гараж» розпізнано!`;
                        executeUserCommand("Альо, гараж");
                    }
                    return;
                }

                // 4. Звичайний режим
                const cleanCommand = stripEchoAndWakePrefix(transcript);
                if (!cleanCommand || isPurePromptEcho(cleanCommand)) {
                    updateWakeContinuousUi();
                    return;
                }
                if (voiceStatusText) voiceStatusText.textContent = `Ви сказали: "${cleanCommand}"`;
                executeUserCommand(cleanCommand);
            };

            recognition.onerror = (event) => {
                console.warn('Speech recognition error:', event.error);
                isListening = false;
                if (btnMicHero) btnMicHero.classList.remove('listening');
                if (event.error === 'not-allowed') {
                    if (voiceStatusText) {
                        voiceStatusText.textContent = '⚠️ Доступ до мікрофона заблоковано браузером (надайте дозвіл)';
                        voiceStatusText.style.color = '#ef4444';
                    }
                } else if (event.error === 'network') {
                    if (voiceStatusText) {
                        voiceStatusText.textContent = '⚠️ Збій мережі розпізнавання мови Google. Введіть команду текстом';
                        voiceStatusText.style.color = '#ef4444';
                    }
                } else if (event.error === 'no-speech') {
                    if (!isContinuousWakeMode && !isWaitingFollowup && voiceStatusText) {
                        voiceStatusText.textContent = 'Голос не виявлено. Натисніть і спробуйте знову';
                    }
                } else if (event.error !== 'aborted') {
                    if (voiceStatusText) voiceStatusText.textContent = `Помилка: ${event.error}. Спробуйте ще раз`;
                }
            };

            recognition.onend = () => {
                isListening = false;
                if (btnMicHero) btnMicHero.classList.remove('listening');

                // ЖОРСТКЕ ПРАВИЛО: Якщо система озвучує або обробляє команду, мікрофон НЕ вмикається!
                if (isSpeaking || isProcessingCommand) {
                    return;
                }

                // Авто-перезапуск у режимі постійного слухання або очікування команди після запиту
                if (isContinuousWakeMode || isWaitingFollowup) {
                    clearTimeout(autoRestartTimer);
                    autoRestartTimer = setTimeout(() => {
                        try {
                            if (!isListening && !isSpeaking && !isProcessingCommand && (isContinuousWakeMode || isWaitingFollowup)) {
                                startMicrophone();
                            }
                        } catch (_) {}
                    }, 350);
                }
            };
            return true;
        } catch (e) {
            console.error('Failed to create SpeechRecognition:', e);
            return false;
        }
    }

    function showHttpVoiceHelp() {
        const origin = window.location.origin;
        const alertMsg = "🔒 ЧОМУ МІКРОФОН НЕ ПРАЦЮЄ НА ТЕЛЕФОНІ:\n\n" +
            "Мобільні браузери (Chrome/Android) з міркувань безпеки повністю вимикають розпізнавання голосу на сайтах без HTTPS (звичайний http://).\n\n" +
            "ЯК УВІМКНУТИ ГОЛОС У CHROME НА ANDROID (1 хвилина):\n" +
            "1. Відкрийте у Chrome нову вкладку та перейдіть на:\n" +
            "   chrome://flags/#unsafely-treat-insecure-origin-as-secure\n\n" +
            "2. У полі 'Insecure origins treated as secure' введіть адресу дашборду:\n" +
            "   " + origin + "\n\n" +
            "3. Перемкніть перемикач на 'Enabled' і натисніть синю кнопку 'Relaunch' внизу.\n\n" +
            "💡 ШВИДКА АЛЬТЕРНАТИВА:\n" +
            "Натисніть на поле вводу тексту внизу — на клавіатурі смартфона є власний мікрофон для надиктовування тексту українською мовою!";
        alert(alertMsg);
        if (voiceInput) voiceInput.focus();
    }

    initSpeechRecognition();

    function updateWakeContinuousUi() {
        if (!btnWakeContinuous) return;
        if (isContinuousWakeMode) {
            btnWakeContinuous.classList.add('active');
            if (wakeContinuousLabel) wakeContinuousLabel.textContent = '«Альо, гараж»: Активно';
            btnWakeContinuous.title = 'Режим авто-слухання активний (натисніть, щоб вимкнути)';
            if (voiceStatusText && !isListening && !isSpeaking && !isProcessingCommand) {
                voiceStatusText.textContent = '👂 Слухаю тільки «Альо, гараж»... (інші розмови ігноруються)';
                voiceStatusText.style.color = '';
            }
        } else {
            btnWakeContinuous.classList.remove('active');
            if (wakeContinuousLabel) wakeContinuousLabel.textContent = '«Альо, гараж»: Вимкнено';
            btnWakeContinuous.title = 'Режим авто-слухання вимкнено (натисніть, щоб увімкнути)';
            if (voiceStatusText && !isListening && !isSpeaking && !isProcessingCommand) {
                voiceStatusText.textContent = 'Натисніть мікрофон або скажіть «Альо, гараж»';
                voiceStatusText.style.color = '';
            }
        }
    }

    if (btnWakeContinuous) {
        btnWakeContinuous.addEventListener('click', () => {
            hapticFeedback(30);
            if (!recognition) {
                initSpeechRecognition();
            }
            if (!recognition) {
                showHttpVoiceHelp();
                return;
            }
            isContinuousWakeMode = !isContinuousWakeMode;
            localStorage.setItem('smartgarage_wake_continuous', isContinuousWakeMode ? 'true' : 'false');
            updateWakeContinuousUi();
            if (isContinuousWakeMode) {
                if (!isSpeaking && !isProcessingCommand) {
                    startMicrophone();
                }
            } else {
                isWaitingFollowup = false;
                isManualMicSession = false;
                clearTimeout(followupTimeoutTimer);
                stopMicrophone();
            }
        });
        updateWakeContinuousUi();
        if (isContinuousWakeMode) {
            setTimeout(() => {
                if (!isListening && !isSpeaking && !isProcessingCommand) {
                    startMicrophone();
                }
            }, 800);
        }
    }

    if (btnMicHero) {
        btnMicHero.addEventListener('click', () => {
            hapticFeedback(40);
            if (!recognition) {
                initSpeechRecognition();
            }
            if (!recognition) {
                showHttpVoiceHelp();
                return;
            }

            if (isListening) {
                isManualMicSession = false;
                isWaitingFollowup = false;
                clearTimeout(followupTimeoutTimer);
                stopMicrophone();
            } else {
                // Якщо система говорить, перериваємо мову при натисканні користувачем
                if (isSpeaking || currentTtsAudio) {
                    if (currentTtsAudio) {
                        try { currentTtsAudio.pause(); } catch (_) {}
                        currentTtsAudio = null;
                    }
                    if ('speechSynthesis' in window) {
                        try { window.speechSynthesis.cancel(); } catch (_) {}
                    }
                    isSpeaking = false;
                    if (btnMicHero) btnMicHero.classList.remove('speaking');
                }
                isProcessingCommand = false;
                isManualMicSession = true;
                isWaitingFollowup = false;
                clearTimeout(followupTimeoutTimer);
                startMicrophone();
            }
        });
    }

    // --- COMMAND EXECUTION VIA HTTP ---
    async function executeUserCommand(commandText) {
        if (!commandText || !commandText.trim()) return;

        // 1. Миттєво блокуємо мікрофон на час обробки
        isProcessingCommand = true;
        stopMicrophone();

        // 2. Якщо вхідний рядок є виключно луною запиту помічника — блокуємо відправку
        if (isPurePromptEcho(commandText) && !/^(?:альо|ало|алло)\s*[, -]?\s*гараж(?:у)?/i.test(commandText.trim())) {
            console.warn('🔇 [Anti-Loop] executeUserCommand відхилив луну запиту:', commandText);
            isProcessingCommand = false;
            if (isContinuousWakeMode) {
                setTimeout(startMicrophone, 500);
            }
            return;
        }

        let query = stripEchoAndWakePrefix(commandText);
        if (!query) {
            if (/^(?:альо|ало|алло)\s*[, -]?\s*гараж(?:у)?/i.test(commandText.trim())) {
                query = "Альо, гараж";
            } else {
                isProcessingCommand = false;
                if (isContinuousWakeMode) {
                    setTimeout(startMicrophone, 500);
                }
                return;
            }
        }

        if (dialogUserText) dialogUserText.textContent = query;
        if (dialogAiText) dialogAiText.textContent = 'Обробляю запит...';
        if (voiceDialogBox) voiceDialogBox.style.display = 'flex';
        if (voiceStatusText) {
            voiceStatusText.textContent = '⏳ Обробляю команду...';
            voiceStatusText.style.color = '';
        }

        try {
            let webSessionId = sessionStorage.getItem('sg_session_id');
            const reqPayload = { command: query };
            if (webSessionId) {
                reqPayload.session_id = webSessionId;
            }

            const res = await fetch('/command', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(reqPayload)
            });
            if (res.status === 403) {
                sessionStorage.removeItem('sg_session_id');
            }
            const data = await res.json();
            if (data.session_id) {
                sessionStorage.setItem('sg_session_id', data.session_id);
            }
            const reply = (data.response || '').trim();
            if (!reply || data.ignored) {
                // Сервер відхилив порожній або луновий запит
                isProcessingCommand = false;
                if (isContinuousWakeMode) {
                    setTimeout(() => {
                        if (!isSpeaking && !isProcessingCommand && isContinuousWakeMode) {
                            startMicrophone();
                            updateWakeContinuousUi();
                        }
                    }, 500);
                }
                return;
            }

            if (dialogAiText) dialogAiText.textContent = reply;

            // Перевіряємо, чи це запит готовності слухати («Що тобі потрібно?», «Що тобі треба?», «Слухаю»)
            const isFollowUpPrompt = /(?:потрібно|треба|слухаю|що\s*хочете|яка\s*команда)/i.test(reply);

            if (isFollowUpPrompt) {
                if (voiceStatusText) {
                    voiceStatusText.textContent = `🗣️ «${reply}»`;
                    voiceStatusText.style.color = '';
                }
            } else {
                if (voiceStatusText) {
                    voiceStatusText.textContent = '🗣️ Озвучую відповідь...';
                    voiceStatusText.style.color = '';
                }
            }

            speakText(reply, () => {
                // Цей callback викликається ВИКЛЮЧНО ПІСЛЯ ТОГО, як озвучення ПОВНІСТЮ завершилося!
                isProcessingCommand = false;

                if (isFollowUpPrompt) {
                    // Система завершила свій запит «Що тобі потрібно?».
                    // Тільки тепер вмикаємо мікрофон для подальшої команди!
                    isWaitingFollowup = true;
                    clearTimeout(followupTimeoutTimer);
                    followupTimeoutTimer = setTimeout(() => {
                        isWaitingFollowup = false;
                        updateWakeContinuousUi();
                    }, 10000);

                    // Додаємо акустичну паузу (750 мс) для Bluetooth-затримки та луни гаража
                    clearTimeout(followupStartTimer);
                    followupStartTimer = setTimeout(() => {
                        if (isWaitingFollowup && !isSpeaking && !isProcessingCommand) {
                            if (voiceStatusText) {
                                voiceStatusText.textContent = '🎙️ Слухаю команду... Назвіть дію';
                                voiceStatusText.style.color = 'var(--accent-emerald, #10b981)';
                            }
                            startMicrophone();
                        }
                    }, 750);
                } else {
                    // Звичайна команда та її відповідь завершені
                    isWaitingFollowup = false;
                    clearTimeout(followupTimeoutTimer);
                    if (isContinuousWakeMode) {
                        clearTimeout(autoRestartTimer);
                        autoRestartTimer = setTimeout(() => {
                            if (!isSpeaking && !isProcessingCommand && isContinuousWakeMode) {
                                startMicrophone();
                                updateWakeContinuousUi();
                            }
                        }, 400);
                    } else {
                        updateWakeContinuousUi();
                    }
                }
            });
            fetchTelemetry();
        } catch (err) {
            isProcessingCommand = false;
            const errReply = 'Помилка зв\'язку з сервером.';
            if (dialogAiText) dialogAiText.textContent = errReply;
            speakText(errReply, () => {
                if (isContinuousWakeMode) {
                    clearTimeout(autoRestartTimer);
                    autoRestartTimer = setTimeout(() => {
                        if (!isSpeaking && !isProcessingCommand && isContinuousWakeMode) {
                            startMicrophone();
                            updateWakeContinuousUi();
                        }
                    }, 400);
                }
            });
        }
    }

    if (voiceForm) {
        voiceForm.addEventListener('submit', (e) => {
            e.preventDefault();
            const text = voiceInput.value;
            if (text) {
                executeUserCommand(text);
                voiceInput.value = '';
            }
        });
    }

    // --- TOUCH TILES CONTROLS ---
    if (tileLight) {
        tileLight.addEventListener('click', async () => {
            hapticFeedback();
            try {
                const res = await fetch('/api/device/light/toggle', { method: 'POST' });
                const data = await res.json();
                updateLightState(data.light);
            } catch (err) {
                console.error(err);
            }
        });
    }

    if (tileFan) {
        tileFan.addEventListener('click', async () => {
            hapticFeedback();
            try {
                const res = await fetch('/api/device/fan/toggle', { method: 'POST' });
                const data = await res.json();
                updateFanState(data.fan);
            } catch (err) {
                console.error(err);
            }
        });
    }

    // Keyboard activation (Enter/Space) for interactive tiles and floor cards
    const floorCard1 = document.getElementById('floorCard1');
    const floorCard2 = document.getElementById('floorCard2');
    const floorCardBasement = document.getElementById('floorCardBasement');
    [tileLight, tileFan, floorCard1, floorCard2, floorCardBasement].forEach(el => {
        if (!el) return;
        el.addEventListener('keydown', (e) => {
            if (e.key === 'Enter' || e.key === ' ') {
                e.preventDefault();
                el.click();
            }
        });
    });


    if (btnAllLightsOn) {
        btnAllLightsOn.addEventListener('click', async () => {
            hapticFeedback();
            await fetch('/api/device/light/state', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ state: true })
            });
            fetchTelemetry();
        });
    }

    if (btnAllLightsOff) {
        btnAllLightsOff.addEventListener('click', async () => {
            hapticFeedback();
            await fetch('/api/device/light/state', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ state: false })
            });
            fetchTelemetry();
        });
    }

    function updateLightState(on) {
        isLightOn = !!on;
        if (tileLight) {
            if (isLightOn) {
                tileLight.classList.add('active-light');
                if (statusLight) statusLight.textContent = 'Увімкнено';
            } else {
                tileLight.classList.remove('active-light');
                if (statusLight) statusLight.textContent = 'Вимкнено';
            }
        }
    }

    function updateFanState(on) {
        isFanOn = !!on;
        if (tileFan) {
            if (isFanOn) {
                tileFan.classList.add('active-fan');
                if (statusFan) statusFan.textContent = 'Увімкнено';
            } else {
                tileFan.classList.remove('active-fan');
                if (statusFan) statusFan.textContent = 'Вимкнено';
            }
        }
    }

    // --- AUTOMATION SCENARIOS ---
    scenarioBtns.forEach(btn => {
        btn.addEventListener('click', async () => {
            hapticFeedback(35);
            const scenario = btn.getAttribute('data-scenario');
            if (!scenario) return;

            btn.style.opacity = '0.6';
            try {
                const res = await fetch(`/api/scenarios/${scenario}`, { method: 'POST' });
                const data = await res.json();
                if (voiceStatusText) voiceStatusText.textContent = data.response || 'Сценарій виконано';
                if (ttsEnabled) speakText(data.response || 'Сценарій виконано');
                fetchTelemetry();
            } catch (err) {
                console.error(err);
            } finally {
                btn.style.opacity = '1';
            }
        });
    });

    // --- MEDIA & PROJECTOR ---
    if (btnProjPause) {
        btnProjPause.addEventListener('click', () => {
            hapticFeedback();
            fetch('/api/media/control', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ action: 'pause' })
            });
        });
    }

    if (btnProjResume) {
        btnProjResume.addEventListener('click', () => {
            hapticFeedback();
            fetch('/api/media/control', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ action: 'resume' })
            });
        });
    }

    if (btnProjStop) {
        btnProjStop.addEventListener('click', () => {
            hapticFeedback();
            fetch('/api/media/control', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ action: 'stop' })
            });
        });
    }

    if (btnProjMirror) {
        btnProjMirror.addEventListener('click', async () => {
            hapticFeedback();
            const res = await fetch('/api/projector/mirror', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ action: 'toggle' })
            });
            const data = await res.json();
            if (btnProjMirror) {
                btnProjMirror.classList.toggle('active', !!data.mirroring);
            }
        });
    }

    if (mediaStreamForm) {
        mediaStreamForm.addEventListener('submit', async (e) => {
            e.preventDefault();
            hapticFeedback();
            const query = mediaStreamInput.value.trim();
            if (!query) return;
            if (voiceStatusText) voiceStatusText.textContent = `Запуск стріму: ${query}...`;
            try {
                const res = await fetch('/api/media/stream_url', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ query: query })
                });
                const data = await res.json();
                if (voiceStatusText) voiceStatusText.textContent = data.response || 'Стрім запущено';
                if (ttsEnabled) speakText(data.response);
                mediaStreamInput.value = '';
            } catch (err) {
                if (voiceStatusText) voiceStatusText.textContent = 'Помилка запуску стріму';
            }
        });
    }

    // --- JBL SPEAKER CONTROLS ---
    let isVolumeDragging = false;

    // Speaker switching logic between JX-BT and JBL Clip 5
    async function switchSpeaker(targetMac) {
        hapticFeedback();
        const isJbl = targetMac === 'garage' || targetMac === 'jbl' || (typeof targetMac === 'string' && targetMac.toLowerCase().includes('jbl'));
        const targetBtn = isJbl ? btnSpeakerJbl : btnSpeakerJxbt;
        const otherBtn = isJbl ? btnSpeakerJxbt : btnSpeakerJbl;
        const name = isJbl ? 'JBL Clip 5 (Гараж)' : 'JX-BT (1-й поверх)';

        if (targetBtn) targetBtn.classList.add('active');
        if (otherBtn) otherBtn.classList.remove('active');

        if (voiceStatusText) {
            voiceStatusText.textContent = `Перемикання аудіо на ${name}...`;
            voiceStatusText.style.color = 'var(--accent-cyan)';
        }

        try {
            const res = await fetch('/api/speaker/switch', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ mac: targetMac })
            });
            const data = await res.json();
            if (data.success) {
                if (voiceStatusText) {
                    voiceStatusText.textContent = data.response || `Підключено: ${name}`;
                }
            } else {
                if (voiceStatusText) {
                    voiceStatusText.textContent = `⚠️ ${data.response || 'Помилка перемикання'}`;
                    voiceStatusText.style.color = '#ef4444';
                }
            }
            if (ttsEnabled && data.response) speakText(data.response);
            fetchTelemetry();
        } catch (e) {
            if (voiceStatusText) {
                voiceStatusText.textContent = `Помилка зв'язку з ${name}`;
                voiceStatusText.style.color = '#ef4444';
            }
        }
    }

    if (btnSpeakerJxbt) {
        btnSpeakerJxbt.addEventListener('click', () => switchSpeaker('floor1'));
    }
    if (btnSpeakerJbl) {
        btnSpeakerJbl.addEventListener('click', () => switchSpeaker('garage'));
    }

    if (speakerSelect) {
        speakerSelect.addEventListener('change', () => {
            const mac = speakerSelect.value;
            switchSpeaker(mac);
        });
    }

    if (btnJblConnect) {
        btnJblConnect.addEventListener('click', async () => {
            hapticFeedback();
            const targetMac = speakerSelect ? speakerSelect.value : undefined;
            btnJblConnect.textContent = 'З\'єднання...';
            try {
                const res = await fetch('/api/speaker/connect', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(targetMac ? { mac: targetMac } : {})
                });
                const data = await res.json();
                if (voiceStatusText) voiceStatusText.textContent = data.response;
                if (ttsEnabled) speakText(data.response);
                fetchTelemetry();
            } catch (e) {
                if (voiceStatusText) voiceStatusText.textContent = 'Помилка підключення до аудіосистеми';
            } finally {
                btnJblConnect.textContent = '🔗 З\'єднати';
            }
        });
    }

    if (btnJblDisconnect) {
        btnJblDisconnect.addEventListener('click', async () => {
            hapticFeedback();
            try {
                const res = await fetch('/api/speaker/disconnect', { method: 'POST' });
                const data = await res.json();
                if (voiceStatusText) voiceStatusText.textContent = data.response;
                fetchTelemetry();
            } catch (e) { }
        });
    }

    if (jblVolumeSlider) {
        jblVolumeSlider.addEventListener('mousedown', () => { isVolumeDragging = true; });
        jblVolumeSlider.addEventListener('touchstart', () => { isVolumeDragging = true; });
        jblVolumeSlider.addEventListener('input', () => {
            if (jblVolumeVal) jblVolumeVal.textContent = `${jblVolumeSlider.value}%`;
        });
        jblVolumeSlider.addEventListener('change', async () => {
            isVolumeDragging = false;
            hapticFeedback();
            await fetch('/api/speaker/volume', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ value: parseInt(jblVolumeSlider.value, 10) })
            });
        });
        jblVolumeSlider.addEventListener('mouseup', () => { isVolumeDragging = false; });
        jblVolumeSlider.addEventListener('touchend', () => { isVolumeDragging = false; });
    }

    function formatDashTime(secs) {
        if (!secs || isNaN(secs) || secs < 0) return '00:00';
        const m = Math.floor(secs / 60);
        const s = Math.floor(secs % 60);
        return `${m.toString().padStart(2, '0')}:${s.toString().padStart(2, '0')}`;
    }

    if (btnJblPrev) {
        btnJblPrev.addEventListener('click', async () => {
            hapticFeedback();
            if (voiceStatusText) voiceStatusText.textContent = 'Попередній трек...';
            try {
                const res = await fetch('/api/ytmusic/prev', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({})
                });
                const data = await res.json();
                if (data.success && data.track_title && jblNowPlaying) {
                    jblNowPlaying.textContent = `🎵 ${data.track_title}`;
                }
                if (voiceStatusText && data.response) {
                    voiceStatusText.textContent = data.response;
                    voiceStatusText.style.color = 'var(--accent-cyan)';
                }
                fetchTelemetry();
            } catch (e) {
                if (voiceStatusText) {
                    voiceStatusText.textContent = 'Помилка перемикання на попередній трек';
                    voiceStatusText.style.color = '#ef4444';
                }
            }
        });
    }

    if (btnJblRewind) {
        btnJblRewind.addEventListener('click', async () => {
            hapticFeedback();
            try {
                await fetch('/api/speaker/seek', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ delta: -10 })
                });
                fetchTelemetry();
            } catch (e) {}
        });
    }

    if (btnJblPause) {
        btnJblPause.addEventListener('click', () => {
            hapticFeedback();
            fetch('/api/speaker/control', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ action: 'pause' })
            });
        });
    }

    if (btnJblResume) {
        btnJblResume.addEventListener('click', () => {
            hapticFeedback();
            fetch('/api/speaker/control', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ action: 'resume' })
            });
        });
    }

    if (btnJblForward) {
        btnJblForward.addEventListener('click', async () => {
            hapticFeedback();
            try {
                await fetch('/api/speaker/seek', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ delta: 10 })
                });
                fetchTelemetry();
            } catch (e) {}
        });
    }

    if (btnJblStop) {
        btnJblStop.addEventListener('click', () => {
            hapticFeedback();
            fetch('/api/speaker/control', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ action: 'stop' })
            });
            if (jblNowPlaying) jblNowPlaying.textContent = 'Немає активного відтворення';
        });
    }

    const btnJblNext = document.getElementById('btnJblNext');
    if (btnJblNext) {
        btnJblNext.addEventListener('click', async () => {
            hapticFeedback();
            if (voiceStatusText) voiceStatusText.textContent = 'Перемикання треку...';
            try {
                const res = await fetch('/api/ytmusic/next', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({})
                });
                const data = await res.json();
                if (data.success && data.track_title && jblNowPlaying) {
                    jblNowPlaying.textContent = `🎵 ${data.track_title}`;
                }
                if (voiceStatusText && data.response) {
                    voiceStatusText.textContent = data.response;
                    voiceStatusText.style.color = 'var(--accent-cyan)';
                }
                fetchTelemetry();
            } catch (e) {
                if (voiceStatusText) {
                    voiceStatusText.textContent = 'Помилка перемикання треку';
                    voiceStatusText.style.color = '#ef4444';
                }
            }
        });
    }

    if (dashTimelineSlider) {
        dashTimelineSlider.addEventListener('input', () => {
            isDashScrubbing = true;
            const targetSec = parseInt(dashTimelineSlider.value, 10);
            if (dashMediaTimeElapsed) dashMediaTimeElapsed.textContent = formatDashTime(targetSec);
        });

        const commitDashSeek = async () => {
            if (!isDashScrubbing) return;
            const targetSec = parseInt(dashTimelineSlider.value, 10);
            try {
                await fetch('/api/speaker/seek', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ position: targetSec })
                });
            } catch (e) {}
            setTimeout(() => {
                isDashScrubbing = false;
                fetchTelemetry();
            }, 400);
        };

        dashTimelineSlider.addEventListener('change', commitDashSeek);
        dashTimelineSlider.addEventListener('mouseup', commitDashSeek);
        dashTimelineSlider.addEventListener('touchend', commitDashSeek);
    }

    if (jblPlayForm) {
        jblPlayForm.addEventListener('submit', async (e) => {
            e.preventDefault();
            hapticFeedback();
            const query = jblPlayInput.value.trim();
            if (!query) return;
            if (voiceStatusText) voiceStatusText.textContent = `Запуск на колонці: ${query}...`;
            try {
                const res = await fetch('/api/speaker/play', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ query: query })
                });
                const data = await res.json();
                if (data.success) {
                    if (voiceStatusText) {
                        voiceStatusText.textContent = data.response || 'Відтворення запущено';
                        voiceStatusText.style.color = 'var(--accent-cyan)';
                    }
                } else {
                    if (voiceStatusText) {
                        voiceStatusText.textContent = `⚠️ ${data.response || 'Помилка відтворення'}`;
                        voiceStatusText.style.color = '#ef4444';
                    }
                }
                if (ttsEnabled && data.response) speakText(data.response);
                jblPlayInput.value = '';
                fetchTelemetry();
            } catch (err) {
                if (voiceStatusText) {
                    voiceStatusText.textContent = 'Помилка відтворення на колонці';
                    voiceStatusText.style.color = '#ef4444';
                }
            }
        });
    }

    // --- INTERNET RADIO (RADIO BROWSER & QUICK PICKS) ---
    async function playRadioStation(streamUrl, stationName) {
        hapticFeedback();
        currentRadioUrl = streamUrl;

        // Highlight matching quick pick button
        if (radioQuickPicks) {
            radioQuickPicks.querySelectorAll('.radio-quick-btn').forEach(btn => {
                const btnUrl = btn.getAttribute('data-url');
                const btnName = btn.getAttribute('data-name');
                if (btnUrl === streamUrl || btnName === stationName) {
                    btn.classList.add('active');
                } else {
                    btn.classList.remove('active');
                }
            });
        }
        // Highlight matching radio chip
        if (radioStationsContainer) {
            radioStationsContainer.querySelectorAll('.radio-chip').forEach(c => {
                const chipName = c.querySelector('span[title]') ? c.querySelector('span[title]').getAttribute('title') : '';
                if (chipName === stationName) {
                    c.classList.add('active');
                } else {
                    c.classList.remove('active');
                }
            });
        }

        if (voiceStatusText) {
            voiceStatusText.textContent = `Запуск радіо: ${stationName}...`;
            voiceStatusText.style.color = 'var(--accent-cyan)';
        }

        try {
            const res = await fetch('/api/radio/play', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ url: streamUrl, name: stationName })
            });
            const data = await res.json();
            if (data.success) {
                if (jblNowPlaying) jblNowPlaying.textContent = `📻 ${stationName}`;
                if (voiceStatusText) {
                    voiceStatusText.textContent = data.response || `Грає ${stationName}`;
                    voiceStatusText.style.color = 'var(--accent-cyan)';
                }
            } else {
                if (voiceStatusText) {
                    voiceStatusText.textContent = `⚠️ ${data.response || 'Помилка запуску'}`;
                    voiceStatusText.style.color = '#ef4444';
                }
            }
            if (ttsEnabled && data.response) speakText(data.response);
            fetchTelemetry();
        } catch (err) {
            if (voiceStatusText) {
                voiceStatusText.textContent = `Помилка запуску ${stationName}`;
                voiceStatusText.style.color = '#ef4444';
            }
        }
    }

    if (radioQuickPicks) {
        radioQuickPicks.querySelectorAll('.radio-quick-btn').forEach(btn => {
            btn.addEventListener('click', () => {
                const url = btn.getAttribute('data-url');
                const name = btn.getAttribute('data-name');
                if (url) playRadioStation(url, name);
            });
        });
    }

    async function loadRadioStations(query = '') {
        if (!radioStationsContainer) return;
        radioStationsContainer.innerHTML = '<div style="font-size: 0.75rem; color: var(--text-muted); padding: 4px;">⏳ Завантаження станцій...</div>';
        try {
            const url = query ? `/api/radio/search?q=${encodeURIComponent(query)}` : '/api/radio/stations?limit=24';
            const res = await fetch(url);
            const data = await res.json();
            if (data.success && data.stations && data.stations.length > 0) {
                renderRadioStations(data.stations);
            } else {
                radioStationsContainer.innerHTML = '<div style="font-size: 0.75rem; color: var(--text-muted); padding: 4px;">Станцій не знайдено</div>';
            }
        } catch (e) {
            radioStationsContainer.innerHTML = '<div style="font-size: 0.75rem; color: var(--accent-pink); padding: 4px;">Помилка завантаження станцій</div>';
        }
    }

    function renderRadioStations(stations) {
        if (!radioStationsContainer) return;
        radioStationsContainer.innerHTML = '';
        stations.forEach(st => {
            const chip = document.createElement('div');
            chip.className = 'radio-chip';
            chip.setAttribute('role', 'button');
            chip.setAttribute('tabindex', '0');
            chip.setAttribute('aria-label', `Увімкнути радіостанцію ${st.name}`);
            if (currentRadioUrl === st.url) {
                chip.classList.add('active');
            }

            const imgHtml = st.favicon ? `<img src="${st.favicon}" alt="" onerror="this.style.display='none'">` : '<span>📻</span>';
            const cleanName = st.name.length > 22 ? st.name.substring(0, 20) + '...' : st.name;
            const primaryTag = st.tags ? st.tags.split(',')[0].trim() : '';

            chip.innerHTML = `
                ${imgHtml}
                <span title="${st.name}">${cleanName}</span>
                ${primaryTag ? `<span class="radio-tag">${primaryTag}</span>` : ''}
            `;

            chip.addEventListener('keydown', (e) => {
                if (e.key === 'Enter' || e.key === ' ') {
                    e.preventDefault();
                    chip.click();
                }
            });

            chip.addEventListener('click', () => {
                playRadioStation(st.url, st.name);
            });

            radioStationsContainer.appendChild(chip);
        });
    }

    if (btnRadioSearch && radioSearchInput) {
        btnRadioSearch.addEventListener('click', () => {
            hapticFeedback();
            const q = radioSearchInput.value.trim();
            loadRadioStations(q);
        });

        radioSearchInput.addEventListener('keydown', (e) => {
            if (e.key === 'Enter') {
                e.preventDefault();
                hapticFeedback();
                const q = radioSearchInput.value.trim();
                loadRadioStations(q);
            }
        });
    }

    if (btnRadioReset) {
        btnRadioReset.addEventListener('click', () => {
            hapticFeedback();
            if (radioSearchInput) radioSearchInput.value = '';
            loadRadioStations('');
        });
    }

    // --- DASHBOARD YOUTUBE MUSIC & AUDIO SOURCE SWITCHER ---
    const btnDashTabYtmusic = document.getElementById('btnDashTabYtmusic');
    const btnDashTabRadio = document.getElementById('btnDashTabRadio');
    const dashYtmusicPanel = document.getElementById('dashYtmusicPanel');
    const dashRadioPanel = document.getElementById('dashRadioPanel');

    const btnDashYtLiked = document.getElementById('btnDashYtLiked');
    const btnDashYtShuffleLiked = document.getElementById('btnDashYtShuffleLiked');
    const dashYtLikedBadge = document.getElementById('dashYtLikedBadge');
    const dashYtPlaylistsContainer = document.getElementById('dashYtPlaylistsContainer');
    const btnDashRefreshPlaylists = document.getElementById('btnDashRefreshPlaylists');

    if (btnDashTabYtmusic && btnDashTabRadio) {
        btnDashTabYtmusic.addEventListener('click', () => {
            hapticFeedback();
            btnDashTabYtmusic.classList.add('active');
            btnDashTabRadio.classList.remove('active');
            if (dashYtmusicPanel) dashYtmusicPanel.style.display = 'block';
            if (dashRadioPanel) dashRadioPanel.style.display = 'none';
        });

        btnDashTabRadio.addEventListener('click', () => {
            hapticFeedback();
            btnDashTabRadio.classList.add('active');
            btnDashTabYtmusic.classList.remove('active');
            if (dashRadioPanel) dashRadioPanel.style.display = 'block';
            if (dashYtmusicPanel) dashYtmusicPanel.style.display = 'none';
        });
    }

    async function playDashYTPlaylist(playlistId, shuffle = false, title = '') {
        hapticFeedback();
        const displayTitle = title || (playlistId === 'LM' ? 'Улюблені пісні' : 'Плейлист');
        if (voiceStatusText) {
            voiceStatusText.textContent = `Запуск '${displayTitle}'...`;
            voiceStatusText.style.color = 'var(--accent-cyan)';
        }

        try {
            const res = await fetch('/api/ytmusic/play', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    playlist_id: playlistId,
                    shuffle: shuffle
                })
            });
            const data = await res.json();
            if (data.success) {
                if (data.track_title && jblNowPlaying) {
                    jblNowPlaying.textContent = `🎵 ${data.track_title}`;
                }
                if (voiceStatusText) {
                    voiceStatusText.textContent = data.response || `Грає ${displayTitle}`;
                    voiceStatusText.style.color = 'var(--accent-cyan)';
                }
            } else {
                if (voiceStatusText) {
                    voiceStatusText.textContent = `⚠️ ${data.response || 'Помилка відтворення'}`;
                    voiceStatusText.style.color = '#ef4444';
                }
            }
            if (ttsEnabled && data.response) speakText(data.response);
            fetchTelemetry();
        } catch (err) {
            if (voiceStatusText) {
                voiceStatusText.textContent = `Помилка запуску '${displayTitle}'`;
                voiceStatusText.style.color = '#ef4444';
            }
        }
    }

    if (btnDashYtLiked) {
        btnDashYtLiked.addEventListener('click', () => {
            playDashYTPlaylist('LM', false, 'Улюблені пісні');
        });
    }

    if (btnDashYtShuffleLiked) {
        btnDashYtShuffleLiked.addEventListener('click', () => {
            playDashYTPlaylist('LM', true, 'Улюблені пісні');
        });
    }

    async function loadDashYTPlaylists(forceRefresh = false) {
        if (!dashYtPlaylistsContainer) return;
        dashYtPlaylistsContainer.innerHTML = '<div style="font-size: 0.75rem; color: var(--text-muted); padding: 4px;">⏳ Оновлення...</div>';

        try {
            const res = await fetch(`/api/ytmusic/playlists?refresh=${forceRefresh ? 1 : 0}`);
            const data = await res.json();
            if (data.success && data.playlists) {
                const likedPl = data.playlists.find(p => p.is_liked || p.id === 'LM');
                if (likedPl && dashYtLikedBadge) {
                    dashYtLikedBadge.textContent = `${likedPl.track_count || 116}+ треків`;
                }

                const customPlaylists = data.playlists.filter(p => !p.is_liked && p.id !== 'LM');
                dashYtPlaylistsContainer.innerHTML = '';
                if (customPlaylists.length === 0) {
                    dashYtPlaylistsContainer.innerHTML = '<div style="font-size: 0.75rem; color: var(--text-muted); padding: 4px;">Плейлистів не знайдено</div>';
                    return;
                }

                customPlaylists.forEach(pl => {
                    const chip = document.createElement('button');
                    chip.type = 'button';
                    chip.className = 'yt-dash-chip';
                    chip.innerHTML = `
                        <span>🎵</span>
                        <span title="${pl.title}">${pl.title.length > 20 ? pl.title.substring(0, 18) + '...' : pl.title}</span>
                        ${pl.track_count ? `<span class="dash-chip-badge">${pl.track_count}</span>` : ''}
                    `;
                    chip.addEventListener('click', () => {
                        document.querySelectorAll('.yt-dash-chip').forEach(c => c.classList.remove('active'));
                        chip.classList.add('active');
                        playDashYTPlaylist(pl.id, false, pl.title);
                    });
                    dashYtPlaylistsContainer.appendChild(chip);
                });
            } else {
                dashYtPlaylistsContainer.innerHTML = '<div style="font-size: 0.75rem; color: var(--text-muted); padding: 4px;">Немає плейлистів</div>';
            }
        } catch (e) {
            dashYtPlaylistsContainer.innerHTML = '<div style="font-size: 0.75rem; color: var(--accent-pink); padding: 4px;">Помилка завантаження</div>';
        }
    }

    if (btnDashRefreshPlaylists) {
        btnDashRefreshPlaylists.addEventListener('click', () => {
            hapticFeedback();
            loadDashYTPlaylists(true);
        });
    }

    async function loadMediaChips() {
        try {
            const res = await fetch('/api/media/list');
            const data = await res.json();
            if (data.success && data.media && mediaChipsContainer) {
                mediaChipsContainer.innerHTML = '';
                data.media.slice(0, 8).forEach(item => {
                    const chip = document.createElement('div');
                    chip.className = 'media-chip';
                    chip.innerHTML = `<span>▶</span> <span>${item.title}</span>`;
                    chip.addEventListener('click', () => {
                        hapticFeedback();
                        fetch('/api/media/play', {
                            method: 'POST',
                            headers: { 'Content-Type': 'application/json' },
                            body: JSON.stringify({ filename: item.filename })
                        });
                        if (voiceStatusText) voiceStatusText.textContent = `Відтворення: ${item.title}`;
                    });
                    mediaChipsContainer.appendChild(chip);
                });
            }
        } catch (e) {
            console.error('Media load error:', e);
        }
    }

    // --- REALTIME TELEMETRY & SYSTEM POLLING ---
    async function fetchTelemetry() {
        try {
            // 1. Garage state
            const resState = await fetch('/api/garage/state');
            const dataState = await resState.json();
            if (dataState.success && dataState.state) {
                const st = dataState.state;

                // Server online badge
                if (pillServerDot) pillServerDot.className = 'status-dot online pulse';
                if (pillServerText) pillServerText.textContent = 'Сервер Онлайн';

                // Light & Fan
                if (st.relays_installed === false) {
                    if (statusLight) statusLight.textContent = 'Очікує реле';
                    if (statusFan) statusFan.textContent = 'Очікує реле';
                    if (tileLight) tileLight.classList.remove('active-light');
                    if (tileFan) tileFan.classList.remove('active-fan');
                } else {
                    updateLightState(st.light);
                    updateFanState(st.fan);
                }

                // 3-Floor Climate Telemetry with strict freshness rules
                const floors = st.floors || {};
                const f1 = floors.floor1 || {};
                const f2 = floors.floor2 || {};
                const fb = floors.basement || {};

                // Helper to render climate tile with strict freshness rules
                const renderFloorTile = (floorObj, defaultName, valTempEl, valHumEl, subEl, batEl, cardEl) => {
                    const isInstalled = floorObj && floorObj.installed !== false;
                    const status = floorObj ? (floorObj.status || (floorObj.online ? 'online' : (floorObj.is_stale ? 'stale' : 'offline'))) : 'never_seen';
                    const isOnline = status === 'online' && floorObj && floorObj.current_temperature !== null && floorObj.current_temperature !== undefined;
                    const lastTemp = floorObj ? (floorObj.last_known_temperature ?? floorObj.temperature) : null;
                    const lastHum = floorObj ? (floorObj.last_known_humidity ?? floorObj.humidity) : null;
                    const lastTime = floorObj ? (floorObj.last_updated_time || '--:--') : '--:--';
                    const lastRel = floorObj ? (floorObj.last_updated_relative || '') : '';
                    const srcName = floorObj && floorObj.source_name ? floorObj.source_name : 'BLE';
                    const batVal = (floorObj && floorObj.battery !== null && floorObj.battery !== undefined) ? `🔋 ${floorObj.battery}%` : '--';

                    let tVal = '--';
                    let hVal = '--';
                    let subText = 'Очікує даних';
                    let tooltip = defaultName;

                    if (!isInstalled || status === 'not_installed') {
                        tVal = '--';
                        hVal = '--';
                        subText = 'Датчик не встановлено';
                        tooltip = `${defaultName}: датчик не встановлено`;
                    } else if (isOnline) {
                        tVal = Number(floorObj.current_temperature).toFixed(1);
                        hVal = (floorObj.current_humidity !== null && floorObj.current_humidity !== undefined) ? Number(floorObj.current_humidity).toFixed(0) : '--';
                        subText = `Актуально • ${lastTime}`;
                        tooltip = `${defaultName}: Актуально (${srcName}) • Оновлено о ${lastTime}`;
                    } else if (status === 'stale') {
                        tVal = lastTemp !== null ? Number(lastTemp).toFixed(1) : '--';
                        hVal = lastHum !== null ? Number(lastHum).toFixed(0) : '--';
                        subText = `🕒 Застаріло • ${lastRel || lastTime}`;
                        tooltip = `${defaultName}: Дані застаріли (${srcName}) • Останній вимір: ${lastTemp !== null ? Number(lastTemp).toFixed(1) + ' °C о ' : ''}${lastTime}`;
                    } else if (status === 'offline') {
                        tVal = lastTemp !== null ? Number(lastTemp).toFixed(1) : '--';
                        hVal = lastHum !== null ? Number(lastHum).toFixed(0) : '--';
                        subText = `🔴 Офлайн • ${lastRel || lastTime}`;
                        tooltip = `${defaultName}: Офлайн (${srcName}) • Останній вимір: ${lastTime}`;
                    } else {
                        // never_seen
                        tVal = '--';
                        hVal = '--';
                        subText = 'Дані ще не надходили';
                        tooltip = `${defaultName}: очікування першого виміру`;
                    }

                    if (valTempEl) {
                        valTempEl.textContent = tVal;
                        valTempEl.title = tooltip;
                        valTempEl.setAttribute('data-tooltip', tooltip);
                        valTempEl.style.cursor = 'help';
                    }
                    if (valHumEl) {
                        valHumEl.textContent = hVal;
                        valHumEl.title = tooltip;
                    }
                    if (subEl) subEl.textContent = subText;
                    if (batEl) batEl.textContent = (!isInstalled || status === 'not_installed') ? '--' : batVal;
                    if (cardEl) {
                        cardEl.classList.toggle('is-stale', status === 'stale');
                    }
                };

                renderFloorTile(f1, '1-й поверх (Гараж)', valTempFloor1, valHumFloor1, subFloor1, batFloor1, floorCard1);
                renderFloorTile(f2, '2-й поверх', valTempFloor2, valHumFloor2, subFloor2, batFloor2, floorCard2);
                renderFloorTile(fb, 'Підвал', valTempBasement, valHumBasement, subBasement, batBasement, floorCardBasement);

                // BLE sensors summary (Count configured BLE climate sensors)
                const totalBleSensors = 2; // Basement + Floor 2
                let activeBleCount = 0;
                if (f2.online) activeBleCount++;
                if (fb.online) activeBleCount++;
                if (valBleSensorsCount) valBleSensorsCount.textContent = `${activeBleCount} / ${totalBleSensors} онлайн`;
                if (subBleSensors) {
                    if (activeBleCount === 2) {
                        subBleSensors.textContent = "Підвал та 2-й поверх на зв'язку";
                    } else if (activeBleCount === 1) {
                        subBleSensors.textContent = f2.online ? "2-й поверх на зв'язку" : "Підвал на зв'язку";
                    } else {
                        subBleSensors.textContent = (fb.is_stale || f2.is_stale) ? "Дані застаріли" : "Очікування сигналів";
                    }
                }

                // CC1101 Radio Transceiver status card on Dashboard
                const dashRfBadge = document.getElementById('dashRfBadge');
                const dashRfStateVal = document.getElementById('dashRfStateVal');
                const dashRfEdgeCount = document.getElementById('dashRfEdgeCount');

                const rfData = st.rf || (st.esp32 && st.esp32.rf_diagnostics) || {};
                if (dashRfStateVal) {
                    const marcName = rfData.marc_state_name || 'RX';
                    const isRx = marcName === 'RX';
                    dashRfStateVal.innerHTML = isRx ? `🟢 Прийом (${marcName})` : (marcName === 'TX' ? `🔵 Передача (${marcName})` : `🟡 ${marcName}`);
                    dashRfStateVal.style.color = isRx ? '#00f0ff' : '#eab308';
                }
                if (dashRfBadge) {
                    const freq = rfData.frequency_mhz ? Number(rfData.frequency_mhz).toFixed(2) : '433.92';
                    dashRfBadge.textContent = `${freq} МГц • OOK`;
                }
                if (dashRfEdgeCount) {
                    const edges = rfData.edge_count !== undefined ? rfData.edge_count : '--';
                    dashRfEdgeCount.textContent = `Імпульсів: ${Number(edges).toLocaleString('uk-UA')}`;
                }

                // ESP32 Status Pill & Gateway Strip
                const esp = st.esp32 || {};
                const espOnline = !!(esp.online !== undefined ? esp.online : (st.online && st.transport !== 'none'));
                const espHost = esp.host || st.wifi_ip || '192.168.100.114';
                const espSeenTime = esp.last_seen_time || '--:--';
                const espSeenRel = esp.last_seen_relative || 'ніколи';

                if (pillEspDot) {
                    pillEspDot.className = espOnline ? 'status-dot online pulse' : 'status-dot offline';
                }
                if (pillEspStatus) {
                    pillEspStatus.textContent = espOnline ? `ESP32: В мережі (${espHost})` : `ESP32: Офлайн (${espSeenTime})`;
                }
                if (esp32StripBadge) {
                    esp32StripBadge.className = 'esp32-strip-badge ' + (espOnline ? 'online' : 'offline');
                    esp32StripBadge.textContent = espOnline ? '🟢 ESP32 В мережі' : '🔴 ESP32 Офлайн';
                }
                if (esp32StripIp) {
                    esp32StripIp.textContent = espHost + (esp.ping_ms !== undefined && esp.ping_ms !== null ? ` • ${esp.ping_ms} мс` : '');
                }
                if (esp32StripLastSeen) {
                    esp32StripLastSeen.textContent = `Останній зв'язок: ${espSeenTime} (${espSeenRel})`;
                }

                // 4. Bluetooth Speakers Switcher & State
                const spk = st.speaker || {};
                const spkConnected = !!spk.connected;
                const activeMac = (spk.mac || '').toUpperCase();

                // Update segmented switcher buttons
                if (btnSpeakerJxbt && btnSpeakerJbl) {
                    const isJxbtActive = spk.floor === 'floor1' || (spk.name && spk.name.includes('JX-BT'));
                    const isJblActive = spk.floor === 'garage' || (spk.name && spk.name.includes('JBL'));

                    btnSpeakerJxbt.classList.toggle('active', isJxbtActive);
                    btnSpeakerJbl.classList.toggle('active', isJblActive);

                    let jxbtOnline = isJxbtActive && spkConnected;
                    let jblOnline = isJblActive && spkConnected;

                    if (Array.isArray(spk.speakers)) {
                        const sJxbt = spk.speakers.find(s => s.floor === 'floor1' || (s.name && s.name.includes('JX-BT')));
                        const sJbl = spk.speakers.find(s => s.floor === 'garage' || (s.name && s.name.includes('JBL')));
                        if (sJxbt && sJxbt.connected !== undefined) jxbtOnline = sJxbt.connected;
                        if (sJbl && sJbl.connected !== undefined) jblOnline = sJbl.connected;
                    }

                    if (dotJxbt) dotJxbt.className = `speaker-btn-dot ${jxbtOnline ? 'online' : 'offline'}`;
                    if (dotJbl) dotJbl.className = `speaker-btn-dot ${jblOnline ? 'online' : 'offline'}`;

                    if (subJxbt) {
                        subJxbt.textContent = isJxbtActive
                            ? (spk.playing ? '▶ Грає зараз' : (jxbtOnline ? 'Підключено' : '1-й поверх (Музика)'))
                            : (jxbtOnline ? 'Підключено' : '1-й поверх');
                    }
                    if (subJbl) {
                        subJbl.textContent = isJblActive
                            ? (spk.playing ? '▶ Грає зараз' : (jblOnline ? 'Підключено' : 'Гараж (Юрій)'))
                            : (jblOnline ? 'Підключено' : 'Гараж (Юрій)');
                    }
                }

                if (jblOnlineDot) {
                    jblOnlineDot.className = `status-dot ${spkConnected ? 'online pulse' : 'offline'}`;
                }
                if (jblStatusBadge) {
                    jblStatusBadge.textContent = spkConnected ? 'Підключено' : 'Відключено';
                    jblStatusBadge.style.color = spkConnected ? 'var(--accent-cyan)' : 'var(--text-muted)';
                }
                if (speakerSelect && spk.mac && document.activeElement !== speakerSelect) {
                    speakerSelect.value = spk.mac;
                }
                if (jblCardTitle && spk.name) {
                    jblCardTitle.textContent = `Аудіо: ${spk.name}`;
                }
                if (jblDeviceName && spk.name) {
                    jblDeviceName.textContent = spk.name;
                }
                if (jblMac && spk.mac) {
                    jblMac.textContent = `MAC: ${spk.mac}`;
                }
                if (btnJblConnect && btnJblDisconnect) {
                    btnJblConnect.style.display = spkConnected ? 'none' : 'inline-block';
                    btnJblDisconnect.style.display = spkConnected ? 'inline-block' : 'none';
                }
                if (jblNowPlaying) {
                    if (spk.playing && spk.current_track) {
                        const elapsed = spk.elapsed_seconds ? ` (${formatDashTime(spk.elapsed_seconds)})` : '';
                        jblNowPlaying.textContent = `▶ ${spk.current_track}${elapsed}`;
                        jblNowPlaying.style.color = 'var(--accent-cyan)';
                    } else {
                        jblNowPlaying.textContent = 'Немає активного відтворення';
                        jblNowPlaying.style.color = '#fff';
                    }
                }

                // Upcoming track preview on tablet dashboard
                if (dashJblUpcomingContainer && dashJblUpcomingTrack) {
                    const upcoming = spk.upcoming_track;
                    if (upcoming && upcoming.title && spk.playing) {
                        dashJblUpcomingContainer.style.display = 'inline-flex';
                        const uploaderStr = upcoming.uploader ? ` • ${upcoming.uploader}` : '';
                        dashJblUpcomingTrack.textContent = `${upcoming.title}${uploaderStr}`;
                        dashJblUpcomingTrack.title = `Наступна: ${upcoming.title}${uploaderStr}`;
                    } else {
                        dashJblUpcomingContainer.style.display = 'none';
                    }
                }

                // Scrubber & timeline update on tablet dashboard
                const dur = spk.duration_seconds || 0;
                const elap = spk.elapsed_seconds || 0;
                if (dashMediaTimeDuration) {
                    dashMediaTimeDuration.textContent = dur > 0 ? formatDashTime(dur) : '--:--';
                }
                if (dashTimelineSlider && !isDashScrubbing) {
                    if (spk.playing && dur > 0) {
                        dashTimelineSlider.max = dur;
                        dashTimelineSlider.value = elap;
                        dashTimelineSlider.disabled = false;
                        if (dashMediaTimeElapsed) dashMediaTimeElapsed.textContent = formatDashTime(elap);
                    } else if (spk.playing) {
                        dashTimelineSlider.value = 0;
                        dashTimelineSlider.disabled = true;
                        if (dashMediaTimeElapsed) dashMediaTimeElapsed.textContent = formatDashTime(elap);
                    } else {
                        dashTimelineSlider.value = 0;
                        dashTimelineSlider.disabled = true;
                        if (dashMediaTimeElapsed) dashMediaTimeElapsed.textContent = '00:00';
                    }
                }

                // Highlight active quick radio station button if current_track contains station name
                if (radioQuickPicks) {
                    const trackLower = (spk.playing && spk.current_track) ? spk.current_track.toLowerCase() : '';
                    radioQuickPicks.querySelectorAll('.radio-quick-btn').forEach(btn => {
                        const btnName = (btn.getAttribute('data-name') || '').toLowerCase();
                        const isThisActive = !!(btnName && trackLower && trackLower.includes(btnName));
                        btn.classList.toggle('active', isThisActive);
                    });
                }
                if (jblVolumeSlider && !isVolumeDragging && spk.volume !== undefined && spk.volume !== null) {
                    jblVolumeSlider.value = spk.volume;
                    if (jblVolumeVal) jblVolumeVal.textContent = `${spk.volume}%`;
                }
            }
        } catch (err) {
            if (pillServerDot) pillServerDot.className = 'status-dot offline';
            if (pillServerText) pillServerText.textContent = 'Немає зв\'язку';
        }

        // 2. System Stats
        try {
            const resSys = await fetch('/api/system/stats');
            const dataSys = await resSys.json();
            if (dataSys.success && dataSys.stats) {
                const s = dataSys.stats;
                if (pillCpuTemp) pillCpuTemp.textContent = `${s.cpu_temp || '--'} °C`;
                if (pillRam) pillRam.textContent = `${s.ram_percent || '--'}%`;

                if (pillServerBat) {
                    if (s.battery_percent !== null && s.battery_percent !== undefined) {
                        const icon = s.battery_plugged ? '⚡' : '🔋';
                        pillServerBat.textContent = `${icon} ${s.battery_percent}%`;
                    } else {
                        pillServerBat.textContent = 'Мережа';
                    }
                }

                if (statCpuLoad) statCpuLoad.textContent = `${s.cpu_percent}%`;
                if (statCpuTemp) statCpuTemp.textContent = `${s.cpu_temp} °C`;
                if (statRam) statRam.textContent = `${s.ram_percent}% (${s.ram_used_mb} MB)`;
                if (statServerBat) {
                    if (s.battery_percent !== null && s.battery_percent !== undefined) {
                        const plugStr = s.battery_plugged ? '(Зарядка)' : '(Батарея)';
                        statServerBat.textContent = `${s.battery_percent}% ${plugStr}`;
                    } else {
                        statServerBat.textContent = 'Від мережі';
                    }
                }
                if (statUptime) statUptime.textContent = s.uptime_str || '--';
                if (statLocalIp) statLocalIp.textContent = s.local_ip || '--';
                if (statTailscaleIp) statTailscaleIp.textContent = s.tailscale_ip || '--';
            }
        } catch (e) { }

        // 3. Projector status
        try {
            const resProj = await fetch('/api/projector/status');
            const dataProj = await resProj.json();
            if (dataProj.success && dataProj.projector) {
                const p = dataProj.projector;
                const isOnline = p.online !== false;
                if (projOnlineDot) {
                    projOnlineDot.className = `status-dot ${isOnline ? 'online pulse' : 'offline'}`;
                }
                if (projStatusBadge) {
                    projStatusBadge.textContent = isOnline ? `Онлайн (${p.ip})` : 'Вимкнено';
                }
            }
        } catch (e) { }
    }

    if (btnRefresh) {
        btnRefresh.addEventListener('click', () => {
            hapticFeedback();
            fetchTelemetry();
            loadMediaChips();
        });
    }

    // --- PIN AUTHENTICATION (DASHBOARD KIOSK) ---
    function updateAuthUi(isAuthed) {
        if (dashAuthIcon) dashAuthIcon.textContent = isAuthed ? '🔓' : '🔒';
        if (dashAuthLabel) dashAuthLabel.textContent = isAuthed ? 'Вхід: ОК' : 'Вхід';
        if (btnDashAuth) btnDashAuth.title = isAuthed ? 'Авторизовано. Натисніть для виходу' : 'Введіть PIN-код для керування';
    }

    async function checkAuthSession() {
        try {
            const res = await fetch('/api/csrf');
            if (res.ok) {
                const data = await res.json();
                if (data.csrf_token) {
                    sessionStorage.setItem('sg_csrf_token', data.csrf_token);
                }
                updateAuthUi(true);
                return true;
            } else {
                sessionStorage.removeItem('sg_csrf_token');
                updateAuthUi(false);
                return false;
            }
        } catch {
            updateAuthUi(false);
            return false;
        }
    }

    function openDashPinModal() {
        if (dashPinModal) {
            dashPinModal.style.display = 'flex';
            if (dashPinInput) {
                dashPinInput.value = '';
                dashPinInput.focus();
            }
            if (dashPinError) {
                dashPinError.style.display = 'none';
                dashPinError.textContent = '';
            }
        }
    }

    function closeDashPinModal() {
        if (dashPinModal) dashPinModal.style.display = 'none';
    }

    if (btnDashAuth) {
        btnDashAuth.addEventListener('click', async () => {
            hapticFeedback();
            const authed = await checkAuthSession();
            if (authed) {
                if (confirm('Ви увійшли як адміністратор. Бажаєте вийти з облікового запису?')) {
                    try {
                        await fetch('/api/admin/logout', { method: 'POST' });
                    } catch { }
                    sessionStorage.removeItem('sg_csrf_token');
                    updateAuthUi(false);
                }
            } else {
                openDashPinModal();
            }
        });
    }

    if (btnDashPinClose) {
        btnDashPinClose.addEventListener('click', closeDashPinModal);
    }

    if (dashPinModal) {
        dashPinModal.addEventListener('click', (e) => {
            if (e.target === dashPinModal) closeDashPinModal();
        });
    }

    if (dashPinForm) {
        dashPinForm.addEventListener('submit', async (e) => {
            e.preventDefault();
            hapticFeedback();
            const pin = (dashPinInput ? dashPinInput.value : '').trim();
            if (!pin) return;

            try {
                if (dashPinError) dashPinError.style.display = 'none';
                const res = await fetch('/api/admin/verify', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ pin })
                });
                const data = await res.json();
                if (res.ok && data.authenticated) {
                    if (data.csrf_token) {
                        sessionStorage.setItem('sg_csrf_token', data.csrf_token);
                    }
                    updateAuthUi(true);
                    closeDashPinModal();
                } else {
                    if (dashPinError) {
                        dashPinError.style.display = 'block';
                        dashPinError.textContent = data.error || 'Невірний PIN-код!';
                    }
                }
            } catch (err) {
                if (dashPinError) {
                    dashPinError.style.display = 'block';
                    dashPinError.textContent = 'Помилка зв\'язку з сервером: ' + err.message;
                }
            }
        });
    }

    // Check initial auth state on dashboard load
    checkAuthSession();

    // ==========================================
    // CLIMATE DYNAMICS MODAL & CHART LOGIC
    // ==========================================
    const climateModal = document.getElementById('climateModal');
    const modalCloseBtn = document.getElementById('modalCloseBtn');
    const modalRefreshBtn = document.getElementById('modalRefreshBtn');
    const modalFloorIcon = document.getElementById('modalFloorIcon');
    const modalFloorTitle = document.getElementById('modalFloorTitle');
    const modalFloorSubtitle = document.getElementById('modalFloorSubtitle');
    const modalRangeTabs = document.getElementById('modalRangeTabs');
    const modalEmptyState = document.getElementById('modalEmptyState');
    const modalEmptyMsg = document.getElementById('modalEmptyMsg');
    const modalClimateChartCanvas = document.getElementById('modalClimateChart');

    const statMinTemp = document.getElementById('statMinTemp');
    const statMaxTemp = document.getElementById('statMaxTemp');
    const statAvgTemp = document.getElementById('statAvgTemp');
    const statMinHum = document.getElementById('statMinHum');
    const statMaxHum = document.getElementById('statMaxHum');
    const statAvgHum = document.getElementById('statAvgHum');

    const FLOOR_INFO = {
        floor1: {
            title: '1-й поверх (Гараж)',
            subtitle: 'AHT10 (ESP32)',
            icon: '🏠'
        },
        floor2: {
            title: '2-й поверх (Житловий)',
            subtitle: 'Xiaomi LYWSD03MMC (BLE)',
            icon: '🏢'
        },
        basement: {
            title: 'Підвал (Сховище)',
            subtitle: 'Xiaomi LYWSD03MMC (BLE)',
            icon: '⚓'
        }
    };

    let activeModalFloor = 'basement';
    let activeModalHours = 24;
    let climateChart = null;
    let climateModalInterval = null;

    function openClimateModal(floorKey) {
        if (!climateModal) return;
        activeModalFloor = floorKey || 'basement';
        const info = FLOOR_INFO[activeModalFloor] || {
            title: activeModalFloor,
            subtitle: 'Кліматичний датчик',
            icon: '📊'
        };

        if (modalFloorIcon) modalFloorIcon.textContent = info.icon;
        if (modalFloorTitle) modalFloorTitle.textContent = info.title;
        if (modalFloorSubtitle) modalFloorSubtitle.textContent = info.subtitle;

        climateModal.style.display = 'flex';
        climateModal.setAttribute('aria-hidden', 'false');
        requestAnimationFrame(() => {
            climateModal.classList.add('open');
        });

        loadClimateHistory();

        if (climateModalInterval) clearInterval(climateModalInterval);
        climateModalInterval = setInterval(() => {
            if (climateModal && climateModal.classList.contains('open')) {
                loadClimateHistory();
            }
        }, 1800000); // Оновлення графіка кожні 30 хвилин
    }

    function closeClimateModal() {
        if (climateModalInterval) {
            clearInterval(climateModalInterval);
            climateModalInterval = null;
        }
        if (!climateModal) return;
        climateModal.classList.remove('open');
        setTimeout(() => {
            climateModal.style.display = 'none';
            climateModal.setAttribute('aria-hidden', 'true');
        }, 220);
    }

    async function loadClimateHistory() {
        if (!modalClimateChartCanvas) return;

        if (modalEmptyState) {
            modalEmptyState.style.display = 'none';
        }

        try {
            const resp = await fetch(`/api/telemetry/history?floor=${encodeURIComponent(activeModalFloor)}&hours=${activeModalHours}`);
            const data = await resp.json();

            if (!data.success || !data.points || data.points.length === 0) {
                if (modalEmptyState) {
                    modalEmptyState.style.display = 'flex';
                    if (modalEmptyMsg) {
                        modalEmptyMsg.textContent = 'Накопичення історії замірів триває (заміри фіксуються кожні кілька хвилин)...';
                    }
                }
                updateModalStats(null);
                if (climateChart) {
                    climateChart.destroy();
                    climateChart = null;
                }
                return;
            }

            updateModalStats(data.stats);
            renderClimateChart(data.points);

        } catch (err) {
            console.error('Error fetching climate history:', err);
            if (modalEmptyState) {
                modalEmptyState.style.display = 'flex';
                if (modalEmptyMsg) modalEmptyMsg.textContent = 'Не вдалося завантажити дані замірів.';
            }
        }
    }

    function updateModalStats(stats) {
        if (!stats || stats.min_temp === undefined || stats.min_temp === null) {
            if (statMinTemp) statMinTemp.textContent = '--';
            if (statMaxTemp) statMaxTemp.textContent = '--';
            if (statAvgTemp) statAvgTemp.textContent = '--';
            if (statMinHum) statMinHum.textContent = '--';
            if (statMaxHum) statMaxHum.textContent = '--';
            if (statAvgHum) statAvgHum.textContent = '--';
            return;
        }

        if (statMinTemp) statMinTemp.textContent = `${stats.min_temp} °C`;
        if (statMaxTemp) statMaxTemp.textContent = `${stats.max_temp} °C`;
        if (statAvgTemp) statAvgTemp.textContent = `${stats.avg_temp} °C`;
        if (statMinHum) statMinHum.textContent = `${stats.min_hum}%`;
        if (statMaxHum) statMaxHum.textContent = `${stats.max_hum}%`;
        if (statAvgHum) statAvgHum.textContent = `${stats.avg_hum}%`;
    }

    function renderClimateChart(points) {
        if (typeof Chart === 'undefined') {
            console.warn('Chart.js is not loaded');
            return;
        }

        const labels = points.map(p => {
            if (activeModalHours > 24 && p.datetime) {
                return p.datetime.slice(5, 16);
            }
            return p.time || '';
        });
        const temps = points.map(p => p.temperature);
        const hums = points.map(p => p.humidity);

        if (climateChart) {
            climateChart.destroy();
            climateChart = null;
        }

        const ctx = modalClimateChartCanvas.getContext('2d');
        const tempGradient = ctx.createLinearGradient(0, 0, 0, 300);
        tempGradient.addColorStop(0, 'rgba(56, 189, 248, 0.35)');
        tempGradient.addColorStop(1, 'rgba(56, 189, 248, 0.0)');

        const humGradient = ctx.createLinearGradient(0, 0, 0, 300);
        humGradient.addColorStop(0, 'rgba(34, 197, 94, 0.25)');
        humGradient.addColorStop(1, 'rgba(34, 197, 94, 0.0)');

        climateChart = new Chart(ctx, {
            type: 'line',
            data: {
                labels: labels,
                datasets: [
                    {
                        label: 'Температура (°C)',
                        data: temps,
                        borderColor: '#38bdf8',
                        backgroundColor: tempGradient,
                        borderWidth: 2.2,
                        tension: 0.35,
                        fill: true,
                        yAxisID: 'yTemp',
                        pointRadius: points.length > 50 ? 0 : 3,
                        pointHoverRadius: 6,
                        pointBackgroundColor: '#38bdf8'
                    },
                    {
                        label: 'Вологість (%)',
                        data: hums,
                        borderColor: '#22c55e',
                        backgroundColor: humGradient,
                        borderWidth: 2,
                        borderDash: [4, 4],
                        tension: 0.35,
                        fill: false,
                        yAxisID: 'yHum',
                        pointRadius: points.length > 50 ? 0 : 3,
                        pointHoverRadius: 6,
                        pointBackgroundColor: '#22c55e'
                    }
                ]
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                interaction: {
                    mode: 'index',
                    intersect: false,
                },
                plugins: {
                    legend: {
                        display: true,
                        position: 'top',
                        labels: {
                            color: '#94a3b8',
                            font: { family: "'Inter', sans-serif", size: 12 },
                            usePointStyle: true,
                            boxWidth: 8
                        }
                    },
                    tooltip: {
                        backgroundColor: 'rgba(15, 23, 42, 0.92)',
                        titleColor: '#f1f5f9',
                        bodyColor: '#cbd5e1',
                        borderColor: 'rgba(56, 189, 248, 0.4)',
                        borderWidth: 1,
                        padding: 10,
                        boxPadding: 4,
                        usePointStyle: true,
                        callbacks: {
                            label: function (context) {
                                let label = context.dataset.label || '';
                                if (label) label += ': ';
                                if (context.parsed.y !== null) {
                                    label += context.dataset.yAxisID === 'yTemp'
                                        ? context.parsed.y + ' °C'
                                        : context.parsed.y + ' %';
                                }
                                return label;
                            }
                        }
                    }
                },
                scales: {
                    x: {
                        grid: {
                            color: 'rgba(255, 255, 255, 0.05)',
                            drawBorder: false
                        },
                        ticks: {
                            color: '#64748b',
                            maxRotation: 0,
                            autoSkip: true,
                            maxTicksLimit: 8,
                            font: { size: 11 }
                        }
                    },
                    yTemp: {
                        type: 'linear',
                        display: true,
                        position: 'left',
                        grid: {
                            color: 'rgba(255, 255, 255, 0.06)',
                            drawBorder: false
                        },
                        ticks: {
                            color: '#38bdf8',
                            callback: v => `${v}°C`,
                            font: { size: 11 }
                        }
                    },
                    yHum: {
                        type: 'linear',
                        display: true,
                        position: 'right',
                        grid: {
                            drawOnChartArea: false,
                            drawBorder: false
                        },
                        ticks: {
                            color: '#22c55e',
                            callback: v => `${v}%`,
                            font: { size: 11 }
                        },
                        min: 0,
                        max: 100
                    }
                }
            }
        });
    }

    // Modal Events Binding
    if (modalCloseBtn) {
        modalCloseBtn.addEventListener('click', closeClimateModal);
    }
    if (climateModal) {
        climateModal.addEventListener('click', (e) => {
            if (e.target === climateModal) {
                closeClimateModal();
            }
        });
    }
    document.addEventListener('keydown', (e) => {
        if (e.key === 'Escape' && climateModal && climateModal.classList.contains('open')) {
            closeClimateModal();
        }
    });

    if (modalRefreshBtn) {
        modalRefreshBtn.addEventListener('click', () => {
            hapticFeedback();
            modalRefreshBtn.textContent = '⏳ Оновлення...';
            loadClimateHistory().finally(() => {
                setTimeout(() => {
                    modalRefreshBtn.textContent = '🔄 Оновити';
                }, 500);
            });
        });
    }

    if (modalRangeTabs) {
        modalRangeTabs.addEventListener('click', (e) => {
            const btn = e.target.closest('.range-btn');
            if (!btn) return;
            modalRangeTabs.querySelectorAll('.range-btn').forEach(b => b.classList.remove('active'));
            btn.classList.add('active');
            activeModalHours = parseFloat(btn.dataset.hours) || 24;
            loadClimateHistory();
        });
    }

    // Attach click listeners to floor cards
    document.querySelectorAll('.floor-card[data-floor]').forEach(card => {
        card.addEventListener('click', () => {
            hapticFeedback();
            const floorKey = card.getAttribute('data-floor');
            openClimateModal(floorKey);
        });
    });

    // ==========================================
    // ESP32 DIAGNOSTICS & LOGS MODAL CONTROLLER
    // ==========================================
    let esp32ModalInterval = null;
    let esp32ActiveFilter = 'all';
    let cachedEsp32Logs = [];

    const modalEsp32Online = document.getElementById('modalEsp32Online');
    const modalEsp32Transport = document.getElementById('modalEsp32Transport');
    const modalEsp32Ip = document.getElementById('modalEsp32Ip');
    const modalEsp32Ping = document.getElementById('modalEsp32Ping');
    const modalEsp32LastSeenTime = document.getElementById('modalEsp32LastSeenTime');
    const modalEsp32LastSeenRel = document.getElementById('modalEsp32LastSeenRel');
    const modalEsp32PollStats = document.getElementById('modalEsp32PollStats');
    const modalEsp32LastPoll = document.getElementById('modalEsp32LastPoll');

    const badgeSensorBasement = document.getElementById('badgeSensorBasement');
    const tempSensorBasement = document.getElementById('tempSensorBasement');
    const humSensorBasement = document.getElementById('humSensorBasement');
    const batSensorBasement = document.getElementById('batSensorBasement');
    const readTimeSensorBasement = document.getElementById('readTimeSensorBasement');

    const badgeSensorFloor2 = document.getElementById('badgeSensorFloor2');
    const tempSensorFloor2 = document.getElementById('tempSensorFloor2');
    const humSensorFloor2 = document.getElementById('humSensorFloor2');
    const batSensorFloor2 = document.getElementById('batSensorFloor2');
    const readTimeSensorFloor2 = document.getElementById('readTimeSensorFloor2');

    const esp32LogsContainer = document.getElementById('esp32LogsContainer');
    const btnCloseEsp32Modal = document.getElementById('btnCloseEsp32Modal');
    const btnModalCloseFooter = document.getElementById('btnModalCloseFooter');
    const btnModalPing = document.getElementById('btnModalPing');
    const btnModalPoll = document.getElementById('btnModalPoll');
    const btnModalClearLogs = document.getElementById('btnModalClearLogs');

    function renderEsp32Logs() {
        if (!esp32LogsContainer) return;
        const filtered = cachedEsp32Logs.filter(item => {
            if (esp32ActiveFilter === 'all') return true;
            if (esp32ActiveFilter === 'sensor_read') return item.type === 'sensor_read';
            if (esp32ActiveFilter === 'connection') return item.type === 'connection';
            if (esp32ActiveFilter === 'error') return item.status === 'error' || item.status === 'warning';
            return true;
        });

        if (filtered.length === 0) {
            esp32LogsContainer.innerHTML = '<div class="esp32-empty-logs">📭 Немає записів у цій категорії журналу</div>';
            return;
        }

        esp32LogsContainer.innerHTML = filtered.map(item => {
            let badgeClass = 'badge-status-info';
            let badgeText = 'ІНФО';
            if (item.status === 'success') {
                badgeClass = 'badge-status-success';
                badgeText = 'УСПІШНО';
            } else if (item.status === 'warning') {
                badgeClass = 'badge-status-warning';
                badgeText = 'УВАГА';
            } else if (item.status === 'error') {
                badgeClass = 'badge-status-error';
                badgeText = 'ПОМИЛКА';
            }

            return `
                <div class="esp32-log-item">
                    <span class="esp32-log-time">${item.time || '--:--:--'}</span>
                    <span class="esp32-log-badge ${badgeClass}">${badgeText}</span>
                    <div class="esp32-log-content">
                        <span class="esp32-log-title">${escapeHtml(item.title || '')}</span>
                        <span class="esp32-log-msg">${escapeHtml(item.message || '')}</span>
                    </div>
                </div>
            `;
        }).join('');
    }

    async function loadEsp32Diagnostics() {
        try {
            const res = await fetch('/api/esp32/status');
            const data = await res.json();
            if (!data.success || !data.status) return;
            const st = data.status;

            // Stats grid
            const isOnline = !!st.online;
            if (modalEsp32Online) {
                modalEsp32Online.className = `esp32-tile-val ${isOnline ? 'text-status-online' : 'text-status-offline'}`;
                modalEsp32Online.textContent = isOnline ? '🟢 В мережі' : '🔴 Офлайн';
            }
            if (modalEsp32Transport) {
                modalEsp32Transport.textContent = `Канал: ${st.transport || 'Немає'}`;
            }
            if (modalEsp32Ip) {
                modalEsp32Ip.textContent = `${st.host || '192.168.100.114'}:${st.port || 80}`;
            }
            if (modalEsp32Ping) {
                modalEsp32Ping.textContent = st.ping_ms !== null && st.ping_ms !== undefined ? `Затримка: ${st.ping_ms} мс` : 'Затримка: немає відповіді';
            }
            if (modalEsp32LastSeenTime) {
                modalEsp32LastSeenTime.textContent = st.last_seen_time || '--:--';
            }
            if (modalEsp32LastSeenRel) {
                modalEsp32LastSeenRel.textContent = st.last_seen_relative || 'Ніколи';
            }
            if (modalEsp32PollStats) {
                const p = st.stats || {};
                modalEsp32PollStats.textContent = `${p.polls_success || 0} успішних / ${p.polls_total || 0} всього`;
            }
            if (modalEsp32LastPoll) {
                const p = st.stats || {};
                modalEsp32LastPoll.textContent = p.last_poll_time ? `Останнє: ${new Date(p.last_poll_time * 1000).toLocaleTimeString()}` : 'Останнє: --:--';
            }

            // Sensors details
            const sensors = st.sensors || {};
            const sb = sensors.basement || {};
            const s2 = sensors.floor2 || {};

            // Basement
            const isOnlineSb = sb.status === 'online' || (sb.online && sb.current_temperature !== null);
            if (tempSensorBasement) {
                if (isOnlineSb && sb.current_temperature !== null && sb.current_temperature !== undefined) {
                    tempSensorBasement.textContent = `${Number(sb.current_temperature).toFixed(1)} °C`;
                } else if (sb.last_known_temperature !== null && sb.last_known_temperature !== undefined) {
                    tempSensorBasement.textContent = `-- °C (ост: ${Number(sb.last_known_temperature).toFixed(1)} °C)`;
                } else {
                    tempSensorBasement.textContent = '-- °C';
                }
            }
            if (humSensorBasement) {
                if (isOnlineSb && sb.current_humidity !== null && sb.current_humidity !== undefined) {
                    humSensorBasement.textContent = `${Number(sb.current_humidity).toFixed(0)} %`;
                } else if (sb.last_known_humidity !== null && sb.last_known_humidity !== undefined) {
                    humSensorBasement.textContent = `-- % (ост: ${Number(sb.last_known_humidity).toFixed(0)} %)`;
                } else {
                    humSensorBasement.textContent = '-- %';
                }
            }
            if (batSensorBasement) batSensorBasement.textContent = sb.battery !== null && sb.battery !== undefined ? `🔋 ${sb.battery}%` : '🔋 --';
            if (readTimeSensorBasement) readTimeSensorBasement.textContent = `Останнє зчитування: ${sb.last_read_time || sb.last_updated_time || '--:--'} (${sb.last_read_relative || sb.last_updated_relative || 'немає'})`;
            if (badgeSensorBasement) {
                if (sb.status === 'online' || sb.online) {
                    badgeSensorBasement.className = 'sensor-badge badge-online';
                    badgeSensorBasement.textContent = '🟢 Актуально';
                } else if (sb.status === 'stale' || sb.is_stale) {
                    badgeSensorBasement.className = 'sensor-badge badge-stale';
                    badgeSensorBasement.textContent = '⚠️ Дані застаріли';
                } else if (sb.status === 'not_installed' || sb.installed === false) {
                    badgeSensorBasement.className = 'sensor-badge badge-offline';
                    badgeSensorBasement.textContent = '⚪ Не встановлено';
                } else {
                    badgeSensorBasement.className = 'sensor-badge badge-offline';
                    badgeSensorBasement.textContent = '🔴 Офлайн';
                }
            }

            // Floor 2
            const isOnlineS2 = s2.status === 'online' || (s2.online && s2.current_temperature !== null);
            if (tempSensorFloor2) {
                if (isOnlineS2 && s2.current_temperature !== null && s2.current_temperature !== undefined) {
                    tempSensorFloor2.textContent = `${Number(s2.current_temperature).toFixed(1)} °C`;
                } else if (s2.last_known_temperature !== null && s2.last_known_temperature !== undefined) {
                    tempSensorFloor2.textContent = `-- °C (ост: ${Number(s2.last_known_temperature).toFixed(1)} °C)`;
                } else {
                    tempSensorFloor2.textContent = '-- °C';
                }
            }
            if (humSensorFloor2) {
                if (isOnlineS2 && s2.current_humidity !== null && s2.current_humidity !== undefined) {
                    humSensorFloor2.textContent = `${Number(s2.current_humidity).toFixed(0)} %`;
                } else if (s2.last_known_humidity !== null && s2.last_known_humidity !== undefined) {
                    humSensorFloor2.textContent = `-- % (ост: ${Number(s2.last_known_humidity).toFixed(0)} %)`;
                } else {
                    humSensorFloor2.textContent = '-- %';
                }
            }
            if (batSensorFloor2) batSensorFloor2.textContent = s2.battery !== null && s2.battery !== undefined ? `🔋 ${s2.battery}%` : '🔋 --';
            if (readTimeSensorFloor2) readTimeSensorFloor2.textContent = `Останнє зчитування: ${s2.last_read_time || s2.last_updated_time || '--:--'} (${s2.last_read_relative || s2.last_updated_relative || 'немає'})`;
            if (badgeSensorFloor2) {
                if (s2.status === 'online' || s2.online) {
                    badgeSensorFloor2.className = 'sensor-badge badge-online';
                    badgeSensorFloor2.textContent = '🟢 Актуально';
                } else if (s2.status === 'stale' || s2.is_stale) {
                    badgeSensorFloor2.className = 'sensor-badge badge-stale';
                    badgeSensorFloor2.textContent = '⚠️ Дані застаріли';
                } else if (s2.status === 'not_installed' || s2.installed === false) {
                    badgeSensorFloor2.className = 'sensor-badge badge-offline';
                    badgeSensorFloor2.textContent = '⚪ Не встановлено';
                } else {
                    badgeSensorFloor2.className = 'sensor-badge badge-offline';
                    badgeSensorFloor2.textContent = '🔴 Офлайн';
                }
            }

            // Logs
            cachedEsp32Logs = st.logs || [];
            renderEsp32Logs();
        } catch (e) {
            console.error('Error loading ESP32 diagnostics:', e);
        }
    }

    function openEsp32Modal() {
        if (!modalEsp32) return;
        hapticFeedback();
        modalEsp32.classList.add('open');
        document.body.style.overflow = 'hidden';
        loadEsp32Diagnostics();
        if (esp32ModalInterval) clearInterval(esp32ModalInterval);
        esp32ModalInterval = setInterval(loadEsp32Diagnostics, 3500);
    }

    function closeEsp32Modal() {
        if (!modalEsp32) return;
        hapticFeedback();
        modalEsp32.classList.remove('open');
        document.body.style.overflow = '';
        if (esp32ModalInterval) {
            clearInterval(esp32ModalInterval);
            esp32ModalInterval = null;
        }
    }

    // Modal Triggers
    if (pillEspContainer) pillEspContainer.addEventListener('click', openEsp32Modal);
    if (btnEsp32Logs) btnEsp32Logs.addEventListener('click', openEsp32Modal);
    if (btnCloseEsp32Modal) btnCloseEsp32Modal.addEventListener('click', closeEsp32Modal);
    if (btnModalCloseFooter) btnModalCloseFooter.addEventListener('click', closeEsp32Modal);

    if (modalEsp32) {
        modalEsp32.addEventListener('click', (e) => {
            if (e.target === modalEsp32) closeEsp32Modal();
        });
    }

    // Filter tabs inside modal
    document.querySelectorAll('.esp32-filter-tabs .filter-tab').forEach(tab => {
        tab.addEventListener('click', () => {
            hapticFeedback();
            document.querySelectorAll('.esp32-filter-tabs .filter-tab').forEach(t => t.classList.remove('active'));
            tab.classList.add('active');
            esp32ActiveFilter = tab.getAttribute('data-filter') || 'all';
            renderEsp32Logs();
        });
    });

    // Ping Action (Both strip and modal)
    const handlePing = async (btn) => {
        hapticFeedback();
        const origText = btn ? btn.textContent : '';
        if (btn) btn.textContent = '⏳ Перевірка...';
        try {
            const res = await fetch('/api/esp32/ping', { method: 'POST' });
            const data = await res.json();
            if (data.result && data.result.online) {
                alert(`✅ ESP32 на зв'язку!\nЧас відгуку (ping): ${data.result.latency_ms} мс\nХост: ${data.result.host}:${data.result.port}`);
            } else {
                alert(`❌ ESP32 не відповідає у мережі!\nХост: ${data.result ? data.result.host : '192.168.100.114'}\nПомилка: ${data.result?.error || 'Таймаут підключення'}`);
            }
            loadEsp32Diagnostics();
            fetchTelemetry();
        } catch (e) {
            alert(`Помилка запиту: ${e.message}`);
        } finally {
            if (btn) btn.textContent = origText;
        }
    };

    if (btnEsp32Ping) btnEsp32Ping.addEventListener('click', () => handlePing(btnEsp32Ping));
    if (btnModalPing) btnModalPing.addEventListener('click', () => handlePing(btnModalPing));

    // Poll Action (Both strip and modal)
    const handlePoll = async (btn) => {
        hapticFeedback();
        const origText = btn ? btn.textContent : '';
        if (btn) btn.textContent = '⏳ Опитування...';
        try {
            const res = await fetch('/api/esp32/poll', { method: 'POST' });
            const data = await res.json();
            if (data.result && data.result.success) {
                alert(`📡 Команду опитування датчиків успішно передано на ESP32 (${data.result.transport})!\nОчікуйте оновлення показників.`);
            } else {
                alert(`⚠️ Не вдалося опитати датчики через ESP32:\n${data.result?.error || 'Контролер не в мережі'}`);
            }
            loadEsp32Diagnostics();
            fetchTelemetry();
        } catch (e) {
            alert(`Помилка запиту: ${e.message}`);
        } finally {
            if (btn) btn.textContent = origText;
        }
    };

    if (btnEsp32Poll) btnEsp32Poll.addEventListener('click', () => handlePoll(btnEsp32Poll));
    if (btnModalPoll) btnModalPoll.addEventListener('click', () => handlePoll(btnModalPoll));

    // Clear Logs Action
    if (btnModalClearLogs) {
        btnModalClearLogs.addEventListener('click', async () => {
            if (!confirm('Ви впевнені, що бажаєте очистити журнал подій ESP32?')) return;
            hapticFeedback();
            try {
                await fetch('/api/esp32/clear_logs', { method: 'POST' });
                cachedEsp32Logs = [];
                renderEsp32Logs();
            } catch (e) {
                console.error(e);
            }
        });
    }

    // Escape key listener for ESP32 modal
    document.addEventListener('keydown', (e) => {
        if (e.key === 'Escape' && modalEsp32 && modalEsp32.classList.contains('open')) {
            closeEsp32Modal();
        }
    });

    // Initial Load & Regular Polling
    fetchTelemetry();
    loadMediaChips();
    loadRadioStations();
    loadDashYTPlaylists();
    setInterval(fetchTelemetry, 2500);
});
