"""Optional native startup view. Uses only stdlib; the console remains a fallback."""
from __future__ import annotations

from collections import deque
import json
import os
from pathlib import Path
import queue
import signal
import subprocess
import sys
import threading
from urllib.parse import urlsplit
import webbrowser


PROJECT = Path(__file__).resolve().parent
EVENT_PREFIX = "FRIB_STARTUP_EVENT="
STAGES = ("Preparing application", "Preparing AI", "Starting workspace", "Ready")
STAGE_IDS = ("application", "ai", "workspace", "ready")


def parse_event(line):
    """Accept only our small progress protocol, never a URL from a log message."""
    if not line.startswith(EVENT_PREFIX):
        return None
    try:
        event = json.loads(line[len(EVENT_PREFIX):])
        if not isinstance(event, dict) or event.get("stage") not in STAGE_IDS:
            return None
        if not isinstance(event.get("message"), str) or len(event["message"]) > 1000:
            return None
        if event["stage"] == "ready":
            parsed = urlsplit(event.get("url", ""))
            if (parsed.scheme != "http" or parsed.hostname != "127.0.0.1"
                    or parsed.username is not None or parsed.password is not None
                    or parsed.path not in ("", "/") or parsed.query or parsed.fragment
                    or parsed.port is None or not 1024 <= parsed.port <= 65535
                    or type(event.get("owned")) is not bool):
                return None
        return event
    except (ValueError, TypeError):
        return None


def friendly_failure(lines):
    diagnostic = "\n".join(lines).casefold()
    if "certificate_verify_failed" in diagnostic or "certificate verify failed" in diagnostic:
        return "The secure download could not be verified. Check your network or certificate settings, then choose Retry. Show details for the exact error."
    if "port " in diagnostic and ("in use" in diagnostic or "already" in diagnostic):
        return "Another application is using a required connection. Close the earlier FRIB startup window, then choose Retry. Show details to see which port is busy."
    if "another frib" in diagnostic or "frib is starting" in diagnostic:
        return "FRIB is already starting in another window. Let that startup finish, or stop it there before choosing Retry."
    if any(word in diagnostic for word in ("download", "connection", "network", "timed out")):
        return "Setup could not finish. Check your internet connection and free disk space, then choose Retry. Show details for the exact cause."
    return "FRIB could not finish starting. Open Show details for the cause, correct it, then choose Retry. Your saved work is retained."


class StartupSession:
    """Own one startup child at a time; the reader confirms cleanup before retry."""
    def __init__(self, arguments, project=PROJECT):
        self.arguments = list(arguments)
        self.project = Path(project)
        self.events = queue.Queue()
        self.process = None
        self.running = False
        self.stopping = False
        self.generation = 0
        self.shutdown_thread = None

    def start(self):
        if self.running:
            return False
        env = {**os.environ, "FRIB_STARTUP_WINDOW": "1", "PYTHONUNBUFFERED": "1"}
        if os.name == "nt":
            env["FRIB_STARTUP_CONSOLE_GROUP"] = "1"
        process = subprocess.Popen([sys.executable, "-u", str(self.project / "start.py"), *self.arguments],
            cwd=self.project, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, encoding="utf-8", errors="replace", start_new_session=os.name == "posix",
            creationflags=subprocess.CREATE_NEW_PROCESS_GROUP if os.name == "nt" else 0)
        self.process = process
        self.running = True
        self.stopping = False
        self.generation += 1
        generation = self.generation

        def read():
            try:
                for line in process.stdout:
                    self.events.put((generation, "line", line.rstrip("\r\n")))
            finally:
                process.stdout.close()
                code = process.wait()
                self.events.put((generation, "exit", code))
        threading.Thread(target=read, name="frib-startup-output", daemon=True).start()
        return True

    def completed(self, generation):
        if generation != self.generation:
            return False
        self.running = False
        self.process = None
        return True

    def stop(self):
        process = self.process
        if not self.running or process is None or self.stopping:
            return False
        self.stopping = True

        def shutdown():
            try:
                # start.py forwards this to the managed launcher, which waits
                # for its own API/dashboard/model processes to stop safely.
                if process.poll() is None:
                    if os.name == "posix":
                        os.killpg(process.pid, signal.SIGTERM)
                    else:
                        process.terminate()
                process.wait(timeout=35)
            except subprocess.TimeoutExpired:
                # The group was created exclusively for this child. Never
                # discover, signal or stop a pre-existing FRIB/Ollama process.
                if process.poll() is None:
                    if os.name == "posix":
                        os.killpg(process.pid, signal.SIGKILL)
                    else:
                        process.kill()
                    process.wait(timeout=5)
            except ProcessLookupError:
                pass
        self.shutdown_thread = threading.Thread(target=shutdown, name="frib-startup-stop", daemon=True)
        self.shutdown_thread.start()
        return True


class StartupWindow:
    def __init__(self, root, tk, ttk, messagebox, arguments):
        self.root, self.tk, self.ttk, self.messagebox = root, tk, ttk, messagebox
        self.session = StartupSession(arguments)
        self.lines = deque(maxlen=800)
        self.url = None
        self.owned = True
        self.ready = False
        self.failed = False
        self.closing = False
        self.details_visible = False
        self.stage_index = 0
        root.title("FRIB · Starting your workspace")
        root.geometry("670x410")
        root.minsize(590, 400)
        root.protocol("WM_DELETE_WINDOW", self.close)
        content = ttk.Frame(root, padding=26)
        content.pack(fill="both", expand=True)
        ttk.Label(content, text="Your FRIB workspace", font=("Helvetica", 23, "bold")).pack(anchor="w")
        ttk.Label(content, text="One place for your data, procedures, and AI guidance.", wraplength=590).pack(anchor="w", pady=(7, 20))
        stages = ttk.Frame(content)
        stages.pack(fill="x")
        self.stage_labels = []
        for index, name in enumerate(STAGES):
            label = ttk.Label(stages, text=f"{index + 1}. {name}", wraplength=135)
            label.grid(row=0, column=index, sticky="nw", padx=(0, 12))
            stages.columnconfigure(index, weight=1)
            self.stage_labels.append(label)
        self.progress = ttk.Progressbar(content, mode="indeterminate")
        self.progress.pack(fill="x", pady=(16, 18))
        self.heading = ttk.Label(content, text="Preparing application", font=("Helvetica", 16, "bold"))
        self.heading.pack(anchor="w")
        self.description = ttk.Label(content, text="Checking the application and its dependencies…", wraplength=590)
        self.description.pack(anchor="w", pady=(7, 14))
        actions = ttk.Frame(content)
        actions.pack(fill="x", pady=(4, 4))
        self.open_button = ttk.Button(actions, text="Open workspace", command=self.open_workspace, state="disabled")
        self.open_button.pack(side="left")
        self.retry_button = ttk.Button(actions, text="Retry", command=self.retry, state="disabled")
        self.retry_button.pack(side="left", padx=8)
        self.stop_button = ttk.Button(actions, text="Cancel startup", command=self.stop)
        self.stop_button.pack(side="right")
        self.details_button = ttk.Button(content, text="Show details", command=self.toggle_details)
        self.details_button.pack(anchor="w", pady=(12, 0))
        self.details = ttk.Frame(content)
        self.log = tk.Text(self.details, height=11, wrap="word", state="disabled", font=("Menlo", 10))
        scrollbar = ttk.Scrollbar(self.details, orient="vertical", command=self.log.yview)
        self.log.configure(yscrollcommand=scrollbar.set)
        self.log.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")
        self.retry()
        root.after(100, self.poll)

    def retry(self):
        if self.session.running:
            return
        self.url, self.owned, self.ready, self.stage_index = None, True, False, 0
        self.failed = False
        self.root.title("FRIB · Starting your workspace")
        self.lines.clear()
        self.log.configure(state="normal")
        self.log.delete("1.0", "end")
        self.log.configure(state="disabled")
        self.open_button.configure(state="disabled")
        self.retry_button.configure(state="disabled")
        self.stop_button.configure(text="Cancel startup", state="normal")
        self.heading.configure(text=STAGES[0])
        self.description.configure(text="Checking the application and its dependencies…")
        self.paint_stages()
        self.progress.start(14)
        try:
            self.session.start()
        except OSError as exc:
            self.lines.append(str(exc))
            self.failure()

    def paint_stages(self):
        for index, label in enumerate(self.stage_labels):
            prefix = "!" if self.failed and index == self.stage_index else "✓" if index < self.stage_index or self.ready else "●" if index == self.stage_index else str(index + 1) + "."
            label.configure(text=f"{prefix} {STAGES[index]}")

    def apply_event(self, event):
        index = STAGE_IDS.index(event["stage"])
        if index < self.stage_index or self.session.stopping:
            return
        self.stage_index = index
        self.heading.configure(text=STAGES[index])
        self.description.configure(text=event["message"])
        if event["stage"] == "ready":
            self.ready, self.url, self.owned = True, event["url"], event["owned"]
            self.progress.stop()
            self.open_button.configure(state="normal")
            self.stop_button.configure(text="Stop workspace" if self.owned else "Close window")
            self.root.title("FRIB · Workspace ready")
        self.paint_stages()

    def failure(self):
        self.ready, self.failed = False, True
        self.progress.stop()
        self.heading.configure(text="Let’s get startup working")
        self.description.configure(text=friendly_failure(self.lines))
        self.retry_button.configure(state="normal")
        self.stop_button.configure(text="Close window", state="normal")
        self.root.title("FRIB · Startup needs attention")
        self.paint_stages()

    def poll(self):
        try:
            while True:
                generation, kind, value = self.session.events.get_nowait()
                if generation != self.session.generation:
                    continue
                if kind == "line":
                    event = parse_event(value)
                    if event is not None:
                        self.apply_event(event)
                    else:
                        self.lines.append(value)
                        self.log.configure(state="normal")
                        self.log.insert("end", value + "\n")
                        if int(self.log.index("end-1c").split(".")[0]) > 800:
                            self.log.delete("1.0", "2.0")
                        self.log.see("end")
                        self.log.configure(state="disabled")
                elif kind == "exit":
                    stopping = self.session.stopping
                    self.session.completed(generation)
                    if self.closing:
                        self.root.destroy()
                        return
                    if self.ready and not self.owned and value == 0:
                        self.description.configure(text="Your existing workspace is ready. Its original startup window controls shutdown.")
                        self.stop_button.configure(text="Close window")
                    elif stopping or value == 0:
                        self.ready = False
                        self.progress.stop()
                        self.open_button.configure(state="disabled")
                        self.heading.configure(text="Workspace stopped")
                        self.description.configure(text="Your saved work is retained. Choose Retry to open FRIB again.")
                        self.stop_button.configure(text="Close window", state="normal")
                        self.retry_button.configure(state="normal")
                    else:
                        self.ready = False
                        self.open_button.configure(state="disabled")
                        self.failure()
        except queue.Empty:
            pass
        self.root.after(100, self.poll)

    def open_workspace(self):
        if self.url:
            webbrowser.open(self.url)

    def stop(self):
        if not self.session.running or not self.owned:
            self.close()
            return
        self.description.configure(text="Stopping the services started by this window. Your saved work is retained…")
        self.stop_button.configure(state="disabled")
        self.session.stop()

    def close(self):
        if not self.session.running:
            self.root.destroy()
        elif not self.owned:
            self.closing = True
        elif self.messagebox.askyesno("Stop FRIB?", "Closing this window will stop this FRIB workspace. Your saved work is retained.\n\nStop and close?", parent=self.root):
            self.closing = True
            self.stop()

    def toggle_details(self):
        self.details_visible = not self.details_visible
        if self.details_visible:
            self.details.pack(fill="both", expand=True, pady=(12, 0))
            self.root.geometry("760x650")
        else:
            self.details.pack_forget()
            self.root.geometry("670x410")
        self.details_button.configure(text="Hide details" if self.details_visible else "Show details")


def main(arguments=None):
    arguments = list(sys.argv[1:] if arguments is None else arguments)
    try:
        import tkinter as tk
        from tkinter import ttk, messagebox
    except ImportError as exc:
        print(f"Native startup view is unavailable ({exc}); continuing in this terminal.", flush=True)
        return subprocess.call([sys.executable, str(PROJECT / "start.py"), *arguments], cwd=PROJECT)
    try:
        root = tk.Tk()
    except tk.TclError as exc:
        print(f"Native startup view is unavailable ({exc}); continuing in this terminal.", flush=True)
        return subprocess.call([sys.executable, str(PROJECT / "start.py"), *arguments], cwd=PROJECT)
    window = StartupWindow(root, tk, ttk, messagebox, arguments)
    previous = {}
    def shutdown(_number, _frame):
        window.closing = True
        if window.session.running:
            window.stop()
        else:
            root.destroy()
    for name in ("SIGINT", "SIGTERM", "SIGHUP"):
        number = getattr(signal, name, None)
        if number is not None:
            previous[number] = signal.getsignal(number)
            signal.signal(number, shutdown)
    try:
        root.mainloop()
    finally:
        if window.session.running:
            window.session.stop()
        if window.session.shutdown_thread is not None:
            window.session.shutdown_thread.join(timeout=42)
        for number, handler in previous.items():
            signal.signal(number, handler)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
