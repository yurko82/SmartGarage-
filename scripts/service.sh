#!/usr/bin/env bash
# Smart Garage Systemd Service Manager

ACTION="${1:-status}"

case "$ACTION" in
    enable)
        systemctl --user daemon-reload
        systemctl --user enable smartgarage.service
        systemctl --user start smartgarage.service
        echo "✅ Smart Garage service enabled and started."
        ;;
    disable)
        systemctl --user stop smartgarage.service
        systemctl --user disable smartgarage.service
        echo "🛑 Smart Garage service disabled."
        ;;
    start)
        systemctl --user start smartgarage.service
        echo "▶️ Smart Garage service started."
        ;;
    stop)
        systemctl --user stop smartgarage.service
        echo "⏹️ Smart Garage service stopped."
        ;;
    restart)
        systemctl --user restart smartgarage.service
        echo "🔄 Smart Garage service restarted."
        ;;
    status)
        systemctl --user status smartgarage.service
        ;;
    logs)
        journalctl --user -u smartgarage.service -f
        ;;
    *)
        echo "Usage: $0 {enable|disable|start|stop|restart|status|logs}"
        exit 1
        ;;
esac
