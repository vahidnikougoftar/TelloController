#!/usr/bin/env python3
"""Simple Tkinter UI for driving a DJI Tello drone."""

import os
import platform
import queue
import socket
import subprocess
import threading
import tkinter as tk
from tkinter import messagebox
from tkinter import scrolledtext
from tkinter import ttk

TELLO_IP = "192.168.10.1"
TELLO_PORT = 8889
LOCAL_PORT = 9000
MOVE_DISTANCE_CM = 50
NETWORKSETUP_PATH = "/usr/sbin/networksetup" if os.path.exists("/usr/sbin/networksetup") else "networksetup"


class TelloController:
    """Low-level UDP interface to the Tello drone."""

    def __init__(self, log_callback):
        self.log_callback = log_callback
        self.sock = None
        self.receiver_thread = None
        self.running = False
        self.lock = threading.Lock()

    def start(self):
        with self.lock:
            if self.sock:
                return
            self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            self.sock.bind(("", LOCAL_PORT))
            self.sock.settimeout(2.0)
            self.running = True
            self.receiver_thread = threading.Thread(target=self._listen, daemon=True)
            self.receiver_thread.start()
            self.log_callback("UDP socket ready on port 9000.")

    def stop(self):
        with self.lock:
            self.running = False
            if self.sock:
                try:
                    self.sock.close()
                finally:
                    self.sock = None
            self.log_callback("Socket closed.")

    def _listen(self):
        while self.running:
            try:
                response, _ = self.sock.recvfrom(1024)
            except socket.timeout:
                continue
            except OSError:
                break
            else:
                decoded = response.decode("utf-8", errors="ignore")
                self.log_callback(f"<<< {decoded}")

    def send_command(self, command: str) -> bool:
        self.start()
        try:
            self.sock.sendto(command.encode("utf-8"), (TELLO_IP, TELLO_PORT))
            self.log_callback(f">>> {command}")
            return True
        except OSError as exc:
            self.log_callback(f"Send failed: {exc}")
            return False


class TelloApp:
    """Tkinter front-end that exposes Wi-Fi helpers and drone controls."""

    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title("Tello Controller")
        self.controller = TelloController(self._queue_log)
        self.command_mode = False
        self.log_queue: queue.Queue[str] = queue.Queue()

        self.interface_var = tk.StringVar(value="en0")
        self.ssid_var = tk.StringVar()
        self.password_var = tk.StringVar()

        self._build_ui()
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)
        self.root.after(100, self._flush_log_queue)

    def _build_ui(self):
        wifi_frame = ttk.LabelFrame(self.root, text="Wi-Fi Helper")
        wifi_frame.pack(fill="x", padx=12, pady=(12, 6))

        ttk.Label(wifi_frame, text="Interface").grid(row=0, column=0, sticky="w", padx=4, pady=2)
        ttk.Entry(wifi_frame, textvariable=self.interface_var, width=12).grid(row=0, column=1, sticky="ew", padx=4, pady=2)

        ttk.Label(wifi_frame, text="SSID").grid(row=1, column=0, sticky="w", padx=4, pady=2)
        ttk.Entry(wifi_frame, textvariable=self.ssid_var).grid(row=1, column=1, sticky="ew", padx=4, pady=2)

        ttk.Label(wifi_frame, text="Password (optional)").grid(row=2, column=0, sticky="w", padx=4, pady=2)
        ttk.Entry(wifi_frame, textvariable=self.password_var, show="*").grid(row=2, column=1, sticky="ew", padx=4, pady=2)

        self.connect_button = ttk.Button(wifi_frame, text="Connect to Drone", command=self.connect_wifi)
        self.connect_button.grid(row=3, column=0, columnspan=2, sticky="ew", padx=4, pady=(6, 2))

        wifi_frame.columnconfigure(1, weight=1)

        control_frame = ttk.LabelFrame(self.root, text="Drone Commands")
        control_frame.pack(fill="x", padx=12, pady=6)

        ttk.Button(control_frame, text="Enter Command Mode", command=self.enter_command_mode).grid(row=0, column=0, columnspan=2, sticky="ew", padx=4, pady=4)
        ttk.Button(control_frame, text="Takeoff", command=lambda: self._send_simple("takeoff")).grid(row=1, column=0, sticky="ew", padx=4, pady=4)
        ttk.Button(control_frame, text="Land", command=lambda: self._send_simple("land")).grid(row=1, column=1, sticky="ew", padx=4, pady=4)

        movement_frame = ttk.Frame(control_frame)
        movement_frame.grid(row=2, column=0, columnspan=2, pady=6)

        ttk.Button(movement_frame, text="Left", width=12, command=lambda: self._send_move("left")).grid(row=0, column=0, padx=4, pady=4)
        ttk.Button(movement_frame, text="Right", width=12, command=lambda: self._send_move("right")).grid(row=0, column=2, padx=4, pady=4)
        ttk.Button(movement_frame, text="Forward", width=12, command=lambda: self._send_move("forward")).grid(row=0, column=1, padx=4, pady=4)
        ttk.Button(movement_frame, text="Backward", width=12, command=lambda: self._send_move("back")).grid(row=1, column=1, padx=4, pady=4)

        log_frame = ttk.LabelFrame(self.root, text="Log")
        log_frame.pack(fill="both", expand=True, padx=12, pady=(6, 12))

        self.log_view = scrolledtext.ScrolledText(log_frame, height=12, state="disabled")
        self.log_view.pack(fill="both", expand=True, padx=4, pady=4)

    def connect_wifi(self):
        if platform.system() != "Darwin":
            messagebox.showinfo("Wi-Fi", "The automatic Wi-Fi connect button only works on macOS. Join the TELLO network manually on other systems.")
            return

        ssid = self.ssid_var.get().strip()
        if not ssid:
            messagebox.showwarning("Missing SSID", "Enter the Tello network SSID (e.g., TELLO-XXXXXX).")
            return

        interface = self.interface_var.get().strip() or "en0"
        password = self.password_var.get().strip()

        self.connect_button.config(state="disabled")
        thread = threading.Thread(target=self._connect_wifi_thread, args=(interface, ssid, password), daemon=True)
        thread.start()

    def _connect_wifi_thread(self, interface: str, ssid: str, password: str):
        cmd = [NETWORKSETUP_PATH, "-setairportnetwork", interface, ssid]
        if password:
            cmd.append(password)

        self._queue_log(f"Connecting {interface} to {ssid}...")
        try:
            completed = subprocess.run(cmd, capture_output=True, text=True, check=True)
            stdout = completed.stdout.strip()
            stderr = completed.stderr.strip()
            if stdout:
                self._queue_log(stdout)
            if stderr:
                self._queue_log(stderr)
            self._notify_user("Wi-Fi", f"Connected to {ssid} via {interface}.")
        except FileNotFoundError:
            self._notify_user("Wi-Fi", "networksetup tool not found. Update the script or connect manually.")
            self._queue_log("networksetup utility not available.")
        except subprocess.CalledProcessError as exc:
            msg = exc.stderr.strip() or exc.stdout.strip() or str(exc)
            self._notify_user("Wi-Fi", f"Failed to connect: {msg}")
            self._queue_log(f"Wi-Fi connect failed: {msg}")
        finally:
            self.root.after(0, lambda: self.connect_button.config(state="normal"))

    def enter_command_mode(self):
        if self.controller.send_command("command"):
            self.command_mode = True
            self._queue_log("Command mode engaged.")

    def _send_simple(self, keyword: str):
        if not self._ensure_command_mode():
            return
        self.controller.send_command(keyword)

    def _send_move(self, direction: str):
        if not self._ensure_command_mode():
            return
        command = f"{direction} {MOVE_DISTANCE_CM}"
        self.controller.send_command(command)

    def _ensure_command_mode(self) -> bool:
        if not self.command_mode:
            messagebox.showwarning("Command Mode", "Click 'Enter Command Mode' before flying.")
            return False
        return True

    def _queue_log(self, text: str):
        self.log_queue.put(text)

    def _flush_log_queue(self):
        try:
            while True:
                line = self.log_queue.get_nowait()
                self.log_view.config(state="normal")
                self.log_view.insert(tk.END, line + "\n")
                self.log_view.see(tk.END)
                self.log_view.config(state="disabled")
        except queue.Empty:
            pass
        finally:
            self.root.after(100, self._flush_log_queue)

    def _notify_user(self, title: str, message: str):
        self.root.after(0, lambda: messagebox.showinfo(title, message))

    def _on_close(self):
        self.controller.stop()
        self.root.destroy()


def main():
    root = tk.Tk()
    app = TelloApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
