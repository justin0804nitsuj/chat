import socket
import threading
import os
import datetime
import tkinter as tk
from tkinter import filedialog, scrolledtext, simpledialog, messagebox, Label, Entry, Button, Frame
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

        self.socket_closed = False

        self.nickname = None
        self.avatar = None
        self.last_date = None
        self.last_sender = None
        self.consecutive_messages = 0
        self.message_count = {}

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
        self.ephemeral_map = {}

        self.client = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.client.connect((HOST, PORT))

        receive_thread = threading.Thread(target=self.receive)
        receive_thread.start()

        self.load_chat_history()

        if os.path.exists("user_info.json"):
            print("找到 user_info.json，載入使用者資訊。")
            self.load_user_info()
            self.display_avatar_preview(self.avatar)
        else:
            print("找不到 user_info.json，顯示註冊介面。")
            self.register_user()
        
    def register_user(self):
        self.register_window = tk.Toplevel(self.root)
        self.register_window.title("註冊")
        self.register_window.lift()

        # Nickname
        nickname_label = tk.Label(self.register_window, text="暱稱:")
        nickname_label.grid(row=0, column=0, padx=5, pady=5, sticky="w")
        self.nickname_entry = tk.Entry(self.register_window)
        self.nickname_entry.grid(row=0, column=1, padx=5, pady=5)

        # Avatar
        self.avatar_label = tk.Label(self.register_window, text="頭像:")
        self.avatar_label.grid(row=1, column=0, padx=5, pady=5, sticky="w")
        self.avatar_button = tk.Button(self.register_window, text="選擇頭像", command=self.choose_avatar)
        self.avatar_button.grid(row=1, column=1, padx=5, pady=5)

        # Avatar Preview
        self.avatar_preview_register = Label(self.register_window)
        self.avatar_preview_register.grid(row=0, column=2, rowspan=2, padx=5, pady=5)

        # Register button
        self.register_button = Button(self.register_window, text="註冊", command=self.complete_registration)
        self.register_button.grid(row=2, columnspan=3, padx=5, pady=5)
        
        self.avatar_path = None

    def choose_avatar(self):
        self.avatar_path = filedialog.askopenfilename(title="選擇頭像", filetypes=[("Image files", "*.png;*.jpg;*.jpeg")])
        if self.avatar_path:
            self.display_avatar_preview_register(self.avatar_path)

    def display_avatar_preview_register(self, avatar_path):
        if avatar_path:
            try:
                img = Image.open(avatar_path)
                img.thumbnail((200, 200))
                photo = ImageTk.PhotoImage(img)
                self.avatar_preview_register.config(image=photo)
                self.avatar_preview_register.image = photo
            except:
                pass

    def complete_registration(self):
        self.nickname = self.nickname_entry.get()
        if self.avatar_path:
            with open(self.avatar_path, 'rb') as f:
                self.avatar = base64.b64encode(f.read()).decode('utf-8')
        self.client.send(f"REGISTER|{self.nickname}|{self.avatar}".encode('utf-8'))
        self.save_user_info()
        self.display_avatar_preview(self.avatar)
        self.register_window.destroy()

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
        if self.socket_closed:  # 檢查標誌
            print("Socket 已關閉，無法發送訊息。")
            return

        message = self.message_entry.get()
        if message:
            now = datetime.datetime.now()
            timestamp = now.strftime("%Y/%m/%d|%H:%M:%S")
            for filepath in self.uploaded_files:
                self.send_file(filepath, message, timestamp)
            if not self.uploaded_files:
                try:
                    self.client.send(f"MESSAGE|{self.nickname}|{self.avatar}|{timestamp}|{message}".encode('utf-8'))
                except OSError as e:
                    print(f"Socket 錯誤：{e}")
                    self.socket_closed = True
                    self.reconnect()
                except Exception as e:
                    print(f"發生錯誤：{e}")
                    self.socket_closed = True
                    self.reconnect()
            self.message_entry.delete(0, tk.END)
            self.uploaded_files = []
            for widget in self.file_preview_frame.winfo_children():
                widget.destroy()

    def send_file(self, filepath, message,timestamp):
        try:
            filesize = os.path.getsize(filepath)
            filename = os.path.basename(filepath)
            with open(filepath, 'rb') as f:
                file_data = f.read()
            file_base64 = base64.b64encode(file_data).decode('utf-8')
            self.client.send(f"FILE|{self.nickname}|{self.avatar}|{timestamp}|{filename}|{filesize}|{file_base64}|{message}".encode('utf-8'))
            print(f"檔案 {filename} 發送成功！")
        except OSError as e:
            print(f"Socket 錯誤：{e}")
            self.socket_closed = True
            self.reconnect()
        except FileNotFoundError:
            print("找不到檔案。")
        except Exception as e:
            print(f"發送檔案時發生錯誤：{e}")
            
    def receive(self):
        while True:
            try:
                message = self.client.recv(16384).decode('utf-8')
                if message.startswith('MESSAGE'):
                    _, nickname, avatar, timestamp, content = message.split('|', 4)
                    date_str, time_str = timestamp.split('|')
                    self.display_message(nickname, avatar, date_str, time_str, content)
                    self.save_chat_history(nickname, avatar, timestamp, content)
                elif message.startswith('FILE'):
                    _, nickname, avatar, timestamp, filename, filesize, file_base64, content = message.split('|', 7)
                    date_str, time_str = timestamp.split('|')
                    self.display_file(nickname, avatar, date_str, time_str, filename, file_base64, content)
                    self.save_chat_history(nickname, avatar, timestamp, f"{filename} ({content})")
            except OSError as e:
                print(f"Socket 錯誤：{e}")
                self.client.close()
                self.socket_closed = True
                print("嘗試重新連線...")
                self.reconnect()
                break
            except Exception as e:
                print(f"發生錯誤：{e}")
                self.client.close()
                self.socket_closed = True
                print("嘗試重新連線...")
                self.reconnect()
                break
    def reconnect(self):
        try:
            self.client = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.client.connect((HOST, PORT))
            self.socket_closed = False
            print("重新連線成功！")
            receive_thread = threading.Thread(target=self.receive)
            receive_thread.start()
        except Exception as e:
            print(f"重新連線失敗：{e}")
            self.reconnect() # 遞迴呼叫，直到重新連線成功
            
    def display_message(self, nickname, avatar, date_str, time_str, content):
        if self.last_date != date_str:
            self.display_date_header(date_str)
            self.last_date = date_str
            self.last_sender = None #reset last sender when new day starts.
            self.consecutive_messages = 0 #reset counter when new day starts.
            self.message_count={} #reset user message count when new day starts.

        show_avatar = False

        if self.last_sender != nickname:
            show_avatar = True
            self.consecutive_messages = 1
            self.last_sender = nickname
            self.message_count[nickname] = 1 #initial user count
        elif self.consecutive_messages < 7:
            show_avatar = True
            self.consecutive_messages += 1
            self.message_count[nickname] += 1
        else:
            self.consecutive_messages += 1
            self.message_count[nickname] += 1

        container = tk.Frame(self.chat_history, bg="#FFFFFF")

        if show_avatar and avatar:
            try:
                file_data = base64.b64decode(avatar)
                img = Image.open(io.BytesIO(file_data))
                img.thumbnail((30, 30))
                photo = ImageTk.PhotoImage(img)
                avatar_label = tk.Label(container, image=photo, bg="#FFFFFF")
                avatar_label.image = photo
                avatar_label.pack(side=tk.LEFT)
            except:
                pass

        msg_label = tk.Label(container, text=f"{nickname}: {content}", bg="#FFFFFF", justify="left")
        msg_label.pack(side=tk.LEFT, anchor="w")
        
        time_label = tk.Label(container, text=time_str, bg="#FFFFFF")
        
        edit_btn = tk.Button(container, text="Edit", command=lambda: self.edit_message(msg_label, content))
        edit_btn.pack(side=tk.RIGHT)
        
        del_btn = tk.Button(container, text="Delete", command=lambda: self.delete_message(container))
        del_btn.pack(side=tk.RIGHT)
        
        container.pack(fill="x")
        def show_time(event):
            time_label.pack(side=tk.LEFT)

        def hide_time(event):
            time_label.pack_forget()

        container.bind("<Enter>", show_time)
        container.bind("<Leave>", hide_time)
        
        self.chat_history.config(state=tk.NORMAL)
        self.chat_history.window_create(tk.END, window=container)
        self.chat_history.insert(tk.END, '\n')
        self.chat_history.config(state=tk.DISABLED)
        self.chat_history.see(tk.END)

    def display_file(self, nickname, avatar, date_str, time_str, filename, file_base64, content):
        if self.last_date != date_str:
            self.display_date_header(date_str)
            self.last_date = date_str
            self.last_sender = None #reset last sender when new day starts.
            self.consecutive_messages = 0 #reset counter when new day starts.
            self.message_count={} #reset user message count when new day starts.

        show_avatar = False

        if self.last_sender != nickname:
            show_avatar = True
            self.consecutive_messages = 1
            self.last_sender = nickname
            self.message_count[nickname] = 1 #initial user count
        elif self.consecutive_messages < 7:
            show_avatar = True
            self.consecutive_messages += 1
            self.message_count[nickname] += 1
        else:
            self.consecutive_messages += 1
            self.message_count[nickname] += 1

        container = tk.Frame(self.chat_history, bg="#FFFFFF")

        if show_avatar and avatar:
            try:
                file_data = base64.b64decode(avatar)
                img = Image.open(io.BytesIO(file_data))
                img.thumbnail((30, 30))
                photo = ImageTk.PhotoImage(img)
                avatar_label = tk.Label(container, image=photo, bg="#FFFFFF")
                avatar_label.image = photo
                avatar_label.pack(side=tk.LEFT)
            except:
                pass

        msg_label = tk.Label(container, text=f"{nickname}: {filename} ({content})", bg="#FFFFFF", justify="left")
        msg_label.pack(side=tk.LEFT, anchor="w")
        try:
            file_data = base64.b64decode(file_base64)
            img = Image.open(io.BytesIO(file_data))
            img.thumbnail((200, 200))
            photo = ImageTk.PhotoImage(img)
            self.chat_history.image_create(tk.END, image=photo)
            self.chat_history.image = photo
        except:
            pass

        time_label = tk.Label(container, text=time_str, bg="#FFFFFF")
        
        edit_btn = tk.Button(container, text="Edit", command=lambda: self.edit_message(msg_label, content))
        edit_btn.pack(side=tk.RIGHT)
        
        del_btn = tk.Button(container, text="Delete", command=lambda: self.delete_message(container))
        del_btn.pack(side=tk.RIGHT)
        
        container.pack(fill="x")
        def show_time(event):
            time_label.pack(side=tk.LEFT)

        def hide_time(event):
            time_label.pack_forget()

        container.bind("<Enter>", show_time)
        container.bind("<Leave>", hide_time)
        
        self.chat_history.config(state=tk.NORMAL)
        self.chat_history.window_create(tk.END, window=container)
        self.chat_history.insert(tk.END, '\n')
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
                nickname = item["nickname"]
                avatar = item["avatar"]
                timestamp = item["timestamp"]
                date_str, time_str = timestamp.split('|')
                content = item["content"]
                self.display_message(nickname, avatar, date_str, time_str, content)
        except FileNotFoundError:
            pass

    def save_user_info(self):
        print("儲存使用者資訊：", self.nickname)
        user_info = {"nickname": self.nickname, "avatar": self.avatar}
        with open("user_info.json", "w") as f:
            json.dump(user_info, f)

    def load_user_info(self):
        try:
            with open("user_info.json", "r") as f:
                user_info = json.load(f)
            self.nickname = user_info["nickname"]
            self.avatar = user_info["avatar"]
            print("載入使用者資訊：", self.nickname)
            print(f"使用者 {self.nickname} 已成功登入。")
        except FileNotFoundError:
            print("找不到使用者資訊。")
            pass
    
    def display_date_header(self, date_str):
        self.chat_history.config(state=tk.NORMAL)
        self.chat_history.insert(tk.END, f"=== {date_str} ===\n")
        self.chat_history.config(state=tk.DISABLED)
    
    def edit_message(self, msg_label, content):
        new_content = simpledialog.askstring("Edit Message", "Edit your message:", initialvalue=content)
        if new_content:
            msg_label.config(text=new_content)
        
    def delete_message(self, container):
        container.destroy()

root = tk.Tk()
client = ChatClient(root)
root.mainloop()
