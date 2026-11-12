import time

from server.automation.engine import AutomationEngine
from server.devices.bluetooth_speaker import BluetoothSpeakerController
from server.devices.esp32 import ESP32Controller
from server.devices.projector import ProjectorController
from server.memory.memory import Memory
from server.services.radio_service import radio_service


class CommandProcessor:
    @property
    def floor1_speaker_mac(self) -> str:
        try:
            from server.devices_config import get_speaker_config
            return (get_speaker_config("floor1").get("mac") or "00:11:22:33:44:01").upper().strip()
        except Exception:
            return "00:11:22:33:44:01"

    @property
    def garage_speaker_mac(self) -> str:
        try:
            from server.devices_config import get_speaker_config
            return (get_speaker_config("garage").get("mac") or "00:11:22:33:44:02").upper().strip()
        except Exception:
            return "00:11:22:33:44:02"


    def __init__(self, logger, memory=None, projector=None, esp32=None, automation=None, bt_sensors=None, speaker=None, presence=None, telemetry_db=None):
        self.logger = logger
        self.memory = memory if memory is not None else Memory()
        self.projector = projector if projector is not None else ProjectorController()
        self.esp32 = esp32 if esp32 is not None else ESP32Controller()
        self.speaker = speaker if speaker is not None else BluetoothSpeakerController(logger=self.logger)
        self.bt_sensors = bt_sensors
        self.presence = presence
        self.automation = automation if automation is not None else AutomationEngine(self.esp32, self.projector, self.memory, self.logger)
        self.telemetry_db = telemetry_db
        self.last_media_queries: dict = {}
    def _get_floors(self) -> dict:
        floors = {}
        if self.bt_sensors:
            t = self.bt_sensors.get_telemetry()
            floors = dict(t.get("floors", {}))
        if hasattr(self, "esp32") and self.esp32:
            st = self.esp32.get_telemetry()
            esp_floors = st.get("floors", {})
            if isinstance(esp_floors, dict):
                for fk, fval in esp_floors.items():
                    if isinstance(fval, dict) and fval.get("mac"):
                        is_esp_online = bool(fval.get("online", False))
                        if is_esp_online and fval.get("temperature") is not None:
                            if fk not in floors:
                                floors[fk] = dict(fval)
                            else:
                                floors[fk] = dict(floors[fk])
                                floors[fk]["temperature"] = fval["temperature"]
                                floors[fk]["humidity"] = fval.get("humidity", floors[fk].get("humidity"))
                                floors[fk]["battery"] = fval.get("battery", floors[fk].get("battery"))
                                floors[fk]["online"] = True
                            floors[fk]["last_updated"] = fval.get("last_updated") or time.time()
                            floors[fk]["source"] = "esp32"
                        elif fk in floors and fval.get("temperature") is not None:
                            if floors[fk].get("temperature") is None:
                                floors[fk]["temperature"] = fval["temperature"]
                                floors[fk]["humidity"] = fval.get("humidity", floors[fk].get("humidity"))
        return floors

    def _format_speaker_location(self, locative: bool = True) -> str:
        """Повертає природну українську назву локації/колонки для відповідей."""
        mac = getattr(self.speaker, "mac", "") or ""
        name = getattr(self.speaker, "name", "") or ""
        if self.floor1_speaker_mac in mac.upper() or "1 поверх" in name or "1-й поверх" in name or "JX-BT" in name or "Музика 1" in name or "Музика перший" in name:
            return "на першому поверсі" if locative else "акустика першого поверху"
        if self.garage_speaker_mac in mac.upper() or "JBL" in name or "Clip" in name:
            return "на колонці JBL Clip 5" if locative else "колонка JBL Clip 5"
        return f"на {name}" if locative and name else (name or "колонці")

    def _extract_temporal_delay(self, command: str) -> tuple[float, str, str]:
        """Витягує затримку виконання з фрази:
        'через півхвилини включи радіо' -> (30.0, '30 секунд', 'включи радіо')
        'через 1 хвилину вимкни світло' -> (60.0, '1 хвилину', 'вимкни світло')
        'вимкни світло через 2 хвилини' -> (120.0, '2 хвилини', 'вимкни світло')
        """
        import re
        patterns = [
            # На початку фрази
            r"^(?:через|за)\s+(півхвилин[иу]?|пів години|півгодини|\d+\s*(?:секунд[иу]?|сек|хвилин[иу]?|хв|годин[иу]?|год)|одну\s+хвилину|хвилину|дві\s+хвилини|три\s+хвилини|п[\x27\’]?ять\s+хвилин|десять\s+хвилин)\s+(.*)$",
            # В кінці фрази
            r"^(.*?)\s+(?:через|за)\s+(півхвилин[иу]?|пів години|півгодини|\d+\s*(?:секунд[иу]?|сек|хвилин[иу]?|хв|годин[иу]?|год)|одну\s+хвилину|хвилину|дві\s+хвилини|три\s+хвилини|п[\x27\’]?ять\s+хвилин|десять\s+хвилин)$"
        ]
        for p in patterns:
            m = re.match(p, command.strip(), re.IGNORECASE)
            if m:
                if p.startswith("^(.*?)\\s+"):
                    cleaned = m.group(1).strip()
                    t_str = m.group(2).strip().lower()
                else:
                    t_str = m.group(1).strip().lower()
                    cleaned = m.group(2).strip()

                sec, desc = self._parse_time_string_to_seconds(t_str)
                return sec, desc, cleaned
        return 0.0, "", command

    @staticmethod
    def _parse_time_string_to_seconds(t_str: str) -> tuple[float, str]:
        import re
        t = t_str.strip().lower()
        if "півхвилин" in t:
            return 30.0, "30 секунд"
        if "півгодин" in t or "пів годин" in t:
            return 1800.0, "30 хвилин"
        if t in ("хвилину", "одну хвилину", "1 хвилину", "1 хв"):
            return 60.0, "1 хвилину"
        if t in ("дві хвилини", "2 хвилини", "2 хв"):
            return 120.0, "2 хвилини"
        if t in ("три хвилини", "3 хвилини", "3 хв"):
            return 180.0, "3 хвилини"
        if t in ("п'ять хвилин", "п’ять хвилин", "5 хвилин", "5 хв"):
            return 300.0, "5 хвилин"
        if t in ("десять хвилин", "10 хвилин", "10 хв"):
            return 600.0, "10 хвилин"

        m_sec = re.search(r"(\d+)\s*(?:секунд|сек)", t)
        if m_sec:
            s = float(m_sec.group(1))
            return s, f"{int(s)} сек"
        m_min = re.search(r"(\d+)\s*(?:хвилин|хв)", t)
        if m_min:
            m = float(m_min.group(1))
            return m * 60.0, f"{int(m)} хв"
        m_hr = re.search(r"(\d+)\s*(?:годин|год)", t)
        if m_hr:
            h = float(m_hr.group(1))
            return h * 3600.0, f"{int(h)} год"
        return 60.0, "1 хвилину"

    def execute(self, command, session_id: str = "default"):

        command = command.strip()

        if not command:
            return True, ""

        # ЖОРСТКЕ ТАБУ НА РОСІЙСЬКУ МОВУ ТА КОНТЕНТ
        import re
        RUSSIAN_CHARS = set("ёъыэЁЪЫЭ")
        RUSSIAN_MARKER_WORDS = {
            "свет", "пожалуйста", "открой", "закрой", "песня", "песню", "песни", "музыка", "музыку",
            "русский", "русская", "русское", "русские", "русскую", "вруби", "выключи", "привет", "спасибо",
            "дверь", "окно", "погода", "температуры", "комната"
        }
        tokens = set(re.findall(r'\b\w+\b', command.lower()))
        has_ru_chars = any(ch in RUSSIAN_CHARS for ch in command)
        has_ru_words = bool(tokens & RUSSIAN_MARKER_WORDS)
        has_ru_media_request = any(w in command.lower() for w in ("російськ", "русск", "по-русски", "російською", "російські")) and any(m in command.lower() for m in ("музик", "пісн", "трек", "радіо", "відео", "кліп", "пісню", "увімкни", "включи", "запусти"))

        if has_ru_chars or has_ru_words or has_ru_media_request:
            return True, "🚫 Російська мова та контент під суворим табу в цій системі. Будь ласка, звертайтесь виключно українською мовою."

        # -----------------------
        # WAKE PHRASE / ACTIVATION ("Альо, гараж" -> "Що тобі потрібно?")
        # -----------------------
        raw_clean = re.sub(r'^[!?.,;:~ \t]+|[!?.,;:~ \t]+$', '', command.strip().lower())
        raw_clean = re.sub(r'\s+', ' ', raw_clean)

        # Anti-loop / echo filter: чиста луна запиту помічника не викликає повторний запит!
        PROMPT_ECHO_EXACT = {
            "що тобі потрібно", "що тобі треба", "що треба", "що потрібно",
            "слухаю", "я слухаю", "що хочете", "яка команда",
            "що тобі потрібно?", "що тобі треба?"
        }
        if raw_clean in PROMPT_ECHO_EXACT:
            return True, None

        WAKE_CALL_EXACT = {
            "альо гараж", "ало гараж", "алло гараж",
            "альо, гараж", "ало, гараж", "алло, гараж",
            "альо гаражу", "ало гаражу", "алло гаражу",
            "альо", "ало", "алло",
            "гараж", "гараж прийом", "гараж, прийом",
            "гараж ти тут", "гараж, ти тут", "гараж слухай", "гараж, слухай"
        }

        if raw_clean in WAKE_CALL_EXACT or re.fullmatch(r'(?:альо|ало|алло)\s*[, -]?\s*гараж(?:у)?', raw_clean):
            return True, "Що тобі потрібно?"

        # Strip prompt echo prefixes if microphone captured assistant's own question:
        # e.g. "Що тобі потрібно, увімкни світло" -> "увімкни світло"
        prompt_echo_match = re.match(
            r'^(?:що\s*(?:тобі|вам)?\s*(?:потрібно|треба)|слухаю|я\s*слухаю)\s*[,:;!?-]*\s*',
            command,
            flags=re.IGNORECASE
        )
        if prompt_echo_match:
            sub_candidate = command[prompt_echo_match.end():].strip()
            if not sub_candidate:
                # Чиста луна без команди -> припиняємо цикл, не повторюємо запит
                return True, None
            sub_handled, sub_resp = self.execute(sub_candidate, session_id=session_id)
            if sub_handled:
                return True, sub_resp
            command = sub_candidate
            raw_clean = re.sub(r'^[!?.,;:~ \t]+|[!?.,;:~ \t]+$', '', command.strip().lower())
            raw_clean = re.sub(r'\s+', ' ', raw_clean)

        # Strip wake prefix if combined with command: e.g. "Альо гараж, відчини ворота" or "Ало гараж увімкни світло"
        wake_prefix_match = re.match(
            r'^(?:(?:альо|ало|алло)\s*[, -]?\s*гараж(?:у)?|гараж)\s*[,:;!?-]*\s+',
            command,
            flags=re.IGNORECASE
        )
        if wake_prefix_match:
            sub_candidate = command[wake_prefix_match.end():].strip()
            if not sub_candidate:
                return True, "Що тобі потрібно?"
            sub_handled, sub_resp = self.execute(sub_candidate, session_id=session_id)
            if sub_handled:
                return True, sub_resp
            return False, None

        # Check sub-clauses if command contains comma or semicolon (e.g. conversational preamble + command)
        if "," in command or ";" in command:
            import re
            sub_commands = [c.strip() for c in re.split(r"[,;]", command) if c.strip()]
            if len(sub_commands) > 1:
                for sub in reversed(sub_commands):
                    sub_handled, sub_resp = self.execute(sub, session_id=session_id)
                    if sub_handled:
                        return True, sub_resp

        # Strip conversational filler words / polite prefixes
        filler_match = re.match(
            r'^(?:просто|будь ласка|будь-ласка|будьласка|давай|ану|а ну|ну|слухай|швидко)\s*[,:;!?-]*\s+',
            command,
            flags=re.IGNORECASE
        )
        if filler_match:
            sub_candidate = command[filler_match.end():].strip()
            if sub_candidate:
                command = sub_candidate

        # Обробка відкладених команд із часовими затримками ("через хвилину ...")
        delay_sec, delay_desc, cleaned_cmd = self._extract_temporal_delay(command)
        if delay_sec > 0 and cleaned_cmd:
            from server.services.action_scheduler import action_scheduler
            rec = action_scheduler.schedule(
                delay_seconds=delay_sec,
                action_fn=lambda: self.execute(cleaned_cmd, session_id=session_id),
                description=f"Команда: {cleaned_cmd}",
                session_id=session_id
            )
            return True, f"⏳ Зрозумів! Заплановано дію '{cleaned_cmd}' через {delay_desc}."

        cmd = command.lower().rstrip("?!.,; ")

        # -----------------------
        # STATUS
        # -----------------------

        if cmd in ("стан", "статус"):
            return True, "Система Smart Garage працює в штатному режимі."

        if cmd == "status":
            return True, "Smart Garage is running."

        # -----------------------
        # HELP
        # -----------------------

        if cmd in ("допомога", "довідка"):
            return True, ("""Доступні команди:
  стан / статус
  допомога
  пам'ять
  запам'ятай <ключ> <значення>
  забудь <ключ>
  ворота відкрити | закрити | перемкнути | стан
  світло увімкнути | вимкнути | перемкнути
  вентиляція увімкнути | вимкнути | перемкнути
  датчики / клімат / стан гаража
  сценарії
  трансляція на проектор
  вихід""")

        if cmd == "help":
            return True, ("""Available commands:
  status
  help
  memory
  remember <key> <value>
  forget <key>
  light on | off | toggle
  fan on | off | toggle
  sensors / telemetry
  scenarios / scenario <arrival | departure | night | cinema>
  project screen | stop | status | slide | stream <query>
  exit""")

        # -----------------------
        # MEMORY
        # -----------------------

        if cmd in ("memory", "пам'ять", "память"):
            return True, str(self.memory.all())

        # -----------------------
        # REMEMBER
        # -----------------------

        if cmd.startswith("remember "):
            parts = command.split(maxsplit=2)
            if len(parts) < 3:
                return True, "Usage: remember <key> <value>"
            key = parts[1]
            value = parts[2]
            self.memory.set(key, value)
            return True, f"Saved '{key}'."

        if cmd.startswith("запам'ятай ") or cmd.startswith("пам'ятай "):
            parts = command.split(maxsplit=2)
            if len(parts) < 3:
                return True, "Використання: запам'ятай <ключ> <значення>"
            key = parts[1]
            value = parts[2]
            self.memory.set(key, value)
            return True, f"Збережено '{key}'."

        # -----------------------
        # FORGET
        # -----------------------

        if cmd.startswith("forget "):
            parts = command.split(maxsplit=1)
            if len(parts) < 2:
                return True, "Usage: forget <key>"
            self.memory.delete(parts[1])
            return True, f"Deleted '{parts[1]}'."

        if cmd.startswith("забудь "):
            parts = command.split(maxsplit=1)
            if len(parts) < 2:
                return True, "Використання: забудь <ключ>"
            self.memory.delete(parts[1])
            return True, f"Видалено '{parts[1]}'."

        # -----------------------
        # PROJECTOR
        # -----------------------

        # -----------------------
        # PROJECTOR & MEDIA STREAMING
        # -----------------------

        # 1. Direct URLs
        if cmd.startswith("http://") or cmd.startswith("https://"):
            if not self.projector.is_reachable():
                return True, f"Проектор HY350MAX ({self.projector.ip}) зараз офлайн або недосяжний."
            self.projector.stop_mirroring()
            success, stream_url = self.projector.stream_online_video(command)
            if success:
                return True, f"🎬 Транслюю на проектор HY350MAX: {command}"
            return True, f"Не вдалося запустити трансляцію на проектор для {command}."

        # -----------------------
        # SPEAKER CONTROLS (STOP, PAUSE, RESUME, VOLUME)
        # -----------------------
        stop_verbs = (
            "виключ", "виключи", "виключити", "вимкни", "вимкнути",
            "зупини", "зупинити", "зупинись", "стоп", "вируби", "вирубити",
            "заглуши", "заглушити", "замовкни", "тиша", "досить", "годі", "stop", "pause"
        )
        media_stop_targets = (
            "музику", "музика", "музон", "радіо", "пісню", "пісня", "пісні",
            "трек", "треки", "звук", "відтворення", "трансляцію", "колонку", "колонки",
            "все", "всі", "music", "radio", "song", "audio", "speaker"
        )

        is_stop_intent = (
            cmd in (
                "стоп", "stop", "зупини", "зупинити", "зупинись", "замовкни", "тиша", "досить", "годі",
                "виключ", "вимкни", "виключи", "вируби", "виключити", "вимкнути",
                "колонка стоп", "speaker stop", "stop music", "stop radio"
            )
            or any(cmd == f"{v} {t}" or cmd.startswith(f"{v} {t} ") for v in stop_verbs for t in media_stop_targets)
            or any(cmd == f"{t} {v}" or cmd.startswith(f"{t} {v} ") for v in stop_verbs for t in media_stop_targets)
            or any(p in cmd for p in (
                "не грай", "не включай", "не вмикай", "без музики", "без звуку", "досить музики", "годі музики",
                "перестань грати", "досить грати", "годі грати",
                "вимкни музику", "виключ музику", "виключи музику", "зупини музику", "вируби музику", "заглуши музику", "стоп музика", "стоп музику",
                "вимкни радіо", "виключ радіо", "виключи радіо", "зупини радіо", "вируби радіо", "заглуши радіо", "стоп радіо",
                "вимкни звук", "виключ звук", "виключи звук", "заглуши звук",
                "вимкни колонку", "виключ колонку", "виключи колонку",
                "вимкни все", "виключ все", "виключи все", "вируби все", "зупини все"
            ))
        ) and not any(w in cmd for w in ("світло", "світла", "вентиляц", "витяжк"))

        if is_stop_intent:
            self.speaker.stop()
            if hasattr(self, "projector") and self.projector:
                try:
                    self.projector.stop_video()
                except Exception:
                    pass
            return True, "⏹️ Відтворення музики та радіо зупинено."

        if any(cmd.startswith(k) or cmd == k for k in (
            "пауза музика", "пауза музику", "колонка пауза", "speaker pause", "пауза радіо", "радіо пауза"
        )):
            self.speaker.pause()
            return True, "⏸️ Музику поставлено на паузу."

        if any(cmd.startswith(k) or cmd == k for k in (
            "продовж музику", "віднови музику", "колонка продовж", "speaker resume", "продовж радіо", "віднови радіо"
        )):
            self.speaker.resume()
            return True, "▶️ Музику продовжено."

        if any(cmd.startswith(k) or cmd == k for k in (
            "включи наступну", "увімкни наступну", "включи наступний", "увімкни наступний",
            "включи наступну пісню", "увімкни наступну пісню", "включи наступний трек", "увімкни наступний трек",
            "наступна пісня", "наступний трек", "наступну пісню", "наступний", "наступна", "наступне",
            "перемкни пісню", "перемкни трек", "пропусти пісню", "пропусти трек", "пропусти цей трек",
            "пропусти", "далі", "грай далі", "включи далі", "увімкни далі",
            "next song", "next track", "next"
        )):
            ok, p_title, t_title = self.speaker.play_next()
            if ok:
                return True, f"⏭️ Наступний трек: {t_title}"
            return True, "Не вдалося перемкнути трек на колонці."

        if any(cmd.startswith(k) or cmd == k for k in (
            "включи попередню", "увімкни попередню", "включи попередній", "увімкни попередній",
            "включи попередню пісню", "увімкни попередню пісню", "включи попередній трек", "увімкни попередній трек",
            "попередня пісня", "попередній трек", "попередню пісню", "попередній", "попередня",
            "поверни пісню", "поверни трек", "назад", "трек назад", "пісню назад",
            "prev song", "prev track", "previous song", "previous track", "prev"
        )):
            ok, p_title, t_title = self.speaker.play_prev()
            if ok:
                return True, f"⏮️ Попередній трек: {t_title}"
            return True, "Не вдалося перемкнути на попередній трек на колонці."

        if any(cmd.startswith(k) for k in ("перемотай", "перемотати", "мотай", "seek")):
            import re
            sec_match = re.search(r"(\d+)\s*(?:сек|sec|хв|min)?", cmd)
            secs = int(sec_match.group(1)) if sec_match else 15
            if "хв" in cmd or "min" in cmd:
                secs *= 60
            if any(w in cmd for w in ("назад", "back", "поверни")):
                secs = -secs
            st = self.speaker.get_status()
            cur = st.get("elapsed_seconds", 0)
            target = max(0, cur + secs)
            ok = self.speaker.seek(target)
            if ok:
                direction = "назад" if secs < 0 else "вперед"
                return True, f"⏩ Перемотано {direction} на {abs(secs)} сек (позиція: {target}с)."
            return True, "Не вдалося перемотати трек."

        if cmd.startswith("колонка гучність ") or cmd.startswith("speaker volume "):
            val_str = cmd.split()[-1].replace("%", "").strip()
            if val_str.isdigit():
                self.speaker.set_volume(int(val_str))
                return True, f"🔊 Гучність колонки JBL встановлено на {val_str}%"

        # -----------------------
        # AUDIO / RADIO STATUS INQUIRY
        # -----------------------
        if any(cmd == q or cmd.startswith(q) for q in (
            "що зараз грає", "що грає", "яка станція грає", "яка радіостанція грає",
            "яка станція зараз грає", "яка музика грає", "що це за музика", "що за радіо",
            "чи грає радіо", "чи грає зараз радіо", "чи працює радіо",
            "стан радіо", "статус радіо", "стан аудіо", "статус аудіо"
        )):
            st = self.speaker.get_status()
            vol = st.get("volume", 0)
            spk_loc = self._format_speaker_location(locative=True)
            if st.get("playing"):
                track = st.get("current_track") or "радіостанція"
                return True, f"📻 Зараз грає {track} {spk_loc} (гучність {vol}%)."
            elif st.get("paused"):
                track = st.get("current_track") or "радіостанція"
                return True, f"⏸️ Радіо на паузі: {track} {spk_loc} (гучність {vol}%)."
            else:
                return True, "Радіо наразі не грає (вимкнено). Доступні станції: Хіт FM, Kiss FM, Radio ROKS, Lounge FM."

        # Interrogative or troubleshooting query detection (should not be treated as playback commands)
        is_inquiry_or_question = (
            cmd.endswith("?")
            or any(cmd.startswith(w) for w in (
                "чому ", "чому не ", "навіщо ", "як ", "чи ", "що ", "яка ", "який ", "яке ", "які ", "де ", "хто ", "коли "
            ))
            or any(w in cmd for w in (
                "чому не", "чому мовчить", "чому вимк", "не грає", "не чути", "не працює",
                "що грає", "що зараз грає", "яка станція", "яка музика", "яка пісня", "чи грає", "чи увімкнен", "чому зупинил"
            ))
        )

        # -----------------------
        # INTERNET RADIO STREAMING
        # -----------------------
        radio_verbs = (
            "увімкни", "увімкнути", "включи", "включити", "вкючи", "вкючити",
            "запусти", "запустити", "відтвори", "відтворити", "постав", "поставити",
            "грай", "пусти", "вруби", "вмикай", "включай", "слухати", "послухати", "play"
        )
        is_video_explicit = any(k in cmd for k in (
            "кліп", "відео", "ролик", "фільм", "кіно", "мультик",
            "покажи на", "на проектор", "на проекторі", "на екран", "на екрані"
        ))
        known_radio_stations = (
            "хіт фм", "хітfm", "hit fm", "hitfm", "хіт",
            "кіс фм", "кісс фм", "кісfm", "kiss fm", "kissfm", "кіс", "кісс",
            "радіо рокс", "radio roks", "радіорокс", "рокс",
            "радіо байрактар", "радіобайрактар", "байрактар",
            "люкс фм", "люксfm", "lux fm", "luxfm",
            "радіо релакс", "radio relax", "релакс", "relax",
            "lounge fm", "лаундж фм", "лаунж фм", "лаундж",
            "радіо джаз", "radio jazz",
            "радіо нв", "радіонв", "наше радіо",
            "радіо промінь", "промінь", "радіо культура", "культура",
            "армія фм", "арміяfm", "радіо мейдан"
        )
        is_radio_cmd = not is_inquiry_or_question and not is_video_explicit and (
            any(cmd.startswith(prefix) for prefix in (
                "увімкни радіо", "увімкнути радіо",
                "включи радіо", "включити радіо",
                "вкючи радіо", "вкючити радіо",
                "запусти радіо", "запустити радіо",
                "відтвори радіо", "відтворити радіо",
                "постав радіо", "поставити радіо",
                "грай радіо", "пусти радіо", "вруби радіо",
                "вмикай радіо", "включай радіо",
                "play radio", "stream radio", "радіо ", "радио "
            ))
            or cmd in ("радіо", "радио", "увімкни радіо", "включи радіо", "radio", "play radio")
            or (any(w in cmd for w in ("радіо", "radio", "радио")) and any(v in cmd for v in radio_verbs))
            or (
                any(st_name in cmd for st_name in known_radio_stations)
                and not any(neg in cmd for neg in ("зупини", "вимкни", "виключи", "вируби", "стоп", "stop"))
            )
        )

        if is_radio_cmd:
            is_floor1_target = any(k in cmd for k in (
                "на 1 поверсі", "на 1 поверх", "на першому поверсі", "1 поверх", "1-й поверх", "перший поверх",
                "jx-bt", "jxbt", "xt-bt", "xtbt", "на jx-bt", "на jxbt", "на xt-bt", "на xtbt"
            ))
            is_jbl_target = any(k in cmd for k in (
                "на jbl", "jbl", "оид", "на оид", "на колонку jbl", "на колонки jbl", "колонку jbl", "колонки jbl",
                "колонці jbl", "колонках jbl", "на кліп", "clip 5"
            ))

            if is_floor1_target:
                self.speaker.set_active_speaker(self.floor1_speaker_mac, "JX-BT (1-й поверх)")
            elif is_jbl_target:
                self.speaker.set_active_speaker(self.garage_speaker_mac, "Юрій: JBL Clip 5")

            station_query = cmd
            for prefix in sorted((
                "увімкни радіо", "увімкнути радіо",
                "включи радіо", "включити радіо",
                "вкючи радіо", "вкючити радіо",
                "запусти радіо", "запустити радіо",
                "відтвори радіо", "відтворити радіо",
                "постав радіо", "поставити радіо",
                "грай радіо", "пусти радіо", "вруби радіо",
                "вмикай радіо", "включай радіо",
                "play radio", "stream radio",
                "увімкни", "увімкнути", "включи", "включити", "вкючи", "вкючити",
                "запусти", "запустити", "відтвори", "відтворити", "постав", "поставити",
                "грай", "пусти", "вруби", "вмикай", "включай", "play"
            ), key=len, reverse=True):
                if station_query.startswith(prefix):
                    station_query = station_query[len(prefix):].strip()
                    break

            # Strip target phrases
            import re
            target_phrases = (
                r"\bна перший поверх\b", r"\bна першому поверсі\b", r"\bна 1 поверх\b", r"\bна 1 поверсі\b",
                r"\bперший поверх\b", r"\b1 поверх\b",
                r"\bна jx-bt\b", r"\bна jxbt\b", r"\bна xt-bt\b", r"\bна xtbt\b",
                r"\bjx-bt\b", r"\bjxbt\b", r"\bxt-bt\b", r"\bxtbt\b",
                r"\bна колонку jbl\b", r"\bна колонки jbl\b", r"\bна колонці jbl\b", r"\bна колонках jbl\b",
                r"\bколонку jbl\b", r"\bколонки jbl\b", r"\bколонці jbl\b",
                r"\bна jbl\b", r"\bна оид\b", r"\bjbl clip 5\b", r"\bclip 5\b", r"\bjbl\b", r"\bоид\b",
                r"\bна колонку\b", r"\bна колонки\b", r"\bна колонці\b", r"\bна колонках\b",
                r"\bчерез колонку\b", r"\bчерез колонки\b", r"\bв колонку\b", r"\bв колонки\b",
                r"\bколонка\b", r"\bколонки\b",
                r"\bon jbl\b", r"\bon speaker\b", r"\bon speakers\b", r"\bon floor 1\b", r"\bfloor 1\b"
            )
            for tp in target_phrases:
                station_query = re.sub(tp, "", station_query, flags=re.IGNORECASE).strip()

            # Remove boundary radio words
            for r_word in ("радіо", "радио", "radio"):
                if station_query.lower().startswith(r_word):
                    station_query = station_query[len(r_word):].strip()
                if station_query.lower().endswith(r_word):
                    station_query = station_query[:-len(r_word)].strip()

            station_query = station_query.strip(" \"'.,:;-")
            for polite in ("будь ласка", "будь-ласка", "please"):
                if station_query.lower().startswith(polite):
                    station_query = station_query[len(polite):].strip(" \"'.,:;-")
                if station_query.lower().endswith(polite):
                    station_query = station_query[:-len(polite)].strip(" \"'.,:;-")

            if not station_query or station_query.lower() in (
                "радіо", "radio", "радио", "музику", "музика", "музон", "трек", "щось", "що-небудь", "шось", "онлайн", "online"
            ):
                station_query = "Hit FM"

            stations = radio_service.search_stations(station_query, limit=3)
            if stations:
                st = stations[0]
                ok = self.speaker.play_stream(st["url"], track_title=st["name"])
                spk_loc = self._format_speaker_location(locative=True)
                if ok:
                    return True, f"📻 Транслюю радіо '{st['name']}' {spk_loc}."
                else:
                    if not self.speaker.is_connected():
                        return True, f"⚠️ Не вдалося запустити радіо '{st['name']}' {spk_loc}: колонка не підключена по Bluetooth або вимкнена. Увімкніть живлення/перепідключіть приймач."
                    return True, f"Не вдалося запустити радіо '{st['name']}' {spk_loc}."
            # Якщо станцію не знайдено швидким пошуком — НЕ блокуємо ШІ помилкою, а передаємо запит моделі
            return False, None

        # -----------------------
        # YOUTUBE MUSIC PLAYLISTS & FAVORITES
        # -----------------------
        is_playlist_list_inquiry = any(cmd == p or cmd.startswith(p + " ") for p in (
            "мої плейлисти", "список моїх плейлистів", "список плейлистів",
            "покажи мої плейлисти", "покажи плейлисти", "які мої плейлисти",
            "які є мої плейлисти", "які є плейлисти", "плейлисти youtube music"
        ))
        if is_playlist_list_inquiry:
            from server.services.ytmusic_service import ytmusic_service
            pls = ytmusic_service.get_user_playlists()
            if not pls:
                return True, "Плейлистів у вашому профілі YouTube Music не знайдено або доступ тимчасово обмежено."
            res_lines = ["🎵 Ваші плейлисти YouTube Music:"]
            for idx, pl in enumerate(pls, 1):
                count_str = f" ({pl['track_count']} треків)" if pl.get('track_count') else ""
                res_lines.append(f"{idx}. {pl['title']}{count_str}")
            res_lines.append("\nЩоб увімкнути, скажіть: 'Включи плейлист <назва>' або 'Включи мої улюблені'.")
            return True, "\n".join(res_lines)

        is_liked_play = not is_inquiry_or_question and (
            any(cmd.startswith(f"{v} {n}") or cmd.startswith(f"{v} мої {n}") for v in (
                "включи", "увімкни", "відтвори", "запусти", "постав", "грай", "програй", "пусти", "вруби", "play"
            ) for n in ("улюблені", "улюблене", "улюблені пісні", "улюблені треки", "лайки", "сподобалось", "мої пісні"))
            or cmd in ("улюблені", "улюблене", "улюблені пісні", "мої улюблені", "улюблені треки")
        )
        if is_liked_play:
            is_floor1_target = any(k in cmd for k in (
                "на 1 поверсі", "на 1 поверх", "на першому поверсі", "1 поверх", "1-й поверх", "перший поверх",
                "jx-bt", "jxbt", "xt-bt", "xtbt", "на jx-bt", "на jxbt", "на xt-bt", "на xtbt"
            ))
            is_jbl_target = any(k in cmd for k in (
                "на jbl", "jbl", "оид", "на оид", "на колонку jbl", "на колонки jbl", "колонку jbl", "колонки jbl",
                "колонці jbl", "колонках jbl", "на кліп", "clip 5"
            ))
            if is_floor1_target:
                self.speaker.set_active_speaker(self.floor1_speaker_mac, "JX-BT (1-й поверх)")
            elif is_jbl_target:
                self.speaker.set_active_speaker(self.garage_speaker_mac, "Юрій: JBL Clip 5")

            spk_loc = self._format_speaker_location(locative=True)
            is_shuffle = any(w in cmd for w in ("перемішай", "рандом", "випадков", "shuffle"))
            ok, p_title, t_title = self.speaker.play_liked(shuffle=is_shuffle)
            if ok:
                return True, f"🔊 Відтворюю з '{p_title}' на YouTube Music {spk_loc}: {t_title}"
            if not self.speaker.is_connected():
                return True, f"⚠️ Не вдалося відтворити Улюблені {spk_loc}: колонка не підключена по Bluetooth або вимкнена."
            return True, f"Не вдалося запустити відтворення з Улюблених {spk_loc}."

        is_playlist_play = not is_inquiry_or_question and any(
            cmd.startswith(f"{v} плейлист") or cmd.startswith(f"{v} мій плейлист")
            for v in ("включи", "увімкни", "відтвори", "запусти", "постав", "грай", "програй", "пусти", "вруби", "play")
        )
        if is_playlist_play:
            is_floor1_target = any(k in cmd for k in (
                "на 1 поверсі", "на 1 поверх", "на першому поверсі", "1 поверх", "1-й поверх", "перший поверх",
                "jx-bt", "jxbt", "xt-bt", "xtbt", "на jx-bt", "на jxbt", "на xt-bt", "на xtbt"
            ))
            is_jbl_target = any(k in cmd for k in (
                "на jbl", "jbl", "оид", "на оид", "на колонку jbl", "на колонки jbl", "колонку jbl", "колонки jbl",
                "колонці jbl", "колонках jbl", "на кліп", "clip 5"
            ))
            if is_floor1_target:
                self.speaker.set_active_speaker(self.floor1_speaker_mac, "JX-BT (1-й поверх)")
            elif is_jbl_target:
                self.speaker.set_active_speaker(self.garage_speaker_mac, "Юрій: JBL Clip 5")

            import re
            target_name = cmd
            for pfx in ("включи мій плейлист", "увімкни мій плейлист", "включи плейлист", "увімкни плейлист",
                        "постав мій плейлист", "постав плейлист", "запусти плейлист", "відтвори плейлист",
                        "грай плейлист", "програй плейлист", "play playlist"):
                if target_name.startswith(pfx):
                    target_name = target_name[len(pfx):].strip()
                    break

            for tp in (
                r"\bна перший поверх\b", r"\bна першому поверсі\b", r"\bна 1 поверх\b", r"\bна 1 поверсі\b",
                r"\bна jx-bt\b", r"\bна jbl\b", r"\bна youtube music\b", r"\bна ютуб мюзік\b"
            ):
                target_name = re.sub(tp, "", target_name, flags=re.IGNORECASE).strip()

            from server.services.ytmusic_service import ytmusic_service
            pl = ytmusic_service.find_playlist(target_name)
            if pl:
                spk_loc = self._format_speaker_location(locative=True)
                is_shuffle = any(w in cmd for w in ("перемішай", "рандом", "випадков", "shuffle"))
                ok, p_title, t_title = self.speaker.play_playlist(pl["id"], shuffle=is_shuffle)
                if ok:
                    return True, f"🔊 Відтворюю з плейлиста '{p_title}' на YouTube Music {spk_loc}: {t_title}"
                return True, f"Не вдалося запустити відтворення з плейлиста '{p_title}' {spk_loc}."
            else:
                return True, f"Плейлист за запитом '{target_name}' не знайдено у вашому YouTube Music."

        # 2. Comprehensive Media Verbs & Nouns
        media_verbs = (
            "включи", "включити", "увімкни", "увімкнути", "відтвори", "відтворити",
            "запусти", "запустити", "постав", "поставити",
            "програй", "програти", "пусти", "пустити", "вруби", "врубити",
            "знайди і включи", "знайди та включи", "знайди", "грай", "play", "stream"
        )
        media_nouns = (
            "кліп", "відео", "музику", "музика", "музон", "пісню", "пісня", "пісь", "пісю",
            "трек", "ролик", "фільм", "кіно", "мультик", "video", "clip", "music", "song", "track"
        )

        prefixes_to_check = []
        for v in media_verbs + ("покажи", "показати", "show"):
            for n in media_nouns:
                prefixes_to_check.append(f"{v} {n} ")
                prefixes_to_check.append(f"{v} {n}")
                prefixes_to_check.append(f"{v} будь ласка {n} ")
                prefixes_to_check.append(f"{v} будь ласка {n}")
                prefixes_to_check.append(f"{v} на проектор {n} ")
                prefixes_to_check.append(f"{v} на проекторі {n} ")
                prefixes_to_check.append(f"{v} на екран {n} ")
                prefixes_to_check.append(f"{v} на екрані {n} ")
        for n in media_nouns:
            prefixes_to_check.append(f"{n} ")
            prefixes_to_check.append(f"{n}")
        for v in media_verbs:
            prefixes_to_check.append(f"{v} ")
            prefixes_to_check.append(f"{v} на проектор ")
            prefixes_to_check.append(f"{v} на проекторі ")
            prefixes_to_check.append(f"{v} на екран ")

        prefixes_to_check.extend([
            "покажи на проекторі ", "покажи на проектор ", "покажи на екрані ", "покажи на екран ",
            "project stream ", "project video ", "play video ", "play clip ", "play music ", "play track ", "play song ", "play "
        ])
        prefixes_to_check.sort(key=len, reverse=True)

        matched_media = False
        media_query = None

        if not is_inquiry_or_question:
            for prefix in prefixes_to_check:
                if cmd.startswith(prefix):
                    candidate_query = command[len(prefix):].strip()
                    # If prefix was just a general verb, ensure it's not a device or sensor command
                    if prefix.strip() in media_verbs:
                        words = [w.strip(" \"'.,:;-") for w in candidate_query.lower().split()]
                        first_w = words[0] if words else ""
                        if (
                            any(rw in words for rw in ("радіо", "radio", "радио", "фм", "fm"))
                            or any(st in candidate_query.lower() for st in (
                                "кіс", "kiss", "хіт", "hit", "рокс", "roks", "байрактар",
                                "люкс", "lux", "релакс", "relax", "lounge", "лаундж", "джаз", "jazz", "промінь"
                            ))
                            or candidate_query.lower().strip(" \"'.,:;-") in (
                                "на колонку", "на колонки", "на колонці", "на колонках",
                                "колонку", "колонки", "jbl", "на jbl", "колонку jbl", "колонки jbl",
                                "jx-bt", "jxbt", "на jx-bt", "на jxbt", "1 поверх", "перший поверх"
                            )
                            or first_w in (
                                "світло", "ворота", "вентиляція", "витяжка", "вентиляцію", "витяжку",
                                "проектор", "екран", "light", "door", "fan", "датчик", "датчики",
                                "клімат", "температур", "температура", "стан", "всі", "все", "статус",
                                "поверх", "поверхи", "підвал", "цоколь"
                            )
                        ):
                            break
                    matched_media = True
                    media_query = candidate_query
                    break

            # 3. Keyword matching if not matched by prefix
            is_stop_or_negated = any(w in cmd.split() for w in stop_verbs + ("не", "без")) or any(
                p in cmd for p in ("не грай", "не включай", "не вмикай", "без музики", "без звуку", "досить", "годі")
            )
            if not matched_media and not is_stop_or_negated:
                for kw in ("кліп", "пісню", "пісня", "трек", "музику", "відео"):
                    if f" {kw} " in f" {cmd} " or f" {kw}" in f" {cmd}" or f"{kw} " in f"{cmd} ":
                        import re
                        parts = re.split(rf"\b{kw}\b", command, flags=re.IGNORECASE)
                        candidate = parts[-1].strip() if len(parts) > 1 and parts[-1].strip() else ""
                        matched_media = True
                        media_query = candidate
                        break

        if matched_media:
            query = media_query or ""
            is_floor1_target = any(k in cmd for k in (
                "на 1 поверсі", "на 1 поверх", "на першому поверсі", "1 поверх", "1-й поверх", "перший поверх",
                "jx-bt", "jxbt", "xt-bt", "xtbt", "на jx-bt", "на jxbt", "на xt-bt", "на xtbt"
            ))
            is_jbl_target = any(k in cmd for k in (
                "на jbl", "jbl", "оид", "на оид", "на колонку jbl", "на колонки jbl", "колонку jbl", "колонки jbl",
                "колонці jbl", "колонках jbl", "на кліп", "clip 5"
            ))
            is_projector_explicit = any(k in cmd for k in ("на проектор", "на проекторі", "на екран", "на екрані", "через проектор", "в проектор"))
            is_speaker_explicit = any(k in cmd for k in (
                "на колонку", "на колонці", "на колонки", "на колонках",
                "через колонку", "через колонки", "в колонку", "в колонки",
                "колонка", "колонки"
            )) or is_floor1_target or is_jbl_target

            if is_projector_explicit:
                is_speaker_target = False
            elif is_speaker_explicit:
                is_speaker_target = True
            else:
                is_video_query = any(k in cmd for k in ("кліп", "відео", "ролик", "фільм", "кіно", "мультик", "clip", "video"))
                is_speaker_target = not is_video_query

            if is_floor1_target:
                self.speaker.set_active_speaker(self.floor1_speaker_mac, "JX-BT (1-й поверх)")
            elif is_jbl_target:
                self.speaker.set_active_speaker(self.garage_speaker_mac, "Юрій: JBL Clip 5")

            # Remove speaker/projector destination suffixes
            for suffix in (
                " на перший поверх", " на першому поверсі", " на 1 поверх", " на 1 поверсі",
                " перший поверх", " 1 поверх", " на jx-bt", " на jxbt", " на xt-bt", " на xtbt", " jx-bt", " jxbt", " xt-bt", " xtbt",
                " на jbl", " на колонку jbl", " на колонки jbl", " на оид", " оид",
                " на колонку", " на колонці", " на колонки", " на колонках",
                " через колонку", " через колонки", " в колонку", " в колонки",
                " колонку jbl", " колонки jbl", " колонка", " колонки",
                " на проектор", " на проекторі", " на екран", " на екрані", " через проектор", " в проектор",
                " on projector", " on the projector", " on jbl", " on speaker", " on speakers", " on floor 1", " floor 1"
            ):
                if query.lower().endswith(suffix):
                    query = query[:-len(suffix)].strip()
                if query.lower().startswith(suffix.strip()):
                    query = query[len(suffix.strip()):].strip()

            # Remove YouTube Music / YouTube platform suffixes and prefixes
            for yt_suf in (
                " на youtube music", " на youtube мюзік", " на ютуб мюзік", " на ютуб мьюзік", " на ютуб музік",
                " в youtube music", " в ютуб мюзік", " з youtube music", " з ютуб мюзік",
                " через youtube music", " через ютуб мюзік",
                " на youtube", " на ютуб", " на ютубі", " в youtube", " в ютуб", " з youtube", " з ютубу",
                " youtube music", " ютуб мюзік", " ютуб мьюзік", " ютуб музік", " youtube", " ютуб"
            ):
                if query.lower().endswith(yt_suf):
                    query = query[:-len(yt_suf)].strip()
                if query.lower().startswith(yt_suf.strip()):
                    query = query[len(yt_suf.strip()):].strip()

            # Clean leading polite words or quotes
            query = query.strip(" \"'.,:;-")

            # Clean leading verbs/nouns to detect generic song/music requests
            cleaned_lower = query.lower().strip(" \"'.,:;-")
            for v in media_verbs + ("покажи", "показати", "show"):
                if cleaned_lower == v:
                    cleaned_lower = ""
                elif cleaned_lower.startswith(f"{v} "):
                    cleaned_lower = cleaned_lower[len(v) + 1:].strip()
            for n in media_nouns:
                if cleaned_lower == n:
                    cleaned_lower = ""
                elif cleaned_lower.startswith(f"{n} "):
                    cleaned_lower = cleaned_lower[len(n) + 1:].strip()

            # Remove laptop/local qualifiers
            for local_kw in (
                "з ноутбука", "з ноута", "з комп'ютера", "з компютера", "з компа",
                "з диска", "локально", "локальну", "локальний", "локальна", "онлайн", "online"
            ):
                if local_kw in cleaned_lower:
                    cleaned_lower = cleaned_lower.replace(local_kw, "").strip()

            DEFAULT_UKRAINIAN_HITS = (
                "ADAM - Сильно Сильно",
                "Океан Ельзи - Той день",
                "Бумбокс - Люди",
                "Антитіла - Фортеця Бахмут",
                "Kalush - Стефанія",
                "KAZKA - Свята",
                "Скрябін - Спи собі сама",
                "Chico & Qatoshi - Допоможе ЗСУ"
            )

            GENERIC_MEDIA_REQUESTS = {
                "музику", "музика", "музон", "пісню", "пісня", "пісь", "пісю", "трек", "кліп", "відео",
                "щось", "що-небудь", "шось", "music", "song", "clip", "video",
                "якусь пісню", "якусь", "якийсь трек", "якусь музику", "будь-яку пісню", "будь яку пісню",
                "гарну пісню", "класну пісню", "щось класне", "щось гарне", "просто пісню", "просто музику",
                "українську пісню", "українські хіти", "пісні", "музичка", "на youtube music", "на ютуб мюзік"
            }

            if not query or not cleaned_lower or cleaned_lower in GENERIC_MEDIA_REQUESTS:
                last_q = (getattr(self, "last_media_queries", {}).get(session_id) or getattr(self, "last_media_query", None))
                if last_q and last_q.lower().strip() not in GENERIC_MEDIA_REQUESTS and not any(last_q.lower().startswith(p) for p in ("просто ", "включи ", "увімкни ")):
                    query = last_q
                else:
                    query = DEFAULT_UKRAINIAN_HITS[0]
            elif cleaned_lower in (
                "цю пісню", "цей кліп", "цю музику", "цей трек", "ту саму пісню", "цю ж пісню",
                "це ж саме", "цю", "цей", "це", "ту саму", "той самий", "this song", "this", "this track"
            ):
                last_q = (getattr(self, "last_media_queries", {}).get(session_id) or getattr(self, "last_media_query", None))
                query = last_q if (last_q and last_q.lower() not in GENERIC_MEDIA_REQUESTS) else DEFAULT_UKRAINIAN_HITS[0]
            elif cleaned_lower:
                query = query.strip(" \"'.,:;-")

            self.last_media_query = query
            if not hasattr(self, "last_media_queries"):
                self.last_media_queries = {}
            self.last_media_queries[session_id] = query

            spk_name = self.speaker.name or "аудіосистемі"
            spk_loc = self._format_speaker_location(locative=True)
            if is_speaker_target:
                # Stop projector video if active to avoid dual audio
                try:
                    self.projector.stop_video()
                except Exception:
                    pass
                success = self.speaker.play_youtube(query)
                if success:
                    return True, f"🔊 Відтворюю на YouTube Music {spk_loc}: {query}"
                if not self.speaker.is_connected():
                    return True, f"⚠️ Не вдалося запустити відтворення на YouTube Music {spk_loc}: колонка не підключена по Bluetooth або вимкнена. Увімкніть живлення/перепідключіть приймач."
                return True, f"Не вдалося запустити відтворення на YouTube Music {spk_loc} для '{query}'."

            if not self.projector.is_reachable():
                # Fallback to speaker if projector is offline!
                success = self.speaker.play_youtube(query)
                if success:
                    return True, f"🔊 Проектор офлайн, перенаправлено на YouTube Music {spk_loc}: {query}"
                if not self.speaker.is_connected():
                    return True, f"⚠️ Проектор HY350MAX офлайн, а {spk_name} не підключена по Bluetooth або вимкнена."
                return True, f"Проектор HY350MAX офлайн, а на {spk_name} не вдалося запустити '{query}'."

            self.projector.stop_mirroring()
            success, stream_url = self.projector.stream_online_video(query)
            if success:
                return True, f"🎬 Транслюю на проектор HY350MAX: {query}"
            return True, f"Не вдалося запустити трансляцію на проектор для '{query}'."

        # Direct Speaker Controls
        if cmd in (
            "підключи jx-bt", "підключи jxbt", "підключи xt-bt", "підключи xtbt",
            "підключи 1 поверх", "підключи музику 1 поверх",
            "підключи колонку 1 поверх", "підключи колонки 1 поверх", "колонки 1 поверх",
            "включи на jx-bt", "включи jx-bt", "включи на xt-bt", "включи xt-bt",
            "увімкни на jx-bt", "увімкни jx-bt", "увімкни на xt-bt", "увімкни xt-bt",
            "спробуй включити на xt-bt", "спробуй включити на jx-bt", "спробуй увімкнути на xt-bt", "спробуй увімкнути на jx-bt",
            "попробуй включити на xt-bt", "попробуй включити на jx-bt"
        ) or any(k in cmd for k in (
            "включити на xt-bt", "включити на jx-bt", "увімкнути на xt-bt", "увімкнути на jx-bt",
            "перемкни на xt-bt", "перемкни на jx-bt", "переключи на xt-bt", "переключи на jx-bt"
        )):
            self.speaker.set_active_speaker(self.floor1_speaker_mac, "JX-BT (1-й поверх)")
            ok = self.speaker.connect(self.floor1_speaker_mac)
            if not ok:
                return True, "⚠️ Не вдалося підключитися до JX-BT (1-й поверх). Схоже, приймач вимкнений або не відповідає (br-connection-page-timeout)."
            if hasattr(self.speaker, "resume_or_replay_last") and self.speaker.resume_or_replay_last():
                track_info = getattr(self.speaker, "_current_track", None) or "аудіо"
                return True, f"🔊 Колонку JX-BT (1-й поверх) успішно підключено, транслюю: {track_info}."
            return True, "🔊 Колонку JX-BT (1-й поверх) успішно підключено та готово до відтворення!"

        if cmd in (
            "підключи jbl", "з'єднай з jbl", "підключи jbl clip", "підключи колонку jbl", "підключи колонки jbl",
            "включи jbl", "увімкни jbl", "включи колонку jbl", "включи колонки jbl"
        ):
            ok = self.speaker.connect(self.garage_speaker_mac)
            return True, "🔊 Колонку JBL Clip 5 успішно підключено!" if ok else "Не вдалося підключитися до JBL Clip 5."

        if cmd in (
            "підключи колонку", "колонка підключи", "connect speaker", "speaker connect",
            "підключи колонки", "колонки підключи", "підключися до колонки", "підключися до колонок",
            "включи колонку", "включи колонки", "увімкни колонку", "увімкни колонки",
            "включи на колонку", "включи на колонки", "увімкни на колонку", "увімкни на колонки",
            "звук на колонку", "звук на колонки", "музику на колонку", "музику на колонки",
            "радіо на колонку", "радіо на колонки"
        ):
            ok = self.speaker.connect()
            spk_name = self.speaker.name or "колонки"
            if not ok:
                return True, f"Не вдалося підключитися до {spk_name}."
            if hasattr(self.speaker, "resume_or_replay_last") and self.speaker.resume_or_replay_last():
                track_info = getattr(self.speaker, "_current_track", None) or "аудіо"
                return True, f"🔊 {spk_name} підключено, транслюю: {track_info}."
            return True, f"🔊 {spk_name} успішно підключено та готово до відтворення!"

        if cmd in ("відключи колонку", "колонка відключи", "disconnect speaker", "speaker disconnect", "відключи jbl", "відключи jx-bt"):
            spk_name = self.speaker.name or "Колонку"
            ok = self.speaker.disconnect()
            return True, f"🔊 {spk_name} відключено." if ok else "Помилка відключення колонки."

        if cmd in (
            "project screen", "project cast", "project on", "project start",
            "транслюй екран", "покажи екран", "дублюй екран", "увімкни проектор", "включи проектор",
            "включи на проектор", "увімкни на проектор", "трансляція на проектор",
            "трансляція екрану", "екран на проектор"
        ):

            if not self.projector.is_reachable():
                return True, f"Проектор HY350MAX ({self.projector.ip}:{self.projector.port}) офлайн або недоступний."
            success = self.projector.capture_and_send_screen()
            self.projector.start_mirroring(fps=2)
            if success:
                return True, f"Трансляцію екрану ноутбука розпочато на проектор HY350MAX ({self.projector.ip})."
            return True, "Не вдалося запустити трансляцію на HY350MAX."

        # Direct Projector App Launchers & Native Controls
        if cmd in ("відкрий transcreen", "запусти transcreen", "включи transcreen", "увімкни transcreen", "transcreen", "транскрін"):
            self.projector.send_rest_command("SCREENCAST")
            return True, "📺 Transcreen активовано на проекторі HY350MAX."

        if cmd in ("відкрий miracast", "запусти miracast", "включи miracast", "увімкни miracast", "miracast", "міракаст"):
            self.projector.send_rest_command("MIRACAST")
            return True, "📺 Miracast активовано на проекторі HY350MAX."

        if cmd in ("відкрий airplay", "запусти airplay", "включи airplay", "увімкни airplay", "airplay", "ейрплей"):
            self.projector.send_rest_command("AIRPLAY")
            return True, "📺 AirPlay активовано на проекторі HY350MAX."

        if cmd in ("відкрий youtube", "запусти youtube", "включи youtube", "увімкни youtube", "youtube", "ютуб"):
            self.projector.send_rest_command("YOUTUBE")
            return True, "▶️ YouTube відкрито на проекторі HY350MAX."

        if cmd in ("відкрий netflix", "запусти netflix", "включи netflix", "увімкни netflix", "netflix", "нетфлікс"):
            self.projector.send_rest_command("NETFLIX")
            return True, "🎬 Netflix відкрито на проекторі HY350MAX."

        if cmd.startswith("проектор гучність ") or cmd.startswith("projector volume "):
            val_str = cmd.split()[-1].replace("%", "").strip()
            if val_str.isdigit():
                self.projector.set_volume(int(val_str))
                return True, f"🔊 Гучність проектора HY350MAX встановлено на {val_str}%"

        if cmd in (
            "project stop", "project off",
            "зупини проектор", "вимкни проектор", "виключи проектор",
            "зупини відео", "зупини трансляцію", "вимкни екран",
            "проектор стоп", "стоп проектор", "проектор вимкни", "проектор виключи"
        ):
            self.projector.stop_mirroring()
            self.projector.stop_video()
            if any(k in cmd for k in ("вимкни", "виключи", "off")):
                self.projector.send_rest_command("POWER")
                return True, "🔌 Проектор HY350MAX вимкнено (POWER)."
            return True, "Трансляцію та відтворення на проекторі HY350MAX зупинено."

        if cmd in ("project pause", "project pause video", "пауза", "зупини на паузу", "проектор пауза", "пауза на проекторі"):
            self.projector.pause_video()
            return True, "Відео на проекторі поставлено на паузу."

        if cmd in ("project resume", "project play", "продовжити", "продовжуй", "проектор продовж", "продовж на проекторі", "проектор грай"):
            self.projector.resume_video()
            return True, "Відтворення на проекторі продовжено."


        if cmd == "project status":
            status = self.projector.get_status()
            online_str = "Online" if status["online"] else "Offline"
            mirror_str = "Active" if status["mirroring"] else "Inactive"
            return True, f"Projector {status['device']}: {online_str} ({status['ip']}:{status['port']}) | Mirroring: {mirror_str}"

        if cmd in ("стан проектора", "статус проектора", "проектор стан", "проектор статус"):
            status = self.projector.get_status()
            online_str = "Онлайн" if status["online"] else "Офлайн (вимкнено/очікування)"
            mirror_str = "Активна" if status["mirroring"] else "Неактивна"
            return True, f"Проектор {status['device']}: {online_str} ({status['ip']}:{status['port']}) | Трансляція: {mirror_str}"

        if cmd in (
            "підключи проектор", "підключись до проектора", "підключися до проектора",
            "з'єднайся з проектором", "з'єднай з проектором", "з'єднатися з проектором",
            "спроби з'єднатися з проектором", "спробуй з'єднатися з проектором", "спробуй підключитися до проектора",
            "попробуй з'єднатися з проектором", "попробуй підключитися до проектора",
            "перевір проектор", "перевір зв'язок з проектором", "перевірити проектор", "перевірити зв'язок з проектором"
        ):
            is_alive = self.projector.is_reachable()
            if is_alive:
                return True, (
                    f"✅ Зв'язок із проектором {self.projector.ip} (HY350MAX) встановлено! "
                    "Проектор онлайн у мережі та готовий до трансляції відео, фільмів або екрана."
                )
            return True, (
                f"⚠️ Проектор HY350MAX ({self.projector.ip}) зараз недосяжний у локальній мережі. "
                "Перевірте, будь ласка, чи увімкнено його живлення (пультом або кнопкою) та чи підключений він до Wi-Fi."
            )

        if cmd in ("project slide", "слайд проектора"):
            if not self.projector.is_reachable():
                return True, f"Проектор HY350MAX ({self.projector.ip}:{self.projector.port}) офлайн."
            mem_summary = [f"{k}: {v}" for k, v in list(self.memory.all().items())[:5]] or ["Пам'ять: порожня"]
            success = self.projector.render_and_send_slide(
                title="Smart Garage Infrastructure",
                subtitle="Стан системи: Онлайн",
                details=["Сервер: Flask Gateway", "Модель: GPT-4.1-mini", "Бездротовий дисплей: Підключено"] + mem_summary
            )
            if success:
                return True, "Слайд дашборду надіслано на HY350MAX."
            return True, "Не вдалося надіслати слайд на HY350MAX."


        # -----------------------
        # ESP32 / HARDWARE & VOICE
        # -----------------------

        # Gate / Door commands: explicitly rejected with safe refusal
        if any(cmd.startswith(p) or cmd == p for p in (
            "door open", "door close", "door toggle", "door status",
            "open door", "close door", "toggle door",
            "відкрий ворота", "відчини ворота", "закрий ворота", "зачини ворота",
            "відкрити ворота", "відчинити ворота", "закрити ворота", "зачинити ворота",
            "ворота відкрий", "ворота відчини", "ворота закрий", "ворота зачини"
        )):
            return True, "Керування воротами вимкнено: датчик та привід воріт не підтримуються у проєкті."

        if cmd in (
            "light on", "turn on light", "turn on lights", "lights on",
            "світло увімкнути", "увімкни світло", "включи світло", "засвіти світло", "увімкнути світло"
        ):
            self.esp32.light_on()
            return True, "Освітлення гаража увімкнено."

        if cmd in (
            "light off", "turn off light", "turn off lights", "lights off",
            "світло вимкнути", "вимкни світло", "виключи світло", "погаси світло", "вимкнути світло"
        ):
            self.esp32.light_off()
            return True, "Освітлення гаража вимкнено."

        # Підвал: Світло та Вентиляція
        if cmd in (
            "увімкни світло в підвалі", "увімкни світло підвал", "засвіти світло в підвалі",
            "підвал світло увімкни", "увімкни підвал", "включи світло в підвалі"
        ):
            if hasattr(self.esp32, "control_zone"):
                self.esp32.control_zone("basement_light", "on")
            return True, "Світло в підвалі увімкнено."

        if cmd in (
            "вимкни світло в підвалі", "вимкни світло підвал", "погаси світло в підвалі",
            "вимкнути світло в підвалі", "вимкнути світло підвал", "підвал світло вимкни",
            "вимкни підвал", "виключи світло в підвалі"
        ):
            if hasattr(self.esp32, "control_zone"):
                self.esp32.control_zone("basement_light", "off")
            elif hasattr(self.esp32, "light_off_zone"):
                self.esp32.light_off_zone("basement_light")
            return True, "Світло в підвалі вимкнено."

        if cmd in (
            "увімкни вентиляцію в підвалі", "увімкни витяжку в підвалі", "включи витяжку в підвалі",
            "включи вентиляцію в підвалі", "підвал витяжка увімкни", "підвал вентиляція увімкни"
        ):
            if hasattr(self.esp32, "control_zone"):
                self.esp32.control_zone("basement_fan", "on")
            return True, "Вентиляцію в підвалі увімкнено."

        if cmd in (
            "вимкни вентиляцію в підвалі", "вимкни витяжку в підвалі", "виключи витяжку в підвалі",
            "виключи вентиляцію в підвалі", "підвал витяжка вимкни", "підвал вентиляція вимкни"
        ):
            if hasattr(self.esp32, "control_zone"):
                self.esp32.control_zone("basement_fan", "off")
            return True, "Вентиляцію в підвалі вимкнено."

        # 2-й поверх: Кімната 1 (Кухня)
        if cmd in (
            "увімкни світло на кухні", "увімкни світло кухня", "засвіти світло на кухні",
            "кухня світло увімкни", "увімкни кухню", "включи світло на кухні"
        ):
            if hasattr(self.esp32, "control_zone"):
                self.esp32.control_zone("floor2_kitchen", "on")
            return True, "Світло на кухні (2-й поверх) увімкнено."

        if cmd in (
            "вимкни світло на кухні", "вимкни світло кухня", "погаси світло на кухні",
            "кухня світло вимкни", "вимкни кухню", "виключи світло на кухні"
        ):
            if hasattr(self.esp32, "control_zone"):
                self.esp32.control_zone("floor2_kitchen", "off")
            return True, "Світло на кухні (2-й поверх) вимкнено."

        # 2-й поверх: Кімната 2 (Вітальня)
        if cmd in (
            "увімкни світло у вітальні", "увімкни світло вітальня", "засвіти світло у вітальні",
            "вітальня світло увімкни", "увімкни вітальню", "включи світло у вітальні"
        ):
            if hasattr(self.esp32, "control_zone"):
                self.esp32.control_zone("floor2_living_room", "on")
            return True, "Світло у вітальні (2-й поверх) увімкнено."

        if cmd in (
            "вимкни світло у вітальні", "вимкни світло вітальня", "погаси світло у вітальні",
            "вітальня світло вимкни", "вимкни вітальню", "виключи світло у вітальні"
        ):
            if hasattr(self.esp32, "control_zone"):
                self.esp32.control_zone("floor2_living_room", "off")
            return True, "Світло у вітальні (2-й поверх) вимкнено."

        # 2-й поверх: Загальне освітлення
        if cmd in (
            "увімкни світло на другому поверсі", "увімкни світло 2 поверх", "увімкни світло другий поверх",
            "засвіти світло на другому поверсі", "другий поверх світло увімкни", "увімкни другий поверх"
        ):
            if hasattr(self.esp32, "control_zone"):
                self.esp32.control_zone("floor2_light", "on")
            return True, "Світло на другому поверсі увімкнено."

        if cmd in (
            "вимкни світло на другому поверсі", "вимкни світло 2 поверх", "вимкни світло другий поверх",
            "погаси світло на другому поверсі", "вимкнути світло на другому поверсі", "другий поверх світло вимкни",
            "вимкни другий поверх", "виключи світло на другому поверсі"
        ):
            if hasattr(self.esp32, "control_zone"):
                self.esp32.control_zone("floor2_light", "off")
            elif hasattr(self.esp32, "light_off_zone"):
                self.esp32.light_off_zone("floor2_light")
            return True, "Світло на другому поверсі вимкнено."

        if cmd in (
            "вимкни все світло", "погаси все світло", "вимкнути все світло", "виключи все світло"
        ):
            if hasattr(self.esp32, "control_zone"):
                self.esp32.control_zone("all", "off")
            elif hasattr(self.esp32, "light_off_zone"):
                self.esp32.light_off_zone("all")
            else:
                self.esp32.light_off()
            return True, "Усе світло у всіх зонах (гараж, підвал, 2-й поверх) вимкнено."

        if cmd in ("light toggle", "toggle light", "світло перемкнути", "перемкни світло"):
            state = self.esp32.light_toggle()
            return True, f"Освітлення гаража {'увімкнено' if state else 'вимкнено'}."

        if cmd in ("fan on", "turn on fan", "вентиляція увімкнути", "увімкни вентиляцію", "включи витяжку", "увімкни витяжку"):
            self.esp32.fan_on()
            return True, "Вентиляцію гаража увімкнено."

        if cmd in ("fan off", "turn off fan", "вентиляція вимкнути", "вимкни вентиляцію", "виключи витяжку", "вимкни витяжку"):
            self.esp32.fan_off()
            return True, "Вентиляцію гаража вимкнено."

        if cmd in ("fan toggle", "toggle fan", "вентиляція перемкнути"):
            state = self.esp32.fan_toggle()
            return True, f"Вентиляцію {'увімкнено' if state else 'вимкнено'}."

        # Якщо це запит на сканування, розмовне питання або запит про загальну температуру/клімат — передаємо на ШІ
        is_scan_or_ai_inquiry = (
            any(w in cmd for w in ("скануй", "проскануй", "сканування", "ефір", "ефіру", "знайди пристрої", "пошук пристроїв", "покажи bluetooth", "bluetooth пристрої"))
            or any(cmd.startswith(q) for q in ("чому ", "як ", "що робити", "чи можна ", "чи варто ", "поясни ", "розкажи ", "порадь ", "який краще", "яка різниця"))
            or ((any(w in cmd for w in ("в гаражі", "у гаражі", "всьому гаражі", "весь гараж", "в гараж")) or cmd in ("температура", "клімат", "градуси", "яка температура", "яка температура в гаражі", "який клімат", "що з кліматом", "погода в гаражі", "яка погода"))
                and not any(w in cmd for w in ("підвал", "підвалі", "підвалу", "basement", "2 поверх", "2-й поверх", "2-му повер", "2 повер", "другий поверх", "другому повер", "floor2", "1 поверх", "1-й поверх", "1-му повер", "перший поверх", "першому повер", "floor1")))
        )
        if is_scan_or_ai_inquiry:
            return False, None

        # Floor-specific temperature queries
        if any(w in cmd for w in ("підвал", "підвалі", "підвалу", "basement")):
            if any(w in cmd for w in ("температур", "волог", "датчик", "стан", "клімат", "скільки", "що")):
                floors = self._get_floors()
                f = floors.get("basement", {})
                t = f.get("temperature") if f.get("temperature") is not None else f.get("last_known_temperature")
                if t is None:
                    return True, "⚓ Клімат у підвалі: датчик наразі офлайн (немає актуальних даних)."
                h = f.get("humidity") if f.get("humidity") is not None else f.get("last_known_humidity", "--")
                return True, f"⚓ Клімат у підвалі: температура {t}°C, вологість {h}%."

        is_floor2 = any(w in cmd for w in ("2 поверх", "2-й поверх", "2-му повер", "2 повер", "другий поверх", "другому повер", "floor2", "2-й", "2-му"))
        if is_floor2 and any(w in cmd for w in ("температур", "волог", "датчик", "стан", "клімат", "скільки", "яка", "що")):
            floors = self._get_floors()
            f = floors.get("floor2", {})
            t = f.get("temperature") if f.get("temperature") is not None else f.get("last_known_temperature")
            if t is None:
                return True, "🏢 Клімат на 2-му поверсі: датчик наразі офлайн (немає актуальних даних)."
            h = f.get("humidity") if f.get("humidity") is not None else f.get("last_known_humidity", "--")
            return True, f"🏢 Клімат на 2-му поверсі: температура {t}°C, вологість {h}%."

        is_floor1 = any(w in cmd for w in ("1 поверх", "1-й поверх", "1-му повер", "1 повер", "перший поверх", "першому повер", "floor1"))
        if is_floor1 and any(w in cmd for w in ("температур", "волог", "датчик", "стан", "клімат", "скільки", "яка", "що")):
            floors = self._get_floors()
            f = floors.get("floor1", {})
            t = f.get("temperature") if f.get("temperature") is not None else f.get("last_known_temperature")
            if t is None:
                status_txt = "очікує встановлення датчика" if not f.get("mac") else "датчик наразі офлайн"
                return True, f"🏠 Клімат на 1-му поверсі (Гараж): {status_txt}."
            h = f.get("humidity") if f.get("humidity") is not None else f.get("last_known_humidity", "--")
            return True, f"🏠 Клімат на 1-му поверсі (Гараж): температура {t}°C, вологість {h}%."

        is_sensor_query = any(cmd == q for q in (
            "sensors", "telemetry", "status", "garage status", "датчики", "стан гаража", "що в гаражі",
            "стан датчиків", "покажи датчики", "покажи всі датчики", "всі датчики", "всі сенсори",
            "покажи сенсори", "клімат на поверхах", "температура на поверхах"
        ))
        if is_sensor_query:
            tel = self.esp32.get_telemetry()
            floors = self._get_floors()

            f1 = floors.get("floor1", {})
            f2 = floors.get("floor2", {})
            fb = floors.get("basement", {})

            online_str = "Онлайн" if tel.get("online") else "Офлайн"
            relays_installed = tel.get("relays_installed", False)
            if not relays_installed:
                light_str = "Очікує реле"
                fan_str = "Очікує реле"
            else:
                light_str = "Увімкнено" if tel.get("light") else "Вимкнено"
                fan_str = "Увімкнено" if tel.get("fan") else "Вимкнено"

            def _fmt_floor(fl, default_offline="Офлайн"):
                t = fl.get("temperature") if fl.get("temperature") is not None else fl.get("last_known_temperature")
                if t is not None:
                    hum = fl.get("humidity") if fl.get("humidity") is not None else fl.get("last_known_humidity")
                    h_val = f", вологість {hum}%" if hum is not None else ""
                    return f"{t}°C{h_val}"
                if not fl.get("mac"):
                    return "очікує встановлення датчика"
                return default_offline

            t1_str = _fmt_floor(f1, "очікує встановлення датчика")
            t2_str = _fmt_floor(f2, "офлайн")
            tb_str = _fmt_floor(fb, "офлайн")

            return True, (f"""📊 Стан системи та датчиків [{online_str}]:
  • 🏠 1-й поверх : {t1_str}
  • 🏢 2-й поверх : {t2_str}
  • ⚓ Підвал     : {tb_str}
  • 💡 Освітлення : {light_str} | 💨 Вентиляція: {fan_str}""")

        # Specific battery inquiry for climate sensors
        is_battery_query = any(w in cmd for w in ("батаре", "акумулятор", "заряд", "батарейк")) and (
            any(w in cmd for w in ("датчик", "сенсор", "клімат", "підвал", "поверх", "гараж", "термометр", "рівень", "стан", "всі", "покажи", "який", "скільки"))
            or cmd in ("батарея", "батарейки", "стан батарей", "стан батарейок", "заряд батареї", "заряд батарей", "рівень заряду", "заряд", "акумулятори")
        )
        if is_battery_query:
            floors = self._get_floors()
            fb = floors.get("basement", {})
            f2 = floors.get("floor2", {})
            f1 = floors.get("floor1", {})

            # Basement-specific
            if any(w in cmd for w in ("підвал", "підвалі", "підвалу", "basement")):
                b = fb.get("battery")
                if b is not None:
                    return True, f"🔋 Заряд батареї датчика у підвалі: {b}%."
                return True, "🔋 Дані про заряд батареї датчика у підвалі наразі відсутні."

            # Floor 2-specific
            if any(w in cmd for w in ("2 поверх", "2-й поверх", "2-му повер", "2 повер", "другий поверх", "другому повер", "floor2", "2-й", "2-му")):
                b = f2.get("battery")
                if b is not None:
                    return True, f"🔋 Заряд батареї датчика на 2-му поверсі: {b}%."
                return True, "🔋 Дані про заряд батареї датчика на 2-му поверсі наразі відсутні."

            # Floor 1-specific
            if any(w in cmd for w in ("1 поверх", "1-й поверх", "1-му повер", "1 повер", "перший поверх", "першому повер", "floor1", "1-й", "1-му")):
                b = f1.get("battery")
                if b is not None:
                    return True, f"🔋 Заряд батареї датчика на 1-му поверсі: {b}%."
                return True, "🔋 Датчик на 1-му поверсі ще очікує встановлення."

            # All sensors
            def _fmt_bat(fl, name):
                b = fl.get("battery")
                if b is not None:
                    return f"{name}: {b}%"
                if not fl.get("mac"):
                    return f"{name}: датчик не встановлено"
                return f"{name}: немає даних"

            b_b = _fmt_bat(fb, "⚓ Підвал")
            b_2 = _fmt_bat(f2, "🏢 2-й поверх")
            b_1 = _fmt_bat(f1, "🏠 1-й поверх")
            return True, f"🔋 Заряд батарей датчиків:\n  • {b_b}\n  • {b_2}\n  • {b_1}"


        # -----------------------
        # AUTOMATION SCENARIOS
        # -----------------------

        if cmd in ("scenario arrival", "сценарій прибуття", "я приїхав", "прибуття авто", "прибуття"):
            _, msg = self.automation.scenario_car_arrival()
            return True, msg

        if cmd in ("scenario departure", "сценарій від'їзд", "я поїхав", "від'їзд авто", "від'їзд"):
            _, msg = self.automation.scenario_departure()
            return True, msg

        if cmd in ("scenario night", "нічний режим", "добраніч", "режим ніч", "охорона"):
            _, msg = self.automation.scenario_night_mode()
            return True, msg

        if cmd in ("scenario cinema", "кінотеатр", "режим кіно", "кінотеатр у гаражі"):
            _, msg = self.automation.scenario_cinema_mode()
            return True, msg

        if cmd in ("scenarios", "scenario list", "сценарії", "список сценаріїв"):
            return True, self.automation.list_scenarios()

        # -----------------------
        # PRESENCE & VISITORS
        # -----------------------

        if any(w in cmd for w in ("хто в гаражі", "хто тут", "хто присутній", "присутність", "хто поруч", "хто прийшов", "хто є")):
            if not self.presence:
                return True, "Модуль фіксації присутності не ініціалізовано."
            status = self.presence.get_status()
            present = status.get("present_now", [])
            if not present:
                return True, "📍 У гаражі та біля нього зараз нікого не зафіксовано."
            lines = ["👥 Зараз зафіксовано біля гаража:"]
            for p in present:
                prox = p.get("proximity", "unknown")
                prox_ua = "дуже близько (<2м)" if prox == "immediate" else ("поруч (2-6м)" if prox == "near" else "на підході")
                lines.append(f"  • {p.get('name')} ({p.get('device_name')}) — {prox_ua}, сигнал: {p.get('last_rssi', '?')} dBm")
            return True, "\n".join(lines)

        if any(w in cmd for w in ("журнал відвідувань", "хто приходив", "хто був", "лог присутності", "історія присутності", "журнал гостей")):
            if not self.presence:
                return True, "Модуль фіксації присутності не ініціалізовано."
            logs = self.presence.get_log(limit=10)
            if not logs:
                return True, "Журнал присутності порожній."
            lines = ["📜 Останні події присутності та візитів:"]
            for l in logs:
                ev_icon = "🟢" if l.get("event") == "ARRIVED" else ("🔴" if l.get("event") == "DEPARTED" else "ℹ️")
                lines.append(f"  {ev_icon} [{l.get('formatted_time')}] {l.get('person_name')} ({l.get('device_name')}) — {l.get('event')} ({l.get('proximity')})")
            return True, "\n".join(lines)

        # -----------------------
        # UNKNOWN
        # -----------------------

        return False, None



