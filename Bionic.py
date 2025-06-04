#!/usr/bin/env python3
import os
import re
import shutil
import threading
from dataclasses import dataclass, field
from queue import Queue
from pathlib import Path
import subprocess
import sys
import logging
import tempfile
from concurrent.futures import ThreadPoolExecutor
from tkinter import filedialog, messagebox
from typing import Dict

from settings import Settings, load_settings, save_settings
try:
    import customtkinter as ctk
except ImportError:  # pragma: no cover - allow import without GUI deps
    ctk = None  # type: ignore
from zipfile import ZipFile, BadZipFile
from contextlib import contextmanager
from html.parser import HTMLParser
from math import ceil, log


@dataclass
class AppState:
    """Store user selections for files and destination folder."""

    selected_file_paths: list[str] = field(default_factory=list)
    selected_dest_folder: str = ""


# Application state and logging
state = AppState()

# Load user settings
settings = load_settings()

translations: Dict[str, Dict[str, str]] = {
    "en": {
        "select_files": "Select EPUB Files",
        "select_destination": "Select Destination Folder",
        "generate": "Generate Modified EPUBs",
        "cancel": "Cancel",
        "open_destination": "Open Destination",
        "open_when_done": "Open when done",
        "no_files": "No files selected",
        "files_selected": "{count} files selected",
        "no_dest": "No destination folder selected",
        "destination": "Destination: {path}",
    },
    "es": {
        "select_files": "Seleccionar EPUBs",
        "select_destination": "Seleccionar carpeta destino",
        "generate": "Generar EPUBs",
        "cancel": "Cancelar",
        "open_destination": "Abrir destino",
        "open_when_done": "Abrir al terminar",
        "no_files": "Ning\u00fan archivo seleccionado",
        "files_selected": "{count} archivos seleccionados",
        "no_dest": "Sin carpeta destino",
        "destination": "Destino: {path}",
    },
}

def t(key: str, **kwargs) -> str:
    return translations.get(settings.language, translations["en"]).get(key, key).format(**kwargs)

logger = logging.getLogger(__name__)

# Queue for safely communicating UI updates from worker threads
ui_queue = Queue()
# Store per-file progress bars
progress_bars: Dict[str, tuple] = {}
# Overall progress bar reference created at runtime
overall_progress = None
ui_poll_id = None
cancel_event = threading.Event()


@contextmanager
def change_directory(path: Path):
    """Context manager to temporarily change the working directory."""
    prev_cwd = Path.cwd()
    os.chdir(path)
    try:
        yield
    finally:
        os.chdir(prev_cwd)

class MyHTMLParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.data_html = []

    def handle_starttag(self, tag, attrs):
        attributes = [attr for attr in attrs]
        self.data_html.append((("Start tag:", tag), ("attr:", attributes)))

    def handle_endtag(self, tag):
        self.data_html.append(("End tag:", tag))

    def handle_data(self, data):
        self.data_html.append(("Data:", data))

def bolding(text: str) -> str:
    """Return text with initial letters of each word bolded."""
    tokens = re.findall(r'\w+|[^\w\s]', text)
    result = []
    for token in tokens:
        if re.fullmatch(r'[^\w\s]', token):
            if result:
                result[-1] += token
            else:
                result.append(token)
        else:
            point = ceil(log(len(token), 2)) if len(token) > 3 else 1
            processed = f"<b>{token[:point]}</b>{token[point:]}"
            result.append(processed)
    return ' '.join(result)

def select_epubs() -> list[str]:
    """Prompt for EPUB files and update the label.

    Returns a list of unique file paths selected by the user.
    """
    file_paths = filedialog.askopenfilenames(filetypes=[("EPUB files", "*.epub")])
    unique_paths = [p for p in dict.fromkeys(file_paths) if Path(p).exists()]
    state.selected_file_paths = list(unique_paths)
    file_label.configure(
        text=t("files_selected", count=len(unique_paths)) if unique_paths else t("no_files")
    )
    return state.selected_file_paths

def select_destination_folder() -> str:
    """Prompt user for destination folder and ensure subfolder exists."""
    dest_folder = filedialog.askdirectory()
    if dest_folder:
        settings.dest_subfolder = subfolder_entry.get() or settings.dest_subfolder
        dest_path = Path(dest_folder) / settings.dest_subfolder
        dest_path.mkdir(parents=True, exist_ok=True)
        dest_folder_label.configure(text=truncate_text(t("destination", path=dest_path), 50))
        state.selected_dest_folder = str(dest_path)
        settings.dest_folder = str(dest_folder)
    else:
        dest_folder_label.configure(text=t("no_dest"))
        state.selected_dest_folder = ""
    return state.selected_dest_folder


def open_destination_folder(path: str) -> None:
    """Open the given folder with the default file manager if it exists."""
    if not path or not Path(path).exists():
        return
    if os.name == "nt":
        os.startfile(path)
    elif sys.platform == "darwin":
        subprocess.run(["open", path])
    else:
        subprocess.run(["xdg-open", path])


def log_message(message: str) -> None:
    """Append a message to the log textbox and to the log file."""
    logger.info(message)
    log_text.configure(state="normal")
    log_text.insert(ctk.END, message + "\n")
    log_text.configure(state="disabled")
    log_text.yview(ctk.END)

def change_theme(new_theme):
    """Update application appearance mode."""
    ctk.set_appearance_mode(new_theme)
    settings.theme = new_theme


def handle_ui_queue():
    """Process UI update events from the worker thread."""
    global ui_poll_id
    while not ui_queue.empty():
        event = ui_queue.get()
        etype = event[0]
        if etype == "log":
            log_message(event[1])
        elif etype == "create_progress":
            file_name = event[1]
            label = ctk.CTkLabel(
                progress_inner_frame,
                text=truncate_text(file_name, 50),
                text_color="black",
            )
            label.pack(pady=5)
            bar = ctk.CTkProgressBar(
                progress_inner_frame,
                orientation="horizontal",
                mode="determinate",
            )
            bar.pack(pady=3, padx=10)
            bar.set(0)
            bar.configure(width=300)
            pct = ctk.CTkLabel(progress_inner_frame, text="0%", text_color="black")
            pct.pack(pady=1)
            progress_bars[file_name] = (bar, pct)
        elif etype == "update_progress":
            file_name = event[1]
            inc = event[2]
            bar_tuple = progress_bars.get(file_name)
            if bar_tuple:
                bar, pct = bar_tuple
                bar.set(min(bar.get() + inc, 1))
                pct.configure(text=f"{int(bar.get()*100)}%")
        elif etype == "overall_progress":
            inc = event[1]
            if overall_progress:
                overall_progress.set(min(overall_progress.get() + inc, 1))
        elif etype == "enable_open":
            open_folder_button.configure(state="normal")
            cancel_button.configure(state="disabled")
        elif etype == "start_processing":
            cancel_button.configure(state="normal")
            open_folder_button.configure(state="disabled")
        elif etype == "finished":
            cancel_button.configure(state="disabled")
            open_folder_button.configure(state="normal")
            if open_when_done_var.get():
                open_destination_folder(state.selected_dest_folder)
    ui_poll_id = root.after(100, handle_ui_queue)


def on_close(win) -> None:
    """Handle application shutdown."""
    if ui_poll_id:
        win.after_cancel(ui_poll_id)
    settings.open_on_finish = open_when_done_var.get()
    save_settings(settings)
    win.destroy()

def generate_epubs(file_paths, dest_folder: str) -> None:
    global overall_progress
    if not file_paths:
        messagebox.showerror("Error", "Please select EPUB files first")
        return
    if not dest_folder:
        messagebox.showerror("Error", "Please select a destination folder first")
        return

    dest_path = Path(dest_folder)
    dest_path.mkdir(parents=True, exist_ok=True)

    for widget in progress_inner_frame.winfo_children():
        widget.destroy()

    overall_progress = ctk.CTkProgressBar(
        progress_inner_frame, orientation="horizontal", mode="determinate"
    )
    overall_progress.pack(pady=10, padx=10)
    overall_progress.set(0)
    overall_progress.configure(width=300)

    step = 1 / len(file_paths)

    def process_files():
        cancel_event.clear()
        ui_queue.put(("start_processing", None))
        with ThreadPoolExecutor(max_workers=4) as executor:
            futures = []
            for file_path in file_paths:
                if cancel_event.is_set():
                    break
                futures.append(executor.submit(generate_epub, Path(file_path), dest_path))
            for fut in futures:
                if cancel_event.is_set():
                    break
                fut.result()
                ui_queue.put(("overall_progress", step))
        if not cancel_event.is_set():
            ui_queue.put(("log", "All EPUB files processed successfully."))
        else:
            ui_queue.put(("log", "Processing cancelled."))
        ui_queue.put(("finished", None))

    threading.Thread(target=process_files, daemon=True).start()

def generate_epub(file_path: Path, dest_folder: Path) -> None:
    """Process a single EPUB file without performing UI updates."""
    if cancel_event.is_set():
        return
    original_cwd = Path.cwd()
    file_name = file_path.name
    epub_path = dest_folder / f"b_{file_name}"

    ui_queue.put(("log", f"Processing {file_name}..."))

    try:
        with tempfile.TemporaryDirectory() as tmpdir:
            unzip_path = Path(tmpdir)
            with ZipFile(file_path, "r") as zipObj:
                zipObj.extractall(unzip_path)
            ui_queue.put(("log", f"Extracted {file_name} successfully."))

            first_tags = """<?xml version='1.0' encoding='utf-8'?>\n<!DOCTYPE html PUBLIC '-//W3C//DTD XHTML 1.1//EN' 'http://www.w3.org/TR/xhtml11/DTD/xhtml11.dtd'>\n"""

            html_files = [str(p) for p in unzip_path.rglob("*.html")]

            if not html_files:
                ui_queue.put(("log", f"No HTML files found in {file_name}"))
                return

            ui_queue.put(("create_progress", file_name))

            step = 1 / len(html_files)

            for html_file in html_files:
                if cancel_event.is_set():
                    return
                process_html_file(html_file, first_tags)
                ui_queue.put(("update_progress", file_name, step))

            create_epub(epub_path, unzip_path, original_cwd)

            ui_queue.put(("log", f"Modified EPUB created at {epub_path}.epub"))
    except BadZipFile as e:
        ui_queue.put(("log", f"Bad EPUB archive {file_name}: {e}"))
    except Exception as e:
        ui_queue.put(("log", f"Failed to process {file_name}: {e}"))

def truncate_text(text: str, max_length: int) -> str:
    """Return text truncated to the specified length."""
    return text if len(text) <= max_length else text[: max_length - 3] + "..."

def process_html_file(html_file: str, first_tags: str) -> None:
    """Read, modify and write a single HTML file."""
    try:
        with open(html_file, 'r', encoding='utf-8') as f:
            html_data = f.read()
        ui_queue.put(("log", f"Read {html_file} successfully."))
    except Exception as e:
        ui_queue.put(("log", f"Failed to read HTML file {html_file}: {e}"))
        return

    parser = MyHTMLParser()
    parser.feed(html_data)

    full_html = ''
    for html_part in parser.data_html:
        if html_part[0] == 'Data:':
            full_html += bolding(html_part[1])
        if len(html_part) == 2 and html_part[0][0] == 'Start tag:':
            tag = '<' + html_part[0][1]
            full_attr = [f'{attr[0]}="{attr[1]}"' for attr in html_part[1][1]]
            attr_str = ' '.join(full_attr)
            if attr_str:
                tag += ' ' + attr_str
            tag += '>'
            full_html += tag
        if html_part[0] == 'End tag:':
            tag = f"</{html_part[1]}>"
            full_html += tag
    full_html = first_tags + full_html

    try:
        with open(html_file, 'w', encoding='utf-8') as f:
            f.write(full_html)
        ui_queue.put(("log", f"Wrote {html_file} successfully."))
    except Exception as e:
        ui_queue.put(("log", f"Failed to write HTML file {html_file}: {e}"))

def create_epub(epub_path: Path, unzip_path: Path, original_cwd: Path) -> None:
    """Create the final EPUB and clean up temporary files."""
    try:
        with change_directory(unzip_path):
            shutil.make_archive(str(epub_path), "zip", "./")
        shutil.move(f"{epub_path}.zip", f"{epub_path}.epub")
        ui_queue.put(("log", f"Created EPUB file {epub_path}.epub successfully."))
    except Exception as e:
        ui_queue.put(("log", f"Failed to create EPUB file {epub_path}: {e}"))

def main() -> None:
    """Initialize the UI and start the application."""
    if ctk is None:
        messagebox.showerror(
            "Missing Dependency",
            "customtkinter is required. Please run 'pip install customtkinter'",
        )
        return
    global root, progress_inner_frame, progress_canvas, progress_scrollbar
    global progress_scrollbar_horizontal, log_text, button_frame
    global open_folder_button, cancel_button, open_when_done_var
    logging.basicConfig(
        filename="bionic.log",
        level=logging.INFO,
        format="%(asctime)s - %(message)s",
    )

    # UI configuration
    ctk.set_appearance_mode(settings.theme)
    ctk.set_default_color_theme("green")

    root = ctk.CTk()
    root.title("EPUB Modifier")
    root.geometry("900x700")
    root.resizable(False, False)

    main_frame = ctk.CTkFrame(root)
    main_frame.pack(pady=20, padx=20, fill="both", expand=True)

    button_frame = ctk.CTkFrame(main_frame)
    button_frame.pack(side="left", fill="y", padx=10, pady=10, expand=True)

    progress_outer_frame = ctk.CTkFrame(main_frame, fg_color="#f0f0f0")
    progress_outer_frame.pack(side="right", fill="both", expand=True, padx=10, pady=10)

    progress_canvas = ctk.CTkCanvas(progress_outer_frame, bg="#f0f0f0")
    progress_canvas.pack(side="left", fill="both", expand=True)

    progress_scrollbar = ctk.CTkScrollbar(progress_outer_frame, orientation="vertical", command=progress_canvas.yview)
    progress_scrollbar.pack(side="right", fill="y")

    progress_scrollbar_horizontal = ctk.CTkScrollbar(progress_outer_frame, orientation="horizontal", command=progress_canvas.xview)
    progress_scrollbar_horizontal.pack(side="bottom", fill="x")

    progress_inner_frame = ctk.CTkFrame(progress_canvas, fg_color="#f0f0f0")
    progress_canvas.create_window((0, 0), window=progress_inner_frame, anchor="nw")
    progress_inner_frame.bind("<Configure>", lambda e: progress_canvas.configure(scrollregion=progress_canvas.bbox("all")))
    progress_canvas.configure(yscrollcommand=progress_scrollbar.set, xscrollcommand=progress_scrollbar_horizontal.set)

    log_frame = ctk.CTkFrame(root)
    log_frame.pack(pady=10, fill="both", expand=True)

    log_text = ctk.CTkTextbox(log_frame, state='disabled', height=10, wrap='word')
    log_text.pack(side="left", fill="both", expand=True)

    log_scroll = ctk.CTkScrollbar(log_frame, command=log_text.yview)
    log_scroll.pack(side="right", fill="y")
    log_text.configure(yscrollcommand=log_scroll.set)

    title_label = ctk.CTkLabel(button_frame, text="EPUB Modifier", font=("Helvetica", 16))
    title_label.pack(pady=10)

    theme_option = ctk.CTkOptionMenu(button_frame, values=["System", "Light", "Dark"], command=change_theme)
    theme_option.set(settings.theme)
    theme_option.pack(pady=5)

    def change_lang(lang):
        settings.language = lang
        file_label.configure(text=t("no_files"))
        dest_folder_label.configure(text=t("no_dest"))
        select_button.configure(text=t("select_files"))
        dest_folder_button.configure(text=t("select_destination"))
        generate_button.configure(text=t("generate"))
        cancel_button.configure(text=t("cancel"))
        open_folder_button.configure(text=t("open_destination"))

    lang_option = ctk.CTkOptionMenu(button_frame, values=["en", "es"], command=change_lang)
    lang_option.set(settings.language)
    lang_option.pack(pady=5)

    file_label = ctk.CTkLabel(button_frame, text=t("no_files"), font=("Helvetica", 10))
    file_label.pack(pady=10)

    select_button = ctk.CTkButton(button_frame, text=t("select_files"), command=select_epubs)
    select_button.pack(pady=10)

    dest_folder_label = ctk.CTkLabel(button_frame, text=t("no_dest"), font=("Helvetica", 10))
    dest_folder_label.pack(pady=10, fill="both", expand=True)

    dest_folder_button = ctk.CTkButton(button_frame, text=t("select_destination"), command=select_destination_folder)
    dest_folder_button.pack(pady=10)

    subfolder_entry = ctk.CTkEntry(button_frame)
    subfolder_entry.insert(0, settings.dest_subfolder)
    subfolder_entry.pack(pady=5)

    open_when_done_var = ctk.BooleanVar(value=settings.open_on_finish)
    open_when_done = ctk.CTkCheckBox(button_frame, text=t("open_when_done"), variable=open_when_done_var)
    open_when_done.pack(pady=5)

    generate_button = ctk.CTkButton(
        button_frame,
        text=t("generate"),
        command=lambda: generate_epubs(state.selected_file_paths, state.selected_dest_folder),
    )
    generate_button.pack(pady=10)

    cancel_button = ctk.CTkButton(
        button_frame,
        text=t("cancel"),
        command=cancel_event.set,
        state="disabled",
    )
    cancel_button.pack(pady=10)

    open_folder_button = ctk.CTkButton(
        button_frame,
        text=t("open_destination"),
        command=lambda: open_destination_folder(state.selected_dest_folder),
        state="disabled",
    )
    open_folder_button.pack(pady=10)

    # Start polling the queue for UI updates
    global ui_poll_id
    ui_poll_id = root.after(100, handle_ui_queue)

    root.protocol("WM_DELETE_WINDOW", lambda: on_close(root))

    root.mainloop()


if __name__ == "__main__":
    main()
