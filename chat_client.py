from ttkthemes import ThemedTk
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
from PIL import Image, ImageTk
import datetime, os, json, shutil, threading, time, base64, socket
from io import BytesIO

# 伺服器設定（測試用，請根據需求修改）
SERVER_HOST = "127.0.0.1"
SERVER_PORT = 12345

DATA_FILENAME = "messages.json"
PROFILE_FILENAME = "profile.json"

# 檔案大小門檻 (byte)，超過此值則採用分塊上傳（1MB）
CHUNK_THRESHOLD = 1048576

class ChatClientApp:
    def __init__(self, root):
        self.root = root
        self.root.title("聊天室 - 檔案傳送 + 就地編輯")
        self.root.state('zoomed')
        # 若在 macOS/Linux，可使用: self.root.attributes("-zoomed", True)

        try:
            self.app_dir = os.path.dirname(os.path.abspath(__file__))
        except Exception:
            self.app_dir = os.getcwd()
        self.data_path = os.path.join(self.app_dir, DATA_FILENAME)
        self.profile_path = os.path.join(self.app_dir, PROFILE_FILENAME)
        self.attachments_dir = os.path.join(self.app_dir, "attachments")
        os.makedirs(self.attachments_dir, exist_ok=True)
        print("資料儲存路徑:", self.data_path)

        self.root.config(bg="#1f1f1f")
        self.entry_font = ("Arial", 25)
        self.message_font = ("Arial", 25)
        self.image_thumbnail_size = (300, 300)
        self.avatar_size = (50, 50)

        self.messages_data = []      # 儲存所有訊息
        self.day_frames = {}         # 每天的訊息容器
        self.last_header_info = {}   # 用來判斷是否顯示頭像與名稱 {date: (last_sender, count)}
        self.ephemeral_map = {}      # 存放每則訊息對應的 UI 元件

        self.attached_file_path = None
        self.attached_file_preview = None
        self.uploaded_file_id = None  # 分塊上傳後的檔案識別
        self.cancel_upload = False
        self.uploading = False       # 是否正在上傳大型檔案

        # Dummy 使用者列表（可從伺服器取得真實資料）
        self.user_list = ["Alice", "Bob", "Charlie", "David"]

        # 讀取個人資料，若無則要求設定
        self.profile = self.load_profile()
        if not self.profile:
            self.setup_profile()

        # 建立與伺服器連線
        self.socket = None
        self.connect_to_server()

        # -------------------- 上方捲動區 --------------------
        top_frame = tk.Frame(self.root, bg="#1f1f1f")
        top_frame.pack(side=tk.TOP, fill=tk.BOTH, expand=True)
        self.canvas = tk.Canvas(top_frame, bg="#2b2b2b", highlightthickness=0)
        self.canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        self.scrollbar = tk.Scrollbar(top_frame, orient="vertical", command=self.canvas.yview, bg="#2b2b2b")
        self.scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        self.canvas.configure(yscrollcommand=self.scrollbar.set)
        self.main_frame = tk.Frame(self.canvas, bg="#2b2b2b")
        self.canvas_window = self.canvas.create_window((0, 0), window=self.main_frame, anchor="nw")
        self.main_frame.bind("<Configure>", lambda e: self.on_frame_configure())
        self.canvas.bind_all("<MouseWheel>", self.on_mousewheel)

        # -------------------- 右上角搜尋 --------------------
        search_frame = tk.Frame(self.root, bg="#1f1f1f")
        search_frame.place(relx=1.0, rely=0.0, x=-70, y=5, anchor="ne")
        self.search_var = tk.StringVar()
        self.search_entry = tk.Entry(search_frame, textvariable=self.search_var,
                                     font=("Arial", 16), bg="#3a3a3a", fg="white", insertbackground="white")
        self.search_entry.pack(side=tk.RIGHT, padx=5, pady=5)
        self.search_entry.config(width=0)
        self.search_listbox = tk.Listbox(self.root, font=("Arial", 14), bg="#2b2b2b", fg="white")
        self.search_listbox.place_forget()
        self.search_var.trace_add("write", self.on_search_var_changed)
        self.search_icon_btn = tk.Button(search_frame, text="🔍", font=("Arial", 18),
                                         bg="#3a3a3a", fg="white", activebackground="#2b2b2b",
                                         activeforeground="white", command=self.on_search_icon_click)
        self.search_icon_btn.pack(side=tk.RIGHT, padx=5, pady=5)

        # -------------------- 下方輸入區 --------------------
        bottom_frame = tk.Frame(self.root, bg="#1f1f1f")
        bottom_frame.pack(side=tk.BOTTOM, fill=tk.X)
        self.attach_btn = tk.Button(bottom_frame, text="+", width=3,
                                      command=self.attach_file, bg="#3a3a3a", fg="white",
                                      activebackground="#000000", activeforeground="white")
        self.attach_btn.bind("<Enter>", lambda e: self.attach_btn.config(bg="#2b2b2b"))
        self.attach_btn.bind("<Leave>", lambda e: self.attach_btn.config(bg="#3a3a3a"))
        self.attach_btn.pack(side=tk.LEFT, padx=5, pady=5)
        self.entry_var = tk.StringVar(value="")
        self.entry_box = tk.Entry(bottom_frame, textvariable=self.entry_var,
                                  width=50, font=self.entry_font, bg="#3a3a3a",
                                  fg="white", insertbackground="white")
        self.entry_box.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=5, pady=5)
        # 提示效果：顯示「按下enter以傳送訊息」，但允許點擊後取得焦點
        self.placeholder_label = tk.Label(bottom_frame, text="按下enter以傳送訊息",
                                          font=self.entry_font, fg="#888888", bg="#3a3a3a")
        self.placeholder_label.place(in_=self.entry_box, relx=0.5, rely=0.5, anchor="center")
        self.placeholder_label.bind("<Button-1>", lambda e: self.entry_box.focus_set())
        self.entry_box.bind("<FocusIn>", lambda e: self.placeholder_label.place_forget())
        self.entry_box.bind("<FocusOut>", lambda e: self.show_placeholder())
        self.entry_box.bind("<Return>", self.on_press_enter)
        self.entry_box.bind("<KP_Enter>", self.on_press_enter)

        # -------------------- 預覽區 (附件) --------------------
        self.preview_label = tk.Label(self.root, text="", fg="white", bg="#1f1f1f", font=("Arial", 20))
        self.preview_label.pack(side=tk.TOP, fill=tk.X)
        self.preview_label.pack_forget()

        # -------------------- 使用者列表（覆蓋整個視窗，按 ESC 切換） --------------------
        self.user_list_frame = tk.Frame(self.root, bg="#333333")
        self.user_list_frame.place(relx=0, rely=0, relwidth=1, relheight=1)
        self.user_list_frame.lower()
        self.root.bind("<Escape>", self.toggle_user_list)

        self.load_data()
        self.root.protocol("WM_DELETE_WINDOW", self.on_close)
        threading.Thread(target=self.receive_messages, daemon=True).start()

    def show_placeholder(self):
        if not self.entry_var.get():
            self.placeholder_label.place(in_=self.entry_box, relx=0.5, rely=0.5, anchor="center")

    def is_image_file(self, filepath):
        ext = os.path.splitext(filepath)[1].lower()
        return ext in ['.png', '.jpg', '.jpeg', '.gif']

    def load_profile(self):
        if os.path.exists(self.profile_path):
            try:
                with open(self.profile_path, "r", encoding="utf-8") as f:
                    profile = json.load(f)
                return profile
            except Exception as e:
                print("讀取個人資料失敗:", e)
        return None

    def save_profile(self, profile):
        try:
            with open(self.profile_path, "w", encoding="utf-8") as f:
                json.dump(profile, f, ensure_ascii=False, indent=2)
            print("已儲存個人資料")
        except Exception as e:
            print("儲存個人資料失敗:", e)

    def setup_profile(self):
        dialog = tk.Toplevel(self.root)
        dialog.title("設定個人資料")
        dialog.grab_set()
        tk.Label(dialog, text="請輸入您的名字：", font=("Arial", 16)).pack(padx=10, pady=5)
        name_var = tk.StringVar()
        name_entry = tk.Entry(dialog, textvariable=name_var, font=("Arial", 16), width=30)
        name_entry.pack(padx=10, pady=5)
        avatar_path = [None]
        def choose_avatar():
            path = filedialog.askopenfilename(title="選擇頭像", filetypes=[("Image Files", "*.png;*.jpg;*.jpeg;*.gif")])
            if path:
                avatar_path[0] = path
                avatar_label.config(text=os.path.basename(path))
        tk.Button(dialog, text="選擇頭像", font=("Arial", 16), command=choose_avatar).pack(padx=10, pady=5)
        avatar_label = tk.Label(dialog, text="尚未選擇", font=("Arial", 14))
        avatar_label.pack(padx=10, pady=5)
        def on_ok():
            name = name_var.get().strip()
            if not name:
                messagebox.showerror("錯誤", "名字不可空白")
                return
            if not avatar_path[0]:
                messagebox.showerror("錯誤", "請選擇頭像")
                return
            try:
                with open(avatar_path[0], "rb") as f:
                    avatar_bytes = f.read()
                avatar_b64 = base64.b64encode(avatar_bytes).decode("utf-8")
            except Exception as e:
                messagebox.showerror("錯誤", f"讀取頭像失敗: {e}")
                return
            self.profile = {"name": name, "avatar_data": avatar_b64, "avatar_filename": os.path.basename(avatar_path[0])}
            self.save_profile(self.profile)
            dialog.destroy()
        tk.Button(dialog, text="確定", font=("Arial", 16), command=on_ok).pack(padx=10, pady=10)
        self.root.wait_window(dialog)

    def connect_to_server(self):
        try:
            self.socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.socket.connect((SERVER_HOST, SERVER_PORT))
            print("已連線到聊天伺服器")
        except Exception as e:
            print("連線伺服器失敗:", e)
            self.socket = None

    def send_network_message(self, message):
        if self.socket:
            try:
                self.socket.sendall((message + "\n").encode("utf-8"))
            except Exception as e:
                print("網路訊息傳送失敗:", e)

    def receive_messages(self):
        buffer = ""
        while self.socket:
            try:
                data = self.socket.recv(16384)
                if not data:
                    break
                buffer += data.decode("utf-8")
                while "\n" in buffer:
                    line, buffer = buffer.split("\n", 1)
                    if line.strip():
                        self.root.after(0, self.send_received_message, line.strip())
            except Exception as e:
                print("接收網路訊息失敗:", e)
                break

    def send_received_message(self, text):
        now = datetime.datetime.now()
        date_str = now.strftime("%Y/%m/%d")
        time_str = now.strftime("%H:%M:%S")
        msg_id = len(self.messages_data) + 1
        msg_data = {
            "msg_id": msg_id,
            "text": text,
            "date": date_str,
            "timestamp": time_str,
            "file_path": None,
            "is_image": False,
            "sender_name": "其他使用者",
            "sender_avatar": ""
        }
        self.create_message_ui(msg_data)
        self.messages_data.append(msg_data)
        self.scroll_to_bottom()
        self.save_data()

    def on_frame_configure(self):
        self.canvas.config(scrollregion=self.canvas.bbox("all"))

    def on_mousewheel(self, event):
        direction = -1 * int(event.delta // 120)
        self.canvas.yview_scroll(direction, "units")

    def scroll_to_bottom(self):
        self.root.update_idletasks()
        self.canvas.config(scrollregion=self.canvas.bbox("all"))
        self.canvas.yview_moveto(1.0)

    def get_container_offset_in_canvas(self, widget):
        return widget.winfo_rooty() - self.canvas.winfo_rooty() + self.canvas.canvasy(0)

    def adjust_canvas_scroll(self, delta):
        total_height = self.canvas.bbox("all")[3]
        current_min, _ = self.canvas.yview()
        old_offset = current_min * total_height
        new_offset = old_offset + delta
        if new_offset < 0:
            new_offset = 0
        elif new_offset > (total_height - self.canvas.winfo_height()):
            new_offset = (total_height - self.canvas.winfo_height())
        self.canvas.yview_moveto(new_offset / total_height)

    def on_press_enter(self, event):
        # Debug: 確認是否觸發
        print("on_press_enter triggered")
        if self.uploading:
            messagebox.showinfo("上傳中", "檔案上傳尚未完成，請稍候再傳送訊息。")
            return
        text = self.entry_var.get().strip()
        if not text and not self.attached_file_path and not self.uploaded_file_id:
            print("無法送出：文字空且無檔案")
            return
        message = self.prepare_message(text)
        # Debug: 印出準備送出的訊息
        print("準備送出訊息:", message)
        self.send_network_message(message)
        self.send_message(text)

    def prepare_message(self, text):
        now = datetime.datetime.now()
        date_str = now.strftime("%Y/%m/%d")
        time_str = now.strftime("%H:%M:%S")
        msg_id = len(self.messages_data) + 1
        sender_name = self.profile.get("name", "匿名")
        sender_avatar = self.profile.get("avatar_data", "")
        msg_data = {
            "msg_id": msg_id,
            "text": text,
            "date": date_str,
            "timestamp": time_str,
            "file_path": None,
            "is_image": False,
            "sender_name": sender_name,
            "sender_avatar": sender_avatar
        }
        if self.uploaded_file_id:
            msg_data["file_chunked"] = True
            msg_data["file_id"] = self.uploaded_file_id
        elif self.attached_file_path:
            msg_data["file_path"] = self.attached_file_path
            if self.is_image_file(self.attached_file_path):
                msg_data["is_image"] = True
            try:
                with open(self.attached_file_path, "rb") as f:
                    file_bytes = f.read()
                file_b64 = base64.b64encode(file_bytes).decode("utf-8")
                msg_data["file_data"] = file_b64
                msg_data["file_name"] = os.path.basename(self.attached_file_path)
            except Exception as e:
                print("檔案編碼失敗:", e)
        return json.dumps(msg_data, ensure_ascii=False)

    def send_message(self, text):
        now = datetime.datetime.now()
        date_str = now.strftime("%Y/%m/%d")
        time_str = now.strftime("%H:%M:%S")
        msg_id = len(self.messages_data) + 1
        sender_name = self.profile.get("name", "匿名")
        sender_avatar = self.profile.get("avatar_data", "")
        msg_data = {
            "msg_id": msg_id,
            "text": text,
            "date": date_str,
            "timestamp": time_str,
            "file_path": None,
            "is_image": False,
            "sender_name": sender_name,
            "sender_avatar": sender_avatar
        }
        if self.uploaded_file_id:
            msg_data["file_chunked"] = True
            msg_data["file_id"] = self.uploaded_file_id
        elif self.attached_file_path:
            msg_data["file_path"] = self.attached_file_path
            if self.is_image_file(self.attached_file_path):
                msg_data["is_image"] = True
            try:
                with open(self.attached_file_path, "rb") as f:
                    file_bytes = f.read()
                file_b64 = base64.b64encode(file_bytes).decode("utf-8")
                msg_data["file_data"] = file_b64
                msg_data["file_name"] = os.path.basename(self.attached_file_path)
            except Exception as e:
                print("檔案編碼失敗:", e)
        self.create_message_ui(msg_data)
        self.messages_data.append(msg_data)
        self.entry_var.set("")
        self.preview_label.pack_forget()
        self.preview_label.config(text="", image="")
        self.attached_file_path = None
        self.attached_file_preview = None
        self.uploaded_file_id = None
        self.scroll_to_bottom()
        self.save_data()

    def on_close(self):
        self.save_data()
        if self.socket:
            self.socket.close()
        self.root.destroy()

    def load_data(self):
        self.last_header_info = {}
        if os.path.exists(self.data_path):
            try:
                with open(self.data_path, "r", encoding="utf-8") as f:
                    saved_msgs = json.load(f)
            except Exception as e:
                print("讀取舊紀錄失敗:", e)
                return
            for m in saved_msgs:
                self.create_message_ui(m)
            self.messages_data = saved_msgs
        self.scroll_to_bottom()

    def save_data(self):
        try:
            with open(self.data_path, "w", encoding="utf-8") as f:
                json.dump(self.messages_data, f, ensure_ascii=False, indent=2)
            print("已儲存資料至", self.data_path)
        except Exception as e:
            print("儲存資料失敗:", e)

    def attach_file(self):
        orig_path = filedialog.askopenfilename()
        if not orig_path:
            return
        # 所有檔案（包含影片）皆走附件上傳流程
        filesize = os.path.getsize(orig_path)
        if filesize > CHUNK_THRESHOLD:
            self.cancel_upload = False
            self.uploaded_file_id = os.path.basename(orig_path)
            self.uploading = True
            threading.Thread(target=self.send_file_in_chunks, args=(orig_path,), daemon=True).start()
            messagebox.showinfo("上傳中", "超大檔案正在分塊上傳中，請稍候...")
        else:
            base_name = os.path.basename(orig_path)
            new_path = os.path.join(self.attachments_dir, base_name)
            if not self.copy_file_with_progress(orig_path, new_path):
                return
            self.attached_file_path = new_path
            if self.is_image_file(new_path):
                try:
                    img = Image.open(new_path)
                    img.thumbnail(self.image_thumbnail_size)
                    preview_img = ImageTk.PhotoImage(img)
                    self.attached_file_preview = preview_img
                    self.preview_label.config(image=preview_img, text="")
                except:
                    self.preview_label.config(text=base_name, image="")
            else:
                self.preview_label.config(text=base_name, image="")
            self.preview_label.pack(side=tk.TOP, fill=tk.X)

    def send_file_in_chunks(self, file_path):
        filesize = os.path.getsize(file_path)
        chunk_size = 65536  # 64KB
        total_chunks = (filesize + chunk_size - 1) // chunk_size
        file_id = os.path.basename(file_path)
        start_time = time.time()
        # 建立進度視窗，背景白色，初始置頂 3 秒後取消
        progress_win = tk.Toplevel(self.root)
        progress_win.title("上傳檔案中...")
        progress_win.geometry("200x250")
        progress_win.configure(bg="white")
        progress_win.attributes('-topmost', True)
        progress_win.after(3000, lambda: progress_win.attributes('-topmost', False))
        
        canvas_size = 150
        canvas = tk.Canvas(progress_win, width=canvas_size, height=canvas_size, bg="white", highlightthickness=0)
        canvas.pack(pady=10)
        margin = 10
        x0, y0 = margin, margin
        x1, y1 = canvas_size - margin, canvas_size - margin
        # 只建立藍色 arc，初始 extent 為 0且 state 為 hidden
        arc = canvas.create_arc(x0, y0, x1, y1, start=270, extent=0, style="arc", outline="blue", width=2, state="hidden")
        
        time_label = tk.Label(progress_win, text="剩餘時間：--秒", font=("Arial", 12), bg="white")
        time_label.pack(pady=5)
        cancel_btn = tk.Button(progress_win, text="取消", command=lambda: self.cancel_upload_action(progress_win))
        cancel_btn.pack(pady=5)
        
        total_sent = 0
        for chunk_index in range(total_chunks):
            if self.cancel_upload:
                progress_win.destroy()
                messagebox.showinfo("上傳取消", "檔案上傳已取消。")
                self.uploading = False
                return False
            with open(file_path, "rb") as f:
                f.seek(chunk_index * chunk_size)
                chunk = f.read(chunk_size)
            b64_data = base64.b64encode(chunk).decode("utf-8")
            msg = {
                "file_chunk": True,
                "file_id": file_id,
                "chunk_index": chunk_index,
                "total_chunks": total_chunks,
                "data": b64_data
            }
            self.send_network_message(json.dumps(msg, ensure_ascii=False))
            total_sent += len(chunk)
            progress = total_sent / filesize
            if progress < 0.01:
                canvas.itemconfigure(arc, state="hidden")
            else:
                canvas.itemconfigure(arc, state="normal")
                extent = -progress * 360  # 負值表示順時針方向
                canvas.itemconfig(arc, extent=extent)
            elapsed = time.time() - start_time
            speed = total_sent / elapsed if elapsed > 0 else 0
            remaining = (filesize - total_sent) / speed if speed > 0 else 0
            time_label.config(text=f"剩餘時間：{int(remaining)}秒")
            progress_win.update_idletasks()
            time.sleep(0.01)
        progress_win.destroy()
        self.uploading = False
        return True

    def cancel_upload_action(self, win):
        self.cancel_upload = True
        win.destroy()

    def copy_file_with_progress(self, src, dst):
        filesize = os.path.getsize(src)
        chunk_size = 65536
        progress_win = tk.Toplevel(self.root)
        progress_win.title("上傳檔案中...")
        progress_win.geometry("300x100")
        progress_label = tk.Label(progress_win, text="上傳中...", font=("Arial", 12))
        progress_label.pack(pady=10)
        progress_bar = ttk.Progressbar(progress_win, orient="horizontal", length=250, mode="determinate")
        progress_bar.pack(pady=10)
        progress_bar["maximum"] = filesize
        total = 0
        try:
            with open(src, "rb") as fsrc, open(dst, "wb") as fdst:
                while True:
                    data = fsrc.read(chunk_size)
                    if not data:
                        break
                    fdst.write(data)
                    total += len(data)
                    progress_bar["value"] = total
                    progress_win.update_idletasks()
            progress_win.destroy()
            return True
        except Exception as e:
            progress_win.destroy()
            print("檔案複製失敗:", e)
            return False

    def get_day_frame(self, date_str):
        if date_str in self.day_frames:
            return self.day_frames[date_str]
        else:
            day_frame = tk.Frame(self.main_frame, bg="#2b2b2b")
            day_frame.pack(fill=tk.X, padx=10, pady=10)
            date_label = tk.Label(day_frame, text=f"=== {date_str} ===", bg="#2b2b2b", fg="white",
                                  font=("Arial", 25, "italic"))
            date_label.pack(anchor="w", padx=18, pady=5)
            self.day_frames[date_str] = day_frame
            return day_frame

    def parse_text_with_secret(self, text):
        parts = text.split("||")
        segments = []
        for i, chunk in enumerate(parts):
            if i % 2 == 0:
                if chunk:
                    segments.append(("normal", chunk))
            else:
                if chunk:
                    segments.append(("secret", chunk))
        return segments

    def create_message_ui(self, msg_data):
        day_frame = self.get_day_frame(msg_data["date"])
        container = tk.Frame(day_frame, bg="#2b2b2b")
        container.pack(fill=tk.X, padx=1, pady=1)
        container.bind("<Enter>", lambda e, mid=msg_data["msg_id"]: self.on_enter_message(mid))
        container.bind("<Leave>", lambda e, mid=msg_data["msg_id"]: self.on_leave_message(mid))
        
        date = msg_data["date"]
        sender = msg_data.get("sender_name", "匿名")
        show_header = True
        if date not in self.last_header_info:
            self.last_header_info[date] = (sender, 1)
        else:
            last_sender, count = self.last_header_info[date]
            if sender != last_sender:
                self.last_header_info[date] = (sender, 1)
            else:
                new_count = count + 1
                self.last_header_info[date] = (sender, new_count)
                if new_count % 7 != 1:
                    show_header = False

        if show_header:
            header_frame = tk.Frame(container, bg="#2b2b2b")
            header_frame.pack(side=tk.TOP, anchor="w", padx=5, pady=2)
            if "sender_avatar" in msg_data and msg_data["sender_avatar"]:
                try:
                    avatar_bytes = base64.b64decode(msg_data["sender_avatar"])
                    avatar_img = Image.open(BytesIO(avatar_bytes))
                    avatar_img.thumbnail(self.avatar_size)
                    avatar_photo = ImageTk.PhotoImage(avatar_img)
                    avatar_label = tk.Label(header_frame, image=avatar_photo, bg="#2b2b2b")
                    avatar_label.image = avatar_photo
                    avatar_label.pack(side=tk.LEFT)
                except Exception as e:
                    print("頭像顯示失敗:", e)
            name_label = tk.Label(header_frame, text=sender, bg="#2b2b2b", fg="white", font=("Arial",16))
            name_label.pack(side=tk.LEFT, padx=5)
        left_frame = tk.Frame(container, bg="#2b2b2b")
        left_frame.pack(side=tk.LEFT, anchor="nw")
        text_frame = tk.Frame(left_frame, bg="#2b2b2b")
        text_frame.pack(side=tk.TOP, anchor="w", padx=5, pady=2)
        segments = self.parse_text_with_secret(msg_data["text"])
        if segments:
            for segtype, segtext in segments:
                if segtype == "normal":
                    lbl = tk.Label(text_frame, text=segtext, bg="#2b2b2b", fg="white", font=self.message_font)
                    lbl.pack(side=tk.LEFT, anchor="w")
                else:
                    hidden_lbl = tk.Label(text_frame, text="點一下顯示", bg="#555555", fg="white", font=self.message_font)
                    hidden_lbl.pack(side=tk.LEFT, anchor="w", padx=2)
                    store = {"hidden": True, "secret_text": segtext}
                    def on_toggle(e, lb=hidden_lbl, d=store):
                        if d["hidden"]:
                            lb.config(text=d["secret_text"], bg="#2b2b2b")
                            d["hidden"] = False
                        else:
                            lb.config(text="點一下顯示", bg="#555555")
                            d["hidden"] = True
                    hidden_lbl.bind("<Button-1>", on_toggle)
        if msg_data["msg_id"] not in self.ephemeral_map:
            self.ephemeral_map[msg_data["msg_id"]] = {}
        self.ephemeral_map[msg_data["msg_id"]]["text_frame"] = text_frame

        attach_frame = tk.Frame(left_frame, bg="#2b2b2b")
        attach_frame.pack(side=tk.TOP, anchor="w", padx=5, pady=2)
        original_photo = None
        hover_photo = None
        canvas_for_image = None
        if "file_data" in msg_data:
            file_name = msg_data.get("file_name", "download_file")
            if msg_data.get("is_image", False):
                try:
                    file_bytes = base64.b64decode(msg_data["file_data"])
                    img = Image.open(BytesIO(file_bytes))
                    img.thumbnail(self.image_thumbnail_size)
                    original_photo = ImageTk.PhotoImage(img)
                    alpha_img = self.make_alpha_image(img, alpha=0.7)
                    hover_photo = ImageTk.PhotoImage(alpha_img)
                    canvas_for_image = tk.Canvas(attach_frame,
                                                  width=self.image_thumbnail_size[0],
                                                  height=self.image_thumbnail_size[1],
                                                  bg="#2b2b2b", highlightthickness=0)
                    canvas_for_image.pack(anchor="w")
                    canvas_for_image.create_image(0, 0, anchor="nw", image=original_photo)
                except Exception as e:
                    print("解碼圖片失敗:", e)
                    tk.Label(attach_frame, text=f"[附件] {file_name}", bg="#2b2b2b", fg="white",
                             font=self.message_font).pack(anchor="w")
            else:
                def download_file():
                    save_path = filedialog.asksaveasfilename(initialfile=file_name)
                    if save_path:
                        try:
                            with open(save_path, "wb") as f:
                                f.write(base64.b64decode(msg_data["file_data"]))
                            messagebox.showinfo("下載完成", f"檔案已儲存到 {save_path}")
                        except Exception as e:
                            messagebox.showerror("錯誤", f"儲存檔案失敗: {e}")
                tk.Button(attach_frame, text=f"下載 {file_name}", bg="#555555", fg="white",
                          font=self.message_font, command=download_file).pack(anchor="w")
        elif msg_data.get("file_path"):
            file_name = os.path.basename(msg_data["file_path"])
            if msg_data["is_image"]:
                canvas_for_image = tk.Canvas(attach_frame,
                                              width=self.image_thumbnail_size[0],
                                              height=self.image_thumbnail_size[1],
                                              bg="#2b2b2b", highlightthickness=0)
                canvas_for_image.pack(anchor="w")
                try:
                    img = Image.open(msg_data["file_path"])
                    img.thumbnail(self.image_thumbnail_size)
                    original_photo = ImageTk.PhotoImage(img)
                    alpha_img = self.make_alpha_image(img, alpha=0.7)
                    hover_photo = ImageTk.PhotoImage(alpha_img)
                    canvas_for_image.create_image(0, 0, anchor="nw", image=original_photo)
                except:
                    tk.Label(attach_frame, text=f"[附件] {file_name}", bg="#2b2b2b", fg="white",
                             font=self.message_font).pack(anchor="w")
                else:
                    canvas_for_image.bind("<Enter>", lambda e, fn=file_name, mid=msg_data["msg_id"]: self.on_image_enter(mid, fn))
                    canvas_for_image.bind("<Leave>", lambda e, mid=msg_data["msg_id"]: self.on_image_leave(mid))
            else:
                def download_file():
                    save_path = filedialog.asksaveasfilename(initialfile=file_name)
                    if save_path:
                        try:
                            with open(msg_data["file_path"], "rb") as src_file:
                                data = src_file.read()
                            with open(save_path, "wb") as dest_file:
                                dest_file.write(data)
                            messagebox.showinfo("下載完成", f"檔案已儲存到 {save_path}")
                        except Exception as e:
                            messagebox.showerror("錯誤", f"儲存檔案失敗: {e}")
                tk.Button(attach_frame, text=f"下載 {file_name}", bg="#555555", fg="white",
                          font=self.message_font, command=download_file).pack(anchor="w")
        right_frame = tk.Frame(container, bg="#2b2b2b")
        right_frame.pack(side=tk.RIGHT, anchor="n")
        time_label = tk.Label(right_frame, text=msg_data["timestamp"], bg="#2b2b2b", fg="white", font=("Arial",20))
        edit_btn = tk.Button(right_frame, text="編輯", bg="#4a4a4a", fg="white",
                             activebackground="#000000", activeforeground="white",
                             command=lambda: self.on_edit_message_inplace(msg_data))
        edit_btn.bind("<Enter>", lambda e: edit_btn.config(bg="#2b2b2b"))
        edit_btn.bind("<Leave>", lambda e: edit_btn.config(bg="#4a4a4a"))
        del_btn = tk.Button(right_frame, text="刪除", bg="#4a4a4a", fg="white",
                            activebackground="#000000", activeforeground="white",
                            command=lambda: self.on_delete_message(msg_data["msg_id"]))
        del_btn.bind("<Enter>", lambda e: del_btn.config(bg="#2b2b2b"))
        del_btn.bind("<Leave>", lambda e: del_btn.config(bg="#4a4a4a"))
        self.ephemeral_map[msg_data["msg_id"]].update({
            "container": container,
            "right_frame": right_frame,
            "time_label": time_label,
            "edit_btn": edit_btn,
            "del_btn": del_btn,
            "canvas_for_image": canvas_for_image,
            "original_photo": original_photo,
            "hover_photo": hover_photo
        })

    def on_edit_message_inplace(self, msg_data):
        mid = msg_data["msg_id"]
        ep = self.ephemeral_map.get(mid)
        if not ep or "text_frame" not in ep:
            return
        text_frame = ep["text_frame"]
        parent = text_frame.master
        attach_frame = None
        for child in parent.winfo_children():
            if child != text_frame:
                attach_frame = child
                break
        text_frame.pack_forget()
        if attach_frame:
            entry = tk.Entry(parent, font=self.message_font, bg="#3a3a3a", fg="white")
            entry.pack(before=attach_frame, anchor="w", padx=5, pady=2)
        else:
            entry = tk.Entry(parent, font=self.message_font, bg="#3a3a3a", fg="white")
            entry.pack(anchor="w", padx=5, pady=2)
        entry.insert(0, msg_data["text"])
        entry.focus_set()
        def finish_edit(event=None):
            new_text = entry.get()
            msg_data["text"] = new_text
            entry.destroy()
            for child in text_frame.winfo_children():
                child.destroy()
            segments = self.parse_text_with_secret(new_text)
            for segtype, segtext in segments:
                if segtype == "normal":
                    lbl = tk.Label(text_frame, text=segtext, bg="#2b2b2b", fg="white", font=self.message_font)
                    lbl.pack(side=tk.LEFT, anchor="w")
                else:
                    hidden_lbl = tk.Label(text_frame, text="點一下顯示", bg="#555555", fg="white", font=self.message_font)
                    hidden_lbl.pack(side=tk.LEFT, anchor="w", padx=2)
                    store = {"hidden": True, "secret_text": segtext}
                    def on_toggle(e, lb=hidden_lbl, d=store):
                        if d["hidden"]:
                            lb.config(text=d["secret_text"], bg="#2b2b2b")
                            d["hidden"] = False
                        else:
                            lb.config(text="點一下顯示", bg="#555555")
                            d["hidden"] = True
                    hidden_lbl.bind("<Button-1>", on_toggle)
            if attach_frame:
                text_frame.pack(before=attach_frame, anchor="w", padx=5, pady=2)
            else:
                text_frame.pack(anchor="w", padx=5, pady=2)
            self.save_data()
        def cancel_edit(event=None):
            entry.destroy()
            if attach_frame:
                text_frame.pack(before=attach_frame, anchor="w", padx=5, pady=2)
            else:
                text_frame.pack(anchor="w", padx=5, pady=2)
        entry.bind("<Return>", finish_edit)
        entry.bind("<Escape>", cancel_edit)

    def on_enter_message(self, msg_id):
        ep = self.ephemeral_map.get(msg_id)
        if ep:
            ep["time_label"].pack(side=tk.LEFT, padx=5)
            ep["edit_btn"].pack(side=tk.LEFT, padx=(10,5))
            ep["del_btn"].pack(side=tk.LEFT, padx=5)

    def on_leave_message(self, msg_id):
        ep = self.ephemeral_map.get(msg_id)
        if ep:
            ep["time_label"].pack_forget()
            ep["edit_btn"].pack_forget()
            ep["del_btn"].pack_forget()

    def on_delete_message(self, msg_id):
        if not messagebox.askyesno("確認刪除", "確定要刪除此訊息嗎？"):
            return
        idx = None
        for i, m in enumerate(self.messages_data):
            if m["msg_id"] == msg_id:
                idx = i
                break
        if idx is not None:
            self.messages_data.pop(idx)
        ep = self.ephemeral_map.pop(msg_id, None)
        if ep:
            ep["container"].destroy()
        self.save_data()

    def make_alpha_image(self, pil_img, alpha=0.7):
        if pil_img.mode != "RGBA":
            new_img = pil_img.convert("RGBA")
        else:
            new_img = pil_img.copy()
        new_img.putalpha(int(255 * alpha))
        return new_img

    def on_image_enter(self, msg_id, file_name):
        ep = self.ephemeral_map.get(msg_id)
        if not ep:
            return
        c = ep["canvas_for_image"]
        if not c:
            return
        hp = ep["hover_photo"]
        if not hp:
            return
        w = self.image_thumbnail_size[0]
        h = self.image_thumbnail_size[1]
        c.delete("all")
        c.create_image(0, 0, anchor="nw", image=hp)
        c.create_text(w//2, h//2, text=file_name, fill="white", font=("Arial",18), anchor="center")

    def on_image_leave(self, msg_id):
        ep = self.ephemeral_map.get(msg_id)
        if not ep:
            return
        c = ep["canvas_for_image"]
        if not c:
            return
        op = ep["original_photo"]
        if not op:
            return
        c.delete("all")
        c.create_image(0, 0, anchor="nw", image=op)

    def on_search_icon_click(self):
        if self.search_entry.cget("width") == 0:
            self.search_entry.config(width=20)
            self.search_entry.focus_set()
        else:
            self.search_entry.config(width=0)
            self.search_listbox.place_forget()

    def on_search_var_changed(self, *args):
        kw = self.search_var.get().strip()
        if not kw:
            self.search_listbox.place_forget()
            return
        results = []
        for m in self.messages_data:
            if kw.lower() in m["text"].lower():
                st = m["text"]
                if len(st) > 30:
                    st = st[:30] + "..."
                results.append((m["msg_id"], st))
        if not results:
            self.search_listbox.place_forget()
            return
        x = self.search_entry.winfo_rootx()
        y = self.search_entry.winfo_rooty() + self.search_entry.winfo_height()
        self.search_listbox.delete(0, tk.END)
        for (mid, st) in results:
            self.search_listbox.insert(tk.END, f"[{mid}] {st}")
        self.search_listbox.place(x=x, y=y, width=300, height=120)
        self.search_listbox.bind("<<ListboxSelect>>", self.on_search_select)

    def on_search_select(self, event):
        if not self.search_listbox.curselection():
            return
        idx = self.search_listbox.curselection()[0]
        line = self.search_listbox.get(idx)
        try:
            lb = line.index("[")
            rb = line.index("]")
            msg_id_str = line[lb+1:rb]
            msg_id = int(msg_id_str)
        except:
            return
        self.search_listbox.place_forget()
        ep = self.ephemeral_map.get(msg_id)
        if not ep:
            return
        container = ep["container"]
        y = container.winfo_rooty() - self.canvas.winfo_rooty() + self.canvas.canvasy(0)
        self.canvas.yview_moveto(y / self.canvas.bbox("all")[3])

    def toggle_user_list(self, event):
        if self.user_list_frame.winfo_ismapped():
            self.user_list_frame.lower()
        else:
            for widget in self.user_list_frame.winfo_children():
                widget.destroy()
            title = tk.Label(self.user_list_frame, text="可聊天使用者", font=("Arial", 30), bg="#333333", fg="white")
            title.pack(pady=20)
            for user in self.user_list:
                user_label = tk.Label(self.user_list_frame, text=user, font=("Arial", 20), bg="#333333", fg="white")
                user_label.pack(pady=10, fill="x")
                user_label.configure(anchor="center")
            self.user_list_frame.lift()

    def prepare_message(self, text):
        now = datetime.datetime.now()
        date_str = now.strftime("%Y/%m/%d")
        time_str = now.strftime("%H:%M:%S")
        msg_id = len(self.messages_data) + 1
        sender_name = self.profile.get("name", "匿名")
        sender_avatar = self.profile.get("avatar_data", "")
        msg_data = {
            "msg_id": msg_id,
            "text": text,
            "date": date_str,
            "timestamp": time_str,
            "file_path": None,
            "is_image": False,
            "sender_name": sender_name,
            "sender_avatar": sender_avatar
        }
        if self.uploaded_file_id:
            msg_data["file_chunked"] = True
            msg_data["file_id"] = self.uploaded_file_id
        elif self.attached_file_path:
            msg_data["file_path"] = self.attached_file_path
            if self.is_image_file(self.attached_file_path):
                msg_data["is_image"] = True
            try:
                with open(self.attached_file_path, "rb") as f:
                    file_bytes = f.read()
                file_b64 = base64.b64encode(file_bytes).decode("utf-8")
                msg_data["file_data"] = file_b64
                msg_data["file_name"] = os.path.basename(self.attached_file_path)
            except Exception as e:
                print("檔案編碼失敗:", e)
        return json.dumps(msg_data, ensure_ascii=False)

    def send_message(self, text):
        now = datetime.datetime.now()
        date_str = now.strftime("%Y/%m/%d")
        time_str = now.strftime("%H:%M:%S")
        msg_id = len(self.messages_data) + 1
        sender_name = self.profile.get("name", "匿名")
        sender_avatar = self.profile.get("avatar_data", "")
        msg_data = {
            "msg_id": msg_id,
            "text": text,
            "date": date_str,
            "timestamp": time_str,
            "file_path": None,
            "is_image": False,
            "sender_name": sender_name,
            "sender_avatar": sender_avatar
        }
        if self.uploaded_file_id:
            msg_data["file_chunked"] = True
            msg_data["file_id"] = self.uploaded_file_id
        elif self.attached_file_path:
            msg_data["file_path"] = self.attached_file_path
            if self.is_image_file(self.attached_file_path):
                msg_data["is_image"] = True
            try:
                with open(self.attached_file_path, "rb") as f:
                    file_bytes = f.read()
                file_b64 = base64.b64encode(file_bytes).decode("utf-8")
                msg_data["file_data"] = file_b64
                msg_data["file_name"] = os.path.basename(self.attached_file_path)
            except Exception as e:
                print("檔案編碼失敗:", e)
        self.create_message_ui(msg_data)
        self.messages_data.append(msg_data)
        self.entry_var.set("")
        self.preview_label.pack_forget()
        self.preview_label.config(text="", image="")
        self.attached_file_path = None
        self.attached_file_preview = None
        self.uploaded_file_id = None
        self.scroll_to_bottom()
        self.save_data()

    def on_close(self):
        self.save_data()
        if self.socket:
            self.socket.close()
        self.root.destroy()

    def load_data(self):
        self.last_header_info = {}
        if os.path.exists(self.data_path):
            try:
                with open(self.data_path, "r", encoding="utf-8") as f:
                    saved_msgs = json.load(f)
            except Exception as e:
                print("讀取舊紀錄失敗:", e)
                return
            for m in saved_msgs:
                self.create_message_ui(m)
            self.messages_data = saved_msgs
        self.scroll_to_bottom()

    def save_data(self):
        try:
            with open(self.data_path, "w", encoding="utf-8") as f:
                json.dump(self.messages_data, f, ensure_ascii=False, indent=2)
            print("已儲存資料至", self.data_path)
        except Exception as e:
            print("儲存資料失敗:", e)

    def attach_file(self):
        orig_path = filedialog.askopenfilename()
        if not orig_path:
            return
        # 所有檔案（包含影片）皆走附件上傳流程
        filesize = os.path.getsize(orig_path)
        if filesize > CHUNK_THRESHOLD:
            self.cancel_upload = False
            self.uploaded_file_id = os.path.basename(orig_path)
            self.uploading = True
            threading.Thread(target=self.send_file_in_chunks, args=(orig_path,), daemon=True).start()
            messagebox.showinfo("上傳中", "超大檔案正在分塊上傳中，請稍候...")
        else:
            base_name = os.path.basename(orig_path)
            new_path = os.path.join(self.attachments_dir, base_name)
            if not self.copy_file_with_progress(orig_path, new_path):
                return
            self.attached_file_path = new_path
            if self.is_image_file(new_path):
                try:
                    img = Image.open(new_path)
                    img.thumbnail(self.image_thumbnail_size)
                    preview_img = ImageTk.PhotoImage(img)
                    self.attached_file_preview = preview_img
                    self.preview_label.config(image=preview_img, text="")
                except:
                    self.preview_label.config(text=base_name, image="")
            else:
                self.preview_label.config(text=base_name, image="")
            self.preview_label.pack(side=tk.TOP, fill=tk.X)

    def send_file_in_chunks(self, file_path):
        filesize = os.path.getsize(file_path)
        chunk_size = 65536  # 64KB
        total_chunks = (filesize + chunk_size - 1) // chunk_size
        file_id = os.path.basename(file_path)
        start_time = time.time()
        # 建立進度視窗，背景白色，初始置頂 3 秒後取消
        progress_win = tk.Toplevel(self.root)
        progress_win.title("上傳檔案中...")
        progress_win.geometry("200x250")
        progress_win.configure(bg="white")
        progress_win.attributes('-topmost', True)
        progress_win.after(3000, lambda: progress_win.attributes('-topmost', False))
        
        canvas_size = 150
        canvas = tk.Canvas(progress_win, width=canvas_size, height=canvas_size, bg="white", highlightthickness=0)
        canvas.pack(pady=10)
        margin = 10
        x0, y0 = margin, margin
        x1, y1 = canvas_size - margin, canvas_size - margin
        # 只建立藍色 arc，初始 extent 為 0且 state 為 hidden
        arc = canvas.create_arc(x0, y0, x1, y1, start=270, extent=0, style="arc", outline="blue", width=2, state="hidden")
        
        time_label = tk.Label(progress_win, text="剩餘時間：--秒", font=("Arial", 12), bg="white")
        time_label.pack(pady=5)
        cancel_btn = tk.Button(progress_win, text="取消", command=lambda: self.cancel_upload_action(progress_win))
        cancel_btn.pack(pady=5)
        
        total_sent = 0
        for chunk_index in range(total_chunks):
            if self.cancel_upload:
                progress_win.destroy()
                messagebox.showinfo("上傳取消", "檔案上傳已取消。")
                self.uploading = False
                return False
            with open(file_path, "rb") as f:
                f.seek(chunk_index * chunk_size)
                chunk = f.read(chunk_size)
            b64_data = base64.b64encode(chunk).decode("utf-8")
            msg = {
                "file_chunk": True,
                "file_id": file_id,
                "chunk_index": chunk_index,
                "total_chunks": total_chunks,
                "data": b64_data
            }
            self.send_network_message(json.dumps(msg, ensure_ascii=False))
            total_sent += len(chunk)
            progress = total_sent / filesize
            if progress < 0.01:
                canvas.itemconfigure(arc, state="hidden")
            else:
                canvas.itemconfigure(arc, state="normal")
                extent = -progress * 360  # 負值表示順時針方向
                canvas.itemconfig(arc, extent=extent)
            elapsed = time.time() - start_time
            speed = total_sent / elapsed if elapsed > 0 else 0
            remaining = (filesize - total_sent) / speed if speed > 0 else 0
            time_label.config(text=f"剩餘時間：{int(remaining)}秒")
            progress_win.update_idletasks()
            time.sleep(0.01)
        progress_win.destroy()
        self.uploading = False
        return True

    def cancel_upload_action(self, win):
        self.cancel_upload = True
        win.destroy()

    def copy_file_with_progress(self, src, dst):
        filesize = os.path.getsize(src)
        chunk_size = 65536
        progress_win = tk.Toplevel(self.root)
        progress_win.title("上傳檔案中...")
        progress_win.geometry("300x100")
        progress_label = tk.Label(progress_win, text="上傳中...", font=("Arial", 12))
        progress_label.pack(pady=10)
        progress_bar = ttk.Progressbar(progress_win, orient="horizontal", length=250, mode="determinate")
        progress_bar.pack(pady=10)
        progress_bar["maximum"] = filesize
        total = 0
        try:
            with open(src, "rb") as fsrc, open(dst, "wb") as fdst:
                while True:
                    data = fsrc.read(chunk_size)
                    if not data:
                        break
                    fdst.write(data)
                    total += len(data)
                    progress_bar["value"] = total
                    progress_win.update_idletasks()
            progress_win.destroy()
            return True
        except Exception as e:
            progress_win.destroy()
            print("檔案複製失敗:", e)
            return False

    def get_day_frame(self, date_str):
        if date_str in self.day_frames:
            return self.day_frames[date_str]
        else:
            day_frame = tk.Frame(self.main_frame, bg="#2b2b2b")
            day_frame.pack(fill=tk.X, padx=10, pady=10)
            date_label = tk.Label(day_frame, text=f"=== {date_str} ===", bg="#2b2b2b", fg="white",
                                  font=("Arial", 25, "italic"))
            date_label.pack(anchor="w", padx=18, pady=5)
            self.day_frames[date_str] = day_frame
            return day_frame

    def parse_text_with_secret(self, text):
        parts = text.split("||")
        segments = []
        for i, chunk in enumerate(parts):
            if i % 2 == 0:
                if chunk:
                    segments.append(("normal", chunk))
            else:
                if chunk:
                    segments.append(("secret", chunk))
        return segments

    def create_message_ui(self, msg_data):
        day_frame = self.get_day_frame(msg_data["date"])
        container = tk.Frame(day_frame, bg="#2b2b2b")
        container.pack(fill=tk.X, padx=1, pady=1)
        container.bind("<Enter>", lambda e, mid=msg_data["msg_id"]: self.on_enter_message(mid))
        container.bind("<Leave>", lambda e, mid=msg_data["msg_id"]: self.on_leave_message(mid))
        
        date = msg_data["date"]
        sender = msg_data.get("sender_name", "匿名")
        show_header = True
        if date not in self.last_header_info:
            self.last_header_info[date] = (sender, 1)
        else:
            last_sender, count = self.last_header_info[date]
            if sender != last_sender:
                self.last_header_info[date] = (sender, 1)
            else:
                new_count = count + 1
                self.last_header_info[date] = (sender, new_count)
                if new_count % 7 != 1:
                    show_header = False

        if show_header:
            header_frame = tk.Frame(container, bg="#2b2b2b")
            header_frame.pack(side=tk.TOP, anchor="w", padx=5, pady=2)
            if "sender_avatar" in msg_data and msg_data["sender_avatar"]:
                try:
                    avatar_bytes = base64.b64decode(msg_data["sender_avatar"])
                    avatar_img = Image.open(BytesIO(avatar_bytes))
                    avatar_img.thumbnail(self.avatar_size)
                    avatar_photo = ImageTk.PhotoImage(avatar_img)
                    avatar_label = tk.Label(header_frame, image=avatar_photo, bg="#2b2b2b")
                    avatar_label.image = avatar_photo
                    avatar_label.pack(side=tk.LEFT)
                except Exception as e:
                    print("頭像顯示失敗:", e)
            name_label = tk.Label(header_frame, text=sender, bg="#2b2b2b", fg="white", font=("Arial",16))
            name_label.pack(side=tk.LEFT, padx=5)
        left_frame = tk.Frame(container, bg="#2b2b2b")
        left_frame.pack(side=tk.LEFT, anchor="nw")
        text_frame = tk.Frame(left_frame, bg="#2b2b2b")
        text_frame.pack(side=tk.TOP, anchor="w", padx=5, pady=2)
        segments = self.parse_text_with_secret(msg_data["text"])
        if segments:
            for segtype, segtext in segments:
                if segtype == "normal":
                    lbl = tk.Label(text_frame, text=segtext, bg="#2b2b2b", fg="white", font=self.message_font)
                    lbl.pack(side=tk.LEFT, anchor="w")
                else:
                    hidden_lbl = tk.Label(text_frame, text="點一下顯示", bg="#555555", fg="white", font=self.message_font)
                    hidden_lbl.pack(side=tk.LEFT, anchor="w", padx=2)
                    store = {"hidden": True, "secret_text": segtext}
                    def on_toggle(e, lb=hidden_lbl, d=store):
                        if d["hidden"]:
                            lb.config(text=d["secret_text"], bg="#2b2b2b")
                            d["hidden"] = False
                        else:
                            lb.config(text="點一下顯示", bg="#555555")
                            d["hidden"] = True
                    hidden_lbl.bind("<Button-1>", on_toggle)
        if msg_data["msg_id"] not in self.ephemeral_map:
            self.ephemeral_map[msg_data["msg_id"]] = {}
        self.ephemeral_map[msg_data["msg_id"]]["text_frame"] = text_frame

        attach_frame = tk.Frame(left_frame, bg="#2b2b2b")
        attach_frame.pack(side=tk.TOP, anchor="w", padx=5, pady=2)
        original_photo = None
        hover_photo = None
        canvas_for_image = None
        if "file_data" in msg_data:
            file_name = msg_data.get("file_name", "download_file")
            if msg_data.get("is_image", False):
                try:
                    file_bytes = base64.b64decode(msg_data["file_data"])
                    img = Image.open(BytesIO(file_bytes))
                    img.thumbnail(self.image_thumbnail_size)
                    original_photo = ImageTk.PhotoImage(img)
                    alpha_img = self.make_alpha_image(img, alpha=0.7)
                    hover_photo = ImageTk.PhotoImage(alpha_img)
                    canvas_for_image = tk.Canvas(attach_frame,
                                                  width=self.image_thumbnail_size[0],
                                                  height=self.image_thumbnail_size[1],
                                                  bg="#2b2b2b", highlightthickness=0)
                    canvas_for_image.pack(anchor="w")
                    canvas_for_image.create_image(0, 0, anchor="nw", image=original_photo)
                except Exception as e:
                    print("解碼圖片失敗:", e)
                    tk.Label(attach_frame, text=f"[附件] {file_name}", bg="#2b2b2b", fg="white",
                             font=self.message_font).pack(anchor="w")
            else:
                def download_file():
                    save_path = filedialog.asksaveasfilename(initialfile=file_name)
                    if save_path:
                        try:
                            with open(save_path, "wb") as f:
                                f.write(base64.b64decode(msg_data["file_data"]))
                            messagebox.showinfo("下載完成", f"檔案已儲存到 {save_path}")
                        except Exception as e:
                            messagebox.showerror("錯誤", f"儲存檔案失敗: {e}")
                tk.Button(attach_frame, text=f"下載 {file_name}", bg="#555555", fg="white",
                          font=self.message_font, command=download_file).pack(anchor="w")
        elif msg_data.get("file_path"):
            file_name = os.path.basename(msg_data["file_path"])
            if msg_data["is_image"]:
                canvas_for_image = tk.Canvas(attach_frame,
                                              width=self.image_thumbnail_size[0],
                                              height=self.image_thumbnail_size[1],
                                              bg="#2b2b2b", highlightthickness=0)
                canvas_for_image.pack(anchor="w")
                try:
                    img = Image.open(msg_data["file_path"])
                    img.thumbnail(self.image_thumbnail_size)
                    original_photo = ImageTk.PhotoImage(img)
                    alpha_img = self.make_alpha_image(img, alpha=0.7)
                    hover_photo = ImageTk.PhotoImage(alpha_img)
                    canvas_for_image.create_image(0, 0, anchor="nw", image=original_photo)
                except:
                    tk.Label(attach_frame, text=f"[附件] {file_name}", bg="#2b2b2b", fg="white",
                             font=self.message_font).pack(anchor="w")
                else:
                    canvas_for_image.bind("<Enter>", lambda e, fn=file_name, mid=msg_data["msg_id"]: self.on_image_enter(mid, fn))
                    canvas_for_image.bind("<Leave>", lambda e, mid=msg_data["msg_id"]: self.on_image_leave(mid))
            else:
                def download_file():
                    save_path = filedialog.asksaveasfilename(initialfile=file_name)
                    if save_path:
                        try:
                            with open(msg_data["file_path"], "rb") as src_file:
                                data = src_file.read()
                            with open(save_path, "wb") as dest_file:
                                dest_file.write(data)
                            messagebox.showinfo("下載完成", f"檔案已儲存到 {save_path}")
                        except Exception as e:
                            messagebox.showerror("錯誤", f"儲存檔案失敗: {e}")
                tk.Button(attach_frame, text=f"下載 {file_name}", bg="#555555", fg="white",
                          font=self.message_font, command=download_file).pack(anchor="w")
        right_frame = tk.Frame(container, bg="#2b2b2b")
        right_frame.pack(side=tk.RIGHT, anchor="n")
        time_label = tk.Label(right_frame, text=msg_data["timestamp"], bg="#2b2b2b", fg="white", font=("Arial",20))
        edit_btn = tk.Button(right_frame, text="編輯", bg="#4a4a4a", fg="white",
                             activebackground="#000000", activeforeground="white",
                             command=lambda: self.on_edit_message_inplace(msg_data))
        edit_btn.bind("<Enter>", lambda e: edit_btn.config(bg="#2b2b2b"))
        edit_btn.bind("<Leave>", lambda e: edit_btn.config(bg="#4a4a4a"))
        del_btn = tk.Button(right_frame, text="刪除", bg="#4a4a4a", fg="white",
                            activebackground="#000000", activeforeground="white",
                            command=lambda: self.on_delete_message(msg_data["msg_id"]))
        del_btn.bind("<Enter>", lambda e: del_btn.config(bg="#2b2b2b"))
        del_btn.bind("<Leave>", lambda e: del_btn.config(bg="#4a4a4a"))
        self.ephemeral_map[msg_data["msg_id"]].update({
            "container": container,
            "right_frame": right_frame,
            "time_label": time_label,
            "edit_btn": edit_btn,
            "del_btn": del_btn,
            "canvas_for_image": canvas_for_image,
            "original_photo": original_photo,
            "hover_photo": hover_photo
        })

    def on_edit_message_inplace(self, msg_data):
        mid = msg_data["msg_id"]
        ep = self.ephemeral_map.get(mid)
        if not ep or "text_frame" not in ep:
            return
        text_frame = ep["text_frame"]
        parent = text_frame.master
        attach_frame = None
        for child in parent.winfo_children():
            if child != text_frame:
                attach_frame = child
                break
        text_frame.pack_forget()
        if attach_frame:
            entry = tk.Entry(parent, font=self.message_font, bg="#3a3a3a", fg="white")
            entry.pack(before=attach_frame, anchor="w", padx=5, pady=2)
        else:
            entry = tk.Entry(parent, font=self.message_font, bg="#3a3a3a", fg="white")
            entry.pack(anchor="w", padx=5, pady=2)
        entry.insert(0, msg_data["text"])
        entry.focus_set()
        def finish_edit(event=None):
            new_text = entry.get()
            msg_data["text"] = new_text
            entry.destroy()
            for child in text_frame.winfo_children():
                child.destroy()
            segments = self.parse_text_with_secret(new_text)
            for segtype, segtext in segments:
                if segtype == "normal":
                    lbl = tk.Label(text_frame, text=segtext, bg="#2b2b2b", fg="white", font=self.message_font)
                    lbl.pack(side=tk.LEFT, anchor="w")
                else:
                    hidden_lbl = tk.Label(text_frame, text="點一下顯示", bg="#555555", fg="white", font=self.message_font)
                    hidden_lbl.pack(side=tk.LEFT, anchor="w", padx=2)
                    store = {"hidden": True, "secret_text": segtext}
                    def on_toggle(e, lb=hidden_lbl, d=store):
                        if d["hidden"]:
                            lb.config(text=d["secret_text"], bg="#2b2b2b")
                            d["hidden"] = False
                        else:
                            lb.config(text="點一下顯示", bg="#555555")
                            d["hidden"] = True
                    hidden_lbl.bind("<Button-1>", on_toggle)
            if attach_frame:
                text_frame.pack(before=attach_frame, anchor="w", padx=5, pady=2)
            else:
                text_frame.pack(anchor="w", padx=5, pady=2)
            self.save_data()
        def cancel_edit(event=None):
            entry.destroy()
            if attach_frame:
                text_frame.pack(before=attach_frame, anchor="w", padx=5, pady=2)
            else:
                text_frame.pack(anchor="w", padx=5, pady=2)
        entry.bind("<Return>", finish_edit)
        entry.bind("<Escape>", cancel_edit)

    def on_enter_message(self, msg_id):
        ep = self.ephemeral_map.get(msg_id)
        if ep:
            ep["time_label"].pack(side=tk.LEFT, padx=5)
            ep["edit_btn"].pack(side=tk.LEFT, padx=(10,5))
            ep["del_btn"].pack(side=tk.LEFT, padx=5)

    def on_leave_message(self, msg_id):
        ep = self.ephemeral_map.get(msg_id)
        if ep:
            ep["time_label"].pack_forget()
            ep["edit_btn"].pack_forget()
            ep["del_btn"].pack_forget()

    def on_delete_message(self, msg_id):
        if not messagebox.askyesno("確認刪除", "確定要刪除此訊息嗎？"):
            return
        idx = None
        for i, m in enumerate(self.messages_data):
            if m["msg_id"] == msg_id:
                idx = i
                break
        if idx is not None:
            self.messages_data.pop(idx)
        ep = self.ephemeral_map.pop(msg_id, None)
        if ep:
            ep["container"].destroy()
        self.save_data()

    def make_alpha_image(self, pil_img, alpha=0.7):
        if pil_img.mode != "RGBA":
            new_img = pil_img.convert("RGBA")
        else:
            new_img = pil_img.copy()
        new_img.putalpha(int(255 * alpha))
        return new_img

    def on_image_enter(self, msg_id, file_name):
        ep = self.ephemeral_map.get(msg_id)
        if not ep:
            return
        c = ep["canvas_for_image"]
        if not c:
            return
        hp = ep["hover_photo"]
        if not hp:
            return
        w = self.image_thumbnail_size[0]
        h = self.image_thumbnail_size[1]
        c.delete("all")
        c.create_image(0, 0, anchor="nw", image=hp)
        c.create_text(w//2, h//2, text=file_name, fill="white", font=("Arial",18), anchor="center")

    def on_image_leave(self, msg_id):
        ep = self.ephemeral_map.get(msg_id)
        if not ep:
            return
        c = ep["canvas_for_image"]
        if not c:
            return
        op = ep["original_photo"]
        if not op:
            return
        c.delete("all")
        c.create_image(0, 0, anchor="nw", image=op)

    def on_search_icon_click(self):
        if self.search_entry.cget("width") == 0:
            self.search_entry.config(width=20)
            self.search_entry.focus_set()
        else:
            self.search_entry.config(width=0)
            self.search_listbox.place_forget()

    def on_search_var_changed(self, *args):
        kw = self.search_var.get().strip()
        if not kw:
            self.search_listbox.place_forget()
            return
        results = []
        for m in self.messages_data:
            if kw.lower() in m["text"].lower():
                st = m["text"]
                if len(st) > 30:
                    st = st[:30] + "..."
                results.append((m["msg_id"], st))
        if not results:
            self.search_listbox.place_forget()
            return
        x = self.search_entry.winfo_rootx()
        y = self.search_entry.winfo_rooty() + self.search_entry.winfo_height()
        self.search_listbox.delete(0, tk.END)
        for (mid, st) in results:
            self.search_listbox.insert(tk.END, f"[{mid}] {st}")
        self.search_listbox.place(x=x, y=y, width=300, height=120)
        self.search_listbox.bind("<<ListboxSelect>>", self.on_search_select)

    def on_search_select(self, event):
        if not self.search_listbox.curselection():
            return
        idx = self.search_listbox.curselection()[0]
        line = self.search_listbox.get(idx)
        try:
            lb = line.index("[")
            rb = line.index("]")
            msg_id_str = line[lb+1:rb]
            msg_id = int(msg_id_str)
        except:
            return
        self.search_listbox.place_forget()
        ep = self.ephemeral_map.get(msg_id)
        if not ep:
            return
        container = ep["container"]
        y = container.winfo_rooty() - self.canvas.winfo_rooty() + self.canvas.canvasy(0)
        self.canvas.yview_moveto(y / self.canvas.bbox("all")[3])

    def toggle_user_list(self, event):
        if self.user_list_frame.winfo_ismapped():
            self.user_list_frame.lower()
        else:
            for widget in self.user_list_frame.winfo_children():
                widget.destroy()
            title = tk.Label(self.user_list_frame, text="可聊天使用者", font=("Arial", 30), bg="#333333", fg="white")
            title.pack(pady=20)
            for user in self.user_list:
                user_label = tk.Label(self.user_list_frame, text=user, font=("Arial", 20), bg="#333333", fg="white")
                user_label.pack(pady=10, fill="x")
                user_label.configure(anchor="center")
            self.user_list_frame.lift()

    def prepare_message(self, text):
        now = datetime.datetime.now()
        date_str = now.strftime("%Y/%m/%d")
        time_str = now.strftime("%H:%M:%S")
        msg_id = len(self.messages_data) + 1
        sender_name = self.profile.get("name", "匿名")
        sender_avatar = self.profile.get("avatar_data", "")
        msg_data = {
            "msg_id": msg_id,
            "text": text,
            "date": date_str,
            "timestamp": time_str,
            "file_path": None,
            "is_image": False,
            "sender_name": sender_name,
            "sender_avatar": sender_avatar
        }
        if self.uploaded_file_id:
            msg_data["file_chunked"] = True
            msg_data["file_id"] = self.uploaded_file_id
        elif self.attached_file_path:
            msg_data["file_path"] = self.attached_file_path
            if self.is_image_file(self.attached_file_path):
                msg_data["is_image"] = True
            try:
                with open(self.attached_file_path, "rb") as f:
                    file_bytes = f.read()
                file_b64 = base64.b64encode(file_bytes).decode("utf-8")
                msg_data["file_data"] = file_b64
                msg_data["file_name"] = os.path.basename(self.attached_file_path)
            except Exception as e:
                print("檔案編碼失敗:", e)
        return json.dumps(msg_data, ensure_ascii=False)

    def send_message(self, text):
        now = datetime.datetime.now()
        date_str = now.strftime("%Y/%m/%d")
        time_str = now.strftime("%H:%M:%S")
        msg_id = len(self.messages_data) + 1
        sender_name = self.profile.get("name", "匿名")
        sender_avatar = self.profile.get("avatar_data", "")
        msg_data = {
            "msg_id": msg_id,
            "text": text,
            "date": date_str,
            "timestamp": time_str,
            "file_path": None,
            "is_image": False,
            "sender_name": sender_name,
            "sender_avatar": sender_avatar
        }
        if self.uploaded_file_id:
            msg_data["file_chunked"] = True
            msg_data["file_id"] = self.uploaded_file_id
        elif self.attached_file_path:
            msg_data["file_path"] = self.attached_file_path
            if self.is_image_file(self.attached_file_path):
                msg_data["is_image"] = True
            try:
                with open(self.attached_file_path, "rb") as f:
                    file_bytes = f.read()
                file_b64 = base64.b64encode(file_bytes).decode("utf-8")
                msg_data["file_data"] = file_b64
                msg_data["file_name"] = os.path.basename(self.attached_file_path)
            except Exception as e:
                print("檔案編碼失敗:", e)
        self.create_message_ui(msg_data)
        self.messages_data.append(msg_data)
        self.entry_var.set("")
        self.preview_label.pack_forget()
        self.preview_label.config(text="", image="")
        self.attached_file_path = None
        self.attached_file_preview = None
        self.uploaded_file_id = None
        self.scroll_to_bottom()
        self.save_data()

    def on_close(self):
        self.save_data()
        if self.socket:
            self.socket.close()
        self.root.destroy()

    def load_data(self):
        self.last_header_info = {}
        if os.path.exists(self.data_path):
            try:
                with open(self.data_path, "r", encoding="utf-8") as f:
                    saved_msgs = json.load(f)
            except Exception as e:
                print("讀取舊紀錄失敗:", e)
                return
            for m in saved_msgs:
                self.create_message_ui(m)
            self.messages_data = saved_msgs
        self.scroll_to_bottom()

    def save_data(self):
        try:
            with open(self.data_path, "w", encoding="utf-8") as f:
                json.dump(self.messages_data, f, ensure_ascii=False, indent=2)
            print("已儲存資料至", self.data_path)
        except Exception as e:
            print("儲存資料失敗:", e)

    def attach_file(self):
        orig_path = filedialog.askopenfilename()
        if not orig_path:
            return
        # 所有檔案（包含影片）皆走附件上傳流程
        filesize = os.path.getsize(orig_path)
        if filesize > CHUNK_THRESHOLD:
            self.cancel_upload = False
            self.uploaded_file_id = os.path.basename(orig_path)
            self.uploading = True
            threading.Thread(target=self.send_file_in_chunks, args=(orig_path,), daemon=True).start()
            messagebox.showinfo("上傳中", "超大檔案正在分塊上傳中，請稍候...")
        else:
            base_name = os.path.basename(orig_path)
            new_path = os.path.join(self.attachments_dir, base_name)
            if not self.copy_file_with_progress(orig_path, new_path):
                return
            self.attached_file_path = new_path
            if self.is_image_file(new_path):
                try:
                    img = Image.open(new_path)
                    img.thumbnail(self.image_thumbnail_size)
                    preview_img = ImageTk.PhotoImage(img)
                    self.attached_file_preview = preview_img
                    self.preview_label.config(image=preview_img, text="")
                except:
                    self.preview_label.config(text=base_name, image="")
            else:
                self.preview_label.config(text=base_name, image="")
            self.preview_label.pack(side=tk.TOP, fill=tk.X)

if __name__ == "__main__":
    root = ThemedTk(theme="equilux")
    app = ChatClientApp(root)
    root.mainloop()
