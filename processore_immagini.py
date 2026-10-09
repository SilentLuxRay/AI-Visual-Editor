import os
import sys
import re
import json
import math
import fnmatch
import threading
import queue
import time
import urllib.request
import urllib.error
from datetime import datetime

# --- identità della versione: unico punto in cui il numero è scritto ---
APP_VERSION = "2.34"
APP_CODENAME = "Text Settings"
GITHUB_REPO = "SilentLuxRay/AI-Visual-Editor"
GITHUB_RELEASES_API = f"https://api.github.com/repos/{GITHUB_REPO}/releases/latest"
GITHUB_RELEASES_PAGE = f"https://github.com/{GITHUB_REPO}/releases/latest"
MAIN_SCRIPT_NAME = "processore_immagini.py"

# --- catalogo dei parametri che possono comparire nei metadati ---------------
# Ricavato dal sorgente del webui e dalle estensioni, non a memoria. Serve solo
# a popolare il menu a tendina: qualunque nome si può comunque scrivere a mano,
# e i jolly * ? sono ammessi (indispensabili per ADetailer, che dalla seconda
# unità in poi aggiunge un suffisso ordinale: "ADetailer model 2nd", "3rd"…).
PARAM_CATALOG = {
    "Base": ["Steps", "Sampler", "Schedule type", "CFG scale", "Distilled CFG Scale", "Seed", "Size",
             "Model", "Model hash", "VAE", "Clip skip", "Denoising strength", "Emphasis", "RNG",
             "Tiling", "Version", "User", "Face restoration", "ENSD", "Init image hash",
             "Token merging ratio", "Token merging ratio hr", "Conditional mask weight",
             "Variation seed", "Variation seed strength", "Seed resize from",
             "SGM noise multiplier", "Noise multiplier", "Extra noise", "Pad conds",
             "Skip Early CFG", "NGMS", "NGMS all steps", "Downcast alphas_cumprod"],
    "Hires fix": ["Hires upscaler", "Hires steps", "Hires CFG Scale", "Hires upscale", "Hires resize",
                  "Hires sampler", "Hires schedule type", "Hires checkpoint", "Hires prompt",
                  "Hires negative prompt", "Hires Distilled CFG Scale", "Hires Shift", "Hires Module 1"],
    "Forge Neo": ["Distilled CFG Scale", "Emphasis", "MaHiRo", "Rescale CFG", "Mask rounding",
                  "NGMS", "NGMS all steps", "Skip Early CFG", "Downcast alphas_cumprod",
                  "Hires Module 1", "Hires Shift", "Lora hashes", "TI hashes", "Hashes"],
    "ControlNet": ["ControlNet*", "ControlNet 0", "ControlNet 1", "ControlNet 2"],
    "Refiner": ["Refiner", "Refiner switch at"],
    "Inpaint / img2img": ["Mask blur", "Mask mode", "Masked content", "Masked area padding",
                          "Inpaint area", "Original Size"],
    "Sigma / schedule": ["Schedule max sigma", "Schedule min sigma", "Schedule rho", "Sigma churn",
                         "Sigma noise", "Sigma tmax", "Sigma tmin", "Beta schedule alpha",
                         "Beta schedule beta", "Noise Schedule", "Discard penultimate sigma"],
    "Ultimate SD upscale": ["Ultimate SD upscale*", "Ultimate SD upscale upscaler",
                            "Ultimate SD upscale tile_width", "Ultimate SD upscale tile_height",
                            "Ultimate SD upscale mask_blur", "Ultimate SD upscale padding"],
    "ADetailer": ["ADetailer*", "ADetailer model*", "ADetailer prompt*", "ADetailer negative prompt*",
                  "ADetailer confidence*", "ADetailer mask blur*", "ADetailer denoising strength*",
                  "ADetailer inpaint only masked*", "ADetailer inpaint padding*", "ADetailer steps*",
                  "ADetailer CFG scale*", "ADetailer sampler*", "ADetailer checkpoint*",
                  "ADetailer VAE*", "ADetailer version"],
}
# Impostazione di partenza: l'essenziale per capire e riprodurre una generazione.
DEFAULT_KEEP_PARAMS = ["Steps", "Sampler", "Schedule type", "CFG scale", "Seed", "Size", "RNG",
                       "Emphasis", "SGM noise multiplier", "Version",
                       "Hires upscaler", "Hires steps", "Hires CFG Scale"]
from PIL import Image, ImageTk, PngImagePlugin, ImageFilter, ImageOps, ImageChops, ImageDraw, ImageFont, ImageColor
import tkinter as tk
from tkinter import filedialog, messagebox, ttk, colorchooser, simpledialog

try:
    from tkinterdnd2 import TkinterDnD, DND_FILES
    DND_AVAILABLE = True
except ImportError:
    DND_AVAILABLE = False

class ImageProcessor:
    def __init__(self, root):
        self.root = root
        self.root.title(f"AI Visual Editor — Studio Pro v{APP_VERSION} ({APP_CODENAME})")
        self.root.geometry("1600x1080")
        self.root.minsize(1280, 800)

        # === TEMA MODERNO (dark) ===
        self.C = {
            "bg": "#12141a", "sidebar": "#191c24", "card": "#232733", "card_hd": "#2c313f",
            # gerarchia dei testi: text (primario) > muted (etichette) > faint (descrizioni).
            # Tutti e tre restano sopra 4.5:1 di contrasto sulle card scure: con i valori
            # precedenti le descrizioni stavano a 2.4:1 ed erano praticamente illeggibili.
            "input": "#2e3440", "input_bd": "#3b4252", "text": "#e6e8ee", "muted": "#a7afc2",
            "faint": "#8b93a7", "line": "#333a49", "accent": "#7c6cff", "accent_hi": "#9385ff",
            "green": "#34d399", "green_hi": "#4ade80", "amber": "#f5b942", "red": "#f26d6d",
            "red_hi": "#f78a8a", "blue": "#5aa2f5", "teal": "#2dd4bf", "canvas": "#0e1014",
        }
        self.FONT = "Segoe UI"; self.MONO = "Consolas"
        try: self.root.configure(bg=self.C["bg"])
        except Exception: pass

        try:
            if getattr(sys, 'frozen', False):
                self.base_path = os.path.dirname(sys.executable)
            else:
                self.base_path = os.path.dirname(os.path.abspath(__file__))
                
            self.folder_firme = os.path.join(self.base_path, "Firme")
            self.folder_cornici = os.path.join(self.base_path, "Cornici")
            self.folder_mask = os.path.join(self.base_path, "Cornici_Mask")
            self.folder_maschere = os.path.join(self.base_path, "Maschere")
            self.folder_rating = os.path.join(self.base_path, "Rating")
            self.folder_extra = os.path.join(self.base_path, "Extra")
            self.folder_lang = os.path.join(self.base_path, "Lang")
            self.folder_layouts = os.path.join(self.base_path, "Layouts")
            self.path_lang_config = os.path.join(self.folder_lang, "config.txt")
            self.output_folder = os.path.join(self.base_path, "Output_Pubblicazione")
            self.path_ignore_loras = os.path.join(self.base_path, "ignore_loras.txt")
            self.path_ignore_tags = os.path.join(self.base_path, "ignore_tags.txt")
            self.path_footer_note = os.path.join(self.base_path, "footer_note.txt")
            self.path_copyright = os.path.join(self.base_path, "copyright.txt")
            self.path_model_links = os.path.join(self.base_path, "model_links.json")
            self.path_keep_params = os.path.join(self.base_path, "params_keep.json")
            self.path_settings = os.path.join(self.base_path, "settings.json")
            self.path_text_presets = os.path.join(self.base_path, "text_presets.json")
            
            for f in [self.output_folder, self.folder_cornici, self.folder_rating, self.folder_mask, self.folder_firme, self.folder_maschere, self.folder_extra, self.folder_lang, self.folder_layouts]:
                os.makedirs(f, exist_ok=True)

            # I vecchi file di testo vengono importati nelle impostazioni.
            
            self.current_file_path = ""
            self.orig_img = None
            self.info_buffer = {}
            self.img_w = self.img_h = 0
            self.preview_hidden = False
            self.base_ratio = 1.0
            self.view_zoom = 1.0
            self.raw_assets = {"firma": None, "cornice": None, "rating": None, "border": None, "trama": None, "extra": None}
            self.tk_refs = {}
            self.ratio = 1.0
            self.selected_layer = None 
            self.current_signature_name = "User"
            self.current_frame_name = ""
            
            self.state = {
                "firma": {"pos": None, "scale": 0.15, "visible": True, "rotation": 0},
                "rating": {"pos": None, "scale": 0.12, "visible": True, "rotation": 0},
                "cornice": {"pos": None, "size": 0.45, "visible": True},
            }
            # EXTRA multipli: ognuno indipendente — {uid, name, img, pos, scale, visible, rotation}
            self.extras = []
            self._extra_uid = 0
            # TESTI personalizzati multipli (liste separate per Editor e Collage: canvas diversi)
            self.texts = []
            self.collage_texts = []
            self._text_uid = 0
            self._font_cache = {}
            self.text_presets = []          # [{name, text, size, color, outline, opacity, align, rotation}]
            self._load_text_presets()

            self.drag_data = {"x": 0, "y": 0, "item": None}
            self.sdnext_mode = tk.BooleanVar(value=False)
            self.keep_metadata = tk.BooleanVar(value=False)
            self.optimize_png = tk.BooleanVar(value=True)
            self.civitai_links = tk.BooleanVar(value=True)  # link di ricerca Civitai per i modelli NON in tabella
            self.custom_links = tk.BooleanVar(value=True)   # link personalizzati per i modelli presenti in tabella
            # Quali parametri finiscono sotto "Parameters:". RNG compreso: prima aveva
            # una spunta tutta sua, ora è una voce della lista come le altre.
            self.param_filter = tk.BooleanVar(value=True)
            self.keep_params = list(DEFAULT_KEEP_PARAMS)
            self._param_filter_saved = True
            self.update_check = tk.BooleanVar(value=True)   # controllo aggiornamenti all'avvio
            self._update_info = None                         # dati dell'ultima release trovata
            self._update_banner = None
            self.model_links = []                            # [{"name":..., "url":...}] da model_links.json
            self._links_index = {}                           # nome normalizzato -> url
            self._load_model_links()
            self._load_keep_params()
            self.param_filter.set(self._param_filter_saved)
            # opzioni della tab Impostazioni: ricordate tra un avvio e l'altro (settings.json)
            self._settings_vars = {
                "sdnext_mode": self.sdnext_mode, "keep_metadata": self.keep_metadata,
                "optimize_png": self.optimize_png, "civitai_links": self.civitai_links,
                "custom_links": self.custom_links,
                "update_check": self.update_check,
            }
            self._load_settings()
            # i trace vanno registrati DOPO il caricamento, altrimenti si riscrive il file all'avvio
            for _v in self._settings_vars.values():
                _v.trace_add("write", lambda *a: self._save_settings())
            self.extra_target = tk.StringVar(value="cornice")  # dove stampare l'EXTRA: "cornice" | "immagine"
            self.trama_mode = tk.BooleanVar(value=False)  # circle trama: ritaglia immagine a cerchio, trama sopra

            # --- MOSAIC BRUSH ---
            self.mosaic_mode = False
            self.mosaic_brush_mode = tk.StringVar(value="rect")  # "rect" o "circle"
            self.mosaic_tile_size = tk.IntVar(value=16)
            self.mosaic_brush_size = tk.IntVar(value=60)
            self.mosaic_regions = []          # list of (x1,y1,x2,y2) in ORIGINAL image coords
            self.mosaic_drag_start = None
            self.mosaic_preview_rect = None
            self._refresh_after_id = None    # throttling refresh background (pennello mosaico)
            self._mosaic_base = None         # copia pulita dell'immagine: il pennello campiona SEMPRE da qui (niente sbavature)

            # --- COLLAGE (tab 2) ---
            self.collage_images = []          # list di dict: {path, name, img(RGBA), info, offx, offy}
            self.collage_w = tk.IntVar(value=800)
            self.collage_h = tk.IntVar(value=1000)
            self.collage_gutter = tk.IntVar(value=20)   # spazio tra colonne + bordo esterno
            self.collage_gutter_color = "#ffffff"
            self.collage_outline = tk.IntVar(value=0)      # spessore contorno vignetta (0 = nessuno)
            self.collage_outline_color = "#000000"
            self.free_snap = tk.BooleanVar(value=True)     # aggancio magnetico degli angoli
            self._collage_cells = []          # geometria celle in px canvas (per il drag del ritaglio)
            self._collage_drag_idx = None
            self._collage_last = (0, 0)
            self._collage_tk = None
            self._collage_origin = (0, 0)
            # firma sul collage (riusa self.raw_assets["firma"])
            self.collage_sig_enabled = tk.BooleanVar(value=False)
            self.collage_sig_scale = tk.IntVar(value=15)     # % della larghezza del collage
            self.signature_opacity = tk.IntVar(value=100)
            self.collage_sig_opacity = tk.IntVar(value=100)
            self.collage_sig_pos = (0.72, 0.90)              # angolo alto-sinistra normalizzato (0-1)
            self._collage_sig_rect = None
            self._collage_sig_drag = False
            self._collage_text_rects = []      # [(dict testo, rect canvas)]
            self.collage_text_sel = None       # uid del testo selezionato
            self._collage_text_drag = None     # dict del testo in trascinamento
            self._collage_pw = self._collage_ph = 1
            # cornice sul collage (il collage viene rimpicciolito dentro l'apertura trasparente)
            self.collage_frame_enabled = tk.BooleanVar(value=False)
            self._collage_frame_img = None       # PIL RGBA della cornice scelta
            self._collage_frame_opening = None    # bbox (x0,y0,x1,y1) dell'apertura trasparente
            self.collage_frame_fit = tk.StringVar(value="inside")  # "inside" | "fill" (unire varianti)
            # --- modalità layout: "cols" (colonne automatiche) | "free" (editor libero) ---
            self.collage_mode = tk.StringVar(value="cols")
            self.collage_dir = tk.StringVar(value="cols")   # griglia automatica: "cols" (verticale) | "rows" (orizzontale)
            self.collage_grid_cols = tk.IntVar(value=2)
            self.collage_grid_rows = tk.IntVar(value=2)
            # celle libere: una per immagine — x,y = CENTRO normalizzato (0-1), w,h normalizzati, rot in gradi
            self.free_cells = []
            self.free_sel = None              # indice cella selezionata
            self.free_rot = tk.IntVar(value=0)  # rotazione della cella selezionata (UI)
            self.free_slant = tk.IntVar(value=40)  # pendenza dei tagli diagonali, in %
            self._free_action = None           # "move" | "resize" | "pan"
            self._free_handle = None           # indice angolo in resize
            self._free_start = None            # snapshot per il drag

            # --- SEED ID ---
            self.seed_value = ""
            self.seed_id_visible = tk.BooleanVar(value=False)
            self.custom_id = tk.StringVar(value="")  # ID manuale quando non c'è seed
            # posizione assoluta normalizzata sull'INTERA immagine (0–1), come firma e rating
            self.seed_id_pos = (0, 0)  # posizione pixel canvas raw
            self.seed_id_pos_relative = None  # posizione RELATIVA alla cornice, salvata al drag (come rating)
            self.seed_id_font_size = tk.IntVar(value=28)
            self.seed_id_dragging = False

            # --- ACCOUNT NAME (per nome file cornice) ---
            self.current_account_name = ""

            # --- COPYRIGHT ---
            self.copyright_enabled = tk.BooleanVar(value=False)  # serve di rado: spento all'avvio
            self.copyright_font_size = tk.IntVar(value=30)  # pixel reali nell'immagine salvata
            self.copyright_opacity = tk.IntVar(value=200)  # 0–255
            self.copyright_text = ""   # caricato da copyright.txt

            # --- MULTILINGUA ---
            self.i18n_widgets = []  # (widget, key) — per aggiornare i testi al cambio lingua a runtime
            self.STRINGS_IT = {
                "layers_control": "LAYERS CONTROL", "transform": "TRANSFORM",
                "delete_permanently": "DELETE PERMANENTLY", "select_account": "SELECT ACCOUNT / SIGNATURE:",
                "circle_trama_mode": "🔷 CORNICI SAGOMATE", "trama_overlay": "TRAMA OVERLAY:",
                "extra_section": "🏷️ EXTRA (sconto / gratis / altro):",
                "extra_hint": "SHIFT + click = aggiungi elemento (più elementi ok)",
                "extra_target": "Stampa su:", "extra_on_frame": "Cornice", "extra_on_image": "Immagine",
                "extra_target_hint": "Vale per l'elemento selezionato: ogni extra può andare\ndove vuoi. Se non ne hai selezionato nessuno, la scelta\nfa da predefinita per il prossimo che aggiungi.",
                "sdnext_mode": "SD.Next", "keep_metadata": "Metadata", "optimize_png": "Ottimizza PNG",
                "civitai_links": "Link Civitai",
                "extra_replace": "⇄  Sostituisci selezionato",
                "custom_links": "Link personalizzati",
                # --- LIVELLI DI TESTO ---
                "t_section": "✏️  TESTI", "t_add": "➕  Aggiungi testo", "t_none": "Nessun testo selezionato",
                "t_placeholder": "Nuovo testo", "layer_text": "TESTO",
                "t_size": "Dim", "t_outline": "Contorno", "t_opacity": "Opacità", "t_color": "Colore",
                "t_target": "Su:", "t_on_image": "Immagine", "t_on_frame": "Cornice",
                "t_hint": "Trascina il testo sul canvas. Usa + − ⟲ ⟳ per\ndimensione e rotazione. Invio va a capo.",
                "t_hint_collage": "Trascina il testo nell'anteprima.\nInvio va a capo.",
                "t_align": "Allinea:", "t_align_left": "Sx", "t_align_center": "Centro", "t_align_right": "Dx",
                "p_presets": "⭐  PRESET DI TESTO", "p_label": "Preset:", "p_use": "Usa",
                "p_save": "⭐  Salva come preset", "p_name": "Nome del preset:", "p_none": "Nessun preset salvato",
                "p_hint": "Componi un testo nell'Editor o nel Collage con colore,\ndimensione e allineamento che vuoi, poi premi\n\"Salva come preset\": lo ritrovi nella tendina Preset.",
                "c_dir": "Direzione:", "c_dir_v": "Colonne", "c_dir_h": "Righe", "c_rows": "righe",
                "c_dir_grid": "Griglia", "c_grid_cols": "Colonne:", "c_grid_rows": "Righe:",
                "c_grid_hint": "Ordine: da sinistra a destra, poi dall'alto in basso.\nSe necessario vengono aggiunte righe automaticamente.",
                "c_diagonal": "◣  Diagonale", "c_slant": "Pendenza % (100 = spigolo a spigolo)",
                # --- TAB IMPOSTAZIONI ---
                "s_tab": "  ⚙  Impostazioni  ", "s_title": "⚙  IMPOSTAZIONI",
                "s_language": "🌐  LINGUA",
                "s_output": "💾  OPZIONI DI SALVATAGGIO",
                # --- aggiornamenti ---
                "u_section": "⬆️  AGGIORNAMENTI", "u_check_startup": "Controlla all'avvio",
                "u_check_now": "Controlla ora", "u_open_page": "Apri la pagina",
                "u_hint": "Il controllo contatta GitHub solo per leggere il numero\ndell'ultima versione. Non viene inviato nulla di tuo.",
                "u_available": "⬆  Disponibile la versione {v} — clicca per aggiornare",
                "u_up_to_date": "Stai già usando l'ultima versione (v{v}).",
                "u_check_failed": "Impossibile controllare gli aggiornamenti.\nControlla la connessione e riprova.",
                "u_confirm": "Scaricare e installare la versione {v}?\n\nLa versione attuale verrà salvata come copia di sicurezza.\nSe hai modificato il file, le tue modifiche verranno sostituite.",
                "u_download_failed": "Scaricamento non riuscito.",
                "u_invalid": "Il file scaricato non è valido: aggiornamento annullato.\nNiente è stato modificato.",
                "u_write_failed": "Impossibile scrivere il file: aggiornamento annullato.",
                "u_done": "Aggiornato alla versione {v}.\n\nCopia di sicurezza: {b}\n\nChiudi e riapri il programma per usare la nuova versione.",
                "u_frozen": "Stai usando la versione compilata (.exe): scarica il nuovo pacchetto dalla pagina delle release.",
                "u_not_found": "File {f} non trovato accanto al programma: aggiornamento annullato.",
                # --- filtro dei parametri ---
                "p_section": "🧮  PARAMETRI NEL TXT", "p_enable": "Tieni solo i parametri scelti",
                "p_hint": "Con il filtro acceso finiscono nel txt solo le voci qui sotto,\nnell'ordine in cui le scrive il webui. Quelle assenti dai\nmetadati vengono semplicemente saltate.\n★ Jolly ammessi: \"ADetailer*\" prende anche \"ADetailer model 2nd\".\nPer escludere qualcosa basta non metterlo in lista.",
                "p_add": "Aggiungi", "p_from_image": "Leggi dall'immagine",
                "p_add_custom": "Aggiungi scritto a mano", "p_reset": "Ripristina",
                "p_clear": "Svuota", "p_empty": "Nessun parametro selezionato:\nla sezione Parameters uscirà vuota.",
                "p_no_image": "Carica prima un'immagine con i metadati.",
                "p_nothing_new": "Tutti i parametri di questa immagine sono già in lista.",
                "p_add_found": "Trovati {n} parametri non ancora in lista:\n{l}\n\nAggiungerli?",
                "s_metadata_hint": "Queste opzioni vengono ricordate al prossimo avvio.\n⚠ Con \"Metadata\" attivo i dati vengono scritti dentro il\nPNG e il file .txt del prompt NON viene creato.",
                "s_language_hint": "Per aggiungere una lingua: copia un file da Lang/,\nrinominalo (es. fr.json) e traduci i valori.",
                "s_links": "🔗  LINK AI MODELLI",
                "s_links_hint": "Per i modelli che NON stanno su Civitai: scrivi il nome\n(senza estensione) e il link dove si trovano.\n★ Jolly: \"ZipZap_OC_Ill_V*\" copre tutte le versioni.\nSe combaciano più jolly vince il più specifico, e un nome\nesatto batte sempre il jolly.\nI modelli in lista non mostrano mai il link Civitai.",
                "s_name": "Nome modello / lora", "s_url": "Link", "s_add": "➕  Aggiungi / Aggiorna",
                "s_no_links": "Nessun link personalizzato", "s_saved_in": "Salvato in model_links.json",
                # --- TAB COLLAGE ---
                "c_title": "🖼  COLLAGE", "c_images": "IMMAGINI  (in ordine)",
                "c_image_scale": "Scala %",
                "c_add_images": "＋  Aggiungi immagini", "c_no_images": "Nessuna immagine caricata",
                "c_format": "FORMATO FILE", "c_width": "Larghezza", "c_height": "Altezza",
                "c_gutter": "Spazio / bordo px", "c_gutter_color": "Colore spazi", "c_choose": "Scegli…",
                "c_outline": "Contorno px", "c_layout": "LAYOUT",
                "c_mode_cols": "Griglia automatica", "c_mode_free": "Libero (sposta / ridimensiona / ruota)",
                "c_rotate": "Ruota", "c_straighten": "▭ Raddrizza", "c_reset_cols": "Reset a colonne",
                "c_preset": "Preset", "c_save_short": "💾 Salva", "c_snap": "🧲 Aggancia angoli e bordi",
                "c_hint_free": "💡 Angolo = lo muovi da solo (vignette storte)\nSHIFT+angolo = ridimensiona restando rettangolo\nTrascina dentro = sposta • Ctrl+trascina = ritaglio\nFai TOCCARE le vignette: il bianco lo crea 'Spazio px',\nsempre uguale ovunque.",
                "c_hint_cols": "💡 Trascina un'immagine nell'anteprima per\nspostare il ritaglio.",
                "c_signature": "FIRMA", "c_sig_apply": "Applica firma", "c_sig_size": "Dim %",
                "c_hint_sig": "💡 Trascina la firma nell'anteprima per spostarla.",
                "signature_opacity": "Opacità firma %",
                "s_text_config": "TESTI E FILTRI", "s_ignore_tags": "Tag esclusi (uno per riga)",
                "s_ignore_loras": "LoRA esclusi (uno per riga)", "s_footer_text": "Nota finale / Footer",
                "s_copyright_text": "Testo copyright",
                "s_text_config_hint": "Salvataggio automatico nelle impostazioni, valido per Editor e Collage.\nFiltri: una voce per riga; # introduce un commento.\nSegnaposto: {NAME}, {YEAR}, {DATE}; nel footer anche {HOURS}.\nI vecchi file vengono importati solo se manca il corrispondente testo nelle impostazioni.",
                "c_frame": "CORNICE", "c_frame_apply": "Applica cornice",
                "c_frame_fit": "Come applicarla:",
                "c_fit_inside": "Dentro l'apertura", "c_fit_fill": "Riempi la cornice (unisci varianti)",
                "c_hint_frame": "💡 \"Dentro l'apertura\": il collage viene rimpicciolito e\ncentrato nella cornice.\n\"Riempi\": il collage copre tutta la cornice e la decorazione\nva sopra — così unisci più varianti della stessa immagine\nin un'unica miniatura. Metti Spazio a 0 e usa lo stesso\nformato della cornice per non perdere nulla ai bordi.",
                "c_textfile": "FILE DI TESTO",
                "c_hint_civitai": "💡 Aggiunge il link di ricerca Civitai sotto ogni hash.",
                "c_save_all": "💾  SALVA COLLAGE",
                "c_empty": "Aggiungi immagini per comporre il collage",
                "c_panels_free": "riquadri (libero)", "c_columns": "colonne", "c_gap": "spazio", "c_with_frame": "cornice",
                "load_image": "LOAD IMAGE", "hide_preview": "🙈 NASCONDI (Ctrl+H)",
                "zoom_canvas_section": "🔍 ZOOM CANVAS", "zoom_reset": "Reset",
                "zoom_hint": "Ctrl+rotellina o Ctrl +/- per zoomare.\nLivelli trascinabili anche da zoomato.",
                "mosaic_section": "✏️ MOSAIC CENSOR BRUSH", "mosaic_off": "🔴 MOSAIC OFF", "mosaic_on": "🟢 MOSAIC ON",
                "modo": "Modo:", "rettangolo": "Rettangolo", "pennello": "Pennello",
                "tile_px": "Tile px:", "brush_px": "Brush px:", "undo": "↩ UNDO", "clear_all": "🗑 CLEAR",
                "seed_section": "🔑 SEED ID", "show_id": "Mostra ID", "font": "Font:",
                "id_manuale": "ID manuale:", "seed_drag_hint": "trascina per spostare",
                "save_all": "SAVE ALL EXPORTS", "copyright_section": "© COPYRIGHT", "copyright_enable": "Attiva",
                "font_px": "Font px:", "opacity": "Opacità:", "language_label": "🌐 Lingua:",
                "layer_firma": "FIRMA", "layer_rating": "RATING", "layer_cornice": "CORNICE", "layer_extra": "EXTRA",
                "msg_success_title": "Successo", "msg_success_body": "Esportazioni salvate!",
                "msg_error_title": "Errore", "msg_unsupported_format_title": "Formato non supportato",
                "msg_unsupported_format_body": "Formato '{ext}' non supportato.\nUsa PNG, JPG, WEBP o BMP.",
                "msg_load_image_first": "Carica prima un'immagine.",
            }
            self._ensure_default_lang_files()
            self.current_lang = self._read_lang_config()
            self.strings = {}
            self._load_language(self.current_lang)

            self.setup_ui()
            self.pre_load_assets()
            # drag & drop se tkinterdnd2 è disponibile
            if DND_AVAILABLE:
                self.canvas.drop_target_register(DND_FILES)
                self.canvas.dnd_bind("<<Drop>>", self.on_drop)
            # controllo aggiornamenti: parte dopo che la finestra è pronta, in background
            if self.update_check.get():
                self.root.after(1200, lambda: self.check_updates_async(manual=False))

        except Exception as e:
            messagebox.showerror("Error", f"Startup failed: {e}")

    # =========================================================
    # SISTEMA MULTILINGUA
    # =========================================================
    def _english_strings(self):
        """Traduzione inglese di default, scritta su disco come esempio/base per altre lingue."""
        return {
            "layers_control": "LAYERS CONTROL", "transform": "TRANSFORM",
            "delete_permanently": "DELETE PERMANENTLY", "select_account": "SELECT ACCOUNT / SIGNATURE:",
            "circle_trama_mode": "🔷 SHAPED FRAME MODE", "trama_overlay": "TEXTURE OVERLAY:",
            "extra_section": "🏷️ EXTRA (discount / free / other):",
            "extra_hint": "SHIFT + click = add element (multiple allowed)",
            "extra_target": "Print on:", "extra_on_frame": "Frame", "extra_on_image": "Image",
            "extra_target_hint": "Applies to the selected element: each extra can go\nwherever you like. With nothing selected, the choice\nbecomes the default for the next one you add.",
            "sdnext_mode": "SD.Next", "keep_metadata": "Metadata", "optimize_png": "Optimize PNG",
            "civitai_links": "Civitai links",
            "extra_replace": "⇄  Replace selected",
            "custom_links": "Custom links",
            # --- TEXT LAYERS ---
            "t_section": "✏️  TEXTS", "t_add": "➕  Add text", "t_none": "No text selected",
            "t_placeholder": "New text", "layer_text": "TEXT",
            "t_size": "Size", "t_outline": "Outline", "t_opacity": "Opacity", "t_color": "Color",
            "t_target": "On:", "t_on_image": "Image", "t_on_frame": "Frame",
            "t_hint": "Drag the text on the canvas. Use + − ⟲ ⟳ for\nsize and rotation. Enter makes a new line.",
            "t_hint_collage": "Drag the text in the preview.\nEnter makes a new line.",
            "t_align": "Align:", "t_align_left": "L", "t_align_center": "C", "t_align_right": "R",
            "p_presets": "⭐  TEXT PRESETS", "p_label": "Preset:", "p_use": "Use",
            "p_save": "⭐  Save as preset", "p_name": "Preset name:", "p_none": "No presets saved",
            "p_hint": "Compose a text in the Editor or Collage with the color,\nsize and alignment you want, then press\n\"Save as preset\": you'll find it in the Preset dropdown.",
            "c_dir": "Direction:", "c_dir_v": "Columns", "c_dir_h": "Rows", "c_rows": "rows",
            "c_dir_grid": "Grid", "c_grid_cols": "Columns:", "c_grid_rows": "Rows:",
            "c_grid_hint": "Order: left to right, then top to bottom.\nExtra rows are added automatically when needed.",
            "c_diagonal": "◣  Diagonal", "c_slant": "Slant % (100 = corner to corner)",
            # --- SETTINGS TAB ---
            "s_tab": "  ⚙  Settings  ", "s_title": "⚙  SETTINGS",
            "s_language": "🌐  LANGUAGE",
            "s_output": "💾  SAVING OPTIONS",
            # --- updates ---
            "u_section": "⬆️  UPDATES", "u_check_startup": "Check on startup",
            "u_check_now": "Check now", "u_open_page": "Open the page",
            "u_hint": "The check contacts GitHub only to read the latest version\nnumber. Nothing of yours is ever sent.",
            "u_available": "⬆  Version {v} is available — click to update",
            "u_up_to_date": "You are already on the latest version (v{v}).",
            "u_check_failed": "Could not check for updates.\nCheck your connection and try again.",
            "u_confirm": "Download and install version {v}?\n\nYour current version will be kept as a backup.\nIf you edited the file, your changes will be replaced.",
            "u_download_failed": "Download failed.",
            "u_invalid": "The downloaded file is not valid: update cancelled.\nNothing has been changed.",
            "u_write_failed": "Could not write the file: update cancelled.",
            "u_done": "Updated to version {v}.\n\nBackup: {b}\n\nClose and reopen the program to use the new version.",
            "u_frozen": "You are running the packaged version (.exe): download the new package from the releases page.",
            "u_not_found": "File {f} not found next to the program: update cancelled.",
            # --- parameter filter ---
            "p_section": "🧮  PARAMETERS IN THE TXT", "p_enable": "Keep only the chosen parameters",
            "p_hint": "With the filter on, only the entries below reach the txt,\nin the order the webui writes them. Ones missing from the\nmetadata are simply skipped.\n★ Wildcards allowed: \"ADetailer*\" also catches \"ADetailer model 2nd\".\nTo exclude something, just leave it off the list.",
            "p_add": "Add", "p_from_image": "Read from image",
            "p_add_custom": "Add typed entry", "p_reset": "Restore defaults",
            "p_clear": "Clear all", "p_empty": "No parameter selected:\nthe Parameters section will come out empty.",
            "p_no_image": "Load an image with metadata first.",
            "p_nothing_new": "Every parameter in this image is already listed.",
            "p_add_found": "Found {n} parameters not yet listed:\n{l}\n\nAdd them?",
            "s_metadata_hint": "These options are remembered on next launch.\n⚠ With \"Metadata\" on, data is written inside the PNG\nand the prompt .txt file is NOT created.",
            "s_language_hint": "To add a language: copy a file from Lang/,\nrename it (e.g. fr.json) and translate the values.",
            "s_links": "🔗  MODEL LINKS",
            "s_links_hint": "For models NOT hosted on Civitai: write the name\n(without extension) and the link where they live.\n★ Wildcard: \"ZipZap_OC_Ill_V*\" covers every version.\nIf several wildcards match, the most specific wins, and an\nexact name always beats a wildcard.\nModels in this list never show the Civitai link.",
            "s_name": "Model / lora name", "s_url": "Link", "s_add": "➕  Add / Update",
            "s_no_links": "No custom links", "s_saved_in": "Saved in model_links.json",
            # --- COLLAGE TAB ---
            "c_title": "🖼  COLLAGE", "c_images": "IMAGES  (in order)",
            "c_image_scale": "Scale %",
            "c_add_images": "＋  Add images", "c_no_images": "No images loaded",
            "c_format": "FILE FORMAT", "c_width": "Width", "c_height": "Height",
            "c_gutter": "Gap / border px", "c_gutter_color": "Gap color", "c_choose": "Choose…",
            "c_outline": "Outline px", "c_layout": "LAYOUT",
            "c_mode_cols": "Automatic grid", "c_mode_free": "Free (move / resize / rotate)",
            "c_rotate": "Rotate", "c_straighten": "▭ Straighten", "c_reset_cols": "Reset to columns",
            "c_preset": "Preset", "c_save_short": "💾 Save", "c_snap": "🧲 Snap corners and edges",
            "c_hint_free": "💡 Corner = moves on its own (slanted panels)\nSHIFT+corner = resize keeping it rectangular\nDrag inside = move • Ctrl+drag = crop\nMake the panels TOUCH: the gap comes from 'Gap px',\nalways the same everywhere.",
            "c_hint_cols": "💡 Drag an image in the preview to\nmove the crop.",
            "c_signature": "SIGNATURE", "c_sig_apply": "Apply signature", "c_sig_size": "Size %",
            "c_hint_sig": "💡 Drag the signature in the preview to move it.",
            "signature_opacity": "Signature opacity %",
            "s_text_config": "TEXT AND FILTERS", "s_ignore_tags": "Excluded tags (one per line)",
            "s_ignore_loras": "Excluded LoRAs (one per line)", "s_footer_text": "Footer note",
            "s_copyright_text": "Copyright text",
            "s_text_config_hint": "Automatically saved in settings, shared by Editor and Collage.\nFilters: one entry per line; # starts a comment.\nPlaceholders: {NAME}, {YEAR}, {DATE}; also {HOURS} in the footer.\nLegacy files are imported only when the corresponding text is absent from settings.",
            "c_frame": "FRAME", "c_frame_apply": "Apply frame",
            "c_frame_fit": "How to apply it:",
            "c_fit_inside": "Inside the opening", "c_fit_fill": "Fill the frame (merge variants)",
            "c_hint_frame": "💡 \"Inside the opening\": the collage is scaled down and\ncentred in the frame.\n\"Fill\": the collage covers the whole frame and the artwork\ngoes on top — this is how you merge several variants of the\nsame image into one thumbnail. Set Gap to 0 and use the\nframe's aspect ratio so nothing is cut off at the edges.",
            "c_textfile": "TEXT FILE",
            "c_hint_civitai": "💡 Adds the Civitai search link under each hash.",
            "c_save_all": "💾  SAVE COLLAGE",
            "c_empty": "Add images to build the collage",
            "c_panels_free": "panels (free)", "c_columns": "columns", "c_gap": "gap", "c_with_frame": "frame",
            "load_image": "LOAD IMAGE", "hide_preview": "🙈 HIDE (Ctrl+H)",
            "zoom_canvas_section": "🔍 ZOOM CANVAS", "zoom_reset": "Reset",
            "zoom_hint": "Ctrl+wheel or Ctrl +/- to zoom.\nLayers can still be dragged while zoomed.",
            "mosaic_section": "✏️ MOSAIC CENSOR BRUSH", "mosaic_off": "🔴 MOSAIC OFF", "mosaic_on": "🟢 MOSAIC ON",
            "modo": "Mode:", "rettangolo": "Rectangle", "pennello": "Brush",
            "tile_px": "Tile px:", "brush_px": "Brush px:", "undo": "↩ UNDO", "clear_all": "🗑 CLEAR",
            "seed_section": "🔑 SEED ID", "show_id": "Show ID", "font": "Font:",
            "id_manuale": "Manual ID:", "seed_drag_hint": "drag to move",
            "save_all": "SAVE ALL EXPORTS", "copyright_section": "© COPYRIGHT", "copyright_enable": "Enable",
            "font_px": "Font px:", "opacity": "Opacity:", "language_label": "🌐 Language:",
            "layer_firma": "SIGNATURE", "layer_rating": "RATING", "layer_cornice": "FRAME", "layer_extra": "EXTRA",
            "msg_success_title": "Success", "msg_success_body": "Exports saved!",
            "msg_error_title": "Error", "msg_unsupported_format_title": "Unsupported format",
            "msg_unsupported_format_body": "Format '{ext}' not supported.\nUse PNG, JPG, WEBP or BMP.",
            "msg_load_image_first": "Load an image first.",
        }

    def _ensure_default_lang_files(self):
        """Scrive Lang/it.json e Lang/en.json se non esistono già — servono anche da esempio
        per chi vuole aggiungere altre lingue (basta copiare un file e tradurre i valori)."""
        try:
            it_path = os.path.join(self.folder_lang, "it.json")
            en_path = os.path.join(self.folder_lang, "en.json")
            if not os.path.exists(it_path):
                with open(it_path, "w", encoding="utf-8") as f: json.dump(self.STRINGS_IT, f, ensure_ascii=False, indent=2)
            if not os.path.exists(en_path):
                with open(en_path, "w", encoding="utf-8") as f: json.dump(self._english_strings(), f, ensure_ascii=False, indent=2)
        except Exception:
            pass

    def _read_lang_config(self):
        try:
            if os.path.exists(self.path_lang_config):
                with open(self.path_lang_config, "r", encoding="utf-8") as f:
                    v = f.read().strip()
                    if v: return v
        except Exception:
            pass
        return "it"

    def _available_languages(self):
        try:
            return sorted([os.path.splitext(f)[0] for f in os.listdir(self.folder_lang) if f.lower().endswith(".json")])
        except Exception:
            return ["it", "en"]

    def _load_language(self, lang_code):
        """Carica le stringhe della lingua richiesta, con fallback sempre sull'italiano per le chiavi mancanti."""
        merged = dict(self.STRINGS_IT)
        lang_path = os.path.join(self.folder_lang, f"{lang_code}.json")
        if os.path.exists(lang_path):
            try:
                with open(lang_path, "r", encoding="utf-8") as f:
                    merged.update(json.load(f))
            except Exception:
                pass
        self.strings = merged
        self.current_lang = lang_code

    def tr(self, key):
        return self.strings.get(key, self.STRINGS_IT.get(key, key))

    def _mk(self, cls, parent, key, **kwargs):
        """Crea un widget con testo tradotto e lo registra per l'aggiornamento a runtime al cambio lingua."""
        w = cls(parent, text=self.tr(key), **kwargs)
        self.i18n_widgets.append((w, key))
        return w

    def change_language(self, e=None):
        lang_code = self.combo_lang.get()
        if not lang_code: return
        self._load_language(lang_code)
        for widget, key in self.i18n_widgets:
            try: widget.config(text=self.tr(key))
            except Exception: pass
        self.update_layer_panel()
        # pannelli ricostruiti dinamicamente: vanno ridisegnati per prendere la nuova lingua
        try: self._refresh_collage_list()
        except Exception: pass
        try: self._refresh_links_list()
        except Exception: pass
        try: self._refresh_presets_list()
        except Exception: pass
        try: self.notebook.tab(self.tab_settings, text=self.tr("s_tab"))
        except Exception: pass
        try: self._render_collage_preview()
        except Exception: pass
        # il toggle del mosaico ha due testi diversi a seconda dello stato
        try: self.btn_mosaic_toggle.config(text=self.tr("mosaic_on" if self.mosaic_mode else "mosaic_off"))
        except Exception: pass
        try:
            with open(self.path_lang_config, "w", encoding="utf-8") as f: f.write(lang_code)
        except Exception:
            pass

    @staticmethod
    def _comfy_workflow(info):
        """Il JSON di ComfyUI contenuto nell'immagine, oppure None.

        ComfyUI non scrive "parameters" come A1111/Forge, ma due blocchi JSON:
        "workflow" (il grafo completo: trascinando il file in ComfyUI si riapre così
        com'era) e "prompt" (formato API, più povero). Si preferisce "workflow".
        La struttura si controlla davvero, perché altri programmi usano la chiave
        "prompt" per del semplice testo."""
        for key in ("workflow", "prompt"):
            raw = info.get(key)
            if not raw: continue
            try:
                data = json.loads(raw) if isinstance(raw, (str, bytes)) else raw
            except Exception:
                continue
            if not isinstance(data, dict) or not data: continue
            if key == "workflow" and isinstance(data.get("nodes"), list):
                return data
            if key == "prompt" and any(isinstance(v, dict) and "class_type" in v for v in data.values()):
                return data
        return None

    def _write_comfy_json(self, data, path):
        with open(path, "w", encoding="utf-8") as f:
            json.dump(self._sanitize_comfy(data), f, ensure_ascii=False, indent=2)

    # --- filtri ignore_loras.txt / ignore_tags.txt applicati al workflow di ComfyUI ---
    def _read_blacklists(self):
        """(lora_bloccate, tag_bloccati). Le LoRA si normalizzano togliendo
        l'estensione, così in ignore_loras.txt vale sia "nome" sia "nome.safetensors"."""
        def leggi(p):
            return [l.strip().lower() for l in self._config_text(p).splitlines() if l.strip() and not l.strip().startswith("#")]
        loras = set()
        for l in leggi(self.path_ignore_loras):
            for ext in self.MODEL_EXTS:
                if l.endswith(ext): l = l[:-len(ext)]; break
            loras.add(l)
        return loras, leggi(self.path_ignore_tags)

    @staticmethod
    def _lora_name_of(value):
        """Solo il nome del file, senza cartelle né estensione:
        "Autore\\NSFW\\Lolity_v2.safetensors" -> "lolity_v2"."""
        base = re.split(r"[\\/]", str(value).strip())[-1]
        for ext in ImageProcessor.MODEL_EXTS:
            if base.lower().endswith(ext): return base[:-len(ext)].lower()
        return base.lower()

    @staticmethod
    def _is_model_path(s):
        return isinstance(s, str) and s.strip().lower().endswith(ImageProcessor.MODEL_EXTS)

    def _clean_comfy_text(self, text, tags, loras):
        """Toglie da un prompt i tag vietati e i richiami <lora:…> bloccati.
        Al contrario del txt, qui il testo si riapre in ComfyUI: quindi si lavora
        riga per riga e si riscrive una riga SOLO se le si toglie qualcosa, così
        a capo, spaziature e virgole originali restano come le avevi scritte."""
        righe = []
        for orig in text.split("\n"):
            riga = orig
            if loras:
                riga = re.sub(r"<lora:([^:>]+)(?::[^>]*)?>",
                              lambda mm: "" if self._lora_name_of(mm.group(1)) in loras else mm.group(0), riga, flags=re.I)
            parti = riga.split(",")
            tenute = [p for p in parti if not (tags and p.strip() and any(w in p.strip().lower() for w in tags))]
            if riga != orig or len(tenute) != len(parti):
                # qualcosa è stato tolto: niente virgole doppie rimaste al suo posto
                riga = ",".join(p for p in tenute if p.strip()).strip().strip(",").strip()
            righe.append(riga)
        return "\n".join(righe)

    def _sanitize_comfy(self, data):
        """Copia del workflow con ignore_loras.txt e ignore_tags.txt applicati.

        Si guarda la forma dei valori, non il nome del nodo, così funziona anche
        con loader che il programma non conosce:
        • un blocco {"lora": "percorso…", …} (Power Lora Loader di rgthree e simili)
          con una LoRA bloccata viene tolto per intero, forza compresa;
        • un percorso di LoRA scritto come stringa (LoraLoader, LoraLoaderModelOnly)
          viene svuotato: la posizione resta, perché lì conta l'ordine dei valori;
        • un testo che sembra un prompt viene ripulito dai tag vietati."""
        loras, tags = self._read_blacklists()
        if not loras and not tags: return data
        data = json.loads(json.dumps(data))           # copia: l'originale non si tocca

        def sistema(v, contesto):
            """(nuovo_valore, da_togliere)"""
            if isinstance(v, dict) and "lora" in v and v.get("lora") and self._lora_name_of(v["lora"]) in loras:
                return None, True
            if isinstance(v, str):
                if self._is_model_path(v):
                    if "lora" in contesto and self._lora_name_of(v) in loras: return "", False
                    return v, False
                if "," in v or "\n" in v or "textencode" in contesto or "prompt" in contesto:
                    return self._clean_comfy_text(v, tags, loras), False
            return v, False

        def sistema_contenitore(c, contesto):
            if isinstance(c, list):
                nuovo = []
                for v in c:
                    nv, via = sistema(v, contesto)
                    if not via: nuovo.append(nv)
                return nuovo
            if isinstance(c, dict):
                for k in list(c):
                    nv, via = sistema(c[k], contesto + " " + str(k).lower())
                    if via: del c[k]
                    else: c[k] = nv
            return c

        if isinstance(data.get("nodes"), list):            # formato "workflow"
            for nd in data["nodes"]:
                if isinstance(nd, dict) and "widgets_values" in nd:
                    nd["widgets_values"] = sistema_contenitore(nd["widgets_values"], str(nd.get("type", "")).lower())
        else:                                              # formato API ("prompt")
            for nd in data.values():
                if isinstance(nd, dict) and isinstance(nd.get("inputs"), dict):
                    sistema_contenitore(nd["inputs"], str(nd.get("class_type", "")).lower())
        return data

    def parse_metadata(self, info, include_footer=True):
        raw = info.get("parameters", "")
        if not raw: return "No metadata found."

        lora_blacklist = [l.strip().lower() for l in self._config_text(self.path_ignore_loras).splitlines() if l.strip() and not l.strip().startswith("#")]

        if "Steps:" in raw:
            parts = raw.split("Steps:"); p_part, t_part = parts[0].strip(), "Steps: " + parts[1].strip()
        else: p_part, t_part = raw, ""

        pos, neg = "", ""
        if self.sdnext_mode.get():
            sv = re.search(r"sv_prompt: \"(.*?)\"", t_part, re.I) or re.search(r"sv_prompt: ([^,]+)", t_part, re.I)
            pos = sv.group(1).strip() if sv else p_part
            if "Negative prompt:" in p_part: neg = p_part.split("Negative prompt:")[1].strip()
        else:
            if "Negative prompt:" in p_part:
                s = p_part.split("Negative prompt:"); pos, neg = s[0].strip(), s[1].strip()
            else: pos = p_part

        pos = re.sub(r'<lora:[^>]+>', '', pos).strip()
        pos = self.clean_prompt_tags(pos)
        neg = self.clean_prompt_tags(neg)

        m_list = []
        if t_part:
            mn = re.search(r"Model: ([^,]+)", t_part, re.I); mh = re.search(r"Model hash: ([a-f0-9]+)", t_part, re.I)
            if mn:
                m_hash = mh.group(1).strip() if mh else ""
                m_name = mn.group(1).strip()
                m_list.append(f"Model: {m_name} - Hash: {m_hash if m_hash else 'N/A'}")
                lnk = self._model_link(m_name, m_hash)
                if lnk: m_list.append(f"  {lnk}")
            # Refiner — scritto in modo diverso dal modello principale:
            # "Refiner: nome_del_modello [hash]", con l'hash fra parentesi quadre.
            rf = re.search(r"Refiner:\s*([^,]+)", t_part, re.I)
            if rf:
                raw = rf.group(1).strip()
                rh = re.search(r"\[([a-f0-9]+)\]\s*$", raw, re.I)
                r_hash = rh.group(1).strip() if rh else ""
                r_name = re.sub(r"\s*\[[a-f0-9]+\]\s*$", "", raw, flags=re.I).strip()
                if r_name:
                    m_list.append(f"Refiner: {r_name} - Hash: {r_hash if r_hash else 'N/A'}")
                    lnk = self._model_link(r_name, r_hash)
                    if lnk: m_list.append(f"  {lnk}")
            h_m = re.search(r"Hashes: (\{.*?\})", t_part)
            if h_m:
                try:
                    h_j = json.loads(h_m.group(1).replace("'", '"'))
                    for k, v in h_j.items():
                        if k.startswith("lora:"):
                            ln = k.replace("lora:", "").strip()
                            if ln.lower() not in lora_blacklist:
                                m_list.append(f"lora: {ln} - Hash: {v}")
                                lnk = self._model_link(ln, str(v).strip())
                                if lnk: m_list.append(f"  {lnk}")
                except: pass
        cp = t_part
        if self.param_filter.get():
            # modalità "tieni solo questi": la lista decide tutto, quindi modello,
            # hash e refiner spariscono da qui senza bisogno di regole dedicate
            cp = self._filter_params(cp)
        else:
            # nessun filtro: si toglie comunque ciò che è già stampato altrove
            # o che è pura ripetizione del prompt
            patterns = [r",?\s*sv_prompt: \".*?\"", r",?\s*sv_prompt: [^,]+", r",?\s*Model hash: [a-f0-9]+",
                        r",?\s*Model: [^,]+", r",?\s*Hashes: \{.*?\}", r",?\s*Lora hashes: \".*?\"",
                        # il refiner passa nei Models; "Refiner switch at" resta invece
                        # fra i parametri, perché serve a riprodurre la generazione
                        r",?\s*Refiner: [^,]+",
                        r",?\s*Hires prompt: \".*?\"", r",?\s*Hires negative prompt: \".*?\""]
            for pat in patterns:
                cp = re.sub(pat, "", cp, flags=re.I | re.S)
        
        # --- LOGICA FOOTER DINAMICO AVANZATO ---
        footer = self.get_footer_text() if include_footer else ""

        out = f"Positive Prompt:\n{pos}\n\nNegative Prompt:\n{neg if neg else 'None'}\n\nParameters:\n{cp.strip().strip(',')}\n\nModels:\n" + ("\n".join(m_list) if m_list else "None")
        if footer: out += f"\n\n---\n{footer}"
        return out

    # =========================================================
    # LIVELLI DI TESTO — motore condiviso Editor/Collage
    # =========================================================
    def _load_font(self, size):
        """Font TrueType alla dimensione richiesta, con cache (ricaricarlo a ogni frame è lento)."""
        size = max(1, int(size))
        if size in self._font_cache: return self._font_cache[size]
        f = None
        for cand in ("arial.ttf", "C:/Windows/Fonts/arial.ttf", "DejaVuSans.ttf",
                     "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"):
            try: f = ImageFont.truetype(cand, size); break
            except Exception: continue
        if f is None: f = ImageFont.load_default()
        self._font_cache[size] = f
        return f

    def new_text_layer(self):
        """Dict di un nuovo livello di testo con i valori di partenza."""
        self._text_uid += 1
        return {"uid": self._text_uid, "text": self.tr("t_placeholder"), "pos": (0.4, 0.45),
                "size": 48, "color": "#ffffff", "outline": 2, "opacity": 255,
                "rotation": 0, "visible": True, "target": "immagine", "align": "left"}

    # --- preset di testo (creati dal testo in uso, gestiti nelle Impostazioni) ---
    PRESET_KEYS = ("text", "size", "color", "outline", "opacity", "align", "rotation")

    def _load_text_presets(self):
        self.text_presets = []
        try:
            if os.path.exists(self.path_text_presets):
                with open(self.path_text_presets, "r", encoding="utf-8") as f: data = json.load(f)
                if isinstance(data, list):
                    for d in data:
                        if not str(d.get("name", "")).strip(): continue
                        p = {"name": str(d["name"]).strip()}
                        for k in self.PRESET_KEYS: p[k] = d.get(k)
                        self.text_presets.append(p)
        except Exception:
            self.text_presets = []

    def _save_text_presets(self):
        try:
            with open(self.path_text_presets, "w", encoding="utf-8") as f:
                json.dump(self.text_presets, f, ensure_ascii=False, indent=2)
        except Exception as ex:
            messagebox.showerror("Preset", str(ex))

    def _preset_names(self):
        return [p["name"] for p in self.text_presets]

    def _refresh_preset_ui(self):
        """Riallinea i menu a tendina dei preset e la lista nelle Impostazioni."""
        names = self._preset_names()
        for combo in ("combo_presets", "combo_cpresets"):
            c = getattr(self, combo, None)
            if c is not None:
                cur = c.get(); c["values"] = names
                if cur not in names: c.set("")
        self._refresh_presets_list()

    def save_text_as_preset(self, from_collage=False):
        """Salva il testo attualmente selezionato come preset riutilizzabile."""
        t = self._sel_collage_text() if from_collage else self._sel_text()
        if t is None:
            messagebox.showwarning(self.tr("p_presets"), self.tr("t_none")); return
        name = simpledialog.askstring(self.tr("p_presets"), self.tr("p_name"), parent=self.root)
        if not name or not name.strip(): return
        name = name.strip()
        p = {"name": name}
        for k in self.PRESET_KEYS: p[k] = t.get(k)
        for i, old in enumerate(self.text_presets):      # stesso nome = aggiorna
            if old["name"].lower() == name.lower(): self.text_presets[i] = p; break
        else:
            self.text_presets.append(p)
        self._save_text_presets(); self._refresh_preset_ui()
        messagebox.showinfo(self.tr("p_presets"), f"'{name}' ✓")

    def _preset_by_name(self, name):
        return next((p for p in self.text_presets if p["name"] == name), None)

    def apply_text_preset(self, from_collage=False):
        """Richiama un preset: crea SEMPRE un nuovo livello di testo già impostato."""
        combo = self.combo_cpresets if from_collage else self.combo_presets
        p = self._preset_by_name(combo.get())
        if p is None: return
        t = self.new_text_layer()
        for k in self.PRESET_KEYS:
            if p.get(k) is not None: t[k] = p[k]
        if from_collage:
            t.pop("target", None)
            self.collage_texts.append(t); self.collage_text_sel = t["uid"]
            self._sync_collage_text_controls(); self._render_collage_preview()
        else:
            self.texts.append(t); self.selected_layer = self._text_tag(t)
            self.draw_text_layer(t); self.update_layer_panel(); self._sync_text_controls()

    def _render_text_img(self, t, scale=1.0):
        """Immagine RGBA del testo (contorno + opacità + rotazione), o None se vuoto.
        'size' e 'outline' sono in pixel dell'immagine FINALE: 'scale' li riporta alla
        risoluzione richiesta, così l'anteprima e il file salvato coincidono."""
        txt = (t.get("text") or "").replace("\\n", "\n")
        if not txt.strip(): return None
        size = max(1, int(round(t.get("size", 48) * scale)))
        font = self._load_font(size)
        sw = max(0, int(round(t.get("outline", 0) * scale)))
        op = max(0, min(255, int(t.get("opacity", 255))))
        try: rgb = ImageColor.getrgb(t.get("color", "#ffffff"))
        except Exception: rgb = (255, 255, 255)
        align = t.get("align", "left")
        if align not in ("left", "center", "right"): align = "left"
        probe = ImageDraw.Draw(Image.new("RGBA", (1, 1)))
        try: bb = probe.textbbox((0, 0), txt, font=font, stroke_width=sw, align=align)
        except TypeError: bb = probe.textbbox((0, 0), txt, font=font)   # Pillow senza stroke/align
        # con align center/right textbbox può restituire float: Image.new vuole interi
        w = max(1, int(math.ceil(bb[2] - bb[0])) + 2)
        h = max(1, int(math.ceil(bb[3] - bb[1])) + 2)
        img = Image.new("RGBA", (w, h), (0, 0, 0, 0))
        d = ImageDraw.Draw(img)
        kw = {"font": font, "fill": rgb + (op,), "align": align}
        if sw: kw.update({"stroke_width": sw, "stroke_fill": (0, 0, 0, op)})
        d.text((-bb[0] + 1, -bb[1] + 1), txt, **kw)
        rot = int(t.get("rotation", 0) or 0)
        if rot: img = img.rotate(rot, expand=True, resample=Image.Resampling.BICUBIC)
        return img

    def _paste_text_layer(self, target_img, t, pos_xy, scale):
        """Incolla un livello di testo su target_img in (x,y) px. Ritorna il rect o None."""
        im = self._render_text_img(t, scale)
        if im is None: return None
        x, y = int(pos_xy[0]), int(pos_xy[1])
        target_img.paste(im, (x, y), im)
        return (x, y, x + im.width, y + im.height)

    def civitai_link(self, h):
        """Link di ricerca su Civitai per un hash di modello/lora."""
        return f"https://civitai.red/search/models?sortBy=models_v9&query={h}"

    # --- link personalizzati ai modelli (tab Impostazioni) ---
    MODEL_EXTS = (".safetensors", ".ckpt", ".pt", ".pth", ".bin", ".sft")

    # =========================================================
    # FILTRO DEI PARAMETRI — decide cosa finisce sotto "Parameters:"
    # =========================================================
    @staticmethod
    def _split_params(text):
        """Spezza la riga dei parametri in [(chiave, pezzo_intero), …].

        Non si può usare un semplice split(","): alcuni valori contengono virgole
        al loro interno — Hashes: {…}, Lora hashes: "…", ADetailer prompt: "a, b".
        Quindi si taglia solo sulle virgole fuori da virgolette e graffe."""
        pezzi, buf, q, depth = [], "", False, 0
        for ch in text:
            if ch == '"': q = not q
            elif not q and ch in "{[": depth += 1
            elif not q and ch in "}]": depth = max(0, depth - 1)
            if ch == "," and not q and depth == 0:
                pezzi.append(buf); buf = ""
            else:
                buf += ch
        if buf.strip(): pezzi.append(buf)
        out = []
        for p in pezzi:
            s = p.strip()
            if not s: continue
            k = s.split(":", 1)[0].strip() if ":" in s else s
            out.append((k, s))
        return out

    def _param_kept(self, key):
        """True se il parametro va tenuto. Confronto senza distinzione fra
        maiuscole e minuscole, con jolly * e ? come per i link ai modelli."""
        k = key.strip().lower()
        for pat in self.keep_params:
            p = pat.strip().lower()
            if not p: continue
            if ("*" in p or "?" in p):
                if fnmatch.fnmatch(k, p): return True
            elif k == p:
                return True
        return False

    def _filter_params(self, text):
        """Tiene solo i parametri scelti, nell'ordine in cui li scrive il webui.
        Quelli assenti dai metadati semplicemente non compaiono: non si inventano
        righe vuote."""
        tenuti = [s for k, s in self._split_params(text) if self._param_kept(k)]
        return ", ".join(tenuti)

    def _param_catalog_values(self):
        """Voci del menu a tendina, raggruppate e senza quelle già in lista."""
        attivi = {p.strip().lower() for p in self.keep_params}
        out = []
        for gruppo, nomi in PARAM_CATALOG.items():
            for n in nomi:
                if n.strip().lower() not in attivi:
                    out.append(f"{gruppo}  ›  {n}")
        return out

    def _refresh_param_combo(self):
        if hasattr(self, "combo_param_add"):
            self.combo_param_add["values"] = self._param_catalog_values()
            self.combo_param_add.set("")

    def _refresh_params_list(self):
        C = self.C
        if not hasattr(self, "params_list_frame"): return
        for w in self.params_list_frame.winfo_children(): w.destroy()
        if not self.keep_params:
            tk.Label(self.params_list_frame, text=self.tr("p_empty"), bg=C["card"], fg=C["faint"],
                     font=(self.FONT, 8), justify=tk.LEFT, wraplength=250).pack(anchor="w")
            return
        for nome in self.keep_params:
            row = tk.Frame(self.params_list_frame, bg=C["card_hd"]); row.pack(fill=tk.X, pady=1)
            jolly = "*" in nome or "?" in nome
            tk.Label(row, text=nome, bg=C["card_hd"], fg=C["amber"] if jolly else C["text"],
                     font=(self.MONO, 8), anchor="w").pack(side=tk.LEFT, fill=tk.X, expand=True, padx=8, pady=2)
            b = tk.Label(row, text="✕", bg=C["card_hd"], fg=C["red_hi"], font=(self.FONT, 9, "bold"),
                         width=3, cursor="hand2")
            b.pack(side=tk.RIGHT); b.bind("<Button-1>", lambda ev, n=nome: self.remove_param(n))

    def _params_changed(self):
        self._save_keep_params(); self._refresh_params_list(); self._refresh_param_combo()

    def _param_filter_changed(self):
        self._save_keep_params()

    def _add_param(self, nome):
        nome = (nome or "").strip()
        if not nome: return False
        if any(p.strip().lower() == nome.lower() for p in self.keep_params): return False
        self.keep_params.append(nome); return True

    def add_param_from_combo(self):
        v = self.combo_param_add.get()
        if "›" in v: v = v.split("›", 1)[1]
        if self._add_param(v): self._params_changed()

    def add_param_custom(self):
        if self._add_param(self.entry_param_custom.get()):
            self.entry_param_custom.delete(0, tk.END); self._params_changed()

    def add_params_from_image(self):
        """Legge i parametri realmente presenti nell'immagine caricata e li
        aggiunge alla lista. Serve per le estensioni che non sono nel catalogo:
        invece di indovinare il nome esatto, lo si prende dai metadati veri."""
        raw = (getattr(self, "info_buffer", None) or {}).get("parameters", "")
        if not raw:
            messagebox.showinfo(self.tr("p_section"), self.tr("p_no_image")); return
        t_part = ("Steps: " + raw.split("Steps:")[1]) if "Steps:" in raw else ""
        trovati = [k for k, _ in self._split_params(t_part) if k]
        nuovi = [k for k in trovati if not any(p.strip().lower() == k.lower() for p in self.keep_params)]
        if not nuovi:
            messagebox.showinfo(self.tr("p_section"), self.tr("p_nothing_new")); return
        if not messagebox.askyesno(self.tr("p_section"),
                                   self.tr("p_add_found").format(n=len(nuovi), l="\n• ".join([""] + nuovi))):
            return
        for k in nuovi: self._add_param(k)
        self._params_changed()

    def remove_param(self, nome):
        self.keep_params = [p for p in self.keep_params if p != nome]
        self._params_changed()

    def reset_params(self):
        self.keep_params = list(DEFAULT_KEEP_PARAMS); self._params_changed()

    def clear_params(self):
        self.keep_params = []; self._params_changed()

    def _load_keep_params(self):
        self.keep_params = list(DEFAULT_KEEP_PARAMS)
        try:
            if os.path.exists(self.path_keep_params):
                with open(self.path_keep_params, "r", encoding="utf-8") as f:
                    data = json.load(f)
                if isinstance(data, dict):
                    if isinstance(data.get("keep"), list):
                        self.keep_params = [str(x) for x in data["keep"] if str(x).strip()]
                    self._param_filter_saved = bool(data.get("enabled", True))
        except Exception:
            pass

    def _save_keep_params(self):
        try:
            with open(self.path_keep_params, "w", encoding="utf-8") as f:
                json.dump({"enabled": bool(self.param_filter.get()), "keep": self.keep_params},
                          f, ensure_ascii=False, indent=2)
        except Exception:
            pass

    def _link_key(self, name):
        """Normalizza il nome di un modello/lora per il confronto: minuscolo, senza estensione.
        NB: si tolgono solo le estensioni note — con os.path.splitext un nome tipo
        'modello_v1.5' verrebbe troncato a 'modello_v1'."""
        n = str(name or "").strip().strip('"').lower()
        for e in self.MODEL_EXTS:
            if n.endswith(e): n = n[:-len(e)]; break
        return n.strip()

    # =========================================================
    # AGGIORNAMENTI — controllo su GitHub Releases
    # =========================================================
    @staticmethod
    def _version_tuple(v):
        """'v2.26.1' -> (2, 26, 1). Serve a confrontare le versioni come numeri,
        altrimenti '2.9' risulterebbe maggiore di '2.10'."""
        nums = re.findall(r"\d+", str(v or ""))
        return tuple(int(n) for n in nums) if nums else (0,)

    def check_updates_async(self, manual=False):
        """Interroga GitHub in un thread separato: l'avvio non deve mai restare
        appeso per colpa della rete.

        Il thread NON tocca né i widget né Tk: deposita il risultato in una coda,
        e il thread principale la controlla con after(). Chiamare root.after() dal
        thread di lavoro sembrerebbe più semplice, ma Tk non è thread-safe e quella
        chiamata può essere ignorata senza dare errore — l'avviso non comparirebbe."""
        if not hasattr(self, "_update_q"):
            self._update_q = queue.Queue()
        def worker():
            info, err = None, None
            try:
                req = urllib.request.Request(GITHUB_RELEASES_API,
                    headers={"User-Agent": f"AI-Visual-Editor/{APP_VERSION}", "Accept": "application/vnd.github+json"})
                with urllib.request.urlopen(req, timeout=8) as r:
                    data = json.loads(r.read().decode("utf-8"))
                info = {"tag": str(data.get("tag_name") or "").strip(),
                        "name": str(data.get("name") or "").strip(),
                        "notes": str(data.get("body") or "").strip(),
                        "url": str(data.get("html_url") or GITHUB_RELEASES_PAGE)}
            except Exception as ex:
                err = str(ex)
            self._update_q.put((info, err, manual))
        threading.Thread(target=worker, daemon=True).start()
        self._poll_update_result(deadline=time.time() + 30)

    def _poll_update_result(self, deadline):
        """Controlla la coda dal thread principale, finché arriva il risultato
        o scade il tempo (così non si continua a controllare all'infinito)."""
        try:
            info, err, manual = self._update_q.get_nowait()
        except queue.Empty:
            if time.time() < deadline:
                self.root.after(200, lambda: self._poll_update_result(deadline))
            return
        self._on_update_checked(info, err, manual)

    def _on_update_checked(self, info, err, manual):
        """Gira nel thread della UI: qui si può toccare l'interfaccia."""
        if err or not info or not info.get("tag"):
            if manual: messagebox.showinfo(self.tr("u_section"), self.tr("u_check_failed"))
            return
        newer = self._version_tuple(info["tag"]) > self._version_tuple(APP_VERSION)
        self._update_info = info if newer else None
        if newer:
            self._show_update_banner(info)
        elif manual:
            messagebox.showinfo(self.tr("u_section"), self.tr("u_up_to_date").format(v=APP_VERSION))

    def _show_update_banner(self, info):
        """Striscia cliccabile in cima alla sidebar dell'Editor."""
        if getattr(self, "_update_banner", None) is not None: return
        C = self.C
        b = tk.Frame(self.editor_top_holder, bg=C["amber"])
        b.pack(fill=tk.X, before=None)
        lbl = tk.Label(b, text=self.tr("u_available").format(v=info["tag"]), bg=C["amber"], fg="#2a1f05",
                       font=(self.FONT, 9, "bold"), cursor="hand2", pady=6)
        lbl.pack(side=tk.LEFT, padx=(12, 4))
        lbl.bind("<Button-1>", lambda e: self.run_update())
        x = tk.Label(b, text="✕", bg=C["amber"], fg="#2a1f05", font=(self.FONT, 9, "bold"), cursor="hand2", padx=10)
        x.pack(side=tk.RIGHT); x.bind("<Button-1>", lambda e: self._dismiss_update_banner())
        self._update_banner = b

    def _dismiss_update_banner(self):
        if getattr(self, "_update_banner", None) is not None:
            self._update_banner.destroy(); self._update_banner = None

    def run_update(self):
        """Scarica la nuova versione, la verifica, salva una copia di sicurezza
        della corrente e la sostituisce. Non riavvia da solo: lo decide l'utente."""
        info = getattr(self, "_update_info", None)
        if not info:
            self.open_releases_page(); return
        if getattr(sys, "frozen", False):
            # eseguibile impacchettato: non ha senso riscrivere il .py
            messagebox.showinfo(self.tr("u_section"), self.tr("u_frozen"))
            self.open_releases_page(); return
        target = os.path.join(self.base_path, MAIN_SCRIPT_NAME)
        if not os.path.exists(target):
            messagebox.showerror(self.tr("u_section"), self.tr("u_not_found").format(f=MAIN_SCRIPT_NAME)); return
        if not messagebox.askyesno(self.tr("u_section"), self.tr("u_confirm").format(v=info["tag"])): return
        url = f"https://raw.githubusercontent.com/{GITHUB_REPO}/{info['tag']}/{MAIN_SCRIPT_NAME}"
        try:
            req = urllib.request.Request(url, headers={"User-Agent": f"AI-Visual-Editor/{APP_VERSION}"})
            with urllib.request.urlopen(req, timeout=20) as r:
                raw = r.read()
        except Exception as ex:
            messagebox.showerror(self.tr("u_section"), f"{self.tr('u_download_failed')}\n\n{ex}"); return
        # --- verifiche prima di toccare qualsiasi cosa ---
        try:
            src = raw.decode("utf-8")
        except Exception:
            messagebox.showerror(self.tr("u_section"), self.tr("u_invalid")); return
        if len(raw) < 50_000 or "class ImageProcessor" not in src:
            messagebox.showerror(self.tr("u_section"), self.tr("u_invalid")); return
        try:
            compile(src, MAIN_SCRIPT_NAME, "exec")     # deve essere Python valido
        except SyntaxError:
            messagebox.showerror(self.tr("u_section"), self.tr("u_invalid")); return
        # --- copia di sicurezza, poi sostituzione ---
        backup = os.path.join(self.base_path, f"processore_immagini_backup_v{APP_VERSION}.py")
        try:
            with open(target, "r", encoding="utf-8") as f: old = f.read()
            with open(backup, "w", encoding="utf-8", newline="") as f: f.write(old)
            with open(target, "w", encoding="utf-8", newline="") as f: f.write(src)
        except Exception as ex:
            messagebox.showerror(self.tr("u_section"), f"{self.tr('u_write_failed')}\n\n{ex}"); return
        self._dismiss_update_banner()
        messagebox.showinfo(self.tr("u_section"),
            self.tr("u_done").format(v=info["tag"], b=os.path.basename(backup)))

    def open_releases_page(self):
        import webbrowser
        try: webbrowser.open(GITHUB_RELEASES_PAGE)
        except Exception: pass

    # --- opzioni persistenti (settings.json) ---
    def _load_settings(self):
        self._text_paths = {"ignore_tags": self.path_ignore_tags, "ignore_loras": self.path_ignore_loras,
                            "footer_note": self.path_footer_note, "copyright": self.path_copyright}
        self.config_texts = {}
        for key, path in self._text_paths.items():
            try:
                with open(path, "r", encoding="utf-8-sig") as f: self.config_texts[key] = f.read()
            except OSError:
                self.config_texts[key] = ""
        try:
            if not os.path.exists(self.path_settings): return
            with open(self.path_settings, "r", encoding="utf-8") as f: data = json.load(f)
            for key, value in data.get("texts", {}).items():
                if key in self.config_texts and isinstance(value, str): self.config_texts[key] = value
            for k, v in self._settings_vars.items():
                if k in data:
                    try: v.set(bool(data[k]))
                    except Exception: pass
        except Exception:
            pass   # file assente o corrotto: si resta ai valori di default

    def _save_settings(self):
        try:
            out = {}
            out["texts"] = self.config_texts.copy()
            for k, v in self._settings_vars.items():
                try: out[k] = bool(v.get())
                except Exception: pass
            with open(self.path_settings, "w", encoding="utf-8") as f:
                json.dump(out, f, ensure_ascii=False, indent=2)
        except Exception:
            pass

    def _config_text(self, path):
        for key, source in self._text_paths.items():
            if source == path: return self.config_texts.get(key, "")
        return ""

    def _load_model_links(self):
        """Carica model_links.json. Accetta sia la lista [{name,url}] sia un dict {nome: url}."""
        self.model_links = []
        try:
            if os.path.exists(self.path_model_links):
                with open(self.path_model_links, "r", encoding="utf-8") as f: data = json.load(f)
                if isinstance(data, list):
                    self.model_links = [{"name": str(d.get("name", "")).strip(), "url": str(d.get("url", "")).strip()}
                                        for d in data if str(d.get("name", "")).strip() and str(d.get("url", "")).strip()]
                elif isinstance(data, dict):
                    self.model_links = [{"name": str(k).strip(), "url": str(v).strip()} for k, v in data.items() if str(v).strip()]
        except Exception:
            self.model_links = []
        self._reindex_links()

    def _reindex_links(self):
        self._links_index = {self._link_key(e["name"]): e["url"] for e in self.model_links}

    def _save_model_links(self):
        try:
            with open(self.path_model_links, "w", encoding="utf-8") as f:
                json.dump(self.model_links, f, ensure_ascii=False, indent=2)
        except Exception as ex:
            messagebox.showerror("Impostazioni", str(ex))

    def _lookup_link(self, key):
        """URL associato a un nome normalizzato, o None.
        Prima la corrispondenza esatta; poi i pattern con jolly (`*` e `?`), così
        'ZipZap_OC_Ill_V*' copre tutte le versioni senza reinserire il link ogni volta.
        Tra più pattern che combaciano vince il PIÙ LUNGO, cioè il più specifico:
        'ZipZap_OC_Ill_V*' batte 'ZipZap_*'."""
        if key in self._links_index: return self._links_index[key]
        best_pat = best_url = None
        for pat, url in self._links_index.items():
            if ("*" in pat or "?" in pat) and fnmatch.fnmatchcase(key, pat):
                if best_pat is None or len(pat) > len(best_pat): best_pat, best_url = pat, url
        return best_url

    def _model_link(self, name, h):
        """Link da stampare sotto un modello/lora, o None.
        Un modello presente in tabella è per definizione 'non su Civitai': mostra il link
        personalizzato se abilitato, e NON ripiega mai sulla ricerca Civitai."""
        url = self._lookup_link(self._link_key(name))
        if url is not None:
            return url if self.custom_links.get() else None
        return self.civitai_link(h) if (h and self.civitai_links.get()) else None

    def get_footer_text(self):
        """Footer dinamico da footer_note.txt con segnaposto {NAME} {YEAR} {DATE} {HOURS}."""
        footer = ""
        footer = self._config_text(self.path_footer_note).strip()
        if footer:
            now = datetime.now()
            footer = footer.replace("{NAME}", self.current_signature_name)
            footer = footer.replace("{YEAR}", now.strftime("%Y"))
            footer = footer.replace("{DATE}", now.strftime("%d/%m/%Y"))
            footer = footer.replace("{HOURS}", now.strftime("%H:%M"))
        return footer

    def get_copyright_text(self):
        """Legge copyright.txt e sostituisce i segnaposto {NAME}, {DATE}, {YEAR}."""
        try:
            text = self._config_text(self.path_copyright).strip()
            now = __import__("datetime").datetime.now()
            text = text.replace("{NAME}", self.current_signature_name)
            text = text.replace("{DATE}", now.strftime("%d/%m/%Y"))
            text = text.replace("{YEAR}", now.strftime("%Y"))
            return text
        except: return ""

    def change_signature(self, e=None):
        sel = self.combo_firme.get()
        if sel:
            self.current_signature_name = os.path.splitext(sel)[0]
            self.current_account_name = self.current_signature_name
            self.raw_assets["firma"] = Image.open(os.path.join(self.folder_firme, sel)).convert("RGBA")
            if self.state["firma"]["pos"]: self.draw_element("firma")
            self.update_layer_panel()
            self.draw_all_layers()  # aggiorna anteprima copyright con nuovo nome

    # --- UI E RENDERING (Stabile) ---
    def _update_zoom_label(self):
        if hasattr(self, "lbl_zoom_pct"):
            self.lbl_zoom_pct.config(text=f"{int(self.view_zoom*100)}%")

    def _on_canvas_ctrl_scroll(self, event):
        self.zoom_canvas(1.15 if event.delta > 0 else 1/1.15)

    def zoom_canvas(self, factor=None, reset=False):
        """Zoom SOLO visivo/di lavoro sul canvas principale: permette di posizionare i layer con
        più precisione. Non influisce in alcun modo sul file salvato (l'export usa sempre
        self.base_ratio, fisso, indipendente dallo zoom corrente)."""
        if not self.orig_img: return
        old_w, old_h = self.img_w, self.img_h
        if reset: self.view_zoom = 1.0
        else: self.view_zoom = max(0.25, min(6.0, self.view_zoom * factor))
        ow, oh = self.orig_img.size
        self.ratio = self.base_ratio * self.view_zoom
        self.img_w, self.img_h = max(1, int(ow * self.ratio)), max(1, int(oh * self.ratio))
        # riproporziona la posizione assoluta (in pixel canvas) del seed id sulla nuova scala
        if old_w and old_h:
            fx = self.seed_id_pos[0] / old_w; fy = self.seed_id_pos[1] / old_h
            self.seed_id_pos = (fx * self.img_w, fy * self.img_h)
        self.canvas.config(scrollregion=(0, 0, self.img_w, self.img_h))
        self._update_zoom_label()
        self.refresh_canvas_bg()

    def _on_sidebar_mousewheel(self, event):
        self.sidebar_canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")

    def _on_collage_side_mousewheel(self, event):
        self.collage_side_canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")

    # =========================================================
    # STILE MODERNO / HELPER UI
    # =========================================================
    def _setup_style(self):
        """Configura ttk (combobox) per il tema dark moderno."""
        style = ttk.Style()
        try: style.theme_use("clam")
        except Exception: pass
        C = self.C
        style.configure("Dark.TCombobox",
            fieldbackground=C["input"], background=C["input"], foreground=C["text"],
            arrowcolor=C["muted"], bordercolor=C["input_bd"], lightcolor=C["input_bd"],
            darkcolor=C["input_bd"], insertcolor=C["text"], relief="flat", padding=5)
        style.map("Dark.TCombobox",
            fieldbackground=[("readonly", C["input"]), ("focus", C["input"])],
            foreground=[("readonly", C["text"])],
            bordercolor=[("focus", C["accent"])],
            selectbackground=[("readonly", C["input"])],
            selectforeground=[("readonly", C["text"])],
            arrowcolor=[("active", C["text"])])
        self.root.option_add("*TCombobox*Listbox.background", C["card_hd"])
        self.root.option_add("*TCombobox*Listbox.foreground", C["text"])
        self.root.option_add("*TCombobox*Listbox.selectBackground", C["accent"])
        self.root.option_add("*TCombobox*Listbox.selectForeground", "#ffffff")
        self.root.option_add("*TCombobox*Listbox.font", (self.FONT, 9))
        self.root.option_add("*TCombobox*Listbox.borderWidth", 0)
        # --- Notebook (tab) ---
        style.configure("Dark.TNotebook", background=C["bg"], borderwidth=0, tabmargins=(6, 6, 6, 0))
        style.configure("Dark.TNotebook.Tab", background=C["sidebar"], foreground=C["muted"],
            padding=(20, 9), font=(self.FONT, 10, "bold"), borderwidth=0)
        style.map("Dark.TNotebook.Tab",
            background=[("selected", C["card"]), ("active", C["card_hd"])],
            foreground=[("selected", C["text"])])

    def _combo(self, parent, **kw):
        return ttk.Combobox(parent, state="readonly", style="Dark.TCombobox", **kw)

    def _spin(self, parent, **kw):
        return tk.Spinbox(parent, bg=self.C["input"], fg=self.C["text"],
            buttonbackground=self.C["card_hd"], relief="flat", highlightthickness=1,
            highlightbackground=self.C["input_bd"], highlightcolor=self.C["accent"],
            insertbackground=self.C["text"], font=(self.FONT, 9), **kw)

    def _card(self, parent, title_key=None, title_text=None, accent=None):
        """Crea una 'card' con header colorato; restituisce il body dove impilare i widget."""
        accent = accent or self.C["accent"]
        outer = tk.Frame(parent, bg=self.C["card"], highlightbackground=self.C["line"],
            highlightthickness=1, bd=0)
        outer.pack(fill=tk.X, padx=12, pady=6)
        hd = tk.Frame(outer, bg=self.C["card"]); hd.pack(fill=tk.X, padx=12, pady=(10, 2))
        bar = tk.Frame(hd, bg=accent, width=4, height=13); bar.pack(side=tk.LEFT, padx=(0, 8)); bar.pack_propagate(False)
        if title_key is not None:
            self._mk(tk.Label, hd, title_key, bg=self.C["card"], fg=self.C["text"], font=(self.FONT, 9, "bold")).pack(side=tk.LEFT)
        elif title_text is not None:
            tk.Label(hd, text=title_text, bg=self.C["card"], fg=self.C["text"], font=(self.FONT, 9, "bold")).pack(side=tk.LEFT)
        body = tk.Frame(outer, bg=self.C["card"]); body.pack(fill=tk.X, padx=12, pady=(4, 12))
        return body

    def _mbtn(self, parent, key=None, text=None, command=None, kind="normal", **kw):
        """Bottone piatto moderno con effetto hover."""
        palette = {
            "normal":  (self.C["card_hd"], "#3a4152", self.C["text"]),
            "primary": (self.C["accent"], self.C["accent_hi"], "#ffffff"),
            "success": (self.C["green"], self.C["green_hi"], "#08251b"),
            "danger":  (self.C["red"], self.C["red_hi"], "#2c0d0d"),
            "amber":   (self.C["amber"], "#fcd34d", "#2a1f05"),
            "violet":  (self.C["accent"], self.C["accent_hi"], "#ffffff"),
        }
        base, hov, fg = palette.get(kind, palette["normal"])
        label = text if text is not None else self.tr(key)
        font = kw.pop("font", (self.FONT, 9, "bold"))
        b = tk.Button(parent, text=label, command=command, bg=base, fg=fg,
            activebackground=hov, activeforeground=fg, relief="flat", bd=0,
            cursor="hand2", font=font, highlightthickness=0, padx=10, pady=6, **kw)
        b.bind("<Enter>", lambda e: b.config(bg=hov))
        b.bind("<Leave>", lambda e: b.config(bg=base))
        if key is not None: self.i18n_widgets.append((b, key))
        return b

    def _iconbtn(self, parent, text, command):
        """Bottoncino quadrato per +/-/rotazione/zoom con hover."""
        b = tk.Button(parent, text=text, command=command, bg=self.C["card_hd"],
            fg=self.C["text"], activebackground=self.C["accent"], activeforeground="#ffffff",
            relief="flat", bd=0, cursor="hand2", width=3, font=(self.FONT, 12, "bold"), highlightthickness=0)
        b.bind("<Enter>", lambda e: b.config(bg=self.C["accent"], fg="#ffffff"))
        b.bind("<Leave>", lambda e: b.config(bg=self.C["card_hd"], fg=self.C["text"]))
        return b

    def setup_ui(self):
        self._setup_style()
        C = self.C
        # ---------- TAB / NOTEBOOK ----------
        self.notebook = ttk.Notebook(self.root, style="Dark.TNotebook")
        self.notebook.pack(fill=tk.BOTH, expand=True)
        self.tab_editor = tk.Frame(self.notebook, bg=C["bg"])
        self.tab_collage = tk.Frame(self.notebook, bg=C["bg"])
        self.tab_settings = tk.Frame(self.notebook, bg=C["bg"])
        self.notebook.add(self.tab_editor, text="  🎨  Editor  ")
        self.notebook.add(self.tab_collage, text="  🖼  Collage  ")
        self.notebook.add(self.tab_settings, text=self.tr("s_tab"))
        # ---------- SIDEBAR SCROLLABILE (tab Editor) ----------
        self.sidebar_container = tk.Frame(self.tab_editor, width=430, bg=C["sidebar"]); self.sidebar_container.pack(side=tk.RIGHT, fill=tk.Y); self.sidebar_container.pack_propagate(False)
        # il pulsante di salvataggio sta FUORI dall'area di scorrimento: sempre raggiungibile.
        # Va impacchettato PRIMA di canvas/scrollbar, altrimenti non si riserva la striscia in basso.
        # barra fissa in ALTO: titolo + caricamento immagine (è la prima cosa che si usa,
        # non deve finire in fondo alla lista man mano che si aggiungono card)
        self.editor_top_holder = tk.Frame(self.sidebar_container, bg=C["sidebar"]); self.editor_top_holder.pack(side=tk.TOP, fill=tk.X)
        self.editor_save_holder = tk.Frame(self.sidebar_container, bg=C["sidebar"]); self.editor_save_holder.pack(side=tk.BOTTOM, fill=tk.X)
        self.sidebar_canvas = tk.Canvas(self.sidebar_container, bg=C["sidebar"], highlightthickness=0)
        self.sidebar_scrollbar = tk.Scrollbar(self.sidebar_container, orient=tk.VERTICAL, command=self.sidebar_canvas.yview,
            bg=C["card_hd"], troughcolor=C["sidebar"], activebackground=C["accent"], bd=0, relief="flat", width=10)
        self.sidebar_canvas.configure(yscrollcommand=self.sidebar_scrollbar.set)
        self.sidebar_scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        self.sidebar_canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        self.sidebar = tk.Frame(self.sidebar_canvas, bg=C["sidebar"])
        self._sidebar_window = self.sidebar_canvas.create_window((0, 0), window=self.sidebar, anchor="nw", width=406)
        self.sidebar.bind("<Configure>", lambda e: self.sidebar_canvas.configure(scrollregion=self.sidebar_canvas.bbox("all")))
        self.sidebar_canvas.bind("<Enter>", lambda e: self.sidebar_canvas.bind_all("<MouseWheel>", self._on_sidebar_mousewheel))
        self.sidebar_canvas.bind("<Leave>", lambda e: self.sidebar_canvas.unbind_all("<MouseWheel>"))
        self.sidebar_canvas.bind_all("<Button-4>", lambda e: self.sidebar_canvas.yview_scroll(-2, "units") if str(e.widget).startswith(str(self.sidebar_canvas)) else None)
        self.sidebar_canvas.bind_all("<Button-5>", lambda e: self.sidebar_canvas.yview_scroll(2, "units") if str(e.widget).startswith(str(self.sidebar_canvas)) else None)

        # ---------- BARRA FISSA IN ALTO ---------- (la scelta lingua è nella tab Impostazioni)
        header = tk.Frame(self.editor_top_holder, bg=C["sidebar"]); header.pack(fill=tk.X, padx=14, pady=(14, 6))
        tk.Label(header, text="✦ AI VISUAL EDITOR", bg=C["sidebar"], fg=C["text"], font=(self.FONT, 13, "bold")).pack(side=tk.LEFT)
        load_hide_row = tk.Frame(self.editor_top_holder, bg=C["sidebar"]); load_hide_row.pack(fill=tk.X, padx=14, pady=(0, 10))
        self._mbtn(load_hide_row, "load_image", command=self.load_image, kind="primary").pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 3), ipady=3)
        self._mbtn(load_hide_row, "hide_preview", command=self.toggle_preview_visibility, kind="violet").pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(3, 0), ipady=3)
        tk.Frame(self.editor_top_holder, bg=C["line"], height=1).pack(fill=tk.X)

        # ---------- CARD: LAYERS ----------
        body = self._card(self.sidebar, "layers_control", accent=C["amber"])
        self.layer_ui_frame = tk.Frame(body, bg=C["card"]); self.layer_ui_frame.pack(fill=tk.X)
        self._mk(tk.Label, body, "transform", bg=C["card"], fg=C["muted"], font=(self.FONT, 8)).pack(anchor="w", pady=(10, 2))
        btn_f = tk.Frame(body, bg=C["card"]); btn_f.pack(fill=tk.X)
        self._iconbtn(btn_f, "＋", lambda: self.resize_item(1.1)).pack(side=tk.LEFT, expand=True, fill=tk.X, padx=2)
        self._iconbtn(btn_f, "－", lambda: self.resize_item(0.9)).pack(side=tk.LEFT, expand=True, fill=tk.X, padx=2)
        self._iconbtn(btn_f, "⟲", lambda: self.rotate_item(-15)).pack(side=tk.LEFT, expand=True, fill=tk.X, padx=2)
        self._iconbtn(btn_f, "⟳", lambda: self.rotate_item(15)).pack(side=tk.LEFT, expand=True, fill=tk.X, padx=2)
        self._mbtn(body, "delete_permanently", command=self.delete_selected, kind="danger").pack(fill=tk.X, pady=(8, 0))

        # ---------- CARD: ACCOUNT / CORNICE ----------
        body = self._card(self.sidebar, "select_account", accent=C["blue"])
        self.combo_firme = self._combo(body, width=10); self.combo_firme.pack(fill=tk.X, pady=(0, 4)); self.combo_firme.bind("<<ComboboxSelected>>", self.change_signature)
        self._signature_opacity_control(body, self.signature_opacity, collage=False)
        self._mk(tk.Checkbutton, body, "circle_trama_mode", variable=self.trama_mode, command=self.toggle_trama_mode_ui, bg=C["card"], fg=C["blue"], selectcolor=C["input"], activebackground=C["card"], activeforeground=C["blue"], font=(self.FONT, 9, "bold")).pack(anchor="w", pady=(2, 4))
        self.combo_cornici = self._combo(body, width=10); self.combo_cornici.pack(fill=tk.X, pady=3); self.combo_cornici.bind("<<ComboboxSelected>>", self.change_frame)
        # Selettore trama — visibile solo in Circle Trama Mode (stesso parent di combo_cornici per il pack after=)
        self.trama_selector_frame = tk.Frame(body, bg=C["card"])
        self._mk(tk.Label, self.trama_selector_frame, "trama_overlay", bg=C["card"], fg=C["blue"], font=(self.FONT, 8)).pack(anchor="w")
        self.combo_trama = self._combo(self.trama_selector_frame, width=10); self.combo_trama.pack(fill=tk.X, pady=(2, 4)); self.combo_trama.bind("<<ComboboxSelected>>", self.change_trama)
        self.combo_rating = self._combo(body, width=10); self.combo_rating.pack(fill=tk.X, pady=3); self.combo_rating.bind("<<ComboboxSelected>>", self.change_rating)
        self._mk(tk.Label, body, "extra_section", bg=C["card"], fg=C["teal"], font=(self.FONT, 8, "bold")).pack(anchor="w", pady=(6, 0))
        self.combo_extra = self._combo(body, width=10); self.combo_extra.pack(fill=tk.X, pady=3); self.combo_extra.bind("<<ComboboxSelected>>", self.change_extra)
        self._mk(tk.Label, body, "extra_hint", bg=C["card"], fg=C["faint"], font=(self.FONT, 8)).pack(anchor="w")
        self._mbtn(body, key="extra_replace", command=self.replace_selected_extra, kind="normal").pack(fill=tk.X, pady=(3, 0))
        extra_tgt_row = tk.Frame(body, bg=C["card"]); extra_tgt_row.pack(fill=tk.X, pady=(2, 0))
        self._mk(tk.Label, extra_tgt_row, "extra_target", bg=C["card"], fg=C["muted"], font=(self.FONT, 8)).pack(side=tk.LEFT)
        self._mk(tk.Radiobutton, extra_tgt_row, "extra_on_frame", variable=self.extra_target, value="cornice", command=self._apply_extra_target, bg=C["card"], fg=C["text"], selectcolor=C["input"], activebackground=C["card"], activeforeground=C["text"], font=(self.FONT, 8)).pack(side=tk.LEFT, padx=4)
        self._mk(tk.Radiobutton, extra_tgt_row, "extra_on_image", variable=self.extra_target, value="immagine", command=self._apply_extra_target, bg=C["card"], fg=C["teal"], selectcolor=C["input"], activebackground=C["card"], activeforeground=C["teal"], font=(self.FONT, 8)).pack(side=tk.LEFT)
        self._mk(tk.Label, body, "extra_target_hint", bg=C["card"], fg=C["faint"], font=(self.FONT, 8), justify=tk.LEFT).pack(anchor="w")

        # ---------- CARD: I/O (opzioni + load/hide) ----------
        # ---------- CARD: TESTI ----------
        body = self._card(self.sidebar, "t_section", accent=C["accent"])
        prow = tk.Frame(body, bg=C["card"]); prow.pack(fill=tk.X, pady=(0, 4))
        self._mk(tk.Label, prow, "p_label", bg=C["card"], fg=C["muted"], font=(self.FONT, 8)).pack(side=tk.LEFT)
        self.combo_presets = self._combo(prow, width=8); self.combo_presets.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=4)
        self._mbtn(prow, key="p_use", command=lambda: self.apply_text_preset(False), kind="normal").pack(side=tk.LEFT)
        self._mbtn(body, key="t_add", command=self.add_text_layer, kind="primary").pack(fill=tk.X)
        self.lbl_text_sel = tk.Label(body, text=self.tr("t_none"), bg=C["card"], fg=C["muted"], font=(self.FONT, 8, "bold"), anchor="w")
        self.lbl_text_sel.pack(fill=tk.X, pady=(6, 2))
        self.txt_size = tk.IntVar(value=48)
        self.txt_outline = tk.IntVar(value=2); self.txt_opacity = tk.IntVar(value=255)
        self.txt_target = tk.StringVar(value="immagine"); self.txt_align = tk.StringVar(value="left")
        # casella multi-riga: Invio va a capo davvero
        self.entry_text = tk.Text(body, height=3, wrap=tk.WORD, bg=C["input"], fg=C["text"], insertbackground=C["text"],
            relief="flat", highlightthickness=1, highlightbackground=C["input_bd"], highlightcolor=C["accent"], font=(self.FONT, 9))
        self.entry_text.pack(fill=tk.X); self.entry_text.config(state=tk.DISABLED)
        self.entry_text.bind("<KeyRelease>", self._apply_text_controls)
        align_row = tk.Frame(body, bg=C["card"]); align_row.pack(fill=tk.X, pady=(4, 0))
        self._mk(tk.Label, align_row, "t_align", bg=C["card"], fg=C["muted"], font=(self.FONT, 8)).pack(side=tk.LEFT)
        for key, val in (("t_align_left", "left"), ("t_align_center", "center"), ("t_align_right", "right")):
            self._mk(tk.Radiobutton, align_row, key, variable=self.txt_align, value=val, command=self._apply_text_controls,
                bg=C["card"], fg=C["text"], selectcolor=C["input"], activebackground=C["card"], activeforeground=C["text"],
                font=(self.FONT, 8)).pack(side=tk.LEFT, padx=2)
        tr1 = tk.Frame(body, bg=C["card"]); tr1.pack(fill=tk.X, pady=(4, 0))
        self._mk(tk.Label, tr1, "t_size", bg=C["card"], fg=C["muted"], font=(self.FONT, 8)).pack(side=tk.LEFT)
        self._spin(tr1, from_=4, to=800, increment=2, textvariable=self.txt_size, width=5, command=self._apply_text_controls).pack(side=tk.LEFT, padx=(3, 8))
        self._mk(tk.Label, tr1, "t_outline", bg=C["card"], fg=C["muted"], font=(self.FONT, 8)).pack(side=tk.LEFT)
        self._spin(tr1, from_=0, to=30, increment=1, textvariable=self.txt_outline, width=4, command=self._apply_text_controls).pack(side=tk.LEFT, padx=3)
        tr2 = tk.Frame(body, bg=C["card"]); tr2.pack(fill=tk.X, pady=(4, 0))
        self._mk(tk.Label, tr2, "t_opacity", bg=C["card"], fg=C["muted"], font=(self.FONT, 8)).pack(side=tk.LEFT)
        self._spin(tr2, from_=0, to=255, increment=5, textvariable=self.txt_opacity, width=5, command=self._apply_text_controls).pack(side=tk.LEFT, padx=(3, 8))
        self._mk(tk.Label, tr2, "t_color", bg=C["card"], fg=C["muted"], font=(self.FONT, 8)).pack(side=tk.LEFT)
        self.txt_swatch = tk.Label(tr2, bg="#ffffff", width=3, relief="flat"); self.txt_swatch.pack(side=tk.LEFT, padx=3)
        self._mbtn(tr2, key="c_choose", command=self.pick_text_color, kind="normal").pack(side=tk.LEFT)
        tr3 = tk.Frame(body, bg=C["card"]); tr3.pack(fill=tk.X, pady=(4, 0))
        self._mk(tk.Label, tr3, "t_target", bg=C["card"], fg=C["muted"], font=(self.FONT, 8)).pack(side=tk.LEFT)
        self._mk(tk.Radiobutton, tr3, "t_on_image", variable=self.txt_target, value="immagine", command=self._apply_text_controls,
            bg=C["card"], fg=C["text"], selectcolor=C["input"], activebackground=C["card"], activeforeground=C["text"], font=(self.FONT, 8)).pack(side=tk.LEFT, padx=3)
        self._mk(tk.Radiobutton, tr3, "t_on_frame", variable=self.txt_target, value="cornice", command=self._apply_text_controls,
            bg=C["card"], fg=C["teal"], selectcolor=C["input"], activebackground=C["card"], activeforeground=C["teal"], font=(self.FONT, 8)).pack(side=tk.LEFT)
        self._mbtn(body, key="p_save", command=lambda: self.save_text_as_preset(False), kind="normal").pack(fill=tk.X, pady=(5, 0))
        self._mk(tk.Label, body, "t_hint", bg=C["card"], fg=C["faint"], font=(self.FONT, 8), justify=tk.LEFT).pack(anchor="w", pady=(5, 0))

        # (la vecchia card "I / O" non serve più: LOAD/NASCONDI stanno nella barra fissa in alto,
        #  le opzioni di salvataggio nella tab Impostazioni)

        # ---------- CARD: ZOOM ----------
        body = self._card(self.sidebar, "zoom_canvas_section", accent=C["blue"])
        zrow = tk.Frame(body, bg=C["card"]); zrow.pack(fill=tk.X)
        self._iconbtn(zrow, "－", lambda: self.zoom_canvas(0.8)).pack(side=tk.LEFT, padx=(0, 3))
        self.lbl_zoom_pct = tk.Label(zrow, text="100%", bg=C["input"], fg=C["text"], font=(self.FONT, 10, "bold"), width=6); self.lbl_zoom_pct.pack(side=tk.LEFT, padx=3, ipady=4)
        self._iconbtn(zrow, "＋", lambda: self.zoom_canvas(1.25)).pack(side=tk.LEFT, padx=3)
        self._mbtn(zrow, "zoom_reset", command=lambda: self.zoom_canvas(reset=True), kind="normal").pack(side=tk.LEFT, padx=3)
        self._mk(tk.Label, body, "zoom_hint", bg=C["card"], fg=C["faint"], font=(self.FONT, 8), justify=tk.LEFT).pack(anchor="w", pady=(4, 0))

        # ---------- CARD: MOSAIC ----------
        body = self._card(self.sidebar, "mosaic_section", accent=C["amber"])
        self.btn_mosaic_toggle = tk.Button(body, text=self.tr("mosaic_off"), command=self.toggle_mosaic_mode,
            bg=C["card_hd"], fg=C["text"], activebackground="#3a4152", relief="flat", bd=0, cursor="hand2",
            font=(self.FONT, 9, "bold"), highlightthickness=0, pady=6)
        self.btn_mosaic_toggle.pack(fill=tk.X, pady=(0, 6)); self.i18n_widgets.append((self.btn_mosaic_toggle, "mosaic_off"))
        mmf = tk.Frame(body, bg=C["card"]); mmf.pack(fill=tk.X, pady=(0, 4))
        self._mk(tk.Label, mmf, "modo", bg=C["card"], fg=C["muted"], font=(self.FONT, 8)).pack(side=tk.LEFT)
        self._mk(tk.Radiobutton, mmf, "rettangolo", variable=self.mosaic_brush_mode, value="rect", bg=C["card"], fg=C["text"], selectcolor=C["input"], activebackground=C["card"], activeforeground=C["text"], font=(self.FONT, 8)).pack(side=tk.LEFT, padx=4)
        self._mk(tk.Radiobutton, mmf, "pennello", variable=self.mosaic_brush_mode, value="circle", bg=C["card"], fg=C["text"], selectcolor=C["input"], activebackground=C["card"], activeforeground=C["text"], font=(self.FONT, 8)).pack(side=tk.LEFT)
        mpf = tk.Frame(body, bg=C["card"]); mpf.pack(fill=tk.X, pady=2)
        self._mk(tk.Label, mpf, "tile_px", bg=C["card"], fg=C["muted"], font=(self.FONT, 8)).grid(row=0, column=0, sticky="w")
        self._spin(mpf, from_=4, to=64, increment=4, textvariable=self.mosaic_tile_size, width=5).grid(row=0, column=1, padx=4)
        self._mk(tk.Label, mpf, "brush_px", bg=C["card"], fg=C["muted"], font=(self.FONT, 8)).grid(row=0, column=2, sticky="w", padx=(8, 0))
        self._spin(mpf, from_=20, to=300, increment=10, textvariable=self.mosaic_brush_size, width=5).grid(row=0, column=3, padx=4)
        mbf = tk.Frame(body, bg=C["card"]); mbf.pack(fill=tk.X, pady=(4, 0))
        self._mbtn(mbf, "undo", command=self.mosaic_undo, kind="amber").pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 3))
        self._mbtn(mbf, "clear_all", command=self.mosaic_clear, kind="danger").pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(3, 0))

        # ---------- CARD: SEED ID + COPYRIGHT (due colonne) ----------
        body = self._card(self.sidebar, title_text="SEED ID  •  COPYRIGHT", accent=C["accent"])
        duo_frame = tk.Frame(body, bg=C["card"]); duo_frame.pack(fill=tk.X)
        seed_col = tk.Frame(duo_frame, bg=C["card"]); seed_col.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(0, 6))
        copy_col = tk.Frame(duo_frame, bg=C["card"]); copy_col.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(6, 0))

        self._mk(tk.Label, seed_col, "seed_section", bg=C["card"], fg=C["accent_hi"], font=(self.FONT, 8, "bold")).pack(anchor="w")
        self._mk(tk.Checkbutton, seed_col, "show_id", variable=self.seed_id_visible, command=self.draw_frame, bg=C["card"], fg=C["text"], selectcolor=C["input"], activebackground=C["card"], activeforeground=C["text"], font=(self.FONT, 8)).pack(anchor="w", pady=(2, 0))
        seed_row2 = tk.Frame(seed_col, bg=C["card"]); seed_row2.pack(anchor="w", pady=2)
        self._mk(tk.Label, seed_row2, "font", bg=C["card"], fg=C["muted"], font=(self.FONT, 8)).pack(side=tk.LEFT)
        self._spin(seed_row2, from_=10, to=120, increment=2, textvariable=self.seed_id_font_size, width=4, command=self.draw_frame).pack(side=tk.LEFT, padx=4)
        self.lbl_seed_val = tk.Label(seed_col, text="Seed: —", bg=C["card"], fg=C["muted"], font=(self.MONO, 7)); self.lbl_seed_val.pack(anchor="w")
        self._mk(tk.Label, seed_col, "seed_drag_hint", bg=C["card"], fg=C["faint"], font=(self.FONT, 8)).pack(anchor="w")
        self.seed_custom_frame = tk.Frame(seed_col, bg=C["card"])
        self._mk(tk.Label, self.seed_custom_frame, "id_manuale", bg=C["card"], fg=C["amber"], font=(self.FONT, 8)).pack(anchor="w")
        tk.Entry(self.seed_custom_frame, textvariable=self.custom_id, width=16, bg=C["input"], fg=C["text"], insertbackground=C["text"], relief="flat", highlightthickness=1, highlightbackground=C["input_bd"], highlightcolor=C["accent"], font=(self.MONO, 8)).pack(anchor="w", fill=tk.X, pady=(1, 0))
        self.seed_custom_frame.pack(anchor="w", fill=tk.X, pady=(2, 0)); self.seed_custom_frame.pack_forget()  # nascosto di default

        self._mk(tk.Label, copy_col, "copyright_section", bg=C["card"], fg=C["amber"], font=(self.FONT, 8, "bold")).pack(anchor="w")
        self._mk(tk.Checkbutton, copy_col, "copyright_enable", variable=self.copyright_enabled, command=self.draw_all_layers, bg=C["card"], fg=C["amber"], selectcolor=C["input"], activebackground=C["card"], activeforeground=C["amber"], font=(self.FONT, 8)).pack(anchor="w", pady=(2, 0))
        copy_row2 = tk.Frame(copy_col, bg=C["card"]); copy_row2.pack(anchor="w", pady=2)
        self._mk(tk.Label, copy_row2, "font_px", bg=C["card"], fg=C["muted"], font=(self.FONT, 8)).pack(side=tk.LEFT)
        self._spin(copy_row2, from_=10, to=200, increment=2, textvariable=self.copyright_font_size, width=4, command=self.draw_all_layers).pack(side=tk.LEFT, padx=4)
        copy_row3 = tk.Frame(copy_col, bg=C["card"]); copy_row3.pack(anchor="w", pady=2)
        self._mk(tk.Label, copy_row3, "opacity", bg=C["card"], fg=C["muted"], font=(self.FONT, 8)).pack(side=tk.LEFT)
        self._spin(copy_row3, from_=0, to=255, increment=10, textvariable=self.copyright_opacity, width=4, command=self.draw_all_layers).pack(side=tk.LEFT, padx=4)

        # ---------- SAVE ----------
        self.btn_salva = self._mbtn(self.editor_save_holder, "save_all", command=self.process, kind="success", state=tk.DISABLED, font=(self.FONT, 12, "bold"))
        self.btn_salva.pack(pady=12, padx=14, fill=tk.X, ipady=6)

        # ---------- CANVAS (tab Editor) ----------
        self.canvas_frame = tk.Frame(self.tab_editor, bg=C["canvas"])
        self.canvas_frame.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        self.canvas_vscroll = tk.Scrollbar(self.canvas_frame, orient=tk.VERTICAL, bg=C["card_hd"], troughcolor=C["canvas"], activebackground=C["accent"], bd=0, relief="flat", width=12)
        self.canvas_hscroll = tk.Scrollbar(self.canvas_frame, orient=tk.HORIZONTAL, bg=C["card_hd"], troughcolor=C["canvas"], activebackground=C["accent"], bd=0, relief="flat", width=12)
        self.canvas = tk.Canvas(self.canvas_frame, bg=C["canvas"], highlightthickness=0,
                                 yscrollcommand=self.canvas_vscroll.set, xscrollcommand=self.canvas_hscroll.set)
        self.canvas_vscroll.config(command=self.canvas.yview); self.canvas_hscroll.config(command=self.canvas.xview)
        self.canvas_vscroll.pack(side=tk.RIGHT, fill=tk.Y); self.canvas_hscroll.pack(side=tk.BOTTOM, fill=tk.X)
        self.canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        self.canvas.bind("<ButtonPress-1>", self.on_press); self.canvas.bind("<B1-Motion>", self.on_drag); self.canvas.bind("<ButtonRelease-1>", self.on_release); self.canvas.bind("<Button-3>", self.place_signature); self.canvas.bind("<Button-2>", self.place_rating); self.canvas.bind("<Shift-Button-1>", self.place_extra)
        self.canvas.bind("<Control-MouseWheel>", self._on_canvas_ctrl_scroll)
        self.canvas.bind("<Control-Button-4>", lambda e: self.zoom_canvas(1.15))
        self.canvas.bind("<Control-Button-5>", lambda e: self.zoom_canvas(1/1.15))
        self.root.bind("<Control-h>", self.toggle_preview_visibility)
        self.root.bind("<Control-H>", self.toggle_preview_visibility)
        self.root.bind("<Control-plus>", lambda e: self.zoom_canvas(1.25))
        self.root.bind("<Control-equal>", lambda e: self.zoom_canvas(1.25))
        self.root.bind("<Control-minus>", lambda e: self.zoom_canvas(0.8))
        self.root.bind("<Control-0>", lambda e: self.zoom_canvas(reset=True))

        # ---------- TAB COLLAGE ----------
        self._build_collage_tab(self.tab_collage)
        # ---------- TAB IMPOSTAZIONI ----------
        self._build_settings_tab(self.tab_settings)
        self._refresh_preset_ui()   # popola le tendine dei preset in tutte le tab

    # =========================================================
    # TAB IMPOSTAZIONI
    # =========================================================
    def _build_settings_tab(self, parent):
        C = self.C
        canvas = tk.Canvas(parent, bg=C["bg"], highlightthickness=0)
        sbar = tk.Scrollbar(parent, orient=tk.VERTICAL, command=canvas.yview,
            bg=C["card_hd"], troughcolor=C["bg"], activebackground=C["accent"], bd=0, relief="flat", width=10)
        canvas.configure(yscrollcommand=sbar.set)
        sbar.pack(side=tk.RIGHT, fill=tk.Y); canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        self.settings_canvas = canvas
        page = tk.Frame(canvas, bg=C["bg"])
        win = canvas.create_window((0, 0), window=page, anchor="nw")
        page.bind("<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.bind("<Configure>", lambda e: canvas.itemconfig(win, width=e.width))
        canvas.bind("<Enter>", lambda e: canvas.bind_all("<MouseWheel>", self._on_settings_mousewheel))
        canvas.bind("<Leave>", lambda e: canvas.unbind_all("<MouseWheel>"))

        head = tk.Frame(page, bg=C["bg"]); head.pack(fill=tk.X, padx=22, pady=(20, 6))
        self._mk(tk.Label, head, "s_title", bg=C["bg"], fg=C["text"], font=(self.FONT, 15, "bold")).pack(side=tk.LEFT)

        # --- LINGUA ---
        body = self._card(page, title_key="s_language", accent=C["blue"])
        row = tk.Frame(body, bg=C["card"]); row.pack(fill=tk.X)
        self._mk(tk.Label, row, "language_label", bg=C["card"], fg=C["muted"], font=(self.FONT, 8)).pack(side=tk.LEFT)
        self.combo_lang = self._combo(row, width=12, values=self._available_languages())
        self.combo_lang.set(self.current_lang); self.combo_lang.pack(side=tk.LEFT, padx=8)
        self.combo_lang.bind("<<ComboboxSelected>>", self.change_language)
        self._mk(tk.Label, body, "s_language_hint", bg=C["card"], fg=C["faint"], font=(self.FONT, 8), justify=tk.LEFT).pack(anchor="w", pady=(8, 0))

        # --- OPZIONI DI SALVATAGGIO ---
        body = self._card(page, title_key="s_output", accent=C["green"])
        orow = tk.Frame(body, bg=C["card"]); orow.pack(fill=tk.X)
        self._mk(tk.Checkbutton, orow, "sdnext_mode", variable=self.sdnext_mode, bg=C["card"], fg=C["text"],
            selectcolor=C["input"], activebackground=C["card"], activeforeground=C["text"], font=(self.FONT, 8)).pack(side=tk.LEFT, padx=(0, 14))
        self._mk(tk.Checkbutton, orow, "keep_metadata", variable=self.keep_metadata, bg=C["card"], fg=C["blue"],
            selectcolor=C["input"], activebackground=C["card"], activeforeground=C["blue"], font=(self.FONT, 8)).pack(side=tk.LEFT, padx=(0, 14))
        self._mk(tk.Checkbutton, orow, "optimize_png", variable=self.optimize_png, bg=C["card"], fg=C["green"],
            selectcolor=C["input"], activebackground=C["card"], activeforeground=C["green"], font=(self.FONT, 8)).pack(side=tk.LEFT)
        self._mk(tk.Label, body, "s_metadata_hint", bg=C["card"], fg=C["faint"], font=(self.FONT, 8), justify=tk.LEFT).pack(anchor="w", pady=(6, 0))

        # --- QUALI PARAMETRI TENERE NEL TXT ---
        body = self._card(page, title_key="s_text_config", accent=C["teal"])
        self._mk(tk.Label, body, "s_text_config_hint", bg=C["card"], fg=C["muted"],
                 font=(self.FONT, 9), justify=tk.LEFT).pack(anchor="w", pady=(0, 8))
        for key, label in (("ignore_tags", "s_ignore_tags"), ("ignore_loras", "s_ignore_loras"),
                           ("footer_note", "s_footer_text"), ("copyright", "s_copyright_text")):
            self._mk(tk.Label, body, label, bg=C["card"], fg=C["text"], font=(self.FONT, 9, "bold")).pack(anchor="w", pady=(6, 3))
            row = tk.Frame(body, bg=C["card"]); row.pack(fill=tk.X)
            field = tk.Text(row, height=4, wrap=tk.WORD, bg=C["input"], fg=C["text"],
                            insertbackground=C["text"], font=(self.FONT, 10), undo=True)
            scroll = tk.Scrollbar(row, command=field.yview)
            field.config(yscrollcommand=scroll.set)
            scroll.pack(side=tk.RIGHT, fill=tk.Y); field.pack(side=tk.LEFT, fill=tk.X, expand=True)
            field.insert("1.0", self.config_texts[key]); field.edit_modified(False)
            def text_changed(event, name=key, editor=field):
                if not editor.edit_modified(): return
                self.config_texts[name] = editor.get("1.0", "end-1c")
                editor.edit_modified(False)
                self._save_settings()
                if name == "copyright" and self.orig_img: self.draw_all_layers()
            field.bind("<<Modified>>", text_changed)
        self._save_settings()

        body = self._card(page, title_key="p_section", accent=C["amber"])
        self._mk(tk.Checkbutton, body, "p_enable", variable=self.param_filter, command=self._param_filter_changed,
            bg=C["card"], fg=C["amber"], selectcolor=C["input"], activebackground=C["card"],
            activeforeground=C["amber"], font=(self.FONT, 8, "bold")).pack(anchor="w")
        self._mk(tk.Label, body, "p_hint", bg=C["card"], fg=C["faint"], font=(self.FONT, 8), justify=tk.LEFT).pack(anchor="w", pady=(2, 6))
        # scelta rapida dal catalogo
        self.combo_param_add = ttk.Combobox(body, state="readonly", font=(self.FONT, 8),
                                            values=self._param_catalog_values())
        self.combo_param_add.pack(fill=tk.X, pady=(0, 3))
        prow = tk.Frame(body, bg=C["card"]); prow.pack(fill=tk.X, pady=(0, 6))
        self._mbtn(prow, key="p_add", command=self.add_param_from_combo, kind="primary").pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 3))
        self._mbtn(prow, key="p_from_image", command=self.add_params_from_image, kind="normal").pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(3, 0))
        # inserimento manuale, con jolly
        self.entry_param_custom = tk.Entry(body, bg=C["input"], fg=C["text"], insertbackground=C["text"],
            relief=tk.FLAT, font=(self.MONO, 8), highlightthickness=1, highlightbackground=C["input_bd"])
        self.entry_param_custom.pack(fill=tk.X, ipady=3)
        self.entry_param_custom.bind("<Return>", lambda e: self.add_param_custom())
        self._mbtn(body, key="p_add_custom", command=self.add_param_custom, kind="normal").pack(fill=tk.X, pady=(3, 6))
        brow = tk.Frame(body, bg=C["card"]); brow.pack(fill=tk.X, pady=(0, 6))
        self._mbtn(brow, key="p_reset", command=self.reset_params, kind="normal").pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 3))
        self._mbtn(brow, key="p_clear", command=self.clear_params, kind="normal").pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(3, 0))
        self.params_list_frame = tk.Frame(body, bg=C["card"]); self.params_list_frame.pack(fill=tk.X)
        self._refresh_params_list()

        # --- AGGIORNAMENTI ---
        body = self._card(page, title_key="u_section", accent=C["amber"])
        tk.Label(body, text=f"AI Visual Editor  v{APP_VERSION}  ({APP_CODENAME})", bg=C["card"], fg=C["text"],
                 font=(self.FONT, 9, "bold")).pack(anchor="w")
        self._mk(tk.Checkbutton, body, "u_check_startup", variable=self.update_check, bg=C["card"], fg=C["amber"],
            selectcolor=C["input"], activebackground=C["card"], activeforeground=C["amber"], font=(self.FONT, 8)).pack(anchor="w", pady=(4, 0))
        urow = tk.Frame(body, bg=C["card"]); urow.pack(fill=tk.X, pady=(4, 0))
        self._mbtn(urow, key="u_check_now", command=lambda: self.check_updates_async(manual=True), kind="normal").pack(side=tk.LEFT, padx=(0, 4))
        self._mbtn(urow, key="u_open_page", command=self.open_releases_page, kind="normal").pack(side=tk.LEFT)
        self._mk(tk.Label, body, "u_hint", bg=C["card"], fg=C["faint"], font=(self.FONT, 8), justify=tk.LEFT).pack(anchor="w", pady=(6, 0))

        # --- PRESET DI TESTO ---
        body = self._card(page, title_key="p_presets", accent=C["accent"])
        self._mk(tk.Label, body, "p_hint", bg=C["card"], fg=C["faint"], font=(self.FONT, 8), justify=tk.LEFT).pack(anchor="w", pady=(0, 6))
        self.presets_list_frame = tk.Frame(body, bg=C["card"]); self.presets_list_frame.pack(fill=tk.X)
        self._refresh_presets_list()

        # --- LINK AI MODELLI ---
        body = self._card(page, title_key="s_links", accent=C["teal"])
        togg = tk.Frame(body, bg=C["card"]); togg.pack(fill=tk.X)
        self._mk(tk.Checkbutton, togg, "civitai_links", variable=self.civitai_links, bg=C["card"], fg=C["teal"],
            selectcolor=C["input"], activebackground=C["card"], activeforeground=C["teal"], font=(self.FONT, 8)).pack(side=tk.LEFT, padx=(0, 12))
        self._mk(tk.Checkbutton, togg, "custom_links", variable=self.custom_links, bg=C["card"], fg=C["amber"],
            selectcolor=C["input"], activebackground=C["card"], activeforeground=C["amber"], font=(self.FONT, 8)).pack(side=tk.LEFT)
        self._mk(tk.Label, body, "s_links_hint", bg=C["card"], fg=C["faint"], font=(self.FONT, 8), justify=tk.LEFT).pack(anchor="w", pady=(6, 8))

        frm = tk.Frame(body, bg=C["card"]); frm.pack(fill=tk.X)
        self._mk(tk.Label, frm, "s_name", bg=C["card"], fg=C["muted"], font=(self.FONT, 8)).grid(row=0, column=0, sticky="w")
        self.entry_link_name = tk.Entry(frm, bg=C["input"], fg=C["text"], insertbackground=C["text"], relief="flat",
            highlightthickness=1, highlightbackground=C["input_bd"], highlightcolor=C["accent"], font=(self.MONO, 9))
        self.entry_link_name.grid(row=1, column=0, sticky="ew", padx=(0, 8), ipady=3)
        self._mk(tk.Label, frm, "s_url", bg=C["card"], fg=C["muted"], font=(self.FONT, 8)).grid(row=0, column=1, sticky="w")
        self.entry_link_url = tk.Entry(frm, bg=C["input"], fg=C["text"], insertbackground=C["text"], relief="flat",
            highlightthickness=1, highlightbackground=C["input_bd"], highlightcolor=C["accent"], font=(self.MONO, 9))
        self.entry_link_url.grid(row=1, column=1, sticky="ew", ipady=3)
        frm.columnconfigure(0, weight=2); frm.columnconfigure(1, weight=3)
        self._mbtn(body, key="s_add", command=self.add_model_link, kind="primary").pack(fill=tk.X, pady=(8, 6))
        self.links_list_frame = tk.Frame(body, bg=C["card"]); self.links_list_frame.pack(fill=tk.X)
        self._refresh_links_list()

    def _on_settings_mousewheel(self, event):
        self.settings_canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")

    def _refresh_presets_list(self):
        C = self.C
        if not hasattr(self, "presets_list_frame"): return
        for w in self.presets_list_frame.winfo_children(): w.destroy()
        if not self.text_presets:
            tk.Label(self.presets_list_frame, text=self.tr("p_none"), bg=C["card"], fg=C["faint"], font=(self.FONT, 8)).pack(anchor="w")
            return
        for p in self.text_presets:
            row = tk.Frame(self.presets_list_frame, bg=C["card_hd"]); row.pack(fill=tk.X, pady=2)
            sw = tk.Label(row, bg=p.get("color", "#ffffff"), width=2); sw.pack(side=tk.LEFT, padx=(6, 4), pady=4)
            box = tk.Frame(row, bg=C["card_hd"]); box.pack(side=tk.LEFT, fill=tk.X, expand=True, pady=3)
            tk.Label(box, text=p["name"], bg=C["card_hd"], fg=C["text"], font=(self.FONT, 9, "bold"), anchor="w").pack(fill=tk.X)
            prev = (p.get("text") or "").replace("\n", " ⏎ ")
            if len(prev) > 34: prev = prev[:33] + "…"
            info = f"{prev}   ·   {p.get('size', '?')}px · {p.get('align', 'left')}"
            tk.Label(box, text=info, bg=C["card_hd"], fg=C["muted"], font=(self.FONT, 8), anchor="w").pack(fill=tk.X)
            b_ren = tk.Label(row, text="✎", bg=C["card_hd"], fg=C["blue"], font=(self.FONT, 10, "bold"), width=3, cursor="hand2")
            b_ren.pack(side=tk.LEFT); b_ren.bind("<Button-1>", lambda ev, d=p: self.rename_text_preset(d))
            b_del = tk.Label(row, text="✕", bg=C["card_hd"], fg=C["red_hi"], font=(self.FONT, 10, "bold"), width=3, cursor="hand2")
            b_del.pack(side=tk.LEFT, padx=(0, 6)); b_del.bind("<Button-1>", lambda ev, d=p: self.delete_text_preset(d))

    def rename_text_preset(self, p):
        name = simpledialog.askstring(self.tr("p_presets"), self.tr("p_name"), initialvalue=p["name"], parent=self.root)
        if not name or not name.strip(): return
        p["name"] = name.strip(); self._save_text_presets(); self._refresh_preset_ui()

    def delete_text_preset(self, p):
        if not messagebox.askyesno(self.tr("p_presets"), f"{p['name']} ✕ ?"): return
        self.text_presets = [x for x in self.text_presets if x is not p]
        self._save_text_presets(); self._refresh_preset_ui()

    def _refresh_links_list(self):
        C = self.C
        if not hasattr(self, "links_list_frame"): return
        for w in self.links_list_frame.winfo_children(): w.destroy()
        if not self.model_links:
            tk.Label(self.links_list_frame, text=self.tr("s_no_links"), bg=C["card"], fg=C["faint"], font=(self.FONT, 8)).pack(anchor="w")
            return
        for i, e in enumerate(sorted(self.model_links, key=lambda d: d["name"].lower())):
            row = tk.Frame(self.links_list_frame, bg=C["card_hd"]); row.pack(fill=tk.X, pady=2)
            txt = tk.Frame(row, bg=C["card_hd"]); txt.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=8, pady=3)
            tk.Label(txt, text=e["name"], bg=C["card_hd"], fg=C["text"], font=(self.FONT, 9, "bold"), anchor="w").pack(fill=tk.X)
            url = e["url"] if len(e["url"]) <= 52 else e["url"][:51] + "…"
            tk.Label(txt, text=url, bg=C["card_hd"], fg=C["muted"], font=(self.MONO, 7), anchor="w").pack(fill=tk.X)
            b_ed = tk.Label(row, text="✎", bg=C["card_hd"], fg=C["blue"], font=(self.FONT, 10, "bold"), width=3, cursor="hand2")
            b_ed.pack(side=tk.LEFT); b_ed.bind("<Button-1>", lambda ev, d=e: self.edit_model_link(d))
            b_del = tk.Label(row, text="✕", bg=C["card_hd"], fg=C["red_hi"], font=(self.FONT, 10, "bold"), width=3, cursor="hand2")
            b_del.pack(side=tk.LEFT, padx=(0, 6)); b_del.bind("<Button-1>", lambda ev, d=e: self.delete_model_link(d))

    def add_model_link(self):
        name = self.entry_link_name.get().strip()
        url = self.entry_link_url.get().strip()
        if not name or not url:
            messagebox.showwarning("Impostazioni", self.tr("s_name") + " + " + self.tr("s_url")); return
        key = self._link_key(name)
        for e in self.model_links:                       # stesso nome = aggiorna, non duplica
            if self._link_key(e["name"]) == key:
                e["name"] = name; e["url"] = url; break
        else:
            self.model_links.append({"name": name, "url": url})
        self._reindex_links(); self._save_model_links(); self._refresh_links_list()
        self.entry_link_name.delete(0, tk.END); self.entry_link_url.delete(0, tk.END)

    def edit_model_link(self, entry):
        self.entry_link_name.delete(0, tk.END); self.entry_link_name.insert(0, entry["name"])
        self.entry_link_url.delete(0, tk.END); self.entry_link_url.insert(0, entry["url"])

    def delete_model_link(self, entry):
        self.model_links = [e for e in self.model_links if self._link_key(e["name"]) != self._link_key(entry["name"])]
        self._reindex_links(); self._save_model_links(); self._refresh_links_list()

    def clean_prompt_tags(self, text):
        if not text: return ""
        blacklist = [l.strip().lower() for l in self._config_text(self.path_ignore_tags).splitlines() if l.strip() and not l.strip().startswith("#")]
        t_list = [t.strip() for t in text.replace('\n',',').split(',') if t.strip()]
        filtered = []
        for t in t_list:
            if not any(w in t.lower() for w in blacklist): filtered.append(t)
        return ", ".join(filtered).strip().strip(',').strip()

    def pre_load_assets(self):
        f_l = [f for f in os.listdir(self.folder_firme) if f.lower().endswith('.png')]
        self.combo_firme['values'] = f_l
        if f_l: self.combo_firme.current(0); self.change_signature()
        if hasattr(self, "combo_firme_collage"):
            self.combo_firme_collage['values'] = f_l
            if f_l: self.combo_firme_collage.current(0)
        if hasattr(self, "combo_cornici_collage"):
            frames = [f for f in os.listdir(self.folder_cornici) if f.lower().endswith('.png') and '_' not in os.path.splitext(f)[0]]
            self.combo_cornici_collage['values'] = frames   # nessuna selezione automatica: la cornice è opzionale
        r_l = [f for f in os.listdir(self.folder_rating) if f.lower().endswith('.png')]
        self.combo_rating['values'] = r_l
        if r_l: self.combo_rating.current(0); self.change_rating()
        e_l = [f for f in os.listdir(self.folder_extra) if f.lower().endswith('.png')]
        self.combo_extra['values'] = e_l
        if e_l: self.combo_extra.current(0); self.change_extra()
        self.refresh_cornici_list(); self.update_layer_panel()
    def refresh_cornici_list(self):
        f = self.folder_mask if self.trama_mode.get() else self.folder_cornici
        l = [file for file in os.listdir(f) if file.lower().endswith('.png') and '_' not in os.path.splitext(file)[0]]
        self.combo_cornici['values'] = l
        if l: self.combo_cornici.current(0); self.change_frame(); self.draw_frame()
    def update_layer_panel(self):
        for w in self.layer_ui_frame.winfo_children(): w.destroy()
        def _row(tag, label, has_pos, visible, on_del=None):
            sel = self.selected_layer == tag
            rowbg = self.C["accent"] if sel else self.C["card_hd"]
            row = tk.Frame(self.layer_ui_frame, bg=rowbg, pady=3); row.pack(fill=tk.X, pady=2)
            if not has_pos: icon, col = "○", self.C["faint"]
            elif visible:   icon, col = "●", ("#ffffff" if sel else self.C["green"])
            else:           icon, col = "◌", self.C["red"]
            lbl_eye = tk.Label(row, text=icon, fg=col, bg=rowbg, font=(self.FONT, 11, 'bold'), width=4, cursor="hand2"); lbl_eye.pack(side=tk.LEFT, padx=(8, 2)); lbl_eye.bind("<Button-1>", lambda e, t=tag: self.toggle_visibility_direct(t))
            lbl_name = tk.Label(row, text=label, fg="#ffffff" if sel else self.C["text"], bg=rowbg, font=(self.FONT, 9, 'bold'), anchor="w", cursor="hand2"); lbl_name.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=6); lbl_name.bind("<Button-1>", lambda e, t=tag: self.select_layer_direct(t))
            if on_del is not None:
                b = tk.Label(row, text="✕", fg=self.C["red_hi"], bg=rowbg, font=(self.FONT, 9, 'bold'), width=3, cursor="hand2")
                b.pack(side=tk.RIGHT, padx=(0, 6)); b.bind("<Button-1>", lambda e: on_del())
        for t in ["firma", "rating", "cornice"]:
            _row(t, self.tr(f"layer_{t}"), bool(self.state[t]["pos"]), self.state[t]["visible"])
        for i, ex in enumerate(self.extras, 1):
            nm = ex["name"] if len(ex["name"]) <= 12 else ex["name"][:11] + "…"
            # segno della destinazione, così si legge a colpo d'occhio senza selezionarlo
            dove = "🖼" if ex.get("target", "cornice") == "immagine" else "🔲"
            _row(self._extra_tag(ex), f"{self.tr('layer_extra')} {i} · {nm}  {dove}", bool(ex["pos"]), ex["visible"],
                 on_del=lambda uid=ex["uid"]: self.delete_extra(uid))
        for i, t in enumerate(self.texts, 1):
            nm = (t.get("text") or "").replace("\n", " ")
            nm = nm if len(nm) <= 12 else nm[:11] + "…"
            _row(self._text_tag(t), f"{self.tr('layer_text')} {i} · {nm}", True, t["visible"],
                 on_del=lambda uid=t["uid"]: self.delete_text(uid))
    def toggle_visibility_direct(self, t):
        tx = next((x for x in self.texts if self._text_tag(x) == t), None)
        if tx is not None:
            tx["visible"] = not tx["visible"]; self.draw_all_layers(); self.update_layer_panel(); return
        ex = next((e for e in self.extras if self._extra_tag(e) == t), None)
        if ex is not None:
            if ex["pos"]: ex["visible"] = not ex["visible"]; self.draw_all_layers(); self.update_layer_panel()
            return
        if self.state[t]["pos"]: self.state[t]["visible"] = not self.state[t]["visible"]; self.draw_all_layers(); self.update_layer_panel()
    def select_layer_direct(self, t):
        self.selected_layer = t
        it = self.canvas.find_withtag(t)
        if it: self.highlight(it[0])
        self.update_layer_panel()
        self._sync_text_controls()   # se è un TESTO, la sua card deve mostrarne i valori
        self._sync_extra_controls()  # se è un EXTRA, il selettore mostra la SUA destinazione
    # ---------- TESTI (editor): comandi ----------
    def add_text_layer(self):
        t = self.new_text_layer()
        self.texts.append(t)
        self.selected_layer = self._text_tag(t)
        self.draw_text_layer(t); self.update_layer_panel(); self._sync_text_controls()

    def delete_text(self, uid):
        t = next((x for x in self.texts if x["uid"] == uid), None)
        if t is None: return
        if self.selected_layer == self._text_tag(t): self.selected_layer = None
        self.canvas.delete(self._text_tag(t)); self.tk_refs.pop(self._text_tag(t), None)
        self.texts.remove(t)
        self.canvas.delete("selector"); self.draw_all_layers(); self.update_layer_panel(); self._sync_text_controls()

    def _sync_text_controls(self):
        """Allinea i controlli della card TESTI al livello selezionato (o li svuota)."""
        if not hasattr(self, "entry_text"): return
        t = self._sel_text()
        self._text_ui_lock = True
        try:
            if t is None:
                self.entry_text.config(state=tk.NORMAL); self.entry_text.delete("1.0", tk.END)
                self.entry_text.config(state=tk.DISABLED)
                self.lbl_text_sel.config(text=self.tr("t_none"))
            else:
                self.entry_text.config(state=tk.NORMAL)
                self.entry_text.delete("1.0", tk.END); self.entry_text.insert("1.0", t.get("text") or "")
                self.txt_size.set(int(t["size"])); self.txt_outline.set(int(t.get("outline", 0)))
                self.txt_opacity.set(int(t.get("opacity", 255))); self.txt_target.set(t.get("target", "immagine"))
                self.txt_align.set(t.get("align", "left"))
                self.txt_swatch.config(bg=t.get("color", "#ffffff"))
                lab = (t.get("text") or "").replace("\n", " ")
                self.lbl_text_sel.config(text=(lab if len(lab) <= 22 else lab[:21] + "…"))
        finally:
            self._text_ui_lock = False

    def _apply_text_controls(self, *a):
        """Riporta sul livello selezionato le modifiche fatte nei controlli."""
        if getattr(self, "_text_ui_lock", False): return
        t = self._sel_text()
        if t is None: return
        t["text"] = self.entry_text.get("1.0", "end-1c")
        t["align"] = self.txt_align.get()
        try: t["size"] = max(4, int(self.txt_size.get()))
        except Exception: pass
        try: t["outline"] = max(0, int(self.txt_outline.get()))
        except Exception: pass
        try: t["opacity"] = max(0, min(255, int(self.txt_opacity.get())))
        except Exception: pass
        t["target"] = self.txt_target.get()
        self.draw_text_layer(t); self.update_layer_panel()

    def pick_text_color(self):
        t = self._sel_text()
        if t is None: return
        c = colorchooser.askcolor(color=t.get("color", "#ffffff"), title=self.tr("t_color"))
        if c and c[1]:
            t["color"] = c[1]; self.txt_swatch.config(bg=c[1]); self.draw_text_layer(t)

    def delete_extra(self, uid):
        """Elimina un singolo EXTRA dalla lista."""
        ex = next((e for e in self.extras if e["uid"] == uid), None)
        if ex is None: return
        if self.selected_layer == self._extra_tag(ex): self.selected_layer = None
        self.canvas.delete(self._extra_tag(ex)); self.tk_refs.pop(self._extra_tag(ex), None)
        self.extras.remove(ex)
        self.canvas.delete("selector"); self.draw_all_layers(); self.update_layer_panel()
    # ---------- EXTRA multipli: helper ----------
    def _sync_extra_controls(self):
        """Porta il selettore 'Stampa su' sulla destinazione dell'EXTRA selezionato.
        Se la selezione non è un extra il valore resta lì, e farà da predefinito
        per il prossimo elemento aggiunto."""
        ex = self._sel_extra()
        if ex is None: return
        self._extra_ui_lock = True
        try: self.extra_target.set(ex.get("target", "cornice"))
        finally: self._extra_ui_lock = False

    def _apply_extra_target(self):
        """Il selettore è stato mosso: la nuova destinazione va sull'elemento scelto."""
        if getattr(self, "_extra_ui_lock", False): return
        ex = self._sel_extra()
        if ex is not None:
            ex["target"] = self.extra_target.get()
            self.update_layer_panel()

    def _extra_tag(self, ex): return f"extra:{ex['uid']}"
    def _sel_extra(self):
        """Dict dell'EXTRA selezionato, o None se la selezione non è un extra."""
        if not isinstance(self.selected_layer, str) or not self.selected_layer.startswith("extra:"): return None
        uid = self.selected_layer.split(":", 1)[1]
        return next((e for e in self.extras if str(e["uid"]) == uid), None)
    def draw_extra(self, ex):
        """Disegna un singolo EXTRA sul canvas (stesso schema di draw_element)."""
        if self.preview_hidden: return
        tag = self._extra_tag(ex)
        self.canvas.delete(tag)
        if not ex.get("img") or not ex.get("pos") or not ex.get("visible", True): return
        s = max(1, int(self.img_w * ex["scale"])); h = max(1, int(ex["img"].height * (s / ex["img"].width)))
        resized = ex["img"].resize((s, h), Image.Resampling.LANCZOS)
        if ex.get("rotation"): resized = resized.rotate(ex["rotation"], expand=True, resample=Image.Resampling.BICUBIC)
        itk = ImageTk.PhotoImage(resized); self.tk_refs[tag] = itk
        px, py = int(ex["pos"][0] * self.img_w), int(ex["pos"][1] * self.img_h)
        item = self.canvas.create_image(px, py, anchor=tk.NW, image=itk, tags=("movable", "extra", tag))
        if self.selected_layer == tag: self.highlight(item)

    # ---------- TESTI (editor): helper ----------
    def _text_tag(self, t): return f"text:{t['uid']}"
    def _sel_text(self, lst=None):
        """Dict del TESTO selezionato, o None. lst = self.texts (editor) o self.collage_texts."""
        if lst is None: lst = self.texts
        if not isinstance(self.selected_layer, str) or not self.selected_layer.startswith("text:"): return None
        uid = self.selected_layer.split(":", 1)[1]
        return next((t for t in lst if str(t["uid"]) == uid), None)
    def draw_text_layer(self, t):
        """Disegna un livello di testo sul canvas dell'editor (stesso rendering dell'export)."""
        if self.preview_hidden: return
        tag = self._text_tag(t)
        self.canvas.delete(tag)
        if not t.get("visible", True): return
        im = self._render_text_img(t, self.ratio)
        if im is None: return
        itk = ImageTk.PhotoImage(im); self.tk_refs[tag] = itk
        px, py = int(t["pos"][0] * self.img_w), int(t["pos"][1] * self.img_h)
        item = self.canvas.create_image(px, py, anchor=tk.NW, image=itk, tags=("movable", "text", tag))
        if self.selected_layer == tag: self.highlight(item)

    def draw_all_layers(self):
        if self.preview_hidden: return
        self.canvas.delete("movable", "selector", "copyright_preview")
        for ex in self.extras: self.draw_extra(ex)          # gli EXTRA stanno sotto a tutto
        for t in ["cornice", "firma", "rating"]: [self.draw_frame() if t=="cornice" else self.draw_element(t) if self.state[t]["pos"] and self.state[t]["visible"] else None]
        for t in self.texts: self.draw_text_layer(t)        # i TESTI stanno sopra a tutto
        # anteprima copyright in basso a destra del canvas
        if self.copyright_enabled.get() and self.orig_img:
            ct = self.get_copyright_text()
            if ct:
                # font size = % della larghezza canvas
                fs = max(6, int(self.copyright_font_size.get() * self.ratio))
                import textwrap
                ct_wrapped = ct  # nessun wrap
                self.canvas.create_text(9, self.img_h - 9, text=ct_wrapped, anchor=tk.SW,
                    fill="#000000", font=('Arial', fs, 'bold'), tags="copyright_preview")
                # approssima opacità sul canvas con luminosità del grigio
                op = self.copyright_opacity.get()
                grey = f"#{op:02x}{op:02x}{op:02x}"
                self.canvas.create_text(10, self.img_h - 10, text=ct_wrapped, anchor=tk.SW,
                    fill=grey, font=('Arial', fs, 'bold'), tags="copyright_preview")
    def draw_element(self, t):
        if self.preview_hidden: return
        self.canvas.delete(t); raw = self.raw_assets[t]
        if not raw or not self.state[t]["pos"]: return
        s = int(self.img_w * self.state[t]["scale"]); h = int(raw.height*(s/raw.width))
        resized = raw.resize((s, h), Image.Resampling.LANCZOS)
        if t == "firma": resized = self._signature_alpha(resized, self.signature_opacity.get())
        rotation = self.state[t].get("rotation", 0)
        if rotation: resized = resized.rotate(rotation, expand=True, resample=Image.Resampling.BICUBIC)
        itk = ImageTk.PhotoImage(resized)
        self.tk_refs[t] = itk
        px, py = int(self.state[t]["pos"][0]*self.img_w), int(self.state[t]["pos"][1]*self.img_h); item = self.canvas.create_image(px, py, anchor=tk.NW, image=itk, tags=("movable", t))
        if self.selected_layer == t: self.highlight(item)
    def draw_frame(self):
        if self.preview_hidden: return
        self.canvas.delete("cornice"); self.canvas.delete("seed_id_text")
        if not self.raw_assets["cornice"] or not self.state["cornice"]["pos"] or not self.orig_img or not self.state["cornice"]["visible"]: return
        side = int(self.state["cornice"]["size"] * self.img_w)
        f_res = self.raw_assets["cornice"].resize((side, side), Image.Resampling.LANCZOS)
        if self.trama_mode.get() and self.raw_assets.get("trama"):
            # Anteprima: cornice + trama sovrapposta, senza ritagliare l'immagine
            trama_res = self.raw_assets["trama"].resize((side, side), Image.Resampling.LANCZOS)
            preview = Image.alpha_composite(f_res, trama_res)
            self.tk_cornice = ImageTk.PhotoImage(preview)
        else:
            self.tk_cornice = ImageTk.PhotoImage(f_res)
        px, py = int(self.state["cornice"]["pos"][0]*self.img_w), int(self.state["cornice"]["pos"][1]*self.img_h); it = self.canvas.create_image(px, py, anchor=tk.NW, image=self.tk_cornice, tags=("movable", "cornice"))
        if self.selected_layer == "cornice": self.highlight(it)
        # seed ID: coordinate pixel canvas dirette
        if self.seed_id_visible.get():
            effective_id = self.seed_value or self.custom_id.get().strip()
            if effective_id:
                tx = int(self.seed_id_pos[0])
                ty = int(self.seed_id_pos[1])
                preview_font_size = max(8, int(self.seed_id_font_size.get() * self.ratio))
                label = f"ID: {effective_id}"
                self.canvas.create_text(tx+1, ty+1, text=label, anchor=tk.NW,
                    fill="#000000", font=('Consolas', preview_font_size, 'bold'), tags=("seed_id_text", "movable_seed"))
                self.canvas.create_text(tx, ty, text=label, anchor=tk.NW,
                    fill="#ffffff", font=('Consolas', preview_font_size, 'bold'), tags=("seed_id_text", "movable_seed"))
    def resize_item(self, f):
        tx = self._sel_text()
        if tx is not None:
            if tx["visible"]:
                tx["size"] = max(4, int(round(tx["size"] * f))); self.draw_text_layer(tx); self._sync_text_controls()
            return
        ex = self._sel_extra()
        if ex is not None:
            if ex["visible"]: ex["scale"] *= f; self.draw_extra(ex)
            return
        if self.selected_layer and self.selected_layer in self.state and self.state[self.selected_layer]["visible"]: self.state[self.selected_layer]["size" if self.selected_layer=="cornice" else "scale"] *= f; [self.draw_frame() if self.selected_layer=="cornice" else self.draw_element(self.selected_layer)]
    def rotate_item(self, delta):
        # rotazione disponibile per firma, rating, extra e testi (la cornice resta fissa)
        tx = self._sel_text()
        if tx is not None:
            if tx["visible"]:
                tx["rotation"] = (tx.get("rotation", 0) + delta) % 360; self.draw_text_layer(tx)
            return
        ex = self._sel_extra()
        if ex is not None:
            if ex["visible"]: ex["rotation"] = (ex.get("rotation", 0) + delta) % 360; self.draw_extra(ex)
            return
        if self.selected_layer in ("firma", "rating") and self.state[self.selected_layer]["visible"]:
            self.state[self.selected_layer]["rotation"] = (self.state[self.selected_layer].get("rotation", 0) + delta) % 360
            self.draw_element(self.selected_layer)
    def highlight(self, it):
        self.canvas.delete("selector"); b = self.canvas.bbox(it)
        if b: self.canvas.create_rectangle(b[0]-1, b[1]-1, b[2]+1, b[3]+1, outline="#27ae60", width=2, tags="selector")
    def change_frame(self, e=None):
        sel = self.combo_cornici.get()
        use_mask_folder = self.trama_mode.get()
        [self.raw_assets.update({"cornice": Image.open(os.path.join(self.folder_mask if use_mask_folder else self.folder_cornici, sel)).convert("RGBA")}) if sel else None]
        if sel: base = os.path.splitext(sel)[0]; self.current_frame_name = base; folder = self.folder_mask if use_mask_folder else self.folder_cornici; bp = os.path.join(folder, f"{base}_border.png"); self.raw_assets["border"] = Image.open(bp).convert("RGBA") if use_mask_folder and os.path.exists(bp) else None
        if self.state["cornice"]["pos"]: self.draw_frame()
        if self.trama_mode.get() and sel:
            prefisso = os.path.splitext(sel)[0].split("_")[0]
            self.refresh_trama_list(prefisso)
    def change_rating(self, e=None):
        sel = self.combo_rating.get(); [self.raw_assets.update({"rating": Image.open(os.path.join(self.folder_rating, sel)).convert("RGBA")}) if sel else None]; self.draw_element("rating") if self.state["rating"]["pos"] else None
    def change_extra(self, e=None):
        """Sceglie l'asset per il PROSSIMO elemento EXTRA aggiunto (SHIFT+click).
        Non tocca gli elementi già piazzati: per cambiarli si usa 'Sostituisci selezionato'."""
        sel = self.combo_extra.get()
        if not sel: return
        self.raw_assets["extra"] = Image.open(os.path.join(self.folder_extra, sel)).convert("RGBA")
        self.current_extra_name = os.path.splitext(sel)[0]

    def replace_selected_extra(self):
        """Sostituisce l'immagine dell'EXTRA selezionato con l'asset scelto nel menu."""
        ex = self._sel_extra()
        if ex is None or not self.raw_assets.get("extra"): return
        ex["img"] = self.raw_assets["extra"]; ex["name"] = getattr(self, "current_extra_name", ex["name"])
        self.draw_extra(ex); self.update_layer_panel()

    def toggle_trama_mode_ui(self):
        """Mostra/nasconde il selettore trama e aggiorna la lista cornici."""
        self.refresh_cornici_list()
        if self.trama_mode.get():
            self.trama_selector_frame.pack(fill=tk.X, padx=20, pady=(0,4), after=self.combo_cornici)
            self.refresh_trama_list()
        else:
            self.trama_selector_frame.pack_forget()

    def refresh_trama_list(self, prefisso=None):
        """Popola combo_trama con le trame della cartella Cornici_Mask, filtrate per prefisso cornice."""
        folder = self.folder_mask
        tutti = sorted([f for f in os.listdir(folder) if f.lower().endswith(".png") and "_" in os.path.splitext(f)[0]])
        if prefisso:
            trame = [f for f in tutti if os.path.splitext(f)[0].split("_")[0].lower() == prefisso.lower()]
        else:
            trame = tutti
        self.combo_trama["values"] = trame
        if trame:
            self.combo_trama.current(0)
            self.change_trama()
        else:
            self.combo_trama.set("")
            self.raw_assets["trama"] = None

    def change_trama(self, e=None):
        """Carica la trama selezionata e aggiorna subito l'anteprima, come fa
        change_frame con le cornici normali: senza il ridisegno la nuova trama
        resterebbe invisibile fino alla prima altra modifica."""
        sel = self.combo_trama.get()
        if sel:
            path = os.path.join(self.folder_mask, sel)
            self.raw_assets["trama"] = Image.open(path).convert("RGBA")
        else:
            self.raw_assets["trama"] = None
        if self.state["cornice"]["pos"]: self.draw_frame()

    def _frame_export_name(self):
        """Parte del nome file che distingue l'esportazione della cornice.

        In Circle Texture Mode la cornice è sempre la stessa (es. "cerchio") e a
        cambiare è la trama sopra: usare il nome della cornice farebbe sovrascrivere
        ogni esportazione con quella successiva. Il nome della trama contiene già il
        prefisso della cornice ("cerchio_pellicola-1"), quindi da solo basta."""
        if self.trama_mode.get():
            t = self.combo_trama.get()
            if t: return os.path.splitext(t)[0]
        return self.current_frame_name
    def on_drop(self, event):
        """Gestisce il drag & drop di un file immagine sulla finestra."""
        path = event.data.strip()
        # tkinterdnd2 su Windows può restituire il path tra graffe {path}
        if path.startswith("{") and path.endswith("}"): path = path[1:-1]
        ext = os.path.splitext(path)[1].lower()
        if ext in (".png", ".jpg", ".jpeg", ".webp", ".bmp"):
            self.load_image(path)
        else:
            messagebox.showwarning(self.tr("msg_unsupported_format_title"), self.tr("msg_unsupported_format_body").format(ext=ext))

    def load_image(self, path=None):
        p = path if path else filedialog.askopenfilename()
        if not p: return
        self.current_file_path = p; self.orig_filename = os.path.splitext(os.path.basename(p))[0]
        img = Image.open(p); self.info_buffer = img.info; self.orig_img = img.convert("RGBA"); ow, oh = self.orig_img.size
        self._mosaic_base = self.orig_img.copy()  # snapshot pulito per il pennello mosaico
        self.mosaic_regions.clear()  # reset mosaic on new image load
        # estrai seed dai metadati
        self.seed_value = ""
        seed_match = re.search(r"Seed:\s*(\d+)", self.info_buffer.get("parameters", ""), re.I)
        if seed_match: self.seed_value = seed_match.group(1)
        self.seed_id_pos_relative = None  # reset relative pos
        self.lbl_seed_val.config(text=f"Seed: {self.seed_value if self.seed_value else '—'}")
        # mostra campo ID manuale solo se non c'è seed
        if self.seed_value:
            self.seed_custom_frame.pack_forget()
            self.custom_id.set("")
        else:
            self.seed_custom_frame.pack(fill=tk.X, padx=20, pady=(0,4))
        self.base_ratio = min(1100/ow, 850/oh); self.view_zoom = 1.0; self.ratio = self.base_ratio * self.view_zoom
        self.img_w, self.img_h = int(ow*self.ratio), int(oh*self.ratio)
        self.seed_id_pos = (self.img_w // 2, 10)  # centro-alto in pixel canvas
        self.tk_main = ImageTk.PhotoImage(self.orig_img.resize((self.img_w, self.img_h), Image.Resampling.LANCZOS))
        self.canvas.delete("all"); self.canvas.config(scrollregion=(0, 0, self.img_w, self.img_h)); self.canvas.create_image(0, 0, anchor=tk.NW, image=self.tk_main, tags="bg")
        self._update_zoom_label()
        self.draw_all_layers(); self.btn_salva.config(state=tk.NORMAL)
        if self.preview_hidden: self._show_privacy_overlay()
    def on_press(self, e):
        if self.preview_hidden: return
        cx, cy = self.canvas.canvasx(e.x), self.canvas.canvasy(e.y)
        if self.mosaic_mode:
            if self.mosaic_brush_mode.get() == "circle":
                self._apply_circle_brush(cx, cy)
            else:
                self.mosaic_drag_start = (cx, cy); self.mosaic_preview_rect = None
            return
        # check click su seed_id_text per drag (coordinate assolute canvas)
        if self.seed_id_visible.get() and (self.seed_value or self.custom_id.get().strip()):
            for item in self.canvas.find_withtag("seed_id_text"):
                bb = self.canvas.bbox(item)
                if bb and bb[0] <= cx <= bb[2] and bb[1] <= cy <= bb[3]:
                    self.seed_id_dragging = True; self.drag_data.update({"x": cx, "y": cy, "item": None}); return
        f = self.canvas.find_closest(cx, cy); it = f[0] if f else None; tags = self.canvas.gettags(it) if it else []
        if "movable" in tags:
            special = next((t for t in tags if t.startswith("extra:") or t.startswith("text:")), None)
            self.selected_layer = special or [t for t in ["firma", "rating", "cornice"] if t in tags][0]
            self.highlight(it); self.drag_data.update({"item": it, "x": cx, "y": cy})
            self.update_layer_panel(); self._sync_text_controls()
        else: self.start_x, self.start_y = cx, cy; self.state["cornice"]["pos"] = (cx/self.img_w, cy/self.img_h); self.state["cornice"]["visible"] = True; self.selected_layer = "cornice"; self.draw_frame(); self.update_layer_panel()
    def on_drag(self, e):
        if self.preview_hidden: return
        cx, cy = self.canvas.canvasx(e.x), self.canvas.canvasy(e.y)
        if self.mosaic_mode:
            if self.mosaic_brush_mode.get() == "circle":
                self._apply_circle_brush(cx, cy)
            else:
                if self.mosaic_drag_start:
                    x0, y0 = self.mosaic_drag_start
                    if self.mosaic_preview_rect: self.canvas.delete(self.mosaic_preview_rect)
                    self.mosaic_preview_rect = self.canvas.create_rectangle(x0, y0, cx, cy, outline="#e67e22", width=2, dash=(4,2), tags="mosaic_preview")
            return
        # drag seed_id: salva coordinate pixel canvas E relativa alla cornice (come rating)
        if self.seed_id_dragging:
            sx = max(0, min(self.img_w, cx))
            sy = max(0, min(self.img_h, cy))
            self.seed_id_pos = (sx, sy)
            if self.state["cornice"]["pos"] and self.state["cornice"]["size"]:
                cp = self.state["cornice"]["pos"]; cs = self.state["cornice"]["size"]
                fcx = int(cp[0] * self.img_w); fcy = int(cp[1] * self.img_h); fcs = int(cs * self.img_w)
                rx = (sx - fcx) / fcs if fcs > 0 else 0.5
                ry = (sy - fcy) / fcs if fcs > 0 else 0.5
                self.seed_id_pos_relative = (max(0.0, min(1.0, rx)), max(0.0, min(1.0, ry)))
            self.draw_frame(); return
        if not self.drag_data["item"] and self.selected_layer == "cornice":
            side = max(4, max(abs(cx - self.start_x), abs(cy - self.start_y))); self.state["cornice"].update({"pos": ((self.start_x if cx > self.start_x else self.start_x - side)/self.img_w, (self.start_y if cy > self.start_y else self.start_y - side)/self.img_h), "size": side/self.img_w}); self.draw_frame()
        elif self.drag_data["item"]:
            dx, dy = cx - self.drag_data["x"], cy - self.drag_data["y"]; self.canvas.move(self.drag_data["item"], dx, dy); self.canvas.move("selector", dx, dy); self.drag_data.update({"x": cx, "y": cy}); c = self.canvas.coords(self.drag_data["item"])
            tx = self._sel_text(); ex = self._sel_extra()
            if tx is not None: tx["pos"] = (c[0]/self.img_w, c[1]/self.img_h)
            elif ex is not None: ex["pos"] = (c[0]/self.img_w, c[1]/self.img_h)
            elif self.selected_layer in self.state: self.state[self.selected_layer]["pos"] = (c[0]/self.img_w, c[1]/self.img_h)
    def on_release(self, e):
        self.seed_id_dragging = False
        cx_e, cy_e = self.canvas.canvasx(e.x), self.canvas.canvasy(e.y)
        if self.mosaic_mode:
            if self.mosaic_brush_mode.get() == "circle":
                self.refresh_canvas_bg(); return  # il pennello aggiorna già orig_img in tempo reale
            if self.mosaic_drag_start:
                x0c, y0c = self.mosaic_drag_start; x1c, y1c = cx_e, cy_e
                cx0, cx1 = min(x0c, x1c), max(x0c, x1c); cy0, cy1 = min(y0c, y1c), max(y0c, y1c)
                if (cx1-cx0) < 4 or (cy1-cy0) < 4:
                    bs = self.mosaic_brush_size.get(); cx0, cy0 = cx_e-bs//2, cy_e-bs//2; cx1, cy1 = cx_e+bs//2, cy_e+bs//2
                cx0=max(0,cx0); cy0=max(0,cy0); cx1=min(self.img_w,cx1); cy1=min(self.img_h,cy1)
                ow, oh = self.orig_img.size
                ox0=int(cx0/self.img_w*ow); oy0=int(cy0/self.img_h*oh); ox1=int(cx1/self.img_w*ow); oy1=int(cy1/self.img_h*oh)
                self.apply_mosaic_region(ox0, oy0, ox1, oy1); self.mosaic_regions.append((ox0, oy0, ox1, oy1))
                if self.mosaic_preview_rect: self.canvas.delete(self.mosaic_preview_rect); self.mosaic_preview_rect = None
                self.mosaic_drag_start = None; self.refresh_canvas_bg()
            return
        self.drag_data["item"] = None
    def place_signature(self, e):
        cx, cy = self.canvas.canvasx(e.x), self.canvas.canvasy(e.y)
        self.state["firma"]["pos"] = (cx/self.img_w, cy/self.img_h); self.state["firma"]["visible"] = True; self.selected_layer = "firma"; self.draw_element("firma"); self.update_layer_panel()
    def place_rating(self, e):
        cx, cy = self.canvas.canvasx(e.x), self.canvas.canvasy(e.y)
        self.state["rating"]["pos"] = (cx/self.img_w, cy/self.img_h); self.state["rating"]["visible"] = True
        if self.state["cornice"]["pos"]: self.state["rating"]["scale"] = self.state["cornice"]["size"] * 0.25
        self.selected_layer = "rating"; self.draw_element("rating"); self.update_layer_panel()
    def place_extra(self, e):
        """SHIFT + click sinistro: aggiunge un NUOVO elemento EXTRA nel punto cliccato."""
        if not self.raw_assets.get("extra"): return
        cx, cy = self.canvas.canvasx(e.x), self.canvas.canvasy(e.y)
        self._extra_uid += 1
        scale = self.state["cornice"]["size"] * 0.3 if self.state["cornice"]["pos"] else 0.15
        ex = {"uid": self._extra_uid, "name": getattr(self, "current_extra_name", "extra"),
              "img": self.raw_assets["extra"], "pos": (cx/self.img_w, cy/self.img_h),
              "scale": scale, "visible": True, "rotation": 0,
              # destinazione PROPRIA dell'elemento: il selettore della card fa da
              # valore di partenza, come il menu decide l'immagine del prossimo extra
              "target": self.extra_target.get()}
        self.extras.append(ex)
        self.selected_layer = self._extra_tag(ex)
        self.draw_extra(ex); self.update_layer_panel(); self._sync_extra_controls()
    def delete_selected(self):
        tx = self._sel_text()
        if tx is not None: self.delete_text(tx["uid"]); return
        ex = self._sel_extra()
        if ex is not None: self.delete_extra(ex["uid"]); return
        if self.selected_layer and self.selected_layer in self.state:
            self.state[self.selected_layer]["pos"] = None; self.canvas.delete(self.selected_layer); self.canvas.delete("selector"); self.selected_layer = None; self.update_layer_panel()

    # =========================================================
    # MOSAIC BRUSH METHODS
    # =========================================================
    def _apply_circle_brush(self, cx, cy):
        """Applica mosaico circolare centrato in (cx,cy) in coordinate canvas.

        Anti-sbavatura: il mosaico è calcolato SEMPRE dai pixel originali puliti
        (`self._mosaic_base`) e su una griglia di tile GLOBALE e fissa. Così pennellate
        sovrapposte durante il drag combaciano e non trascinano/stirano l'effetto."""
        if not self.orig_img: return
        src = self._mosaic_base if self._mosaic_base is not None else self.orig_img
        bs = self.mosaic_brush_size.get()
        ow, oh = self.orig_img.size
        ox_c = int(cx / self.img_w * ow); oy_c = int(cy / self.img_h * oh)
        r = max(1, int(bs / 2 / self.ratio))  # raggio in px originali
        tile = max(2, self.mosaic_tile_size.get())
        # bounding box del cerchio, poi allineato (snap) alla griglia globale dei tile
        bx0 = max(0, ox_c - r); by0 = max(0, oy_c - r)
        bx1 = min(ow, ox_c + r); by1 = min(oh, oy_c + r)
        gx0 = (bx0 // tile) * tile; gy0 = (by0 // tile) * tile
        gx1 = min(ow, -(-bx1 // tile) * tile); gy1 = min(oh, -(-by1 // tile) * tile)
        if gx1 <= gx0 or gy1 <= gy0: return
        # mosaico dai pixel ORIGINALI, con griglia allineata a (gx0,gy0) multipli di tile
        region = src.crop((gx0, gy0, gx1, gy1)).convert("RGBA")
        rw, rh = region.size
        small = region.resize((max(1, rw//tile), max(1, rh//tile)), Image.Resampling.NEAREST)
        mosaic = small.resize((rw, rh), Image.Resampling.NEAREST)
        # maschera ellittica posizionata sul cerchio reale del pennello dentro la regione
        mask = Image.new("L", (rw, rh), 0)
        ecx0 = ox_c - r - gx0; ecy0 = oy_c - r - gy0
        ImageDraw.Draw(mask).ellipse((ecx0, ecy0, ecx0 + 2*r, ecy0 + 2*r), fill=255)
        # composita il mosaico sopra l'immagine CORRENTE (fuori dal cerchio resta com'è)
        current = self.orig_img.crop((gx0, gy0, gx1, gy1)).convert("RGBA")
        result = Image.composite(mosaic, current, mask)
        self.orig_img.paste(result, (gx0, gy0))
        self.mosaic_regions.append((gx0, gy0, gx1, gy1))
        # refresh throttolato (~60fps): evita di rifare il resize dell'intera immagine ad ogni evento mouse
        self._schedule_bg_refresh()
    def _schedule_bg_refresh(self):
        """Coalesce gli aggiornamenti del background durante il drag del pennello mosaico."""
        if self._refresh_after_id is not None: return
        self._refresh_after_id = self.root.after(16, self._do_scheduled_refresh)
    def _do_scheduled_refresh(self):
        self._refresh_after_id = None
        if not self.orig_img or self.preview_hidden: return
        # BILINEAR durante il drag: molto più veloce di LANCZOS; il refresh finale (rilascio) resta LANCZOS
        preview = self.orig_img.resize((self.img_w, self.img_h), Image.Resampling.BILINEAR)
        self.tk_main = ImageTk.PhotoImage(preview)
        self.canvas.itemconfig("bg", image=self.tk_main)
    def toggle_mosaic_mode(self):
        self.mosaic_mode = not self.mosaic_mode
        if self.mosaic_mode:
            self.btn_mosaic_toggle.config(text=self.tr("mosaic_on"), bg=self.C["amber"], fg="#2a1f05")
            self.canvas.config(cursor="crosshair")
        else:
            self.btn_mosaic_toggle.config(text=self.tr("mosaic_off"), bg=self.C["card_hd"], fg=self.C["text"])
            self.canvas.config(cursor="")
            if self.mosaic_preview_rect:
                self.canvas.delete(self.mosaic_preview_rect)
                self.mosaic_preview_rect = None

    def apply_mosaic_region(self, ox0, oy0, ox1, oy1):
        """Apply pixelated mosaic effect to orig_img in the given original-coords rectangle."""
        if not self.orig_img: return
        tile = max(2, self.mosaic_tile_size.get())
        region = self.orig_img.crop((ox0, oy0, ox1, oy1))
        rw, rh = region.size
        if rw < 1 or rh < 1: return
        # Downscale to tile grid then upscale back — classic mosaic
        small_w = max(1, rw // tile)
        small_h = max(1, rh // tile)
        region = region.resize((small_w, small_h), Image.Resampling.NEAREST)
        region = region.resize((rw, rh), Image.Resampling.NEAREST)
        self.orig_img.paste(region, (ox0, oy0))

    def mosaic_undo(self):
        """Re-open original file and replay all regions except the last one."""
        if not self.mosaic_regions or not self.current_file_path: return
        self.mosaic_regions.pop()
        # Reload clean image
        img = Image.open(self.current_file_path)
        self.orig_img = img.convert("RGBA")
        # Replay remaining regions
        for region in self.mosaic_regions:
            self.apply_mosaic_region(*region)
        self.refresh_canvas_bg()

    def mosaic_clear(self):
        """Remove all mosaic regions and restore original image."""
        if not self.current_file_path: return
        self.mosaic_regions.clear()
        img = Image.open(self.current_file_path)
        self.orig_img = img.convert("RGBA")
        self.refresh_canvas_bg()

    def refresh_canvas_bg(self):
        """Redraw the canvas background with the current orig_img (with mosaic applied)."""
        if not self.orig_img: return
        if self.preview_hidden: return
        preview = self.orig_img.resize((self.img_w, self.img_h), Image.Resampling.LANCZOS)
        self.tk_main = ImageTk.PhotoImage(preview)
        self.canvas.delete("bg")
        self.canvas.create_image(0, 0, anchor=tk.NW, image=self.tk_main, tags="bg")
        self.canvas.tag_lower("bg")
        self.draw_all_layers()

    def _show_privacy_overlay(self):
        """Copre il canvas con un overlay nero — usato per nascondere immagini 'delicate'."""
        w = self.img_w if self.img_w else 800
        h = self.img_h if self.img_h else 600
        self.canvas.delete("all")
        self.canvas.config(width=w, height=h)
        self.canvas.create_rectangle(0, 0, w, h, fill=self.C["canvas"], outline="", tags="privacy_overlay")
        self.canvas.create_text(w // 2, h // 2, text="🔒  Anteprima nascosta\n(Ctrl+H per mostrare)",
            fill=self.C["faint"], font=(self.FONT, 16, 'bold'), justify=tk.CENTER, tags="privacy_overlay")

    def toggle_preview_visibility(self, event=None):
        """Nasconde/mostra rapidamente l'anteprima dell'immagine (per lavori 'delicati')."""
        self.preview_hidden = not self.preview_hidden
        if self.preview_hidden:
            self._show_privacy_overlay()
        else:
            self.canvas.delete("privacy_overlay")
            if self.orig_img:
                self.refresh_canvas_bg()
        return "break"

    # =========================================================
    # TAB COLLAGE — compositore a colonne
    # =========================================================
    def _build_collage_tab(self, parent):
        C = self.C
        # --- anteprima a sinistra ---
        left = tk.Frame(parent, bg=C["canvas"]); left.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        self.collage_canvas = tk.Canvas(left, bg=C["canvas"], highlightthickness=0)
        self.collage_canvas.pack(fill=tk.BOTH, expand=True)
        self.collage_canvas.bind("<ButtonPress-1>", self._collage_press)
        self.collage_canvas.bind("<B1-Motion>", self._collage_drag)
        self.collage_canvas.bind("<ButtonRelease-1>", self._collage_release)
        self.collage_canvas.bind("<Configure>", lambda e: self._render_collage_preview())

        # --- pannello controlli a destra (scrollabile, con SALVA fissato in basso) ---
        side_container = tk.Frame(parent, width=390, bg=C["sidebar"]); side_container.pack(side=tk.RIGHT, fill=tk.Y); side_container.pack_propagate(False)
        # il pulsante di salvataggio sta FUORI dall'area di scorrimento: sempre raggiungibile
        self.collage_save_holder = tk.Frame(side_container, bg=C["sidebar"]); self.collage_save_holder.pack(side=tk.BOTTOM, fill=tk.X)
        scroll_area = tk.Frame(side_container, bg=C["sidebar"]); scroll_area.pack(side=tk.TOP, fill=tk.BOTH, expand=True)
        self.collage_side_canvas = tk.Canvas(scroll_area, bg=C["sidebar"], highlightthickness=0)
        self.collage_side_scroll = tk.Scrollbar(scroll_area, orient=tk.VERTICAL, command=self.collage_side_canvas.yview,
            bg=C["card_hd"], troughcolor=C["sidebar"], activebackground=C["accent"], bd=0, relief="flat", width=10)
        self.collage_side_canvas.configure(yscrollcommand=self.collage_side_scroll.set)
        self.collage_side_scroll.pack(side=tk.RIGHT, fill=tk.Y)
        self.collage_side_canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        side = tk.Frame(self.collage_side_canvas, bg=C["sidebar"])
        self.collage_side_canvas.create_window((0, 0), window=side, anchor="nw", width=368)
        side.bind("<Configure>", lambda e: self.collage_side_canvas.configure(scrollregion=self.collage_side_canvas.bbox("all")))
        self.collage_side_canvas.bind("<Enter>", lambda e: self.collage_side_canvas.bind_all("<MouseWheel>", self._on_collage_side_mousewheel))
        self.collage_side_canvas.bind("<Leave>", lambda e: self.collage_side_canvas.unbind_all("<MouseWheel>"))
        self.collage_side_canvas.bind("<Button-4>", lambda e: self.collage_side_canvas.yview_scroll(-2, "units"))
        self.collage_side_canvas.bind("<Button-5>", lambda e: self.collage_side_canvas.yview_scroll(2, "units"))

        header = tk.Frame(side, bg=C["sidebar"]); header.pack(fill=tk.X, padx=16, pady=(16, 4))
        self._mk(tk.Label, header, "c_title", bg=C["sidebar"], fg=C["text"], font=(self.FONT, 12, "bold")).pack(side=tk.LEFT)

        body = self._card(side, title_key="c_images", accent=C["blue"])
        self._mbtn(body, key="c_add_images", command=self.collage_add_images, kind="primary").pack(fill=tk.X)
        self.collage_list_frame = tk.Frame(body, bg=C["card"]); self.collage_list_frame.pack(fill=tk.X, pady=(8, 0))

        body = self._card(side, title_key="c_format", accent=C["green"])
        r = tk.Frame(body, bg=C["card"]); r.pack(fill=tk.X, pady=2)
        self._mk(tk.Label, r, "c_width", bg=C["card"], fg=C["muted"], font=(self.FONT, 8)).pack(side=tk.LEFT)
        self._spin(r, from_=100, to=12000, increment=50, textvariable=self.collage_w, width=6, command=self._render_collage_preview).pack(side=tk.LEFT, padx=(4, 10))
        self._mk(tk.Label, r, "c_height", bg=C["card"], fg=C["muted"], font=(self.FONT, 8)).pack(side=tk.LEFT)
        self._spin(r, from_=100, to=12000, increment=50, textvariable=self.collage_h, width=6, command=self._render_collage_preview).pack(side=tk.LEFT, padx=4)
        r2 = tk.Frame(body, bg=C["card"]); r2.pack(fill=tk.X, pady=2)
        self._mk(tk.Label, r2, "c_gutter", bg=C["card"], fg=C["muted"], font=(self.FONT, 8)).pack(side=tk.LEFT)
        self._spin(r2, from_=0, to=500, increment=2, textvariable=self.collage_gutter, width=5, command=self._render_collage_preview).pack(side=tk.LEFT, padx=6)
        r3 = tk.Frame(body, bg=C["card"]); r3.pack(fill=tk.X, pady=2)
        self._mk(tk.Label, r3, "c_gutter_color", bg=C["card"], fg=C["muted"], font=(self.FONT, 8)).pack(side=tk.LEFT)
        self.collage_swatch = tk.Label(r3, bg=self.collage_gutter_color, width=4, relief="flat"); self.collage_swatch.pack(side=tk.LEFT, padx=6)
        self._mbtn(r3, key="c_choose", command=self.collage_pick_color, kind="normal").pack(side=tk.LEFT)
        r4 = tk.Frame(body, bg=C["card"]); r4.pack(fill=tk.X, pady=2)
        self._mk(tk.Label, r4, "c_outline", bg=C["card"], fg=C["muted"], font=(self.FONT, 8)).pack(side=tk.LEFT)
        self._spin(r4, from_=0, to=100, increment=1, textvariable=self.collage_outline, width=4, command=self._render_collage_preview).pack(side=tk.LEFT, padx=6)
        self.collage_outline_swatch = tk.Label(r4, bg=self.collage_outline_color, width=4, relief="flat"); self.collage_outline_swatch.pack(side=tk.LEFT, padx=(0, 6))
        self._mbtn(r4, key="c_choose", command=self.collage_pick_outline_color, kind="normal").pack(side=tk.LEFT)
        body = self._card(side, title_key="c_layout", accent=C["amber"])
        mrow = tk.Frame(body, bg=C["card"]); mrow.pack(fill=tk.X)
        self._mk(tk.Radiobutton, mrow, "c_mode_cols", variable=self.collage_mode, value="cols", command=self._collage_mode_changed,
            bg=C["card"], fg=C["text"], selectcolor=C["input"], activebackground=C["card"], activeforeground=C["text"], font=(self.FONT, 8)).pack(anchor="w")
        drow = tk.Frame(mrow, bg=C["card"]); drow.pack(fill=tk.X, padx=(18, 0))
        self._mk(tk.Label, drow, "c_dir", bg=C["card"], fg=C["muted"], font=(self.FONT, 8)).pack(side=tk.LEFT)
        self._mk(tk.Radiobutton, drow, "c_dir_v", variable=self.collage_dir, value="cols", command=self._collage_dir_changed,
            bg=C["card"], fg=C["text"], selectcolor=C["input"], activebackground=C["card"], activeforeground=C["text"], font=(self.FONT, 8)).pack(side=tk.LEFT, padx=3)
        self._mk(tk.Radiobutton, drow, "c_dir_h", variable=self.collage_dir, value="rows", command=self._collage_dir_changed,
            bg=C["card"], fg=C["text"], selectcolor=C["input"], activebackground=C["card"], activeforeground=C["text"], font=(self.FONT, 8)).pack(side=tk.LEFT)
        self._mk(tk.Radiobutton, mrow, "c_dir_grid", variable=self.collage_dir, value="grid", command=self._collage_dir_changed,
            bg=C["card"], fg=C["text"], selectcolor=C["input"], activebackground=C["card"], activeforeground=C["text"], font=(self.FONT, 8)).pack(anchor="w", padx=18)
        grow = tk.Frame(mrow, bg=C["card"]); grow.pack(fill=tk.X, padx=18, pady=3)
        for key, var in (("c_grid_cols", self.collage_grid_cols), ("c_grid_rows", self.collage_grid_rows)):
            self._mk(tk.Label, grow, key, bg=C["card"], fg=C["muted"], font=(self.FONT, 8)).pack(side=tk.LEFT)
            self._spin(grow, from_=1, to=100, increment=1, textvariable=var, width=4).pack(side=tk.LEFT, padx=4)
            var.trace_add("write", lambda *a: self._collage_grid_changed())
        self._mk(tk.Label, mrow, "c_grid_hint", bg=C["card"], fg=C["faint"], font=(self.FONT, 8), justify=tk.LEFT).pack(anchor="w", padx=18, pady=3)
        self._mk(tk.Radiobutton, mrow, "c_mode_free", variable=self.collage_mode, value="free", command=self._collage_mode_changed,
            bg=C["card"], fg=C["amber"], selectcolor=C["input"], activebackground=C["card"], activeforeground=C["amber"], font=(self.FONT, 8)).pack(anchor="w")
        # controlli visibili solo in modalità libera
        self.free_panel = tk.Frame(body, bg=C["card"])
        rr = tk.Frame(self.free_panel, bg=C["card"]); rr.pack(fill=tk.X, pady=(6, 2))
        self._mk(tk.Label, rr, "c_rotate", bg=C["card"], fg=C["muted"], font=(self.FONT, 8)).pack(side=tk.LEFT)
        self._iconbtn(rr, "⟲", lambda: self._free_rotate(-1)).pack(side=tk.LEFT, padx=(6, 2))
        self._spin(rr, from_=1, to=90, increment=1, textvariable=self.free_rot, width=4, command=self._free_rot_set).pack(side=tk.LEFT, padx=2)
        self._iconbtn(rr, "⟳", lambda: self._free_rotate(1)).pack(side=tk.LEFT, padx=2)
        tk.Label(rr, text="°", bg=C["card"], fg=C["muted"], font=(self.FONT, 8)).pack(side=tk.LEFT)
        br = tk.Frame(self.free_panel, bg=C["card"]); br.pack(fill=tk.X, pady=2)
        self._mbtn(br, key="c_straighten", command=self._free_straighten, kind="normal").pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 3))
        self._mbtn(br, key="c_reset_cols", command=self._free_reset_from_cols, kind="normal").pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(3, 0))
        dr = tk.Frame(self.free_panel, bg=C["card"]); dr.pack(fill=tk.X, pady=2)
        self._mbtn(dr, key="c_diagonal", command=self._free_diagonal, kind="primary").pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 4))
        self._mk(tk.Label, dr, "c_slant", bg=C["card"], fg=C["muted"], font=(self.FONT, 8)).pack(side=tk.LEFT)
        self._spin(dr, from_=0, to=100, increment=5, textvariable=self.free_slant, width=4, command=self._free_diagonal).pack(side=tk.LEFT, padx=3)
        pr = tk.Frame(self.free_panel, bg=C["card"]); pr.pack(fill=tk.X, pady=(6, 2))
        self._mk(tk.Label, pr, "c_preset", bg=C["card"], fg=C["muted"], font=(self.FONT, 8)).pack(anchor="w")
        self.combo_layouts = self._combo(self.free_panel, width=10); self.combo_layouts.pack(fill=tk.X, pady=2)
        self.combo_layouts.bind("<<ComboboxSelected>>", self.layout_load)
        pbr = tk.Frame(self.free_panel, bg=C["card"]); pbr.pack(fill=tk.X, pady=2)
        self._mbtn(pbr, key="c_save_short", command=self.layout_save, kind="primary").pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 3))
        self._mbtn(pbr, text="🗑", command=self.layout_delete, kind="danger").pack(side=tk.LEFT, padx=(3, 0))
        self._mk(tk.Checkbutton, self.free_panel, "c_snap", variable=self.free_snap, command=self._render_collage_preview,
            bg=C["card"], fg=C["amber"], selectcolor=C["input"], activebackground=C["card"], activeforeground=C["amber"], font=(self.FONT, 8)).pack(anchor="w", pady=(4, 0))
        self._mk(tk.Label, self.free_panel, "c_hint_free", bg=C["card"], fg=C["faint"], font=(self.FONT, 8), justify=tk.LEFT).pack(anchor="w", pady=(4, 0))
        self.cols_hint = self._mk(tk.Label, body, "c_hint_cols", bg=C["card"], fg=C["faint"], font=(self.FONT, 8), justify=tk.LEFT)
        self.cols_hint.pack(anchor="w", pady=(8, 0))

        body = self._card(side, title_key="c_signature", accent=C["accent"])
        self.combo_firme_collage = self._combo(body, width=10); self.combo_firme_collage.pack(fill=tk.X, pady=(0, 4)); self.combo_firme_collage.bind("<<ComboboxSelected>>", self.collage_change_signature)
        r = tk.Frame(body, bg=C["card"]); r.pack(fill=tk.X, pady=2)
        self._mk(tk.Checkbutton, r, "c_sig_apply", variable=self.collage_sig_enabled, command=self._render_collage_preview, bg=C["card"], fg=C["text"], selectcolor=C["input"], activebackground=C["card"], activeforeground=C["text"], font=(self.FONT, 8)).pack(side=tk.LEFT)
        self._mk(tk.Label, r, "c_sig_size", bg=C["card"], fg=C["muted"], font=(self.FONT, 8)).pack(side=tk.LEFT, padx=(8, 2))
        self._spin(r, from_=2, to=80, increment=1, textvariable=self.collage_sig_scale, width=4, command=self._render_collage_preview).pack(side=tk.LEFT)
        self._signature_opacity_control(body, self.collage_sig_opacity, collage=True)
        self._mk(tk.Label, body, "c_hint_sig", bg=C["card"], fg=C["faint"], font=(self.FONT, 8), justify=tk.LEFT).pack(anchor="w", pady=(6, 0))

        body = self._card(side, title_key="c_frame", accent=C["teal"])
        self.combo_cornici_collage = self._combo(body, width=10); self.combo_cornici_collage.pack(fill=tk.X, pady=(0, 4)); self.combo_cornici_collage.bind("<<ComboboxSelected>>", self.collage_change_frame)
        self._mk(tk.Checkbutton, body, "c_frame_apply", variable=self.collage_frame_enabled, command=self._render_collage_preview, bg=C["card"], fg=C["teal"], selectcolor=C["input"], activebackground=C["card"], activeforeground=C["teal"], font=(self.FONT, 8)).pack(anchor="w")
        ffit = tk.Frame(body, bg=C["card"]); ffit.pack(fill=tk.X, pady=(4, 0))
        self._mk(tk.Label, ffit, "c_frame_fit", bg=C["card"], fg=C["muted"], font=(self.FONT, 8)).pack(anchor="w")
        self._mk(tk.Radiobutton, ffit, "c_fit_inside", variable=self.collage_frame_fit, value="inside", command=self._render_collage_preview,
            bg=C["card"], fg=C["text"], selectcolor=C["input"], activebackground=C["card"], activeforeground=C["text"], font=(self.FONT, 8)).pack(anchor="w")
        self._mk(tk.Radiobutton, ffit, "c_fit_fill", variable=self.collage_frame_fit, value="fill", command=self._render_collage_preview,
            bg=C["card"], fg=C["amber"], selectcolor=C["input"], activebackground=C["card"], activeforeground=C["amber"], font=(self.FONT, 8)).pack(anchor="w")
        self._mk(tk.Label, body, "c_hint_frame", bg=C["card"], fg=C["faint"], font=(self.FONT, 8), justify=tk.LEFT).pack(anchor="w", pady=(6, 0))

        # --- TESTI sul collage ---
        body = self._card(side, "t_section", accent=C["accent"])
        cprow = tk.Frame(body, bg=C["card"]); cprow.pack(fill=tk.X, pady=(0, 4))
        self._mk(tk.Label, cprow, "p_label", bg=C["card"], fg=C["muted"], font=(self.FONT, 8)).pack(side=tk.LEFT)
        self.combo_cpresets = self._combo(cprow, width=8); self.combo_cpresets.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=4)
        self._mbtn(cprow, key="p_use", command=lambda: self.apply_text_preset(True), kind="normal").pack(side=tk.LEFT)
        self._mbtn(body, key="t_add", command=self.add_collage_text, kind="primary").pack(fill=tk.X)
        self.lbl_ctext_sel = tk.Label(body, text=self.tr("t_none"), bg=C["card"], fg=C["muted"], font=(self.FONT, 8, "bold"), anchor="w")
        self.lbl_ctext_sel.pack(fill=tk.X, pady=(6, 2))
        self.ctxt_size = tk.IntVar(value=48)
        self.ctxt_outline = tk.IntVar(value=2); self.ctxt_opacity = tk.IntVar(value=255)
        self.ctxt_rot = tk.IntVar(value=0); self.ctxt_align = tk.StringVar(value="left")
        self.entry_ctext = tk.Text(body, height=3, wrap=tk.WORD, bg=C["input"], fg=C["text"], insertbackground=C["text"],
            relief="flat", highlightthickness=1, highlightbackground=C["input_bd"], highlightcolor=C["accent"], font=(self.FONT, 9))
        self.entry_ctext.pack(fill=tk.X); self.entry_ctext.config(state=tk.DISABLED)
        self.entry_ctext.bind("<KeyRelease>", self._apply_collage_text_controls)
        calign = tk.Frame(body, bg=C["card"]); calign.pack(fill=tk.X, pady=(4, 0))
        self._mk(tk.Label, calign, "t_align", bg=C["card"], fg=C["muted"], font=(self.FONT, 8)).pack(side=tk.LEFT)
        for key, val in (("t_align_left", "left"), ("t_align_center", "center"), ("t_align_right", "right")):
            self._mk(tk.Radiobutton, calign, key, variable=self.ctxt_align, value=val, command=self._apply_collage_text_controls,
                bg=C["card"], fg=C["text"], selectcolor=C["input"], activebackground=C["card"], activeforeground=C["text"],
                font=(self.FONT, 8)).pack(side=tk.LEFT, padx=2)
        cr1 = tk.Frame(body, bg=C["card"]); cr1.pack(fill=tk.X, pady=(4, 0))
        self._mk(tk.Label, cr1, "t_size", bg=C["card"], fg=C["muted"], font=(self.FONT, 8)).pack(side=tk.LEFT)
        self._spin(cr1, from_=4, to=800, increment=2, textvariable=self.ctxt_size, width=5, command=self._apply_collage_text_controls).pack(side=tk.LEFT, padx=(3, 8))
        self._mk(tk.Label, cr1, "t_outline", bg=C["card"], fg=C["muted"], font=(self.FONT, 8)).pack(side=tk.LEFT)
        self._spin(cr1, from_=0, to=30, increment=1, textvariable=self.ctxt_outline, width=4, command=self._apply_collage_text_controls).pack(side=tk.LEFT, padx=3)
        cr2 = tk.Frame(body, bg=C["card"]); cr2.pack(fill=tk.X, pady=(4, 0))
        self._mk(tk.Label, cr2, "t_opacity", bg=C["card"], fg=C["muted"], font=(self.FONT, 8)).pack(side=tk.LEFT)
        self._spin(cr2, from_=0, to=255, increment=5, textvariable=self.ctxt_opacity, width=5, command=self._apply_collage_text_controls).pack(side=tk.LEFT, padx=(3, 8))
        self._mk(tk.Label, cr2, "t_color", bg=C["card"], fg=C["muted"], font=(self.FONT, 8)).pack(side=tk.LEFT)
        self.ctxt_swatch = tk.Label(cr2, bg="#ffffff", width=3, relief="flat"); self.ctxt_swatch.pack(side=tk.LEFT, padx=3)
        self._mbtn(cr2, key="c_choose", command=self.pick_collage_text_color, kind="normal").pack(side=tk.LEFT)
        cr3 = tk.Frame(body, bg=C["card"]); cr3.pack(fill=tk.X, pady=(4, 0))
        self._mk(tk.Label, cr3, "c_rotate", bg=C["card"], fg=C["muted"], font=(self.FONT, 8)).pack(side=tk.LEFT)
        self._spin(cr3, from_=-180, to=180, increment=5, textvariable=self.ctxt_rot, width=5, command=self._apply_collage_text_controls).pack(side=tk.LEFT, padx=(3, 8))
        self._mbtn(cr3, text="🗑", command=self.delete_collage_text, kind="danger").pack(side=tk.LEFT)
        self._mbtn(body, key="p_save", command=lambda: self.save_text_as_preset(True), kind="normal").pack(fill=tk.X, pady=(5, 0))
        self._mk(tk.Label, body, "t_hint_collage", bg=C["card"], fg=C["faint"], font=(self.FONT, 8), justify=tk.LEFT).pack(anchor="w", pady=(5, 0))

        body = self._card(side, title_key="c_textfile", accent=C["teal"])
        self._mk(tk.Checkbutton, body, "civitai_links", variable=self.civitai_links, bg=C["card"], fg=C["teal"], selectcolor=C["input"], activebackground=C["card"], activeforeground=C["teal"], font=(self.FONT, 8)).pack(anchor="w")
        self._mk(tk.Label, body, "c_hint_civitai", bg=C["card"], fg=C["faint"], font=(self.FONT, 8), justify=tk.LEFT).pack(anchor="w", pady=(4, 0))

        self._mbtn(self.collage_save_holder, key="c_save_all", command=self.collage_save, kind="success", font=(self.FONT, 12, "bold")).pack(pady=12, padx=14, fill=tk.X, ipady=6)
        self._refresh_collage_list()
        self._refresh_layouts_list()
        # aggiorna l'anteprima ANCHE quando si digita nei campi (non solo con le frecce)
        for _v in (self.collage_w, self.collage_h, self.collage_gutter, self.collage_sig_scale, self.collage_outline):
            _v.trace_add("write", lambda *a: self._render_collage_preview())

    def _refresh_collage_list(self):
        C = self.C
        for w in self.collage_list_frame.winfo_children(): w.destroy()
        if not self.collage_images:
            tk.Label(self.collage_list_frame, text=self.tr("c_no_images"), bg=C["card"], fg=C["faint"], font=(self.FONT, 8)).pack(anchor="w")
            return
        for i, item in enumerate(self.collage_images):
            row = tk.Frame(self.collage_list_frame, bg=C["card_hd"]); row.pack(fill=tk.X, pady=2)
            name = item["name"]
            if len(name) > 20: name = name[:19] + "…"
            tk.Label(row, text=f"{i+1}.  {name}", bg=C["card_hd"], fg=C["text"], font=(self.FONT, 8), anchor="w").pack(side=tk.LEFT, fill=tk.X, expand=True, padx=6, pady=3)
            self._iconbtn(row, "↑", lambda idx=i: self.collage_move(idx, -1)).pack(side=tk.LEFT, padx=1)
            self._iconbtn(row, "↓", lambda idx=i: self.collage_move(idx, 1)).pack(side=tk.LEFT, padx=1)
            self._iconbtn(row, "✕", lambda idx=i: self.collage_remove(idx)).pack(side=tk.LEFT, padx=(1, 4))
            scale_row = tk.Frame(self.collage_list_frame, bg=C["card"])
            scale_row.pack(fill=tk.X, pady=(0, 4))
            self._mk(tk.Label, scale_row, "c_image_scale", bg=C["card"], fg=C["muted"], font=(self.FONT, 8)).pack(side=tk.LEFT)
            value = tk.DoubleVar(value=round(item.get("zoom", 1.0) * 100, 1))
            typed = tk.StringVar(value=f"{value.get():g}")
            tk.Scale(scale_row, from_=10, to=300, resolution=1, orient=tk.HORIZONTAL,
                     variable=value,
                     bg=C["card"], fg=C["text"], troughcolor=C["input"], highlightthickness=0,
                     length=140).pack(side=tk.LEFT, fill=tk.X, expand=True, padx=4)
            entry = self._spin(scale_row, from_=10, to=300, increment=5, textvariable=typed, width=5)
            entry.pack(side=tk.LEFT)
            def slide_changed(*a, image=item, var=value, field=typed):
                field.set(f"{var.get():g}")
                self._collage_image_scale(image, var)
            def edit_scale(event=None, final=False, image=item, var=value, field=typed):
                try:
                    number = float(field.get().replace(",", "."))
                    if not math.isfinite(number): raise ValueError
                except ValueError:
                    if final: field.set(f"{image.get('zoom', 1.0) * 100:g}")
                    return
                if not final and not 10 <= number <= 300: return
                number = min(300, max(10, number))
                if var.get() != number: var.set(number)
                if final: field.set(f"{var.get():g}")
                self._collage_image_scale(image, number)
            entry.config(command=edit_scale)
            entry.bind("<KeyRelease>", edit_scale)
            entry.bind("<Return>", lambda e, apply=edit_scale: apply(e, final=True))
            entry.bind("<FocusOut>", lambda e, apply=edit_scale: apply(e, final=True))
            value.trace_add("write", slide_changed)
            self._iconbtn(scale_row, "↺", lambda var=value: var.set(100)).pack(side=tk.LEFT, padx=3)

    def _collage_image_scale(self, item, value):
        try:
            zoom = float(value.get() if hasattr(value, "get") else value) / 100.0
            if not math.isfinite(zoom): return
            zoom = min(3.0, max(0.1, zoom))
        except (ValueError, tk.TclError):
            return
        if item.get("zoom", 1.0) == zoom: return
        item["zoom"] = zoom
        self._render_collage_preview()

    def collage_add_images(self):
        paths = filedialog.askopenfilenames(filetypes=[("Immagini", "*.png *.jpg *.jpeg *.webp *.bmp"), ("Tutti i file", "*.*")])
        if not paths: return
        for p in paths:
            try:
                im = Image.open(p)
                self.collage_images.append({
                    "path": p, "name": os.path.splitext(os.path.basename(p))[0],
                    "img": im.convert("RGBA"), "info": dict(im.info), "offx": 0.5, "offy": 0.5,
                })
            except Exception:
                pass
        self._refresh_collage_list(); self._render_collage_preview()

    def collage_move(self, idx, delta):
        j = idx + delta
        if 0 <= j < len(self.collage_images):
            self.collage_images[idx], self.collage_images[j] = self.collage_images[j], self.collage_images[idx]
            self._refresh_collage_list(); self._render_collage_preview()

    def collage_remove(self, idx):
        if 0 <= idx < len(self.collage_images):
            del self.collage_images[idx]; self._refresh_collage_list(); self._render_collage_preview()

    # ---------- TESTI del collage ----------
    def _sel_collage_text(self):
        return next((t for t in self.collage_texts if t["uid"] == self.collage_text_sel), None)

    def add_collage_text(self):
        t = self.new_text_layer(); t.pop("target", None)
        self.collage_texts.append(t); self.collage_text_sel = t["uid"]
        self._sync_collage_text_controls(); self._render_collage_preview()

    def delete_collage_text(self):
        t = self._sel_collage_text()
        if t is None: return
        self.collage_texts.remove(t); self.collage_text_sel = None
        self._sync_collage_text_controls(); self._render_collage_preview()

    def _sync_collage_text_controls(self):
        if not hasattr(self, "entry_ctext"): return
        t = self._sel_collage_text()
        self._ctext_ui_lock = True
        try:
            if t is None:
                self.entry_ctext.config(state=tk.NORMAL); self.entry_ctext.delete("1.0", tk.END)
                self.entry_ctext.config(state=tk.DISABLED)
                self.lbl_ctext_sel.config(text=self.tr("t_none"))
            else:
                self.entry_ctext.config(state=tk.NORMAL)
                self.entry_ctext.delete("1.0", tk.END); self.entry_ctext.insert("1.0", t.get("text") or "")
                self.ctxt_size.set(int(t["size"])); self.ctxt_outline.set(int(t.get("outline", 0)))
                self.ctxt_opacity.set(int(t.get("opacity", 255))); self.ctxt_rot.set(int(t.get("rotation", 0)))
                self.ctxt_align.set(t.get("align", "left"))
                self.ctxt_swatch.config(bg=t.get("color", "#ffffff"))
                lab = (t.get("text") or "").replace("\n", " ")
                self.lbl_ctext_sel.config(text=(lab if len(lab) <= 22 else lab[:21] + "…"))
        finally:
            self._ctext_ui_lock = False

    def _apply_collage_text_controls(self, *a):
        if getattr(self, "_ctext_ui_lock", False): return
        t = self._sel_collage_text()
        if t is None: return
        t["text"] = self.entry_ctext.get("1.0", "end-1c")
        t["align"] = self.ctxt_align.get()
        for key, var, lo, hi in (("size", self.ctxt_size, 4, 800), ("outline", self.ctxt_outline, 0, 30),
                                 ("opacity", self.ctxt_opacity, 0, 255), ("rotation", self.ctxt_rot, -180, 180)):
            try: t[key] = max(lo, min(hi, int(var.get())))
            except Exception: pass
        self._render_collage_preview()

    def pick_collage_text_color(self):
        t = self._sel_collage_text()
        if t is None: return
        c = colorchooser.askcolor(color=t.get("color", "#ffffff"), title=self.tr("t_color"))
        if c and c[1]:
            t["color"] = c[1]; self.ctxt_swatch.config(bg=c[1]); self._render_collage_preview()

    def collage_change_signature(self, e=None):
        """Carica la firma scelta nella tab Collage (riusa raw_assets['firma'], sincronizza l'editor)."""
        sel = self.combo_firme_collage.get()
        if not sel: return
        self.current_signature_name = os.path.splitext(sel)[0]
        self.current_account_name = self.current_signature_name
        self.raw_assets["firma"] = Image.open(os.path.join(self.folder_firme, sel)).convert("RGBA")
        try: self.combo_firme.set(sel)   # tiene allineato il combo dell'editor
        except Exception: pass
        self.collage_sig_enabled.set(True)
        self._render_collage_preview()

    def collage_change_frame(self, e=None):
        """Carica la cornice scelta e rileva l'apertura trasparente (bbox del centro trasparente)."""
        sel = self.combo_cornici_collage.get()
        if not sel:
            self._collage_frame_img = None; self._collage_frame_opening = None; return
        try:
            self._collage_frame_img = Image.open(os.path.join(self.folder_cornici, sel)).convert("RGBA")
            self._collage_frame_opening = self._frame_opening_bbox(self._collage_frame_img)
        except Exception:
            self._collage_frame_img = None; self._collage_frame_opening = None
            self._render_collage_preview(); return
        self.collage_frame_enabled.set(True)
        self._render_collage_preview()

    def _frame_opening_bbox(self, frame_rgba):
        """Bounding box dell'apertura INTERNA trasparente della cornice.
        Rimuove prima la trasparenza esterna (connessa ai bordi) con un flood fill,
        così funziona anche con cornici che hanno gli angoli trasparenti."""
        w, h = frame_rgba.size
        alpha = frame_rgba.split()[3]
        transp = alpha.point(lambda a: 255 if a < 128 else 0).convert("L")  # 255 = trasparente
        try:
            seeds = [(0, 0), (w - 1, 0), (0, h - 1), (w - 1, h - 1), (w // 2, 0), (w // 2, h - 1), (0, h // 2), (w - 1, h // 2)]
            for sx, sy in seeds:
                if transp.getpixel((sx, sy)) == 255:
                    ImageDraw.floodfill(transp, (sx, sy), 128)  # marca l'esterno
            inner = transp.point(lambda v: 255 if v == 255 else 0)  # resta solo l'apertura interna
            bbox = inner.getbbox()
        except Exception:
            bbox = None
        if not bbox:
            m = int(min(w, h) * 0.06); bbox = (m, m, w - m, h - m)  # fallback: riquadro con margine
        return bbox

    def collage_pick_outline_color(self):
        c = colorchooser.askcolor(color=self.collage_outline_color, title="Colore del contorno delle vignette")
        if c and c[1]:
            self.collage_outline_color = c[1]
            self.collage_outline_swatch.config(bg=c[1])
            self._render_collage_preview()

    def collage_pick_color(self):
        c = colorchooser.askcolor(color=self.collage_gutter_color, title="Colore degli spazi / bordo")
        if c and c[1]:
            self.collage_gutter_color = c[1]
            self.collage_swatch.config(bg=c[1])
            self._render_collage_preview()

    def _compute_collage_layout(self, W, H, n, g):
        """Celle (x, y, cw, ch) in coordinate del file finale, con spazio 'g' tra le celle
        E come bordo esterno. La direzione dipende da collage_dir: 'cols' = colonne affiancate
        (verticali), 'rows' = righe impilate (orizzontali)."""
        if n <= 0: return []
        if self.collage_dir.get() == "grid":
            cols, rows = self._collage_grid_shape(n)
            cw = (W - (cols + 1) * g) / cols
            ch = (H - (rows + 1) * g) / rows
            if cw < 1 or ch < 1: return []
            cells = []
            for i in range(n):
                row, col = divmod(i, cols)
                x = g + col * (cw + g); y = g + row * (ch + g)
                x0, y0 = round(x), round(y)
                cells.append((x0, y0, max(1, round(x + cw) - x0), max(1, round(y + ch) - y0)))
            return cells
        horizontal = self.collage_dir.get() == "rows"
        cells = []
        if horizontal:
            inner_h = H - (n + 1) * g
            ch = inner_h / n
            cw = W - 2 * g
            if cw < 1 or ch < 1: return []
            y = float(g)
            for i in range(n):
                y0 = int(round(y)); y1 = int(round(y + ch))
                cells.append((g, y0, max(1, int(round(cw))), max(1, y1 - y0)))
                y += ch + g
        else:
            inner_w = W - (n + 1) * g
            cw = inner_w / n
            ch = H - 2 * g
            if cw < 1 or ch < 1: return []
            x = float(g)
            for i in range(n):
                x0 = int(round(x)); x1 = int(round(x + cw))
                cells.append((x0, g, max(1, x1 - x0), max(1, int(round(ch)))))
                x += cw + g
        return cells

    def _fit_cover(self, img, cw, ch, offx, offy, zoom=1.0):
        """Ritaglio 'cover': riempie (cw, ch) mantenendo le proporzioni, con pan (offx, offy) in 0..1."""
        iw, ih = img.size
        if iw <= 0 or ih <= 0: return Image.new("RGBA", (cw, ch), (0, 0, 0, 0))
        scale = max(cw / iw, ch / ih) * zoom
        sw = max(1, int(round(iw * scale))); sh = max(1, int(round(ih * scale)))
        scaled = img.resize((sw, sh), Image.Resampling.LANCZOS)
        max_x = sw - cw; max_y = sh - ch
        cx = int(round(max_x * offx)); cy = int(round(max_y * offy))
        piece = scaled.crop((cx, cy, cx + cw, cy + ch))
        background = Image.new("RGBA", (cw, ch), self.collage_gutter_color)
        return Image.alpha_composite(background, piece.convert("RGBA"))

    # ---------- modalità libera: helper geometrici ----------
    def _cover_overflow(self, img, cw, ch, zoom=1.0):
        """Dimensione dell'immagine scalata in 'cover' su (cw,ch) — serve per il pan del ritaglio."""
        iw, ih = img.size
        if iw <= 0 or ih <= 0: return cw, ch
        sc = max(cw / iw, ch / ih) * zoom
        return max(1, int(round(iw * sc))), max(1, int(round(ih * sc)))

    def _rot_xy(self, lx, ly, deg):
        """Ruota un offset locale di 'deg' gradi (positivo = orario, coordinate schermo y-giù)."""
        import math
        a = math.radians(deg); c, s = math.cos(a), math.sin(a)
        return lx * c - ly * s, lx * s + ly * c

    def _unrot_xy(self, dx, dy, deg):
        """Trasformazione inversa di _rot_xy: da offset canvas a offset locale della cella."""
        import math
        a = math.radians(deg); c, s = math.cos(a), math.sin(a)
        return dx * c + dy * s, -dx * s + dy * c

    @staticmethod
    def _poly_area(pts):
        n = len(pts)
        return 0.5 * sum(pts[i][0] * pts[(i + 1) % n][1] - pts[(i + 1) % n][0] * pts[i][1] for i in range(n))

    def _inset_polygon(self, pts, d, strict=False):
        """Restringe il poligono di 'd' px verso l'interno (offset dei lati + intersezione).
        Serve a generare il bordo bianco: due vignette che si toccano danno un distacco di 2*d,
        quindi la distanza risulta identica ovunque senza allineamenti a mano.

        strict=True ritorna None quando l'inset non è possibile (forma degenere/collassata),
        così il chiamante distingue il fallimento dal risultato — con strict=False torna
        l'originale. NON usare soglie sull'area lato chiamante: su poligoni grandi un inset
        sottile cambia l'area di pochissimo e verrebbe scambiato per un fallimento."""
        fail = None if strict else pts
        if d <= 0: return pts
        n = len(pts)
        cx = sum(p[0] for p in pts) / n; cy = sum(p[1] for p in pts) / n
        lines = []
        for i in range(n):
            x0, y0 = pts[i]; x1, y1 = pts[(i + 1) % n]
            dx, dy = x1 - x0, y1 - y0
            L = math.hypot(dx, dy)
            if L < 1e-9: return fail
            nx, ny = dy / L, -dx / L
            # sceglie la normale che punta verso il centro (robusto per qualsiasi orientamento)
            mx, my = (x0 + x1) / 2, (y0 + y1) / 2
            if (mx + nx - cx) ** 2 + (my + ny - cy) ** 2 > (mx - cx) ** 2 + (my - cy) ** 2: nx, ny = -nx, -ny
            lines.append(((x0 + nx * d, y0 + ny * d), (x1 + nx * d, y1 + ny * d)))
        out = []
        for i in range(n):
            (ax, ay), (bx, by) = lines[i - 1]
            (px, py), (qx, qy) = lines[i]
            r1x, r1y = bx - ax, by - ay; r2x, r2y = qx - px, qy - py
            den = r1x * r2y - r1y * r2x
            if abs(den) < 1e-9: return fail         # lati paralleli: rinuncio all'inset
            t = ((px - ax) * r2y - (py - ay) * r2x) / den
            out.append([ax + r1x * t, ay + r1y * t])
        # se il poligono si è ribaltato o è collassato, tengo l'originale
        a0, a1 = self._poly_area(pts), self._poly_area(out)
        if a1 == 0 or (a0 > 0) != (a1 > 0) or abs(a1) < abs(a0) * 0.02: return fail
        return out

    @staticmethod
    def _rect_pts(cx, cy, w, h):
        """Quadrilatero rettangolare (TL, TR, BR, BL) da centro + dimensioni, in coord normalizzate."""
        hw, hh = w / 2.0, h / 2.0
        return [[cx - hw, cy - hh], [cx + hw, cy - hh], [cx + hw, cy + hh], [cx - hw, cy + hh]]

    def _normalize_cell(self, cell):
        """Converte una cella vecchio formato (x,y,w,h,rot) nel nuovo formato a 4 angoli liberi."""
        if "pts" in cell and len(cell.get("pts") or []) == 4: return cell
        cx, cy = cell.get("x", .5), cell.get("y", .5)
        w, h = cell.get("w", .3), cell.get("h", .3)
        pts = self._rect_pts(cx, cy, w, h)
        rot = cell.get("rot", 0) or 0
        if rot:  # applica la vecchia rotazione agli angoli
            out = []
            for px, py in pts:
                rx, ry = self._rot_xy(px - cx, py - cy, rot)
                out.append([cx + rx, cy + ry])
            pts = out
        return {"pts": pts}

    def _ensure_free_cells(self, W, H, g=None):
        """Allinea free_cells al numero di immagini; le nuove partono dal layout a colonne."""
        n = len(self.collage_images)
        if len(self.free_cells) > n: del self.free_cells[n:]
        for i, c in enumerate(self.free_cells):          # migra eventuali celle vecchio formato
            self.free_cells[i] = self._normalize_cell(c)
        if len(self.free_cells) < n:
            if g is None:
                try: g = max(0, self.collage_gutter.get())
                except Exception: g = 0
            cells = self._default_free_cells(W, H, g, n)
            for i in range(len(self.free_cells), n):
                self.free_cells.append(cells[i] if i < len(cells) else {"pts": self._rect_pts(0.5, 0.5, 0.3, 0.3)})

    def _diagonal_free_cells(self, W, H, g, n, slant):
        """Celle a divisori inclinati, nel verso scelto in 'Direzione'.

        I divisori ESTERNI restano dritti sul bordo pagina: se si inclinassero anche
        quelli, agli angoli resterebbero dei triangoli vuoti. Si inclinano solo i
        divisori interni, così la pagina resta coperta e con 2 immagini si ottiene
        il classico taglio in diagonale."""
        if n <= 0: return []
        half = g / 2.0
        x0 = half / W; x1 = 1.0 - half / W
        y0 = half / H; y1 = 1.0 - half / H
        horizontal = self.collage_dir.get() == "rows"
        span = (y1 - y0) if horizontal else (x1 - x0)
        step = span / n
        # scarto del divisore rispetto alla posizione dritta, per lato.
        # slant 100% => d = step: con 2 immagini il taglio va da spigolo a spigolo.
        # Oltre step i divisori scavalcherebbero il bordo e le celle si annoderebbero.
        d = max(0.0, min(1.0, slant / 100.0)) * step
        a0, a1 = (y0, y1) if horizontal else (x0, x1)
        def divisore(i):
            """(inizio, fine) del divisore i: dritto se è un bordo, inclinato se interno."""
            base = a0 + i * step
            if i == 0 or i == n: return a0 if i == 0 else a1, a0 if i == 0 else a1
            return base + d, base - d
        out = []
        for i in range(n):
            s_a, e_a = divisore(i); s_b, e_b = divisore(i + 1)
            if horizontal:
                # divisori orizzontali inclinati: variano da sinistra (s) a destra (e)
                out.append({"pts": [[x0, s_a], [x1, e_a], [x1, e_b], [x0, s_b]]})
            else:
                # divisori verticali inclinati: variano dall'alto (s) al basso (e)
                out.append({"pts": [[s_a, y0], [s_b, y0], [e_b, y1], [e_a, y1]]})
        return out

    def _free_diagonal(self):
        """Rigenera le vignette con i tagli in diagonale."""
        try:
            W = max(1, self.collage_w.get()); H = max(1, self.collage_h.get()); g = max(0, self.collage_gutter.get())
            slant = max(0, min(100, int(self.free_slant.get())))
        except Exception:
            return
        n = len(self.collage_images)
        if n <= 0: return
        self.free_cells = self._diagonal_free_cells(W, H, g, n, slant)
        self.free_sel = None; self._render_collage_preview()

    def _default_free_cells(self, W, H, g, n):
        """Celle che si TOCCANO, con mezzo spazio di margine dal bordo pagina, nella direzione
        scelta. Dopo l'inset di g/2 il distacco risulta g sia tra le vignette sia verso il bordo."""
        if n <= 0: return []
        half = (g / 2.0)
        x0 = half / W; x1 = 1.0 - half / W
        y0 = half / H; y1 = 1.0 - half / H
        out = []
        if self.collage_dir.get() == "grid":
            cols, rows = self._collage_grid_shape(n)
            cw = (x1 - x0) / cols; ch = (y1 - y0) / rows
            for i in range(n):
                row, col = divmod(i, cols)
                ax = x0 + col * cw; ay = y0 + row * ch
                out.append({"pts": [[ax, ay], [ax + cw, ay], [ax + cw, ay + ch], [ax, ay + ch]]})
            return out
        if self.collage_dir.get() == "rows":
            rowh = (y1 - y0) / n
            for i in range(n):
                ay = y0 + i * rowh; by = ay + rowh
                out.append({"pts": [[x0, ay], [x1, ay], [x1, by], [x0, by]]})
        else:
            colw = (x1 - x0) / n
            for i in range(n):
                ax = x0 + i * colw; bx = ax + colw
                out.append({"pts": [[ax, y0], [bx, y0], [bx, y1], [ax, y1]]})
        return out

    def _free_reset_from_cols(self):
        """Rigenera tutte le celle libere come colonne affiancate (punto di partenza pulito)."""
        try: W = max(1, self.collage_w.get()); H = max(1, self.collage_h.get()); g = max(0, self.collage_gutter.get())
        except Exception: return
        self.free_cells = self._default_free_cells(W, H, g, len(self.collage_images))
        self.free_sel = None; self._render_collage_preview()

    def _snap_point(self, nx, ny, skip_idx):
        """Aggancio magnetico: attira l'angolo trascinato sugli angoli delle ALTRE vignette
        e sui bordi pagina. x e y si agganciano in modo indipendente (aiuta anche l'allineamento)."""
        if not self.free_snap.get(): return nx, ny
        tol_x = 9.0 / max(1e-6, self._free_px_x); tol_y = 9.0 / max(1e-6, self._free_px_y)
        bx, by = nx, ny; dbx, dby = tol_x, tol_y
        for j, cell in enumerate(self.free_cells):
            if j == skip_idx: continue
            for p in cell["pts"]:
                if abs(p[0] - nx) < dbx: dbx = abs(p[0] - nx); bx = p[0]
                if abs(p[1] - ny) < dby: dby = abs(p[1] - ny); by = p[1]
        try: half_x = (self.collage_gutter.get() / 2.0) / max(1, self.collage_w.get()); half_y = (self.collage_gutter.get() / 2.0) / max(1, self.collage_h.get())
        except Exception: half_x = half_y = 0.0
        for v in (0.0, half_x, 1.0 - half_x, 1.0):
            if abs(v - nx) < dbx: dbx = abs(v - nx); bx = v
        for v in (0.0, half_y, 1.0 - half_y, 1.0):
            if abs(v - ny) < dby: dby = abs(v - ny); by = v
        return bx, by

    def _collage_grid_shape(self, n):
        try:
            cols = min(100, max(1, self.collage_grid_cols.get()))
            rows = min(100, max(1, self.collage_grid_rows.get()))
        except tk.TclError:
            cols, rows = 2, 2
        return cols, max(rows, (n + cols - 1) // cols)

    def _collage_grid_changed(self):
        try:
            self.collage_grid_cols.get(); self.collage_grid_rows.get()
        except tk.TclError:
            return
        if self.collage_dir.get() == "grid": self._collage_dir_changed()

    def _collage_dir_changed(self):
        """Cambio direzione della griglia automatica. In modalità libera rigenera le celle,
        altrimenti il nuovo verso non si vedrebbe (le forme sono già state definite)."""
        if self.collage_mode.get() == "free":
            self._free_reset_from_cols()
        else:
            self._render_collage_preview()

    def _collage_mode_changed(self):
        free = self.collage_mode.get() == "free"
        if free:
            self.cols_hint.pack_forget(); self.free_panel.pack(fill=tk.X)
            try: self._ensure_free_cells(max(1, self.collage_w.get()), max(1, self.collage_h.get()))
            except Exception: pass
            self._refresh_layouts_list()
        else:
            self.free_panel.pack_forget(); self.cols_hint.pack(anchor="w", pady=(8, 0))
        self._render_collage_preview()

    def _free_rotate(self, direction):
        """Ruota il quadrilatero selezionato attorno al suo centro, del passo impostato."""
        if self.free_sel is None or self.free_sel >= len(self.free_cells): return
        try: step = max(1, int(self.free_rot.get()))
        except Exception: step = 5
        cell = self.free_cells[self.free_sel]; pts = cell["pts"]
        # centro in coordinate CANVAS: la rotazione dev'essere visivamente circolare anche se W≠H
        cx = sum(p[0] for p in pts) / 4.0 * self._free_px_x
        cy = sum(p[1] for p in pts) / 4.0 * self._free_px_y
        deg = step * (1 if direction > 0 else -1)
        for p in pts:
            px_c, py_c = p[0] * self._free_px_x, p[1] * self._free_px_y
            rx, ry = self._rot_xy(px_c - cx, py_c - cy, deg)
            p[0] = (cx + rx) / self._free_px_x; p[1] = (cy + ry) / self._free_px_y
        self._render_collage_preview()

    def _free_rot_set(self):
        pass  # lo spinbox ora è solo il passo di rotazione: nessuna azione immediata

    def _free_straighten(self):
        """Raddrizza la cella selezionata: torna a un rettangolo dal suo ingombro."""
        if self.free_sel is None or self.free_sel >= len(self.free_cells): return
        pts = self.free_cells[self.free_sel]["pts"]
        xs = [p[0] for p in pts]; ys = [p[1] for p in pts]
        x0, x1 = min(xs), max(xs); y0, y1 = min(ys), max(ys)
        self.free_cells[self.free_sel]["pts"] = [[x0, y0], [x1, y0], [x1, y1], [x0, y1]]
        self._render_collage_preview()

    # ---------- costruzione condivisa (anteprima E salvataggio) ----------
    def _build_collage(self, W, H, g, s=1.0):
        """Costruisce il collage alla scala s. Ritorna (img RGB, rects) con la geometria di ogni
        cella nello spazio dell'immagine prodotta. Usata sia dall'anteprima che dal salvataggio,
        così quello che vedi è esattamente quello che viene salvato."""
        pw, ph = max(1, int(W * s)), max(1, int(H * s))
        img = Image.new("RGB", (pw, ph), self.collage_gutter_color)
        rects = []
        n = len(self.collage_images)
        if n == 0: return img, rects
        if self.collage_mode.get() == "free":
            self._ensure_free_cells(W, H, g)
            inset = (g / 2.0) * s   # il bordo bianco nasce restringendo ogni vignetta di metà spazio
            for i, item in enumerate(self.collage_images):
                if i >= len(self.free_cells): break
                raw_pts = [(p[0] * W * s, p[1] * H * s) for p in self.free_cells[i]["pts"]]
                pts = self._inset_polygon([list(p) for p in raw_pts], inset)
                xs = [p[0] for p in pts]; ys = [p[1] for p in pts]
                x0, y0 = int(math.floor(min(xs))), int(math.floor(min(ys)))
                x1, y1 = int(math.ceil(max(xs))), int(math.ceil(max(ys)))
                bw, bh = max(1, x1 - x0), max(1, y1 - y0)
                piece = self._fit_cover(item["img"], bw, bh, item["offx"], item["offy"], item.get("zoom", 1.0))
                # maschera poligonale in supersampling: bordi diagonali lisci invece che a scaletta
                ss = 4 if bw * bh <= 4_000_000 else 2
                mk = Image.new("L", (bw * ss, bh * ss), 0)
                ImageDraw.Draw(mk).polygon([((px - x0) * ss, (py - y0) * ss) for px, py in pts], fill=255)
                mask = mk.resize((bw, bh), Image.Resampling.LANCZOS)
                img.paste(piece.convert("RGB"), (x0, y0), mask)
                sw, sh = self._cover_overflow(item["img"], bw, bh, item.get("zoom", 1.0))
                # per l'interazione servono gli angoli ORIGINALI (quelli che l'utente trascina),
                # mentre 'draw' è la forma effettivamente disegnata (ristretta dall'inset)
                rects.append({"pts": raw_pts, "draw": pts, "ovx": sw - bw, "ovy": sh - bh})
        else:
            for i, (x, y, cw0, ch0) in enumerate(self._compute_collage_layout(W, H, n, g)):
                item = self.collage_images[i]
                px, py = int(x * s), int(y * s)
                cw = max(1, int(cw0 * s)); ch = max(1, int(ch0 * s))
                piece = self._fit_cover(item["img"], cw, ch, item["offx"], item["offy"], item.get("zoom", 1.0))
                img.paste(piece.convert("RGB"), (px, py))
                sw, sh = self._cover_overflow(item["img"], cw, ch, item.get("zoom", 1.0))
                rects.append({"pts": [(px, py), (px + cw, py), (px + cw, py + ch), (px, py + ch)],
                              "ovx": sw - cw, "ovy": sh - ch})
        self._draw_cell_outlines(img, rects, s)
        return img, rects

    def _draw_cell_outlines(self, img, rects, s):
        """Contorno di ogni vignetta, disegnato DOPO tutti i riempimenti così non viene coperto
        dalle vignette adiacenti.

        Il tratto sta TUTTO DENTRO la vignetta (anello: poligono meno il poligono ristretto):
        il nero coincide con il bordo reale dell'immagine e non invade lo spazio bianco, che
        resta quindi esattamente della larghezza impostata."""
        try: wpx = max(0, int(self.collage_outline.get()))
        except Exception: return
        if wpx <= 0: return
        lw = max(1.0, wpx * s)
        for r in rects:
            pts = [list(p) for p in (r.get("draw") or r["pts"])]
            xs = [p[0] for p in pts]; ys = [p[1] for p in pts]
            x0 = int(math.floor(min(xs))) - 1; y0 = int(math.floor(min(ys))) - 1
            x1 = int(math.ceil(max(xs))) + 1;  y1 = int(math.ceil(max(ys))) + 1
            bw, bh = max(1, x1 - x0), max(1, y1 - y0)
            ss = 4 if bw * bh <= 2_000_000 else 2
            mk = Image.new("L", (bw * ss, bh * ss), 0)
            d = ImageDraw.Draw(mk)
            d.polygon([((px - x0) * ss, (py - y0) * ss) for px, py in pts], fill=255)
            inner = self._inset_polygon(pts, lw, strict=True)
            # inner is None solo se la vignetta è troppo piccola per contenere l'anello: resta piena
            if inner is not None:
                d.polygon([((px - x0) * ss, (py - y0) * ss) for px, py in inner], fill=0)
            mask = mk.resize((bw, bh), Image.Resampling.LANCZOS)
            ox, oy = max(0, x0), max(0, y0)
            crop = mask.crop((ox - x0, oy - y0, min(img.width, x1) - x0, min(img.height, y1) - y0))
            if crop.width <= 0 or crop.height <= 0: continue
            img.paste(self.collage_outline_color, (ox, oy), crop)

    def _compose_with_frame(self, base_rgb, frame_rgba):
        """Unisce collage e cornice. Ritorna (immagine, scala_applicata, (offset_x, offset_y)),
        dove l'offset è la posizione dell'angolo (0,0) del collage dentro il risultato —
        serve all'anteprima per sapere dove disegnare i riquadri delle celle.

        Due modalità:
        • inside → il collage viene rimpicciolito DENTRO l'apertura trasparente (default)
        • fill   → il collage RIEMPIE tutta la cornice e la decorazione ci va sopra,
                   come la miniatura dell'Editor. Serve a unire più varianti in un'unica
                   cornice. Scala per coprire e ritaglia il di più al centro, così le
                   proporzioni non vengono mai deformate."""
        fw, fh = frame_rgba.size
        if self.collage_frame_fit.get() == "fill":
            s = max(fw / base_rgb.width, fh / base_rgb.height)
            nw, nh = max(1, int(round(base_rgb.width * s))), max(1, int(round(base_rgb.height * s)))
            scaled = base_rgb.resize((nw, nh), Image.Resampling.LANCZOS)
            offx, offy = (nw - fw) // 2, (nh - fh) // 2
            out = scaled.crop((offx, offy, offx + fw, offy + fh))
            place = (-offx, -offy)
        else:
            # l'apertura è memorizzata nelle coordinate della cornice a piena risoluzione:
            # va riscalata se qui arriva una cornice ridotta (anteprima)
            k = fw / max(1, self._collage_frame_img.width) if self._collage_frame_img else 1.0
            src = self._collage_frame_opening or (0, 0, fw, fh)
            ox0, oy0, ox1, oy1 = [v * k for v in src]
            inner_w = max(1, int(ox1 - ox0)); inner_h = max(1, int(oy1 - oy0))
            s = min(inner_w / base_rgb.width, inner_h / base_rgb.height)
            nw, nh = max(1, int(base_rgb.width * s)), max(1, int(base_rgb.height * s))
            coll = base_rgb.resize((nw, nh), Image.Resampling.LANCZOS)
            out = Image.new("RGB", (fw, fh), self.collage_gutter_color)
            place = (int(ox0) + (inner_w - nw) // 2, int(oy0) + (inner_h - nh) // 2)
            out.paste(coll, place)
        return Image.alpha_composite(out.convert("RGBA"), frame_rgba).convert("RGB"), s, place

    def _paste_collage_texts(self, img, W):
        """Incolla i testi del collage. W = larghezza del documento finale: il rapporto
        img.width/W è il fattore che riporta corpo del font e contorno alla scala corrente."""
        scale = img.width / float(max(1, W))
        rects = []
        for t in self.collage_texts:
            if not t.get("visible", True): continue
            r = self._paste_text_layer(img, t, (t["pos"][0] * img.width, t["pos"][1] * img.height), scale)
            rects.append((t, r))
        return rects

    @staticmethod
    def _signature_alpha(image, opacity):
        image = image.convert("RGBA").copy()
        factor = max(0, min(100, opacity)) / 100.0
        image.putalpha(image.getchannel("A").point(lambda a: round(a * factor)))
        return image

    def _signature_opacity_control(self, parent, variable, collage=False):
        self._mk(tk.Label, parent, "signature_opacity", bg=self.C["card"], fg=self.C["muted"],
                 font=(self.FONT, 8)).pack(anchor="w", pady=(4, 0))
        tk.Scale(parent, from_=0, to=100, resolution=1, orient=tk.HORIZONTAL, variable=variable,
                 bg=self.C["card"], fg=self.C["text"], troughcolor=self.C["input"],
                 highlightthickness=0).pack(fill=tk.X)
        def changed(*args):
            if collage: self._render_collage_preview()
            else: self.draw_element("firma")
        variable.trace_add("write", changed)

    def _paste_collage_signature(self, img):
        """Incolla la firma sul collage; ritorna il rect (x0,y0,x1,y1) o None."""
        firma = self.raw_assets.get("firma")
        if not self.collage_sig_enabled.get() or firma is None: return None
        w, h = img.size
        sw = max(1, int((self.collage_sig_scale.get() / 100.0) * w))
        sh = max(1, int(firma.height * (sw / firma.width)))
        sig = firma.resize((sw, sh), Image.Resampling.LANCZOS)
        sig = self._signature_alpha(sig, self.collage_sig_opacity.get())
        sx = min(max(0, int(self.collage_sig_pos[0] * w)), max(0, w - sw))
        sy = min(max(0, int(self.collage_sig_pos[1] * h)), max(0, h - sh))
        img.paste(sig, (sx, sy), sig)
        return (sx, sy, sx + sw, sy + sh)

    def _render_collage_preview(self, event=None):
        cv = getattr(self, "collage_canvas", None)
        if cv is None: return
        try:
            W = max(1, self.collage_w.get()); H = max(1, self.collage_h.get()); g = max(0, self.collage_gutter.get())
        except Exception:
            return  # valore ancora incompleto durante la digitazione: salto il render
        cv.delete("all"); self._collage_cells = []; self._collage_sig_rect = None
        n = len(self.collage_images)
        free = self.collage_mode.get() == "free"
        aw = max(50, cv.winfo_width()); ah = max(50, cv.winfo_height())
        frame = self._collage_frame_img if self.collage_frame_enabled.get() else None

        # 1) collage alla scala di lavoro (rects in "collage space")
        work = min((aw - 24) / W, (ah - 24) / H)
        if work <= 0: work = 0.1
        collage_img, cell_rects = self._build_collage(W, H, g, work)
        cpw, cph = collage_img.size
        sig_rect_cs = self._paste_collage_signature(collage_img)
        text_rects_cs = self._paste_collage_texts(collage_img, W)

        # 2) placement finale: con cornice il collage entra nell'apertura; senza, riempie il canvas
        if frame is None:
            disp = collage_img; s = 1.0; place_x = place_y = 0; dpw, dph = cpw, cph
        else:
            fw, fh = frame.size
            fscale = min((aw - 24) / fw, (ah - 24) / fh)
            if fscale <= 0: fscale = 0.1
            fpw, fph = max(1, int(fw * fscale)), max(1, int(fh * fscale))
            frame_prev = frame.resize((fpw, fph), Image.Resampling.LANCZOS)
            disp, s, (place_x, place_y) = self._compose_with_frame(collage_img, frame_prev)
            dpw, dph = fpw, fph

        # 3) mostra centrato
        ox = (aw - dpw) // 2; oy = (ah - dph) // 2
        self._collage_origin = (ox, oy)
        self._collage_pw, self._collage_ph = cpw * s, cph * s   # px visualizzati del collage (per il drag firma)
        self._collage_tk = ImageTk.PhotoImage(disp)
        cv.create_image(ox, oy, anchor=tk.NW, image=self._collage_tk)

        # 4) geometria in coordinate canvas: collage_space * s + offset
        bx, by = ox + place_x, oy + place_y
        # riferimenti per convertire canvas <-> coordinate normalizzate delle celle libere
        self._free_bx, self._free_by = bx, by
        self._free_px_x = max(1e-6, W * work * s); self._free_px_y = max(1e-6, H * work * s)
        for i, r in enumerate(cell_rects):
            gc = {"pts": [(bx + px * s, by + py * s) for px, py in r["pts"]],
                  "ovx": r["ovx"] * s, "ovy": r["ovy"] * s}
            self._collage_cells.append(gc)
            sel = free and self.free_sel == i
            cv.create_polygon(gc["pts"], outline=(self.C["amber"] if sel else self.C["line"]),
                fill="", width=(2 if sel else 1))
            if sel:
                for (hx, hy) in gc["pts"]:
                    cv.create_rectangle(hx - 5, hy - 5, hx + 5, hy + 5, fill=self.C["amber"], outline="#ffffff")
        if sig_rect_cs:
            sx, sy, sx1, sy1 = sig_rect_cs
            self._collage_sig_rect = (bx + sx * s, by + sy * s, bx + sx1 * s, by + sy1 * s)
            x0, y0, x1, y1 = self._collage_sig_rect
            cv.create_rectangle(x0, y0, x1, y1, outline=self.C["accent"], width=1, dash=(3, 2))
        # rettangoli dei testi, per selezione e trascinamento
        self._collage_text_rects = []
        for t, r in text_rects_cs:
            if not r: continue
            rc = (bx + r[0] * s, by + r[1] * s, bx + r[2] * s, by + r[3] * s)
            self._collage_text_rects.append((t, rc))
            if self.collage_text_sel == t["uid"]:
                cv.create_rectangle(rc[0] - 2, rc[1] - 2, rc[2] + 2, rc[3] + 2, outline=self.C["amber"], width=2)
        if n == 0:
            cv.create_text(aw // 2, ah // 2, text=self.tr("c_empty"),
                fill=self.C["faint"], font=(self.FONT, 13, "bold"))
        # riquadro info: la dimensione mostrata è quella REALE del file finale
        out_w, out_h = (frame.size if frame is not None else (W, H))
        unit = self.tr("c_rows") if self.collage_dir.get() == "rows" else self.tr("c_columns")
        layout_txt = f"{n} {self.tr('c_panels_free')}" if free else f"{n} {unit}   •   {self.tr('c_gap')} {g}px"
        if not free and self.collage_dir.get() == "grid":
            cols, rows = self._collage_grid_shape(n)
            layout_txt = f"{self.tr('c_dir_grid')} {cols} × {rows}   •   {self.tr('c_gap')} {g}px"
        readout = f"{out_w} × {out_h} px   •   {layout_txt}" + (f"   •   {self.tr('c_with_frame')}" if frame is not None else "")
        cv.create_rectangle(8, 8, 8 + 9 * len(readout), 30, fill=self.C["card"], outline=self.C["line"])
        cv.create_text(14, 19, anchor="w", text=readout, fill=self.C["text"], font=(self.FONT, 9, "bold"))

    def _cell_corner_points(self, gc):
        """4 angoli (in coordinate canvas) della cella."""
        return list(gc["pts"])

    def _cell_hit(self, gc, px, py):
        """Point-in-polygon (ray casting) — funziona con quadrilateri di forma qualsiasi."""
        pts = gc["pts"]; inside = False; n = len(pts)
        for k in range(n):
            x0, y0 = pts[k]; x1, y1 = pts[(k + 1) % n]
            if (y0 > py) != (y1 > py):
                xint = (x1 - x0) * (py - y0) / ((y1 - y0) or 1e-9) + x0
                if px < xint: inside = not inside
        return inside

    def _collage_press(self, e):
        self._collage_drag_idx = None; self._collage_sig_drag = False; self._free_action = None
        free = self.collage_mode.get() == "free"
        self._collage_text_drag = None
        # i testi hanno la priorità sul click (stanno sopra tutto)
        for t, rc in reversed(getattr(self, "_collage_text_rects", [])):
            if rc[0] <= e.x <= rc[2] and rc[1] <= e.y <= rc[3]:
                self.collage_text_sel = t["uid"]; self._collage_text_drag = t
                self._collage_last = (e.x, e.y)
                self.collage_canvas.config(cursor="fleur")
                self._sync_collage_text_controls(); self._render_collage_preview(); return
        if self._collage_text_rects and self.collage_text_sel is not None:
            self.collage_text_sel = None; self._sync_collage_text_controls()
        # poi la firma
        if self._collage_sig_rect:
            x0, y0, x1, y1 = self._collage_sig_rect
            if x0 <= e.x <= x1 and y0 <= e.y <= y1:
                self._collage_sig_drag = True; self._collage_last = (e.x, e.y)
                self.collage_canvas.config(cursor="fleur"); return
        if not free:
            for i, c in enumerate(self._collage_cells):
                if self._cell_hit(c, e.x, e.y):
                    self._collage_drag_idx = i; self._collage_last = (e.x, e.y)
                    self.collage_canvas.config(cursor="fleur"); return
            return
        # --- modalità libera ---
        # 1) maniglie della cella selezionata
        if self.free_sel is not None and self.free_sel < len(self._collage_cells):
            for k, (hx, hy) in enumerate(self._cell_corner_points(self._collage_cells[self.free_sel])):
                if abs(e.x - hx) <= 7 and abs(e.y - hy) <= 7:
                    # SHIFT = ridimensionamento rettangolare (angolo opposto fisso); altrimenti angolo libero
                    self._free_action = "rect" if (e.state & 0x0001) else "corner"
                    self._free_handle = k
                    self._collage_drag_idx = self.free_sel; self._collage_last = (e.x, e.y)
                    self.collage_canvas.config(cursor="sizing"); return
        # 2) corpo della cella (dalla più in alto)
        for i in range(len(self._collage_cells) - 1, -1, -1):
            if self._cell_hit(self._collage_cells[i], e.x, e.y):
                self.free_sel = i; self._collage_drag_idx = i; self._collage_last = (e.x, e.y)
                if i < len(self.free_cells): self.free_rot.set(int(self.free_cells[i].get("rot", 0)))
                # Ctrl = sposta il ritaglio dentro il riquadro, altrimenti sposta il riquadro
                self._free_action = "pan" if (e.state & 0x0004) else "move"
                self.collage_canvas.config(cursor="hand2" if self._free_action == "pan" else "fleur")
                self._render_collage_preview(); return
        self.free_sel = None; self._render_collage_preview()

    def _collage_drag(self, e):
        if self._collage_text_drag is not None:
            dx = e.x - self._collage_last[0]; dy = e.y - self._collage_last[1]
            self._collage_last = (e.x, e.y)
            pw = max(1, self._collage_pw); ph = max(1, self._collage_ph)
            t = self._collage_text_drag
            t["pos"] = (min(1.0, max(-0.2, t["pos"][0] + dx / pw)), min(1.0, max(-0.2, t["pos"][1] + dy / ph)))
            self._render_collage_preview(); return
        if self._collage_sig_drag:
            dx = e.x - self._collage_last[0]; dy = e.y - self._collage_last[1]
            self._collage_last = (e.x, e.y)
            pw = max(1, self._collage_pw); ph = max(1, self._collage_ph)
            self.collage_sig_pos = (min(1.0, max(0.0, self.collage_sig_pos[0] + dx / pw)),
                                    min(1.0, max(0.0, self.collage_sig_pos[1] + dy / ph)))
            self._render_collage_preview(); return
        i = self._collage_drag_idx
        if i is None or i >= len(self.collage_images): return
        c = self._collage_cells[i]; item = self.collage_images[i]
        dx = e.x - self._collage_last[0]; dy = e.y - self._collage_last[1]
        self._collage_last = (e.x, e.y)
        act = self._free_action
        if act is None or act == "pan":
            # sposta il ritaglio dentro il riquadro
            if c["ovx"] != 0: item["offx"] = min(1.0, max(0.0, item["offx"] - dx / c["ovx"]))
            if c["ovy"] != 0: item["offy"] = min(1.0, max(0.0, item["offy"] - dy / c["ovy"]))
        elif act == "move":
            cell = self.free_cells[i]; ndx = dx / self._free_px_x; ndy = dy / self._free_px_y
            for p in cell["pts"]: p[0] += ndx; p[1] += ndy
        elif act == "corner":
            # muove SOLO l'angolo trascinato → vignette trapezoidali/storte
            cell = self.free_cells[i]; k = self._free_handle
            nx, ny = self._snap_point((e.x - self._free_bx) / self._free_px_x,
                                      (e.y - self._free_by) / self._free_px_y, i)
            cell["pts"][k][0] = nx; cell["pts"][k][1] = ny
        elif act == "rect":
            # SHIFT: ridimensionamento rettangolare classico, angolo opposto fermo
            cell = self.free_cells[i]; k = self._free_handle
            ox, oy = cell["pts"][(k + 2) % 4]
            nx, ny = self._snap_point((e.x - self._free_bx) / self._free_px_x,
                                      (e.y - self._free_by) / self._free_px_y, i)
            x0, x1 = min(ox, nx), max(ox, nx); y0, y1 = min(oy, ny), max(oy, ny)
            if x1 - x0 < 0.01: x1 = x0 + 0.01
            if y1 - y0 < 0.01: y1 = y0 + 0.01
            cell["pts"] = [[x0, y0], [x1, y0], [x1, y1], [x0, y1]]
        self._render_collage_preview()

    def _collage_release(self, e):
        self._collage_drag_idx = None; self._collage_sig_drag = False; self._free_action = None
        self._collage_text_drag = None
        self.collage_canvas.config(cursor="")

    # ---------- preset di layout ----------
    def _refresh_layouts_list(self):
        try:
            names = sorted(os.path.splitext(f)[0] for f in os.listdir(self.folder_layouts) if f.lower().endswith(".json"))
        except Exception:
            names = []
        if hasattr(self, "combo_layouts"): self.combo_layouts["values"] = names
        return names

    def layout_save(self):
        if self.collage_mode.get() != "free" or not self.free_cells:
            messagebox.showwarning("Layout", "Passa in modalità Libero e componi la struttura prima di salvarla.")
            return
        name = simpledialog.askstring("Salva layout", "Nome del preset:", parent=self.root)
        if not name: return
        name = re.sub(r'[\\/:*?"<>|]', "_", name.strip())
        if not name: return
        try:
            data = {"cells": [{"pts": [[round(p[0], 6), round(p[1], 6)] for p in c["pts"]]} for c in self.free_cells]}
            with open(os.path.join(self.folder_layouts, f"{name}.json"), "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            self._refresh_layouts_list(); self.combo_layouts.set(name)
            messagebox.showinfo("Layout", f"Preset '{name}' salvato ({len(self.free_cells)} riquadri).")
        except Exception as ex:
            messagebox.showerror("Layout", str(ex))

    def layout_load(self, e=None):
        name = self.combo_layouts.get()
        if not name: return
        try:
            with open(os.path.join(self.folder_layouts, f"{name}.json"), "r", encoding="utf-8") as f:
                data = json.load(f)
            cells = data.get("cells", [])
        except Exception as ex:
            messagebox.showerror("Layout", str(ex)); return
        self.collage_mode.set("free")
        try: W = max(1, self.collage_w.get()); H = max(1, self.collage_h.get())
        except Exception: W = H = 1000
        self._ensure_free_cells(W, H)
        for i, c in enumerate(cells):
            if i >= len(self.free_cells): break
            # accetta sia il nuovo formato a 4 angoli sia i preset vecchi (x,y,w,h,rot)
            self.free_cells[i] = self._normalize_cell(c if "pts" not in c else
                {"pts": [[float(p[0]), float(p[1])] for p in c["pts"]]})
        self.free_sel = None
        self._collage_mode_changed()

    def layout_delete(self):
        name = self.combo_layouts.get()
        if not name: return
        p = os.path.join(self.folder_layouts, f"{name}.json")
        if not os.path.exists(p): return
        if not messagebox.askyesno("Layout", f"Eliminare il preset '{name}'?"): return
        try:
            os.remove(p); self.combo_layouts.set(""); self._refresh_layouts_list()
        except Exception as ex:
            messagebox.showerror("Layout", str(ex))

    def collage_save(self):
        if not self.collage_images:
            messagebox.showwarning("Collage", "Aggiungi almeno un'immagine.")
            return
        try:
            try:
                W = max(1, self.collage_w.get()); H = max(1, self.collage_h.get()); g = max(0, self.collage_gutter.get())
            except Exception:
                messagebox.showwarning("Collage", "Dimensioni non valide: controlla larghezza/altezza/spazio.")
                return
            n = len(self.collage_images)
            if self.collage_mode.get() != "free" and not self._compute_collage_layout(W, H, n, g):
                messagebox.showerror("Collage", "Formato non valido: colonne troppo strette per lo spazio scelto.")
                return
            # stessa funzione usata dall'anteprima → il file è identico a quello che vedi
            base, _ = self._build_collage(W, H, g, 1.0)
            self._paste_collage_signature(base)   # firma full-res
            self._paste_collage_texts(base, W)    # testi full-res
            ts = datetime.now().strftime("%Y%m%d_%H%M%S")
            saved = []
            # 1) collage "nudo", sempre salvato, con le dimensioni impostate (W × H)
            img_path = os.path.join(self.output_folder, f"collage_{ts}.png")
            base.save(img_path, "PNG", optimize=self.optimize_png.get())
            saved.append(f"collage_{ts}.png  ({base.width}×{base.height})")
            # 2) versione incorniciata — stessa funzione usata dall'anteprima, quindi identica
            if self.collage_frame_enabled.get() and self._collage_frame_img is not None:
                frame = self._collage_frame_img; fw, fh = frame.size
                framed, _s, _p = self._compose_with_frame(base, frame)
                fname = os.path.splitext(self.combo_cornici_collage.get())[0] or "cornice"
                framed_path = os.path.join(self.output_folder, f"collage_{ts}_{fname}.png")
                framed.save(framed_path, "PNG", optimize=self.optimize_png.get())
                saved.append(f"collage_{ts}_{fname}.png  ({fw}×{fh})")
            # --- testo: concatenazione semplice dei prompt + footer una volta sola ---
            blocks = []
            for i, item in enumerate(self.collage_images, 1):
                comfy = self._comfy_workflow(item["info"])
                if comfy and not item["info"].get("parameters"):
                    # immagine di ComfyUI: il workflow va in un json a parte, numerato
                    jname = f"collage_{ts}_{i}.json"
                    self._write_comfy_json(comfy, os.path.join(self.output_folder, jname))
                    saved.append(jname)
                    blocks.append(f"#{i}\nComfyUI workflow: {jname}")
                    continue
                txt = self.parse_metadata(item["info"], include_footer=False)
                blocks.append(f"#{i}\n{txt}")
            combined = "\n\n".join(blocks)
            footer = self.get_footer_text()
            if footer: combined += (("\n\n" if combined else "") + f"------\n{footer}")
            with open(os.path.join(self.output_folder, f"collage_{ts}.txt"), "w", encoding="utf-8") as f:
                f.write(combined)
            saved.append(f"collage_{ts}.txt")
            messagebox.showinfo("Collage", "Salvato in Output_Pubblicazione:\n• " + "\n• ".join(saved))
        except Exception as e:
            messagebox.showerror("Errore", str(e))

    def process(self):
        try:
            original_size = os.path.getsize(self.current_file_path)
            png_info = PngImagePlugin.PngInfo() if self.keep_metadata.get() else None
            if png_info:
                for k, v in self.info_buffer.items(): png_info.add_text(k, str(v))
            else:
                # Immagine di ComfyUI: si estrae il workflow così com'è, in un .json.
                # Il txt si scrive lo stesso se c'è anche un blocco "parameters" in stile
                # A1111 (alcuni nodi di salvataggio lo aggiungono), altrimenti no: sarebbe
                # solo un "No metadata found." accanto al json.
                comfy = self._comfy_workflow(self.info_buffer)
                if comfy:
                    self._write_comfy_json(comfy, os.path.join(self.output_folder, f"{self.orig_filename}.json"))
                if self.info_buffer.get("parameters") or not comfy:
                    with open(os.path.join(self.output_folder, f"{self.orig_filename}.txt"), "w", encoding="utf-8") as f: f.write(self.parse_metadata(self.info_buffer))
            ow, oh = self.orig_img.size; out_png = self.orig_img.copy()
            if self.state["firma"]["pos"] and self.state["firma"]["visible"] and self.raw_assets["firma"]:
                p, s = self.state["firma"]["pos"], self.state["firma"]["scale"]; px, py = int(p[0]*ow), int(p[1]*oh); sw = int(ow*s)
                asset = self.raw_assets["firma"].resize((sw, int(self.raw_assets["firma"].height*(sw/self.raw_assets["firma"].width))), Image.Resampling.LANCZOS)
                asset = self._signature_alpha(asset, self.signature_opacity.get())
                firma_rotation = self.state["firma"].get("rotation", 0)
                if firma_rotation: asset = asset.rotate(firma_rotation, expand=True, resample=Image.Resampling.BICUBIC)
                out_png.paste(asset, (px, py), asset)
            # --- EXTRA sull'immagine intera: solo quelli con destinazione "immagine" ---
            for ex in self.extras:
                if ex.get("target", "cornice") != "immagine": continue
                if not (ex["pos"] and ex["visible"] and ex.get("img")): continue
                ep, es = ex["pos"], ex["scale"]
                epx, epy = int(ep[0]*ow), int(ep[1]*oh); e_src = ex["img"]; ew = max(1, int(ow*es))
                e_asset = e_src.resize((ew, max(1, int(e_src.height*(ew/e_src.width)))), Image.Resampling.LANCZOS)
                e_rot = ex.get("rotation", 0)
                if e_rot: e_asset = e_asset.rotate(e_rot, expand=True, resample=Image.Resampling.BICUBIC)
                out_png.paste(e_asset, (epx, epy), e_asset)
            # --- TESTI con destinazione "immagine": sul PNG principale, a piena risoluzione ---
            for t in self.texts:
                if not t.get("visible", True) or t.get("target") != "immagine": continue
                self._paste_text_layer(out_png, t, (t["pos"][0] * ow, t["pos"][1] * oh), 1.0)
            cens_suffix = "_censored" if self.mosaic_regions else ""
            acct = f"_{self.current_account_name}" if self.current_account_name else ""
            cid_suffix = f"_{self.custom_id.get().strip()}" if not self.seed_value and self.custom_id.get().strip() else ""
            # --- COPYRIGHT sull'immagine principale ---
            if self.copyright_enabled.get():
                ct = self.get_copyright_text()
                if ct:
                    import textwrap
                    # font_size è in pixel reali sull'immagine salvata — quello che vedi è quello che ottieni
                    font_size = self.copyright_font_size.get()
                    overlay = Image.new("RGBA", out_png.size, (0,0,0,0))
                    draw_ov = ImageDraw.Draw(overlay)
                    try: font_c = ImageFont.truetype("arial.ttf", font_size)
                    except:
                        try: font_c = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", font_size)
                        except: font_c = ImageFont.load_default()
                    # wrap: misura quanti caratteri entrano nel 90% della larghezza reale
                    char_w = draw_ov.textlength("W", font=font_c)
                    ct_wrapped = ct  # nessun wrap, testo su riga singola
                    margin = font_size
                    op = self.copyright_opacity.get()
                    outline_op = max(0, op - 60)
                    bbox = draw_ov.textbbox((0, 0), ct_wrapped, font=font_c)
                    th = bbox[3] - bbox[1]
                    tx_c = margin; ty_c = oh - th - margin
                    for ox, oy in [(-1,0),(1,0),(0,-1),(0,1),(1,1),(-1,1),(1,-1),(-1,-1)]:
                        draw_ov.text((tx_c+ox, ty_c+oy), ct_wrapped, font=font_c, fill=(0,0,0,outline_op))
                    draw_ov.text((tx_c, ty_c), ct_wrapped, font=font_c, fill=(255,255,255,op))
                    out_png = Image.alpha_composite(out_png, overlay)
            final_png = os.path.join(self.output_folder, f"{self.orig_filename}{cens_suffix}{cid_suffix}{acct}.png"); out_png.convert("RGB").save(final_png, "PNG", pnginfo=png_info, optimize=self.optimize_png.get(), compress_level=9 if self.optimize_png.get() else 1)
            if self.state["cornice"]["pos"] and self.state["cornice"]["visible"] and self.raw_assets["cornice"]:
                cp, cs = self.state["cornice"]["pos"], self.state["cornice"]["size"]; cx1, cy1 = int(cp[0]*ow), int(cp[1]*oh); c_side = int(cs*ow); crop = self.orig_img.crop((cx1, cy1, cx1 + c_side, cy1 + c_side)).resize(self.raw_assets["cornice"].size, Image.Resampling.LANCZOS)
                # --- EXTRA (sconto/gratis/badge): incollato SUL RITAGLIO, prima di sovrapporre la cornice ---
                def _paste_extra_on(target_img):
                    for ex in self.extras:
                        # ogni elemento ha la sua destinazione: qui entrano solo quelli
                        # della cornice, gli altri sono già sul PNG principale
                        if ex.get("target", "cornice") != "cornice": continue
                        if not (ex["pos"] and ex["visible"] and ex.get("img")): continue
                        exp, exs = ex["pos"], ex["scale"]; exr, eyr = (exp[0]*ow-cx1)/c_side, (exp[1]*oh-cy1)/c_side
                        if 0<=exr<=1 and 0<=eyr<=1:
                            e_src = ex["img"]; tw = target_img.width; ew = max(1, int(tw*(exs/cs)))
                            e_a = e_src.resize((ew, max(1, int(e_src.height*(ew/e_src.width)))), Image.Resampling.LANCZOS)
                            if ex.get("rotation"): e_a = e_a.rotate(ex["rotation"], expand=True, resample=Image.Resampling.BICUBIC)
                            target_img.paste(e_a, (int(exr*tw), int(eyr*tw)), e_a)
                if self.trama_mode.get():
                    # --- CIRCLE TRAMA MODE ---
                    # Il PNG cornice è un cerchio con solo il bordo (interno trasparente).
                    # Usiamo sempre una ellisse automatica per il ritaglio,
                    # poi sovrapponiamo il bordo PNG e la trama sopra.
                    frame_rgba = self.raw_assets["cornice"]
                    fw, fh = frame_rgba.size
                    crop_rgba = crop.convert("RGBA").resize((fw, fh), Image.Resampling.LANCZOS)
                    # 1) Cerca maschera in Maschere/ dal prefisso della cornice
                    #    es. "cerchio_Adult-F.png" → "Maschere/cerchio.png"
                    sel_cornice = self.combo_cornici.get()
                    prefisso = sel_cornice.split("_")[0] if "_" in sel_cornice else os.path.splitext(sel_cornice)[0]
                    maschera_path = os.path.join(self.folder_maschere, f"{prefisso}.png")
                    if os.path.exists(maschera_path):
                        # Nero=visibile, Bianco=trasparente → inverti e usa come maschera L
                        maschera_img = Image.open(maschera_path).convert("L").resize((fw, fh), Image.Resampling.LANCZOS)
                        circle_mask = maschera_img.point(lambda p: 255 if p < 128 else 0)
                    else:
                        # Fallback: ellisse automatica
                        circle_mask = Image.new("L", (fw, fh), 0)
                        ImageDraw.Draw(circle_mask).ellipse((1, 1, fw - 2, fh - 2), fill=255)
                    social = Image.new("RGBA", (fw, fh), (0, 0, 0, 0))
                    social.paste(crop_rgba, (0, 0), circle_mask)
                    # 1.5) EXTRA sopra al ritaglio, ma prima della cornice/trama
                    _paste_extra_on(social)
                    # 2) Sovrapponi il PNG cornice (bordo) sopra l'immagine ritagliata
                    social = Image.alpha_composite(social, frame_rgba)
                    # 3) Se esiste _trama.png collegato, sovrapponilo sopra tutto
                    if self.raw_assets.get("trama"):
                        trama_res = self.raw_assets["trama"].resize((fw, fh), Image.Resampling.LANCZOS)
                        social = Image.alpha_composite(social, trama_res)
                else:
                    _paste_extra_on(crop)  # EXTRA sopra al ritaglio, sotto alla cornice
                    social = Image.alpha_composite(crop, self.raw_assets["cornice"].convert("RGBA"))
                if self.state["rating"]["pos"] and self.state["rating"]["visible"] and self.raw_assets["rating"]:
                    rp, rs = self.state["rating"]["pos"], self.state["rating"]["scale"]; rx, ry = (rp[0]*ow-cx1)/c_side, (rp[1]*oh-cy1)/c_side
                    if 0<=rx<=1 and 0<=ry<=1:
                        tw = social.width; rw = int(tw*(rs/cs)); r_a = self.raw_assets["rating"].resize((rw, int(self.raw_assets["rating"].height*(rw/self.raw_assets["rating"].width))), Image.Resampling.LANCZOS)
                        rating_rotation = self.state["rating"].get("rotation", 0)
                        if rating_rotation: r_a = r_a.rotate(rating_rotation, expand=True, resample=Image.Resampling.BICUBIC)
                        social.paste(r_a, (int(rx*tw), int(ry*tw)), r_a)
                # --- TESTI con destinazione "cornice": dentro il ritaglio social ---
                # il ritaglio (c_side px originali) viene riscalato alla dimensione della cornice:
                # posizione e corpo del font vanno riportati con lo stesso fattore.
                t_scale = social.width / c_side if c_side else 1.0
                for t in self.texts:
                    if not t.get("visible", True) or t.get("target") != "cornice": continue
                    trx = (t["pos"][0] * ow - cx1) / c_side; tryy = (t["pos"][1] * oh - cy1) / c_side
                    if 0 <= trx <= 1 and 0 <= tryy <= 1:
                        self._paste_text_layer(social, t, (trx * social.width, tryy * social.height), t_scale)
                # --- SEED ID: dentro la cornice (usa pos relativa come rating) ---
                if self.seed_id_visible.get() and self.seed_id_pos_relative:
                    effective_id = self.seed_value or self.custom_id.get().strip()
                    if effective_id:
                        rx, ry = self.seed_id_pos_relative
                        tx_s = int(rx * social.width); ty_s = int(ry * social.height)
                        draw_s = ImageDraw.Draw(social)
                        font_size = int(self.seed_id_font_size.get() / self.base_ratio)
                        try: font_s = ImageFont.truetype("arial.ttf", font_size)
                        except:
                            try: font_s = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSansMono-Bold.ttf", font_size)
                            except: font_s = ImageFont.load_default()
                        label = f"ID: {effective_id}"
                        for ox, oy in [(-1,0),(1,0),(0,-1),(0,1),(1,1),(-1,1),(1,-1),(-1,-1)]:
                            draw_s.text((tx_s+ox, ty_s+oy), label, font=font_s, fill=(0,0,0,220))
                        draw_s.text((tx_s, ty_s), label, font=font_s, fill=(255,255,255,255))
                # nome file cornice: aggiunge nome account/firma se disponibile
                out_name = os.path.join(self.output_folder, f"{self.orig_filename}_{self._frame_export_name()}{acct}" + (".png" if self.trama_mode.get() else ".jpg"))
                if self.trama_mode.get(): social.save(out_name, "PNG", optimize=True)
                else: final_j = Image.new("RGB", social.size, (255,255,255)); final_j.paste(social, mask=social.split()[3]); final_j.save(out_name, "JPEG", quality=95)
            # --- SEED ID: fuori dalla cornice → sull'immagine principale ---
            # RIMOSSO: il seed ID ora funziona come rating, solo dentro la cornice se posizionato
            messagebox.showinfo(self.tr("msg_success_title"), self.tr("msg_success_body"))
        except Exception as e: messagebox.showerror(self.tr("msg_error_title"), str(e))

if __name__ == "__main__":
    if DND_AVAILABLE:
        root = TkinterDnD.Tk()
    else:
        root = tk.Tk()
    app = ImageProcessor(root)
    root.mainloop()
