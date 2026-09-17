/**
 * Smart Garage - 1st Floor Dashboard (Tablet & Mobile Kiosk Controller)
 */

document.addEventListener('DOMContentLoaded', () => {
    // --- STATE VARIABLES ---
    let wakeLock = null;
    let isListening = false;
    let ttsEnabled = true;
    let recognition = null;
    let isLightOn = false;
    let isFanOn = false;
    let isDoorOpen = false;

    // --- DOM REFERENCES ---
    // Clock
    const clockTime = document.getElementById('clockTime');
    const clockDate = document.getElementById('clockDate');

    // Header buttons
    const btnWakeLock = document.getElementById('btnWakeLock');
    const btnFullscreen = document.getElementById('btnFullscreen');
    const btnTts = document.getElementById('btnTts');
    const btnRefresh = document.getElementById('btnRefresh');

    // Status pills
    const pillServerDot = document.getElementById('pillServerDot');
    const pillServerText = document.getElementById('pillServerText');
    const pillCpuTemp = document.getElementById('pillCpuTemp');
    const pillRam = document.getElementById('pillRam');
    const pillServerBat = document.getElementById('pillServerBat');
    const pillEspStatus = document.getElementById('pillEspStatus');

    // Touch Tiles
    const tileLight = document.getElementById('tileLight');
    const statusLight = document.getElementById('statusLight');
    const tileFan = document.getElementById('tileFan');
    const statusFan = document.getElementById('statusFan');
    const tileDoor = document.getElementById('tileDoor');
    const statusDoor = document.getElementById('statusDoor');

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

    const valAir = document.getElementById('valAir');
    const subAir = document.getElementById('subAir');
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

    // JBL Speaker Elements
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
    const btnJblPause = document.getElementById('btnJblPause');
    const btnJblResume = document.getElementById('btnJblResume');
    const btnJblStop = document.getElementById('btnJblStop');
    const jblPlayForm = document.getElementById('jblPlayForm');
    const jblPlayInput = document.getElementById('jblPlayInput');

    // Internet Radio Elements
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
            try { navigator.vibrate(duration); } catch (e) {}
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
                if ('speechSynthesis' in window) window.speechSynthesis.cancel();
            }
        });
    }

    // --- TTS SPEAK FUNCTION ---
    function speakText(text) {
        if (!ttsEnabled || !('speechSynthesis' in window)) return;
        try {
            window.speechSynthesis.cancel();
            const utterance = new SpeechSynthesisUtterance(text);
            utterance.lang = 'uk-UA';
            utterance.rate = 1.05;
            utterance.pitch = 1.0;

            const voices = window.speechSynthesis.getVoices();
            const ukVoice = voices.find(v => v.lang.includes('uk') || v.lang.includes('UK'));
            if (ukVoice) utterance.voice = ukVoice;

            window.speechSynthesis.speak(utterance);
        } catch (e) {
            console.error('Speech error:', e);
        }
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
                isListening = true;
                if (btnMicHero) btnMicHero.classList.add('listening');
                if (voiceStatusText) {
                    voiceStatusText.textContent = '🎙️ Слухаю... Говоріть команду';
                    voiceStatusText.style.color = '';
                }
            };

            recognition.onresult = (event) => {
                const transcript = event.results[0][0].transcript;
                if (voiceStatusText) voiceStatusText.textContent = `Ви сказали: "${transcript}"`;
                executeUserCommand(transcript);
            };

            recognition.onerror = (event) => {
                console.warn('Speech recognition error:', event.error);
                isListening = false;
                if (btnMicHero) btnMicHero.classList.remove('listening');
                if (event.error === 'not-allowed') {
                    if (voiceStatusText) {
                        voiceStatusText.textContent = '⚠️ Доступ до мікрофона відхилено в браузері';
                        voiceStatusText.style.color = '#ef4444';
                    }
                } else if (event.error === 'no-speech') {
                    if (voiceStatusText) voiceStatusText.textContent = 'Голос не виявлено. Натисніть і спробуйте знову';
                } else {
                    if (voiceStatusText) voiceStatusText.textContent = `Помилка: ${event.error}. Спробуйте ще раз`;
                }
            };

            recognition.onend = () => {
                isListening = false;
                if (btnMicHero) btnMicHero.classList.remove('listening');
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
                recognition.stop();
            } else {
                try {
                    recognition.start();
                } catch (e) {
                    console.warn('Recognition start exception:', e);
                    try { recognition.stop(); } catch (_) {}
                }
            }
        });
    }

    // --- COMMAND EXECUTION VIA HTTP ---
    async function executeUserCommand(commandText) {
        if (!commandText || !commandText.trim()) return;
        const query = commandText.trim();

        if (dialogUserText) dialogUserText.textContent = query;
        if (dialogAiText) dialogAiText.textContent = 'Обробляю запит...';
        if (voiceDialogBox) voiceDialogBox.style.display = 'flex';

        try {
            const res = await fetch('/command', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ command: query })
            });
            const data = await res.json();
            const reply = data.response || 'Команду виконано.';
            if (dialogAiText) dialogAiText.textContent = reply;
            speakText(reply);
            fetchTelemetry();
        } catch (err) {
            const errReply = 'Помилка зв\'язку з сервером.';
            if (dialogAiText) dialogAiText.textContent = errReply;
            speakText(errReply);
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

    if (tileDoor) {
        tileDoor.addEventListener('click', async () => {
            hapticFeedback();
            try {
                const res = await fetch('/api/device/door/toggle', { method: 'POST' });
                const data = await res.json();
                updateDoorState(data.door === 'open');
            } catch (err) {
                console.error(err);
            }
        });
    }

    // Keyboard activation (Enter/Space) for interactive tiles and floor cards
    const floorCard1 = document.getElementById('floorCard1');
    const floorCard2 = document.getElementById('floorCard2');
    const floorCardBasement = document.getElementById('floorCardBasement');
    [tileLight, tileFan, tileDoor, floorCard1, floorCard2, floorCardBasement].forEach(el => {
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

    function updateDoorState(open) {
        isDoorOpen = !!open;
        if (tileDoor) {
            if (isDoorOpen) {
                tileDoor.classList.add('active-light');
                if (statusDoor) statusDoor.textContent = 'Відкрито';
            } else {
                tileDoor.classList.remove('active-light');
                if (statusDoor) statusDoor.textContent = 'Закрито';
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

    if (btnJblConnect) {
        btnJblConnect.addEventListener('click', async () => {
            hapticFeedback();
            btnJblConnect.textContent = 'З\'єднання...';
            try {
                const res = await fetch('/api/speaker/connect', { method: 'POST' });
                const data = await res.json();
                if (voiceStatusText) voiceStatusText.textContent = data.response;
                if (ttsEnabled) speakText(data.response);
                fetchTelemetry();
            } catch (e) {
                if (voiceStatusText) voiceStatusText.textContent = 'Помилка підключення до JBL';
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
            } catch (e) {}
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
                if (voiceStatusText) voiceStatusText.textContent = data.response || 'Відтворення запущено';
                if (ttsEnabled) speakText(data.response);
                jblPlayInput.value = '';
                fetchTelemetry();
            } catch (err) {
                if (voiceStatusText) voiceStatusText.textContent = 'Помилка відтворення на колонці';
            }
        });
    }

    // --- INTERNET RADIO (RADIO BROWSER) ---
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

            chip.addEventListener('click', async () => {

                hapticFeedback();
                currentRadioUrl = st.url;
                document.querySelectorAll('.radio-chip').forEach(c => c.classList.remove('active'));
                chip.classList.add('active');

                if (voiceStatusText) voiceStatusText.textContent = `Запуск радіо: ${st.name}...`;
                if (jblNowPlaying) jblNowPlaying.textContent = `📻 ${st.name}`;

                try {
                    const res = await fetch('/api/radio/play', {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({ url: st.url, name: st.name })
                    });
                    const data = await res.json();
                    if (voiceStatusText) voiceStatusText.textContent = data.response || `Грає ${st.name}`;
                    if (ttsEnabled) speakText(data.response);
                    fetchTelemetry();
                } catch (err) {
                    if (voiceStatusText) voiceStatusText.textContent = `Помилка запуску ${st.name}`;
                }
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

                // Light & Fan & Door
                if (st.relays_installed === false) {
                    if (statusLight) statusLight.textContent = 'Очікує реле';
                    if (statusFan) statusFan.textContent = 'Очікує реле';
                    if (statusDoor) statusDoor.textContent = 'Очікує реле';
                    if (tileLight) tileLight.classList.remove('active-light');
                    if (tileFan) tileFan.classList.remove('active-fan');
                    if (tileDoor) tileDoor.classList.remove('active-light');
                } else {
                    updateLightState(st.light);
                    updateFanState(st.fan);
                    updateDoorState(st.door === 'open');
                }

                // 3-Floor Climate Telemetry
                const floors = st.floors || {};
                const f1 = floors.floor1 || {};
                const f2 = floors.floor2 || {};
                const fb = floors.basement || {};

                // Helper for comfort status
                const getComfort = (t, h) => {
                    if (t === null || t === undefined || isNaN(t)) return 'Очікування';
                    if (t < 18) return 'Прохолодно';
                    if (t <= 25) return 'Комфортно';
                    return 'Тепло';
                };

                // Format update time helper
                const formatUpdateTime = (floorObj) => {
                    if (!floorObj) return 'Очікується оновлення';
                    if (floorObj.last_updated_formatted) return `Оновлено: ${floorObj.last_updated_formatted}`;
                    if (floorObj.last_updated_time) return `Оновлено: ${floorObj.last_updated_time}`;
                    return 'Очікується оновлення';
                };

                // Floor 1 (Garage - currently waiting for sensor)
                const isOnlineF1 = !!f1.online;
                const hasF1 = isOnlineF1 && f1.temperature !== null && f1.temperature !== undefined;
                const t1 = hasF1 ? Number(f1.temperature).toFixed(1) : '--';
                const h1 = (hasF1 && f1.humidity !== null && f1.humidity !== undefined) ? Number(f1.humidity).toFixed(0) : '--';
                const tip1 = formatUpdateTime(f1);
                if (valTempFloor1) {
                    valTempFloor1.textContent = t1;
                    valTempFloor1.title = tip1;
                    valTempFloor1.setAttribute('data-tooltip', tip1);
                    valTempFloor1.style.cursor = 'help';
                }
                if (valHumFloor1) {
                    valHumFloor1.textContent = h1;
                    valHumFloor1.title = tip1;
                }
                if (subFloor1) subFloor1.textContent = hasF1 ? `${getComfort(Number(t1), Number(h1))} • ${f1.last_updated_time || '--:--'}` : 'Очікує BLE-датчик';
                if (batFloor1) batFloor1.textContent = hasF1 ? `🔋 ${f1.battery || 100}%` : '--';

                // Floor 2 (LYWSD03MMC BLE)
                const isOnlineF2 = !!f2.online;
                const hasF2 = isOnlineF2 && f2.temperature !== null && f2.temperature !== undefined;
                const t2 = hasF2 ? Number(f2.temperature).toFixed(1) : '--';
                const h2 = (hasF2 && f2.humidity !== null && f2.humidity !== undefined) ? Number(f2.humidity).toFixed(0) : '--';
                const b2 = hasF2 && f2.battery !== null && f2.battery !== undefined ? `🔋 ${f2.battery}%` : '--';
                const tip2 = formatUpdateTime(f2);
                if (valTempFloor2) {
                    valTempFloor2.textContent = t2;
                    valTempFloor2.title = tip2;
                    valTempFloor2.setAttribute('data-tooltip', tip2);
                    valTempFloor2.style.cursor = 'help';
                }
                if (valHumFloor2) {
                    valHumFloor2.textContent = h2;
                    valHumFloor2.title = tip2;
                }
                if (subFloor2) subFloor2.textContent = isOnlineF2 ? `Онлайн • ${f2.last_updated_time || '--:--'}` : 'Офлайн (немає зв\'язку)';
                if (batFloor2) batFloor2.textContent = b2;

                // Basement (LYWSD03MMC BLE)
                const isOnlineFB = !!fb.online;
                const hasFB = isOnlineFB && fb.temperature !== null && fb.temperature !== undefined;
                const tb = hasFB ? Number(fb.temperature).toFixed(1) : '--';
                const hb = (hasFB && fb.humidity !== null && fb.humidity !== undefined) ? Number(fb.humidity).toFixed(0) : '--';
                const bb = (hasFB && fb.battery !== null && fb.battery !== undefined) ? `🔋 ${fb.battery}%` : '--';
                const tipB = formatUpdateTime(fb);
                if (valTempBasement) {
                    valTempBasement.textContent = tb;
                    valTempBasement.title = tipB;
                    valTempBasement.setAttribute('data-tooltip', tipB);
                    valTempBasement.style.cursor = 'help';
                }
                if (valHumBasement) {
                    valHumBasement.textContent = hb;
                    valHumBasement.title = tipB;
                }
                if (subBasement) subBasement.textContent = hasFB ? `${getComfort(Number(tb), Number(hb))} • ${fb.last_updated_time || '--:--'}` : 'Очікує даних';
                if (batBasement) batBasement.textContent = bb;

                // BLE sensors summary (Count configured BLE climate sensors)
                const totalBleSensors = 2; // Basement + Floor 2
                let activeBleCount = 0;
                if (f2.online) activeBleCount++;
                if (fb.online) activeBleCount++;
                if (valBleSensorsCount) valBleSensorsCount.textContent = `${activeBleCount} / ${totalBleSensors} онлайн`;
                if (subBleSensors) {
                    subBleSensors.textContent = activeBleCount > 0 ? "Підвал на зв'язку" : "Очікування сигналів";
                }

                // Air quality / Gas
                if (valAir) {
                    if (st.gas_ppm === null || st.gas_installed === false) {
                        valAir.textContent = 'Очікує монтажу';
                        valAir.style.fontSize = '1.05rem';
                        valAir.style.color = 'var(--text-muted, #94a3b8)';
                        if (subAir) {
                            subAir.textContent = 'MQ2 не підключено';
                            subAir.style.color = 'var(--text-muted, #94a3b8)';
                        }
                    } else {
                        const gas = st.gas_ppm;
                        valAir.textContent = `${gas} ppm`;
                        valAir.style.fontSize = '';
                        if (subAir) {
                            if (gas < 100) {
                                subAir.textContent = 'Повітря чисте';
                                subAir.style.color = '#34d399';
                            } else if (gas < 250) {
                                subAir.textContent = 'Увага: Задимлення';
                                subAir.style.color = '#fbbf24';
                            } else {
                                subAir.textContent = 'Небезпека: Газ/Дим!';
                                subAir.style.color = '#ef4444';
                            }
                        }
                    }
                }

                // ESP32 Status Pill
                if (pillEspStatus) {
                    const online = st.online !== false;
                    const transport = st.transport || 'Auto';
                    pillEspStatus.textContent = `ESP32: ${online ? 'Онлайн (' + transport + ')' : 'Очікування'}`;
                }

                // 4. Bluetooth JBL Speaker
                const spk = st.speaker || {};
                const spkConnected = !!spk.connected;
                if (jblOnlineDot) {
                    jblOnlineDot.className = `status-dot ${spkConnected ? 'online pulse' : 'offline'}`;
                }
                if (jblStatusBadge) {
                    jblStatusBadge.textContent = spkConnected ? 'Підключено' : 'Відключено';
                    jblStatusBadge.style.color = spkConnected ? 'var(--accent-cyan)' : 'var(--text-muted)';
                }
                if (jblCardTitle && spk.name) {
                    jblCardTitle.textContent = `Колонка ${spk.name}`;
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
                        const elapsed = spk.elapsed_seconds ? ` (${spk.elapsed_seconds}с)` : '';
                        jblNowPlaying.textContent = `▶ ${spk.current_track}${elapsed}`;
                        jblNowPlaying.style.color = 'var(--accent-cyan)';
                    } else {
                        jblNowPlaying.textContent = 'Немає активного відтворення';
                        jblNowPlaying.style.color = '#fff';
                    }
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
        } catch (e) {}

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
        } catch (e) {}
    }

    if (btnRefresh) {
        btnRefresh.addEventListener('click', () => {
            hapticFeedback();
            fetchTelemetry();
            loadMediaChips();
        });
    }

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
            subtitle: 'Датчик очікує підключення',
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
    }

    function closeClimateModal() {
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
                        modalEmptyMsg.textContent = activeModalFloor === 'floor1'
                            ? 'Для 1-го поверху фізичний датчик ще не встановлено.'
                            : 'Накопичення історії замірів триває (заміри фіксуються кожні кілька хвилин)...';
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
                            label: function(context) {
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

    // Initial Load & Regular Polling
    fetchTelemetry();
    loadMediaChips();
    loadRadioStations();
    setInterval(fetchTelemetry, 2500);
});
