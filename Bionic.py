import os
import re
import shutil
import string
import customtkinter as ctk
from tkinter import filedialog, messagebox
from zipfile import ZipFile
from html.parser import HTMLParser
from html.entities import name2codepoint
from math import ceil, log

class MyHTMLParser(HTMLParser):
    def handle_starttag(self, tag, attrs):
        global data_html
        attributes = []
        for attr in attrs:
            attributes.append(attr)
        data_html.append((("Start tag:", tag), ("attr:", attributes)))

    def handle_endtag(self, tag):
        global data_html
        data_html.append(("End tag:", tag))

    def handle_data(self, data):
        global data_html
        data_html.append(("Data:", data))

    def handle_entityref(self, name):
        pass

    def handle_charref(self, name):
        pass

    def handle_decl(self, data):
        pass

def bolding(text):
    parts = re.findall(r'\w+|[^\s\w]+', text)
    new_text = ''
    for part in parts:
        if part in string.punctuation or part in string.digits:
            new_text += part
        else:
            if len(part) <= 3:
                new_part = f"<b>{part[0]}</b>" + ''.join(part[1:])
                new_text += ' ' + new_part
            else:
                point = ceil(log(len(part), 2))
                new_part = f"<b>{part[0:point]}</b>" + ''.join(part[point:])
                new_text += ' ' + new_part
    return new_text

def select_epubs():
    global file_paths
    file_paths = filedialog.askopenfilenames(filetypes=[("EPUB files", "*.epub")])
    if file_paths:
        file_label.configure(text=f"{len(file_paths)} files selected")
    else:
        file_label.configure(text="No files selected")

def select_destination_folder():
    global dest_folder
    dest_folder = filedialog.askdirectory()
    if dest_folder:
        dest_folder_label.configure(text=f"Destination: {dest_folder}")
    else:
        dest_folder_label.configure(text="No destination folder selected")

def log_message(message):
    log_text.configure(state='normal')
    log_text.insert(ctk.END, message + '\n')
    log_text.configure(state='disabled')
    log_text.yview(ctk.END)

def generate_epubs():
    if 'file_paths' not in globals() or not file_paths:
        messagebox.showerror("Error", "Please select EPUB files first")
        return
    if 'dest_folder' not in globals() or not dest_folder:
        messagebox.showerror("Error", "Please select a destination folder first")
        return

    if not os.path.exists(dest_folder):
        os.makedirs(dest_folder)

    for widget in progress_inner_frame.winfo_children():
        widget.destroy()

    overall_progress = ctk.CTkProgressBar(progress_inner_frame, orientation="horizontal", mode="determinate")
    overall_progress.pack(pady=10, padx=10)
    overall_progress.set(0)
    overall_progress.configure(width=300)

    step = 1 / len(file_paths)

    for file_path in file_paths:
        generate_epub(file_path)
        overall_progress.set(overall_progress.get() + step)
        root.update_idletasks()

def generate_epub(file_path):
    original_cwd = os.getcwd()  # Save the original current working directory
    file_name = os.path.basename(file_path)
    epub_path = os.path.join(dest_folder, 'bionic_' + file_name)
    unzip_path_folder = file_name + '_zip/'
    unzip_path = os.path.join(original_cwd, unzip_path_folder)

    log_message(f"Processing {file_name}...")

    try:
        with ZipFile(file_path, 'r') as zipObj:
            zipObj.extractall(unzip_path)
    except Exception as e:
        log_message(f"Failed to extract {file_name}: {e}")
        return

    first_tags = """<?xml version='1.0' encoding='utf-8'?>\n<!DOCTYPE html PUBLIC '-//W3C//DTD XHTML 1.1//EN' 'http://www.w3.org/TR/xhtml11/DTD/xhtml11.dtd'>\n"""

    htmls = []
    for r, d, f in os.walk(unzip_path):
        for hfile in f:
            if hfile.endswith('html'):
                htmls.append(os.path.join(r, hfile))

    progress_label = ctk.CTkLabel(progress_inner_frame, text=f"Processing {file_name}", text_color="black")
    progress_label.pack(pady=5)
    progress_bar = ctk.CTkProgressBar(progress_inner_frame, orientation="horizontal", mode="determinate")
    progress_bar.pack(pady=10, padx=10)
    progress_bar.set(0)
    progress_bar.configure(width=300)

    step = 1 / len(htmls)

    for index, html in enumerate(htmls):
        try:
            with open(html, 'r', encoding='utf-8') as f:
                html_data = f.read()
        except Exception as e:
            log_message(f"Failed to read HTML file {html}: {e}")
            return

        global data_html
        data_html = []
        parser = MyHTMLParser()
        parser.feed(html_data)

        full_html = ''
        for html_part in data_html:
            if html_part[0] == 'Data:':
                full_html += bolding(html_part[1])
            if len(html_part) == 2 and html_part[0][0] == 'Start tag:':
                tag = '<' + html_part[0][1]
                full_attr = [f'{attr[0]}="{attr[1]}"' for attr in html_part[1][1]]
                tag += ' ' + ' '.join(full_attr) + '>'
                full_html += tag
            if html_part[0] == 'End tag:':
                tag = f"</{html_part[1]}>"
                full_html += tag
        full_html = first_tags + full_html

        try:
            with open(html, 'w', encoding='utf-8') as f:
                f.write(full_html)
        except Exception as e:
            log_message(f"Failed to write HTML file {html}: {e}")
            return

        progress_bar.set(progress_bar.get() + step)
        root.update_idletasks()

    try:
        os.chdir(unzip_path)
        shutil.make_archive(epub_path, 'zip', './')
        os.chdir(original_cwd)  # Change back to the original working directory
        shutil.move(epub_path + '.zip', epub_path + '.epub')
    except Exception as e:
        log_message(f"Failed to create EPUB file {epub_path}: {e}")
        return
    finally:
        try:
            shutil.rmtree(unzip_path)
        except Exception as e:
            log_message(f"Failed to remove temporary directory {unzip_path}: {e}")

    log_message(f"Modified EPUB created at {epub_path}.epub")

# Configuración de la interfaz gráfica con customtkinter
ctk.set_appearance_mode("System")  # Opciones: "System" (Default), "Light", "Dark"
ctk.set_default_color_theme("blue")  # Opciones: "blue" (Default), "green", "dark-blue"

root = ctk.CTk()
root.title("EPUB Modifier")
root.geometry("800x600")
root.resizable(False, False)

main_frame = ctk.CTkFrame(root)
main_frame.pack(pady=20, padx=20, fill="both", expand=True)

button_frame = ctk.CTkFrame(main_frame)
button_frame.pack(side="left", fill="y", padx=10, pady=10)

progress_outer_frame = ctk.CTkFrame(main_frame, fg_color="#f0f0f0")
progress_outer_frame.pack(side="right", fill="both", expand=True, padx=10, pady=10)

progress_canvas = ctk.CTkCanvas(progress_outer_frame, bg="#f0f0f0")
progress_canvas.pack(side="left", fill="both", expand=True)

progress_scrollbar = ctk.CTkScrollbar(progress_outer_frame, orientation="vertical", command=progress_canvas.yview)
progress_scrollbar.pack(side="right", fill="y")

progress_inner_frame = ctk.CTkFrame(progress_canvas, fg_color="#f0f0f0")
progress_canvas.create_window((0, 0), window=progress_inner_frame, anchor="nw")
progress_inner_frame.bind("<Configure>", lambda e: progress_canvas.configure(scrollregion=progress_canvas.bbox("all")))
progress_canvas.configure(yscrollcommand=progress_scrollbar.set)

log_frame = ctk.CTkFrame(root)
log_frame.pack(pady=10, fill="both", expand=True)

log_text = ctk.CTkTextbox(log_frame, state='disabled', height=10, wrap='word')
log_text.pack(side="left", fill="both", expand=True)

log_scroll = ctk.CTkScrollbar(log_frame, command=log_text.yview)
log_scroll.pack(side="right", fill="y")
log_text.configure(yscrollcommand=log_scroll.set)

title_label = ctk.CTkLabel(button_frame, text="EPUB Modifier", font=("Helvetica", 16))
title_label.pack(pady=10)

file_label = ctk.CTkLabel(button_frame, text="No files selected", font=("Helvetica", 10))
file_label.pack(pady=10)

select_button = ctk.CTkButton(button_frame, text="Select EPUB Files", command=select_epubs)
select_button.pack(pady=10)

dest_folder_label = ctk.CTkLabel(button_frame, text="No destination folder selected", font=("Helvetica", 10))
dest_folder_label.pack(pady=10)

dest_folder_button = ctk.CTkButton(button_frame, text="Select Destination Folder", command=select_destination_folder)
dest_folder_button.pack(pady=10)

generate_button = ctk.CTkButton(button_frame, text="Generate Modified EPUBs", command=generate_epubs)
generate_button.pack(pady=10)

root.mainloop()
