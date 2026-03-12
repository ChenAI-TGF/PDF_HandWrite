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
        self.poly_id = None  # 多边形ID
        self.control_points = []  # 控制点ID列表
        self.dragging_point = -1  # 正在拖拽的控制点索引
        self.start_x = self.start_y = 0
        self.end_x = self.end_y = 0
        self.quad_points = []  # 四边形顶点坐标 [x1,y1, x2,y2, x3,y3, x4,y4]

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
            'vertical_jitter': tk.DoubleVar(value=2.0),  # 垂直浮动
            'color_variation': tk.DoubleVar(value=0.1),  # 颜色变化
            # --- 每一行的随机扰动参数 ---
            'line_jitter_x': tk.DoubleVar(value=10.0), 
            'line_jitter_y': tk.DoubleVar(value=2.0),  
            'line_tilt': tk.DoubleVar(value=2.0),
            # --- 纸张印痕效果参数 ---
            'indent_enabled': tk.BooleanVar(value=False),      # 启用/禁用
            'indent_strength': tk.DoubleVar(value=0.3),        # 印痕强度 0-1
            'indent_offset_x': tk.DoubleVar(value=0.3),        # X方向偏移 -1到1
            'indent_offset_y': tk.DoubleVar(value=0.3),        # Y方向偏移 -1到1
            'indent_opacity': tk.DoubleVar(value=0.4),         # 不透明度 0-1
            'indent_color_mode': tk.StringVar(value='auto')    # 颜色模式: auto/gray/custom     
        }
        for v in vars.values():
            if isinstance(v, (tk.IntVar, tk.DoubleVar, tk.StringVar)):
                v.trace_add("write", self.auto_refresh_preview)
        return vars

    def calculate_indent_color(self, base_color, params):
        """计算印痕颜色"""
        mode = params['indent_color_mode'].get()
        strength = params['indent_strength'].get()
        
        if mode == 'gray':
            # 灰色印痕：根据强度调整灰度
            gray_value = 0.7 + 0.3 * strength  # 0.7-1.0范围
            return (gray_value, gray_value, gray_value)
        elif mode == 'custom':
            # 自定义颜色（暂不支持，返回灰色）
            gray_value = 0.7 + 0.3 * strength
            return (gray_value, gray_value, gray_value)
        else:  # auto模式
            # 基于主颜色变浅
            r = min(1.0, base_color[0] + 0.3 * strength)
            g = min(1.0, base_color[1] + 0.3 * strength)
            b = min(1.0, base_color[2] + 0.3 * strength)
            return (r, g, b)

    def is_chinese(self, char):
        if '\u4e00' <= char <= '\u9fff': return True
        if char in "。，、？！：；“”‘’（）《》【】": return True
        return False

    def scan_fonts(self):
        files = [f for f in os.listdir(self.ttf_dir) if f.lower().endswith('.ttf')]
        for f in files:
            name = os.path.splitext(f)[0]
            self.font_dict[name] = os.path.join(self.ttf_dir, f)
        if not self.font_dict: 
            self.font_dict["(默认字体)"] = "simkai.ttf"
            print("提示：TTF 文件夹为空，使用默认字体")
            print("请下载手写字体放入 TTF 文件夹，详见 FONT_RECOMMENDATIONS.md")

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
        
        # 添加适应窗口按钮
        tk.Button(top_frame, text="适应窗口", command=self.fit_to_window, bg="#9b59b6", fg="white").pack(side=tk.LEFT, padx=10)

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
        self.canvas.bind("<ButtonRelease-1>", self.on_button_release)

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
        self.create_scale(container, "垂直浮动", p['vertical_jitter'], 0, 10, 0.5)
        self.create_scale(container, "颜色深浅变化", p['color_variation'], 0, 0.5, 0.05)

        ttk.Separator(container, orient='horizontal').pack(fill='x', pady=10)
        tk.Label(container, text="[ 纸张印痕效果 ]", fg="#8e44ad", font=("", 9, "bold")).pack()

        # 启用复选框
        tk.Checkbutton(container, text="启用纸张印痕", variable=p['indent_enabled']).pack(anchor=tk.W, pady=5)

        # 印痕参数滑块
        self.create_scale(container, "印痕强度", p['indent_strength'], 0, 1, 0.05)
        self.create_scale(container, "X方向偏移", p['indent_offset_x'], -1, 1, 0.1)
        self.create_scale(container, "Y方向偏移", p['indent_offset_y'], -1, 1, 0.1)
        self.create_scale(container, "不透明度", p['indent_opacity'], 0, 1, 0.05)

        # 颜色模式选择
        tk.Label(container, text="印痕颜色模式:").pack(anchor=tk.W, pady=(5,0))
        color_combo = ttk.Combobox(container, textvariable=p['indent_color_mode'], 
                                  values=['auto', 'gray', 'custom'], state="readonly")
        color_combo.pack(fill=tk.X, pady=2)
        color_combo.current(0)

    def create_scale(self, parent, label, var, f, t, res=1):
        tk.Label(parent, text=f"{label}:").pack(anchor=tk.W)
        tk.Scale(parent, from_=f, to=t, resolution=res, orient=tk.HORIZONTAL, variable=var).pack(fill=tk.X)

    def map_point_to_quad(self, x, y, x1, y1, x2, y2):
        """将矩形内的点(x,y)映射到四边形内"""
        if x2 == x1 or y2 == y1:
            return x, y
            
        # 归一化坐标
        u = (x - x1) / (x2 - x1)
        v = (y - y1) / (y2 - y1)
        
        # 四边形顶点
        qp = self.quad_points
        A = (qp[0]/self.zoom, qp[1]/self.zoom)  # 左上
        B = (qp[2]/self.zoom, qp[3]/self.zoom)  # 右上
        C = (qp[4]/self.zoom, qp[5]/self.zoom)  # 右下
        D = (qp[6]/self.zoom, qp[7]/self.zoom)  # 左下
        
        # 双线性插值
        mapped_x = (1-u)*(1-v)*A[0] + u*(1-v)*B[0] + u*v*C[0] + (1-u)*v*D[0]
        mapped_y = (1-u)*(1-v)*A[1] + u*(1-v)*B[1] + u*v*C[1] + (1-u)*v*D[1]
        
        return mapped_x, mapped_y

    def generate_handwriting_logic(self, is_preview=False):
        text = self.text_editor.get("1.0", tk.END).strip("\n")
        if not text or not self.poly_id or len(self.quad_points) < 8: return
        if not self.doc: return

        page = self.doc[self.current_page_num]
        
        # 使用四边形的最小包围矩形作为文字布局区域
        qp = self.quad_points
        x1 = min(qp[0], qp[2], qp[4], qp[6]) / self.zoom
        y1 = min(qp[1], qp[3], qp[5], qp[7]) / self.zoom
        x2 = max(qp[0], qp[2], qp[4], qp[6]) / self.zoom
        y2 = max(qp[1], qp[3], qp[5], qp[7]) / self.zoom
        
        active_lang = 'zh' if self.notebook.index("current") == 0 else 'en'
        curr_y = y1 + self.params[active_lang]['font_size'].get()
        lines = text.split('\n')

        if is_preview: random.seed(42) 
        else: random.seed()

        paragraph_tilt_rad = 0  # 记录当前段落的倾斜角度
        for line in lines:
            if not line.strip():
                curr_y += self.params[active_lang]['font_size'].get() * self.params[active_lang]['line_spacing'].get() * 2.0
                continue

            p_line = self.params[active_lang]
            line_dx = random.uniform(-p_line['line_jitter_x'].get(), p_line['line_jitter_x'].get())
            line_dy = random.uniform(-p_line['line_jitter_y'].get(), p_line['line_jitter_y'].get())
            line_angle_deg = random.uniform(-p_line['line_tilt'].get(), p_line['line_tilt'].get())
            line_angle_rad = math.radians(line_angle_deg)
            paragraph_tilt_rad = line_angle_rad  # 保存当前段落的倾斜角度

            line_start_x = x1 + line_dx
            line_base_y = curr_y + line_dy
            curr_x = line_start_x
            max_row_height = 0 
            line_char_count = 0

            for char in line:
                lang = 'zh' if self.is_chinese(char) else 'en'
                p = self.params[lang]
                
                f_size = p['font_size'].get()
                f_path = self.font_dict.get(p['font_name'].get())
                c_space = p['char_spacing'].get()
                char_line_height = f_size * p['line_spacing'].get()

                if char == ' ': 
                    curr_x += f_size * 0.4
                    continue

                # 检测换行：如果字符超出边界且不是行首字符
                if curr_x + f_size > x2 and line_char_count > 0:
                    curr_x = line_start_x
                    # 行间距 = 上一行高度 * 1.5 + 倾斜角度额外边距（基于区域宽度）
                    # 估计上一行的宽度作为倾斜补偿基础
                    estimated_line_width = min(x2 - line_start_x, 100)  # 限制最大估计宽度
                    extra_tilt_margin = abs(line_angle_rad) * estimated_line_width * 0.8 if max_row_height > 0 else 0
                    line_base_y += max_row_height * 1.5 + extra_tilt_margin
                    max_row_height = 0  # 重置为新行重新计算
                    line_char_count = 0
                
                # 更新当前行最大高度（换行后重新计算）
                max_row_height = max(max_row_height, char_line_height)
                
                if line_base_y > y2 + 10: break

                char_jitter_x = random.uniform(-p['jitter_pos'].get(), p['jitter_pos'].get())
                char_jitter_y = random.uniform(-p['jitter_pos'].get(), p['jitter_pos'].get())
                # 垂直浮动
                vertical_jitter = random.uniform(-p['vertical_jitter'].get(), p['vertical_jitter'].get())
                char_jitter_rot = random.uniform(-p['jitter_rot'].get(), p['jitter_rot'].get())
                char_jitter_fs = f_size + random.uniform(-p['jitter_size'].get(), p['jitter_size'].get())

                tilt_y_offset = (curr_x - line_start_x) * math.tan(line_angle_rad)

                # 基础颜色
                base_color = self.zh_color if lang == 'zh' else self.en_color
                # 颜色变化
                color_var = p['color_variation'].get()
                if color_var > 0:
                    r = max(0, min(1, base_color[0] + random.uniform(-color_var, color_var)))
                    g = max(0, min(1, base_color[1] + random.uniform(-color_var, color_var)))
                    b = max(0, min(1, base_color[2] + random.uniform(-color_var, color_var)))
                    final_color = (r, g, b)
                else:
                    final_color = base_color

                try:
                    final_y = line_base_y + tilt_y_offset + char_jitter_y + vertical_jitter
                    final_x = curr_x + char_jitter_x
                    # 将点映射到四边形内
                    mapped_x, mapped_y = self.map_point_to_quad(final_x, final_y, x1, y1, x2, y2)
                    point = fitz.Point(mapped_x, mapped_y)
                    total_rotation = line_angle_deg + char_jitter_rot
                    
                    # 纸张印痕效果
                    if p['indent_enabled'].get():
                        # 计算偏移量（基于字体大小的比例）
                        offset_x = p['indent_offset_x'].get() * char_jitter_fs * 0.2
                        offset_y = p['indent_offset_y'].get() * char_jitter_fs * 0.2
                        indent_point = fitz.Point(mapped_x + offset_x, mapped_y + offset_y)
                        
                        # 计算印痕颜色
                        indent_color = self.calculate_indent_color(base_color, p)
                        opacity = p['indent_opacity'].get()
                        # 混合印痕颜色与白色（模拟不透明度）
                        indent_color = (
                            indent_color[0] * opacity + (1 - opacity),
                            indent_color[1] * opacity + (1 - opacity),
                            indent_color[2] * opacity + (1 - opacity)
                        )
                        
                        # 绘制印痕层
                        page.insert_text(indent_point, char,
                                         fontsize=char_jitter_fs,
                                         fontname=f"f_{lang}",
                                         fontfile=f_path,
                                         color=indent_color,
                                         morph=(indent_point, fitz.Matrix(total_rotation)))
                    
                    # 绘制主文本层
                    page.insert_text(point, char, 
                                     fontsize=char_jitter_fs, 
                                     fontname=f"f_{lang}",
                                     fontfile=f_path, 
                                     color=final_color, 
                                     morph=(point, fitz.Matrix(total_rotation)))
                except Exception as e:
                    print(f"Render Error: {e}")
                
                curr_x += f_size + c_space
                line_char_count += 1
            
            # 段落间距 = 最后一行高度 * 2.0 + 倾斜角度额外边距（基于区域宽度）
            estimated_line_width = min(x2 - x1, 100)  # 估计行宽度
            extra_paragraph_margin = abs(paragraph_tilt_rad) * estimated_line_width * 0.8 if max_row_height > 0 else 0
            paragraph_spacing = (max_row_height * 2.0 + extra_paragraph_margin) if max_row_height > 0 else p_line['font_size'].get() * 2.0
            curr_y = line_base_y + paragraph_spacing
            if curr_y > y2 + 20: break

    def toggle_preview_mode(self):
        if not self.doc or not self.poly_id:
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
        if color_code[0] and color_code[1]:
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
            # 强制更新GUI以确保画布尺寸可用
            self.root.update_idletasks()
            self.render_page(auto_zoom=True)

    def calculate_auto_zoom(self, page):
        """计算自适应缩放比例使PDF页面完整显示在画布中"""
        canvas_width = self.canvas.winfo_width()
        canvas_height = self.canvas.winfo_height()
        
        # 如果画布尺寸未知，使用默认缩放
        if canvas_width <= 10 or canvas_height <= 10:
            return 1.5
            
        page_width = page.rect.width
        page_height = page.rect.height
        
        # 计算宽高缩放比例，留出10px边距
        width_ratio = (canvas_width - 20) / page_width
        height_ratio = (canvas_height - 20) / page_height
        
        # 选择较小的比例确保页面完全显示
        zoom = min(width_ratio, height_ratio)
        
        # 限制缩放范围在0.5到3.0之间
        return max(0.5, min(zoom, 3.0))
    
    def fit_to_window(self):
        """调整缩放使PDF页面完整显示在窗口中"""
        if self.doc:
            self.render_page(auto_zoom=True)
    
    def render_page(self, preserve_rect=False, auto_zoom=False):
        if not self.doc: return
        page = self.doc[self.current_page_num]
        self.page_label.config(text=f"页码: {self.current_page_num + 1} / {self.doc.page_count}")
        
        # 如果是首次加载或auto_zoom为True，计算自适应缩放
        if auto_zoom:
            self.zoom = self.calculate_auto_zoom(page)
        
        pix = page.get_pixmap(matrix=fitz.Matrix(self.zoom, self.zoom))
        img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
        self.tk_img = ImageTk.PhotoImage(img)
        
        # 调整画布滚动区域以适应图像大小
        self.canvas.config(scrollregion=(0, 0, pix.width, pix.height))
        
        self.canvas.delete("all")
        self.canvas.create_image(0, 0, anchor=tk.NW, image=self.tk_img)
        
        # 如果存在四边形且需要保留，重新创建
        if preserve_rect and self.poly_id and self.quad_points:
            self.update_quadrilateral()
        else: 
            self.poly_id = None
            self.quad_points = []
            for cp_id in self.control_points:
                self.canvas.delete(cp_id)
            self.control_points.clear()

    def save_to_history(self, doc_bytes):
        self.history.append(doc_bytes)
        if len(self.history) > self.max_history: self.history.pop(0)

    def undo_action(self):
        if not self.history: return
        self.doc.close()
        self.doc = fitz.open("pdf", self.history.pop())
        self.render_page()

    def erase_selection(self):
        if not self.doc or not self.poly_id or len(self.quad_points) < 8: return
        self.save_to_history(self.doc.write())
        page = self.doc[self.current_page_num]
        # 使用四边形的最小包围矩形进行擦除
        qp = self.quad_points
        x1 = min(qp[0], qp[2], qp[4], qp[6]) / self.zoom
        y1 = min(qp[1], qp[3], qp[5], qp[7]) / self.zoom
        x2 = max(qp[0], qp[2], qp[4], qp[6]) / self.zoom
        y2 = max(qp[1], qp[3], qp[5], qp[7]) / self.zoom
        rect = fitz.Rect(x1, y1, x2, y2)
        page.add_redact_annot(rect, fill=(1, 1, 1))
        page.apply_redactions()
        self.render_page()

    def prev_page(self):
        if self.doc and self.current_page_num > 0:
            self.current_page_num -= 1; self.render_page()

    def next_page(self):
        if self.doc and self.current_page_num < self.doc.page_count - 1:
            self.current_page_num += 1; self.render_page()

    def update_quadrilateral(self):
        """更新四边形显示和控制点"""
        # 删除旧的多边形和控制点
        if self.poly_id:
            self.canvas.delete(self.poly_id)
        for cp_id in self.control_points:
            self.canvas.delete(cp_id)
        self.control_points.clear()
        
        if not self.quad_points:
            return
            
        # 创建多边形
        self.poly_id = self.canvas.create_polygon(self.quad_points, outline='red', width=2, fill='')
        
        # 创建控制点（小圆点）
        for i in range(0, len(self.quad_points), 2):
            x, y = self.quad_points[i], self.quad_points[i+1]
            cp = self.canvas.create_oval(x-5, y-5, x+5, y+5, fill='blue', outline='white', width=2, tags=f"control_{i//2}")
            self.control_points.append(cp)
    
    def on_button_press(self, event):
        self.start_x, self.start_y = self.canvas.canvasx(event.x), self.canvas.canvasy(event.y)
        
        # 检查是否点击在控制点上
        items = self.canvas.find_overlapping(event.x-6, event.y-6, event.x+6, event.y+6)
        self.dragging_point = -1
        for item in items:
            tags = self.canvas.gettags(item)
            for tag in tags:
                if tag.startswith("control_"):
                    self.dragging_point = int(tag.split("_")[1])
                    return
        
        # 不是点击控制点，开始绘制新区域
        if self.poly_id:
            self.canvas.delete(self.poly_id)
        for cp_id in self.control_points:
            self.canvas.delete(cp_id)
        self.control_points.clear()
        self.quad_points = []
        self.dragging_point = -1
        
        # 创建初始矩形（四边形）
        self.quad_points = [
            self.start_x, self.start_y,
            self.start_x, self.start_y,
            self.start_x, self.start_y,
            self.start_x, self.start_y
        ]
        self.update_quadrilateral()

    def on_move_press(self, event):
        x, y = self.canvas.canvasx(event.x), self.canvas.canvasy(event.y)
        
        if self.dragging_point >= 0:
            # 拖拽控制点
            idx = self.dragging_point * 2
            self.quad_points[idx] = x
            self.quad_points[idx + 1] = y
            self.update_quadrilateral()
        elif self.quad_points:
            # 拖拽绘制新区域（更新四边形为矩形）
            x1, y1 = self.start_x, self.start_y
            x2, y2 = x, y
            
            # 确保四边形顶点顺序：左上、右上、右下、左下
            self.quad_points = [
                min(x1, x2), min(y1, y2),  # 左上
                max(x1, x2), min(y1, y2),  # 右上
                max(x1, x2), max(y1, y2),  # 右下
                min(x1, x2), max(y1, y2)   # 左下
            ]
            self.update_quadrilateral()

    def on_button_release(self, event):
        """鼠标释放事件处理"""
        self.dragging_point = -1
        self.auto_refresh_preview()
    
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