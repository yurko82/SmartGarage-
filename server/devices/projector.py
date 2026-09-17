import os
import io
import time
import threading
import urllib.request
import urllib.parse
import socket
import re
from PIL import Image, ImageDraw, ImageGrab
from server.config import config


def get_local_ip(target_ip=None):
    if target_ip:
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.connect((target_ip, 80))
            ip = s.getsockname()[0]
            s.close()
            return ip
        except Exception:
            pass

    try:
        import subprocess
        res = subprocess.run(['ip', '-br', 'addr', 'show'], capture_output=True, text=True, timeout=1.0)
        wifi_ip = None
        enx_ip = None
        for line in res.stdout.splitlines():
            parts = line.split()
            if len(parts) >= 3 and parts[1].upper() in ('UP', 'UNKNOWN'):
                if parts[0].startswith('wl'):
                    for addr in parts[2:]:
                        if '.' in addr and not addr.startswith('127.'):
                            wifi_ip = addr.split('/')[0]
                elif parts[0].startswith(('enx', 'eth', 'enp')):
                    for addr in parts[2:]:
                        if '.' in addr and not addr.startswith('127.'):
                            enx_ip = addr.split('/')[0]
        if wifi_ip:
            return wifi_ip
        if enx_ip:
            return enx_ip
    except Exception:
        pass
    return '192.168.100.126'


class ProjectorController:

    def __init__(self, ip=None, port=None):
        cfg = config.get("projector", {}) if isinstance(config, dict) else {}
        self.ip = ip or cfg.get("ip", "192.168.100.191")
        self.port = port or cfg.get("airplay_port", cfg.get("port", 57000))
        self.dlna_port = cfg.get("dlna_port", 36887)
        self.dlna_uuid = cfg.get("dlna_uuid", "86257d31-b925-3e7f-9a41-b9ac6b4e0d1a")
        self.ip6 = None
        self.rest_port = cfg.get("rest_port", 8899)
        self._dlna_base_url = None
        self.mirroring = False
        self._mirror_thread = None
        self._lock = threading.Lock()

    def send_rest_command(self, command: str, value=None, timeout=2.0) -> bool:
        if os.environ.get("TESTING"):
            return True
        import json
        payload = {"command": command}
        if value is not None:
            payload["value"] = value
        data = json.dumps(payload).encode("utf-8")
        hosts_to_try = []
        ip6_host = getattr(self, "ip6", None) or self.discover_ipv6_projector()
        if ip6_host:
            hosts_to_try.append(f"http://[{ip6_host}]:{self.rest_port}")
        hosts_to_try.append(f"http://{self.ip}:{self.rest_port}")
        for host in hosts_to_try:
            url = f"{host}/api/v1/command"
            req = urllib.request.Request(
                url, data=data, headers={"Content-Type": "application/json"}, method="POST"
            )
            try:
                with urllib.request.urlopen(req, timeout=timeout) as res:
                    if res.status == 200:
                        return True
            except Exception:
                continue
        return False

    def discover_ipv6_projector(self):
        """Find projector IPv6 link-local address from neighbor table."""
        import subprocess
        try:
            res = subprocess.run(['ip', '-6', 'neigh'], capture_output=True, text=True, timeout=1.5)
            for line in res.stdout.splitlines():
                if '88:91:49:a1:6e:ca' in line.lower() or 'fe80::' in line.lower():
                    parts = line.split()
                    if len(parts) >= 3 and 'dev' in parts:
                        ip6 = parts[0]
                        dev = parts[parts.index('dev') + 1]
                        return f"{ip6}%{dev}"
        except Exception:
            pass
        return None

    def discover_projector(self, timeout=2.0):
        """Dynamic auto-discovery of projector IP and ports via SSDP / mDNS."""
        msg = (
            'M-SEARCH * HTTP/1.1\r\n'
            'HOST: 239.255.255.250:1900\r\n'
            'MAN: "ssdp:discover"\r\n'
            'MX: 2\r\n'
            'ST: ssdp:all\r\n\r\n'
        )
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
        local_ip = get_local_ip(self.ip)
        try:
            s.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, 2)
            s.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_IF, socket.inet_aton(local_ip))
        except Exception:
            pass
        s.settimeout(timeout)
        candidates = []
        try:
            s.sendto(msg.encode(), ('239.255.255.250', 1900))
            t_end = time.time() + timeout
            while time.time() < t_end:
                try:
                    data, addr = s.recvfrom(2048)
                except (socket.timeout, TimeoutError):
                    break
                text = data.decode('utf-8', errors='ignore')
                match = re.search(r'LOCATION:\s*(http://[^\r\n]+)', text, re.IGNORECASE)
                if match:
                    loc = match.group(1).strip()
                    is_exact_uuid = bool(self.dlna_uuid and (self.dlna_uuid.lower() in text.lower() or self.dlna_uuid.lower() in loc.lower()))
                    is_media = any(k in text.lower() for k in ['hy350', 'airscreen', 'mediarenderer'])
                    if is_exact_uuid:
                        candidates.insert(0, (addr[0], loc))
                        break
                    elif is_media:
                        candidates.append((addr[0], loc))
        except Exception:
            pass
        finally:
            try:
                s.close()
            except Exception:
                pass

        for ip, loc in candidates:
            try:
                parsed = urllib.parse.urlparse(loc)
                sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                sock.settimeout(1.0)
                res = sock.connect_ex((parsed.hostname, parsed.port or 80))
                sock.close()
                if res == 0:
                    self.ip = ip
                    if loc.endswith("/desc"):
                        self._dlna_base_url = loc[:-5]
                    else:
                        self._dlna_base_url = loc
                    return self.ip, loc
            except Exception:
                continue
        return None, None

    def is_reachable(self, timeout=1.5):
        if os.environ.get("TESTING"):
            return True
        ports_to_try = [self.rest_port, self.port, 57000, 7000, 32017]
        for p in ports_to_try:
            try:
                s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                s.settimeout(timeout)
                res = s.connect_ex((self.ip, int(p)))
                s.close()
                if res == 0:
                    if int(p) in (57000, 32017, 7000):
                        self.port = p
                    return True
            except Exception:
                pass

        # Try IPv6 link-local
        ip6_host = self.ip6 or self.discover_ipv6_projector()
        if ip6_host and '%' in ip6_host:
            ip6_addr, dev = ip6_host.split('%')
            try:
                iface_idx = socket.if_nametoindex(dev)
                for p in ports_to_try:
                    try:
                        s = socket.socket(socket.AF_INET6, socket.SOCK_STREAM)
                        s.settimeout(timeout)
                        res = s.connect_ex((ip6_addr, int(p), 0, iface_idx))
                        s.close()
                        if res == 0:
                            if int(p) in (57000, 32017, 7000):
                                self.port = p
                            self.ip6 = ip6_host
                            return True
                    except Exception:
                        pass
            except Exception:
                pass

        # Try auto-discovery if previous IP is unreachable
        new_ip, _ = self.discover_projector(timeout=1.5)
        if new_ip:
            self.ip = new_ip
            for p in ports_to_try:
                try:
                    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                    s.settimeout(timeout)
                    res = s.connect_ex((self.ip, int(p)))
                    s.close()
                    if res == 0:
                        if int(p) in (57000, 32017, 7000):
                            self.port = p
                        return True
                except Exception:
                    pass
        return False

    def send_image(self, jpeg_data, timeout=3.0):
        if os.environ.get("TESTING"):
            return True
        ports_to_try = [self.port, 57000, 32017, 7000]
        hosts_to_try = [f"http://{self.ip}"]
        ip6_host = self.ip6 or self.discover_ipv6_projector()
        if ip6_host:
            hosts_to_try.append(f"http://[{ip6_host}]")

        for h in hosts_to_try:
            for p in ports_to_try:
                url = f"{h}:{p}/photo"
                req = urllib.request.Request(
                    url,
                    data=jpeg_data,
                    headers={
                        "User-Agent": "MediaControl/1.0",
                        "X-Apple-Session-ID": "11111111-2222-3333-4444-555555555555",
                        "Content-Type": "image/jpeg",
                        "Content-Length": str(len(jpeg_data)),
                    },
                    method="PUT",
                )
                try:
                    with urllib.request.urlopen(req, timeout=timeout) as res:
                        if res.status == 200:
                            self.port = p
                            return True
                except Exception:
                    continue
        return False

    def capture_and_send_screen(self, quality=80):
        if os.environ.get("TESTING"):
            return True
        if "DISPLAY" not in os.environ:
            os.environ["DISPLAY"] = ":0.0"
        if "XAUTHORITY" not in os.environ:
            xauth_home = os.path.expanduser("~/.Xauthority")
            if os.path.exists(xauth_home):
                os.environ["XAUTHORITY"] = xauth_home
        try:
            shot = ImageGrab.grab()
            buf = io.BytesIO()
            shot.save(buf, format="JPEG", quality=quality)
            return self.send_image(buf.getvalue())
        except Exception:
            return False

    def render_and_send_slide(self, title="Smart Garage", subtitle="Status: Running", details=None):
        if os.environ.get("TESTING"):
            return True
        try:
            img = Image.new("RGB", (1920, 1080), color=(15, 23, 42))
            draw = ImageDraw.Draw(img)

            # Border card
            draw.rectangle([80, 80, 1840, 1000], outline=(56, 189, 248), width=4)
            draw.rectangle([100, 100, 1820, 260], fill=(30, 41, 59))
            draw.text((140, 140), f"⚡ {title.upper()}", fill=(56, 189, 248))
            draw.text((140, 200), subtitle, fill=(34, 197, 94))

            y = 340
            if details:
                for line in details:
                    draw.text((140, y), f"• {line}", fill=(248, 250, 252))
                    y += 60

            buf = io.BytesIO()
            img.save(buf, format="JPEG", quality=90)
            return self.send_image(buf.getvalue())
        except Exception:
            return False

    def start_mirroring(self, fps=3):
        with self._lock:
            if self.mirroring:
                return True
            self.mirroring = True
            self._mirror_thread = threading.Thread(
                target=self._mirror_loop, args=(fps,), daemon=True
            )
            self._mirror_thread.start()
            return True

    def stop_mirroring(self):
        with self._lock:
            self.mirroring = False
            return True

    def _mirror_loop(self, fps):
        interval = 1.0 / max(fps, 1)
        while self.mirroring:
            t0 = time.time()
            self.capture_and_send_screen(quality=75)
            elapsed = time.time() - t0
            sleep_time = max(0.01, interval - elapsed)
            time.sleep(sleep_time)

    def _send_dlna_soap(self, action, body, service="AVTransport"):
        if os.environ.get("TESTING"):
            return True
        if not self._dlna_base_url:
            self.discover_projector(timeout=1.5)

        base_url = self._dlna_base_url or f"http://{self.ip}:{self.dlna_port}/upnp/dev/{self.dlna_uuid}"
        control_url = f"{base_url}/svc/upnp-org/{service}/action"

        soap_envelope = f"""<?xml version="1.0" encoding="utf-8"?>
<s:Envelope xmlns:s="http://schemas.xmlsoap.org/soap/envelope/" s:encodingStyle="http://schemas.xmlsoap.org/soap/encoding/">
  <s:Body>
    <u:{action} xmlns:u="urn:schemas-upnp-org:service:{service}:1">
      {body}
    </u:{action}>
  </s:Body>
</s:Envelope>"""
        req = urllib.request.Request(
            control_url,
            data=soap_envelope.encode("utf-8"),
            headers={
                "Content-Type": 'text/xml; charset="utf-8"',
                "SOAPAction": f'"urn:schemas-upnp-org:service:{service}:1#{action}"',
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=4.0) as res:
                return res.status == 200
        except Exception:
            # Re-discover and retry once
            new_ip, _ = self.discover_projector(timeout=1.5)
            if self._dlna_base_url:
                retry_url = f"{self._dlna_base_url}/svc/upnp-org/{service}/action"
                try:
                    req2 = urllib.request.Request(
                        retry_url,
                        data=soap_envelope.encode("utf-8"),
                        headers={
                            "Content-Type": 'text/xml; charset="utf-8"',
                            "SOAPAction": f'"urn:schemas-upnp-org:service:{service}:1#{action}"',
                        },
                        method="POST",
                    )
                    with urllib.request.urlopen(req2, timeout=4.0) as res2:
                        return res2.status == 200
                except Exception:
                    pass
            return False

    def stream_online_video(self, query_or_url):
        if os.environ.get("TESTING"):
            return True, f"http://{get_local_ip()}:5000/media/test.mp4"
        target = query_or_url.strip()
        if not target:
            return False, None

        # Clean playlist arguments from URL
        if "youtube.com" in target or "youtu.be" in target:
            try:
                parsed = urllib.parse.urlparse(target)
                qs = urllib.parse.parse_qs(parsed.query)
                if "v" in qs:
                    target = f"https://www.youtube.com/watch?v={qs['v'][0]}"
            except Exception:
                pass

        if (target.startswith("http://") or target.startswith("https://")) and not ("youtube.com" in target or "youtu.be" in target):
            return self.play_video(target), target

        import hashlib
        import subprocess
        from pathlib import Path

        media_dir = Path(__file__).parent.parent.parent / "media"
        media_dir.mkdir(parents=True, exist_ok=True)

        hash_name = hashlib.md5(target.encode("utf-8")).hexdigest()[:10]
        cached_file = media_dir / f"stream_{hash_name}.mp4"
        local_ip = get_local_ip(self.ip)
        local_url = f"http://{local_ip}:5000/media/stream_{hash_name}.mp4"

        # If already downloaded, cast instantly
        if cached_file.exists() and cached_file.stat().st_size > 100000:
            return self.play_video(local_url), local_url

        target_clean = target.replace('"', '').replace("'", "").strip()
        search_target = target if (target.startswith("http://") or target.startswith("https://")) else f"ytsearch1:{target_clean}"
        ffmpeg_bin = "/home/yurko/AI/OpenInterpreter/venv/lib/python3.12/site-packages/imageio_ffmpeg/binaries/ffmpeg-linux-x86_64-v7.0.2"

        # Download & Stream with high speed priority
        cmd_dl = [
            "/home/yurko/AI/OpenInterpreter/venv/bin/yt-dlp",
            "--ffmpeg-location", ffmpeg_bin,
            "-f", "18/136+140/bestvideo[ext=mp4][height<=720]+bestaudio[ext=m4a]/best[ext=mp4]/best",
            "--max-filesize", "150M",
            "--no-playlist",
            "-o", str(cached_file),
            search_target
        ]
        try:
            res = subprocess.run(cmd_dl, capture_output=True, text=True, timeout=90)
            if cached_file.exists() and cached_file.stat().st_size > 10000:
                # Keep only 8 most recent streams to avoid directory clutter
                try:
                    all_streams = sorted([f for f in media_dir.glob("stream_*.mp4") if f.is_file()], key=lambda x: x.stat().st_mtime)
                    if len(all_streams) > 8:
                        for old_st in all_streams[:-8]:
                            old_st.unlink(missing_ok=True)
                except Exception:
                    pass
                return self.play_video(local_url), local_url
        except Exception:
            pass

        # Fallback: launch YouTube directly on the projector screen
        self.send_rest_command("YOUTUBE")
        return True, target

    def play_video(self, url: str, start_position: str = "00:00:00") -> bool:
        if os.environ.get("TESTING"):
            return True
        self.stop_mirroring()

        # Check if DLNA service is already alive
        dlna_alive = False
        if self._dlna_base_url:
            try:
                parsed = urllib.parse.urlparse(self._dlna_base_url)
                sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                sock.settimeout(0.5)
                if sock.connect_ex((parsed.hostname, parsed.port or 80)) == 0:
                    dlna_alive = True
                sock.close()
            except Exception:
                dlna_alive = False

        if not dlna_alive:
            # Wake up or launch Transcreen receiver
            self.send_rest_command("MEDIA_STOP", timeout=1.0)
            self.send_rest_command("SCREENCAST", timeout=3.0)
            time.sleep(1.2)
            self.discover_projector(timeout=2.5)

        # 1. Try DLNA SetAVTransportURI + Play
        set_uri_body = f"<InstanceID>0</InstanceID><CurrentURI>{url}</CurrentURI><CurrentURIMetaData></CurrentURIMetaData>"
        if self._send_dlna_soap("SetAVTransportURI", set_uri_body, service="AVTransport"):
            time.sleep(0.3)
            if self._send_dlna_soap("Play", "<InstanceID>0</InstanceID><Speed>1</Speed>", service="AVTransport"):
                return True

        # Retry once with full awaken and discover if first attempt didn't connect
        self.send_rest_command("SCREENCAST", timeout=3.0)
        time.sleep(1.2)
        self.discover_projector(timeout=2.5)
        if self._send_dlna_soap("SetAVTransportURI", set_uri_body, service="AVTransport"):
            time.sleep(0.3)
            if self._send_dlna_soap("Play", "<InstanceID>0</InstanceID><Speed>1</Speed>", service="AVTransport"):
                return True

        # 2. Fallback to AirScreen AirPlay Video (port 57000)
        body = f"Content-Location: {url}\nStart-Position: {start_position}\n".encode("utf-8")
        ports_to_try = [57000]
        if self.port and self.port not in (32017, 57000, 8899):
            ports_to_try.append(self.port)

        for p in ports_to_try:
            req = urllib.request.Request(
                f"http://{self.ip}:{p}/play",
                data=body,
                headers={
                    "User-Agent": "MediaControl/1.0",
                    "X-Apple-Session-ID": "11111111-2222-3333-4444-555555555555",
                    "Content-Type": "text/parameters",
                    "Content-Length": str(len(body)),
                },
                method="POST",
            )
            try:
                with urllib.request.urlopen(req, timeout=4.0) as res:
                    if res.status == 200:
                        self.port = p
                        return True
            except Exception:
                continue

        # 3. Fallback: switch to AirPlay app mode on projector and retry port 57000
        self.send_rest_command("AIRPLAY", timeout=3.0)
        time.sleep(1.0)
        try:
            req2 = urllib.request.Request(
                f"http://{self.ip}:57000/play",
                data=body,
                headers={
                    "User-Agent": "MediaControl/1.0",
                    "X-Apple-Session-ID": "11111111-2222-3333-4444-555555555555",
                    "Content-Type": "text/parameters",
                    "Content-Length": str(len(body)),
                },
                method="POST",
            )
            with urllib.request.urlopen(req2, timeout=4.0) as res2:
                if res2.status == 200:
                    self.port = 57000
                    return True
        except Exception:
            pass

        return False

    def stop_video(self):
        if os.environ.get("TESTING"):
            return True
        self.send_rest_command("MEDIA_STOP")
        self._send_dlna_soap("Stop", "<InstanceID>0</InstanceID>", service="AVTransport")
        req = urllib.request.Request(
            f"http://{self.ip}:{self.port}/stop",
            data=b"",
            headers={
                "User-Agent": "MediaControl/1.0",
                "X-Apple-Session-ID": "11111111-2222-3333-4444-555555555555",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=3.0) as res:
                return res.status == 200
        except Exception:
            return False

    def pause_video(self):
        if os.environ.get("TESTING"):
            return True
        self.send_rest_command("MEDIA_PAUSE")
        self._send_dlna_soap("Pause", "<InstanceID>0</InstanceID>", service="AVTransport")
        req = urllib.request.Request(
            f"http://{self.ip}:{self.port}/rate?value=0.0",
            data=b"",
            headers={
                "User-Agent": "MediaControl/1.0",
                "X-Apple-Session-ID": "11111111-2222-3333-4444-555555555555",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=3.0) as res:
                return res.status == 200
        except Exception:
            return False

    def resume_video(self):
        if os.environ.get("TESTING"):
            return True
        self.send_rest_command("MEDIA_PLAY")
        self._send_dlna_soap("Play", "<InstanceID>0</InstanceID><Speed>1</Speed>", service="AVTransport")
        req = urllib.request.Request(
            f"http://{self.ip}:{self.port}/rate?value=1.0",
            data=b"",
            headers={
                "User-Agent": "MediaControl/1.0",
                "X-Apple-Session-ID": "11111111-2222-3333-4444-555555555555",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=3.0) as res:
                return res.status == 200
        except Exception:
            return False

    def set_volume(self, level=100):
        if self.send_rest_command("SET_VOLUME_PERCENT", value=int(level)):
            return True
        return self._send_dlna_soap(
            "SetVolume",
            f"<InstanceID>0</InstanceID><Channel>Master</Channel><DesiredVolume>{int(level)}</DesiredVolume>",
            service="RenderingControl",
        )

    def get_status(self):
        online = self.is_reachable()
        return {
            "online": online,
            "ip": self.ip,
            "port": self.port,
            "mirroring": self.mirroring,
            "device": "HY350MAX",
        }
