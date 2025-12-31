import tkinter as tk
from tkinter import filedialog, messagebox, scrolledtext, ttk, colorchooser, simpledialog
from PIL import Image, ImageTk
import fitz  # PyMuPDF
import os
import random
import json
import math

class PDFHandwriterApp:
    def __init__(self, root):
        self.root = root
        self.root.title("PDF 手写模拟器")
        self.root.geometry("1400x950")
        
        self.base_path = os.path.dirname(__file__)
        self.ttf_dir = os.path.join(self.base_path, "TTF")
        self.set_dir = os.path.join(self.base_path, "SET")
        
        for folder in [self.ttf_dir, self.set_dir]:
            if not os.path.exists(folder): os.makedirs(folder)

        self.pdf_path = None
        self.doc = None
        self.history = []  
        self.max_history = 10
        self.is_preview_mode = False
        self.pre_edit_doc_bytes = None
        self.current_page_num = 0
        self.zoom = 1.5
        self.rect_id = None
        self.start_x = self.start_y = 0
        self.end_x = self.end_y = 0

        self.params = {
            'zh': self.init_param_vars(default_font_size=22),
            'en': self.init_param_vars(default_font_size=18)
        }
        # 默认颜色修改为纯黑色 (0, 0, 0)
        self.zh_color = (0, 0, 0)
        self.en_color = (0, 0, 0)

        self.font_dict = {}
        self.scan_fonts()
        self.setup_ui()
        self.refresh_template_list()

    def init_param_vars(self, default_font_size):
        vars = {
            'font_name': tk.StringVar(),
            'font_size': tk.IntVar(value=default_font_size),
            'char_spacing': tk.DoubleVar(value=0.0),
            'line_spacing': tk.DoubleVar(value=1.2),
            # 字符内扰动
            'jitter_pos': tk.DoubleVar(value=0.5),
            'jitter_size': tk.DoubleVar(value=0.5),
            'jitter_rot': tk.DoubleVar(value=1.5),
            # --- 每一行的随机扰动参数 ---
            'line_jitter_x': tk.DoubleVar(value=10.0), 
            'line_jitter_y': tk.DoubleVar(value=2.0),  
            'line_tilt': tk.DoubleVar(value=2.0)       
        }
        for v in vars.values():
            if isinstance(v, (tk.IntVar, tk.DoubleVar, tk.StringVar)):
                v.trace_add("write", self.auto_refresh_preview)
        return vars

    def is_chinese(self, char):
        if '\u4e00' <= char <= '\u9fff': return True
        if char in "。，、？！：；“”‘’（）《》【】": return True
        return False

    def scan_fonts(self):
        files = [f for f in os.listdir(self.ttf_dir) if f.lower().endswith('.ttf')]
        for f in files:
            name = os.path.splitext(f)[0]
            self.font_dict[name] = os.path.join(self.ttf_dir, f)
        if not self.font_dict: self.font_dict["(无字体)"] = "simkai.ttf"

    def setup_ui(self):
        top_frame = tk.Frame(self.root, bg="#2c3e50", pady=5)
        top_frame.pack(side=tk.TOP, fill=tk.X)
        tk.Button(top_frame, text="打开 PDF", command=self.load_pdf).pack(side=tk.LEFT, padx=10)
        tk.Button(top_frame, text="保存 PDF", command=self.save_pdf).pack(side=tk.LEFT, padx=5)
        
        page_ctrl_frame = tk.Frame(top_frame, bg="#2c3e50")
        page_ctrl_frame.pack(side=tk.LEFT, expand=True)
        tk.Button(page_ctrl_frame, text="< 上一页", command=self.prev_page).pack(side=tk.LEFT, padx=5)
        self.page_label = tk.Label(page_ctrl_frame, text="页码: 0 / 0", bg="#2c3e50", fg="white", width=15)
        self.page_label.pack(side=tk.LEFT, padx=10)
        tk.Button(page_ctrl_frame, text="下一页 >", command=self.next_page).pack(side=tk.LEFT, padx=5)

        main_frame = tk.Frame(self.root)
        main_frame.pack(fill=tk.BOTH, expand=True)

        ctrl_panel = tk.Frame(main_frame, width=320)
        ctrl_panel.pack(side=tk.LEFT, fill=tk.Y)
        ctrl_panel.pack_propagate(False)

        tpl_frame = tk.LabelFrame(ctrl_panel, text="模版配置", pady=5, padx=5)
        tpl_frame.pack(fill=tk.X, pady=5)
        self.tpl_combo = ttk.Combobox(tpl_frame, state="readonly")
        self.tpl_combo.pack(fill=tk.X, pady=2)
        self.tpl_combo.bind("<<ComboboxSelected>>", self.apply_template)
        tk.Button(tpl_frame, text="保存当前配置", command=self.save_current_config, bg="#34495e", fg="white").pack(fill=tk.X)

        self.notebook = ttk.Notebook(ctrl_panel)
        self.notebook.pack(fill=tk.BOTH, expand=True, padx=5)

        self.zh_tab = tk.Frame(self.notebook)
        self.en_tab = tk.Frame(self.notebook)
        self.notebook.add(self.zh_tab, text=" 中文设置 ")
        self.notebook.add(self.en_tab, text=" 英文/数字 ")

        self.build_param_tab(self.zh_tab, 'zh')
        self.build_param_tab(self.en_tab, 'en')

        right_frame = tk.LabelFrame(main_frame, text="文字内容", padx=10, pady=10, width=350)
        right_frame.pack(side=tk.RIGHT, fill=tk.Y)
        right_frame.pack_propagate(False)

        self.text_editor = scrolledtext.ScrolledText(right_frame, wrap=tk.WORD, font=("微软雅黑", 11))
        self.text_editor.pack(fill=tk.BOTH, expand=True)
        self.text_editor.bind("<KeyRelease>", self.auto_refresh_preview)
        
        self.btn_main = tk.Button(right_frame, text="开启实时预览", command=self.toggle_preview_mode, 
                  bg="#3498db", fg="white", font=("微软雅黑", 12, "bold"), height=2)
        self.btn_main.pack(fill=tk.X, pady=(10, 5))
        
        act_f = tk.Frame(right_frame)
        act_f.pack(fill=tk.X)
        tk.Button(act_f, text="撤销", command=self.undo_action, bg="#e67e22", fg="white").pack(side=tk.LEFT, expand=True, fill=tk.X)
        tk.Button(act_f, text="擦除", command=self.erase_selection, bg="#c0392b", fg="white").pack(side=tk.LEFT, expand=True, fill=tk.X)

        self.canvas = tk.Canvas(main_frame, bg="#bdc3c7", cursor="cross")
        self.canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        self.canvas.bind("<ButtonPress-1>", self.on_button_press)
        self.canvas.bind("<B1-Motion>", self.on_move_press)
        self.canvas.bind("<ButtonRelease-1>", self.auto_refresh_preview)

    def build_param_tab(self, parent, lang_key):
        p = self.params[lang_key]
        container = tk.Frame(parent)
        container.pack(fill=tk.BOTH, expand=True, padx=5)
        
        tk.Label(container, text="选择字体:").pack(anchor=tk.W, pady=(5,0))
        cb = ttk.Combobox(container, textvariable=p['font_name'], values=list(self.font_dict.keys()), state="readonly")
        cb.pack(fill=tk.X, pady=2)
        if self.font_dict: cb.current(0)

        tk.Button(container, text="选择颜色", command=lambda: self.choose_color(lang_key)).pack(fill=tk.X, pady=5)
        # 初始化显示颜色预览
        color_hex = '#%02x%02x%02x' % tuple(int(c*255) for c in (self.zh_color if lang_key=='zh' else self.en_color))
        p['color_btn'] = tk.Label(container, text="颜色预览", bg=color_hex, fg="white")
        p['color_btn'].pack(fill=tk.X)

        self.create_scale(container, "字体大小", p['font_size'], 5, 80)
        self.create_scale(container, "基本行距", p['line_spacing'], 0.5, 4.0, 0.1)
        self.create_scale(container, "基本字距", p['char_spacing'], -10, 20, 0.5)
        
        ttk.Separator(container, orient='horizontal').pack(fill='x', pady=10)
        tk.Label(container, text="[ PDF 每一行的随机量 ]", fg="#e67e22", font=("", 9, "bold")).pack()
        self.create_scale(container, "行左右平移量", p['line_jitter_x'], 0, 100, 1)
        self.create_scale(container, "行上下平移量", p['line_jitter_y'], 0, 20, 0.5)
        self.create_scale(container, "行整行倾斜量", p['line_tilt'], 0, 10, 0.1)

        ttk.Separator(container, orient='horizontal').pack(fill='x', pady=10)
        tk.Label(container, text="[ 每一个字的随机量 ]", fg="#27ae60", font=("", 9, "bold")).pack()
        self.create_scale(container, "字位置抖动", p['jitter_pos'], 0, 5, 0.1)
        self.create_scale(container, "字大小抖动", p['jitter_size'], 0, 5, 0.1)
        self.create_scale(container, "字旋转抖动", p['jitter_rot'], 0, 20, 0.1)

    def create_scale(self, parent, label, var, f, t, res=1):
        tk.Label(parent, text=f"{label}:").pack(anchor=tk.W)
        tk.Scale(parent, from_=f, to=t, resolution=res, orient=tk.HORIZONTAL, variable=var).pack(fill=tk.X)

    def generate_handwriting_logic(self, is_preview=False):
        text = self.text_editor.get("1.0", tk.END).strip("\n")
        if not text or not self.rect_id: return

        page = self.doc[self.current_page_num]
        x1, y1 = min(self.start_x, self.end_x)/self.zoom, min(self.start_y, self.end_y)/self.zoom
        x2, y2 = max(self.start_x, self.end_x)/self.zoom, max(self.start_y, self.end_y)/self.zoom
        
        active_lang = 'zh' if self.notebook.index("current") == 0 else 'en'
        curr_y = y1 + self.params[active_lang]['font_size'].get()
        lines = text.split('\n')

        if is_preview: random.seed(42) 
        else: random.seed()

        for line in lines:
            if not line.strip():
                curr_y += self.params[active_lang]['font_size'].get() * self.params[active_lang]['line_spacing'].get()
                continue

            p_line = self.params[active_lang]
            line_dx = random.uniform(-p_line['line_jitter_x'].get(), p_line['line_jitter_x'].get())
            line_dy = random.uniform(-p_line['line_jitter_y'].get(), p_line['line_jitter_y'].get())
            line_angle_deg = random.uniform(-p_line['line_tilt'].get(), p_line['line_tilt'].get())
            line_angle_rad = math.radians(line_angle_deg)

            line_start_x = x1 + line_dx
            line_base_y = curr_y + line_dy
            curr_x = line_start_x
            max_row_height = 0 

            for char in line:
                lang = 'zh' if self.is_chinese(char) else 'en'
                p = self.params[lang]
                
                f_size = p['font_size'].get()
                f_path = self.font_dict.get(p['font_name'].get())
                c_space = p['char_spacing'].get()
                char_line_height = f_size * p['line_spacing'].get()
                max_row_height = max(max_row_height, char_line_height)

                if char == ' ': 
                    curr_x += f_size * 0.4
                    continue

                if curr_x + f_size > x2:
                    curr_x = line_start_x
                    line_base_y += max_row_height
                
                if line_base_y > y2 + 10: break

                char_jitter_x = random.uniform(-p['jitter_pos'].get(), p['jitter_pos'].get())
                char_jitter_y = random.uniform(-p['jitter_pos'].get(), p['jitter_pos'].get())
                char_jitter_rot = random.uniform(-p['jitter_rot'].get(), p['jitter_rot'].get())
                char_jitter_fs = f_size + random.uniform(-p['jitter_size'].get(), p['jitter_size'].get())

                tilt_y_offset = (curr_x - line_start_x) * math.tan(line_angle_rad)

                # --- 重点：此处已移除随机颜色扰动，直接使用 base_rgb ---
                final_color = self.zh_color if lang == 'zh' else self.en_color

                try:
                    final_y = line_base_y + tilt_y_offset + char_jitter_y
                    final_x = curr_x + char_jitter_x
                    point = fitz.Point(final_x, final_y)
                    total_rotation = line_angle_deg + char_jitter_rot
                    
                    page.insert_text(point, char, 
                                     fontsize=char_jitter_fs, 
                                     fontname=f"f_{lang}",
                                     fontfile=f_path, 
                                     color=final_color, 
                                     morph=(point, fitz.Matrix(total_rotation)))
                except Exception as e:
                    print(f"Render Error: {e}")
                
                curr_x += f_size + c_space
            
            curr_y += max_row_height if max_row_height > 0 else p_line['font_size'].get() * 1.5
            if curr_y > y2 + 20: break

    def toggle_preview_mode(self):
        if not self.doc or not self.rect_id:
            messagebox.showwarning("提示", "请先在PDF上框选区域")
            return
        if not self.is_preview_mode:
            self.is_preview_mode = True
            self.pre_edit_doc_bytes = self.doc.write()
            self.btn_main.config(text="确认应用笔迹", bg="#27ae60")
            self.auto_refresh_preview()
        else:
            self.is_preview_mode = False
            self.save_to_history(self.pre_edit_doc_bytes)
            self.btn_main.config(text="开启实时预览", bg="#3498db")
            messagebox.showinfo("成功", "已保存")

    def auto_refresh_preview(self, *args):
        if not self.is_preview_mode or not self.doc: return
        try:
            self.doc.close()
            self.doc = fitz.open("pdf", self.pre_edit_doc_bytes)
            self.generate_handwriting_logic(is_preview=True)
            self.render_page(preserve_rect=True)
        except: pass

    def choose_color(self, lang_key):
        color_code = colorchooser.askcolor(title="颜色选择")
        if color_code[1]:
            rgb = (color_code[0][0]/255, color_code[0][1]/255, color_code[0][2]/255)
            if lang_key == 'zh': self.zh_color = rgb
            else: self.en_color = rgb
            self.params[lang_key]['color_btn'].config(bg=color_code[1])
            self.auto_refresh_preview()

    def save_current_config(self):
        name = simpledialog.askstring("配置", "模版名称:")
        if not name: return
        data = {
            'zh': {k: (v.get() if not isinstance(v, tk.Label) else "") for k, v in self.params['zh'].items()},
            'en': {k: (v.get() if not isinstance(v, tk.Label) else "") for k, v in self.params['en'].items()},
            'zh_color': self.zh_color, 'en_color': self.en_color
        }
        with open(os.path.join(self.set_dir, f"{name}.json"), 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=4, ensure_ascii=False)
        self.refresh_template_list()

    def apply_template(self, event=None):
        path = os.path.join(self.set_dir, f"{self.tpl_combo.get()}.json")
        if not os.path.exists(path): return
        with open(path, 'r', encoding='utf-8') as f:
            d = json.load(f)
        for lang in ['zh', 'en']:
            for k, v in d[lang].items():
                if k in self.params[lang] and isinstance(self.params[lang][k], (tk.Variable)):
                    self.params[lang][k].set(v)
        self.zh_color, self.en_color = tuple(d.get('zh_color', [0,0,0])), tuple(d.get('en_color', [0,0,0]))
        self.params['zh']['color_btn'].config(bg='#%02x%02x%02x' % tuple(int(c*255) for c in self.zh_color))
        self.params['en']['color_btn'].config(bg='#%02x%02x%02x' % tuple(int(c*255) for c in self.en_color))
        self.auto_refresh_preview()

    def load_pdf(self):
        path = filedialog.askopenfilename(filetypes=[("PDF", "*.pdf")])
        if path:
            self.doc = fitz.open(path)
            self.current_page_num = 0
            self.render_page()

    def render_page(self, preserve_rect=False):
        if not self.doc: return
        page = self.doc[self.current_page_num]
        self.page_label.config(text=f"页码: {self.current_page_num + 1} / {self.doc.page_count}")
        pix = page.get_pixmap(matrix=fitz.Matrix(self.zoom, self.zoom))
        img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
        self.tk_img = ImageTk.PhotoImage(img)
        coords = self.canvas.coords(self.rect_id) if self.rect_id else None
        self.canvas.delete("all")
        self.canvas.create_image(0, 0, anchor=tk.NW, image=self.tk_img)
        if preserve_rect and coords:
            self.rect_id = self.canvas.create_rectangle(*coords, outline='red', width=2)
        else: self.rect_id = None

    def save_to_history(self, doc_bytes):
        self.history.append(doc_bytes)
        if len(self.history) > self.max_history: self.history.pop(0)

    def undo_action(self):
        if not self.history: return
        self.doc.close()
        self.doc = fitz.open("pdf", self.history.pop())
        self.render_page()

    def erase_selection(self):
        if not self.doc or not self.rect_id: return
        self.save_to_history(self.doc.write())
        page = self.doc[self.current_page_num]
        rect = fitz.Rect(min(self.start_x, self.end_x)/self.zoom, min(self.start_y, self.end_y)/self.zoom,
                         max(self.start_x, self.end_x)/self.zoom, max(self.start_y, self.end_y)/self.zoom)
        page.add_redact_annot(rect, fill=(1, 1, 1))
        page.apply_redactions()
        self.render_page()

    def prev_page(self):
        if self.doc and self.current_page_num > 0:
            self.current_page_num -= 1; self.render_page()

    def next_page(self):
        if self.doc and self.current_page_num < self.doc.page_count - 1:
            self.current_page_num += 1; self.render_page()

    def on_button_press(self, event):
        self.start_x, self.start_y = self.canvas.canvasx(event.x), self.canvas.canvasy(event.y)
        if self.rect_id: self.canvas.delete(self.rect_id)
        self.rect_id = self.canvas.create_rectangle(self.start_x, self.start_y, self.start_x, self.start_y, outline='red', width=2)

    def on_move_press(self, event):
        self.end_x, self.end_y = self.canvas.canvasx(event.x), self.canvas.canvasy(event.y)
        self.canvas.coords(self.rect_id, self.start_x, self.start_y, self.end_x, self.end_y)

    def refresh_template_list(self):
        names = [os.path.splitext(f)[0] for f in os.listdir(self.set_dir) if f.endswith('.json')]
        self.tpl_combo['values'] = names
        self.tpl_combo.set("配置模版" if names else "暂无模版")

    def save_pdf(self):
        if not self.doc: return
        path = filedialog.asksaveasfilename(defaultextension=".pdf")
        if path: self.doc.save(path); messagebox.showinfo("成功", "保存成功")

if __name__ == "__main__":
    root = tk.Tk()
    app = PDFHandwriterApp(root)
    root.mainloop()