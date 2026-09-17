from server.memory.memory import Memory
from server.devices.projector import ProjectorController
from server.devices.esp32 import ESP32Controller
from server.devices.bluetooth_speaker import BluetoothSpeakerController
from server.automation.engine import AutomationEngine
from server.services.radio_service import radio_service


class CommandProcessor:

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
                        elif not is_esp_online and fk in floors:
                            floors[fk]["online"] = False

        if hasattr(self, "telemetry_db") and self.telemetry_db:
            latest_db = self.telemetry_db.get_latest_by_floor()
            for fk, db_val in latest_db.items():
                if fk in floors and floors[fk].get("temperature") is None and db_val.get("temperature") is not None:
                    floors[fk]["temperature"] = db_val["temperature"]
                    floors[fk]["humidity"] = db_val.get("humidity")
                    floors[fk]["battery"] = db_val.get("battery")
                    floors[fk]["last_updated"] = db_val.get("timestamp")
                    floors[fk]["source"] = "db"
        return floors

    def execute(self, command):

        command = command.strip()

        if not command:
            return True, ""

        cmd = command.lower()

        # -----------------------
        # STATUS
        # -----------------------

        if cmd == "status":
            return True, "Smart Garage is running."

        # -----------------------
        # HELP
        # -----------------------

        if cmd == "help":
            return True, ("""Available commands:
  status
  help
  memory
  remember <key> <value>
  forget <key>
  door open | close | toggle | status
  light on | off | toggle
  fan on | off | toggle
  sensors / telemetry
  scenarios / scenario <arrival | departure | night | cinema | safety>
  project screen | stop | status | slide | stream <query>
  exit""")




        # -----------------------
        # MEMORY
        # -----------------------

        if cmd == "memory":
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

        # -----------------------
        # FORGET
        # -----------------------

        if cmd.startswith("forget "):

            parts = command.split(maxsplit=1)

            if len(parts) < 2:
                return True, "Usage: forget <key>"

            self.memory.delete(parts[1])

            return True, f"Deleted '{parts[1]}'."

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
                prefixes_to_check.append(f"{v} будь ласка {n} ")
                prefixes_to_check.append(f"{v} на проектор {n} ")
                prefixes_to_check.append(f"{v} на проекторі {n} ")
                prefixes_to_check.append(f"{v} на екран {n} ")
                prefixes_to_check.append(f"{v} на екрані {n} ")
        for n in media_nouns:
            prefixes_to_check.append(f"{n} ")
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

        for prefix in prefixes_to_check:
            if cmd.startswith(prefix):
                candidate_query = command[len(prefix):].strip()
                # If prefix was just a general verb, ensure it's not a device or sensor command
                if prefix.strip() in media_verbs:
                    first_w = candidate_query.lower().split()[0] if candidate_query else ""
                    if first_w in (
                        "радіо", "radio", "світло", "ворота", "вентиляція", "витяжка", "вентиляцію", "витяжку",
                        "проектор", "екран", "light", "door", "fan", "датчик", "датчики",
                        "клімат", "температур", "температура", "стан", "всі", "все", "статус",
                        "поверх", "поверхи", "підвал", "цоколь"
                    ):
                        break
                matched_media = True
                media_query = candidate_query
                break

        # 3. Keyword matching if not matched by prefix
        if not matched_media:
            for kw in ("кліп", "пісню", "пісня", "трек", "музику", "відео"):
                if f" {kw} " in f" {cmd} ":
                    import re
                    parts = re.split(rf"\b{kw}\b", command, flags=re.IGNORECASE)
                    candidate = parts[-1].strip() if len(parts) > 1 and parts[-1].strip() else command
                    matched_media = True
                    media_query = candidate
                    break

        if matched_media and media_query:
            query = media_query
            is_floor1_target = any(k in cmd for k in ("на 1 поверсі", "на 1 поверх", "на першому поверсі", "1 поверх", "jx-bt", "jxbt"))
            is_jbl_target = any(k in cmd for k in ("на jbl", "jbl", "на колонку jbl", "колонку jbl", "колонці jbl", "на кліп", "clip 5"))
            is_projector_explicit = any(k in cmd for k in ("на проектор", "на проекторі", "на екран", "на екрані", "через проектор", "в проектор"))
            is_speaker_explicit = any(k in cmd for k in ("на колонку", "на колонці", "через колонку", "в колонку", "колонка")) or is_floor1_target or is_jbl_target

            if is_projector_explicit:
                is_speaker_target = False
            elif is_speaker_explicit:
                is_speaker_target = True
            else:
                is_video_query = any(k in cmd for k in ("кліп", "відео", "ролик", "фільм", "кіно", "мультик", "clip", "video"))
                is_speaker_target = not is_video_query

            if is_floor1_target:
                self.speaker.set_active_speaker("41:42:62:69:51:9B", "JX-BT (1-й поверх)")
            elif is_jbl_target:
                self.speaker.set_active_speaker("F8:5C:7E:EE:7D:CC", "Юрій: JBL Clip 5")

            for suffix in (
                " на перший поверх", " на першому поверсі", " на 1 поверх", " на 1 поверсі",
                " перший поверх", " 1 поверх", " на jx-bt", " на jxbt", " на jbl", " на колонку jbl",
                " на колонку", " на колонці", " через колонку", " в колонку", " колонку jbl",
                " на проектор", " на проекторі", " на екран", " на екрані", " через проектор", " в проектор",
                " on projector", " on the projector", " on jbl", " on speaker", " on floor 1", " floor 1"
            ):
                if query.lower().endswith(suffix):
                    query = query[:-len(suffix)].strip()
                if query.lower().startswith(suffix.strip()):
                    query = query[len(suffix.strip()):].strip()

            # Clean leading polite words or quotes
            query = query.strip(" \"'.,:;-")

            # If user just said "play music" or "play clip" without specifying track, choose default media
            cleaned_lower = query.lower()
            for v in media_verbs + ("покажи", "показати", "show"):
                if cleaned_lower.startswith(f"{v} "):
                    cleaned_lower = cleaned_lower[len(v) + 1:].strip()
            for n in media_nouns:
                if cleaned_lower == n:
                    cleaned_lower = ""
                elif cleaned_lower.startswith(f"{n} "):
                    cleaned_lower = cleaned_lower[len(n) + 1:].strip()

            if not query or not cleaned_lower or cleaned_lower in (
                "музику", "музика", "музон", "пісню", "пісня", "трек", "кліп", "відео",
                "щось", "що-небудь", "шось", "music", "song", "clip", "video"
            ):
                query = getattr(self, "last_media_query", None) or "Кузьма Скрябін - Мам"
            elif cleaned_lower in (
                "цю пісню", "цей кліп", "цю музику", "цей трек", "ту саму пісню", "цю ж пісню",
                "це ж саме", "цю", "цей", "це", "ту саму", "той самий", "this song", "this", "this track"
            ):
                query = getattr(self, "last_media_query", None) or "Кузьма Скрябін - Мам"
            elif cleaned_lower:
                query = cleaned_lower

            self.last_media_query = query

            spk_name = self.speaker.name or "аудіосистемі"
            if is_speaker_target:
                # Stop projector video if active to avoid dual audio
                try:
                    self.projector.stop_video()
                except Exception:
                    pass
                success = self.speaker.play_youtube(query)
                if success:
                    return True, f"🔊 Відтворюю на {spk_name}: {query}"
                return True, f"Не вдалося запустити відтворення на {spk_name} для '{query}'."

            if not self.projector.is_reachable():
                # Fallback to speaker if projector is offline!
                success = self.speaker.play_youtube(query)
                if success:
                    return True, f"🔊 Проектор офлайн, перенаправлено на {spk_name}: {query}"
                return True, f"Проектор HY350MAX офлайн, а на {spk_name} не вдалося запустити '{query}'."

            self.projector.stop_mirroring()
            success, stream_url = self.projector.stream_online_video(query)
            if success:
                return True, f"🎬 Транслюю на проектор HY350MAX: {query}"
            return True, f"Не вдалося запустити трансляцію на проектор для '{query}'."

        # Direct Speaker Controls
        if cmd in ("підключи jx-bt", "підключи jxbt", "підключи 1 поверх", "підключи музику 1 поверх", "підключи колонку 1 поверх"):
            ok = self.speaker.connect("41:42:62:69:51:9B")
            return True, "🔊 Колонку JX-BT (1-й поверх) успішно підключено!" if ok else "Не вдалося підключитися до JX-BT."

        if cmd in ("підключи jbl", "з'єднай з jbl", "підключи jbl clip", "підключи колонку jbl"):
            ok = self.speaker.connect("F8:5C:7E:EE:7D:CC")
            return True, "🔊 Колонку JBL Clip 5 успішно підключено!" if ok else "Не вдалося підключитися до JBL Clip 5."

        if cmd in ("підключи колонку", "колонка підключи", "connect speaker", "speaker connect"):
            ok = self.speaker.connect()
            spk_name = self.speaker.name or "колонки"
            return True, f"🔊 {spk_name} успішно підключено!" if ok else f"Не вдалося підключитися до {spk_name}."

        if cmd in ("відключи колонку", "колонка відключи", "disconnect speaker", "speaker disconnect", "відключи jbl", "відключи jx-bt"):
            spk_name = self.speaker.name or "Колонку"
            ok = self.speaker.disconnect()
            return True, f"🔊 {spk_name} відключено." if ok else "Помилка відключення колонки."

        if cmd in ("зупини музику", "стоп музика", "вимкни музику", "колонка стоп", "speaker stop", "stop music", "зупини радіо", "вимкни радіо", "стоп радіо", "radio stop"):
            self.speaker.stop()
            return True, "⏹️ Відтворення на колонці зупинено."

        if cmd in ("пауза музика", "колонка пауза", "speaker pause", "пауза радіо"):
            self.speaker.pause()
            return True, "⏸️ Музику поставлено на паузу."

        if cmd in ("продовж музику", "колонка продовж", "speaker resume", "продовж радіо"):
            self.speaker.resume()
            return True, "▶️ Музику продовжено."

        if cmd.startswith("колонка гучність ") or cmd.startswith("speaker volume "):
            val_str = cmd.split()[-1].replace("%", "").strip()
            if val_str.isdigit():
                self.speaker.set_volume(int(val_str))
                return True, f"🔊 Гучність колонки JBL встановлено на {val_str}%"

        # Internet Radio triggers
        if any(cmd.startswith(prefix) for prefix in ("увімкни радіо", "включи радіо", "запусти радіо", "радіо ")) or cmd in ("радіо", "увімкни радіо", "включи радіо"):
            station_query = cmd
            for prefix in ("увімкни радіо", "включи радіо", "запусти радіо", "радіо"):
                if station_query.startswith(prefix):
                    station_query = station_query[len(prefix):].strip()
                    break

            if not station_query:
                station_query = "Hit FM"

            stations = radio_service.search_stations(station_query, limit=3)
            if stations:
                st = stations[0]
                ok = self.speaker.play_stream(st["url"], track_title=st["name"])
                spk = self.speaker.name or "колонці"
                if ok:
                    return True, f"📻 Транслюю радіо '{st['name']}' на {spk}."
                else:
                    return True, f"Не вдалося запустити радіо '{st['name']}' на {spk}."
            return True, f"Радіостанцію за запитом '{station_query}' не знайдено в каталозі."




        if cmd in (
            "project screen", "project cast", "project on", "project start",
            "транслюй екран", "покажи екран", "дублюй екран", "увімкни проектор", "включи проектор",
            "включи на проектор", "увімкни на проектор", "трансляція на проектор",
            "трансляція екрану", "екран на проектор"
        ):

            if not self.projector.is_reachable():
                return True, f"Projector HY350MAX ({self.projector.ip}:{self.projector.port}) is offline or unreachable."
            success = self.projector.capture_and_send_screen()
            self.projector.start_mirroring(fps=2)
            if success:
                return True, f"Трансляцію екрану ноутбука розпочато на проектор HY350MAX ({self.projector.ip})."
            return True, f"Failed to project screen to HY350MAX."

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

        if cmd == "project slide":
            if not self.projector.is_reachable():
                return True, f"Projector HY350MAX ({self.projector.ip}:{self.projector.port}) is offline."
            mem_summary = [f"{k}: {v}" for k, v in list(self.memory.all().items())[:5]] or ["Memory: Empty"]
            success = self.projector.render_and_send_slide(
                title="Smart Garage Infrastructure",
                subtitle="System Status: Online",
                details=["Backend: Flask Gateway", "Model: GPT-4.1-mini", "Wireless Display: Connected"] + mem_summary
            )
            if success:
                return True, "Dashboard slide sent to HY350MAX."
            return True, "Failed to send slide to HY350MAX."


        # -----------------------
        # ESP32 / HARDWARE & VOICE
        # -----------------------

        if cmd in (
            "door open", "open door", "open gate", "open the door", "open the gate",
            "ворота відкрити", "відкрий ворота", "відчини ворота", "відчинити ворота",
            "відкрий двері", "відчини двері", "відкрий гараж", "відчини гараж"
        ):
            state = self.esp32.door_open()
            return True, f"Ворота гаража відкрито (СТАН: {state.upper()})."

        if cmd in (
            "door close", "close door", "close gate", "close the door", "close the gate",
            "ворота закрити", "закрий ворота", "зачини ворота", "зачинити ворота",
            "закрий двері", "зачини двері", "закрий гараж", "зачини гараж"
        ):
            state = self.esp32.door_close()
            return True, f"Ворота гаража закрито (СТАН: {state.upper()})."

        if cmd in ("door toggle", "toggle door", "ворота перемкнути", "перемкни ворота"):
            state = self.esp32.door_toggle()
            return True, f"Положення воріт змінено: {state.upper()}."

        if cmd in ("door status", "стан воріт", "чи закриті ворота", "чи відкриті ворота"):
            tel = self.esp32.get_telemetry()
            return True, f"Статус воріт: {tel['door'].upper()}"

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

        # Floor-specific temperature queries
        if any(w in cmd for w in ("підвал", "підвалі", "підвалу", "basement")):
            if any(w in cmd for w in ("температур", "волог", "датчик", "стан", "клімат", "скільки", "що")):
                floors = self._get_floors()
                f = floors.get("basement", {})
                t = f.get("temperature", "--")
                h = f.get("humidity", "--")
                b = f.get("battery")
                b_str = f", 🔋 батарея: {b}%" if b is not None else ""
                return True, f"⚓ Клімат у підвалі: температура {t}°C, вологість {h}%{b_str}."

        is_floor2 = any(w in cmd for w in ("2 поверх", "2-й поверх", "2-му повер", "2 повер", "другий поверх", "другому повер", "floor2", "2-й", "2-му"))
        if is_floor2 and any(w in cmd for w in ("температур", "волог", "датчик", "стан", "клімат", "скільки", "яка", "що")):
            floors = self._get_floors()
            f = floors.get("floor2", {})
            t = f.get("temperature", "--")
            h = f.get("humidity", "--")
            b = f.get("battery")
            b_str = f", 🔋 батарея: {b}%" if b is not None else ""
            return True, f"🏢 Клімат на 2-му поверсі: температура {t}°C, вологість {h}%{b_str}."

        is_floor1 = any(w in cmd for w in ("1 поверх", "1-й поверх", "1-му повер", "1 повер", "перший поверх", "першому повер", "floor1", "1-й", "1-му"))
        if is_floor1 and any(w in cmd for w in ("температур", "волог", "датчик", "стан", "клімат", "скільки", "яка", "що")):
            floors = self._get_floors()
            f = floors.get("floor1", {})
            t = f.get("temperature", "--")
            h = f.get("humidity", "--")
            b = f.get("battery")
            b_str = f", 🔋 батарея: {b}%" if b is not None else ""
            return True, f"🏠 Клімат на 1-му поверсі: температура {t}°C, вологість {h}%{b_str}."

        if any(cmd == q for q in (
            "sensors", "telemetry", "garage status", "датчики", "стан гаража", "яка температура",
            "покажи датчики", "покажи всі датчики", "всі датчики", "всі сенсори", "покажи сенсори",
            "що в гаражі", "клімат", "стан датчиків", "клімат на поверхах", "температура на поверхах"
        )):
            tel = self.esp32.get_telemetry()
            floors = self._get_floors()

            f1 = floors.get("floor1", {})
            f2 = floors.get("floor2", {})
            fb = floors.get("basement", {})

            online_str = "Онлайн" if tel.get("online") else "Офлайн"
            light_str = "Увімкнено" if tel.get("light") else "Вимкнено"
            fan_str = "Увімкнено" if tel.get("fan") else "Вимкнено"
            door_ua = "ВІДКРИТО" if tel.get("door") == "open" else "ЗАКРИТО"

            t1 = f1.get("temperature") if f1.get("temperature") is not None else "--"
            h1 = f1.get("humidity") if f1.get("humidity") is not None else "--"
            b1 = f1.get("battery") if f1.get("battery") is not None else "--"

            t2 = f2.get("temperature") if f2.get("temperature") is not None else "--"
            h2 = f2.get("humidity") if f2.get("humidity") is not None else "--"
            b2 = f2.get("battery") if f2.get("battery") is not None else "--"

            tb = fb.get("temperature") if fb.get("temperature") is not None else "--"
            hb = fb.get("humidity") if fb.get("humidity") is not None else "--"
            bb = fb.get("battery") if fb.get("battery") is not None else "--"

            return True, (f"""📊 Стан системи та датчиків [{online_str}]:
  • 🏠 1-й поверх : {t1}°C, вологість {h1}% (🔋 {b1}%)
  • 🏢 2-й поверх : {t2}°C, вологість {h2}% (🔋 {b2}%)
  • ⚓ Підвал     : {tb}°C, вологість {hb}% (🔋 {bb}%)
  • 💡 Освітлення : {light_str} | 💨 Вентиляція: {fan_str}
  • 🚪 Ворота     : {door_ua} | 🛡️ Газ MQ2: {tel.get('gas_ppm', 0)} ppm""")


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

        if cmd in ("scenario safety", "провітрити", "безпека", "аварійне провітрювання", "тривога"):
            _, msg = self.automation.scenario_gas_alarm()
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



