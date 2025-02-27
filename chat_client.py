import socket
import threading
import os
import datetime
import tkinter as tk
from tkinter import filedialog, scrolledtext, simpledialog, messagebox, Label
from PIL import Image, ImageTk
import re
import io
import base64
import json

HOST = '127.0.0.1'
PORT = 55555
CHUNK_SIZE = 1024 * 1024  # 1MB 區塊大小

class ChatClient:
    def __init__(self, root):
        self.root = root
        self.root.title("聊天室")

        self.nickname = None
        self.avatar = None

        self.chat_history = scrolledtext.ScrolledText(root, state=tk.DISABLED)
        self.chat_history.pack(padx=10, pady=10, fill=tk.BOTH, expand=True)

        self.input_frame = tk.Frame(root)
        self.input_frame.pack(padx=10, pady=5, fill=tk.X)

        self.attach_button = tk.Button(self.input_frame, text="+", command=self.attach_file)
        self.attach_button.pack(side=tk.LEFT)

        self.message_entry = tk.Entry(self.input_frame)
        self.message_entry.pack(side=tk.LEFT, fill=tk.X, expand=True)
        self.message_entry.bind("<Return>", self.send_message)

        self.avatar_preview = Label(self.input_frame)
        self.avatar_preview.pack(side=tk.LEFT)

        self.file_preview_frame = tk.Frame(self.input_frame)
        self.file_preview_frame.pack(side=tk.LEFT)

        self.uploaded_files = []

        self.client = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.client.connect((HOST, PORT))

        receive_thread = threading.Thread(target=self.receive)
        receive_thread.start()

        self.register_user()
        self.load_chat_history()
        self.load_user_info()

    def register_user(self):
        self.nickname = simpledialog.askstring("暱稱", "請輸入您的暱稱：")
        avatar_path = filedialog.askopenfilename(title="選擇頭像", filetypes=[("Image files", "*.png;*.jpg;*.jpeg")])
        if avatar_path:
            with open(avatar_path, 'rb') as f:
                self.avatar = base64.b64encode(f.read()).decode('utf-8')
        self.client.send(f"REGISTER|{self.nickname}|{self.avatar}".encode('utf-8'))
        self.save_user_info()
        self.display_avatar_preview(self.avatar)

    def attach_file(self):
        filepath = filedialog.askopenfilename(title="選擇檔案")
        if filepath:
            self.uploaded_files.append(filepath)
            self.display_file_preview(filepath)

    def display_avatar_preview(self, avatar_base64):
        if avatar_base64:
            try:
                file_data = base64.b64decode(avatar_base64)
                img = Image.open(io.BytesIO(file_data))
                img.thumbnail((50, 50))
                photo = ImageTk.PhotoImage(img)
                self.avatar_preview.config(image=photo)
                self.avatar_preview.image = photo
            except:
                pass

    def display_file_preview(self, filepath):
        try:
            img = Image.open(filepath)
            img.thumbnail((50, 50))
            photo = ImageTk.PhotoImage(img)
            label = Label(self.file_preview_frame, image=photo)
            label.image = photo
            label.pack(side=tk.LEFT)
        except:
            pass

    def send_message(self, event=None):
        message = self.message_entry.get()
        if message:
            for filepath in self.uploaded_files:
                self.send_file(filepath, message)
            if not self.uploaded_files:
                self.client.send(f"MESSAGE|{message}".encode('utf-8'))
            self.message_entry.delete(0, tk.END)
            self.uploaded_files = []
            for widget in self.file_preview_frame.winfo_children():
                widget.destroy()

    def send_file(self, filepath, message):
        try:
            filesize = os.path.getsize(filepath)
            filename = os.path.basename(filepath)
            with open(filepath, 'rb') as f:
                file_data = f.read()
            file_base64 = base64.b64encode(file_data).decode('utf-8')
            self.client.send(f"FILE|{filename}|{filesize}|{file_base64}|{message}".encode('utf-8'))
            print(f"檔案 {filename} 發送成功！")
        except FileNotFoundError:
            print("找不到檔案。")
        except Exception as e:
            print(f"發送檔案時發生錯誤：{e}")

    def receive(self):
        while True:
            try:
                message = self.client.recv(1024).decode('utf-8')
                if message.startswith('MESSAGE'):
                    _, nickname, avatar, timestamp, content = message.split('|')
                    self.display_message(nickname, avatar, timestamp, content)
                    self.save_chat_history(nickname, avatar, timestamp, content)
                elif message.startswith('FILE'):
                    _, nickname, avatar, timestamp, filename, filesize, file_base64, content = message.split('|')
                    self.display_file(nickname, avatar, timestamp, filename, file_base64, content)
                    self.save_chat_history(nickname, avatar, timestamp, f"{filename} ({content})")
            except:
                print("發生錯誤！")
                self.client.close()
                break

    def display_message(self, nickname, avatar, timestamp, content):
        self.chat_history.config(state=tk.NORMAL)
        self.chat_history.insert(tk.END, f"{nickname}: {content}\n")
        self.chat_history.config(state=tk.DISABLED)
        self.chat_history.see(tk.END)

    def display_file(self, nickname, avatar, timestamp, filename, file_base64, content):
        self.chat_history.config(state=tk.NORMAL)
        self.chat_history.insert(tk.END, f"{nickname}: {filename} ({content})\n")
        try:
            file_data = base64.b64decode(file_base64)
            img = Image.open(io.BytesIO(file_data))
            img.thumbnail((200, 200))
            photo = ImageTk.PhotoImage(img)
            self.chat_history.image_create(tk.END, image=photo)
            self.chat_history.image = photo
        except:
            pass
        self.chat_history.insert(tk.END, "\n")
        self.chat_history.config(state=tk.DISABLED)
        self.chat_history.see(tk.END)

    def save_chat_history(self, nickname, avatar, timestamp, content):
        try:
            with open("chat_history.json", "r") as f:
                history = json.load(f)
        except FileNotFoundError:
            history = []
        history.append({"nickname": nickname, "avatar": avatar, "timestamp": timestamp, "content": content})
        with open("chat_history.json", "w") as f:
            json.dump(history, f)

    def load_chat_history(self):
        try:
            with open("chat_history.json", "r") as f:
                history = json.load(f)
            for item in history:
                self.display_message(item["nickname"], item["avatar"], item["timestamp"], item["content"])
        except FileNotFoundError:
            pass

    def save_user_info(self):
        user_info = {"nickname": self.nickname, "avatar": self.avatar}
        with open("user_info.json", "w") as f:
            json.dump(user_info, f)

    def load_user_info(self):
        try:
            with open("user_info.json", "r") as f:
                user_info = json.load(f)
            self.nickname = user_info["nickname"]
            self.avatar = user_info["avatar"]
            self.display_avatar_preview(self.avatar)
        except FileNotFoundError:
            pass

root = tk.Tk()
client = ChatClient(root)
root.mainloop()