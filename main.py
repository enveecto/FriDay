"""FRIDAY application entry point and background assistant controller."""

from __future__ import annotations

import asyncio
import os
import threading
from typing import Optional

import customtkinter as ctk
import pyttsx3
import speech_recognition as sr

from core import AIClient, GoogleCalendarManager, MemoryManager, Scheduler
from core.paths import app_path
from modules.desktop import DesktopController
from ui.hud import FridayHUD

try:
    from dotenv import load_dotenv
except ImportError:
    load_dotenv = None


class FridayCore:
    """The assistant's deterministic commands and AI-assisted task execution."""

    def __init__(self):
        self.ai = AIClient()
        self.memory = MemoryManager()
        self.scheduler = Scheduler()
        self.calendar = GoogleCalendarManager()
        self.desktop = DesktopController()

    async def process_query(self, text, logger):
        raw_query = text.strip()
        query = raw_query.casefold()
        memory_response = self._handle_memory_commands(raw_query, query, logger)
        if memory_response:
            return memory_response

        if not self.ai.available():
            return await self.ai.query(text, logger=logger)

        context = self._build_context()
        response = await self.ai.query(text, context=context, logger=logger)
        self._process_tasks(response, logger)
        return response

    def _build_context(self):
        events = self.calendar.get_upcoming_events()
        if not events:
            return "No connected calendar events are available."
        lines = ["Upcoming Google Calendar events:"]
        for event in events:
            start = event.get("start", {}).get("dateTime", event.get("start", {}).get("date", ""))
            lines.append(f"- {start}: {event.get('summary', '(untitled)')}")
        return "\n".join(lines)

    def _handle_memory_commands(self, raw_query, query, logger):
        if query.startswith("remember "):
            fact = raw_query[len("remember "):].strip()
            try:
                self.memory.remember(fact)
            except ValueError as exc:
                return {"reply": str(exc), "info_panel": "", "tasks": []}
            logger("MEMORY // Stored a local memory.")
            return {"reply": "Memory stored.", "info_panel": f"Remembered: {fact}", "tasks": []}

        if query == "recall" or query.startswith("recall ") or query.startswith("what did i"):
            search = raw_query[len("recall"):].strip() if query.startswith("recall") else raw_query
            results = self.memory.recall(query=search)
            if not results:
                return {"reply": "No matching memories found.", "info_panel": "Your local memory store has no match.", "tasks": []}
            lines = [f"#{memory_id}  {fact}\n    {category} · {timestamp}" for memory_id, fact, category, timestamp in results]
            return {"reply": "Here is what I remember.", "info_panel": "\n\n".join(lines), "tasks": []}

        if query.startswith("forget ") or query.startswith("delete memory "):
            prefix_length = len("forget ") if query.startswith("forget ") else len("delete memory ")
            target = raw_query[prefix_length:].strip()
            try:
                if target.isdigit():
                    self.memory.forget(memory_id=int(target))
                else:
                    self.memory.forget(query=target)
                return {"reply": "Memory removed.", "info_panel": f"Removed matching memory: {target}", "tasks": []}
            except (LookupError, ValueError) as exc:
                logger(f"MEMORY // Forget failed: {exc}")
                return {"reply": "I could not remove that memory.", "info_panel": str(exc), "tasks": []}

        return None

    def _process_tasks(self, response, logger):
        for task in response.get("tasks", []):
            action = task.get("action")
            value = task.get("value", "")
            try:
                if action == "open_url":
                    self.desktop.open_url(value)
                elif action == "launch":
                    self.desktop.launch(value)
                elif action == "play_youtube":
                    self.desktop.play_youtube(value)
                elif action == "get_directions":
                    origin, destination, mode = [part.strip() for part in value.split("|", 2)]
                    self.desktop.get_directions(origin, destination, mode)
                elif action == "gcal_create":
                    start, duration, title = [part.strip() for part in value.split("|", 2)]
                    self.calendar.create_event(start, duration, title)
                elif action == "media_control":
                    self.desktop.media_control(value)
                elif action == "schedule":
                    when, reminder = [part.strip() for part in value.split("|", 1)]
                    self.scheduler.add_event(when, reminder)
                else:
                    logger(f"ACTION // Ignored unsupported task: {action}")
                    continue
                logger(f"ACTION // Completed {action}.")
            except Exception as exc:
                logger(f"ACTION // {action} failed: {exc}")


class FridayController:
    """Owns the one asyncio loop used for voice, TTS, AI, and manual commands."""

    WAKE_WORDS = ("friday", "hey friday", "ok friday", "wake friday", "wake up friday", "hello friday")

    def __init__(self, ui: FridayHUD):
        self.ui = ui
        self.core: Optional[FridayCore] = None
        self.loop: Optional[asyncio.AbstractEventLoop] = None
        self.stop_signal: Optional[asyncio.Event] = None
        self.ready = threading.Event()
        self.thread = threading.Thread(target=self._thread_main, name="friday-core", daemon=True)
        self.tts_engine = None
        self.speech_lock: Optional[asyncio.Lock] = None

    def start(self):
        self.thread.start()

    def submit(self, text: str):
        if not self.ready.is_set() or self.loop is None:
            self.ui.post_log("CORE // Still starting; please try again in a moment.")
            self.ui.post_state("idle")
            return
        asyncio.run_coroutine_threadsafe(self._handle_query(text, source="TEXT"), self.loop)

    def shutdown(self):
        if self.loop and self.stop_signal:
            self.loop.call_soon_threadsafe(self.stop_signal.set)

    def _thread_main(self):
        asyncio.run(self._run())

    async def _run(self):
        self.loop = asyncio.get_running_loop()
        self.stop_signal = asyncio.Event()
        self.speech_lock = asyncio.Lock()
        try:
            self.core = FridayCore()
            self.ui.core = self.core  # Plain Python reference; all Tk changes remain queued.
            self._initialize_tts()
            self.ready.set()
            ai_status = "CORE ONLINE / AI CONNECTED" if self.core.ai.available() else "CORE ONLINE / LOCAL MODE"
            self.ui.post_connection(ai_status)
            self.ui.post_log("CORE // Systems initialized. Text commands are ready.")
        except Exception as exc:
            self.ready.set()
            self.ui.post_connection("CORE STARTUP FAILED", healthy=False)
            self.ui.post_log(f"CORE // Startup failed: {exc}")
            return

        voice_task = asyncio.create_task(self._voice_loop(), name="friday-voice")
        await self.stop_signal.wait()
        voice_task.cancel()
        try:
            await voice_task
        except asyncio.CancelledError:
            pass

    def _initialize_tts(self):
        try:
            self.tts_engine = pyttsx3.init()
            self.tts_engine.setProperty("rate", 185)
            self.ui.post_log("VOICE // Text-to-speech ready.")
        except Exception as exc:
            self.tts_engine = None
            self.ui.post_log(f"VOICE // TTS unavailable: {exc}")

    async def _handle_query(self, text: str, source: str):
        if not self.core:
            return
        self.ui.post_state("processing")
        self.ui.post_log(f"{source} // Processing request.")
        try:
            response = await self.core.process_query(text, self.ui.post_log)
            info = response.get("info_panel", "")
            reply = response.get("reply", "")
            if info:
                self.ui.post_readout(info)
            if reply:
                self.ui.post_response(reply)
                await self._speak(reply)
        except Exception as exc:
            self.ui.post_log(f"CORE // Request error: {exc}")
            self.ui.post_readout(f"Unable to complete this request.\n\n{exc}")
        finally:
            self.ui.post_state("idle")

    async def _speak(self, text: str):
        if not self.tts_engine or not self.speech_lock:
            return
        async with self.speech_lock:
            self.ui.post_state("speaking")
            self.ui.post_log("VOICE // Delivering response.")
            try:
                await asyncio.to_thread(self._speak_sync, text[:800])
            except Exception as exc:
                self.ui.post_log(f"VOICE // Playback error: {exc}")

    def _speak_sync(self, text: str):
        self.tts_engine.say(text)
        self.tts_engine.runAndWait()

    async def _voice_loop(self):
        try:
            recognizer, microphone = await asyncio.to_thread(self._setup_voice_input)
        except Exception as exc:
            self.ui.post_log(f"VOICE // Microphone unavailable; text mode remains active. ({exc})")
            return

        self.ui.post_log("VOICE // Listening for a FRIDAY wake word.")
        while self.stop_signal and not self.stop_signal.is_set():
            await self._deliver_due_reminders()
            try:
                phrase = await asyncio.wait_for(
                    asyncio.to_thread(self._listen_once, recognizer, microphone), timeout=22
                )
            except (asyncio.TimeoutError, sr.WaitTimeoutError):
                continue
            except Exception as exc:
                self.ui.post_log(f"VOICE // Listener error: {exc}")
                await asyncio.sleep(1)
                continue

            cleaned = phrase.strip()
            if any(wake_word in cleaned.casefold() for wake_word in self.WAKE_WORDS):
                self.ui.post_log(f"VOICE // Wake word detected: {cleaned}")
                await self._handle_query(cleaned, source="VOICE")

    def _setup_voice_input(self):
        recognizer = sr.Recognizer()
        recognizer.dynamic_energy_threshold = True
        recognizer.pause_threshold = 0.8
        device_index = os.environ.get("MIC_DEVICE_INDEX")
        microphone = sr.Microphone(device_index=int(device_index)) if device_index else sr.Microphone()
        with microphone as source:
            recognizer.adjust_for_ambient_noise(source, duration=0.7)
        return recognizer, microphone

    @staticmethod
    def _listen_once(recognizer, microphone):
        with microphone as source:
            audio = recognizer.listen(source, timeout=7, phrase_time_limit=15)
        return recognizer.recognize_google(audio)

    async def _deliver_due_reminders(self):
        if not self.core:
            return
        for event_id, task in self.core.scheduler.get_due_events():
            self.ui.post_log(f"REMINDER // {task}")
            self.ui.post_response(f"Reminder: {task}")
            await self._speak(f"Reminder: {task}")
            self.core.scheduler.mark_event_done(event_id)


def load_environment():
    if load_dotenv:
        load_dotenv(dotenv_path=app_path(".env"), override=False)


def run():
    load_environment()
    ctk.set_appearance_mode("dark")
    ctk.set_default_color_theme("dark-blue")
    app = FridayHUD()
    controller = FridayController(app)
    app.set_command_handler(controller.submit)
    app.set_close_handler(controller.shutdown)
    controller.start()
    app.mainloop()


if __name__ == "__main__":
    run()
