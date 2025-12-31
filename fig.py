import tkinter as tk
from tkinter import filedialog, messagebox, ttk
import threading
import queue
from PIL import Image, ImageTk
import fitz  # PyMuPDF
import io
import os

# --- 核心修改：强制指向本地模型路径 ---
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
MODEL_DIR = os.path.join(BASE_DIR, "models")
os.environ["U2NET_HOME"] = MODEL_DIR

if not os.path.exists(MODEL_DIR):
    os.makedirs(MODEL_DIR)

from rembg import remove, new_session

class PDFImageEditor:
    def __init__(self, root):
        self.root = root
        self.root.title("PDF 图片编辑器 (多页版)")
        self.root.geometry("1150x850")

        self.check_local_model()

        # 数据存储
        self.pdf_doc = None
        self.current_page_idx = 0  # 当前页码索引
        self.pdf_page_pixmap = None 
        self.original_img = None     
        self.processed_img = None    
        self.tk_overlay_img = None   
        self.img_id = None           
        self.scale_value = 1.0
        self.is_rembg = tk.BooleanVar(value=False)
        self.queue = queue.Queue()
        self.drag_data = {"x": 0, "y": 0}

        self.setup_ui()

    def check_local_model(self):
        actual_model_path = os.path.join(MODEL_DIR, ".u2net", "u2net.onnx")
        simple_path = os.path.join(MODEL_DIR, "u2net.onnx")
        if os.path.exists(simple_path) and not os.path.exists(actual_model_path):
            os.makedirs(os.path.join(MODEL_DIR, ".u2net"), exist_ok=True)
            os.rename(simple_path, actual_model_path)
        
        if not os.path.exists(actual_model_path):
            print(f"[Warning] 模型缺失: {actual_model_path}")

    def setup_ui(self):
        # --- 左侧控制栏 ---
        sidebar = tk.Frame(self.root, width=250, bg="#f0f0f0", padx=10, pady=10)
        sidebar.pack(side=tk.LEFT, fill=tk.Y)

        tk.Label(sidebar, text="操作步骤", font=("Arial", 12, "bold"), bg="#f0f0f0").pack(pady=10)
        tk.Button(sidebar, text="1. 打开 PDF文件", command=self.load_pdf, height=2).pack(fill=tk.X, pady=5)
        
        # --- 翻页控制区 ---
        page_frame = tk.LabelFrame(sidebar, text="页面导航", bg="#f0f0f0", pady=5)
        page_frame.pack(fill=tk.X, pady=10)
        
        self.btn_prev = tk.Button(page_frame, text="上一页", command=self.prev_page, state=tk.DISABLED)
        self.btn_prev.pack(side=tk.LEFT, expand=True)
        
        self.page_label = tk.Label(page_frame, text="0 / 0", bg="#f0f0f0")
        self.page_label.pack(side=tk.LEFT, expand=True)
        
        self.btn_next = tk.Button(page_frame, text="下一页", command=self.next_page, state=tk.DISABLED)
        self.btn_next.pack(side=tk.LEFT, expand=True)

        tk.Button(sidebar, text="2. 上传叠加图片", command=self.load_image, height=2).pack(fill=tk.X, pady=5)
        tk.Checkbutton(sidebar, text="启用 AI 自动抠图", variable=self.is_rembg, command=self.on_rembg_toggle, bg="#f0f0f0").pack(pady=10)

        tk.Label(sidebar, text="图片缩放:", bg="#f0f0f0").pack()
        self.scale_slider = tk.Scale(sidebar, from_=10, to=200, orient=tk.HORIZONTAL, command=self.update_ui_scale, bg="#f0f0f0")
        self.scale_slider.set(100)
        self.scale_slider.pack(fill=tk.X, pady=5)

        tk.Button(sidebar, text="3. 保存导出 PDF", command=self.save_pdf, bg="#4CAF50", fg="white", font=('Arial', 10, 'bold'), height=2).pack(fill=tk.X, side=tk.BOTTOM, pady=20)

        # --- 右侧预览区 ---
        self.preview_frame = tk.Frame(self.root, bg="gray")
        self.preview_frame.pack(side=tk.RIGHT, expand=True, fill=tk.BOTH)

        self.canvas = tk.Canvas(self.preview_frame, bg="gray", cursor="hand2")
        self.canvas.pack(side=tk.LEFT, expand=True, fill=tk.BOTH)

        self.canvas.tag_bind("overlay", "<ButtonPress-1>", self.on_drag_start)
        self.canvas.tag_bind("overlay", "<B1-Motion>", self.on_drag_motion)

    # --- 页面切换逻辑 ---

    def load_pdf(self):
        path = filedialog.askopenfilename(filetypes=[("PDF Files", "*.pdf")])
        if not path: return
        
        self.pdf_doc = fitz.open(path)
        self.current_page_idx = 0
        self.update_page_view()
        self.update_nav_buttons()

    def update_page_view(self):
        """更新当前显示的 PDF 页面"""
        if not self.pdf_doc: return
        
        # 获取当前页并转为图片
        page = self.pdf_doc[self.current_page_idx]
        pix = page.get_pixmap(matrix=fitz.Matrix(1.2, 1.2)) # 1.2倍缩放提高清晰度
        self.pdf_page_pixmap = Image.open(io.BytesIO(pix.tobytes("ppm")))
        
        self.render_canvas()
        self.page_label.config(text=f"{self.current_page_idx + 1} / {len(self.pdf_doc)}")

    def next_page(self):
        if self.pdf_doc and self.current_page_idx < len(self.pdf_doc) - 1:
            self.current_page_idx += 1
            self.update_page_view()
            self.update_nav_buttons()

    def prev_page(self):
        if self.pdf_doc and self.current_page_idx > 0:
            self.current_page_idx -= 1
            self.update_page_view()
            self.update_nav_buttons()

    def update_nav_buttons(self):
        """根据当前页码状态启用/禁用按钮"""
        if not self.pdf_doc: return
        total = len(self.pdf_doc)
        self.btn_prev.config(state=tk.NORMAL if self.current_page_idx > 0 else tk.DISABLED)
        self.btn_next.config(state=tk.NORMAL if self.current_page_idx < total - 1 else tk.DISABLED)

    def render_canvas(self):
        """渲染画布背景，注意不删除已有的叠加图片"""
        if self.pdf_page_pixmap:
            self.tk_pdf_img = ImageTk.PhotoImage(self.pdf_page_pixmap)
            # 这里的逻辑是：先清理旧的背景图，再重绘，最后把叠加图层放到最上面
            self.canvas.delete("pdf_bg") 
            self.canvas.config(scrollregion=(0, 0, self.pdf_page_pixmap.width, self.pdf_page_pixmap.height))
            self.canvas.create_image(0, 0, image=self.tk_pdf_img, anchor=tk.NW, tags="pdf_bg")
            self.canvas.tag_lower("pdf_bg") # 确保背景在底层

    # --- 抠图与缩放逻辑 (保持并优化) ---

    def on_rembg_toggle(self):
        if self.original_img:
            self.process_image_threaded()

    def process_image_threaded(self):
        if self.original_img is None: return
        if not self.is_rembg.get():
            self.processed_img = self.original_img
            self.update_ui_scale()
            return

        self.loading_win = tk.Toplevel(self.root)
        self.loading_win.title("AI 处理中")
        self.loading_win.geometry("300x120")
        self.loading_win.transient(self.root)
        self.loading_win.grab_set()
        tk.Label(self.loading_win, text="正在调用本地模型进行抠图...", pady=10).pack()
        prog = ttk.Progressbar(self.loading_win, mode='indeterminate')
        prog.pack(fill=tk.X, padx=20)
        prog.start(10)

        thread = threading.Thread(target=self.bg_removal_worker, args=(self.original_img,))
        thread.daemon = True
        thread.start()
        self.root.after(100, self.check_queue)

    def bg_removal_worker(self, img):
        try:
            session = new_session("u2net") 
            result = remove(img, session=session)
            self.queue.put(("SUCCESS", result))
        except Exception as e:
            self.queue.put(("ERROR", str(e)))

    def check_queue(self):
        try:
            status, data = self.queue.get_nowait()
            self.loading_win.destroy()
            if status == "SUCCESS":
                self.processed_img = data
                self.update_ui_scale()
            else:
                messagebox.showerror("错误", f"AI 处理失败: {data}")
        except queue.Empty:
            self.root.after(100, self.check_queue)

    def update_ui_scale(self, *args):
        if self.processed_img is None: return
        self.scale_value = self.scale_slider.get() / 100.0
        w, h = self.processed_img.size
        new_size = (int(w * self.scale_value), int(h * self.scale_value))
        resized_img = self.processed_img.resize(new_size, Image.Resampling.LANCZOS)
        self.tk_overlay_img = ImageTk.PhotoImage(resized_img)
        
        if self.img_id:
            # 更新已存在的图片
            self.canvas.itemconfig(self.img_id, image=self.tk_overlay_img)
        else:
            # 第一次创建
            self.img_id = self.canvas.create_image(50, 50, image=self.tk_overlay_img, anchor=tk.NW, tags="overlay")

    def load_image(self):
        path = filedialog.askopenfilename(filetypes=[("Image Files", "*.png *.jpg *.jpeg")])
        if not path: return
        self.original_img = Image.open(path)
        self.process_image_threaded()

    # --- 拖拽与保存逻辑 ---

    def on_drag_start(self, event):
        self.drag_data["x"] = event.x
        self.drag_data["y"] = event.y

    def on_drag_motion(self, event):
        dx = event.x - self.drag_data["x"]
        dy = event.y - self.drag_data["y"]
        self.canvas.move("overlay", dx, dy)
        self.drag_data["x"] = event.x
        self.drag_data["y"] = event.y

    def save_pdf(self):
        if not self.pdf_doc or not self.img_id:
            messagebox.showwarning("提示", "请先加载 PDF 和图片")
            return
        
        save_path = filedialog.asksaveasfilename(defaultextension=".pdf", filetypes=[("PDF Files", "*.pdf")])
        if not save_path: return
        
        # 获取图片在画布上的坐标
        coords = self.canvas.coords(self.img_id)
        
        # 计算 PDF 实际尺寸与预览图的比例 (预览图可能有缩放)
        current_page = self.pdf_doc[self.current_page_idx]
        ratio = current_page.rect.width / self.pdf_page_pixmap.width
        
        # 转换图片为字节流
        img_byte_arr = io.BytesIO()
        self.processed_img.save(img_byte_arr, format='PNG')
        
        # 计算插入到 PDF 的实际位置和大小
        final_w = (self.processed_img.width * self.scale_value) * ratio
        final_h = (self.processed_img.height * self.scale_value) * ratio
        rect = fitz.Rect(coords[0]*ratio, coords[1]*ratio, coords[0]*ratio + final_w, coords[1]*ratio + final_h)
        
        # 插入到“当前页”
        current_page.insert_image(rect, stream=img_byte_arr.getvalue())
        
        self.pdf_doc.save(save_path)
        messagebox.showinfo("成功", f"保存成功！已导出到当前页 ({self.current_page_idx + 1})")

if __name__ == "__main__":
    root = tk.Tk()
    app = PDFImageEditor(root)
    root.mainloop()