document.addEventListener('DOMContentLoaded', () => {
    // DOM Elements - Console
    const commandForm = document.getElementById('commandForm');
    const commandInput = document.getElementById('commandInput');
    const executeBtn = document.getElementById('executeBtn');
    const voiceBtn = document.getElementById('voiceBtn');
    const voiceListeningBar = document.getElementById('voiceListeningBar');
    const voiceHint = document.getElementById('voiceHint');
    const ttsToggleBtn = document.getElementById('ttsToggleBtn');
    const ttsIcon = document.getElementById('ttsIcon');
    const history = document.getElementById('history');
    const loadingIndicator = document.getElementById('loadingIndicator');
    const clearBtn = document.getElementById('clearBtn');
    const statusDot = document.getElementById('statusDot');
    const statusText = document.getElementById('statusText');
    const welcomeTime = document.getElementById('welcomeTime');
    const quickBtns = document.querySelectorAll('.quick-btn');

    // Sidebar & Telemetry badges
    const telDoor = document.getElementById('telDoor');
    const telLight = document.getElementById('telLight');
    const telTemp = document.getElementById('telTemp');
    const telHum = document.getElementById('telHum');
    const telBat = document.getElementById('telBat');
    const telCar = document.getElementById('telCar');
    const sidebarProjBadge = document.getElementById('sidebarProjBadge');
    const sidebarJblBadge = document.getElementById('sidebarJblBadge');

    // Metric Cards in Charts Tab
    const chartCardTemp = document.getElementById('chartCardTemp');
    const chartCardTempSub = document.getElementById('chartCardTempSub');
    const chartCardTempF2 = document.getElementById('chartCardTempF2');
    const chartCardSubF2 = document.getElementById('chartCardSubF2');
    const chartCardTempFB = document.getElementById('chartCardTempFB');
    const chartCardSubFB = document.getElementById('chartCardSubFB');
    const chartCardHum = document.getElementById('chartCardHum');
    const chartCardHumSub = document.getElementById('chartCardHumSub');
    const chartCardCar = document.getElementById('chartCardCar');
    const chartCardAir = document.getElementById('chartCardAir');
    const telTempFloor2 = document.getElementById('telTempFloor2');
    const telTempBasement = document.getElementById('telTempBasement');
    const refreshChartBtn = document.getElementById('refreshChartBtn');

    // Media Hub Elements
    const mediaGrid = document.getElementById('mediaGrid');
    const refreshMediaBtn = document.getElementById('refreshMediaBtn');
    const streamForm = document.getElementById('streamForm');
    const streamInput = document.getElementById('streamInput');
    const projOnlineBadge = document.getElementById('projOnlineBadge');
    const projIpText = document.getElementById('projIpText');
    const projPauseBtn = document.getElementById('projPauseBtn');
    const projResumeBtn = document.getElementById('projResumeBtn');
    const projStopBtn = document.getElementById('projStopBtn');
    const projMirrorBtn = document.getElementById('projMirrorBtn');

    // JBL Speaker Elements
    const jblOnlineBadge = document.getElementById('jblOnlineBadge');
    const jblStatusText = document.getElementById('jblStatusText');
    const jblConnectBtn = document.getElementById('jblConnectBtn');
    const jblPauseBtn = document.getElementById('jblPauseBtn');
    const jblResumeBtn = document.getElementById('jblResumeBtn');
    const jblStopBtn = document.getElementById('jblStopBtn');


    // Tab Navigation
    const tabBtns = document.querySelectorAll('.tab-btn');
    const tabPanes = document.querySelectorAll('.tab-pane');

    let ttsEnabled = true;
    let isListening = false;
    let recognition = null;
    let telemetryChart = null;

    if (welcomeTime) {
        welcomeTime.textContent = new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
    }

    // --- TAB SWITCHING ---
    tabBtns.forEach(btn => {
        btn.addEventListener('click', () => {
            const targetTab = btn.getAttribute('data-tab');
            tabBtns.forEach(b => b.classList.remove('active'));
            tabPanes.forEach(p => p.classList.remove('active'));

            btn.classList.add('active');
            const targetPane = document.getElementById(targetTab);
            if (targetPane) {
                targetPane.classList.add('active');
            }

            if (targetTab === 'chartsTab') {
                initOrUpdateChart();
            } else if (targetTab === 'mediaTab') {
                loadMediaList();
                updateProjectorStatus();
            } else if (targetTab === 'adminTab') {
                checkAdminState();
            }
        });
    });

    if (window.location.hash === '#admin' || window.location.hash === '#adminTab') {
        const adminBtn = document.getElementById('adminTabBtn');
        if (adminBtn) adminBtn.click();
    }

    // --- HEALTH CHECK ---
    function checkHealth() {
        fetch('/health')
            .then(res => res.json())
            .then(data => {
                if (data.status === 'ok') {
                    if (statusDot) statusDot.className = 'status-dot online';
                    if (statusText) statusText.textContent = 'Сервер онлайн';
                } else {
                    if (statusDot) statusDot.className = 'status-dot offline';
                    if (statusText) statusText.textContent = 'Збій сервера';
                }
            })
            .catch(() => {
                if (statusDot) statusDot.className = 'status-dot offline';
                if (statusText) statusText.textContent = 'Немає зв\'язку';
            });
    }

    // --- TELEMETRY CHECK ---
    function updateTelemetry() {
        fetch('/api/garage/state')
            .then(res => res.json())
            .then(data => {
                if (data.success && data.state) {
                    const s = data.state;
                    if (telDoor) {
                        if (s.door === 'not_installed' || s.door_installed === false) {
                            telDoor.textContent = 'Очікує датчик';
                            telDoor.className = 'val-badge';
                            telDoor.title = 'Геркон воріт фізично ще не підключено';
                        } else {
                            const isOpen = s.door === 'open';
                            telDoor.textContent = isOpen ? 'Відкрито' : 'Закрито';
                            telDoor.className = isOpen ? 'val-badge warning' : 'val-badge';
                        }
                    }
                    if (telLight) {
                        if (s.relays_installed === false) {
                            telLight.textContent = 'Очікує реле';
                            telLight.className = 'val-badge';
                            telLight.title = 'Реле світла фізично ще не підключено';
                        } else {
                            telLight.textContent = s.light ? 'Увімкнено' : 'Вимкнено';
                            telLight.className = s.light ? 'val-badge active' : 'val-badge';
                        }
                    }
                    // Floors & Multi-sensor climate
                    const floors = s.floors || {};
                    const f1 = floors.floor1 || {};
                    const f2 = floors.floor2 || {};
                    const fb = floors.basement || {};

                    const formatTime = (obj, defaultName) => {
                        if (!obj) return `${defaultName}: Очікується оновлення`;
                        const timeStr = obj.last_updated_formatted || obj.last_updated_time || 'Очікується оновлення';
                        return `${obj.name || defaultName}: Оновлено о ${timeStr}`;
                    };

                    // Floor 1 (Garage - currently waiting for sensor)
                    const hasF1 = f1 && f1.temperature !== undefined && f1.temperature !== null;
                    const t1 = hasF1 ? `${Number(f1.temperature).toFixed(1)} °C` : 'Очікує датчик';
                    const tip1 = hasF1 ? formatTime(f1, '1-й поверх (Гараж)') : 'BLE-термометр на 1-му поверсі ще не встановлено';
                    if (telTemp) {
                        telTemp.textContent = t1;
                        telTemp.title = tip1;
                        telTemp.className = hasF1 ? 'val-badge active hoverable' : 'val-badge hoverable';
                    }
                    if (chartCardTemp) {
                        chartCardTemp.textContent = t1;
                        chartCardTemp.title = tip1;
                    }
                    if (chartCardTempSub) {
                        chartCardTempSub.textContent = hasF1 ? `Оновлено: ${f1.last_updated_time || '--:--'} • 🔋 ${f1.battery || 100}%` : 'Очікує монтажу датчика';
                    }

                    // Floor 2 (Xiaomi LYWSD03MMC)
                    const isOnlineF2 = f2 && !!f2.online;
                    const hasF2 = isOnlineF2 && f2.temperature !== undefined && f2.temperature !== null;
                    const t2 = hasF2 ? `${Number(f2.temperature).toFixed(1)} °C` : '-- °C';
                    const tip2 = formatTime(f2, '2-й поверх');
                    if (telTempFloor2) {
                        telTempFloor2.textContent = t2;
                        telTempFloor2.title = tip2;
                        telTempFloor2.className = isOnlineF2 ? 'val-badge active hoverable' : 'val-badge hoverable';
                    }
                    if (chartCardTempF2) {
                        chartCardTempF2.textContent = t2;
                        chartCardTempF2.title = tip2;
                    }
                    if (chartCardSubF2) {
                        chartCardSubF2.textContent = isOnlineF2 ? `Онлайн • ${f2.last_updated_time || '--:--'} • 🔋 ${f2.battery || 99}%` : 'Офлайн (немає зв\'язку)';
                    }

                    // Basement (Xiaomi LYWSD03MMC - Online)
                    const hasFB = fb && fb.temperature !== undefined && fb.temperature !== null;
                    const tb = hasFB ? `${Number(fb.temperature).toFixed(1)} °C` : '-- °C';
                    const tipB = formatTime(fb, 'Підвал');
                    if (telTempBasement) {
                        telTempBasement.textContent = tb;
                        telTempBasement.title = tipB;
                        telTempBasement.className = (fb && fb.online) ? 'val-badge active hoverable' : 'val-badge hoverable';
                    }
                    if (chartCardTempFB) {
                        chartCardTempFB.textContent = tb;
                        chartCardTempFB.title = tipB;
                    }
                    if (chartCardSubFB) {
                        chartCardSubFB.textContent = hasFB ? `Оновлено: ${fb.last_updated_time || '--:--'} • 🔋 ${fb.battery || 99}%` : 'Очікує даних';
                    }

                    // Humidity (prefer real basement reading or floor1)
                    const humReading = (hasFB && fb.humidity !== undefined && fb.humidity !== null) ? fb.humidity : (hasF1 ? f1.humidity : null);
                    const humVal = humReading !== null ? `${Number(humReading).toFixed(0)} %` : '-- %';
                    const humTip = hasFB ? `Вологість у підвалі: ${humVal}` : 'Очікується датчик';
                    if (telHum) {
                        telHum.textContent = humVal;
                        telHum.title = humTip;
                    }
                    if (chartCardHum) {
                        chartCardHum.textContent = humVal;
                        chartCardHum.title = humTip;
                    }

                    // Battery (calculate only from real configured sensors)
                    if (telBat) {
                        const bats = [];
                        if (hasFB && fb.battery !== null && fb.battery !== undefined) bats.push(fb.battery);
                        if (hasF2 && f2.battery !== null && f2.battery !== undefined) bats.push(f2.battery);
                        if (bats.length > 0) {
                            telBat.textContent = `🔋 ${Math.min(...bats)}%`;
                            telBat.title = `Заряд батарей: Підвал: ${fb.battery || '--'}%, 2-й поверх: ${f2.battery || '--'}%`;
                        } else {
                            telBat.textContent = `🔋 -- %`;
                            telBat.title = `Немає активних датчиків`;
                        }
                    }

                    // Car status (Ultrasonic HC-SR04 not installed yet)
                    if (telCar) {
                        if (s.car_present === null || s.car_sensor_installed === false) {
                            telCar.textContent = 'Очікує датчик';
                            telCar.className = 'val-badge';
                            telCar.title = 'Ультразвуковий датчик авто ще не встановлено';
                            if (chartCardCar) chartCardCar.textContent = 'Очікує монтажу';
                        } else {
                            const carText = s.car_present ? 'На місці' : 'Відсутнє';
                            telCar.textContent = carText;
                            telCar.className = s.car_present ? 'val-badge active' : 'val-badge';
                            if (chartCardCar) chartCardCar.textContent = carText;
                        }
                    }

                    // Gas / Air quality (MQ2 sensor not installed yet)
                    if (chartCardAir) {
                        if (s.gas_ppm === null || s.gas_installed === false) {
                            chartCardAir.textContent = 'Очікує монтажу';
                            chartCardAir.className = 'metric-val text-muted';
                            chartCardAir.title = 'Газовий сенсор MQ2 фізично ще не підключено';
                        } else {
                            const gas = s.gas_ppm;
                            chartCardAir.textContent = gas < 100 ? `Норма (${gas} ppm)` : `Увага (${gas} ppm)`;
                            chartCardAir.className = gas < 100 ? 'metric-val text-success' : 'metric-val text-warning';
                        }
                    }
                    updateSpeakerStatus();
                    updateProjectorStatus();
                }
            })
            .catch(() => {});
    }

    // --- TELEMETRY CHART (Chart.js) ---
    function initOrUpdateChart() {
        fetch('/api/telemetry/history')
            .then(res => res.json())
            .then(data => {
                if (data.success && data.history) {
                    const labels = data.history.map(item => item.time);
                    const temps = data.history.map(item => item.temperature);
                    const hums = data.history.map(item => item.humidity);

                    const canvas = document.getElementById('telemetryChart');
                    if (!canvas || !window.Chart) return;

                    if (telemetryChart) {
                        telemetryChart.data.labels = labels;
                        telemetryChart.data.datasets[0].data = temps;
                        telemetryChart.data.datasets[1].data = hums;
                        telemetryChart.update();
                        return;
                    }

                    const ctx = canvas.getContext('2d');
                    telemetryChart = new Chart(ctx, {
                        type: 'line',
                        data: {
                            labels: labels,
                            datasets: [
                                {
                                    label: 'Температура (°C)',
                                    data: temps,
                                    borderColor: '#38bdf8',
                                    backgroundColor: 'rgba(56, 189, 248, 0.15)',
                                    borderWidth: 2,
                                    tension: 0.35,
                                    fill: true,
                                    yAxisID: 'y'
                                },
                                {
                                    label: 'Вологість (%)',
                                    data: hums,
                                    borderColor: '#22c55e',
                                    backgroundColor: 'rgba(34, 197, 94, 0.1)',
                                    borderWidth: 2,
                                    tension: 0.35,
                                    fill: true,
                                    yAxisID: 'y1'
                                }
                            ]
                        },
                        options: {
                            responsive: true,
                            maintainAspectRatio: false,
                            interaction: {
                                mode: 'index',
                                intersect: false
                            },
                            scales: {
                                x: {
                                    grid: { color: 'rgba(255, 255, 255, 0.05)' },
                                    ticks: { color: '#94a3b8' }
                                },
                                y: {
                                    type: 'linear',
                                    display: true,
                                    position: 'left',
                                    grid: { color: 'rgba(255, 255, 255, 0.05)' },
                                    ticks: { color: '#38bdf8' }
                                },
                                y1: {
                                    type: 'linear',
                                    display: true,
                                    position: 'right',
                                    grid: { drawOnChartArea: false },
                                    ticks: { color: '#22c55e' }
                                }
                            },
                            plugins: {
                                legend: {
                                    labels: { color: '#f8fafc', font: { size: 12 } }
                                }
                            }
                        }
                    });
                }
            })
            .catch(err => console.warn('Chart load error:', err));
    }

    if (refreshChartBtn) {
        refreshChartBtn.addEventListener('click', initOrUpdateChart);
    }

    // --- MEDIA HUB & PROJECTOR CONTROLS ---
    function updateSpeakerStatus() {
        fetch('/api/speaker/status')
            .then(res => res.json())
            .then(data => {
                if (data.success && data.speaker) {
                    const s = data.speaker;
                    const isConnected = !!s.connected;
                    if (sidebarJblBadge) {
                        sidebarJblBadge.textContent = isConnected ? 'Підключено' : 'Відключено';
                        sidebarJblBadge.className = isConnected ? 'badge badge-accent' : 'badge';
                    }
                    if (jblOnlineBadge) {
                        jblOnlineBadge.textContent = isConnected ? '● JBL Clip 5 Підключено' : '○ JBL Clip 5 Відключено';
                        jblOnlineBadge.style.color = isConnected ? 'var(--accent-cyan, #00f0ff)' : 'var(--text-muted, #94a3b8)';
                    }
                    if (jblStatusText) {
                        if (s.playing && s.current_track) {
                            jblStatusText.textContent = `▶ Грає: ${s.current_track} (${s.volume}%)`;
                        } else {
                            jblStatusText.textContent = isConnected ? `Готово до відтворення (Гучність: ${s.volume}%)` : 'Відключено';
                        }
                    }
                    if (jblConnectBtn) {
                        jblConnectBtn.textContent = isConnected ? '🔌 Відключити' : '🔗 Підключити';
                    }
                }
            })
            .catch(() => {});
    }

    if (jblConnectBtn) {
        jblConnectBtn.addEventListener('click', () => {
            const isConnected = sidebarJblBadge && sidebarJblBadge.textContent.includes('Підключено');
            const endpoint = isConnected ? '/api/speaker/disconnect' : '/api/speaker/connect';
            jblConnectBtn.textContent = 'Зачекайте...';
            fetch(endpoint, { method: 'POST' })
                .then(res => res.json())
                .then(data => {
                    appendEntry('system', data.response || 'Команду виконано');
                    updateSpeakerStatus();
                })
                .catch(err => appendEntry('system', `Помилка: ${err.message}`));
        });
    }

    if (jblPauseBtn) jblPauseBtn.addEventListener('click', () => {
        fetch('/api/speaker/control', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ action: 'pause' })
        }).then(updateSpeakerStatus);
    });

    if (jblResumeBtn) jblResumeBtn.addEventListener('click', () => {
        fetch('/api/speaker/control', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ action: 'resume' })
        }).then(updateSpeakerStatus);
    });

    if (jblStopBtn) jblStopBtn.addEventListener('click', () => {
        fetch('/api/speaker/control', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ action: 'stop' })
        }).then(updateSpeakerStatus);
    });

    function updateProjectorStatus() {
        fetch('/api/projector/status')
            .then(res => res.json())
            .then(data => {
                if (data.success && data.projector) {
                    const p = data.projector;
                    const isOnline = p.online;
                    if (sidebarProjBadge) {
                        sidebarProjBadge.textContent = isOnline ? 'Онлайн' : 'Офлайн';
                        sidebarProjBadge.className = isOnline ? 'badge badge-accent' : 'badge';
                    }
                    if (projOnlineBadge) {
                        projOnlineBadge.textContent = isOnline ? '● HY350MAX Онлайн' : '○ HY350MAX Офлайн';
                        projOnlineBadge.style.color = isOnline ? 'var(--success)' : 'var(--danger)';
                    }
                    if (projIpText) {
                        projIpText.textContent = `IP: ${p.ip || '--'}`;
                    }
                    if (projMirrorBtn) {
                        projMirrorBtn.textContent = p.mirroring ? '⏹ Зупинити трансляцію' : '🖥️ Трансляція екрану';
                    }
                }
            })
            .catch(() => {});
    }


    function loadMediaList() {
        if (!mediaGrid) return;
        fetch('/api/media/list')
            .then(res => res.json())
            .then(data => {
                if (data.success && data.media) {
                    if (data.media.length === 0) {
                        mediaGrid.innerHTML = '<div class="media-placeholder">У директорії media/ поки немає відеофайлів</div>';
                        return;
                    }
                    mediaGrid.innerHTML = '';
                    data.media.forEach(file => {
                        const card = document.createElement('div');
                        card.className = 'media-card';
                        card.innerHTML = `
                            <div class="media-card-top">
                                <div class="media-card-icon">🎬</div>
                                <div class="media-card-info">
                                    <div class="media-card-title" title="${file.title}">${file.title}</div>
                                    <div class="media-card-meta">${file.size_mb} MB • ${file.modified}</div>
                                </div>
                            </div>
                            <button class="media-card-btn" data-filename="${file.filename}">
                                <span>▶ Грати на проекторі</span>
                            </button>
                        `;
                        mediaGrid.appendChild(card);
                    });

                    // Attach click handlers to play buttons
                    document.querySelectorAll('.media-card-btn').forEach(btn => {
                        btn.addEventListener('click', () => {
                            const fname = btn.getAttribute('data-filename');
                            playMedia(fname);
                        });
                    });
                }
            })
            .catch(() => {
                if (mediaGrid) {
                    mediaGrid.innerHTML = '<div class="media-placeholder">Помилка завантаження медіафайлів</div>';
                }
            });
    }

    function playMedia(filename) {
        appendEntry('system', `Запуск відтворення: ${filename} на проекторі...`);
        fetch('/api/media/play', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ filename: filename })
        })
        .then(res => res.json())
        .then(data => {
            appendEntry('system', data.response || (data.success ? 'Відтворення запущено' : 'Помилка відтворення'));
        })
        .catch(err => appendEntry('system', `Помилка: ${err.message}`));
    }

    function controlProjector(action, value) {
        fetch('/api/media/control', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ action: action, value: value })
        })
        .then(res => res.json())
        .then(data => {
            appendEntry('system', data.response || 'Команду проектору виконано');
        })
        .catch(err => appendEntry('system', `Помилка: ${err.message}`));
    }

    if (projPauseBtn) projPauseBtn.addEventListener('click', () => controlProjector('pause'));
    if (projResumeBtn) projResumeBtn.addEventListener('click', () => controlProjector('resume'));
    if (projStopBtn) projStopBtn.addEventListener('click', () => controlProjector('stop'));
    if (projMirrorBtn) {
        projMirrorBtn.addEventListener('click', () => {
            fetch('/api/projector/mirror', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ action: 'toggle' })
            })
            .then(res => res.json())
            .then(data => {
                updateProjectorStatus();
                appendEntry('system', data.mirroring ? 'Трансляцію екрану запущено' : 'Трансляцію екрану зупинено');
            });
        });
    }

    if (refreshMediaBtn) refreshMediaBtn.addEventListener('click', loadMediaList);

    if (streamForm) {
        streamForm.addEventListener('submit', (e) => {
            e.preventDefault();
            const query = (streamInput ? streamInput.value : '').trim();
            if (!query) return;

            appendEntry('user', `Стрім на проектор: ${query}`);
            appendEntry('system', `Завантаження та запуск потоку для "${query}"...`);
            setLoading(true);

            fetch('/api/media/stream_url', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ query: query })
            })
            .then(res => res.json())
            .then(data => {
                appendEntry('ai', data.response || 'Стрім запущено на проекторі');
                if (streamInput) streamInput.value = '';
                loadMediaList();
            })
            .catch(err => appendEntry('system', `Помилка стрімінгу: ${err.message}`))
            .finally(() => setLoading(false));
        });
    }

    // --- TIMERS & INITIAL CALLS ---
    checkHealth();
    updateTelemetry();
    updateProjectorStatus();
    setInterval(checkHealth, 15000);
    setInterval(updateTelemetry, 4000);
    setInterval(updateProjectorStatus, 20000);
    setInterval(() => {
        if (sessionStorage.getItem('sg_admin_auth') === 'true' && document.getElementById('adminTab')?.classList.contains('active')) {
            loadPresenceData();
        }
    }, 20000);

    // --- FORMAT TIME ---
    function getCurrentTime() {
        return new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
    }

    // --- TEXT TO SPEECH (TTS) ---
    function speakText(text) {
        if (!ttsEnabled || !window.speechSynthesis) return;

        let clean = text
            .replace(/https?:\/\/\S+/g, '')
            .replace(/[*_#`[\]()]/g, '')
            .replace(/•/g, '')
            .replace(/\s+/g, ' ')
            .trim();

        if (!clean) return;

        window.speechSynthesis.cancel();
        const utterance = new SpeechSynthesisUtterance(clean);
        utterance.lang = 'uk-UA';
        utterance.rate = 1.05;

        const voices = window.speechSynthesis.getVoices();
        const ukVoice = voices.find(v => v.lang.startsWith('uk')) || voices.find(v => v.lang.startsWith('en'));
        if (ukVoice) utterance.voice = ukVoice;

        window.speechSynthesis.speak(utterance);
    }

    // --- SPEECH RECOGNITION (STT) ---
    const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
    if (SpeechRecognition) {
        recognition = new SpeechRecognition();
        recognition.continuous = false;
        recognition.interimResults = false;
        recognition.lang = 'uk-UA';

        recognition.onstart = () => {
            isListening = true;
            if (voiceBtn) voiceBtn.classList.add('listening');
            if (voiceListeningBar) voiceListeningBar.style.display = 'flex';
            if (voiceHint) voiceHint.textContent = 'Слухаю... Говоріть команду';
        };

        recognition.onresult = (event) => {
            const transcript = event.results[0][0].transcript;
            if (commandInput) commandInput.value = transcript;
            sendCommand(transcript);
        };

        recognition.onerror = (event) => {
            console.warn('Speech recognition error:', event.error);
            stopListening();
        };

        recognition.onend = () => {
            stopListening();
        };
    } else {
        if (voiceBtn) {
            voiceBtn.style.opacity = '0.5';
            voiceBtn.title = 'Голосовий ввід не підтримується цим браузером';
        }
    }

    function toggleListening() {
        if (!recognition) {
            alert('Голосовий ввід Web Speech API не підтримується у цьому браузері. Рекомендовано Chrome або Edge.');
            return;
        }
        if (isListening) {
            recognition.stop();
            stopListening();
        } else {
            try {
                recognition.start();
            } catch (e) {
                recognition.stop();
            }
        }
    }

    function stopListening() {
        isListening = false;
        if (voiceBtn) voiceBtn.classList.remove('listening');
        if (voiceListeningBar) voiceListeningBar.style.display = 'none';
    }

    if (voiceBtn) {
        voiceBtn.addEventListener('click', toggleListening);
    }

    // TTS Toggle
    if (ttsToggleBtn) {
        ttsToggleBtn.addEventListener('click', () => {
            ttsEnabled = !ttsEnabled;
            const label = ttsToggleBtn.querySelector('.tts-label');
            if (ttsEnabled) {
                ttsIcon.textContent = '🔊';
                if (label) label.textContent = 'Озвучення: Увімк';
                ttsToggleBtn.classList.remove('disabled');
            } else {
                window.speechSynthesis.cancel();
                ttsIcon.textContent = '🔇';
                if (label) label.textContent = 'Озвучення: Вимк';
                ttsToggleBtn.classList.add('disabled');
            }
        });
    }

    // --- APPEND MESSAGE TO HISTORY ---
    function appendEntry(role, text) {
        if (!history) return;
        const entry = document.createElement('div');
        entry.classList.add('entry');

        const meta = document.createElement('div');
        meta.classList.add('entry-meta');

        const tag = document.createElement('span');
        tag.classList.add('sender-tag');

        const time = document.createElement('span');
        time.classList.add('time');
        time.textContent = getCurrentTime();

        if (role === 'user') {
            entry.classList.add('user-entry');
            tag.classList.add('user-tag');
            tag.textContent = 'Ви';
            meta.appendChild(time);
            meta.appendChild(tag);
        } else if (role === 'system') {
            entry.classList.add('system-entry');
            tag.classList.add('system-tag');
            tag.textContent = 'Система';
            meta.appendChild(tag);
            meta.appendChild(time);
        } else {
            entry.classList.add('ai-entry');
            tag.classList.add('ai-tag');
            tag.textContent = 'Smart Garage AI';
            meta.appendChild(tag);
            meta.appendChild(time);
        }

        const bubble = document.createElement('div');
        bubble.classList.add('entry-bubble');
        bubble.textContent = text;

        entry.appendChild(meta);
        entry.appendChild(bubble);
        history.appendChild(entry);
        history.scrollTop = history.scrollHeight;
    }

    // --- SEND COMMAND ---
    function sendCommand(cmdText) {
        const command = (cmdText || '').trim();
        if (!command) return;

        appendEntry('user', command);
        if (commandInput) {
            commandInput.value = '';
        }

        setLoading(true);

        fetch('/command', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({ command: command })
        })
        .then(response => {
            if (!response.ok) {
                return response.json().then(errData => {
                    throw new Error(errData.response || `HTTP Error ${response.status}`);
                });
            }
            return response.json();
        })
        .then(data => {
            if (data.success) {
                const aiResp = data.response || 'Команду виконано.';
                appendEntry('ai', aiResp);
                speakText(aiResp);
                updateTelemetry();
            } else {
                appendEntry('system', `Помилка: ${data.response || 'Невідома помилка'}`);
            }
        })
        .catch(err => {
            appendEntry('system', `Помилка запиту: ${err.message}`);
        })
        .finally(() => {
            setLoading(false);
            if (commandInput) commandInput.focus();
        });
    }

    function setLoading(isLoading) {
        if (loadingIndicator && executeBtn) {
            if (isLoading) {
                loadingIndicator.style.display = 'flex';
                executeBtn.disabled = true;
                if (commandInput) commandInput.disabled = true;
                if (history) history.scrollTop = history.scrollHeight;
            } else {
                loadingIndicator.style.display = 'none';
                executeBtn.disabled = false;
                if (commandInput) commandInput.disabled = false;
            }
        }
    }

    // Form submission
    if (commandForm) {
        commandForm.addEventListener('submit', (e) => {
            e.preventDefault();
            sendCommand(commandInput.value);
        });
    }

    // Quick action buttons
    quickBtns.forEach(btn => {
        btn.addEventListener('click', () => {
            const cmd = btn.getAttribute('data-cmd');
            if (cmd) {
                sendCommand(cmd);
            }
        });
    });

    // Clear history
    if (clearBtn) {
        clearBtn.addEventListener('click', () => {
            history.innerHTML = `
                <div class="entry system-entry">
                    <div class="entry-meta">
                        <span class="sender-tag system-tag">Система</span>
                        <span class="time">${getCurrentTime()}</span>
                    </div>
                    <div class="entry-bubble">
                        Історію консолі очищено.
                    </div>
                </div>
            `;
        });
    }

    // =========================================================================
    // ADMIN & PRESENCE MANAGEMENT LOGIC
    // =========================================================================
    const adminAuthSection = document.getElementById('adminAuthSection');
    const adminContentSection = document.getElementById('adminContentSection');
    const adminPinForm = document.getElementById('adminPinForm');
    const adminPinInput = document.getElementById('adminPinInput');
    const adminPinError = document.getElementById('adminPinError');
    const adminLogoutBtn = document.getElementById('adminLogoutBtn');

    const presenceCardsGrid = document.getElementById('presenceCardsGrid');
    const btnRefreshPresence = document.getElementById('btnRefreshPresence');

    const btnTriggerEspScan = document.getElementById('btnTriggerEspScan');
    const scanDurationSelect = document.getElementById('scanDurationSelect');
    const scanStatusIndicator = document.getElementById('scanStatusIndicator');
    const scanStatusMsg = document.getElementById('scanStatusMsg');
    const scanResultsBody = document.getElementById('scanResultsBody');

    const addDeviceForm = document.getElementById('addDeviceForm');
    const devName = document.getElementById('devName');
    const devRole = document.getElementById('devRole');
    const devType = document.getElementById('devType');
    const devModel = document.getElementById('devModel');
    const devClassicMac = document.getElementById('devClassicMac');
    const devBleMac = document.getElementById('devBleMac');

    const devicesTableBody = document.getElementById('devicesTableBody');
    const logTableBody = document.getElementById('logTableBody');
    const btnRefreshLog = document.getElementById('btnRefreshLog');

    function checkAdminState() {
        const isAuth = sessionStorage.getItem('sg_admin_auth') === 'true';
        if (isAuth) {
            if (adminAuthSection) adminAuthSection.style.display = 'none';
            if (adminContentSection) adminContentSection.style.display = 'block';
            loadPresenceData();
            loadDevicesData();
            loadLogData();
        } else {
            if (adminAuthSection) adminAuthSection.style.display = 'block';
            if (adminContentSection) adminContentSection.style.display = 'none';
            if (adminPinInput) adminPinInput.value = '';
            if (adminPinError) adminPinError.style.display = 'none';
        }
    }

    if (adminPinForm) {
        adminPinForm.addEventListener('submit', (e) => {
            e.preventDefault();
            const pin = (adminPinInput ? adminPinInput.value : '').trim();
            if (!pin) return;

            fetch('/api/admin/verify', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ pin: pin })
            })
            .then(res => res.json())
            .then(data => {
                if (data.authenticated) {
                    sessionStorage.setItem('sg_admin_auth', 'true');
                    checkAdminState();
                } else {
                    if (adminPinError) {
                        adminPinError.style.display = 'block';
                        adminPinError.textContent = data.error || 'Невірний PIN-код!';
                    }
                }
            })
            .catch(err => {
                if (adminPinError) {
                    adminPinError.style.display = 'block';
                    adminPinError.textContent = 'Помилка зв\'язку з сервером: ' + err.message;
                }
            });
        });
    }

    if (adminLogoutBtn) {
        adminLogoutBtn.addEventListener('click', () => {
            sessionStorage.removeItem('sg_admin_auth');
            checkAdminState();
        });
    }

    function loadPresenceData() {
        if (!presenceCardsGrid) return;
        fetch('/api/presence/status')
            .then(res => res.json())
            .then(data => {
                if (!data.success || !data.presence) return;
                const p = data.presence;
                const devices = Object.values(p.devices || {});

                if (!devices.length) {
                    presenceCardsGrid.innerHTML = '<div class="admin-placeholder">Немає зареєстрованих осіб у базі.</div>';
                    return;
                }

                presenceCardsGrid.innerHTML = devices.map(d => {
                    const isPresent = (d.status === 'present');
                    const badgeClass = isPresent ? 'badge-present' : 'badge-away';
                    const badgeText = isPresent ? '🟢 В гаражі / Поруч' : '⚪ Відсутній';

                    let proxText = 'Невідомо';
                    if (d.proximity === 'immediate') proxText = 'Дуже близько (< 2м)';
                    else if (d.proximity === 'near') proxText = 'Поруч (2 - 6м)';
                    else if (d.proximity === 'approaching') proxText = 'На підході (> 6м)';

                    const icon = d.device_type === 'watch' ? '⌚' : (d.device_type === 'car' ? '🚗' : (d.device_type === 'tag' ? '🏷️' : '📱'));
                    const lastSeenStr = d.last_seen ? new Date(d.last_seen * 1000).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' }) : 'Ніколи';

                    let macParts = [];
                    if (d.classic_mac) {
                        macParts.push(`<div><strong>Classic MAC:</strong> <code class="badge-mac">${escapeHtml(d.classic_mac)}</code></div>`);
                    }
                    const rpaList = d.recent_ble_rpa || [];
                    if (rpaList.length > 0) {
                        const latestRpa = rpaList[rpaList.length - 1];
                        macParts.push(`<div><strong>BLE RPA/MAC:</strong> <code class="badge-mac">${escapeHtml(latestRpa)}</code></div>`);
                    }
                    if (macParts.length === 0) {
                        macParts.push(`<div><strong>MAC:</strong> <span class="text-muted">Не вказано</span></div>`);
                    }

                    return `
                        <div class="presence-card ${isPresent ? 'is-present' : ''}">
                            <div class="presence-card-top">
                                <span class="presence-card-name">${icon} ${escapeHtml(d.name)}</span>
                                <span class="presence-badge ${badgeClass}">${badgeText}</span>
                            </div>
                            <div class="presence-card-details">
                                <div><strong>Пристрій:</strong> ${escapeHtml(d.device_name || d.device_type)}</div>
                                ${macParts.join('')}
                                <div><strong>Дистанція:</strong> ${proxText} ${d.last_rssi ? `(${d.last_rssi} dBm)` : ''}</div>
                                <div><strong>Останній контакт:</strong> ${lastSeenStr}</div>
                            </div>
                        </div>
                    `;
                }).join('');
            })
            .catch(err => {
                presenceCardsGrid.innerHTML = `<div class="admin-placeholder" style="color: var(--danger);">Помилка завантаження: ${err.message}</div>`;
            });
    }

    function loadDevicesData() {
        if (!devicesTableBody) return;
        fetch('/api/presence/status')
            .then(res => res.json())
            .then(data => {
                if (!data.success || !data.presence) return;
                const devices = Object.values(data.presence.devices || {});

                if (!devices.length) {
                    devicesTableBody.innerHTML = '<tr><td colspan="6" class="text-muted text-center">Немає пристроїв у базі</td></tr>';
                    return;
                }

                devicesTableBody.innerHTML = devices.map(d => {
                    const roleUa = d.role === 'owner' ? '👑 Власник' : (d.role === 'family' ? '🏠 Сім\'я' : '👤 Гість');
                    const isPresent = (d.status === 'present');
                    const statusHtml = isPresent ? '<span class="badge badge-present">🟢 Присутній</span>' : '<span class="badge badge-away">⚪ Відсутній</span>';
                    const macStr = d.classic_mac || (d.recent_ble_rpa && d.recent_ble_rpa[0]) || '—';

                    return `
                        <tr>
                            <td><strong>${escapeHtml(d.name)}</strong></td>
                            <td>${roleUa}</td>
                            <td>${escapeHtml(d.device_name)} (${d.device_type})</td>
                            <td><code>${escapeHtml(macStr)}</code></td>
                            <td>${statusHtml}</td>
                            <td>
                                <button class="btn-ctrl btn-danger-sm btn-delete-device" data-id="${escapeHtml(d.id)}">
                                    🗑️ Видалити
                                </button>
                            </td>
                        </tr>
                    `;
                }).join('');

                document.querySelectorAll('.btn-delete-device').forEach(btn => {
                    btn.addEventListener('click', () => {
                        const devId = btn.getAttribute('data-id');
                        if (!confirm(`Ви дійсно бажаєте видалити "${devId}" з реєстру?`)) return;
                        fetch(`/api/presence/devices/${devId}`, { method: 'DELETE' })
                            .then(res => res.json())
                            .then(() => {
                                loadDevicesData();
                                loadPresenceData();
                            });
                    });
                });
            });
    }

    function loadLogData() {
        if (!logTableBody) return;
        fetch('/api/presence/log?limit=30')
            .then(res => res.json())
            .then(data => {
                if (!data.success || !data.log) return;
                const logs = data.log;

                if (!logs.length) {
                    logTableBody.innerHTML = '<tr><td colspan="6" class="text-muted text-center">Журнал порожній</td></tr>';
                    return;
                }

                logTableBody.innerHTML = logs.map(l => {
                    let evBadge = '';
                    if (l.event === 'ARRIVED') evBadge = '<span class="badge badge-present">🟢 Прибув / Поруч</span>';
                    else if (l.event === 'DEPARTED') evBadge = '<span class="badge badge-away">🔴 Пішов / Поза зоною</span>';
                    else evBadge = `<span class="badge">${l.event}</span>`;

                    let proxUa = l.proximity === 'immediate' ? 'Дуже близько (<2м)' : (l.proximity === 'near' ? 'Поруч (2-6м)' : 'На підході');
                    if (l.rssi) proxUa += ` (${l.rssi} dBm)`;

                    return `
                        <tr>
                            <td><small>${escapeHtml(l.formatted_time)}</small></td>
                            <td>${evBadge}</td>
                            <td><strong>${escapeHtml(l.person_name)}</strong></td>
                            <td>${escapeHtml(l.device_name)}</td>
                            <td>${proxUa}</td>
                            <td><small><code>${escapeHtml(l.source)}</code></small></td>
                        </tr>
                    `;
                }).join('');
            });
    }

    if (btnRefreshPresence) btnRefreshPresence.addEventListener('click', loadPresenceData);
    if (btnRefreshLog) btnRefreshLog.addEventListener('click', loadLogData);

    if (btnTriggerEspScan) {
        btnTriggerEspScan.addEventListener('click', () => {
            const dur = scanDurationSelect ? scanDurationSelect.value : '15';
            if (scanStatusIndicator) {
                scanStatusIndicator.style.display = 'flex';
                if (scanStatusMsg) scanStatusMsg.textContent = `ESP32 активно сканує Bluetooth-ефір (${dur} сек)... Зачекайте`;
            }
            btnTriggerEspScan.disabled = true;

            fetch(`/api/presence/scan?duration=${dur}`, { method: 'POST' })
                .then(res => res.json())
                .then(data => {
                    if (scanStatusIndicator) scanStatusIndicator.style.display = 'none';
                    btnTriggerEspScan.disabled = false;

                    if (!data.success) {
                        alert('Помилка сканування: ' + (data.error || 'Невідома'));
                        return;
                    }

                    loadPresenceData();
                    loadDevicesData();
                    loadLogData();

                    const list = data.devices || [];
                    if (!list.length) {
                        if (scanResultsBody) {
                            scanResultsBody.innerHTML = '<tr><td colspan="4" class="text-muted text-center">Завершено. Пристроїв у радіусі дії не виявлено.</td></tr>';
                        }
                        return;
                    }

                    if (scanResultsBody) {
                        scanResultsBody.innerHTML = list.map(d => {
                            const sourceTag = d.source ? `<span class="badge" style="font-size: 10px; margin-left: 6px;">${escapeHtml(d.source)}</span>` : '';
                            return `
                                <tr>
                                    <td><code>${escapeHtml(d.mac)}</code></td>
                                    <td><strong>${escapeHtml(d.name || '<Без імені / RPA>')}</strong>${sourceTag}</td>
                                    <td><strong style="color: ${d.rssi >= -65 ? 'var(--success)' : 'var(--text-primary)'};">${d.rssi} dBm</strong></td>
                                    <td>
                                        <button class="btn-ctrl btn-link-guest" data-mac="${escapeHtml(d.mac)}" data-name="${escapeHtml(d.name || '')}">
                                            ➕ Прив'язати до гостя
                                        </button>
                                    </td>
                                </tr>
                            `;
                        }).join('');

                        document.querySelectorAll('.btn-link-guest').forEach(b => {
                            b.addEventListener('click', () => {
                                const m = b.getAttribute('data-mac');
                                const n = b.getAttribute('data-name');
                                if (devBleMac) devBleMac.value = m;
                                if (devModel && n) devModel.value = n;
                                if (devName) devName.focus();
                                if (addDeviceForm) addDeviceForm.scrollIntoView({ behavior: 'smooth' });
                            });
                        });
                    }
                })
                .catch(err => {
                    if (scanStatusIndicator) scanStatusIndicator.style.display = 'none';
                    btnTriggerEspScan.disabled = false;
                    alert('Помилка під час сканування: ' + err.message);
                });
        });
    }

    if (addDeviceForm) {
        addDeviceForm.addEventListener('submit', (e) => {
            e.preventDefault();
            const name = (devName ? devName.value : '').trim();
            if (!name) return;

            const payload = {
                name: name,
                role: devRole ? devRole.value : 'guest',
                device_type: devType ? devType.value : 'phone',
                device_name: (devModel && devModel.value.trim()) || name,
                classic_mac: (devClassicMac && devClassicMac.value.trim()) || '',
                ble_mac: (devBleMac && devBleMac.value.trim()) || ''
            };

            fetch('/api/presence/devices', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(payload)
            })
            .then(res => res.json())
            .then(data => {
                if (data.success) {
                    alert(`✅ Гостя/пристрій "${name}" успішно зареєстровано в базі!`);
                    addDeviceForm.reset();
                    loadDevicesData();
                    loadPresenceData();
                    loadLogData();
                } else {
                    alert('Помилка збереження: ' + (data.error || 'Невідома'));
                }
            })
            .catch(err => alert('Помилка збереження: ' + err.message));
        });
    }

    function escapeHtml(text) {
        if (!text) return '';
        return String(text)
            .replace(/&/g, '&amp;')
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;')
            .replace(/"/g, '&quot;')
            .replace(/'/g, '&#039;');
    }
});

