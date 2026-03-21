#!/usr/bin/env python3
import glob
import json
import os
import re
import sys
import tkinter as tk
from tkinter import ttk, messagebox, filedialog

import pdfplumber  # pip install pdfplumber


# ================== PATH BASE (py + exe) ==================

if getattr(sys, 'frozen', False):
    BASE_DIR = os.path.dirname(sys.executable)          # cartella dell'exe (file utente, PDF)
    BUNDLE_DIR = getattr(sys, '_MEIPASS', BASE_DIR)     # cartella _internal (risorse bundle)
else:
    BASE_DIR = os.path.dirname(os.path.abspath(__file__))
    BUNDLE_DIR = BASE_DIR

# Config: cerca prima accanto all'exe (copia utente), poi nel bundle (_internal)
_config_user = os.path.join(BASE_DIR, "config_bolletta.json")
_config_bundle = os.path.join(BUNDLE_DIR, "config_bolletta.json")
CONFIG_FILE = _config_user if os.path.exists(_config_user) else _config_bundle


# ================== GESTIONE CONFIG ==================

def carica_config(path=CONFIG_FILE):
    if not os.path.exists(path):
        messagebox.showerror("Errore", f"File di configurazione non trovato:\n{path}")
        raise SystemExit(1)
    with open(path, "r", encoding="utf-8") as f:
        cfg = json.load(f)
    # Normalizza booleani da stringa se necessario
    for sezione in ("imposte", "materia_oraria"):
        if sezione in cfg and isinstance(cfg[sezione], dict):
            for k, v in cfg[sezione].items():
                if isinstance(v, str) and v.lower() in ("true", "false"):
                    cfg[sezione][k] = v.lower() == "true"
    return cfg


def salva_config(cfg, path=None):
    # Salva sempre accanto all'exe (copia utente), mai dentro _internal
    if path is None:
        path = os.path.join(BASE_DIR, "config_bolletta.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(cfg, f, indent=4)


# ================== LOGICA DI CALCOLO ==================

def stima_kwh_accisa_da_energia(kwh_energia, soglia_esente=150.0):
    """Restituisce i kWh eccedenti la soglia esente (150 kWh/mese)."""
    return max(0.0, kwh_energia - soglia_esente)


def calcola_accisa(kwh_energia, imposte_cfg):
    """Calcola l'accisa stimando i kWh eccedenti sopra la soglia esenzione."""
    soglia_esente = float(imposte_cfg.get("soglia_esenzione_kwh_mese", 150.0))
    kwh_accisa = stima_kwh_accisa_da_energia(kwh_energia, soglia_esente)
    accisa_euro = kwh_accisa * float(imposte_cfg["accisa_kwh"])
    return accisa_euro, kwh_accisa


def calcola_bolletta(kwh, potenza_kw, applica_bonus, cfg):
    materia_cfg = cfg["materia"]
    trasporto_cfg = cfg["trasporto"]
    oneri_cfg = cfg["oneri"]
    imposte_cfg = cfg["imposte"]
    bonus_mese = cfg["bonus_sociale_mese"]

    iva_aliquota = float(imposte_cfg["iva"])

    # --- energia e perdite ---
    kwh_energia = kwh
    coeff_perdite = float(imposte_cfg.get("coeff_perdite", 0.105))
    kwh_perdite = kwh_energia * coeff_perdite
    kwh_totali = kwh_energia + kwh_perdite

    # --- MATERIA ENERGIA ---
    quota_fissa_materia = float(materia_cfg["quota_fissa_mese"])
    prezzo_materia = float(materia_cfg["prezzo_materia_kwh"])
    prezzo_disp = float(materia_cfg["prezzo_disp_kwh"])
    materia_variabile = kwh_totali * (prezzo_materia + prezzo_disp)
    materia_totale_grezzo = quota_fissa_materia + materia_variabile

    # --- TRASPORTO E GESTIONE CONTATORE ---
    trasporto_quota_energia = kwh_energia * float(trasporto_cfg["quota_energia_kwh"])
    trasporto_quota_fissa = float(trasporto_cfg["quota_fissa_mese"])
    trasporto_quota_potenza = potenza_kw * float(trasporto_cfg["quota_potenza_kw_mese"])
    uc3 = kwh_energia * float(trasporto_cfg["uc3_kwh"])
    uc6_fisso = potenza_kw * float(trasporto_cfg["uc6_fisso_kw_mese"])
    uc6_var = kwh_energia * float(trasporto_cfg["uc6_var_kwh"])

    # --- ONERI DI SISTEMA ---
    arim = kwh_energia * float(oneri_cfg["arim_kwh"])
    asos = kwh_energia * float(oneri_cfg["asos_kwh"])
    oneri_quota_fissa = float(oneri_cfg.get("quota_fissa_mese", 0.0))
    oneri_quota_potenza = potenza_kw * float(oneri_cfg.get("quota_potenza_kw_mese", 0.0))

    # --- ACCISA ---
    accisa, kwh_accisa_usati = calcola_accisa(kwh_energia, imposte_cfg)

    # --- BONUS SOCIALE ---
    bonus = float(bonus_mese) if applica_bonus else 0.0

    # ================== COSTRUZIONE RIGHE FATTURA ==================

    def _riga(cat, imp_grezzo):
        imp_r = round(imp_grezzo, 2)
        iva_r = round(imp_r * iva_aliquota, 2)
        return (cat, imp_r, iva_r)

    righe = [
        _riga("materia", materia_totale_grezzo),
        _riga("trasporto", trasporto_quota_energia),
        _riga("trasporto", trasporto_quota_fissa),
        _riga("trasporto", trasporto_quota_potenza),
        _riga("trasporto", uc3),
        _riga("trasporto", uc6_fisso),
        _riga("trasporto", uc6_var),
    ]

    # Oneri: solo se non nulli
    for cat, imp in [("oneri", arim), ("oneri", asos),
                     ("oneri", oneri_quota_fissa), ("oneri", oneri_quota_potenza)]:
        if abs(imp) >= 1e-9:
            righe.append(_riga(cat, imp))

    righe.append(_riga("imposte", accisa))
    righe.append(_riga("bonus", bonus))

    # ================== AGGREGAZIONE PER CATEGORIA ==================

    categorie = ("materia", "trasporto", "oneri", "imposte", "bonus")
    tot_cat_imp = {c: 0.0 for c in categorie}
    tot_cat_iva = {c: 0.0 for c in categorie}

    for cat, imp_r, iva_r in righe:
        tot_cat_imp[cat] += imp_r
        tot_cat_iva[cat] += iva_r

    imponibile_totale = sum(imp for _, imp, _ in righe)
    iva_tot_dettaglio = sum(iva_r for _, _, iva_r in righe)
    iva_globale = round(imponibile_totale * iva_aliquota, 2)
    totale = imponibile_totale + iva_globale

    # --- PERCENTUALI COMPONENTI (senza bonus) ---
    imponibile_senza_bonus = sum(tot_cat_imp[c] for c in ("materia", "trasporto", "oneri", "imposte"))
    iva_senza_bonus = sum(tot_cat_iva[c] for c in ("materia", "trasporto", "oneri", "imposte"))
    totale_senza_bonus = imponibile_senza_bonus + iva_senza_bonus

    componenti = {
        "materia": tot_cat_imp["materia"],
        "trasporto": tot_cat_imp["trasporto"],
        "oneri": tot_cat_imp["oneri"],
        "imposte": tot_cat_imp["imposte"] + tot_cat_iva["imposte"],
    }

    percentuali = {
        k: round(v / totale_senza_bonus * 100, 1) if totale_senza_bonus > 0 else 0.0
        for k, v in componenti.items()
    }

    return {
        "materia": round(tot_cat_imp["materia"], 2),
        "trasporto": round(tot_cat_imp["trasporto"], 2),
        "oneri": round(tot_cat_imp["oneri"], 2),
        "accisa": round(tot_cat_imp["imposte"], 2),
        "bonus": round(tot_cat_imp["bonus"], 2),
        "iva": iva_globale,
        "totale": round(totale, 2),
        "percentuali": percentuali,
        "kwh_accisa": round(kwh_accisa_usati, 2),
        "kwh_perdite": round(kwh_perdite, 2),
        "iva_dettaglio": round(iva_tot_dettaglio, 2),
        "imponibile_totale": round(imponibile_totale, 2),
    }


# ================== PARSING BOLLETTA PDF ==================

def estrai_testo_da_pdf(path_pdf: str) -> str:
    testo = ""
    with pdfplumber.open(path_pdf) as pdf:
        for page in pdf.pages:
            page_text = page.extract_text() or ""
            testo += page_text + "\n"
    return testo


def pulisci_testo_ricalcoli(testo: str) -> str:
    righe = testo.splitlines()
    parole_escluse = ("ricalcolo", "conguaglio", "rateizzazione", "ricostruzione")
    righe_filtrate = [
        r for r in righe
        if not any(kw in r.lower() for kw in parole_escluse)
    ]
    return "\n".join(righe_filtrate)


def _estrai_valore(testo, pattern):
    """Cerca un pattern nel testo e restituisce il primo gruppo come float."""
    m = re.search(pattern, testo, flags=re.DOTALL)
    if not m:
        return None
    num_str = m.group(1).strip().replace(".", "").replace(",", ".")
    try:
        return float(num_str)
    except ValueError:
        return None


def parse_correspettivi_da_testo(testo: str) -> dict:
    risultato = {}

    mapping = [
        (r"Trasporto quota energia\s+[\d]+\s+([\d,\.]+)\s*€/kWh", "trasporto.quota_energia_kwh"),
        (r"Componente ARIM.*?\s+[\d]+\s+([\d,\.]+)\s*€/kWh", "oneri.arim_kwh"),
        (r"Componente ASOS.*?\s+[\d]+\s+([\d,\.]+)\s*€/kWh", "oneri.asos_kwh"),
        (r"Imposta erariale.*?\s+[\d]+\s+([\d,\.]+)\s*€/kWh", "imposte.accisa_kwh"),
        (r"Bonus sociale\s+[\d]+\s+(-?[\d,\.]+)\s*€/PdP", "bonus_sociale_mese"),
    ]

    for pattern, chiave in mapping:
        v = _estrai_valore(testo, pattern)
        if v is not None:
            risultato[chiave] = v

    return risultato


def parse_riepilogo_bolletta(testo: str) -> dict:
    """Estrae dati di riepilogo dalla bolletta Octopus: totale, periodo, kWh, fattura."""
    riepilogo = {}

    # Numero fattura elettronica (es: KE-26-ED403532-003)
    m = re.search(
        r"(?:NUMERO\s+FATTURA\s+ELETTRONICA.*?|fattura\s+elettronica.*?numero[:\s]*)"
        r"([\w\-]+\-\d+)",
        testo, re.IGNORECASE
    )
    if m:
        riepilogo["numero_fattura"] = m.group(1).strip()

    # Periodo di riferimento (es: "dal 01/02/2026 al 28/02/2026")
    m = re.search(
        r"PERIODO\s+DI\s+RIFERIMENTO[:\s]*dal\s+"
        r"(\d{1,2}/\d{1,2}/\d{4})\s+al\s+(\d{1,2}/\d{1,2}/\d{4})",
        testo, re.IGNORECASE
    )
    if m:
        riepilogo["periodo_da"] = m.group(1)
        riepilogo["periodo_a"] = m.group(2)

    # Totale bolletta (es: "TOTALE BOLLETTA -19,42 €" o "TOTALE BOLLETTA 45,30 €")
    m = re.search(
        r"TOTALE\s+BOLLETTA\s+(-?[\d.,]+)\s*€",
        testo, re.IGNORECASE
    )
    if m:
        num_str = m.group(1).replace(".", "").replace(",", ".")
        try:
            riepilogo["totale_euro"] = float(num_str)
        except ValueError:
            pass

    # kWh consumati (es: "CONSUMO FATTURATO: 178 kWh")
    m = re.search(
        r"CONSUMO\s+FATTURATO[:\s]*([\d.,]+)\s*kWh",
        testo, re.IGNORECASE
    )
    if m:
        num_str = m.group(1).replace(".", "").replace(",", ".")
        try:
            riepilogo["kwh_consumati"] = float(num_str)
        except ValueError:
            pass

    # Data fattura (es: "DATA FATTURA: 10/03/2026")
    m = re.search(r"DATA\s+FATTURA[:\s]*(\d{1,2}/\d{1,2}/\d{4})", testo)
    if m:
        riepilogo["data_fattura"] = m.group(1)

    return riepilogo


def analizza_bolletta_pdf(path_pdf: str) -> dict:
    testo = estrai_testo_da_pdf(path_pdf)
    testo = pulisci_testo_ricalcoli(testo)
    return parse_correspettivi_da_testo(testo)


def analizza_bolletta_completa(path_pdf: str) -> dict:
    """Estrae sia i corrispettivi che il riepilogo della bolletta."""
    testo = estrai_testo_da_pdf(path_pdf)
    testo_pulito = pulisci_testo_ricalcoli(testo)
    corrispettivi = parse_correspettivi_da_testo(testo_pulito)
    riepilogo = parse_riepilogo_bolletta(testo)
    return {**riepilogo, "corrispettivi": corrispettivi}


def trova_bollette_pdf(directory: str) -> list:
    """Cerca file fattura-*.pdf nella directory, ordinati per data modifica (più recenti prima)."""
    pattern = os.path.join(directory, "fattura-*.pdf")
    files = glob.glob(pattern)
    # Ordina per data di modifica (più recente prima)
    files.sort(key=lambda f: os.path.getmtime(f), reverse=True)
    return files


def confronta_config_con_bolletta(cfg: dict, nuovi: dict, tolleranza=1e-6):
    differenze = []
    for chiave, valore_nuovo in nuovi.items():
        parti = chiave.split(".")
        try:
            if len(parti) == 2:
                sezione, campo = parti
                valore_vecchio = float(cfg[sezione][campo])
            else:
                valore_vecchio = float(cfg[chiave])
        except KeyError:
            differenze.append({
                "chiave": chiave,
                "vecchio": None,
                "nuovo": float(valore_nuovo),
            })
            continue

        if valore_vecchio is None or abs(valore_vecchio - float(valore_nuovo)) > tolleranza:
            differenze.append({
                "chiave": chiave,
                "vecchio": valore_vecchio,
                "nuovo": float(valore_nuovo),
            })

    return differenze


# ================== HELPER GUI ==================

def centra_finestra(finestra, parent):
    """Centra una finestra rispetto al parent."""
    finestra.update_idletasks()
    pw, ph = parent.winfo_width(), parent.winfo_height()
    px, py = parent.winfo_x(), parent.winfo_y()
    w, h = finestra.winfo_width(), finestra.winfo_height()
    finestra.geometry(f"+{px + (pw - w) // 2}+{py + (ph - h) // 2}")


def formatta_info_tariffa(materia_cfg):
    """Genera la stringa info tariffa dall'oggetto materia config."""
    return (
        f"Materia: {float(materia_cfg['prezzo_materia_kwh']):.3f} €/kWh  |  "
        f"Disp./cap.: {float(materia_cfg['prezzo_disp_kwh']):.3f} €/kWh  |  "
        f"Quota fissa: {float(materia_cfg['quota_fissa_mese']):.2f} €/mese"
    )


# ================== COLORI TEMA ==================

COLORI = {
    "bg": "#f5f6fa",
    "header_bg": "#2c3e50",
    "header_fg": "#ecf0f1",
    "accent": "#2980b9",
    "accent_hover": "#3498db",
    "totale_bg": "#27ae60",
    "totale_fg": "#ffffff",
    "bonus_fg": "#e74c3c",
    "testo": "#2c3e50",
    "testo_sub": "#7f8c8d",
    "separator": "#bdc3c7",
    "tree_alt": "#eaf2f8",
    "tree_sel": "#d5e8f0",
}


# ================== GUI ==================

class ConfigWindow(tk.Toplevel):
    def __init__(self, master, cfg, on_save):
        super().__init__(master)
        self.title("⚙  Impostazioni bolletta")
        self.cfg = cfg
        self.on_save = on_save
        self.configure(bg=COLORI["bg"])

        frame = ttk.Frame(self, padding=12)
        frame.grid(row=0, column=0, sticky="nsew")

        self.entries = {}
        row = 0
        for section, values in cfg.items():
            lbl = ttk.Label(frame, text=section.upper(), font=("Segoe UI", 9, "bold"))
            lbl.grid(row=row, column=0, columnspan=2, sticky="w", pady=(8, 2))
            row += 1
            if isinstance(values, dict):
                for key, val in values.items():
                    ttk.Label(frame, text=key).grid(row=row, column=0, sticky="w", padx=(8, 0))
                    var = tk.StringVar(value=str(val))
                    ent = ttk.Entry(frame, textvariable=var, width=15)
                    ent.grid(row=row, column=1, sticky="w", padx=(5, 0), pady=1)
                    self.entries[(section, key)] = var
                    row += 1
            else:
                ttk.Label(frame, text=section).grid(row=row, column=0, sticky="w", padx=(8, 0))
                var = tk.StringVar(value=str(values))
                ent = ttk.Entry(frame, textvariable=var, width=15)
                ent.grid(row=row, column=1, sticky="w", padx=(5, 0), pady=1)
                self.entries[(None, section)] = var
                row += 1

        btn_frame = ttk.Frame(frame)
        btn_frame.grid(row=row, column=0, columnspan=2, pady=(12, 0), sticky="e")
        ttk.Button(btn_frame, text="Annulla", command=self.destroy).grid(row=0, column=0, padx=5)
        ttk.Button(btn_frame, text="💾 Salva", command=self.save).grid(row=0, column=1, padx=5)

        self.resizable(False, False)
        centra_finestra(self, master)

    def save(self):
        for (section, key), var in self.entries.items():
            value_str = var.get().strip().replace(",", ".")
            # Gestisci booleani
            if value_str.lower() in ("true", "false"):
                value = value_str.lower() == "true"
            else:
                try:
                    value = float(value_str)
                except ValueError:
                    value = value_str

            if section is None:
                self.cfg[key] = value
            else:
                self.cfg[section][key] = value

        self.on_save(self.cfg)
        self.destroy()


class DifferenzeWindow(tk.Toplevel):
    def __init__(self, master, differenze, on_apply):
        super().__init__(master)
        self.title("📋 Variazioni trovate nella nuova bolletta")
        self.differenze = differenze
        self.on_apply = on_apply
        self.configure(bg=COLORI["bg"])

        frame = ttk.Frame(self, padding=12)
        frame.grid(row=0, column=0, sticky="nsew")

        cols = ("aggiorna", "chiave", "vecchio", "nuovo")
        self.tree = ttk.Treeview(frame, columns=cols, show="headings", height=10)
        self.tree.heading("aggiorna", text="Agg.")
        self.tree.heading("chiave", text="Voce")
        self.tree.heading("vecchio", text="Vecchio")
        self.tree.heading("nuovo", text="Nuovo")

        self.tree.column("aggiorna", width=40, anchor="center")
        self.tree.column("chiave", width=220)
        self.tree.column("vecchio", width=90, anchor="e")
        self.tree.column("nuovo", width=90, anchor="e")

        self.tree.grid(row=0, column=0, sticky="nsew")

        self.check_vars = {}
        for diff in differenze:
            chiave = diff["chiave"]
            vecchio = "" if diff["vecchio"] is None else f"{diff['vecchio']:.6f}"
            nuovo = f"{diff['nuovo']:.6f}"
            item_id = self.tree.insert("", "end", values=("", chiave, vecchio, nuovo))
            self.check_vars[item_id] = tk.BooleanVar(value=True)

        self.tree.bind("<Double-1>", self.on_double_click)

        btn_frame = ttk.Frame(frame)
        btn_frame.grid(row=1, column=0, pady=(10, 0), sticky="e")
        ttk.Button(btn_frame, text="Annulla", command=self.destroy).grid(row=0, column=0, padx=5)
        ttk.Button(btn_frame, text="✅ Applica", command=self.apply).grid(row=0, column=1, padx=5)

        frame.rowconfigure(0, weight=1)
        frame.columnconfigure(0, weight=1)
        self.mostra_check()

        self.resizable(False, False)
        centra_finestra(self, master)

    def mostra_check(self):
        for item_id, var in self.check_vars.items():
            self.tree.set(item_id, "aggiorna", "☑" if var.get() else "☐")

    def on_double_click(self, event):
        item_id = self.tree.identify_row(event.y)
        if item_id in self.check_vars:
            var = self.check_vars[item_id]
            var.set(not var.get())
            self.mostra_check()

    def apply(self):
        selezionate = []
        for item_id, var in self.check_vars.items():
            if var.get():
                values = self.tree.item(item_id, "values")
                chiave = values[1]
                selezionate.append(chiave)
        self.on_apply(selezionate, self.differenze)
        self.destroy()


class BollettaGUI:
    def __init__(self, root):
        self.root = root
        self.root.title("⚡ Calcolatore bolletta luce - Octopus")
        self.root.resizable(False, False)
        self.root.configure(bg=COLORI["bg"])

        # Tema e font
        style = ttk.Style(self.root)
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass

        default_font = ("Segoe UI", 10)
        self.root.option_add("*Font", default_font)

        # Configura stili personalizzati
        style.configure("TFrame", background=COLORI["bg"])
        style.configure("TLabel", background=COLORI["bg"], foreground=COLORI["testo"])
        style.configure("Header.TLabel", background=COLORI["header_bg"],
                        foreground=COLORI["header_fg"], font=("Segoe UI", 12, "bold"),
                        padding=(12, 8))
        style.configure("Sub.TLabel", foreground=COLORI["testo_sub"], font=("Segoe UI", 9))
        style.configure("Accent.TButton", font=("Segoe UI", 10, "bold"))

        style.configure("Treeview.Heading", font=("Segoe UI", 9, "bold"),
                        background=COLORI["accent"], foreground="white")
        style.configure("Treeview", rowheight=24, font=("Segoe UI", 10),
                        fieldbackground=COLORI["bg"])
        style.map("Treeview", background=[("selected", COLORI["tree_sel"])])

        style.configure("Storico.Treeview.Heading", font=("Segoe UI", 9, "bold"),
                        background="#8e44ad", foreground="white")

        self.config = carica_config()

        # ================== LAYOUT PRINCIPALE ==================

        # Header
        header_frame = tk.Frame(root, bg=COLORI["header_bg"], padx=12, pady=10)
        header_frame.grid(row=0, column=0, sticky="ew")
        tk.Label(
            header_frame,
            text="⚡ Simulatore bolletta luce – Octopus Fissa 12M",
            font=("Segoe UI", 13, "bold"),
            bg=COLORI["header_bg"], fg=COLORI["header_fg"]
        ).pack(side="left")

        # Main content
        main = ttk.Frame(root, padding=14)
        main.grid(row=1, column=0, sticky="nsew")

        # --- Input kWh ---
        input_frame = ttk.LabelFrame(main, text="  📊  Dati consumo  ", padding=10)
        input_frame.grid(row=0, column=0, columnspan=3, sticky="ew", pady=(0, 8))

        ttk.Label(input_frame, text="Consumo mensile (kWh energia):").grid(
            row=0, column=0, sticky="w")
        self.kwh_var = tk.StringVar()
        kwh_entry = ttk.Entry(input_frame, textvariable=self.kwh_var, width=10,
                              font=("Segoe UI", 11))
        kwh_entry.grid(row=0, column=1, sticky="w", padx=(8, 0))
        kwh_entry.focus_set()

        self.lbl_kwh_accisa = ttk.Label(input_frame, text="", style="Sub.TLabel")
        self.lbl_kwh_accisa.grid(row=0, column=2, sticky="w", padx=(14, 0))

        ttk.Label(input_frame, text="Potenza impegnata (kW):").grid(
            row=1, column=0, sticky="w", pady=(4, 0))
        self.potenza_var = tk.StringVar(value="3")
        ttk.Entry(input_frame, textvariable=self.potenza_var, width=10,
                  font=("Segoe UI", 11)).grid(
            row=1, column=1, sticky="w", padx=(8, 0), pady=(4, 0))

        self.lbl_kwh_perdite = ttk.Label(input_frame, text="", style="Sub.TLabel")
        self.lbl_kwh_perdite.grid(row=1, column=2, sticky="w", padx=(14, 0), pady=(4, 0))

        # Bonus
        self.bonus_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(
            input_frame,
            text="Applica bonus sociale",
            variable=self.bonus_var
        ).grid(row=2, column=0, columnspan=3, sticky="w", pady=(6, 0))

        # Info rapida tariffa
        self.lbl_info = ttk.Label(input_frame,
                                  text=formatta_info_tariffa(self.config["materia"]),
                                  style="Sub.TLabel")
        self.lbl_info.grid(row=3, column=0, columnspan=3, sticky="w", pady=(6, 0))

        # Pulsante calcolo
        calcola_btn = ttk.Button(main, text="🔍  Calcola stima bolletta",
                                 command=self.on_calcola, style="Accent.TButton")
        calcola_btn.grid(row=1, column=0, columnspan=3, pady=(4, 8), sticky="ew")

        # --- Tabella risultati ---
        risultati_frame = ttk.LabelFrame(main, text="  💰  Risultato stima  ", padding=6)
        risultati_frame.grid(row=2, column=0, columnspan=3, sticky="nsew", pady=(0, 8))

        self.tree = ttk.Treeview(
            risultati_frame,
            columns=("voce", "importo"),
            show="headings",
            height=8
        )
        self.tree.heading("voce", text="Voce")
        self.tree.heading("importo", text="Importo (€)")
        self.tree.column("voce", width=240)
        self.tree.column("importo", width=110, anchor="e")
        self.tree.grid(row=0, column=0, sticky="nsew")

        # Tag per riga totale e bonus
        self.tree.tag_configure("totale", background=COLORI["totale_bg"],
                                foreground=COLORI["totale_fg"],
                                font=("Segoe UI", 10, "bold"))
        self.tree.tag_configure("bonus", foreground=COLORI["bonus_fg"])
        self.tree.tag_configure("alt", background=COLORI["tree_alt"])

        risultati_frame.columnconfigure(0, weight=1)

        # Label percentuali
        self.lbl_percent = ttk.Label(main, text="", style="Sub.TLabel", wraplength=500)
        self.lbl_percent.grid(row=3, column=0, columnspan=3, sticky="w", pady=(0, 4))

        # --- Separatore ---
        ttk.Separator(main, orient="horizontal").grid(
            row=4, column=0, columnspan=3, sticky="ew", pady=6)

        # --- Storico bollette ---
        storico_frame = ttk.LabelFrame(main, text="  📄  Storico ultime bollette  ", padding=6)
        storico_frame.grid(row=5, column=0, columnspan=3, sticky="nsew")

        self.tree_storico = ttk.Treeview(
            storico_frame,
            columns=("file", "periodo", "kwh", "totale"),
            show="headings",
            height=4
        )
        self.tree_storico.heading("file", text="Fattura")
        self.tree_storico.heading("periodo", text="Periodo")
        self.tree_storico.heading("kwh", text="kWh")
        self.tree_storico.heading("totale", text="Totale €")
        self.tree_storico.column("file", width=180)
        self.tree_storico.column("periodo", width=130, anchor="center")
        self.tree_storico.column("kwh", width=60, anchor="e")
        self.tree_storico.column("totale", width=80, anchor="e")
        self.tree_storico.grid(row=0, column=0, sticky="nsew")

        self.tree_storico.tag_configure("alt", background=COLORI["tree_alt"])

        storico_frame.columnconfigure(0, weight=1)

        main.columnconfigure(1, weight=1)

        # ================== MENU ==================
        menubar = tk.Menu(root)

        menu_file = tk.Menu(menubar, tearoff=0)
        menu_file.add_command(label="⚙  Impostazioni...", command=self.apri_impostazioni)
        menu_file.add_command(label="📄  Importa bolletta (PDF)...",
                              command=self.importa_bolletta_pdf)
        menu_file.add_command(label="🔄  Aggiorna storico bollette",
                              command=self.carica_storico_bollette)
        menu_file.add_separator()
        menu_file.add_command(label="Esci", command=root.quit)
        menubar.add_cascade(label="File", menu=menu_file)

        menu_help = tk.Menu(menubar, tearoff=0)
        menu_help.add_command(label="Guida rapida", command=self.mostra_guida)
        menubar.add_cascade(label="Guida", menu=menu_help)

        menu_info = tk.Menu(menubar, tearoff=0)
        menu_info.add_command(label="Informazioni su...", command=self.mostra_info)
        menubar.add_cascade(label="Info", menu=menu_info)

        root.config(menu=menubar)

        # Invio = calcola
        self.root.bind("<Return>", lambda event: self.on_calcola())

        # Carica storico all'avvio
        self.carica_storico_bollette()

    # ---- Helper UI ----

    def _aggiorna_info_tariffa(self):
        """Aggiorna la label info tariffa dalla config corrente."""
        self.lbl_info.config(text=formatta_info_tariffa(self.config["materia"]))

    # ---- Storico bollette ----

    def carica_storico_bollette(self):
        """Scansiona i PDF nella directory e popola la tabella storico."""
        for row in self.tree_storico.get_children():
            self.tree_storico.delete(row)

        pdf_files = trova_bollette_pdf(BASE_DIR)
        if not pdf_files:
            self.tree_storico.insert("", "end",
                                     values=("Nessuna bolletta trovata", "", "", ""))
            return

        for idx, pdf_path in enumerate(pdf_files[:5]):  # max 5 bollette
            nome_file = os.path.basename(pdf_path)
            # Estrai nome leggibile dal filename
            nome_display = nome_file.replace("fattura-", "").replace(".pdf", "")

            try:
                dati = analizza_bolletta_completa(pdf_path)
                periodo = ""
                if "periodo_da" in dati and "periodo_a" in dati:
                    periodo = f"{dati['periodo_da']} – {dati['periodo_a']}"

                kwh = f"{dati['kwh_consumati']:.0f}" if "kwh_consumati" in dati else "–"
                totale = f"{dati['totale_euro']:.2f}" if "totale_euro" in dati else "–"
            except Exception:
                periodo = "errore lettura"
                kwh = "–"
                totale = "–"

            tag = ("alt",) if idx % 2 == 1 else ()
            self.tree_storico.insert("", "end",
                                     values=(nome_display, periodo, kwh, totale),
                                     tags=tag)

    # ---- Impostazioni ----

    def apri_impostazioni(self):
        def on_save(new_cfg):
            self.config = new_cfg
            salva_config(self.config)
            messagebox.showinfo("Salvato", "Configurazione aggiornata e salvata.")
            self._aggiorna_info_tariffa()

        ConfigWindow(self.root, self.config, on_save)

    # ---- Import PDF ----

    def importa_bolletta_pdf(self):
        path = filedialog.askopenfilename(
            title="Seleziona una bolletta PDF",
            filetypes=[("PDF", "*.pdf")]
        )
        if not path:
            return

        try:
            nuovi = analizza_bolletta_pdf(path)
        except Exception as e:
            messagebox.showerror("Errore", f"Errore durante la lettura del PDF:\n{e}")
            return

        if not nuovi:
            messagebox.showwarning("Attenzione", "Nessuna voce riconosciuta nella bolletta.")
            return

        differenze = confronta_config_con_bolletta(self.config, nuovi)
        if not differenze:
            messagebox.showinfo("Info",
                                "Nessuna variazione trovata rispetto alla configurazione attuale.")
            return

        def applica_selezionate(chiavi_selezionate, tutte_diff):
            mappa_diff = {d["chiave"]: d for d in tutte_diff}
            for chiave in chiavi_selezionate:
                diff = mappa_diff[chiave]
                parti = chiave.split(".")
                valore_nuovo = diff["nuovo"]
                if len(parti) == 2:
                    sezione, campo = parti
                    self.config.setdefault(sezione, {})[campo] = valore_nuovo
                else:
                    self.config[chiave] = valore_nuovo

            salva_config(self.config)
            messagebox.showinfo("Aggiornato",
                                "Configurazione aggiornata dai valori della bolletta.")
            self._aggiorna_info_tariffa()

        DifferenzeWindow(self.root, differenze, applica_selezionate)

    # ---- Guida & Info ----

    def mostra_guida(self):
        testo = (
            "Questo programma stima la bolletta della luce a partire dal consumo mensile in kWh.\n\n"
            "FUNZIONAMENTO:\n"
            "- Usa i corrispettivi presenti nelle bollette Octopus Fissa 12M (materia, trasporto,\n"
            "  oneri, imposte, bonus sociale), configurati nel file config_bolletta.json.\n"
            "- Inserisci il consumo mensile (kWh) e la potenza impegnata: il software calcola\n"
            "  spesa materia energia, trasporto e gestione contatore, oneri di sistema,\n"
            "  imposte (accisa + IVA) e applica il bonus sociale se selezionato.\n"
            "- L'opzione 'Importa bolletta (PDF)...' permette di leggere una bolletta Octopus e\n"
            "  aggiornare automaticamente alcuni corrispettivi proponendo le variazioni trovate.\n"
            "- La sezione Storico mostra in basso i dati estratti dalle bollette PDF trovate\n"
            "  nella cartella dell'applicazione.\n\n"
            "LIMITI:\n"
            "- Il risultato è una stima realistica basata sui parametri correnti; piccoli scostamenti\n"
            "  rispetto alla bolletta reale possono dipendere da arrotondamenti e aggiornamenti ARERA.\n"
        )
        messagebox.showinfo("Guida rapida", testo)

    def mostra_info(self):
        testo = (
            "Calcolatore Bolletta Luce - Octopus\n"
            "Versione: 2.0.0\n"
            "© Frank1980 - Home Computing - 2026\n\n"
            "Software per uso personale per stimare l'importo della bolletta elettrica\n"
            "a partire dai consumi mensili, usando i corrispettivi indicati nelle bollette\n"
            "Octopus e nella relativa documentazione contrattuale.\n\n"
            "Licenza: uso personale. Verifica sempre i risultati con le bollette ufficiali "
            "del tuo fornitore prima di prendere decisioni economiche.\n"
        )
        messagebox.showinfo("Informazioni", testo)

    # ---- Calcolo ----

    def on_calcola(self):
        try:
            kwh = float(self.kwh_var.get().replace(",", "."))
        except ValueError:
            messagebox.showerror("Errore", "Inserisci un valore numerico valido per i kWh.")
            return

        try:
            potenza_kw = float(self.potenza_var.get().replace(",", "."))
        except ValueError:
            messagebox.showerror("Errore",
                                 "Inserisci un valore numerico valido per la potenza (kW).")
            return

        if kwh < 0:
            messagebox.showerror("Errore", "I kWh devono essere >= 0.")
            return
        if potenza_kw <= 0:
            messagebox.showerror("Errore", "La potenza deve essere > 0.")
            return

        risultati = calcola_bolletta(
            kwh,
            potenza_kw=potenza_kw,
            applica_bonus=self.bonus_var.get(),
            cfg=self.config
        )

        # Aggiorna config con il nuovo accisa_kwh_max stimato
        kwh_accisa = risultati.get("kwh_accisa", 0.0)
        try:
            self.config.setdefault("imposte", {})
            self.config["imposte"]["accisa_kwh_max"] = float(kwh_accisa)
            salva_config(self.config)
        except Exception as e:
            print("Errore salvataggio accisa_kwh_max:", e)

        # Aggiorna label kWh accisa e perdite
        self.lbl_kwh_accisa.config(
            text=f"kWh tassati accisa: {kwh_accisa:.2f}"
        )
        self.lbl_kwh_perdite.config(
            text=f"kWh perdite stimate: {risultati.get('kwh_perdite', 0.0):.2f}"
        )

        # Reset tabella
        for row in self.tree.get_children():
            self.tree.delete(row)

        ordine_voci = ["materia", "trasporto", "oneri", "accisa", "bonus", "iva", "totale"]
        etichette = {
            "materia": "Spesa materia energia",
            "trasporto": "Trasporto e contatore",
            "oneri": "Oneri di sistema",
            "accisa": "Imposte (accisa)",
            "bonus": "Bonus sociale",
            "iva": "IVA",
            "totale": "TOTALE BOLLETTA",
        }

        for idx, voce in enumerate(ordine_voci):
            if voce == "totale":
                tag = ("totale",)
            elif voce == "bonus":
                tag = ("bonus",)
            elif idx % 2 == 1:
                tag = ("alt",)
            else:
                tag = ()

            self.tree.insert(
                "",
                "end",
                values=(etichette[voce], f"{risultati[voce]:.2f}"),
                tags=tag
            )

        perc = risultati.get("percentuali")
        if perc:
            txt = (
                f"📊 Composizione (senza bonus) – "
                f"Materia: {perc['materia']}%  •  "
                f"Trasporto: {perc['trasporto']}%  •  "
                f"Oneri: {perc['oneri']}%  •  "
                f"Imposte: {perc['imposte']}%"
            )
            self.lbl_percent.config(text=txt)
        else:
            self.lbl_percent.config(text="")


if __name__ == "__main__":
    root = tk.Tk()
    app = BollettaGUI(root)
    root.mainloop()
