// Auto-attach CSRF token & unified session headers to mutating requests
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
    const telLight = document.getElementById('telLight');
    const telTemp = document.getElementById('telTemp');
    const telHum = document.getElementById('telHum');
    const telHumFloor1 = document.getElementById('telHumFloor1');
    const telHumFloor2 = document.getElementById('telHumFloor2');
    const telHumBasement = document.getElementById('telHumBasement');
    const telBat = document.getElementById('telBat');
    const telCar = document.getElementById('telCar');
    const sidebarProjBadge = document.getElementById('sidebarProjBadge');
    const sidebarJblBadge = document.getElementById('sidebarJblBadge');

    // Floor Climate Cards in Charts Tab
    const chartCardTemp = document.getElementById('chartCardTemp');
    const chartCardHumF1 = document.getElementById('chartCardHumF1');
    const chartCardTempSub = document.getElementById('chartCardTempSub');
    const badgeFloor1 = document.getElementById('badgeFloor1');

    const chartCardTempF2 = document.getElementById('chartCardTempF2');
    const chartCardHumF2 = document.getElementById('chartCardHumF2');
    const chartCardSubF2 = document.getElementById('chartCardSubF2');
    const badgeFloor2 = document.getElementById('badgeFloor2');

    const chartCardTempFB = document.getElementById('chartCardTempFB');
    const chartCardHumFB = document.getElementById('chartCardHumFB');
    const chartCardSubFB = document.getElementById('chartCardSubFB');
    const badgeBasement = document.getElementById('badgeBasement');

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

    // Radio Elements (Full Page)
    const fullRadioStationsContainer = document.getElementById('fullRadioStationsContainer');
    const fullRadioSearchInput = document.getElementById('fullRadioSearchInput');
    const fullBtnRadioSearch = document.getElementById('fullBtnRadioSearch');
    const fullBtnRadioReset = document.getElementById('fullBtnRadioReset');
    const fullRadioStatusText = document.getElementById('fullRadioStatusText');
    let fullActiveRadioUrl = null;

    // Media Filter & Cleanup Elements
    const filterAllMediaBtn = document.getElementById('filterAllMediaBtn');
    const filterFilesBtn = document.getElementById('filterFilesBtn');
    const filterStreamsBtn = document.getElementById('filterStreamsBtn');
    const cleanupStreamsBtn = document.getElementById('cleanupStreamsBtn');
    let currentMediaFilter = 'all'; // 'all' | 'files' | 'streams'
    let rawMediaList = [];

    // Tab Navigation
    const tabBtns = document.querySelectorAll('.tab-btn');
    const tabPanes = document.querySelectorAll('.tab-pane');

    let ttsEnabled = true;
    let isListening = false;
    let isSpeakingApp = false;
    let isProcessingApp = false;
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
                loadFullRadioStations();
                loadYTMusicPlaylists();
                updateSpeakerStatus();
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

                    // Helper to render telemetry per floor with strict freshness rules
                    const renderFloorUi = (floorObj, defaultName, elTelTemp, elTelHum, elCardTemp, elCardHum, elCardSub, elBadge, cardEl) => {
                        const isInstalled = floorObj && floorObj.installed !== false;
                        const status = floorObj ? (floorObj.status || (floorObj.online ? 'online' : (floorObj.is_stale ? 'stale' : 'offline'))) : 'never_seen';
                        const isOnline = status === 'online' && floorObj && floorObj.current_temperature !== null && floorObj.current_temperature !== undefined;
                        const lastTemp = floorObj ? (floorObj.last_known_temperature ?? floorObj.temperature) : null;
                        const lastHum = floorObj ? (floorObj.last_known_humidity ?? floorObj.humidity) : null;
                        const lastTime = floorObj ? (floorObj.last_updated_time || '--:--') : '--:--';
                        const lastRel = floorObj ? (floorObj.last_updated_relative || '') : '';
                        const srcName = floorObj && floorObj.source_name ? floorObj.source_name : 'BLE';
                        const batStr = '';

                        let tempText = '-- °C';
                        let humText = '-- %';
                        let badgeText = 'Офлайн';
                        let badgeClass = 'floor-badge warning';
                        let subText = 'Очікує даних';
                        let tooltip = defaultName;

                        if (!isInstalled || status === 'not_installed') {
                            tempText = '-- °C';
                            humText = '-- %';
                            badgeText = 'Датчик не встановлено';
                            badgeClass = 'floor-badge';
                            subText = 'Датчик не встановлено';
                            tooltip = `${defaultName}: датчик не встановлено`;
                        } else if (isOnline) {
                            tempText = `${Number(floorObj.current_temperature).toFixed(1)} °C`;
                            humText = (floorObj.current_humidity !== null && floorObj.current_humidity !== undefined)
                                ? `${Number(floorObj.current_humidity).toFixed(0)} %` : '-- %';
                            badgeText = 'Актуально';
                            badgeClass = 'floor-badge active';
                            subText = `Актуально • ${lastTime}`;
                            tooltip = `${defaultName}: Актуально (${srcName}) • Оновлено о ${lastTime}`;
                        } else if (status === 'stale') {
                            tempText = lastTemp !== null ? `${Number(lastTemp).toFixed(1)} °C` : '-- °C';
                            humText = lastHum !== null ? `${Number(lastHum).toFixed(0)} %` : '-- %';
                            badgeText = 'Дані застаріли';
                            badgeClass = 'floor-badge warning';
                            const lastValStr = lastTemp !== null ? ` (ост. ${Number(lastTemp).toFixed(1)} °C)` : '';
                            subText = `Дані застаріли${lastValStr} • ${lastRel || lastTime}`;
                            tooltip = `${defaultName}: Дані застаріли (${srcName}) • Останній вимір: ${lastTemp !== null ? Number(lastTemp).toFixed(1) + ' °C о ' : ''}${lastTime}`;
                        } else if (status === 'offline') {
                            tempText = lastTemp !== null ? `${Number(lastTemp).toFixed(1)} °C` : '-- °C';
                            humText = lastHum !== null ? `${Number(lastHum).toFixed(0)} %` : '-- %';
                            badgeText = 'Офлайн';
                            badgeClass = 'floor-badge warning';
                            const lastValStr = lastTemp !== null ? ` (${Number(lastTemp).toFixed(1)} °C)` : '';
                            subText = `Офлайн — останній вимір ${lastTime}${lastValStr}`;
                            tooltip = `${defaultName}: Офлайн (${srcName}) • Останній вимір: ${lastTime}`;
                        } else {
                            // never_seen
                            tempText = '-- °C';
                            humText = '-- %';
                            badgeText = 'Очікує даних';
                            badgeClass = 'floor-badge';
                            subText = 'Дані ще не надходили';
                            tooltip = `${defaultName}: очікування зв'язку з датчиком`;
                        }

                        if (elTelTemp) {
                            elTelTemp.textContent = tempText;
                            elTelTemp.title = tooltip;
                            elTelTemp.className = isOnline ? 'val-badge active hoverable' : 'val-badge hoverable';
                        }
                        if (elTelHum) {
                            elTelHum.textContent = humText;
                            elTelHum.title = `${defaultName}: вологість ${humText}`;
                            elTelHum.className = isOnline ? 'val-badge active hoverable' : 'val-badge hoverable';
                        }
                        if (elCardTemp) {
                            elCardTemp.textContent = tempText;
                            elCardTemp.title = tooltip;
                        }
                        if (elCardHum) {
                            elCardHum.textContent = humText;
                            elCardHum.title = `${defaultName}: вологість ${humText}`;
                        }
                        if (elCardSub) {
                            elCardSub.textContent = subText;
                        }
                        if (elBadge) {
                            elBadge.textContent = badgeText;
                            elBadge.className = badgeClass;
                        }
                        if (cardEl) {
                            cardEl.classList.toggle('is-stale', status === 'stale');
                        }
                    };

                    const floorCard1 = document.getElementById('floorCard1');
                    const floorCard2 = document.getElementById('floorCard2');
                    const floorCardBasement = document.getElementById('floorCardBasement');

                    renderFloorUi(f1, '1-й поверх (Гараж)', telTemp, telHumFloor1, chartCardTemp, chartCardHumF1, chartCardTempSub, badgeFloor1, floorCard1);
                    renderFloorUi(f2, '2-й поверх', telTempFloor2, telHumFloor2, chartCardTempF2, chartCardHumF2, chartCardSubF2, badgeFloor2, floorCard2);
                    renderFloorUi(fb, 'Підвал', telTempBasement, telHumBasement, chartCardTempFB, chartCardHumFB, chartCardSubFB, badgeBasement, floorCardBasement);

                    // Battery (calculate only from real configured sensors)
                    if (telBat) {
                        const bats = [];
                        if (fb && fb.installed !== false && fb.battery !== null && fb.battery !== undefined) bats.push(fb.battery);
                        if (f2 && f2.installed !== false && f2.battery !== null && f2.battery !== undefined) bats.push(f2.battery);
                        if (bats.length > 0) {
                            telBat.textContent = `🔋 ${Math.min(...bats)}%`;
                            telBat.title = `Заряд батарей: Підвал: ${fb.battery || '--'}%, 2-й поверх: ${f2.battery || '--'}%`;
                        } else {
                            telBat.textContent = `🔋 -- %`;
                            telBat.title = `Немає активних датчиків`;
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
                    const spkName = s.name || 'Bluetooth Колонка';
                    if (sidebarJblBadge) {
                        sidebarJblBadge.textContent = isConnected ? spkName : 'Відключено';
                        sidebarJblBadge.className = isConnected ? 'badge badge-accent' : 'badge';
                    }
                    if (jblOnlineBadge) {
                        jblOnlineBadge.textContent = isConnected ? `● ${spkName} Підключено` : `○ ${spkName} Відключено`;
                        jblOnlineBadge.style.color = isConnected ? 'var(--accent-cyan, #00f0ff)' : 'var(--text-muted, #94a3b8)';
                    }
                    if (jblStatusText) {
                        if (s.playing && s.current_track) {
                            jblStatusText.textContent = `▶ Грає на ${spkName}: ${s.current_track} (${s.volume}%)`;
                        } else {
                            jblStatusText.textContent = isConnected ? `${spkName}: Готово до відтворення (${s.volume}%)` : 'Відключено';
                        }
                    }
                    if (fullRadioStatusText) {
                        if (s.playing && s.current_track) {
                            fullRadioStatusText.textContent = `Трансляція на ${spkName}: ▶ ${s.current_track}`;
                        } else {
                            fullRadioStatusText.textContent = `Трансляція інтернет-радіо на ${spkName}`;
                        }
                    }
                    if (jblConnectBtn) {
                        jblConnectBtn.textContent = isConnected ? '🔌 Відключити' : '🔗 Підключити';
                    }
                    const fullJblNowPlaying = document.getElementById('fullJblNowPlaying');
                    const fullJblVolumeSlider = document.getElementById('fullJblVolumeSlider');
                    const fullJblVolumeVal = document.getElementById('fullJblVolumeVal');
                    const fullSpeakerBtnJxbt = document.getElementById('fullSpeakerBtnJxbt');
                    const fullSpeakerBtnJbl = document.getElementById('fullSpeakerBtnJbl');

                    if (fullJblNowPlaying) {
                        if (s.playing && s.current_track) {
                            fullJblNowPlaying.textContent = s.current_track;
                        } else {
                            fullJblNowPlaying.textContent = isConnected ? 'Готово до відтворення' : 'Відключено';
                        }
                    }
                    if (fullJblVolumeSlider && s.volume !== undefined) {
                        fullJblVolumeSlider.value = s.volume;
                    }
                    if (fullJblVolumeVal && s.volume !== undefined) {
                        fullJblVolumeVal.textContent = s.volume + '%';
                    }
                    if (fullSpeakerBtnJxbt && fullSpeakerBtnJbl) {
                        const curMac = (s.mac || '').toUpperCase();
                        if (curMac === '41:42:62:69:51:9B') {
                            fullSpeakerBtnJxbt.classList.add('active');
                            fullSpeakerBtnJbl.classList.remove('active');
                        } else if (curMac === 'F8:5C:7E:EE:7D:CC') {
                            fullSpeakerBtnJbl.classList.add('active');
                            fullSpeakerBtnJxbt.classList.remove('active');
                        }
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

    const jblNextBtn = document.getElementById('jblNextBtn');
    if (jblNextBtn) {
        jblNextBtn.addEventListener('click', () => {
            fetch('/api/ytmusic/next', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({})
            })
            .then(res => res.json())
            .then(data => {
                appendEntry('system', data.response || 'Наступний трек');
                updateSpeakerStatus();
            })
            .catch(err => appendEntry('system', `Помилка перемикання треку: ${err.message}`));
        });
    }

    const fullSpeakerBtnJxbt = document.getElementById('fullSpeakerBtnJxbt');
    const fullSpeakerBtnJbl = document.getElementById('fullSpeakerBtnJbl');
    function switchFullSpeaker(mac, name) {
        appendEntry('system', `Перемикання аудіо на ${name}...`);
        fetch('/api/speaker/switch', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ mac: mac })
        })
        .then(res => res.json())
        .then(data => {
            appendEntry('system', data.response || `Активна колонка: ${name}`);
            updateSpeakerStatus();
        })
        .catch(err => appendEntry('system', `Помилка перемикання: ${err.message}`));
    }
    if (fullSpeakerBtnJxbt) {
        fullSpeakerBtnJxbt.addEventListener('click', () => {
            switchFullSpeaker('41:42:62:69:51:9B', 'JX-BT (1-й поверх)');
        });
    }
    if (fullSpeakerBtnJbl) {
        fullSpeakerBtnJbl.addEventListener('click', () => {
            switchFullSpeaker('F8:5C:7E:EE:7D:CC', 'JBL Clip 5 (Гараж)');
        });
    }

    const fullJblVolumeSlider = document.getElementById('fullJblVolumeSlider');
    const fullJblVolumeVal = document.getElementById('fullJblVolumeVal');
    if (fullJblVolumeSlider) {
        fullJblVolumeSlider.addEventListener('input', () => {
            if (fullJblVolumeVal) fullJblVolumeVal.textContent = fullJblVolumeSlider.value + '%';
        });
        fullJblVolumeSlider.addEventListener('change', () => {
            const val = parseInt(fullJblVolumeSlider.value, 10);
            fetch('/api/speaker/volume', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ volume: val })
            }).then(updateSpeakerStatus);
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
                    rawMediaList = data.media;
                    renderMediaGrid();
                }
            })
            .catch(() => {
                if (mediaGrid) {
                    mediaGrid.innerHTML = '<div class="media-placeholder">Помилка завантаження медіафайлів</div>';
                }
            });
    }

    function renderMediaGrid() {
        if (!mediaGrid) return;
        const filtered = rawMediaList.filter(file => {
            if (currentMediaFilter === 'files') return !file.is_stream;
            if (currentMediaFilter === 'streams') return file.is_stream;
            return true;
        });

        if (filtered.length === 0) {
            mediaGrid.innerHTML = '<div class="media-placeholder">У цьому розділі немає відеофайлів</div>';
            return;
        }

        mediaGrid.innerHTML = '';
        filtered.forEach(file => {
            const card = document.createElement('div');
            card.className = 'media-card';
            const badgeHtml = file.is_stream
                ? '<span class="media-badge media-badge-stream">Стрім</span>'
                : '<span class="media-badge media-badge-file">Файл</span>';
            const icon = file.is_stream ? '⚡' : '🎬';

            card.innerHTML = `
                <div class="media-card-top">
                    <div class="media-card-icon">${icon}</div>
                    <div class="media-card-info">
                        <div style="display: flex; align-items: center; justify-content: space-between; gap: 6px;">
                            <div class="media-card-title" title="${file.title}">${file.title}</div>
                            ${badgeHtml}
                        </div>
                        <div class="media-card-meta">${file.size_mb} MB • ${file.modified}</div>
                    </div>
                </div>
                <div style="display: flex; gap: 6px; margin-top: 4px;">
                    <button class="media-card-btn" data-filename="${file.filename}" style="flex: 1;">
                        <span>▶ На проектор</span>
                    </button>
                    <button class="btn-ctrl btn-danger-sm btn-delete-media" data-filename="${file.filename}" title="Видалити файл" aria-label="Видалити файл ${file.filename}" style="padding: 0 10px;">
                        <span>🗑️</span>
                    </button>

                </div>
            `;
            mediaGrid.appendChild(card);
        });

        // Attach click handlers to play buttons
        mediaGrid.querySelectorAll('.media-card-btn').forEach(btn => {
            btn.addEventListener('click', () => {
                const fname = btn.getAttribute('data-filename');
                playMedia(fname);
            });
        });

        // Attach click handlers to delete buttons
        mediaGrid.querySelectorAll('.btn-delete-media').forEach(btn => {
            btn.addEventListener('click', () => {
                const fname = btn.getAttribute('data-filename');
                if (confirm(`Видалити "${fname}"?`)) {
                    fetch('/api/media/delete', {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({ filename: fname })
                    })
                    .then(res => res.json())
                    .then(data => {
                        appendEntry('system', data.response || 'Файл видалено');
                        loadMediaList();
                    })
                    .catch(err => appendEntry('system', `Помилка: ${err.message}`));
                }
            });
        });
    }

    // Media Filter Tab Buttons
    if (filterAllMediaBtn) {
        filterAllMediaBtn.addEventListener('click', () => {
            currentMediaFilter = 'all';
            document.querySelectorAll('.media-filter-tabs .btn-sm').forEach(b => b.classList.remove('active'));
            filterAllMediaBtn.classList.add('active');
            renderMediaGrid();
        });
    }

    if (filterFilesBtn) {
        filterFilesBtn.addEventListener('click', () => {
            currentMediaFilter = 'files';
            document.querySelectorAll('.media-filter-tabs .btn-sm').forEach(b => b.classList.remove('active'));
            filterFilesBtn.classList.add('active');
            renderMediaGrid();
        });
    }

    if (filterStreamsBtn) {
        filterStreamsBtn.addEventListener('click', () => {
            currentMediaFilter = 'streams';
            document.querySelectorAll('.media-filter-tabs .btn-sm').forEach(b => b.classList.remove('active'));
            filterStreamsBtn.classList.add('active');
            renderMediaGrid();
        });
    }

    if (cleanupStreamsBtn) {
        cleanupStreamsBtn.addEventListener('click', () => {
            if (confirm('Видалити всі тимчасові кешовані стріми YouTube? Постійні медіафайли залишаться.')) {
                cleanupStreamsBtn.textContent = 'Очищення...';
                fetch('/api/media/cleanup', { method: 'POST' })
                    .then(res => res.json())
                    .then(data => {
                        appendEntry('system', `🧹 ${data.response || 'Кеш стрімів очищено'}`);
                        cleanupStreamsBtn.textContent = '🧹 Очистити стріми';
                        loadMediaList();
                    })
                    .catch(err => {
                        cleanupStreamsBtn.textContent = '🧹 Очистити стріми';
                        appendEntry('system', `Помилка очищення: ${err.message}`);
                    });
            }
        });
    }

    // --- INTERNET RADIO (FULL PAGE) ---
    function loadFullRadioStations(query = '') {
        if (!fullRadioStationsContainer) return;
        fullRadioStationsContainer.innerHTML = '<div style="font-size: 12px; color: var(--text-muted); padding: 6px;">⏳ Завантаження станцій...</div>';
        const url = query ? `/api/radio/search?q=${encodeURIComponent(query)}` : '/api/radio/stations?limit=24';

        fetch(url)
            .then(res => res.json())
            .then(data => {
                if (data.success && data.stations && data.stations.length > 0) {
                    renderFullRadioStations(data.stations);
                } else {
                    fullRadioStationsContainer.innerHTML = '<div style="font-size: 12px; color: var(--text-muted); padding: 6px;">Станцій не знайдено</div>';
                }
            })
            .catch(() => {
                fullRadioStationsContainer.innerHTML = '<div style="font-size: 12px; color: #ff0055; padding: 6px;">Помилка завантаження станцій</div>';
            });
    }

    function renderFullRadioStations(stations) {
        if (!fullRadioStationsContainer) return;
        fullRadioStationsContainer.innerHTML = '';
        stations.forEach(st => {
            const chip = document.createElement('div');
            chip.className = 'radio-chip';
            if (fullActiveRadioUrl === st.url) {
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

            chip.addEventListener('click', () => {
                fullActiveRadioUrl = st.url;
                document.querySelectorAll('#fullRadioStationsContainer .radio-chip').forEach(c => c.classList.remove('active'));
                chip.classList.add('active');

                if (fullRadioStatusText) fullRadioStatusText.textContent = `▶ Грає: ${st.name}`;
                if (jblStatusText) jblStatusText.textContent = `▶ Радіо: ${st.name}`;
                appendEntry('system', `📻 Запуск трансляції радіо "${st.name}" на колонку JBL...`);

                fetch('/api/radio/play', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ url: st.url, name: st.name })
                })
                .then(res => res.json())
                .then(data => {
                    appendEntry('system', data.response || `Трансляція ${st.name} активна`);
                    updateSpeakerStatus();
                })
                .catch(err => {
                    appendEntry('system', `Помилка трансляції радіо: ${err.message}`);
                });
            });

            fullRadioStationsContainer.appendChild(chip);
        });
    }

    if (fullBtnRadioSearch && fullRadioSearchInput) {
        fullBtnRadioSearch.addEventListener('click', () => {
            const q = fullRadioSearchInput.value.trim();
            loadFullRadioStations(q);
        });

        fullRadioSearchInput.addEventListener('keydown', (e) => {
            if (e.key === 'Enter') {
                e.preventDefault();
                const q = fullRadioSearchInput.value.trim();
                loadFullRadioStations(q);
            }
        });
    }

    if (fullBtnRadioReset) {
        fullBtnRadioReset.addEventListener('click', () => {
            if (fullRadioSearchInput) fullRadioSearchInput.value = '';
            loadFullRadioStations('');
        });
    }

    // --- MEDIA HUB SUB-TABS SWITCHER ---
    document.querySelectorAll('.media-subtab-btn').forEach(btn => {
        btn.addEventListener('click', () => {
            const targetId = btn.getAttribute('data-target');
            document.querySelectorAll('.media-subtab-btn').forEach(b => {
                b.classList.remove('active');
                b.setAttribute('aria-selected', 'false');
            });
            document.querySelectorAll('.media-subtab-pane').forEach(p => p.classList.remove('active'));
            btn.classList.add('active');
            btn.setAttribute('aria-selected', 'true');
            const targetPane = document.getElementById(targetId);
            if (targetPane) targetPane.classList.add('active');
        });
    });

    // --- YOUTUBE MUSIC CONTROLS (WEB PANEL) ---
    const ytPlaylistsContainer = document.getElementById('ytPlaylistsContainer');
    const ytPlaylistsCountBadge = document.getElementById('ytPlaylistsCountBadge');
    const ytLikedCountBadge = document.getElementById('ytLikedCountBadge');
    const ytPlaylistsSearch = document.getElementById('ytPlaylistsSearch');
    const btnYtRefreshPlaylists = document.getElementById('btnYtRefreshPlaylists');

    const btnYtPlayLiked = document.getElementById('btnYtPlayLiked');
    const btnYtShuffleLiked = document.getElementById('btnYtShuffleLiked');
    const btnYtBrowseLiked = document.getElementById('btnYtBrowseLiked');

    const ytTrackViewerCard = document.getElementById('ytTrackViewerCard');
    const ytActivePlaylistTitle = document.getElementById('ytActivePlaylistTitle');
    const ytActivePlaylistCount = document.getElementById('ytActivePlaylistCount');
    const btnYtCloseTracks = document.getElementById('btnYtCloseTracks');
    const btnYtPlayCurrentAll = document.getElementById('btnYtPlayCurrentAll');
    const btnYtShuffleCurrentAll = document.getElementById('btnYtShuffleCurrentAll');
    const ytTrackSearchInput = document.getElementById('ytTrackSearchInput');
    const ytTracksListContainer = document.getElementById('ytTracksListContainer');

    let ytPlaylistsCache = [];
    let ytActivePlaylistData = { id: 'LM', title: 'Улюблені пісні', tracks: [] };

    function loadYTMusicPlaylists(forceRefresh = false) {
        if (!ytPlaylistsContainer) return;
        ytPlaylistsContainer.innerHTML = '<div style="grid-column: 1 / -1; font-size: 13px; color: var(--text-muted); padding: 16px; text-align: center;">⏳ Оновлення списків YouTube Music...</div>';

        fetch(`/api/ytmusic/playlists?refresh=${forceRefresh ? 1 : 0}`)
            .then(res => res.json())
            .then(data => {
                if (data.success && data.playlists) {
                    ytPlaylistsCache = data.playlists;
                    // Find Liked Music count
                    const likedPl = data.playlists.find(p => p.is_liked || p.id === 'LM');
                    if (likedPl && ytLikedCountBadge) {
                        ytLikedCountBadge.textContent = `${likedPl.track_count || 116}+`;
                    }
                    if (ytPlaylistsCountBadge) {
                        const customCount = data.playlists.filter(p => !p.is_liked && p.id !== 'LM').length;
                        ytPlaylistsCountBadge.textContent = `${customCount} списків`;
                    }
                    renderYTPlaylists(ytPlaylistsCache, ytPlaylistsSearch ? ytPlaylistsSearch.value.trim() : '');
                } else {
                    ytPlaylistsContainer.innerHTML = '<div style="grid-column: 1 / -1; font-size: 13px; color: var(--text-muted); padding: 16px; text-align: center;">Плейлистів не знайдено</div>';
                }
            })
            .catch(err => {
                ytPlaylistsContainer.innerHTML = `<div style="grid-column: 1 / -1; font-size: 13px; color: #ff0055; padding: 16px; text-align: center;">Помилка завантаження: ${err.message}</div>`;
            });
    }

    function renderYTPlaylists(playlists, filterText = '') {
        if (!ytPlaylistsContainer) return;
        ytPlaylistsContainer.innerHTML = '';

        const customPlaylists = playlists.filter(p => !p.is_liked && p.id !== 'LM');
        const q = filterText.toLowerCase();
        const filtered = customPlaylists.filter(p => p.title.toLowerCase().includes(q));

        if (filtered.length === 0) {
            ytPlaylistsContainer.innerHTML = '<div style="grid-column: 1 / -1; font-size: 13px; color: var(--text-muted); padding: 16px; text-align: center;">Плейлистів за запитом не знайдено</div>';
            return;
        }

        filtered.forEach(pl => {
            const card = document.createElement('div');
            card.className = 'yt-playlist-card';

            const countText = pl.track_count ? `${pl.track_count} треків` : 'Плейлист';

            card.innerHTML = `
                <div style="display: flex; justify-content: space-between; align-items: flex-start; gap: 8px;">
                    <div class="yt-pl-title">
                        <span>🎵</span>
                        <span title="${pl.title}">${pl.title}</span>
                    </div>
                    <span class="yt-pl-count">${countText}</span>
                </div>
                <div class="yt-pl-actions">
                    <button type="button" class="btn-ctrl btn-play-pl" aria-label="Відтворити плейлист">▶ Слухати</button>
                    <button type="button" class="btn-ctrl btn-shuffle-pl" aria-label="Відтворити у випадковому порядку">🔀 Shuffle</button>
                    <button type="button" class="btn-ctrl btn-browse-pl" style="color: var(--accent-cyan); border-color: rgba(0,240,255,0.3);" aria-label="Переглянути треки плейлиста">☰ Треки</button>
                </div>
            `;

            card.querySelector('.btn-play-pl').addEventListener('click', (e) => {
                e.stopPropagation();
                playYTPlaylist(pl.id, false, pl.title);
            });

            card.querySelector('.btn-shuffle-pl').addEventListener('click', (e) => {
                e.stopPropagation();
                playYTPlaylist(pl.id, true, pl.title);
            });

            card.querySelector('.btn-browse-pl').addEventListener('click', (e) => {
                e.stopPropagation();
                openYTPlaylistTracks(pl.id, pl.title);
            });

            card.addEventListener('click', () => {
                openYTPlaylistTracks(pl.id, pl.title);
            });

            ytPlaylistsContainer.appendChild(card);
        });
    }

    function playYTPlaylist(playlistId, shuffle = false, playlistTitle = '') {
        const title = playlistTitle || (playlistId === 'LM' ? 'Улюблені пісні' : 'Плейлист');
        appendEntry('system', `🎵 Запуск ${shuffle ? 'випадкового порядку ' : ''}з '${title}' на Bluetooth-колонку...`);

        fetch('/api/ytmusic/play', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                playlist_id: playlistId,
                shuffle: shuffle
            })
        })
        .then(res => res.json())
        .then(data => {
            appendEntry('system', data.response || `Відтворення '${title}' запущено`);
            updateSpeakerStatus();
        })
        .catch(err => {
            appendEntry('system', `Помилка запуску плейлиста: ${err.message}`);
        });
    }

    function openYTPlaylistTracks(playlistId, playlistTitle) {
        if (!ytTrackViewerCard || !ytTracksListContainer) return;

        ytActivePlaylistData.id = playlistId;
        ytActivePlaylistData.title = playlistTitle;
        ytActivePlaylistData.tracks = [];

        ytTrackViewerCard.style.display = 'block';
        if (ytActivePlaylistTitle) ytActivePlaylistTitle.textContent = playlistTitle;
        if (ytActivePlaylistCount) ytActivePlaylistCount.textContent = 'Завантаження пісень...';
        ytTracksListContainer.innerHTML = '<div style="font-size: 12px; color: var(--text-muted); padding: 14px; text-align: center;">⏳ Отримання списку пісень...</div>';

        ytTrackViewerCard.scrollIntoView({ behavior: 'smooth', block: 'nearest' });

        fetch(`/api/ytmusic/playlist/${playlistId}/tracks`)
            .then(res => res.json())
            .then(data => {
                if (data.success && data.tracks && data.tracks.length > 0) {
                    ytActivePlaylistData.tracks = data.tracks;
                    if (ytActivePlaylistCount) ytActivePlaylistCount.textContent = `${data.tracks.length} пісень`;
                    renderYTTracks(data.tracks);
                } else {
                    ytTracksListContainer.innerHTML = '<div style="font-size: 12px; color: var(--text-muted); padding: 14px; text-align: center;">Не знайдено пісень у цьому плейлисті</div>';
                    if (ytActivePlaylistCount) ytActivePlaylistCount.textContent = '0 пісень';
                }
            })
            .catch(err => {
                ytTracksListContainer.innerHTML = `<div style="font-size: 12px; color: #ff0055; padding: 14px; text-align: center;">Помилка завантаження пісень: ${err.message}</div>`;
            });
    }

    function formatDuration(sec) {
        if (!sec || isNaN(sec)) return '';
        const m = Math.floor(sec / 60);
        const s = Math.floor(sec % 60);
        return `${m}:${s < 10 ? '0' : ''}${s}`;
    }

    function renderYTTracks(tracks, filterText = '') {
        if (!ytTracksListContainer) return;
        ytTracksListContainer.innerHTML = '';

        const q = filterText.toLowerCase();
        const filtered = tracks.filter(t => 
            t.title.toLowerCase().includes(q) || 
            (t.uploader && t.uploader.toLowerCase().includes(q))
        );

        if (filtered.length === 0) {
            ytTracksListContainer.innerHTML = '<div style="font-size: 12px; color: var(--text-muted); padding: 12px; text-align: center;">Пісень за запитом не знайдено</div>';
            return;
        }

        filtered.forEach((tr, index) => {
            const row = document.createElement('div');
            row.className = 'yt-track-row';

            const durStr = formatDuration(tr.duration);

            row.innerHTML = `
                <div class="yt-track-main">
                    <span class="yt-track-idx">${index + 1}</span>
                    <button type="button" class="yt-track-playbtn" title="Відтворити трек" aria-label="Відтворити ${tr.title}">▶</button>
                    <div class="yt-track-meta">
                        <span class="yt-track-title" title="${tr.title}">${tr.title}</span>
                        ${tr.uploader ? `<span class="yt-track-artist">${tr.uploader}</span>` : ''}
                    </div>
                </div>
                ${durStr ? `<span class="yt-track-time">${durStr}</span>` : ''}
            `;

            row.addEventListener('click', () => {
                playYTTrack(ytActivePlaylistData.id, tr.id, tr.title, tr.uploader);
                document.querySelectorAll('.yt-track-row').forEach(r => r.classList.remove('playing'));
                row.classList.add('playing');
            });

            ytTracksListContainer.appendChild(row);
        });
    }

    function playYTTrack(playlistId, trackId, trackTitle, uploader) {
        appendEntry('system', `▶ Запуск треку '${trackTitle}' на колонці...`);

        fetch('/api/ytmusic/play', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                playlist_id: playlistId,
                track_id: trackId,
                track_title: trackTitle,
                uploader: uploader,
                shuffle: false
            })
        })
        .then(res => res.json())
        .then(data => {
            appendEntry('system', data.response || `Грає: ${trackTitle}`);
            updateSpeakerStatus();
        })
        .catch(err => {
            appendEntry('system', `Помилка запуску треку: ${err.message}`);
        });
    }

    if (btnYtPlayLiked) {
        btnYtPlayLiked.addEventListener('click', () => {
            playYTPlaylist('LM', false, 'Улюблені пісні');
        });
    }

    if (btnYtShuffleLiked) {
        btnYtShuffleLiked.addEventListener('click', () => {
            playYTPlaylist('LM', true, 'Улюблені пісні');
        });
    }

    if (btnYtBrowseLiked) {
        btnYtBrowseLiked.addEventListener('click', () => {
            openYTPlaylistTracks('LM', 'Улюблені пісні (Liked Music)');
        });
    }

    if (btnYtRefreshPlaylists) {
        btnYtRefreshPlaylists.addEventListener('click', () => {
            loadYTMusicPlaylists(true);
        });
    }

    if (ytPlaylistsSearch) {
        ytPlaylistsSearch.addEventListener('input', () => {
            renderYTPlaylists(ytPlaylistsCache, ytPlaylistsSearch.value.trim());
        });
    }

    if (btnYtCloseTracks && ytTrackViewerCard) {
        btnYtCloseTracks.addEventListener('click', () => {
            ytTrackViewerCard.style.display = 'none';
        });
    }

    if (btnYtPlayCurrentAll) {
        btnYtPlayCurrentAll.addEventListener('click', () => {
            playYTPlaylist(ytActivePlaylistData.id, false, ytActivePlaylistData.title);
        });
    }

    if (btnYtShuffleCurrentAll) {
        btnYtShuffleCurrentAll.addEventListener('click', () => {
            playYTPlaylist(ytActivePlaylistData.id, true, ytActivePlaylistData.title);
        });
    }

    if (ytTrackSearchInput) {
        ytTrackSearchInput.addEventListener('input', () => {
            renderYTTracks(ytActivePlaylistData.tracks, ytTrackSearchInput.value.trim());
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
    loadFullRadioStations();
    loadMediaList();
    setInterval(checkHealth, 15000);
    setInterval(updateTelemetry, 4000);
    setInterval(updateProjectorStatus, 20000);
    setInterval(() => {
        if (sessionStorage.getItem('sg_admin_auth') === 'true' && document.getElementById('adminTab')?.classList.contains('active')) {
            loadPresenceData();
            loadRfStatus();
        }
    }, 5000);
    // Auto-update climate chart every 30 minutes (1800000 ms)
    setInterval(() => {
        if (document.getElementById('chartsTab')?.classList.contains('active')) {
            initOrUpdateChart();
        }
    }, 1800000);

    // --- FORMAT TIME ---
    function getCurrentTime() {
        return new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
    }

    // --- TEXT TO SPEECH (TTS) ---
    function cleanSpeechText(text) {
        if (!text) return '';
        let clean = text
            .replace(/https?:\/\/\S+/g, '')
            .replace(/\p{Extended_Pictographic}/gu, '')
            .replace(/[\u{1F300}-\u{1FAFF}\u{2600}-\u{27BF}\u{FE00}-\u{FE0F}\u{1F900}-\u{1F9FF}\u{200D}]/gu, '')
            .replace(/[*_#`~[\]()]/g, ' ')
            // Strip single and double quotes (prevents staccato robotic pauses in neural TTS)
            .replace(/['"«»“”]/g, '')
            .replace(/(\d+(?:[.,]\d+)?)\s*°C/g, '$1 градусів')
            .replace(/°C/g, ' градусів')
            .replace(/(\d+(?:[.,]\d+)?)\s*%/g, '$1 відсотків')
            .replace(/%/g, ' відсотків')
            .replace(/1-й\s*поверх/gi, 'перший поверх')
            .replace(/2-й\s*поверх/gi, 'другий поверх')
            .replace(/1-му\s*поверсі/gi, 'першому поверсі')
            .replace(/2-му\s*поверсі/gi, 'другому поверсі')
            .replace(/на\s+музика\s+(?:1-й|перший|1)\s+поверх/gi, 'на першому поверсі')
            .replace(/на\s+музика\s+1/gi, 'на першому поверсі')
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

    let cachedUkVoiceApp = null;
    function getUkrainianVoiceApp() {
        if (!('speechSynthesis' in window)) return null;
        const voices = window.speechSynthesis.getVoices() || [];
        if (!voices || voices.length === 0) return null;
        return voices.find(v => {
            const lang = (v.lang || '').toLowerCase().replace(/_/g, '-');
            const name = (v.name || '').toLowerCase();
            const isEnglish = lang.startsWith('en') || name.includes('english') || name.includes('british') || name.includes('united kingdom');
            if (isEnglish) return false;
            return lang === 'uk' || lang.startsWith('uk-') || name.includes('ukrain') || name.includes('україн');
        }) || null;
    }

    let currentTtsAudioApp = null;
    let currentTtsUrlApp = null;

    function stopTtsPlaybackApp() {
        if (currentTtsAudioApp) {
            try {
                currentTtsAudioApp.pause();
                currentTtsAudioApp.currentTime = 0;
            } catch (_) {}
            currentTtsAudioApp = null;
        }
        if (currentTtsUrlApp) {
            try { URL.revokeObjectURL(currentTtsUrlApp); } catch (_) {}
            currentTtsUrlApp = null;
        }
        if ('speechSynthesis' in window) {
            try { window.speechSynthesis.cancel(); } catch (_) {}
        }
        isSpeakingApp = false;
    }

    function playBrowserSpeechSynthesisApp(clean, onEnded) {
        if (!('speechSynthesis' in window)) {
            if (typeof onEnded === 'function') onEnded();
            return;
        }
        try {
            window.speechSynthesis.cancel();
            const utt = new SpeechSynthesisUtterance(clean);
            utt.lang = 'uk-UA';
            const ukVoice = getUkrainianVoiceApp();
            if (ukVoice) utt.voice = ukVoice;
            utt.onend = () => {
                if (typeof onEnded === 'function') onEnded();
            };
            utt.onerror = () => {
                if (typeof onEnded === 'function') onEnded();
            };
            window.speechSynthesis.speak(utt);
        } catch (e) {
            console.warn('Browser speechSynthesis error:', e);
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

        // Система починає говорити: вимикаємо розпізнавання
        isSpeakingApp = true;
        stopListening();

        if ('speechSynthesis' in window) {
            try { window.speechSynthesis.cancel(); } catch (_) {}
        }

        if (currentTtsAudioApp) {
            try {
                currentTtsAudioApp.pause();
                currentTtsAudioApp.currentTime = 0;
            } catch (_) {}
            currentTtsAudioApp = null;
        }
        if (currentTtsUrlApp) {
            try { URL.revokeObjectURL(currentTtsUrlApp); } catch (_) {}
            currentTtsUrlApp = null;
        }

        let endedCalled = false;
        const fireEnded = () => {
            if (endedCalled) return;
            endedCalled = true;
            isSpeakingApp = false;
            if (currentTtsUrlApp) {
                try { URL.revokeObjectURL(currentTtsUrlApp); } catch (_) {}
                currentTtsUrlApp = null;
            }
            currentTtsAudioApp = null;
            if (typeof onEnded === 'function') onEnded();
        };

        const ttsUrl = '/api/voice/tts?text=' + encodeURIComponent(clean);
        fetch(ttsUrl)
            .then(res => {
                if (!res.ok) {
                    throw new Error(`Server TTS HTTP ${res.status}`);
                }
                const provider = res.headers.get('X-TTS-Provider') || 'server';
                const isFallback = res.headers.get('X-TTS-Fallback') === 'true';
                if (isFallback) {
                    console.info(`[TTS] Використано серверний fallback: ${provider}`);
                }
                return res.blob();
            })
            .then(blob => {
                if (!blob || blob.size === 0) {
                    throw new Error('Отримано порожнє аудіо від сервера');
                }
                currentTtsUrlApp = URL.createObjectURL(blob);
                currentTtsAudioApp = new Audio(currentTtsUrlApp);
                currentTtsAudioApp.onended = fireEnded;
                currentTtsAudioApp.onerror = () => {
                    console.warn('Audio playback error, fallback to browser synthesis');
                    appendEntry('system', '⚠️ Резервне озвучення: браузерний синтез (Web Speech API)');
                    playBrowserSpeechSynthesisApp(clean, fireEnded);
                };
                return currentTtsAudioApp.play();
            })
            .catch(err => {
                console.warn('[TTS] Серверний синтез недоступний:', err.message);
                appendEntry('system', '⚠️ Серверний TTS недоступний. Задіяно резервний браузерний синтез (Web Speech API)');
                if ('speechSynthesis' in window) {
                    playBrowserSpeechSynthesisApp(clean, fireEnded);
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

    // --- STRIP ECHO & WAKE PREFIXES ---
    const PROMPT_ECHO_REGEX_APP = /^(?:що\s*(?:тобі|вам)?\s*(?:потрібно|треба)|що\s*(?:потрібно|треба)|потрібно|треба|слухаю|я\s*слухаю)\s*[!?.]*$/i;

    function isPurePromptEchoApp(text) {
        if (!text || !text.trim()) return true;
        return PROMPT_ECHO_REGEX_APP.test(text.trim().toLowerCase());
    }

    function stripEchoAndWakePrefixApp(text) {
        if (!text || !text.trim()) return '';
        let clean = text.trim();
        clean = clean.replace(/^(?:(?:альо|ало|алло|але|оле|ольо)\s*[, -]?\s*гараж(?:у)?|гараж)\s*[,:;!?-]*\s*/i, '');
        clean = clean.replace(/^(?:що\s*(?:тобі|вам)?\s*(?:потрібно|треба)|слухаю|я\s*слухаю)\s*[,:;!?-]*\s*/i, '');
        return clean.trim();
    }

    // --- SPEECH RECOGNITION (STT) ---
    const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;

    function createRecognitionInstance() {
        if (!SpeechRecognition) return null;
        try {
            const inst = new SpeechRecognition();
            inst.continuous = false;
            inst.interimResults = false;
            inst.lang = 'uk-UA';

            inst.onstart = () => {
                if (isSpeakingApp || isProcessingApp) {
                    stopListening();
                    return;
                }
                isListening = true;
                if (voiceBtn) voiceBtn.classList.add('listening');
                if (voiceListeningBar) voiceListeningBar.style.display = 'flex';
                if (voiceHint) {
                    voiceHint.textContent = '🎙️ Слухаю... Говоріть команду';
                    voiceHint.style.color = '';
                }
            };

            inst.onresult = (event) => {
                const transcript = (event.results && event.results[0] && event.results[0][0])
                    ? event.results[0][0].transcript.trim()
                    : '';
                stopListening();
                if (transcript) {
                    if (isPurePromptEchoApp(transcript)) {
                        console.warn('🔇 [Anti-Loop App] Проігноровано луну запиту помічника:', transcript);
                        return;
                    }
                    const clean = stripEchoAndWakePrefixApp(transcript);
                    if (!clean || isPurePromptEchoApp(clean)) {
                        return;
                    }
                    if (commandInput) commandInput.value = clean;
                    if (voiceHint) {
                        voiceHint.textContent = `✅ Розпізнано: "${clean}"`;
                        voiceHint.style.color = '#10b981';
                    }
                    setTimeout(() => {
                        sendCommand(clean);
                    }, 250);
                }
            };

            inst.onerror = (event) => {
                console.warn('Speech recognition error:', event.error);
                isListening = false;
                if (voiceBtn) voiceBtn.classList.remove('listening');

                let errMsg = '⚠️ Помилка розпізнавання голосу';
                if (event.error === 'not-allowed') {
                    errMsg = '⚠️ Доступ до мікрофона заблоковано в браузері. Натисніть на значок налаштувань ліворуч від адреси сайту та дозвольте мікрофон.';
                    if (navigator.mediaDevices && navigator.mediaDevices.getUserMedia) {
                        navigator.mediaDevices.getUserMedia({ audio: true }).catch(() => {});
                    }
                } else if (event.error === 'network') {
                    errMsg = '⚠️ Збій підключення до служби розпізнавання Google Speech API. Перевірте інтернет або введіть команду текстом.';
                } else if (event.error === 'no-speech') {
                    errMsg = '🔇 Голос не розпізнано. Спробуйте ще раз, говорячи чіткіше.';
                } else if (event.error === 'audio-capture') {
                    errMsg = '⚠️ Не вдалося захопити аудіо з мікрофона. Перевірте, чи не зайнятий мікрофон іншою програмою.';
                } else {
                    errMsg = `⚠️ Помилка розпізнавання: ${event.error}`;
                }

                if (voiceHint) {
                    voiceHint.textContent = errMsg;
                    voiceHint.style.color = '#ef4444';
                }
                if (voiceListeningBar) {
                    voiceListeningBar.style.display = 'flex';
                    setTimeout(() => {
                        if (!isListening && voiceListeningBar) {
                            voiceListeningBar.style.display = 'none';
                            if (voiceHint) voiceHint.style.color = '';
                        }
                    }, 6000);
                }
                appendEntry('system', errMsg);
            };

            inst.onend = () => {
                if (isListening) {
                    stopListening();
                }
            };

            return inst;
        } catch (e) {
            console.error('Failed to create SpeechRecognition instance:', e);
            return null;
        }
    }

    if (!SpeechRecognition && voiceBtn) {
        voiceBtn.style.opacity = '0.5';
        voiceBtn.title = 'Голосовий ввід не підтримується цим браузером';
    }

    function toggleListening() {
        if (!SpeechRecognition) {
            const warn = '⚠️ Голосовий ввід Web Speech API не підтримується у цьому браузері. Рекомендовано Google Chrome або Microsoft Edge.';
            appendEntry('system', warn);
            alert(warn);
            return;
        }

        if (isSpeakingApp || isProcessingApp) {
            console.log('🔇 Мікрофон тимчасово заблоковано: система зайнята озвученням або обробкою.');
            return;
        }

        if (isListening) {
            if (recognition) {
                try { recognition.stop(); } catch (_) {}
            }
            stopListening();
            return;
        }

        // Immediate visual feedback on click
        isListening = true;
        if (voiceBtn) voiceBtn.classList.add('listening');
        if (voiceListeningBar) voiceListeningBar.style.display = 'flex';
        if (voiceHint) {
            voiceHint.textContent = '🎙️ Підключення мікрофона... Говоріть команду';
            voiceHint.style.color = '';
        }

        try {
            if (recognition) {
                try { recognition.abort(); } catch (_) {}
            }
            recognition = createRecognitionInstance();
            if (!recognition) {
                throw new Error('Не вдалося ініціалізувати компонент розпізнавання');
            }
            recognition.start();
        } catch (e) {
            console.warn('Recognition start exception:', e);
            isListening = false;
            if (voiceBtn) voiceBtn.classList.remove('listening');
            const errText = `⚠️ Не вдалося запустити мікрофон: ${e.message || e}`;
            if (voiceHint) {
                voiceHint.textContent = errText;
                voiceHint.style.color = '#ef4444';
            }
            appendEntry('system', errText);
            setTimeout(() => {
                if (!isListening && voiceListeningBar) {
                    voiceListeningBar.style.display = 'none';
                    if (voiceHint) voiceHint.style.color = '';
                }
            }, 5000);
        }
    }

    function stopListening() {
        isListening = false;
        if (voiceBtn) voiceBtn.classList.remove('listening');
        if (voiceListeningBar) voiceListeningBar.style.display = 'none';
        if (voiceHint) voiceHint.style.color = '';
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
                stopTtsPlaybackApp();
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
        if (!cmdText || isPurePromptEchoApp(cmdText)) return;
        let command = stripEchoAndWakePrefixApp(cmdText || '');
        if (!command || isPurePromptEchoApp(command)) return;

        isProcessingApp = true;
        stopListening();

        appendEntry('user', command);
        if (commandInput) {
            commandInput.value = '';
        }

        setLoading(true);

        let webSessionId = sessionStorage.getItem('sg_session_id');
        const reqPayload = { command: command };
        if (webSessionId) {
            reqPayload.session_id = webSessionId;
        }

        fetch('/command', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify(reqPayload)
        })
        .then(response => {
            if (!response.ok) {
                if (response.status === 403) {
                    sessionStorage.removeItem('sg_session_id');
                }
                return response.json().then(errData => {
                    throw new Error(errData.response || `HTTP Error ${response.status}`);
                });
            }
            return response.json();
        })
        .then(data => {
            if (data.session_id) {
                sessionStorage.setItem('sg_session_id', data.session_id);
            }
            if (data.success) {
                const aiResp = (data.response || '').trim();
                if (!aiResp || data.ignored) {
                    isProcessingApp = false;
                    return;
                }
                appendEntry('ai', aiResp);
                const isFollowUpPrompt = /(?:потрібно|треба|слухаю|що\s*хочете|яка\s*команда)/i.test(aiResp);
                speakText(aiResp, () => {
                    isProcessingApp = false;
                    if (isFollowUpPrompt && recognition) {
                        setTimeout(() => {
                            try {
                                if (!isListening && !isSpeakingApp && !isProcessingApp) {
                                    if (voiceHint) voiceHint.textContent = '🎙️ Слухаю команду... Назвіть дію';
                                    toggleListening();
                                }
                            } catch (_) {}
                        }, 750);
                    }
                });
                updateTelemetry();
            } else {
                isProcessingApp = false;
                appendEntry('system', `Помилка: ${data.response || 'Невідома помилка'}`);
            }
        })
        .catch(err => {
            isProcessingApp = false;
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
    const devEditId = document.getElementById('devEditId');
    const devName = document.getElementById('devName');
    const devRole = document.getElementById('devRole');
    const devType = document.getElementById('devType');
    const devModel = document.getElementById('devModel');
    const devClassicMac = document.getElementById('devClassicMac');
    const devBleMac = document.getElementById('devBleMac');
    const devAbsenceMsg = document.getElementById('devAbsenceMsg');
    const devTelegramChatId = document.getElementById('devTelegramChatId');
    const devNotifyOwner = document.getElementById('devNotifyOwner');
    const btnCancelEdit = document.getElementById('btnCancelEdit');
    const formSectionTitle = document.getElementById('formSectionTitle');
    const btnSaveDeviceText = document.getElementById('btnSaveDeviceText');

    const statTotalGuests = document.getElementById('statTotalGuests');
    const statVisitsToday = document.getElementById('statVisitsToday');
    const statPresentNow = document.getElementById('statPresentNow');

    const devicesTableBody = document.getElementById('devicesTableBody');
    const logTableBody = document.getElementById('logTableBody');
    const btnRefreshLog = document.getElementById('btnRefreshLog');

    function checkAdminState() {
        const isAuth = sessionStorage.getItem('sg_admin_auth') === 'true';
        if (!sessionStorage.getItem('sg_csrf_token')) {
            fetch('/api/csrf')
                .then(res => res.json())
                .then(d => {
                    if (d && d.csrf_token) sessionStorage.setItem('sg_csrf_token', d.csrf_token);
                })
                .catch(() => {});
        }
        if (isAuth) {
            if (adminAuthSection) adminAuthSection.style.display = 'none';
            if (adminContentSection) adminContentSection.style.display = 'block';
            loadPresenceData();
            loadDevicesData();
            loadLogData();
            loadRfStatus();
            loadRelays();
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
                    if (data.csrf_token) {
                        sessionStorage.setItem('sg_csrf_token', data.csrf_token);
                    }
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
            fetch('/api/admin/logout', { method: 'POST' }).finally(() => {
                sessionStorage.removeItem('sg_admin_auth');
                sessionStorage.removeItem('sg_csrf_token');
                checkAdminState();
            });
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

                if (statPresentNow && p.present_count !== undefined) {
                    statPresentNow.textContent = p.present_count;
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

                    let extraGuestInfo = '';
                    if (d.absence_voice_message) {
                        extraGuestInfo += `<div><strong>Фраза динаміка:</strong> <em>"${escapeHtml(d.absence_voice_message)}"</em></div>`;
                    }
                    if (d.telegram_chat_id) {
                        extraGuestInfo += `<div><strong>Telegram Chat:</strong> <code>${escapeHtml(d.telegram_chat_id)}</code></div>`;
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
                                ${extraGuestInfo}
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
                    devicesTableBody.innerHTML = '<tr><td colspan="7" class="text-muted text-center">Немає пристроїв у базі</td></tr>';
                    return;
                }

                devicesTableBody.innerHTML = devices.map(d => {
                    const roleUa = d.role === 'owner' ? '👑 Власник' : (d.role === 'family' ? '🏠 Сім\'я' : '👤 Гість');
                    const isPresent = (d.status === 'present');
                    const statusHtml = isPresent ? '<span class="badge badge-present">🟢 Присутній</span>' : '<span class="badge badge-away">⚪ Відсутній</span>';
                    const macStr = d.classic_mac || (d.recent_ble_rpa && d.recent_ble_rpa[d.recent_ble_rpa.length - 1]) || '—';

                    let absencePart = '';
                    if (d.absence_voice_message) {
                        absencePart += `<div><small title="${escapeHtml(d.absence_voice_message)}">🔊 <em>"${escapeHtml(d.absence_voice_message.length > 25 ? d.absence_voice_message.substring(0, 25) + '...' : d.absence_voice_message)}"</em></small></div>`;
                    }
                    if (d.telegram_chat_id) {
                        absencePart += `<div><small>💬 TG: <code>${escapeHtml(d.telegram_chat_id)}</code></small></div>`;
                    }
                    if (!absencePart) {
                        absencePart = '<span class="text-muted"><small>Стандартне</small></span>';
                    }

                    return `
                        <tr>
                            <td><strong>${escapeHtml(d.name)}</strong></td>
                            <td>${roleUa}</td>
                            <td>${escapeHtml(d.device_name)} (${d.device_type})</td>
                            <td><code>${escapeHtml(macStr)}</code></td>
                            <td>${absencePart}</td>
                            <td>${statusHtml}</td>
                            <td style="white-space: nowrap;">
                                <button class="btn-ctrl btn-edit-device" data-id="${escapeHtml(d.id)}" style="margin-right: 4px;">
                                    ✏️ Редагувати
                                </button>
                                ${d.role !== 'owner' ? `
                                <button class="btn-ctrl btn-danger-sm btn-delete-device" data-id="${escapeHtml(d.id)}">
                                    🗑️
                                </button>` : ''}
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
                                loadLogData();
                            });
                    });
                });

                document.querySelectorAll('.btn-edit-device').forEach(btn => {
                    btn.addEventListener('click', () => {
                        const devId = btn.getAttribute('data-id');
                        const targetDev = devices.find(x => x.id === devId);
                        if (!targetDev) return;
                        if (devEditId) devEditId.value = targetDev.id;
                        if (devName) devName.value = targetDev.name || '';
                        if (devRole) devRole.value = targetDev.role || 'guest';
                        if (devType) devType.value = targetDev.device_type || 'phone';
                        if (devModel) devModel.value = targetDev.device_name || '';
                        if (devClassicMac) devClassicMac.value = targetDev.classic_mac || '';
                        if (devBleMac) {
                            const rpas = targetDev.recent_ble_rpa || [];
                            devBleMac.value = rpas.length ? rpas[rpas.length - 1] : '';
                        }
                        if (devAbsenceMsg) devAbsenceMsg.value = targetDev.absence_voice_message || '';
                        if (devTelegramChatId) devTelegramChatId.value = targetDev.telegram_chat_id || '';
                        if (devNotifyOwner) devNotifyOwner.checked = targetDev.notify_owner !== false;

                        if (formSectionTitle) formSectionTitle.textContent = `✏️ Редагування: ${targetDev.name}`;
                        if (btnSaveDeviceText) btnSaveDeviceText.textContent = `💾 Оновити налаштування "${targetDev.name}"`;
                        if (btnCancelEdit) btnCancelEdit.style.display = 'inline-block';
                        if (addDeviceForm) addDeviceForm.scrollIntoView({ behavior: 'smooth' });
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

        fetch('/api/presence/report')
            .then(res => res.json())
            .then(data => {
                if (!data.success || !data.report) return;
                const r = data.report;
                if (statTotalGuests) statTotalGuests.textContent = r.total_registered_guests || '0';
                if (statVisitsToday) statVisitsToday.textContent = r.visits_today_count || '0';
            })
            .catch(() => {});
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
                            scanResultsBody.innerHTML = '<tr><td colspan="4" class="text-muted text-center">Завершено. Нових пристроїв у радіусі дії не виявлено (всі наявні датчики та пристрої гаража вже прив\'язані).</td></tr>';
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
                                if (devEditId) devEditId.value = '';
                                if (btnCancelEdit) btnCancelEdit.style.display = 'none';
                                if (formSectionTitle) formSectionTitle.textContent = '➕ Додати гостя або новий пристрій';
                                if (btnSaveDeviceText) btnSaveDeviceText.textContent = '💾 Зберегти в базі присутності';
                                if (devBleMac) devBleMac.value = m;
                                if (devModel && n) devModel.value = n;
                                if (devName) {
                                    devName.value = n || '';
                                    devName.focus();
                                }
                                if (devAbsenceMsg) {
                                    devAbsenceMsg.value = `${n || 'Друже'}, Юри в гаражі немає, гуляйте собі далі...`;
                                }
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

    if (btnCancelEdit) {
        btnCancelEdit.addEventListener('click', () => {
            if (devEditId) devEditId.value = '';
            if (addDeviceForm) addDeviceForm.reset();
            if (formSectionTitle) formSectionTitle.textContent = '➕ Додати гостя або новий пристрій';
            if (btnSaveDeviceText) btnSaveDeviceText.textContent = '💾 Зберегти в базі присутності';
            btnCancelEdit.style.display = 'none';
        });
    }

    if (addDeviceForm) {
        addDeviceForm.addEventListener('submit', (e) => {
            e.preventDefault();
            const name = (devName ? devName.value : '').trim();
            if (!name) return;

            const editId = devEditId ? devEditId.value.trim() : '';
            const payload = {
                name: name,
                role: devRole ? devRole.value : 'guest',
                device_type: devType ? devType.value : 'phone',
                device_name: (devModel && devModel.value.trim()) || name,
                classic_mac: (devClassicMac && devClassicMac.value.trim()) || '',
                ble_mac: (devBleMac && devBleMac.value.trim()) || '',
                absence_voice_message: (devAbsenceMsg && devAbsenceMsg.value.trim()) || '',
                telegram_chat_id: (devTelegramChatId && devTelegramChatId.value.trim()) || '',
                notify_owner: devNotifyOwner ? devNotifyOwner.checked : true,
                auto_welcome: true
            };

            const url = editId ? `/api/presence/devices/${editId}` : '/api/presence/devices';
            const method = editId ? 'PUT' : 'POST';

            fetch(url, {
                method: method,
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(payload)
            })
            .then(res => res.json())
            .then(data => {
                if (data.success) {
                    alert(editId ? `✅ Дані гостя "${name}" успішно оновлено!` : `✅ Гостя/пристрій "${name}" успішно зареєстровано в базі!`);
                    addDeviceForm.reset();
                    if (devEditId) devEditId.value = '';
                    if (btnCancelEdit) btnCancelEdit.style.display = 'none';
                    if (formSectionTitle) formSectionTitle.textContent = '➕ Додати гостя або новий пристрій';
                    if (btnSaveDeviceText) btnSaveDeviceText.textContent = '💾 Зберегти в базі присутності';
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

    // --- 433 MHz RF TRANSCEIVER & RADIO RELAYS LOGIC ---
    const btnRefreshRfActivity = document.getElementById('btnRefreshRfActivity');
    const btnRfDiag = document.getElementById('btnRfDiag');
    const statRfModuleStatus = document.getElementById('statRfModuleStatus');
    const statRfRssi = document.getElementById('statRfRssi');
    const statRfTxCount = document.getElementById('statRfTxCount');
    const statRfRxCount = document.getElementById('statRfRxCount');
    const statRfDedupCount = document.getElementById('statRfDedupCount');
    const statRfLastTx = document.getElementById('statRfLastTx');
    const statRfLastRx = document.getElementById('statRfLastRx');
    const rfActivityTableBody = document.getElementById('rfActivityTableBody');

    const btnRefreshRelays = document.getElementById('btnRefreshRelays');
    const relaysTableBody = document.getElementById('relaysTableBody');
    const relayConfigForm = document.getElementById('relayConfigForm');
    const relayZoneSelect = document.getElementById('relayZoneSelect');
    const relayNameInput = document.getElementById('relayNameInput');
    const relayCodeOnInput = document.getElementById('relayCodeOnInput');
    const relayCodeOffInput = document.getElementById('relayCodeOffInput');
    const btnGenRelayCodes = document.getElementById('btnGenRelayCodes');
    const btnPairRelayOn = document.getElementById('btnPairRelayOn');
    const btnPairRelayOff = document.getElementById('btnPairRelayOff');
    const btnTestRelayOn = document.getElementById('btnTestRelayOn');
    const btnTestRelayOff = document.getElementById('btnTestRelayOff');
    const pairStatusIndicator = document.getElementById('pairStatusIndicator');
    const pairStatusMsg = document.getElementById('pairStatusMsg');

    const btnStartRfLearn = document.getElementById('btnStartRfLearn');
    const rfLearnStatusBox = document.getElementById('rfLearnStatusBox');
    const rfLearnStatusText = document.getElementById('rfLearnStatusText');

    let pairTimer = null;

    function formatTime(ts) {
        if (!ts) return 'ніколи';
        const d = new Date(ts * 1000);
        return d.toLocaleTimeString('uk-UA', { hour: '2-digit', minute: '2-digit', second: '2-digit' });
    }

    function loadRfStatus() {
        fetch('/api/rf/status')
            .then(res => res.json())
            .then(data => {
                if (!data.success) return;
                const m = data.metrics || {};
                const rf = data.rf_status || {};
                if (statRfModuleStatus) {
                    const ok = rf.cc1101 !== false;
                    statRfModuleStatus.innerHTML = ok ? '🟢 Онлайн (433.92 МГц)' : '🔴 Офлайн';
                    statRfModuleStatus.style.color = ok ? 'var(--success)' : 'var(--danger)';
                }
                if (statRfRssi) {
                    statRfRssi.textContent = (rf.rssi !== undefined && rf.rssi !== null) ? `Сигнал (RSSI): ${rf.rssi} dBm` : 'Сигнал: готовність';
                }
                if (statRfTxCount) statRfTxCount.textContent = m.tx_count || 0;
                if (statRfRxCount) statRfRxCount.textContent = m.rx_count || 0;
                if (statRfDedupCount) statRfDedupCount.textContent = m.burst_dedup_count || 0;

                if (statRfLastTx) {
                    statRfLastTx.textContent = m.last_tx_time ? `Остання: ${formatTime(m.last_tx_time)}` : 'Остання: ніколи';
                }
                if (statRfLastRx) {
                    statRfLastRx.textContent = m.last_rx_time ? `Остання: ${formatTime(m.last_rx_time)}` : 'Остання: ніколи';
                }

                if (rfActivityTableBody && data.activity) {
                    if (data.activity.length === 0) {
                        rfActivityTableBody.innerHTML = '<tr><td colspan="6" class="text-muted">Немає зафіксованих подій в ефірі</td></tr>';
                    } else {
                        rfActivityTableBody.innerHTML = data.activity.map(item => {
                            const isTx = item.direction === 'TX';
                            const dirBadge = isTx 
                                ? '<span class="badge" style="background:#2563eb; color:#fff;">TX ⬆️ Передача</span>' 
                                : '<span class="badge" style="background:#059669; color:#fff;">RX ⬇️ Прийом</span>';
                            const actBadge = item.is_repeat 
                                ? '<span class="badge" style="background:rgba(255,255,255,0.1); color:#cbd5e1;">Повтор (Burst)</span>' 
                                : (item.action === 'off' ? '<span class="badge" style="background:#ef4444; color:#fff;">OFF</span>' : (item.action === 'on' ? '<span class="badge" style="background:#22c55e; color:#fff;">ON</span>' : `<span class="badge" style="background:rgba(255,255,255,0.1); color:#cbd5e1;">${escapeHtml(item.action)}</span>`));
                            return `
                                <tr>
                                    <td><strong>${escapeHtml(item.time)}</strong></td>
                                    <td>${dirBadge}</td>
                                    <td><code>${escapeHtml(item.hex)}</code> <span class="text-muted">(${item.code})</span></td>
                                    <td>${escapeHtml(item.zone_title || item.zone || '—')}</td>
                                    <td>${actBadge}</td>
                                    <td><small>${escapeHtml(item.details || '—')}</small></td>
                                </tr>
                            `;
                        }).join('');
                    }
                }
            })
            .catch(() => {});
    }

    function loadRelays() {
        fetch('/api/rf/relays')
            .then(res => res.json())
            .then(data => {
                if (!data.success || !relaysTableBody) return;
                const relays = Object.values(data.relays || {});
                if (relays.length === 0) {
                    relaysTableBody.innerHTML = '<tr><td colspan="6" class="text-muted">Немає прив\'язаних радіореле</td></tr>';
                    return;
                }
                relaysTableBody.innerHTML = relays.map(r => {
                    const onHex = r.code_on_hex || ('0x' + Number(r.code_on).toString(16).toUpperCase());
                    const offHex = r.code_off_hex || ('0x' + Number(r.code_off).toString(16).toUpperCase());
                    const lastAct = r.last_action ? `${r.last_action.toUpperCase()} (${formatTime(r.last_switched)})` : 'Не вмикалось';
                    return `
                        <tr>
                            <td><strong>${escapeHtml(r.name)}</strong></td>
                            <td><code>${escapeHtml(r.zone)}</code></td>
                            <td><span style="color:var(--success)">${onHex}</span> <small class="text-muted">(${r.code_on})</small></td>
                            <td><span style="color:var(--danger)">${offHex}</span> <small class="text-muted">(${r.code_off})</small></td>
                            <td><small>${lastAct}</small></td>
                            <td>
                                <div style="display:flex; gap:4px; flex-wrap:wrap;">
                                    <button class="btn-sm btn-relay-test" data-id="${escapeHtml(r.id)}" data-action="on" title="Надіслати код ON">⚡ ON</button>
                                    <button class="btn-sm btn-relay-test" data-id="${escapeHtml(r.id)}" data-action="off" title="Надіслати код OFF">⚡ OFF</button>
                                    <button class="btn-sm btn-relay-pair" data-id="${escapeHtml(r.id)}" data-action="on" title="Сполучення коду ON з реле">📡 Pair ON</button>
                                    <button class="btn-sm btn-relay-pair" data-id="${escapeHtml(r.id)}" data-action="off" title="Сполучення коду OFF з реле">📡 Pair OFF</button>
                                    <button class="btn-sm btn-danger btn-relay-del" data-id="${escapeHtml(r.id)}" title="Видалити реле">🗑️</button>
                                </div>
                            </td>
                        </tr>
                    `;
                }).join('');
            })
            .catch(() => {});
    }

    // Event delegation for zone buttons & relay action buttons
    document.addEventListener('click', (e) => {
        const btnZone = e.target.closest('.btn-zone-action');
        if (btnZone) {
            const zone = btnZone.getAttribute('data-zone');
            const action = btnZone.getAttribute('data-action');
            if (!zone || !action) return;

            btnZone.disabled = true;
            fetch('/api/device/zone/control', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ zone: zone, action: action })
            })
            .then(res => res.json())
            .then(d => {
                btnZone.disabled = false;
                if (d.success) {
                    loadRfStatus();
                    loadRelays();
                } else {
                    alert('Помилка: ' + (d.error || 'не вдалося виконати команду'));
                }
            })
            .catch(err => {
                btnZone.disabled = false;
                alert('Помилка запиту: ' + err.message);
            });
            return;
        }

        const btnTest = e.target.closest('.btn-relay-test');
        if (btnTest) {
            const rId = btnTest.getAttribute('data-id');
            const act = btnTest.getAttribute('data-action');
            btnTest.disabled = true;
            fetch(`/api/rf/relays/${rId}/test`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ action: act })
            })
            .then(res => res.json())
            .then(d => {
                btnTest.disabled = false;
                if (d.success) {
                    loadRfStatus();
                    loadRelays();
                } else {
                    alert('Помилка тестування реле: ' + (d.error || ''));
                }
            })
            .catch(err => {
                btnTest.disabled = false;
                alert('Помилка запиту: ' + err.message);
            });
            return;
        }

        const btnPair = e.target.closest('.btn-relay-pair');
        if (btnPair) {
            const rId = btnPair.getAttribute('data-id');
            const act = btnPair.getAttribute('data-action');
            startPairingRelay(rId, act);
            return;
        }

        const btnDel = e.target.closest('.btn-relay-del');
        if (btnDel) {
            const rId = btnDel.getAttribute('data-id');
            if (confirm(`Ви впевнені, що бажаєте видалити радіореле "${rId}"?`)) {
                fetch(`/api/rf/relays/${rId}`, { method: 'DELETE' })
                    .then(res => res.json())
                    .then(d => {
                        if (d.success) {
                            loadRelays();
                        } else {
                            alert('Помилка видалення: ' + (d.error || ''));
                        }
                    })
                    .catch(err => alert('Помилка запиту: ' + err.message));
            }
            return;
        }
    });

    function startPairingRelay(relayId, action = 'on') {
        if (pairTimer) clearInterval(pairTimer);
        if (pairStatusIndicator && pairStatusMsg) {
            pairStatusIndicator.style.display = 'block';
            let remain = 15;
            pairStatusMsg.textContent = `📡 Трансляція коду ${action.toUpperCase()} для реле (${remain}с)... Утримуйте кнопку навчання на радіореле!`;

            pairTimer = setInterval(() => {
                remain -= 1;
                if (remain <= 0) {
                    clearInterval(pairTimer);
                    pairStatusMsg.textContent = '✅ Сполучення завершено. Перевірте роботу реле кнопками "⚡ Тест ON/OFF"!';
                    setTimeout(() => { if (pairStatusIndicator) pairStatusIndicator.style.display = 'none'; }, 4000);
                } else {
                    pairStatusMsg.textContent = `📡 Трансляція коду ${action.toUpperCase()} для реле (${remain}с)... Утримуйте кнопку навчання на радіореле!`;
                }
            }, 1000);
        }

        fetch(`/api/rf/relays/${relayId}/pair`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ action: action, duration: 15 })
        })
        .then(res => res.json())
        .then(d => {
            if (d.success) {
                loadRfStatus();
            } else {
                alert('Помилка запуску сполучення: ' + (d.error || ''));
            }
        })
        .catch(err => alert('Помилка: ' + err.message));
    }

    if (btnRefreshRfActivity) {
        btnRefreshRfActivity.addEventListener('click', () => loadRfStatus());
    }

    if (btnRefreshRelays) {
        btnRefreshRelays.addEventListener('click', () => loadRelays());
    }

    if (btnRfDiag) {
        btnRfDiag.addEventListener('click', () => {
            fetch('/api/rf/diag', { method: 'POST' })
                .then(res => res.json())
                .then(() => {
                    alert('Запит апаратної діагностики CC1101 надіслано до ESP32. Оновлення...');
                    setTimeout(loadRfStatus, 1000);
                })
                .catch(err => alert('Помилка: ' + err.message));
        });
    }

    if (btnGenRelayCodes) {
        btnGenRelayCodes.addEventListener('click', () => {
            const baseCode = Math.floor(15800000 + Math.random() * 50000);
            if (relayCodeOnInput) relayCodeOnInput.value = baseCode;
            if (relayCodeOffInput) relayCodeOffInput.value = baseCode + 1;
        });
    }

    if (btnPairRelayOn) {
        btnPairRelayOn.addEventListener('click', () => {
            const code = relayCodeOnInput ? relayCodeOnInput.value : '';
            if (!code) { alert('Спочатку введіть або згенеруйте код ON'); return; }
            triggerDirectPair(code, 'ON');
        });
    }

    if (btnPairRelayOff) {
        btnPairRelayOff.addEventListener('click', () => {
            const code = relayCodeOffInput ? relayCodeOffInput.value : '';
            if (!code) { alert('Спочатку введіть або згенеруйте код OFF'); return; }
            triggerDirectPair(code, 'OFF');
        });
    }

    function triggerDirectPair(code, actName) {
        if (pairTimer) clearInterval(pairTimer);
        if (pairStatusIndicator && pairStatusMsg) {
            pairStatusIndicator.style.display = 'block';
            let remain = 15;
            pairStatusMsg.textContent = `📡 Безперервна трансляція коду ${code} (${actName}) [${remain}с]... Утримуйте кнопку на реле!`;

            pairTimer = setInterval(() => {
                remain -= 1;
                if (remain <= 0) {
                    clearInterval(pairTimer);
                    pairStatusMsg.textContent = '✅ Трансляцію коду сполучення завершено.';
                    setTimeout(() => { if (pairStatusIndicator) pairStatusIndicator.style.display = 'none'; }, 4000);
                } else {
                    pairStatusMsg.textContent = `📡 Безперервна трансляція коду ${code} (${actName}) [${remain}с]... Утримуйте кнопку на реле!`;
                }
            }, 1000);
        }

        fetch('/api/rf/pair', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ duration: 15, code: Number(code) })
        })
        .then(res => res.json())
        .then(() => loadRfStatus())
        .catch(err => alert('Помилка: ' + err.message));
    }

    if (btnTestRelayOn) {
        btnTestRelayOn.addEventListener('click', () => {
            const code = relayCodeOnInput ? relayCodeOnInput.value : '';
            const zone = relayZoneSelect ? relayZoneSelect.value : '';
            if (!code) { alert('Введіть код ON для тесту'); return; }
            fetch('/api/rf/transmit', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ code: Number(code), zone: zone, action: 'on', name: 'Тест ON' })
            })
            .then(res => res.json())
            .then(d => {
                if (d.success) loadRfStatus();
                else alert('Помилка передачі: ' + (d.error || ''));
            })
            .catch(err => alert('Помилка: ' + err.message));
        });
    }

    if (btnTestRelayOff) {
        btnTestRelayOff.addEventListener('click', () => {
            const code = relayCodeOffInput ? relayCodeOffInput.value : '';
            const zone = relayZoneSelect ? relayZoneSelect.value : '';
            if (!code) { alert('Введіть код OFF для тесту'); return; }
            fetch('/api/rf/transmit', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ code: Number(code), zone: zone, action: 'off', name: 'Тест OFF' })
            })
            .then(res => res.json())
            .then(d => {
                if (d.success) loadRfStatus();
                else alert('Помилка передачі: ' + (d.error || ''));
            })
            .catch(err => alert('Помилка: ' + err.message));
        });
    }

    if (relayConfigForm) {
        relayConfigForm.addEventListener('submit', (e) => {
            e.preventDefault();
            const zone = relayZoneSelect ? relayZoneSelect.value : '';
            const name = (relayNameInput ? relayNameInput.value : '').trim();
            const codeOn = relayCodeOnInput ? relayCodeOnInput.value : '';
            const codeOff = relayCodeOffInput ? relayCodeOffInput.value : '';
            if (!zone || !name || !codeOn || !codeOff) {
                alert('Заповніть усі поля форми');
                return;
            }

            const payload = {
                zone: zone,
                name: name,
                code_on: Number(codeOn),
                code_off: Number(codeOff),
                protocol: 1,
                bits: 24,
                delay: 320,
                enabled: true
            };

            fetch('/api/rf/relays', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(payload)
            })
            .then(res => res.json())
            .then(d => {
                if (d.success) {
                    alert(`✅ Радіореле "${name}" для зони "${zone}" успішно збережено!`);
                    relayConfigForm.reset();
                    loadRelays();
                    loadRfStatus();
                } else {
                    alert('Помилка збереження реле: ' + (d.error || ''));
                }
            })
            .catch(err => alert('Помилка: ' + err.message));
        });
    }

    if (btnStartRfLearn) {
        btnStartRfLearn.addEventListener('click', () => {
            btnStartRfLearn.disabled = true;
            if (rfLearnStatusBox && rfLearnStatusText) {
                rfLearnStatusBox.style.display = 'block';
                rfLearnStatusText.textContent = '📡 Запуск режиму навчання... Натисніть кнопку на фізичному пульті 433 МГц!';
            }

            fetch('/api/rf/learn/start', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ duration: 30 })
            })
            .then(res => res.json())
            .then(d => {
                if (d.success) {
                    let pollCount = 0;
                    const learnPoll = setInterval(() => {
                        pollCount += 1;
                        fetch('/api/rf/learn/status')
                            .then(r => r.json())
                            .then(sd => {
                                if (sd.success && sd.status) {
                                    const st = sd.status;
                                    if (st.learning_active) {
                                        rfLearnStatusText.textContent = `🎯 Режим навчання активний (${st.remaining_sec}с). Захоплено сигналів: ${st.captured_count}. Натисніть кнопку пульта!`;
                                    } else {
                                        clearInterval(learnPoll);
                                        btnStartRfLearn.disabled = false;
                                        rfLearnStatusText.textContent = `✅ Режим навчання завершено. Захоплено кодів: ${st.captured_count}. Перевірте журнал активності.`;
                                        loadRfStatus();
                                    }
                                }
                            })
                            .catch(() => {});

                        if (pollCount > 35) {
                            clearInterval(learnPoll);
                            btnStartRfLearn.disabled = false;
                        }
                    }, 1000);
                } else {
                    btnStartRfLearn.disabled = false;
                    alert('Не вдалося запустити режим навчання: ' + (d.error || ''));
                }
            })
            .catch(err => {
                btnStartRfLearn.disabled = false;
                alert('Помилка: ' + err.message);
            });
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

